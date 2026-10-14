"""Owner-approved storage seams; no clinical operations or paid workers."""
from pathlib import Path
import pytest
import storage_retention as storage


def test_sequential_peak_counts_retained_growth_and_one_worker_wave(tmp_path):
    cases = [dict(case_id='retrospective', retained_bytes=20, worker_peak_bytes=50, scratch_peak_bytes=10),
             dict(case_id='prospective', retained_bytes=40, worker_peak_bytes=50, scratch_peak_bytes=10)]
    report = storage.sequential_admission(tmp_path, cases, margin_bytes=15, available_bytes=120)
    assert report['required_available_bytes'] == 95
    assert report['forecast_sequence_peak_bytes'] == 135
    assert report['admitted'] is True
    assert report['case_peaks'] == [95, 135]
    # A historical operation already on disk is not included in the forecast.
    assert report['baseline_used_bytes'] > 0


def test_durable_retirement_protects_sources_and_requires_exact_inventory(tmp_path):
    old = tmp_path / 'old'
    old.mkdir()
    (old / 'runtime').write_bytes(b'prior runtime')
    expected = storage.inventory(old)
    journal = tmp_path / 'retirement.json'
    with pytest.raises(ValueError, match='Protected'):
        storage.retire_tree(old, journal, expected, protected=[old / 'runtime'])
    assert (old / 'runtime').read_bytes() == b'prior runtime'
    (old / 'runtime').write_bytes(b'changed')
    with pytest.raises(ValueError, match='inventory'):
        storage.retire_tree(old, journal, expected, protected=[])
    assert old.exists()
    storage.retire_tree(old, journal, storage.inventory(old), protected=[])
    assert not old.exists()
    assert storage.retire_tree(old, journal, storage.inventory_from_record(journal), protected=[])['state'] == 'retired'


def test_completed_worker_cleanup_preserves_all_unique_state_and_pending_images(tmp_path):
    run = tmp_path / 'run'; run.mkdir()
    state = run / 'operation.json'; state.write_text('{"status":"running"}')
    worker = run / '.hermes-cache' / 'worker'; worker.mkdir(parents=True)
    duplicate = worker / 'bin'; duplicate.mkdir(); (duplicate / 'tool').write_bytes(b'tool')
    retained = tmp_path / 'retained'; retained.mkdir(); (retained / 'tool').write_bytes(b'tool')
    (worker / 'state.db').write_bytes(b'unique usage tools session')
    (run / 'page.png').write_bytes(b'pending independent audit')
    with pytest.raises(ValueError, match='terminal'):
        storage.cleanup_completed_workers(run, state, [(duplicate, retained)])
    state.write_text('{"status":"passed"}')
    result = storage.cleanup_completed_workers(run, state, [(duplicate, retained)])
    assert result['retired'][0]['state'] == 'retired'
    assert (worker / 'state.db').read_bytes() == b'unique usage tools session'
    assert (run / 'page.png').read_bytes() == b'pending independent audit'
    assert (retained / 'tool').read_bytes() == b'tool'


def test_archive_member_only_copy_is_never_deleted(tmp_path):
    import zipfile
    retained = tmp_path / 'folder'; retained.mkdir(); (retained / 'same.txt').write_bytes(b'same')
    archive = tmp_path / 'diagnostic.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('same.txt', b'same'); z.writestr('only-copy.txt', b'unique')
    with pytest.raises(ValueError, match='member'):
        storage.retire_duplicate_archive(archive, retained, tmp_path / 'archive-record.json')
    assert archive.exists()


@pytest.mark.parametrize('phase', ['intent_durable', 'entry_intent', 'entry_removed'])
def test_interrupted_retirement_resumes_exact_inventory(tmp_path, phase):
    root = tmp_path / 'old'; root.mkdir(); (root / 'nested').mkdir()
    (root / 'nested' / 'runtime').write_bytes(b'retired dependency copy')
    (root / 'nested').chmod(0o555); root.chmod(0o555)
    expected = storage.inventory(root); journal = tmp_path / 'record.json'
    def interrupt(actual):
        if actual == phase:
            raise OSError('crash boundary')
    with pytest.raises(OSError, match='crash'):
        storage.retire_tree(root, journal, expected, protected=[], hook=interrupt)
    result = storage.retire_tree(root, journal, expected, protected=[])
    assert result['state'] == 'retired'
    assert not root.exists()


