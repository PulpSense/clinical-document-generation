"""Recovery attempts are measured before a subsequent retry is archived."""
import json
from pathlib import Path

import pytest

import workflow

ROOT = Path(__file__).resolve().parents[1]


def _finding(issue: str) -> dict[str, object]:
    return {
        "category": "drafting",
        "field": "introduction",
        "target_ids": ["introduction"],
        "recovery_class": "drafting_defect",
        "action": "retry_drafting_target",
        "issue": issue,
    }


def test_second_drafting_retry_measures_first_attempt_before_strict_validation(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    revision = run_dir / "revisions/r-test"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    first = workflow._archive_failed_attempt(revision, "drafting", [_finding("first rejection")])
    journal = json.loads((revision / "gate-attempt-journal.json").read_text(encoding="utf-8"))
    relative = first.relative_to(revision).as_posix()
    working = {
        "generation": {
            "gate_attempts": journal["entries"],
            "pending_recovery_attempts": [relative],
        }
    }
    reference_path.write_text(json.dumps(working), encoding="utf-8")
    approved = json.loads(
        (ROOT / "tests/fixtures/retrospective-acceptance-source.json").read_text(encoding="utf-8")
    )
    request = revision / "hermes/requests/retry.json"
    monkeypatch.setattr(workflow, "_apply_pending_recovery_plan", lambda *_args, **_kwargs: [request])
    monkeypatch.setattr(
        workflow,
        "_awaiting",
        lambda _revision, *, stage, paths, findings=None: {
            "status": "awaiting_hermes",
            "stage": stage,
        },
    )

    result = workflow._quality_retry(
        run_dir,
        reference_path,
        working,
        approved,
        revision,
        {},
        [_finding("second rejection")],
        "drafting",
        require_promoted_runtime=False,
    )

    assert result["status"] == "awaiting_hermes"
    assert result["stage"] == "drafting_retry"
    attempts = sorted((revision / "attempts").glob("*/attempt-manifest.json"))
    assert len(attempts) == 2
    first_manifest = json.loads(attempts[0].read_text(encoding="utf-8"))
    second_manifest = json.loads(attempts[1].read_text(encoding="utf-8"))
    assert {action["outcome_status"] for action in first_manifest["recovery_actions"]} == {"measured"}
    assert {action["outcome_status"] for action in second_manifest["recovery_actions"]} == {"pending"}
    state = json.loads(reference_path.read_text(encoding="utf-8"))["generation"]
    journal = json.loads((revision / "gate-attempt-journal.json").read_text(encoding="utf-8"))
    assert state["gate_attempts"] == journal["entries"]
    assert state["pending_recovery_attempts"] == [attempts[1].parent.relative_to(revision).as_posix()]


def test_second_retry_rejects_tampered_pending_evidence_before_rebinding(tmp_path):
    run_dir = tmp_path / "run"
    revision = run_dir / "revisions/r-test"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    first = workflow._archive_failed_attempt(revision, "drafting", [_finding("first rejection")])
    journal_path = revision / "gate-attempt-journal.json"
    manifest_path = first / "attempt-manifest.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    relative = first.relative_to(revision).as_posix()
    working = {
        "generation": {
            "gate_attempts": journal["entries"],
            "pending_recovery_attempts": [relative],
        }
    }
    reference_path.write_text(json.dumps(working), encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["findings"][0]["issue"] = "tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = {
        "manifest": manifest_path.read_bytes(),
        "journal": journal_path.read_bytes(),
        "reference": reference_path.read_bytes(),
    }
    approved = json.loads(
        (ROOT / "tests/fixtures/retrospective-acceptance-source.json").read_text(encoding="utf-8")
    )

    with pytest.raises(ValueError, match="missing or stale"):
        workflow._quality_retry(
            run_dir,
            reference_path,
            working,
            approved,
            revision,
            {},
            [_finding("second rejection")],
            "drafting",
            require_promoted_runtime=False,
        )

    assert manifest_path.read_bytes() == before["manifest"]
    assert journal_path.read_bytes() == before["journal"]
    assert reference_path.read_bytes() == before["reference"]


def test_strict_validator_still_rejects_an_unfinalized_attempt(tmp_path):
    revision = tmp_path / "revision"
    workflow._archive_failed_attempt(revision, "drafting", [_finding("unresolved")])
    journal = json.loads((revision / "gate-attempt-journal.json").read_text(encoding="utf-8"))

    try:
        workflow._validate_expected_gate_attempts(revision, journal["entries"])
    except ValueError as exc:
        assert "outcome is pending" in str(exc)
    else:
        raise AssertionError("Strict validation accepted pending recovery evidence")
