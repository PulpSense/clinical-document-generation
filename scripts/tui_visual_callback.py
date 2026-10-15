#!/usr/bin/env python3
"""Genuine configured Hermes visual observer behind the executable callback.

This helper receives existing bound requests only; it cannot generate clinical
packages or grant an approval. Every returned judgment comes from a real model.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys
import time
import uuid

import quality
import workflow
from visual_review import run_visual_review, visual_review_unit_result, _read, _write


def callback_admission(path: Path) -> tuple[dict, Path, float]:
    request = _read(path)
    revision = Path(request['revision_path'])
    if (request.get('schema_version') != 'desktop-parent-visual-review-request/v1'
            or not revision.is_absolute() or revision.is_symlink()
            or revision.name != request.get('revision_id') or not path.resolve().is_relative_to(revision.resolve())):
        raise ValueError('Callback admission: foreign revision/request')
    configuration = request.get('configuration', {})
    base = {k: configuration.get(k) for k in workflow.CERTIFIED_HERMES_CONFIGURATION}
    if (base != workflow.CERTIFIED_HERMES_CONFIGURATION
            or set(configuration) - set(base) - {'layout_preservation_notes'}):
        raise ValueError('Callback admission: configuration differs from governed configured-model policy')
    deadline = datetime.fromisoformat(request['callback_deadline_utc'])
    if deadline.tzinfo is None:
        raise ValueError('Callback admission: deadline lacks timezone')
    remaining = min(480.0, float(request['remaining_seconds']),
        (deadline - datetime.now(timezone.utc)).total_seconds())
    if remaining <= 2.0:
        raise ValueError('Callback admission: persisted remaining deadline expired')
    if request.get('managed_hermes_identity') != workflow._managed_hermes_identity():
        raise ValueError('Callback admission: managed Hermes launcher/interpreter changed')
    if request.get('callback_release_binding'):
        from visual_review import callback_release_binding
        binding = callback_release_binding(Path(__file__).parent.parent)
        if (request['callback_release_binding'] != binding
                or request.get('callback_command') != {'path': str(Path(__file__).with_name('tui_visual_callback')),
                    'sha256': binding['source_sha256']['scripts/tui_visual_callback']}):
            raise ValueError('Callback admission: installed source/command identity differs')
    request['_invocation_path'] = str(path)
    request['_invocation_sha256'] = quality.sha256_file(path)
    return request, revision, remaining


def observer_metadata(state: Path, revision: Path, unit: dict) -> dict:
    """Whitelisted real session/tool evidence; never export credentials or prompts."""
    database = state / 'state.db'
    if database.is_symlink() or not database.is_file():
        raise ValueError('No genuine observer session metadata was recorded')
    connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=1)
    try:
        sessions = connection.execute('SELECT id, model FROM sessions').fetchall()
        if len(sessions) != 1 or not all(isinstance(v, str) and v.strip() for v in sessions[0]):
            raise ValueError('Observer session/model identity is missing or ambiguous')
        session_id, model_id = sessions[0]
        calls = {}
        for (raw,) in connection.execute("SELECT tool_calls FROM messages WHERE session_id=? AND role='assistant' AND tool_calls IS NOT NULL", (session_id,)):
            for call in json.loads(raw):
                function = call.get('function', call)
                if function.get('name') not in {'vision_analyze', 'read_file'}:
                    continue
                arguments = function.get('arguments', {})
                if isinstance(arguments, str): arguments = json.loads(arguments)
                image = Path(arguments.get('image_url') or arguments.get('path') or '')
                if not image.is_absolute(): image = revision / image
                calls[call['id']] = None if call['id'] in calls else (function['name'], image.resolve(), arguments)
        tools = []
        inspected = set()
        native_reads = []
        read_coverage = {}
        results = connection.execute(
            "SELECT tool_call_id, tool_name, content, timestamp FROM messages WHERE session_id=? AND role='tool'", (session_id,)).fetchall()
        counts = {}
        for call_id, _, _, _ in results:
            counts[call_id] = counts.get(call_id, 0) + 1
        for call_id, returned_name, raw, stamp in results:
            if not calls.get(call_id) or counts[call_id] != 1:
                continue
            name, image, arguments = calls[call_id]
            if returned_name != name:
                continue
            region = arguments.get('region')
            try:
                value = json.loads(raw)
            except (ValueError, TypeError):
                # Hermes persists native multimodal tool results as their text
                # projection, not the auxiliary JSON success envelope. This
                # exact runtime result indicates pixels attached to the main
                # model; it is access evidence, NOT a visual-quality judgment.
                native_prefix = 'Image loaded into your context — you can see it natively now. Use your built-in vision to answer the user.'
                value = {'success': True, 'native_vision': True} if name == 'vision_analyze' and isinstance(raw, str) and raw.startswith(native_prefix) else {}
            if name == 'read_file':
                if (not isinstance(value, dict) or 'error' in value or value.get('success') is False
                        or not isinstance(value.get('content'), str)
                        or type(value.get('total_lines')) is not int or value['total_lines'] < 1
                        or not image.is_relative_to(revision.resolve())):
                    continue
                total = value['total_lines']
                # Count only numbered lines actually delivered. EOF/truncation
                # flags and model full-read claims establish no coverage.
                lines = [int(m.group(1)) for m in re.finditer(r'(?m)^(\d+)\|', value['content'])]
                offset = arguments.get('offset', 1)
                limit = arguments.get('limit', 2000)
                if (type(offset) is not int or type(limit) is not int
                        or offset < 1 or limit < 1 or not lines
                        or lines != sorted(set(lines))
                        or lines[0] != offset or lines[-1] > min(total, offset + limit - 1)):
                    continue
                key = str(image)
                coverage = read_coverage.setdefault(key, {'total_lines': total, 'lines': set(), 'contradictory': False})
                if coverage['total_lines'] != total:
                    coverage['contradictory'] = True
                coverage['lines'].update(lines)
                ranges = []
                for line in lines:
                    if ranges and line == ranges[-1][1] + 1:
                        ranges[-1][1] = line
                    else:
                        ranges.append([line, line])
                native_reads.append({'path': key, 'tool_call_id': call_id, 'timestamp': stamp,
                    'returned_line_ranges': ranges, 'total_lines': total,
                    'result_sha256': __import__('hashlib').sha256(raw.encode()).hexdigest()})
                continue
            if (not isinstance(value, dict) or value.get('success') is not True
                    or 'error' in value or region is not None):
                continue
            if not image.is_relative_to(revision.resolve()):
                continue
            relative = image.relative_to(revision.resolve()).as_posix()
            expected = {p['path']: p['sha256'] for t in unit['visual_scope'] for p in t['pages']}
            if relative not in expected or quality.sha256_file(image) != expected[relative]:
                continue
            inspected.add(relative)
            tools.append({'tool': 'vision_analyze', 'tool_call_id': call_id, 'timestamp': stamp,
                'page_path': relative, 'sha256': expected[relative], 'success': True,
                'transport': 'native_main_model_image_attachment' if value.get('native_vision') else 'configured_auxiliary_image_analysis',
                'result_sha256': __import__('hashlib').sha256(raw.encode()).hexdigest()})
        required_native = {str((revision / a['docx']).resolve()) for a in unit['artifacts']}
        if unit.get('document_evidence'):
            required_native.add(str((revision / unit['document_evidence']['path']).resolve()))
        baseline_bindings_valid = True
        if any(t.get('kind') == 'document' for t in unit['visual_scope']):
            for baseline in unit.get('template_baseline_evidence', []):
                path = revision / baseline['path']
                required_native.add(str(path.resolve()))
                if (not quality._revision_owned_nonsymlink_path(revision, path)
                        or not path.is_file() or quality.sha256_file(path) != baseline['sha256']):
                    baseline_bindings_valid = False
        complete_reads = {p for p, c in read_coverage.items()
            if not c['contradictory'] and len(c['lines']) == c['total_lines']}
        return {'session_id': session_id, 'model_id': model_id, 'image_tool_results': tools,
            'native_read_results': native_reads,
            'request_inspection_complete': bool(unit.get('request_id')) and str((revision / f"hermes/visual-review-requests/{unit['request_id']}.json").resolve()) in complete_reads,
            'native_inspection_complete': baseline_bindings_valid and required_native <= complete_reads,
            'inspected_paths': sorted(inspected), 'state_path': str(state),
            'database_sha256': quality.sha256_file(database),
            'provenance_sha256': quality.sha256_file(state / 'provenance.json') if (state / 'provenance.json').is_file() else None,
            'usage': workflow._production_worker_usage(state),
            'identity_source': 'actual configured Hermes session and successful bound vision tool results'}
    finally:
        connection.close()


def _retain_observer_bytes(revision: Path, target: Path, raw: bytes) -> None:
    """Retain exact transport bytes with the existing revision mutation guards."""
    if not quality._revision_owned_nonsymlink_path(revision, target):
        raise ValueError('Observer diagnostic must be revision-owned and nonsymlinked')
    quality._assert_safe_mutation_path(target.parent, directory=True)
    quality._assert_safe_mutation_path(target, directory=False)
    if target.exists():
        if target.read_bytes() != raw:
            raise ValueError('Retained observer transport bytes changed')
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    quality._assert_safe_mutation_path(target, directory=False)
    target.write_bytes(raw)


def _observer_feedback(revision: Path, unit: dict, channel: str, issue: str) -> None:
    path = revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json"
    ledger = _read(path)
    feedback = {'category': 'transport', 'issue': issue,
        'target_ids': [t['target_id'] for t in unit['visual_scope']], 'channel': channel}
    rows = ledger.setdefault('observer_transport_feedback', [])
    if feedback not in rows:
        rows.append(feedback)
    validation = ledger.setdefault('validation_feedback', [])
    if feedback not in validation:
        validation.append(feedback)
    _write(revision, path, ledger)


def _observer_binding(unit: dict, response: dict) -> None:
    """Authenticate raw outer identity before host attestation or filtering."""
    if (response.get('schema_version') != quality.RESPONSE_SCHEMA
            or any(response.get(k) != unit[k] for k in ('request_id', 'request_sha256', 'task', 'revision_id'))
            or not isinstance(response.get('producer'), dict)
            or any(not isinstance(response['producer'].get(k), str) or not response['producer'][k].strip()
                for k in ('model_id', 'reviewer_id'))):
        raise ValueError('Observer raw response mandatory identity/binding rejected')


def _observer_stdout_frames(text: str) -> list[tuple[object, bytes]]:
    """Locate original byte slices; only the shared strict framer grants values.

    This lexical walk does not decode or salvage JSON. In particular, a broken
    outer container owns its nested bytes, including after mismatched brackets.
    """
    frames = []
    stack = []
    quoted = escaped = False
    start = None
    for index, character in enumerate(text):
        if quoted:
            if character == '"' and not escaped:
                quoted = False
            escaped = character == '\\' and not escaped
            continue
        if character == '"':
            quoted = True
        elif character in '{[':
            if not stack:
                start = index
            stack.append(character)
        elif character in '}]' and stack:
            if stack.pop() != {'}': '{', ']': '['}[character]:
                break
            if not stack:
                frame = text[start:index + 1]
                values, _ = workflow._framed_json_values(frame)
                if len(values) == 1:
                    frames.append((values[0], frame.encode('utf-8')))
    return frames


def _observer_channels(revision: Path, state: Path, unit: dict, metadata: dict) -> None:
    """Parse independent file channels and all semantic outer stdout candidates."""
    checkpoint = revision / unit['review_transport']['progress_path']
    final = revision / unit['response_path']
    for channel, path in (('checkpoint', checkpoint), ('final_file', final)):
        if not quality._revision_owned_nonsymlink_path(revision, path):
            raise ValueError('Observer response channel is not revision-owned')
        if not path.is_file() or not path.stat().st_size:
            _observer_feedback(revision, unit, channel, 'Missing response channel')
            continue
        raw = path.read_bytes()
        retained = state / ('raw-progress.json' if channel == 'checkpoint' else 'raw-disk-final.json')
        if retained.exists() and retained.read_bytes() != raw:
            ledger = _read(revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json")
            attestation = ledger.get('observer_attestations', {}).get(path.relative_to(revision).as_posix(), {})
            if attestation.get('response_sha256') != quality.sha256_file(path):
                raise ValueError('Observer response changed after authentication')
            raw = retained.read_bytes()
        else:
            _retain_observer_bytes(revision, retained, raw)
        try:
            response = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            _observer_feedback(revision, unit, channel, 'Malformed response JSON')
            continue
        if not isinstance(response, dict):
            _observer_feedback(revision, unit, channel, 'Response is not an object')
            continue
        _observer_binding(unit, response)
        _authenticate_observer_response(revision, path, unit, metadata, response)
    output = (state / 'stdout.log').read_bytes()
    _retain_observer_bytes(revision, state / 'raw-final.json', output)
    try:
        text = output.decode('utf-8')
        valid_encoding = True
    except UnicodeDecodeError:
        # Replacement text may expose an attempted foreign identity, but may
        # never be published or earn review credit from repaired bytes.
        text = output.decode('utf-8', errors='replace')
        valid_encoding = False
        _observer_feedback(revision, unit, 'stdout', 'Malformed UTF-8 final response channel')
    values, malformed = workflow._framed_json_values(text)
    for issue in malformed:
        _observer_feedback(revision, unit, 'stdout', issue)
    candidates = []
    semantic = {'schema_version', 'request_id', 'request_sha256', 'task', 'revision_id',
        'visual_assessments', 'findings', 'producer', 'status'}
    for value, raw in _observer_stdout_frames(text):
        if isinstance(value, dict) and value in values and semantic.intersection(value):
            _observer_binding(unit, value)
            if valid_encoding:
                candidates.append((value, raw))
    if not candidates:
        _observer_feedback(revision, unit, 'stdout', 'Missing or malformed final response JSON')
    for candidate, raw in candidates:
        # Hash and retain the exact original frame, before host attestation.
        name = __import__('hashlib').sha256(raw).hexdigest() + '.json'
        path = state / 'authenticated-finals' / name
        _retain_observer_bytes(revision, state / 'raw-finals' / name, raw)
        ledger_path = revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json"
        relative = path.relative_to(revision).as_posix()
        if not path.exists():
            _retain_observer_bytes(revision, path, raw)
        elif path.read_bytes() != raw:
            attestation = _read(ledger_path).get('observer_attestations', {}).get(relative, {})
            if attestation.get('response_sha256') != quality.sha256_file(path):
                raise ValueError('Observer stdout response changed after authentication')
        _authenticate_observer_response(revision, path, unit, metadata, candidate)
        ledger = _read(ledger_path)
        if relative in ledger.get('observer_attestations', {}):
            channels = ledger.setdefault('observer_final_channels', [])
            if relative not in channels:
                channels.append(relative)
            _write(revision, ledger_path, ledger)
    # Retain the declared final for legacy readers, without replacing any disk
    # judgment. Aggregation uses every separately authenticated candidate above.
    if candidates and not final.exists():
        _retain_observer_bytes(revision, state / 'raw-disk-final.json', candidates[0][1])
        _write(revision, final, candidates[0][0])
        _authenticate_observer_response(revision, final, unit, metadata)


def _authenticate_observer_response(revision: Path, path: Path, unit: dict, metadata: dict,
                                    raw_response: dict | None = None) -> None:
    """Attach observed runtime identity, retaining original model response bytes."""
    if not path.is_file() or not metadata.get('request_inspection_complete'):
        return
    response = dict(raw_response) if raw_response is not None else _read(path)
    if (response.get('schema_version') != quality.RESPONSE_SCHEMA
            or any(response.get(k) != unit[k] for k in ('request_id', 'request_sha256', 'task', 'revision_id'))):
        return
    rows = response.get('visual_assessments')
    inspected = set(metadata['inspected_paths'])
    expected = {t['target_id']: t for t in unit['visual_scope']}
    # Filter incomplete tool access, not visual conclusions. Never derive a pass.
    observed_targets = {t['target_id'] for t in unit['visual_scope']
        if all(p['path'] in inspected for p in t['pages'])
        and (t['kind'] != 'document' or metadata['native_inspection_complete'])}
    if isinstance(rows, list):
        # Leave malformed/foreign rows visible to the row validator for precise
        # feedback; only filter valid assigned rows lacking inspected evidence.
        response['visual_assessments'] = [r for r in rows if not isinstance(r, dict)
            or not isinstance(r.get('target_id'), str) or r['target_id'] not in expected
            or r['target_id'] in observed_targets]
    # Keep malformed assessment shape for precise feedback. Independently
    # authenticated findings must still reach downstream concern validation.
    # Concerns carry their own bound location/provenance. Missing pixels may
    # withhold assessment credit, but must not destroy native concerns or
    # pixel concerns that downstream aggregation routes to targeted follow-up.
    response['model_reported_producer'] = response.get('producer')
    response['producer'] = {'model_id': metadata['model_id'], 'reviewer_id': metadata['session_id'],
        'role': 'independent configured TUI callback observer; not the invoking conversational parent'}
    response['observer_evidence'] = metadata
    _write(revision, path, response)
    ledger_path = revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json"
    ledger = _read(ledger_path)
    ledger.setdefault('observer_attestations', {})[path.relative_to(revision).as_posix()] = {
        'response_sha256': quality.sha256_file(path), 'producer': response['producer'],
        'observer_evidence': metadata}
    _write(revision, ledger_path, ledger)


def recover_completed_observers(revision: Path, parent_path: Path) -> None:
    """Recover genuine stopped-observer checkpoints after an interrupted callback.

    Raw model judgments and successful runtime tool evidence must both exist;
    a live observer, foreign request or poisoned unit never earns recovery credit.
    """
    from visual_review import visual_review_result, _parent, _owned
    parent = _parent(revision, parent_path)
    root = revision / 'hermes/visual-review-observers'
    for state in sorted(root.iterdir()) if root.is_dir() else []:
        if not state.is_dir() or state.is_symlink():
            continue
        try:
            diagnostic = _read(state / 'diagnostic.json') if (state / 'diagnostic.json').is_file() else {}
            launch = _read(state / 'launch.json') if (state / 'launch.json').is_file() else {}
            if launch:
                proc = Path(f"/proc/{launch['pid']}/stat")
                if proc.is_file() and proc.read_text().rsplit(')', 1)[1].split()[19] == launch['start_ticks']:
                    continue
            elif diagnostic.get('returncode') is None:
                continue
            path = revision / (launch.get('request_path') or diagnostic['request_path'])
            unit = _read(path)
            if unit.get('parent_request_sha256') != parent['request_sha256'] or not unit.get('observer_evidence_required'):
                continue
            ledger = _read(revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json")
            if (ledger.get('integrity_rejection') or not _owned(revision, path)
                    or path != revision / f"hermes/visual-review-requests/{unit['request_id']}.json"
                    or ledger.get('request_sha256') != unit['request_sha256']
                    or ledger.get('request_file_sha256') != quality.sha256_file(path)
                    or not quality.verification_request_hash_valid(unit)):
                continue
            from owned_observer_runtime import validate_owned_observer_cleanup, OwnedObserverLifetimeUnresolved
            try:
                validate_owned_observer_cleanup(state)
            except (OwnedObserverLifetimeUnresolved, OSError, ValueError, KeyError, TypeError) as exc:
                ledger['integrity_rejection'] = {'reason': 'Stopped observer cleanup proof invalid', 'error': str(exc)}
                _write(revision, revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json", ledger)
                continue  # Reject this unit; preserve recovery of independently valid siblings.
            try:
                provenance = _read(state / 'provenance.json')
                proof = validate_owned_observer_cleanup(state)
                if 'returncode' in proof:
                    # Production proofs bind terminal status. Legacy synthetic
                    # fixture certificates have no status and grant no crash evidence.
                    host_timeout = diagnostic.get('owned_timeout') is True
                    if type(proof['returncode']) is not int or (proof['returncode'] != 0 and not host_timeout):
                        raise ValueError('Stopped observer uncontrolled terminal exit')
                    if (provenance.get('request_sha256') != quality.sha256_file(path)
                            or provenance.get('request_path') != path.relative_to(revision).as_posix()
                            or provenance.get('managed_hermes_identity') != workflow._managed_hermes_identity()):
                        raise ValueError('Stopped observer request/runtime identity changed')
                    if provenance.get('invocation_path') and quality.sha256_file(Path(provenance['invocation_path'])) != provenance.get('invocation_sha256'):
                        raise ValueError('Stopped observer invocation identity changed')
                    if provenance.get('callback_release_binding'):
                        from visual_review import callback_release_binding
                        if callback_release_binding(Path(__file__).parent.parent) != provenance['callback_release_binding']:
                            raise ValueError('Stopped observer callback source changed')
                metadata = observer_metadata(state, revision, unit)
                _observer_channels(revision, state, unit, metadata)
            except (OSError, ValueError, KeyError, TypeError, sqlite3.DatabaseError) as exc:
                ledger = _read(revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json")
                ledger['integrity_rejection'] = {'reason': 'Stopped observer authentication/execution rejected',
                    'error': str(exc)}
                _write(revision, revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json", ledger)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.DatabaseError):
            continue  # Valid sibling observers remain independently recoverable.


def observe_unit(revision: Path, handoff: dict, budget: float, envelope: dict) -> None:
    unit_path = revision / handoff['request_path']
    original_request_sha256 = quality.sha256_file(unit_path)
    unit = _read(unit_path)
    state = revision / 'hermes/visual-review-observers' / (unit['request_id'] + '.' + uuid.uuid4().hex)
    state.mkdir(parents=True)
    original = Path(envelope.get('profile_path') or os.environ.get('HERMES_HOME', '')).resolve()
    if not (original / 'config.yaml').is_file():
        raise ValueError('Configured Hermes profile is unavailable; callback did not change model')
    for name in ('config.yaml', 'auth.json', '.env'):
        source = original / name
        if source.is_file(): (state / name).symlink_to(source.resolve())
    environment = dict(os.environ)
    for key, suffix in (('HERMES_HOME', ''), ('HOME', ''), ('TMPDIR', '.tmp'),
            ('XDG_CACHE_HOME', '.cache'), ('XDG_CONFIG_HOME', '.config'),
            ('XDG_DATA_HOME', '.local/share'), ('XDG_STATE_HOME', '.local/state')):
        directory = state / suffix
        directory.mkdir(parents=True, exist_ok=True)
        environment[key] = str(directory)
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    checkpoint = workflow._prepare_worker_checkpoint(revision, unit['review_transport']['progress_path'])
    launcher, interpreter = workflow._managed_hermes_pair()
    prompt = ('You are an independent visual observer invoked by a TUI callback, NOT the conversational parent. '
        'The configured model is unchanged. Use only read_file, vision_analyze, and write_file to your declared '
        'checkpoint. Native artifacts, source, requests, installed files and sibling judgments are READ-ONLY. '
        'Do not load unrelated skills or search the host. Read the bounded request at ' + str(unit_path) + '. '
        'Inspect assigned PNGs with vision_analyze, batch independent images together. '
        'The request instructions and visual_scope define your complete assignment. Evidence paths are relative to ' + str(revision) + '. '
        'Package paths in contracted_template_bundle are identities, not revision-readable locations. '
        'Read document_evidence, exact native DOCX, and every template_baseline_evidence file completely when document scope is assigned. '
        'Only the declared staged baseline paths authorize template comparison; do not search installed assets. '
        'Immediately save completed target judgments to ' + str(checkpoint) + ' as bound response JSON, status in_progress; '
        'read current checkpoint before overwriting, preserve completed work. '
        'Return complete or partial response JSON only, with schema_version ' + quality.RESPONSE_SCHEMA + ', '
        'request_id, request_sha256, task, revision_id copied exactly, producer genuine model/reviewer identity, '
        'status passed/blocked/in_progress, findings and visual_assessments. Each assessment copies target_id, kind, '
        'artifact, pages and checks exactly and adds status and visible notes. Do not invent judgments. '
        f'Your total remaining allocation including final response and cleanup is {budget:.1f} seconds; '
        'reserve at least 15 seconds for final response. A tool failure is incomplete review, never a pass.')
    command = [str(interpreter), str(launcher), 'chat', '-q', prompt,
        '--source', envelope['configuration']['source'], '--max-turns', str(envelope['configuration']['max_turns']),
        '-Q', '--safe-mode']
    provenance = {'request_path': handoff['request_path'],
        'request_sha256': quality.sha256_file(unit_path),
        'callback_release_binding': envelope.get('callback_release_binding'),
        'invocation_path': envelope.get('_invocation_path'),
        'invocation_sha256': envelope.get('_invocation_sha256'),
        'managed_hermes_identity': workflow._managed_hermes_identity(),
        'command': [str(interpreter), str(launcher), 'chat', '--safe-mode'],
        'command_sha256': __import__('hashlib').sha256(json.dumps(command).encode()).hexdigest()}
    _write(revision, state / 'provenance.json', provenance)
    stdout_path, stderr_path = state / 'stdout.log', state / 'stderr.log'
    process = None
    owned = None
    failure = None
    started = time.monotonic()
    from owned_observer_runtime import run_owned_observer, OwnedObserverLifetimeUnresolved
    try:
        owned = run_owned_observer(command, cwd=revision, env=environment, state=state, budget=budget,
            write_launch=lambda fields: _write(revision, state / 'launch.json', {**fields,
                'request_path': handoff['request_path'], 'callback_owner_pid': os.getpid()}))
        failure = owned['failure']
    except OwnedObserverLifetimeUnresolved as exc:
        failure = exc
        # Unresolved owned lifetime permanently poisons this unit, including
        # any partial checkpoints. Recovery cannot grant it credit.
        ledger_path = revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json"
        ledger = _read(ledger_path)
        ledger['integrity_rejection'] = {'reason': 'Owned observer descendant lifetime unresolved', 'error': str(exc)}
        _write(revision, ledger_path, ledger)
        _write(revision, state / 'diagnostic.json', {'request_path': handoff['request_path'],
            'returncode': None, 'descendants_reaped': False, 'error_type': type(exc).__name__,
            'elapsed_seconds': time.monotonic() - started})
        raise
    metadata = None
    try:
        metadata = observer_metadata(state, revision, unit)
        _observer_channels(revision, state, unit, metadata)
    except Exception as exc:
        failure = exc  # Authentication failure always outranks a host timeout.
    owned_timeout = (failure is owned.get('failure')
        and isinstance(failure, (TimeoutError, subprocess.TimeoutExpired)))
    _write(revision, state / 'diagnostic.json', {'request_path': handoff['request_path'],
        'owned_timeout': owned_timeout,
        'allocated_seconds': budget, 'elapsed_seconds': time.monotonic() - started,
        'returncode': owned['returncode'], 'observer_evidence': metadata,
        'error_type': type(failure).__name__ if failure else None,
        'descendants_reaped': owned['cleanup']['descendants_reaped'],
        'owned_cleanup_path': 'owned-descendant-cleanup.json', 'owned_cleanup_sha256': owned['cleanup_sha256'],
        'cleanup_scope': 'dedicated per-observer Linux subreaper; all owned descendants terminated and reaped'})
    result = visual_review_unit_result(revision, unit_path)
    ledger_path = revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json"
    feedback = list((result or {}).get('validation_feedback', []))
    for item in _read(ledger_path).get('observer_transport_feedback', []):
        if item not in feedback:
            feedback.append(item)
    diagnostic = _read(state / 'diagnostic.json')
    diagnostic['validation_feedback'] = feedback
    _write(revision, state / 'diagnostic.json', diagnostic)
    try:
        from owned_observer_runtime import validate_owned_observer_cleanup
        from visual_review import validate_visual_review_unit_request
        proof = validate_owned_observer_cleanup(state)
        validate_visual_review_unit_request(revision, unit_path)
        if (quality.sha256_file(state / 'owned-descendant-cleanup.json') != owned['cleanup_sha256']
                or quality.sha256_file(unit_path) != original_request_sha256
                or _read(state / 'provenance.json') != provenance
                or workflow._managed_hermes_identity() != provenance['managed_hermes_identity']
                or _read(state / 'launch.json').get('request_path') != handoff['request_path']
                or type(proof.get('returncode')) is not int
                or type(owned.get('returncode')) is not int
                or proof['returncode'] != owned['returncode']):
            raise ValueError('Observer request, runtime, provenance or cleanup changed')
        if envelope.get('_invocation_path') and quality.sha256_file(Path(envelope['_invocation_path'])) != envelope['_invocation_sha256']:
            raise ValueError('Observer invocation request changed')
        if envelope.get('callback_release_binding'):
            from visual_review import callback_release_binding
            if callback_release_binding(Path(__file__).parent.parent) != envelope['callback_release_binding']:
                raise ValueError('Observer callback source changed')
        if failure is not None and not owned_timeout:
            raise RuntimeError('Configured callback observer authentication/execution failed') from failure
        if failure is None and owned['returncode'] != 0:
            raise RuntimeError('Configured callback observer exited without a controlled timeout')
        if _read(ledger_path).get('integrity_rejection'):
            raise ValueError('Observer unit integrity was rejected')
    except Exception as exc:
        ledger = _read(ledger_path)
        ledger['integrity_rejection'] = {'reason': 'Observer terminal authentication/execution rejected',
            'error_type': type(exc).__name__, 'error': str(exc)}
        _write(revision, ledger_path, ledger)
        raise
    if result and result['complete']:
        return
    if failure is not None:
        raise failure
    from visual_review import IncompleteVisualReview
    incomplete = IncompleteVisualReview('Configured callback observer returned incomplete authenticated visual scope')
    incomplete.validation_feedback = feedback
    raise incomplete


def main() -> int:
    try:
        path = Path(sys.argv[1]).absolute()
        envelope, revision, allocation = callback_admission(path)
    except Exception as exc:
        print('Callback admission rejected: ' + type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        return 2
    deadline = time.monotonic() + allocation - 2.0
    errors = []
    missing_target_ids = set()
    validation_feedback = []
    for handoff in envelope['handoffs']:
        parent_path = revision / handoff['request_path']
        parent = _read(parent_path)
        if not parent.get('visual_review_plan'):
            raise ValueError('Bundled callback requires authenticated bounded visual coverage plan')
        recover_completed_observers(revision, parent_path)
        def dispatch(handoffs, budget):
            # Reclaim a previous closed wave before allocating the next one.
            # A final complete wave need not discard or lose its judgments
            # merely because unrelated process inspection is unavailable.
            try:
                from storage_retention import await_observer_reclamation
                await_observer_reclamation(revision, deadline - min(15.0, max(2.0, budget / 10)))
            except Exception as exc:
                if getattr(exc, 'storage_reclamation_deferred', False):
                    raise
                failure = RuntimeError('Observer storage retention could not safely complete before another wave')
                failure.storage_retention_failure = True
                raise failure from exc
            observer_budget = min(budget, deadline - time.monotonic())
            if observer_budget <= 15.0:
                raise TimeoutError('Callback observer allocation cannot cover response and cleanup reserve')
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = [pool.submit(observe_unit, revision, dict(h), observer_budget, envelope)
                    for h in handoffs]
                failures = []
                for future in futures:
                    try: future.result()
                    except Exception as exc: failures.append(exc)
                if failures:
                    from visual_review import IncompleteVisualReview
                    recoverable = (IncompleteVisualReview, TimeoutError, subprocess.TimeoutExpired)
                    # A safely incomplete sibling must never hide another
                    # observer's fatal identity, cleanup or execution fault.
                    raise next((exc for exc in failures if not isinstance(exc, recoverable)), failures[0])
        result = run_visual_review(revision, parent_path, dispatch, max(0.0, deadline - time.monotonic()),
            observer_evidence_required=True)
        if result['findings']:
            return 0  # Productive native findings preempt unrelated later review.
        if not result['complete']:
            errors.extend(result['dispatch_errors'] or ['Incomplete visual targets'])
            for target in result.get('followup_missing') or result.get('missing', []):
                missing_target_ids.add(target['target_id'] if isinstance(target, dict) else target)
            validation_feedback.extend(result.get('validation_feedback', []))
    if errors:
        # Dedicated exit code + immutable invocation identity. Exit 1 and
        # arbitrary exceptions remain fatal; the parent must authenticate this
        # report and its own cleanup proof before granting bounded retry.
        invocation = Path(envelope['_invocation_path'])
        if quality.sha256_file(invocation) != envelope['_invocation_sha256']:
            raise ValueError('Callback invocation changed before recoverable report')
        if workflow._managed_hermes_identity() != envelope['managed_hermes_identity']:
            raise ValueError('Callback runtime changed before recoverable report')
        if envelope.get('callback_release_binding'):
            from visual_review import callback_release_binding
            if callback_release_binding(Path(__file__).parent.parent) != envelope['callback_release_binding']:
                raise ValueError('Callback source changed before recoverable report')
        report = {'schema_version': 'tui-visual-callback-recovery/v1',
            'outcome': 'incomplete_authenticated_visual_scope', 'exit_code': 75,
            'invocation_path': str(invocation), 'invocation_sha256': envelope['_invocation_sha256'],
            'revision_id': revision.name, 'revision_path': str(revision),
            'managed_hermes_identity': envelope.get('managed_hermes_identity'),
            'callback_release_binding': envelope.get('callback_release_binding'),
            'callback_command': envelope.get('callback_command'),
            'handoffs': envelope['handoffs'], 'missing_target_ids': sorted(missing_target_ids),
            'validation_feedback': validation_feedback, 'dispatch_errors': errors}
        report_path = invocation.with_suffix('.recovery.json')
        _write(revision, report_path, report)
        print(json.dumps(report, sort_keys=True))
        print('Configured visual callback safely incomplete; retained authenticated diagnostics', file=sys.stderr)
        return 75
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