@pytest.mark.parametrize('mutation', ['bytes', 'inode'])
def test_change_between_intent_and_delete_is_detected(tmp_path, mutation):
    root = tmp_path / 'old'; root.mkdir(); target = root / 'a'; target.write_bytes(b'original')
    expected = storage.inventory(root)
    def mutate(phase):
        if phase == 'entry_intent':
            if mutation == 'inode':
                target.unlink(); target.write_bytes(b'original')
            else:
                target.write_bytes(b'modified')
    with pytest.raises(ValueError, match='changed'):
        storage.retire_tree(root, tmp_path / 'record.json', expected, protected=[], hook=mutate)
    assert target.exists()


def test_enospc_before_durable_intent_keeps_entire_tree(tmp_path, monkeypatch):
    root = tmp_path / 'old'; root.mkdir(); (root / 'runtime').write_bytes(b'preserved')
    expected = storage.inventory(root)
    def full(*args):
        raise OSError(28, 'No space left on device')
    monkeypatch.setattr(storage, 'save', full)
    with pytest.raises(OSError):
        storage.retire_tree(root, tmp_path / 'journal.json', expected, protected=[])
    assert storage.inventory(root) == expected


def test_archive_exact_duplicate_is_durable_and_reentrant(tmp_path):
    import zipfile
    retained = tmp_path / 'folder'; retained.mkdir(); (retained / 'same').write_bytes(b'actual bytes')
    archive = tmp_path / 'diagnostic.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('same', b'actual bytes')
    journal = tmp_path / 'archive-record.json'
    assert storage.retire_duplicate_archive(archive, retained, journal)['state'] == 'retired'
    assert not archive.exists()
    assert storage.retire_duplicate_archive(archive, retained, journal)['members'][0]['bytes'] == 12
    assert (retained / 'same').read_bytes() == b'actual bytes'


def test_auto_completed_cleanup_keeps_one_copy_and_all_unique_state(tmp_path):
    run = tmp_path / 'run'; run.mkdir(); state = run / 'operation.json'; state.write_text('{"status":"passed"}')
    for worker in ('one', 'two', 'unique'):
        root = run / '.hermes-cache' / worker; (root / 'bin').mkdir(parents=True)
        (root / 'bin' / 'tool').write_bytes(b'tool' if worker != 'unique' else b'only copy')
        (root / 'stdout.log').write_bytes(worker.encode())
    result = storage.completed_operation_cleanup(run, state)
    assert len(result['retired']) == 1
    assert (run / '.hermes-cache/one/bin/tool').read_bytes() == b'tool'
    assert not (run / '.hermes-cache/two/bin').exists()
    assert (run / '.hermes-cache/unique/bin/tool').read_bytes() == b'only copy'
    assert len(list(run.glob('.hermes-cache/*/stdout.log'))) == 3


def test_archive_generated_index_is_retained_byte_for_byte(tmp_path):
    import zipfile
    retained = tmp_path / 'folder'; retained.mkdir(); (retained / 'same').write_bytes(b'actual')
    raw_index = b'{"files": []}\n'
    archive = tmp_path / 'diagnostic.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('same', b'actual'); z.writestr('diagnostic-inventory.json', raw_index)
    result = storage.retire_duplicate_archive(archive, retained, tmp_path / 'archive-record.json')
    assert Path(result['generated_index']['retained_path']).read_bytes() == raw_index
    assert not archive.exists()


def test_completed_catalog_dedup_preserves_model_metadata_and_unique_session_state(tmp_path):
    run = tmp_path / 'run'; run.mkdir(); state = run / 'operation.json'; state.write_text('{"status":"passed"}')
    for name in ('one', 'two', 'unique'):
        worker = run / '.hermes-cache' / name; worker.mkdir(parents=True)
        (worker / 'models_dev_cache.json').write_bytes(b'full model catalog' if name != 'unique' else b'foreign metadata')
        (worker / 'state.db').write_bytes(name.encode())
    storage.completed_operation_cleanup(run, state)
    assert (run / '.hermes-cache/one/models_dev_cache.json').read_bytes() == b'full model catalog'
    assert not (run / '.hermes-cache/two/models_dev_cache.json').exists()
    assert (run / '.hermes-cache/unique/models_dev_cache.json').read_bytes() == b'foreign metadata'
    assert (run / '.hermes-cache/two/state.db').read_bytes() == b'two'


