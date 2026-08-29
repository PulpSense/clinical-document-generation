import json
from pathlib import Path

import pytest

import quality
import workflow


ROOT = Path(__file__).resolve().parents[1]


def test_format_conformance_matrix_is_complete_hash_addressed_and_ordered():
    matrix = quality.load_format_conformance_matrix(ROOT)

    assert matrix["schema_version"] == "clinical-format-conformance/v1"
    assert [case["case_id"] for case in matrix["cases"]] == [
        "retrospective-protocol",
        "prospective-advarra",
        "prospective-sterling",
        "ambispective-advarra",
        "ambispective-sterling",
    ]
    assert [gate["gate_id"] for gate in matrix["gate_sequence"]] == list(quality.GOVERNED_GATE_SEQUENCE)
    assert matrix["finding_contract"]["required"] == [
        "code", "target", "evidence_sha256", "retry_owner", "terminal_status",
    ]
    required_checks = {
        "section_properties", "margins", "orientation", "styles", "numbering",
        "headers", "footers", "fields_toc", "page_furniture", "table_geometry",
        "signature_blocks", "consent_legal_language", "paragraph_rhythm",
        "natural_section_3_flow", "heading_cohesion", "front_matter_boundaries",
    }
    for case in matrix["cases"]:
        assert set(case["checks"]) == required_checks
        assert case["expected_outputs"] == (
            ["protocol.docx"] if case["study_type"] == "Retrospective"
            else ["icf.docx", "protocol.docx", "study.xml"]
        )
        for item in [case["fixture"], *case["baselines"]]:
            path = ROOT / item["path"]
            assert path.is_file()
            assert quality.sha256_file(path) == item["sha256"]

    canonical = dict(matrix)
    declared_sha256 = canonical.pop("matrix_sha256")
    assert declared_sha256 == quality.canonical_evidence_sha256(canonical)


def test_gate_ledger_is_hash_bound_and_failed_gates_are_monotonic():
    evidence = {
        gate_id: {"gate": gate_id, "artifact_sha256": str(index) * 64}
        for index, gate_id in enumerate(quality.GOVERNED_GATE_SEQUENCE, start=1)
    }
    ledger = quality.build_gate_ledger(ROOT, evidence)

    assert [record["gate_id"] for record in ledger["records"]] == list(quality.GOVERNED_GATE_SEQUENCE)
    assert all(record["terminal_status"] == "passed" for record in ledger["records"])
    assert all(len(record["evidence_sha256"]) == 64 for record in ledger["records"])
    unsigned = dict(ledger)
    declared_sha256 = unsigned.pop("ledger_sha256")
    assert declared_sha256 == quality.canonical_evidence_sha256(unsigned)
    assert quality.validate_gate_ledger(ROOT, ledger) == ledger

    bypass = json.loads(json.dumps(ledger))
    bypass["records"][2]["terminal_status"] = "blocked"
    bypass["records"][3]["terminal_status"] = "passed"
    unsigned = dict(bypass)
    unsigned.pop("ledger_sha256")
    bypass["ledger_sha256"] = quality.canonical_evidence_sha256(unsigned)
    with pytest.raises(ValueError, match="cannot pass after"):
        quality.validate_gate_ledger(ROOT, bypass)


def test_only_next_pending_gate_advances_with_new_exact_evidence():
    evidence = {gate_id: {"gate": gate_id} for gate_id in quality.GOVERNED_GATE_SEQUENCE}
    pending = quality.build_gate_ledger(
        ROOT,
        evidence,
        statuses={"exact_byte_atomic_delivery": "pending"},
    )
    prior_hash = pending["records"][-1]["evidence_sha256"]

    passed = quality.advance_gate_ledger(
        ROOT,
        pending,
        gate_id="exact_byte_atomic_delivery",
        terminal_status="passed",
        evidence={"opened": [{"filename": "protocol.docx", "sha256": "a" * 64}]},
    )

    assert passed["records"][-1]["terminal_status"] == "passed"
    assert passed["records"][-1]["evidence_sha256"] != prior_hash
    assert quality.validate_gate_ledger(ROOT, passed) == passed
    with pytest.raises(ValueError, match="first unresolved"):
        quality.advance_gate_ledger(
            ROOT,
            pending,
            gate_id="every_page_visual_qa",
            terminal_status="passed",
            evidence={"invalid": True},
        )


def test_independent_runner_binds_exact_matrix_combinations(tmp_path, monkeypatch):
    cases = [
        {"status": "passed", "case": "retrospective", "result": {"study_type": "Retrospective"}, "icf_template": None},
        {"status": "passed", "case": "prospective-advarra", "result": {"study_type": "Prospective"}, "icf_template": "Advarra"},
        {"status": "passed", "case": "prospective-sterling", "result": {"study_type": "Prospective"}, "icf_template": "Sterling"},
        {"status": "passed", "case": "ambispective-advarra", "result": {"study_type": "Ambispective"}, "icf_template": "Advarra"},
        {"status": "passed", "case": "ambispective-sterling", "result": {"study_type": "Ambispective"}, "icf_template": "Sterling"},
    ]
    monkeypatch.setattr(workflow, "page_renderers", lambda **kwargs: [{"kind": "pypdfium2"}])
    monkeypatch.setattr(workflow, "run_release_gate", lambda *args, **kwargs: {
        "status": "structural_passed",
        "assurance": "synthetic-structural-only",
        "cases": cases,
        "evidence_root": tmp_path.as_posix(),
    })

    report = workflow.run_format_conformance(ROOT, evidence_root=tmp_path)

    assert report["status"] == "structural_passed"
    assert report["assurance"] == "deterministic-structural-only"
    assert report["live_certification_required"] is True
    assert report["matrix_sha256"] == quality.load_format_conformance_matrix(ROOT)["matrix_sha256"]
    assert report["covered_cases"] == [
        "ambispective-advarra", "ambispective-sterling", "prospective-advarra",
        "prospective-sterling", "retrospective-protocol",
    ]
    assert (tmp_path / "format-conformance-report.json").is_file()


def test_source_runner_bootstraps_disposable_release_candidate(monkeypatch, tmp_path):
    expected = {"status": "structural_passed", "assurance": "deterministic-structural-only"}
    calls = []
    evidence_root = (tmp_path / "evidence").resolve()
    monkeypatch.setattr(workflow, "page_renderers", lambda **kwargs: [])
    monkeypatch.setattr(
        workflow,
        "_run_format_conformance_in_disposable_candidate",
        lambda repo_root, target: calls.append((repo_root, target)) or expected,
        raising=False,
    )

    result = workflow.run_format_conformance(ROOT, evidence_root=evidence_root)

    assert result == expected
    assert calls == [(ROOT.resolve(), evidence_root)]
