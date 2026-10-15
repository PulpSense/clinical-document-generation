"""Post-attestation loss must stop recovery, not disappear beside valid progress."""
import json

import pytest

from test_observer_concern_channels import exercise
from test_visual_units import response_for
from visual_review import create_visual_review_unit, run_visual_review, visual_review_result


@pytest.mark.parametrize('fault', ['hash', 'missing', 'path'])
def test_changed_attested_stdout_cannot_be_erased_by_valid_siblings(tmp_path, monkeypatch, fault):
    revision, unit, ledger, state, result, error = exercise(tmp_path, monkeypatch, 'quoted')
    assert error is None and result['complete']
    parent_path = revision / unit['parent_request_path']
    parent = json.loads(parent_path.read_text())
    sibling_target = parent['visual_review_plan']['targets'][1]
    sibling_path = create_visual_review_unit(revision, parent_path, [sibling_target], 20)
    sibling = json.loads(sibling_path.read_text())
    output = revision / sibling['response_path']
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(response_for(sibling)))
    relative = ledger['observer_final_channels'][0]
    attested = revision / relative
    ledger_path = revision / 'hermes/visual-review-ledgers' / (unit['request_id'] + '.json')
    if fault == 'hash':
        attested.write_bytes(attested.read_bytes() + b' ')
    elif fault == 'missing':
        attested.unlink()
    else:
        alternate = revision / 'hermes/unauthorized-relocation.json'
        alternate.write_bytes(attested.read_bytes())
        relocated = alternate.relative_to(revision).as_posix()
        ledger['observer_final_channels'] = [relocated]
        ledger['observer_attestations'][relocated] = ledger['observer_attestations'][relative]
        ledger_path.write_text(json.dumps(ledger))
    allocated = []
    def dispatch(handoffs, budget):
        allocated.extend(handoffs)
        for handoff in handoffs:
            request = json.loads((revision / handoff['request_path']).read_text())
            path = revision / request['response_path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(response_for(request)))
    with pytest.raises(ValueError, match='integrity|rejected'):
        run_visual_review(revision, parent_path, dispatch, 60)
    assert not allocated, 'Do not turn an attestation rejection into a fresh missing-scope worker'
    assert json.loads(ledger_path.read_text()).get('integrity_rejection')
    snapshot = visual_review_result(revision, parent_path, publish=False)
    assert not snapshot['complete']
    assert any(row['target_id'] == sibling_target['target_id'] for row in snapshot['assessments'])
