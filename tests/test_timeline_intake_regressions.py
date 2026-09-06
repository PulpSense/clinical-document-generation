"""Unknown schedule origins are not conflicting obligatory source inputs."""
import copy
import json
import os
from pathlib import Path

import pytest

import contracts
import workflow

ROOT = Path(__file__).resolve().parents[1]


def test_prepare_preserves_unanchored_timeline_without_extra_intake(tmp_path):
    # Set this to reproduce an existing run read-only; never prepare in that run.
    supplied = os.environ.get("CLINICAL_TIMELINE_APPROVED_REFERENCE")
    source = Path(supplied) if supplied else ROOT / "tests/fixtures/release-certification/ambispective-advarra/approved-reference.json"
    original_bytes = source.read_bytes()
    reference = json.loads(original_bytes)
    if not supplied:
        reference["study"]["timeline"] = (
            "Enrollment is expected to last 8 months. Each participant is followed "
            "from screening through Week 12, for approximately 11 weeks after the baseline device fitting."
        )
        reference["procedures"]["assessments"] = [
            "Baseline device fitting at Week 2 after surgery; final clinic visit at Week 12."
        ]
        reference["procedures"]["visit_schedule"] = [
            {"visit": "Baseline device fitting", "timing": "Week 2 after surgery"},
            {"visit": "Final clinic visit", "timing": "Week 12"},
        ]
        reference["procedures"].pop("visit_schedule_table", None)
    before = copy.deepcopy(reference)
    path = tmp_path / "reference/study.reference.json"
    path.parent.mkdir()
    path.write_text(json.dumps(reference), encoding="utf-8")

    result = workflow.prepare(tmp_path)

    assert result["status"] == "awaiting_approval", result
    assert "missing" not in result and "missing_inputs" not in result
    assert not (tmp_path / "reference/missing-inputs.md").exists()
    prepared = json.loads(path.read_text())
    markdown = (tmp_path / result["source_of_truth"]).read_text()
    parsed = contracts.parse_source_truth(markdown, prepared)
    for field in ("study", "procedures"):
        assert prepared[field] == before[field]
        assert parsed[field] == before[field]
    assert source.read_bytes() == original_bytes
    assert reference == before
    assert contracts.timeline_findings(reference) == []


@pytest.mark.parametrize("final_timing", ["Week 12 after surgery", "Week 12 after baseline"])
def test_explicit_comparable_anchors_still_report_proven_contradiction(final_timing):
    reference = {
        "meta": {"study_type": "Prospective", "icf_template": "Advarra"},
        "study": {"timeline": "Final contact 11 weeks after baseline."},
        "procedures": {"visit_schedule": [
            {"visit": "Baseline", "timing": "Week 2 after surgery"},
            {"visit": "Final contact", "timing": final_timing},
        ]},
    }
    original = copy.deepcopy(reference)
    findings = contracts.timeline_findings(reference)
    assert len(findings) == 1
    assert "conflicts" in findings[0]["issue"]
    assert "unspecified" not in findings[0]["issue"]
    assert findings[0]["source_values"]["study.timeline"] == reference["study"]["timeline"]
    contract = contracts.source_contract(reference)
    assert contract["status"] == "blocked"
    assert findings[0] in contract["blocking_findings"]
    assert reference == original
