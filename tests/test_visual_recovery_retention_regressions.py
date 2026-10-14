"""Unpaid public-seam specification controls; not clinical/capability evidence."""
import json
from pathlib import Path
import sys
import pytest
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'), str(Path(__file__).resolve().parent)]
import storage_retention as storage

@pytest.mark.parametrize('diagnostic', [
    {'returncode': None, 'error_type': 'TimeoutError'},
    {'returncode': None, 'descendants_reaped': True},
    {'returncode': 'unknown', 'descendants_reaped': True},
])
def test_launched_missing_cleanup_blocks_next_wave(tmp_path, diagnostic):
    revision = tmp_path / 'revisions/r1'
    worker = revision / 'hermes/visual-review-observers/launched'
    worker.mkdir(parents=True)
    (worker / 'launch.json').write_text(json.dumps({'pid':99999999,'start_ticks':'1'}))
    (worker / 'diagnostic.json').write_text(json.dumps(diagnostic))
    (worker / 'bin').mkdir()
    (worker / 'bin/keep').write_text('missing lifetime proof')
    with pytest.raises((storage.OwnedProcessProofUnavailable, ValueError)):
        storage.cleanup_stopped_observer_assets(revision)


@pytest.mark.parametrize('malformed', [False, True])
def test_malformed_progress_cannot_erase_valid_final_recovery(tmp_path, monkeypatch, malformed):
    import tui_visual_callback as callback
    import quality
    from test_visual_units import parent_fixture, response_for
    from visual_review import create_visual_review_unit, visual_review_result
    revision,parent_path,parent=parent_fixture(tmp_path,'retrospective')
    path=create_visual_review_unit(revision,parent_path,parent['visual_review_plan']['targets'][:1],1,observer_evidence_required=True)
    unit=json.loads(path.read_text())
    state=revision/'hermes/visual-review-observers/stopped-fixture'
    state.mkdir(parents=True)
    (state/'stdout.log').write_text(json.dumps(response_for(unit)))
    (state/'diagnostic.json').write_text(json.dumps({'request_path':path.relative_to(revision).as_posix(),'returncode':-9}))
    command_hash='unpaid-fixture-command'
    launch={'pid':99999999,'start_ticks':'1','request_path':path.relative_to(revision).as_posix(),'owned_command_sha256':command_hash,'supervisor_sha256':quality.sha256_file(Path(callback.__file__).with_name('owned_observer_process.py'))}
    (state/'launch.json').write_text(json.dumps(launch))
    (state/'provenance.json').write_text(json.dumps({'command_sha256':command_hash}))
    (state/'owned-descendant-cleanup.json').write_text(json.dumps({'fixture_only':True,'descendants_reaped':True,'errors':[],'owner_pid':launch['pid'],'owner_start_ticks':launch['start_ticks'],'command_sha256':command_hash}))
    (state/'state.db').write_bytes(b'synthetic database; metadata mocked at public recovery seam')
    metadata={'session_id':'stopped-fixture-session','model_id':'test-model','state_path':str(state),'database_sha256':quality.sha256_file(state/'state.db'),'request_inspection_complete':True,'native_inspection_complete':True,'inspected_paths':[p['path'] for t in unit['visual_scope'] for p in t['pages']],'image_tool_results':[{'tool':'vision_analyze','page_path':p['path'],'sha256':p['sha256'],'success':True} for t in unit['visual_scope'] for p in t['pages']]}
    monkeypatch.setattr(callback,'observer_metadata',lambda *a:metadata)
    progress=revision/unit['review_transport']['progress_path']
    progress.parent.mkdir(parents=True,exist_ok=True)
    progress.write_text('{malformed interrupted checkpoint' if malformed else '')
    callback.recover_completed_observers(revision,parent_path)
    assert len(visual_review_result(revision,parent_path,publish=False)['assessments'])==1
