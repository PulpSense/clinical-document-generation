"""Focused reliability maintenance regressions at approved public seams."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import contracts
import rendering
import workflow

ROOT = Path(__file__).resolve().parents[1]


def prospective_reference() -> dict:
    return json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text())


def test_source_contract_canonicalizes_declared_aliases_with_provenance_and_conflicts():
    reference = prospective_reference()
    reference["risks_benefits"].pop("compensation_or_reimbursement")
    reference["risks_benefits"]["compensation"] = "None"
    reference["population"].pop("sample_justification")
    reference["statistics"]["sample_size_justification"] = "TBD"

    contract = contracts.source_contract(reference)

    normalized = contract["normalized_reference"]
    assert normalized["risks_benefits"]["compensation_or_reimbursement"] == "None"
    assert normalized["source"]["alias_provenance"]["risks_benefits.compensation_or_reimbursement"] == [
        "risks_benefits.compensation"
    ]
    assert any(item["field"] == "population.sample_justification" for item in contract["source_gaps"])

    conflict = prospective_reference()
    conflict["risks_benefits"]["compensation"] = "$25 per visit"
    result = contracts.source_contract(conflict)
    assert any("conflicting declared aliases" in item["issue"].lower() for item in result["source_gaps"])


def test_source_contract_rejects_combined_endpoint_prose():
    reference = prospective_reference()
    reference["endpoints"] = {
        "primary": "Primary: Change in symptom score at Month 3; Secondary: Device adherence at Week 12"
    }
    contract = contracts.source_contract(reference)
    assert contract["status"] == "blocked"
    assert any(item["field"] == "endpoints.primary" for item in contract["technical_findings"])


def test_constructability_closes_optional_protocol_identifiers_deterministically():
    reference = prospective_reference()
    reference["meta"].pop("protocol_number", None)
    reference["regulatory"]["prs"].pop("provider_study_id", None)

    first = contracts.source_contract(reference)["normalized_reference"]
    second = contracts.source_contract(copy.deepcopy(reference))["normalized_reference"]
    identifier = first["meta"]["protocol_number"]

    assert identifier.startswith("ADM-")
    assert first["regulatory"]["prs"]["provider_study_id"] == identifier
    assert second["meta"]["protocol_number"] == identifier
    assert first["source"]["administrative_identifier"]["authority"] == "deterministic_workflow"
    assert first == second


def test_facility_projection_is_central_and_postal_appears_once():
    facility = {
        "name": "North Clinic",
        "address": {"address_line1": "10 Main Street", "locality": "Boston", "region": "MA"},
        "postalCode": "02110",
        "country": "United States",
    }
    projection = contracts.facility_projection(facility)
    assert projection == {
        "name": "North Clinic",
        "street": "10 Main Street",
        "city": "Boston",
        "state": "MA",
        "postal_code": "02110",
        "country": "United States",
        "locality": "Boston, MA, 02110, United States",
        "address": "10 Main Street, Boston, MA, United States, 02110",
    }
    fields = rendering.render_fields({"sites": [{"facility": facility}]}, {})
    assert fields["facilityAddress"] == projection["street"]
    assert fields["facilityLocation"] == projection["locality"]
    assert fields["studySiteAddress"] == projection["address"]
    assert fields["studySiteAddress"].count("02110") == 1


def test_recovery_findings_declare_the_owning_seam():
    finding = contracts.recovery_finding(
        {"category": "visual", "field": "icf", "target_ids": ["layout:icf"]},
        "visual_defect",
    )
    assert finding["owner"] == "layout"

    assert contracts.recovery_finding(
        {"category": "rendering", "field": "icf"},
        "document_structure_defect",
    )["owner"] == "construction"


def test_delivery_retries_same_bytes_until_deadline_not_legacy_retry_count(monkeypatch):
    payload = b"exact"
    manifest = {"client_outputs": [{
        "filename": "study.xml",
        "path": "output/study.xml",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }]}
    reply = workflow.desktop_attachment_reply(manifest)
    ticks = iter([0.0, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
    attempts = []

    def opener(_path):
        attempts.append(1)
        if len(attempts) < 4:
            raise OSError("transient")
        return payload

    monkeypatch.setattr(workflow.time, "sleep", lambda _seconds: None)
    result = workflow.confirm_desktop_delivery(
        manifest, reply, opener, deadline=1.0, retries=0, clock=lambda: next(ticks)
    )
    assert result["confirmed"] is True
    assert result["attempts"] == 4


def test_null_compensation_remains_a_missing_required_answer():
    reference = prospective_reference()
    reference["risks_benefits"]["compensation_or_reimbursement"] = None

    contract = contracts.source_contract(reference)

    assert contract["status"] == "blocked"
    assert any(
        finding["field"] == "risks_benefits.compensation_or_reimbursement"
        and finding["issue"] == "Required Source Input is missing."
        for finding in contract["source_gaps"]
    )


def test_all_declared_required_aliases_are_projected_to_canonical_paths():
    reference = prospective_reference()
    reference["procedures"].pop("assessments")
    reference["parties"]["principal_investigator"]["degree"] = reference["parties"]["principal_investigator"].pop("title")
    reference["parties"]["study_coordinator"]["degree"] = reference["parties"]["study_coordinator"].pop("title")

    normalized = contracts.source_contract(reference)["normalized_reference"]

    assert normalized["procedures"]["assessments"] == reference["procedures"]["visit_schedule"]
    assert normalized["parties"]["principal_investigator"]["title"] == reference["parties"]["principal_investigator"]["degree"]
    assert normalized["parties"]["study_coordinator"]["title"] == reference["parties"]["study_coordinator"]["degree"]


def test_retrospective_source_does_not_receive_prs_administrative_identifiers():
    reference = json.loads((ROOT / "tests/fixtures/retrospective-acceptance-source.json").read_text())
    reference["meta"].pop("protocol_number", None)
    reference.setdefault("regulatory", {}).setdefault("prs", {}).pop("provider_study_id", None)

    normalized = contracts.source_contract(reference)["normalized_reference"]

    assert "protocol_number" not in normalized["meta"]
    assert "provider_study_id" not in normalized.get("regulatory", {}).get("prs", {})


def test_flat_complete_address_with_structured_components_projects_without_duplication():
    facility = {
        "name": "North Georgia Eye Associates",
        "address": "North Georgia Eye Associates, 2061 Beverly Rd, Gainesville, GA 30501, United States",
        "city": "Gainesville",
        "state": "GA",
        "postal_code": "30501",
        "country": "United States",
    }

    assert contracts.facility_projection(facility) == {
        "name": "North Georgia Eye Associates",
        "street": "2061 Beverly Rd",
        "city": "Gainesville",
        "state": "GA",
        "postal_code": "30501",
        "country": "United States",
        "locality": "Gainesville, GA, 30501, United States",
        "address": "2061 Beverly Rd, Gainesville, GA 30501, United States",
    }


def test_nested_locality_without_street_never_stringifies_the_address_mapping():
    projection = contracts.facility_projection({
        "name": "Clinic",
        "address": {"city": "Boston", "state": "MA", "zip": "02110"},
    })

    assert projection["street"] == ""
    assert projection["address"] == "Boston, MA, 02110"
    assert "{" not in projection["address"]


def test_blocked_desktop_operation_rebinds_verified_release_under_same_source_and_deadline(tmp_path, monkeypatch):
    approval = {
        "status": "approved",
        "approved_by": "client",
        "approved_at": "2026-09-10T00:00:00+00:00",
        "revision_id": "r-source",
        "source_sha256": "a" * 64,
        "approved_reference_sha256": "b" * 64,
        "source_approval_identity": "c" * 64,
    }
    reference_path = tmp_path / "reference" / "study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({"meta": {"study_type": "Retrospective"}, "approval": approval}))
    state_path = tmp_path / "logs" / "desktop-operation.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "operation_id": "default",
        "started_at_epoch": 900.0,
        "deadline_at_epoch": 1_100.0,
        "budget_seconds": 200.0,
        "release_identity": {"package_fingerprint": "old", "git_commit": "old"},
        "approval_identity": approval,
        "status": "blocked",
        "stage": "layout_repair_classification",
        "result": {"status": "blocked", "stage": "layout_repair_classification"},
    }))
    calls = []
    monkeypatch.setattr(workflow, "generate", lambda *_args, **_kwargs: calls.append(True) or {
        "status": "blocked", "stage": "test-stop", "client_outputs": [],
    })

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda *_args: None,
        opener=lambda _path: b"unused",
        release_identity={"package_fingerprint": "new", "git_commit": "new"},
        budget_seconds=200.0,
        clock=lambda: 0.0,
        wall_clock=lambda: 1_000.0,
    )

    state = json.loads(state_path.read_text())
    assert calls == [True]
    assert result["stage"] == "test-stop"
    assert state["started_at_epoch"] == 900.0
    assert state["deadline_at_epoch"] == 1_100.0
    assert state["release_transitions"][0]["prior_result"]["stage"] == "layout_repair_classification"


def test_desktop_elapsed_and_budget_are_reported_after_cleanup(tmp_path, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(workflow, "generate", lambda *_args, **_kwargs: {
        "status": "blocked", "stage": "test-stop", "client_outputs": [],
    })

    def cleanup(_status, _remaining):
        now[0] += 5.0
        return {"owned_processes_reaped": True}

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda *_args: None,
        opener=lambda _path: b"unused",
        cleanup=cleanup,
        budget_seconds=30.0,
        clock=lambda: now[0],
        wall_clock=lambda: 1_000.0,
    )

    assert result["elapsed_seconds"] == 5.0
    assert result["operation_deadline_seconds"] == 30.0