def test_stopped_observer_assets_are_deduped_before_next_wave_without_touching_audit(tmp_path):
    import json
    revision = tmp_path / 'revisions/r1'; observers = revision / 'hermes/visual-review-observers'
    request = revision / 'hermes/request.json'; request.parent.mkdir(parents=True)
    request.write_text('{"fixture_only":true}')
    for name in ('one', 'two'):
        worker = observers / name; (worker / 'bin').mkdir(parents=True)
        (worker / 'bin/tirith').write_bytes(b'exact verified security binary')
        (worker / 'state.db').write_bytes(b'actual session tool evidence')
        (worker / 'diagnostic.json').write_text(json.dumps({'returncode':0, 'request_path':'hermes/request.json'}))
        (worker / 'provenance.json').write_text(json.dumps({'request_path':'hermes/request.json', 'request_sha256':storage.sha(request)}))
        (worker / 'launch.json').write_text('{"pid":99999999,"start_ticks":"1","request_path":"hermes/request.json","fixture_only":true}')
    storage.cleanup_stopped_observer_assets(revision)
    assert (observers / 'one/bin/tirith').read_bytes() == b'exact verified security binary'
    assert not (observers / 'two/bin').exists()
    assert (observers / 'two/state.db').read_bytes() == b'actual session tool evidence'
    # A later wave must not remove the canonical source of earlier records.
    earlier = observers / 'aaa'; (earlier / 'bin').mkdir(parents=True)
    for name in ('diagnostic.json','provenance.json','launch.json','state.db'):
        (earlier / name).write_bytes((observers / 'one' / name).read_bytes())
    (earlier / 'bin/tirith').write_bytes(b'exact verified security binary')
    storage.cleanup_stopped_observer_assets(revision)
    assert (observers / 'one/bin/tirith').is_file()
    assert not (earlier / 'bin').exists()


@pytest.mark.parametrize('family', ['prospective-advarra','prospective-sterling','ambispective-advarra','ambispective-sterling','retrospective'])
def test_storage_failure_stops_new_visual_wave_without_poisoning_completed_review(tmp_path, family):
    import json
    from test_visual_units import parent_fixture, response_for
    from visual_review import run_visual_review, visual_review_result
    revision, parent_path, _ = parent_fixture(tmp_path, family)
    calls = []
    def dispatch(handoffs, budget):
        calls.append(handoffs)
        unit = json.loads((revision / handoffs[0]['request_path']).read_text())
        checkpoint = revision / unit['review_transport']['progress_path']
        checkpoint.parent.mkdir(parents=True,exist_ok=True)
        checkpoint.write_text(json.dumps(response_for(unit,unit['visual_scope'][:1])))
        error = RuntimeError('retention did not safely complete')
        error.storage_retention_failure = True
        raise error
    with pytest.raises(RuntimeError, match='retention'):
        run_visual_review(revision, parent_path, dispatch, 30)
    assert len(calls) == 1
    partial = visual_review_result(revision, parent_path, publish=False)
    assert len(partial['assessments']) == 1
    assert not partial['complete']


def test_live_owned_worker_cwd_blocks_disposable_tree_retirement(tmp_path):
    import subprocess
    root = tmp_path / 'worker'; root.mkdir(); (root / 'binary').write_bytes(b'preserve while live')
    process = subprocess.Popen(['/bin/sleep','30'], cwd=root)
    try:
        with pytest.raises(ValueError, match='Live'):
            storage.retire_tree(root, tmp_path / 'record.json', storage.inventory(root), protected=[])
        assert (root / 'binary').read_bytes() == b'preserve while live'
        assert not (tmp_path / 'record.json').exists()
    finally:
        process.kill(); process.wait(timeout=5)
