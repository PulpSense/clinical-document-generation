"""Durable, explicit storage retention. No cleanup is performed on import.

Forecasts allocate only future bytes, and keep all pending audit evidence.
Deletion is opt-in, serialized with the installer's directory flock. This is
not a hostile-writer sandbox: stopped workers and cooperative writers are a
precondition, with inode/hash rechecks detecting accidental interference.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import time


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def sha(path):
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def safe_path(path):
    path = Path(os.path.abspath(path))
    require(path.resolve() == path, 'Linked or aliased path: ' + str(path))
    return path


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save(path, value):
    import uuid
    path = safe_path(path)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.pending')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(canonical(value) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        sync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink()


def entry(path, relative, *, owned=True):
    before = path.lstat()
    require(not owned or before.st_uid == os.getuid(), 'Not an owned entry: ' + str(path))
    row = {'path': relative, 'dev': before.st_dev, 'ino': before.st_ino,
           'mode': stat.S_IMODE(before.st_mode), 'allocated_bytes': before.st_blocks * 512}
    if stat.S_ISLNK(before.st_mode):
        row.update(type='symlink', target=os.readlink(path))
    elif stat.S_ISDIR(before.st_mode):
        row.update(type='dir')
    elif stat.S_ISREG(before.st_mode):
        row.update(type='file', bytes=before.st_size, sha256=sha(path))
    else:
        raise ValueError('Unsupported entry: ' + str(path))
    after = path.lstat()
    if row['type'] != 'dir':
        row.update(mtime_ns=before.st_mtime_ns, ctime_ns=before.st_ctime_ns)
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_mode)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_mode), 'Entry changed during inventory')
    return row


def inventory(root):
    root = safe_path(root)
    rows = [entry(root, '.')]
    require(rows[0]['type'] == 'dir', 'Not a directory')
    def fail(error):
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=fail):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            rows.append(entry(path, path.relative_to(root).as_posix()))
    return sorted(rows, key=lambda row: row['path'])


def validate_inventory(rows):
    from pathlib import PurePosixPath
    names = set()
    for row in rows:
        name = row['path']
        p = PurePosixPath(name)
        require(name == '.' or (bool(p.parts) and not p.is_absolute() and '..' not in p.parts
                and str(p) == name and '\\' not in name), 'Unsafe inventory path')
        require(name not in names, 'Duplicate inventory path')
        names.add(name)
    require('.' in names, 'Missing root inventory')


def inventory_from_record(journal):
    return json.loads(Path(journal).read_text())['inventory']


def stopped_references(root):
    """Inspect actual argv, cwd, environment and FDs for owned live workers.

    Inaccessible foreign/root processes are explicitly not evidence about owned
    workers. An inaccessible owned process fails closed. No shell-string search.
    """
    require(Path('/proc').is_dir(), 'Process proof unavailable')
    root = safe_path(root)
    checked = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            def inside(value):
                return value.startswith('/') and Path(value).is_relative_to(root)
            argv = proc.joinpath('cmdline').read_bytes().split(b'\0')
            env = proc.joinpath('environ').read_bytes().split(b'\0')
            require(not any(inside(os.fsdecode(v)) for v in argv), 'Live process argv references target')
            require(not any(inside(os.fsdecode(v).partition('=')[2]) for v in env), 'Live process environment references target')
            for link in [proc / 'cwd', *proc.joinpath('fd').iterdir()]:
                try:
                    value = os.readlink(link).removesuffix(' (deleted)')
                except FileNotFoundError:
                    continue
                require(not inside(value), 'Live process cwd/fd references target')
            checked.append(int(proc.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as exc:
            raise ValueError('Owned process proof unavailable: ' + proc.name) from exc
    return {'owned_pids_checked': checked, 'foreign_processes': 'excluded; not claimed inspected'}


def retire_tree(root, journal, expected, *, protected, hook=lambda phase: None):
    root = safe_path(root)
    with directory_lock(root.parent):
        return _retire_tree(root, journal, expected, protected=protected, hook=hook)


def _retire_tree(root, journal, expected, *, protected, hook=lambda phase: None):
    """Exact allowlist deletion with durable per-entry crash reconciliation.

    Caller holds the owning transaction lock and proves eligibility. Every
    entry is hashed before any deletion, then rechecked before unlink. A crash
    after unlink but before the completion write is reconciled from intent.
    """
    root, journal = safe_path(root), safe_path(journal)
    protected = [safe_path(path) for path in protected]
    require(all(not root.is_relative_to(p) and not p.is_relative_to(root) for p in protected), 'Protected root overlap')
    require(not journal.is_relative_to(root), 'Journal inside deletion target')
    require(bool(expected) and expected[0]['path'] == '.', 'Missing full inventory')
    validate_inventory(expected)
    if journal.exists():
        record = json.loads(journal.read_text())
        require(record['root'] == str(root) and record['inventory'] == expected, 'Retirement inventory mismatch')
        if record['state'] == 'retired':
            require(not root.exists() and not root.is_symlink(), 'Retired path recreated')
            sync_dir(root.parent)
            return record
    else:
        require(inventory(root) == expected, 'Retirement inventory mismatch')
        process_proof = stopped_references(root)
        record = {'schema_version': 'storage-retirement/v1', 'root': str(root),
                  'inventory': expected, 'state': 'retiring', 'done': [], 'pending': None,
                  'process_proof': process_proof, 'started_at_epoch': time.time()}
        save(journal, record)
        hook('intent_durable')
    # Validate the entire remaining namespace before resuming or changing modes.
    if root.exists():
        actual = {r['path']: r for r in inventory(root)}
        wanted = {r['path']: r for r in expected if r['path'] not in record['done']}
        if record['pending'] and record['pending'] not in actual:
            wanted.pop(record['pending'], None)
        require(set(actual) == set(wanted), 'Retirement remaining inventory changed')
        for name, current in actual.items():
            original = wanted[name]
            if current['type'] == 'dir' and current['mode'] == original['mode'] | stat.S_IWUSR:
                current['mode'] = original['mode']
            # Directory allocated blocks may shrink as entries disappear.
            if current['type'] == 'dir':
                current['allocated_bytes'] = original['allocated_bytes']
            require(current == original, 'Retirement remaining inventory changed')
        stopped_references(root)
    else:
        require(record['pending'] == '.' or '.' in record['done'], 'Target disappeared without durable intent')
        sync_dir(root.parent)
    for row in sorted(expected, key=lambda r: (len(Path(r['path']).parts), r['path']), reverse=True):
        name = row['path']
        if name in record['done']:
            continue
        path = root if name == '.' else root / name
        if not path.exists() and not path.is_symlink():
            require(record['pending'] == name, 'Missing entry without durable intent')
            sync_dir(path.parent)
        else:
            require(path.parent.resolve() == path.parent, 'Deletion parent alias changed')
            current = entry(path, name)
            if row['type'] == 'dir':
                require(current['mode'] in (row['mode'], row['mode'] | stat.S_IWUSR), 'Directory mode changed')
                current['mode'] = row['mode']
                current['allocated_bytes'] = row['allocated_bytes']
            require(current == row, 'Deletion entry inventory changed')
            record['pending'] = name
            save(journal, record)
            hook('entry_intent')
            # Recheck after durable intent; no namespace mutation before it.
            again = entry(path, name)
            if row['type'] == 'dir':
                require(again['mode'] in (row['mode'], row['mode'] | stat.S_IWUSR), 'Directory mode changed')
                again['mode'] = row['mode']
                again['allocated_bytes'] = row['allocated_bytes']
            require(again == row, 'Deletion entry inventory changed after intent')
            parent = path.parent
            parent_mode = stat.S_IMODE(parent.lstat().st_mode)
            require(parent.lstat().st_uid == os.getuid(), 'Unowned deletion parent')
            if parent != root.parent:
                parent.chmod(parent_mode | stat.S_IWUSR)
            if row['type'] == 'dir':
                path.rmdir()
            else:
                path.unlink()
            sync_dir(parent)
            hook('entry_removed')
        record['done'].append(name)
        record['pending'] = None
        save(journal, record)
    record.update(state='retired', completed_at_epoch=time.time())
    save(journal, record)
    require(not root.exists() and not root.is_symlink(), 'Retirement readback failed')
    return record


def duplicate_tree_index(root, retained):
    """Every disposable member must have an exact retained counterpart."""
    root, retained = safe_path(root), safe_path(retained)
    require(not root.is_relative_to(retained) and not retained.is_relative_to(root), 'Aliased duplicate source')
    rows = inventory(root)
    source = []
    for row in rows:
        target = retained if row['path'] == '.' else retained / row['path']
        require(target.parent.resolve() == target.parent, 'Linked retained parent')
        require(target.exists() or target.is_symlink(), 'Unique duplicate member')
        other = entry(target, row['path'], owned=False)
        for key in ('type', 'mode', 'bytes', 'sha256', 'target'):
            require(row.get(key) == other.get(key), 'Unique or changed duplicate member: ' + row['path'])
        source.append(other)
    return {'root': str(root), 'retained': str(retained), 'inventory': rows, 'source_index': source}


def directory_lock(root):
    """Use the same directory inode lock as the external installer."""
    from contextlib import contextmanager
    import fcntl
    @contextmanager
    def locked():
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)
    return locked()


def cleanup_completed_workers(run, state_path, copies):
    """Only exact bin/skills duplicates in completed private workers are eligible.

    Sessions, databases/WAL, logs, model caches, tool responses, request/usage
    metadata and all render/native/approved-source evidence remain untouched.
    Unknown worker data is never treated as disposable. Caller explicitly maps
    each copy to an existing retained source. No shared-profile symlinks added.
    """
    run, state_path = safe_path(run), safe_path(state_path)
    require(state_path.is_relative_to(run), 'Foreign operation state')
    state_hash = sha(state_path)
    state = json.loads(state_path.read_text())
    require(state.get('status') in {'passed', 'blocked', 'timeout', 'review_required'}, 'Operation is not terminal')
    records = run / 'storage-retention'
    records.mkdir(exist_ok=True)
    results = []
    with directory_lock(run):
        for root, retained in copies:
            root, retained = safe_path(root), safe_path(retained)
            cache = root.parent
            require(root.name in {'bin', 'skills'}, 'Not a disposable worker class')
            require(cache.parent == run / '.hermes-cache' or
                (cache.parent.name == 'visual-review-observers' and cache.is_relative_to(run / 'revisions')),
                'Not a private operation worker')
            stopped_references(cache)
            name = hashlib.sha256(str(root).encode()).hexdigest()
            proof_path, deletion_path = records / (name + '-source.json'), records / (name + '-deletion.json')
            if proof_path.exists():
                proof = json.loads(proof_path.read_text())
                require(proof['root'] == str(root) and proof['retained'] == str(retained), 'Changed duplicate mapping')
            else:
                proof = duplicate_tree_index(root, retained)
                proof['operation_state_sha256'] = state_hash
                save(proof_path, proof)
            require(sha(state_path) == proof['operation_state_sha256'], 'Operation state changed')
            # Recheck retained counterpart hashes/identity before every invocation.
            for row in proof['source_index']:
                target = retained if row['path'] == '.' else retained / row['path']
                require(entry(target, row['path'], owned=False) == row, 'Retained duplicate source changed')
            protected = [retained, state_path, proof_path]
            results.append(retire_tree(root, deletion_path, proof['inventory'], protected=protected))
    return {'status': 'passed', 'retired': results,
            'preserved': 'all unique operation evidence, mutable worker state and pending audit images'}


def retire_duplicate_catalog(path, retained, journal):
    """Exact redundant model catalog only, never actual model/session/usage state."""
    path, retained, journal = map(safe_path, (path, retained, journal))
    require(path != retained and path.name == retained.name == 'models_dev_cache.json', 'Not a redundant model catalog')
    with directory_lock(path.parent):
        stopped_references(path.parent)
        stopped_references(retained.parent)
        if journal.exists():
            record = json.loads(journal.read_text())
            require(record['path'] == str(path) and record['retained'] == str(retained), 'Foreign catalog record')
        else:
            duplicate, source = entry(path, '.'), entry(retained, '.')
            require(duplicate['type'] == source['type'] == 'file' and
                all(duplicate[k] == source[k] for k in ('bytes', 'sha256', 'mode')), 'Unique model catalog')
            record = {'state':'retiring', 'path':str(path), 'retained':str(retained),
                'inventory':duplicate, 'source':source}
            save(journal, record)
        require(entry(retained, '.') == record['source'], 'Retained model catalog changed')
        if path.exists():
            require(record['state'] == 'retiring' and entry(path, '.') == record['inventory'], 'Catalog identity changed')
            path.unlink()
        else:
            require(record['state'] in {'retiring', 'retired'}, 'Missing unjournaled catalog')
        sync_dir(path.parent)
        record['state'] = 'retired'
        save(journal, record)
        require(not path.exists(), 'Catalog retirement readback failed')
        return record


def tree_content_sha(rows):
    """Content identity excludes allocation/inode metadata, not modes or links."""
    ignored = {'dev', 'ino', 'allocated_bytes', 'mtime_ns', 'ctime_ns'}
    content = [{k: v for k, v in row.items() if k not in ignored} for row in rows]
    return hashlib.sha256(canonical(content)).hexdigest()


def completed_operation_cleanup(run, state_path):
    """Discover duplicate-only private copies, retaining one exact local source.

    Does not modify worker provisioning or tool permissions. Bin/skills trees
    with unique bytes remain intact; this intentionally keeps the first copy.
    """
    run = safe_path(run)
    state_path = safe_path(state_path)
    require(state_path.is_relative_to(run) and json.loads(state_path.read_text()).get('status')
        in {'passed','blocked','timeout','review_required'}, 'Operation is not terminal')
    roots = sorted((run / '.hermes-cache').glob('*'))
    observer_results = []
    for revision in sorted((run / 'revisions').glob('*')):
        if revision.is_dir() and not revision.is_symlink() and (revision / 'hermes/visual-review-observers').is_dir():
            observer_results.extend(cleanup_stopped_observer_assets(revision)['retired'])
    copies = []
    seen = {}
    records = run / 'storage-retention'
    for record in sorted(records.glob('*-source.json')):
        proof = json.loads(record.read_text())
        deletion = record.with_name(record.name.replace('-source.json', '-deletion.json'))
        retained = safe_path(proof['retained'])
        require(retained.parent in roots and retained.name in {'bin', 'skills'}, 'Foreign retained worker anchor')
        for row in proof['source_index']:
            target = retained if row['path'] == '.' else retained / row['path']
            require(entry(target, row['path'], owned=False) == row, 'Retained worker anchor changed')
        seen[(retained.name, tree_content_sha(proof['source_index']))] = retained
        if not deletion.exists() or json.loads(deletion.read_text()).get('state') != 'retired':
            copies.append((Path(proof['root']), retained))
    pending = {root for root, _ in copies}
    for worker in roots:
        if worker.is_symlink() or not worker.is_dir():
            continue
        for name in ('bin', 'skills'):
            root = worker / name
            if not root.is_dir() or root.is_symlink() or root in pending:
                continue
            rows = inventory(root)
            key = (name, tree_content_sha(rows))
            if key in seen and seen[key] != root:
                copies.append((root, seen[key]))
            else:
                seen[key] = root
    result = cleanup_completed_workers(run, state_path, copies)
    result['retired'].extend(observer_results)
    # Cache catalogs are byte-identical duplicates, not actual configured model
    # identity or session/tool evidence. Preserve one full original catalog and
    # bind every removed copy to it; unique catalogs always remain.
    catalogs = {}
    with directory_lock(run):
        state_hash = sha(state_path)
        for record_path in sorted(records.glob('*-catalog.json')):
            record = json.loads(record_path.read_text())
            target, source = Path(record['path']), Path(record['retained'])
            require(target.parent in roots and source.parent in roots, 'Foreign catalog worker')
            row = entry(source, '.')
            require(row == record['source'], 'Retained catalog anchor changed')
            catalogs[(row['sha256'], row['bytes'], row['mode'])] = source
            if record['state'] != 'retired':
                retire_duplicate_catalog(target, source, record_path)
        for worker in roots:
            if worker.is_symlink() or not worker.is_dir():
                continue
            path = worker / 'models_dev_cache.json'
            if not path.is_file() or path.is_symlink():
                continue
            row = entry(path, '.')
            key = (row['sha256'], row['bytes'], row['mode'])
            if key in catalogs and catalogs[key] != path:
                require(sha(state_path) == state_hash, 'Operation changed during catalog cleanup')
                record_path = records / (hashlib.sha256(str(path).encode()).hexdigest() + '-catalog.json')
                result['retired'].append(retire_duplicate_catalog(path, catalogs[key], record_path))
            else:
                catalogs[key] = path
    return result


def cleanup_stopped_observer_assets(revision):
    """End-of-wave duplicate cleanup, before another observer wave allocates.

    A terminal direct-worker diagnostic, immutable request/provenance binding,
    exited launch identity and absence of owned process references are required.
    No mutable session/log/request/response/usage state or images are selected.
    """
    revision = safe_path(revision)
    root = revision / 'hermes/visual-review-observers'
    if not root.is_dir():
        return {'status':'passed', 'retired':[]}
    records = root.parent / 'observer-storage-retention'
    records.mkdir(exist_ok=True)
    workers = []
    with directory_lock(root):
        for worker in sorted(root.iterdir()):
            if worker.is_symlink() or not worker.is_dir():
                continue
            diagnostic = worker / 'diagnostic.json'
            if not diagnostic.is_file() or diagnostic.is_symlink():
                continue
            data = json.loads(diagnostic.read_text())
            if type(data.get('returncode')) is not int:
                continue
            launch = json.loads((worker / 'launch.json').read_text())
            require(type(launch['pid']) is int and launch['pid'] > 0 and str(launch['start_ticks']).isdigit(), 'Invalid observer launch identity')
            proc = Path('/proc') / str(launch['pid']) / 'stat'
            try:
                current_ticks = proc.read_text().rsplit(')',1)[1].split()[19]
                require(current_ticks != str(launch['start_ticks']), 'Observer process still live')
            except FileNotFoundError:
                pass
            provenance = json.loads((worker / 'provenance.json').read_text())
            request = safe_path(revision / data['request_path'])
            require(request.is_relative_to(revision) and launch['request_path'] == data['request_path']
                and provenance['request_path'] == data['request_path'] and sha(request) == provenance['request_sha256'],
                'Observer request/provenance changed')
            require((worker / 'state.db').is_file(), 'Required observer session state missing')
            stopped_references(worker)
            workers.append(worker)
        results = []
        # Resume exact plans before discovering more completed duplicates.
        for path in sorted(records.glob('*-source.json')):
            proof = json.loads(path.read_text())
            copy, source = Path(proof['root']), Path(proof['retained'])
            require(copy.parent in workers and source.parent in workers, 'Unfinished or foreign observer duplicate')
            for row in proof['source_index']:
                target = source if row['path'] == '.' else source / row['path']
                require(entry(target, row['path'], owned=False) == row, 'Observer retained source changed')
            deletion = path.with_name(path.name.replace('-source.json','-deletion.json'))
            results.append(retire_tree(copy, deletion, proof['inventory'], protected=[source]))
        for name in ('bin','skills','models_dev_cache.json'):
            seen = {}
            anchors = [Path(json.loads(p.read_text())['retained']) for p in records.glob('*-source.json')]
            anchors += [Path(json.loads(p.read_text())['retained']) for p in records.glob('*-catalog.json')]
            for anchor in anchors:
                if anchor.name != name or anchor.parent not in workers:
                    continue
                if name == 'models_dev_cache.json':
                    row = entry(anchor, '.')
                    key = (row['bytes'],row['sha256'],row['mode'])
                else:
                    rows = inventory(anchor)
                    content = [{k:v for k,v in row.items() if k not in {'dev','ino','allocated_bytes','mtime_ns','ctime_ns'}} for row in rows]
                    key = hashlib.sha256(canonical(content)).hexdigest()
                seen[key] = anchor
            for worker in workers:
                path = worker / name
                if not path.exists() or path.is_symlink():
                    continue
                if name == 'models_dev_cache.json':
                    row = entry(path, '.')
                    key = (row['bytes'],row['sha256'],row['mode'])
                else:
                    rows = inventory(path)
                    content = [{k:v for k,v in row.items() if k not in {'dev','ino','allocated_bytes','mtime_ns','ctime_ns'}} for row in rows]
                    key = hashlib.sha256(canonical(content)).hexdigest()
                if key not in seen:
                    seen[key] = path
                    continue
                source = seen[key]
                if source == path:
                    continue
                token = hashlib.sha256(str(path).encode()).hexdigest()
                if name == 'models_dev_cache.json':
                    results.append(retire_duplicate_catalog(path, source, records / (token+'-catalog.json')))
                else:
                    proof = duplicate_tree_index(path, source)
                    save(records / (token+'-source.json'), proof)
                    results.append(retire_tree(path, records / (token+'-deletion.json'), proof['inventory'], protected=[source]))
        return {'status':'passed','retired':results}


def archive_duplicate_index(archive, retained, *, generated_index_path=None, strip_prefix=None):
    import zipfile
    from pathlib import PurePosixPath
    archive, retained = safe_path(archive), safe_path(retained)
    before = entry(archive, '.')
    members = []
    generated_index = None
    seen = set()
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        require(len(infos) <= 20000 and sum(i.file_size for i in infos) <= 512 * 1024 * 1024
                and all(i.file_size <= 64 * 1024 * 1024 for i in infos), 'Archive exceeds verification bounds')
        require(z.testzip() is None, 'Archive CRC failure')
        for info in infos:
            p = PurePosixPath(info.filename)
            require(bool(p.parts) and not p.is_absolute() and '..' not in p.parts
                    and ':' not in info.filename and '\\' not in info.filename,
                    'Unsafe archive member')
            require(str(p) not in seen, 'Duplicate archive member')
            seen.add(str(p))
            if strip_prefix is not None:
                require(strip_prefix == 'clinical-document-generation' and p.parts[0] == strip_prefix, 'Wrong release archive prefix')
                p = PurePosixPath(*p.parts[1:])
            require(stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR), 'Unsafe archive member type')
            target = retained / p
            if str(p) == 'diagnostic-inventory.json' and not target.exists() and generated_index_path is not None:
                require(info.file_size <= 16 * 1024 * 1024, 'Generated diagnostic index too large')
                raw = z.read(info)
                require(isinstance(json.loads(raw), dict), 'Invalid generated diagnostic index')
                generated_index = {'member': str(p), 'bytes': len(raw),
                    'sha256': hashlib.sha256(raw).hexdigest(), 'retained_path': str(safe_path(generated_index_path))}
                # Sole archive-only index is preserved exactly, not reconstructed.
                target = safe_path(generated_index_path)
                if target.exists():
                    require(target.read_bytes() == raw, 'Conflicting retained generated index')
                else:
                    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                    sync_dir(target.parent)
                continue
            require(target.resolve() == target and not target.is_symlink(), 'Linked archive member source')
            if info.is_dir():
                require(target.is_dir(), 'Missing retained directory member')
                continue
            require(target.is_file(), 'Missing retained member: ' + str(p))
            digest = hashlib.sha256()
            with z.open(info) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            observed = entry(target, str(p), owned=False)
            require(observed['bytes'] == info.file_size and observed['sha256'] == digest.hexdigest(), 'Changed retained member')
            members.append(observed)
    require(entry(archive, '.') == before, 'Archive changed during verification')
    return {'archive': str(archive), 'retained': str(retained), 'archive_inventory': before,
            'members': members, 'generated_index': generated_index}


def retire_duplicate_archive(archive, retained, journal, *, strip_prefix=None):
    archive, retained, journal = map(safe_path, (archive, retained, journal))
    require(not journal.is_relative_to(archive), 'Archive journal overlaps')
    with directory_lock(archive.parent):
        if journal.exists():
            proof = json.loads(journal.read_text())
            require(proof['archive'] == str(archive) and proof['retained'] == str(retained), 'Foreign archive record')
        else:
            proof = archive_duplicate_index(archive, retained,
                generated_index_path=journal.with_name(journal.name + '.diagnostic-inventory.json'), strip_prefix=strip_prefix)
            proof['strip_prefix'] = strip_prefix
            proof['state'] = 'retiring'
            save(journal, proof)
        for row in proof['members']:
            require(entry(retained / row['path'], row['path'], owned=False) == row, 'Retained member changed')
        if proof.get('generated_index'):
            index = proof['generated_index']
            target = safe_path(index['retained_path'])
            require(target.stat().st_size == index['bytes'] and sha(target) == index['sha256'], 'Retained generated index changed')
        if archive.exists():
            require(entry(archive, '.') == proof['archive_inventory'], 'Archive identity changed')
            stopped_references(archive)
            archive.unlink()
        else:
            require(proof['state'] in {'retiring', 'retired'}, 'Unjournaled missing archive')
        sync_dir(archive.parent)
        proof['state'] = 'retired'
        save(journal, proof)
        require(not archive.exists(), 'Archive deletion readback failed')
        return proof


def source_recovery(repo, release_identity):
    """Prove the exact commit exists and is reachable on the live origin."""
    import re
    import subprocess
    repo = safe_path(repo)
    commit = release_identity['git_commit']
    require(re.fullmatch('[0-9a-f]{40}', commit) is not None, 'Invalid recovery commit')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], timeout=60).decode().strip()
    require(git('rev-parse', commit + '^{commit}') == commit, 'Recovery commit unavailable')
    origin = git('remote', 'get-url', 'origin')
    require(bool(origin), 'Missing verified origin')
    remote = git('ls-remote', '--heads', 'origin')
    reachable = []
    for line in remote.splitlines():
        head, ref = line.split()
        if subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', commit, head],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30).returncode == 0:
            reachable.append({'ref': ref, 'commit': head})
    require(bool(reachable), 'Recovery commit not reachable on live origin')
    require((repo / 'scripts/workflow.py').is_file(), 'Ordinary packager unavailable')
    return {'identity': release_identity, 'origin': origin, 'reachable_refs': reachable,
        'verified_at_epoch': time.time(), 'local_rollback_available': False,
        'instructions': ['Fetch the recorded origin and verify the full commit and ancestry.',
            'Create a clean detached worktree or git archive of the recorded commit.',
            'Run CLINICAL_PYTHON scripts/workflow.py --package-release <archive> from the clean committed worktree.',
            'Verify package manifest commit/fingerprint equals the recorded prior identity.',
            'Use the independently reviewed installer and repeat staged/active/render/host/callback gates.']}


def validate_storage_forecast(forecast):
    """Validate observed allocations, explained scope and disjoint populations.

    Reused observations may describe distinct future populations (one retained
    canonical copy and three concurrent workers), not the same allocation twice
    in one population. Reasons remain estimates, not measured future peaks.
    """
    observations = {}
    for row in forecast.get('evidence_inventory', []):
        path = safe_path(row['path'])
        require(path.is_file() and sha(path) == row['sha256'], 'Storage observation changed')
        try:
            data = json.loads(path.read_text())
        except ValueError as exc:
            raise ValueError('Invalid storage observation JSON') from exc
        require(data.get('schema_version') == 'storage-allocation-observation/v1', 'Unsupported storage observation')
        require(type(data.get('measured_at_epoch')) in (int, float) and bool(data.get('scope')), 'Missing observation scope')
        entries = data['inventory']
        validate_inventory(entries)
        require(all(type(r.get('allocated_bytes')) is int and r['allocated_bytes'] >= 0 for r in entries), 'Invalid observed allocation')
        require(sum(r['allocated_bytes'] for r in entries) == data['allocated_bytes'], 'Observation allocation mismatch')
        require(data['inventory_sha256'] == hashlib.sha256(canonical(entries)).hexdigest(), 'Observation inventory changed')
        require(inventory(safe_path(data['root'])) == entries, 'Observed allocation source changed')
        require(row['sha256'] not in observations, 'Duplicate storage observation')
        observations[row['sha256']] = {r['path']: r for r in entries}
    require(bool(observations), 'Missing storage observations')
    def amount(terms, seen):
        require(bool(terms), 'Missing component observation terms')
        total = 0
        for term in terms:
            digest = term['observation_sha256']
            require(digest in observations, 'Foreign component observation')
            require(type(term['copies']) is int and term['copies'] > 0, 'Invalid component population')
            require(len(term.get('rationale', '').strip()) >= 20 and bool(term.get('population')), 'Missing component justification')
            paths = term['paths']
            require(bool(paths) and len(paths) == len(set(paths)), 'Missing or duplicate allocation paths')
            for name in paths:
                require(name in observations[digest], 'Unknown allocation path')
                allocation = observations[digest][name]
                key = (allocation['dev'], allocation['ino'], allocation['type'], term['population'])
                require(key not in seen, 'Double-counted component allocation')
                seen.add(key)
            total += sum(observations[digest][p]['allocated_bytes'] for p in paths) * term['copies']
        return total
    require(len(forecast.get('comparability', '').strip()) >= 40, 'Missing comparable-workload scope')
    for case in forecast['cases']:
        seen = set()
        for key in ('retained_bytes', 'worker_peak_bytes', 'scratch_peak_bytes'):
            require(case[key] > 0 and case[key] == amount(case['component_terms'][key], seen), 'Unsupported component estimate')
    margin = forecast['margin_basis']
    raw = amount(margin['terms'], set())
    quantum = margin['rounding_quantum_bytes']
    require(type(quantum) is int and quantum > 0 and len(margin.get('rationale', '').strip()) >= 40, 'Missing defensible margin basis')
    require(raw > 0 and forecast['margin_bytes'] == ((raw + quantum - 1) // quantum) * quantum, 'Unsupported margin estimate')
    return observations


def sequential_admission(path, cases, *, margin_bytes, available_bytes=None):
    """Conservative sequential high-water forecast, including future retention.

    Every case supplies disjoint retained, worker-wave and scratch allowances.
    Earlier cases' retained evidence accumulates; worker waves do not. Physical
    available space is sampled on every call, including with fixture overrides.
    """
    usage = shutil.disk_usage(path)
    require(type(margin_bytes) is int and margin_bytes >= 0, 'Invalid margin')
    require(bool(cases), 'Missing storage forecast')
    retained = 0
    peaks = []
    ids = set()
    for case in cases:
        require(case['case_id'] not in ids, 'Duplicate case forecast')
        ids.add(case['case_id'])
        for key in ('retained_bytes', 'worker_peak_bytes', 'scratch_peak_bytes'):
            require(type(case[key]) is int and case[key] >= 0, 'Invalid storage component')
        retained += case['retained_bytes']
        peaks.append(retained + case['worker_peak_bytes'] + case['scratch_peak_bytes'] + margin_bytes)
    available = usage.free if available_bytes is None else available_bytes
    require(type(available) is int and available >= 0, 'Invalid available bytes')
    required = peaks[0]
    return {'measured_at_epoch': time.time(), 'baseline_used_bytes': usage.used,
        'available_bytes': available, 'required_available_bytes': required,
        'forecast_sequence_peak_bytes': max(peaks),
        'admission_scope': 'next case only; measure again before every sequential case',
        'missing_capacity_bytes': max(0, required - available), 'admitted': available >= required,
        'case_peaks': peaks, 'cases': cases, 'margin_bytes': margin_bytes,
        'method': 'future retained growth plus one concurrent worker wave and scratch; existing used files excluded'}
