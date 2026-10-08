"""Synthetic schedule replay through the public Desktop delivery operation.

Controlled external responders are not independent clinical certification.
Internal construction, gates, cache invalidation and atomic publication are real.
"""
import copy
import json
import subprocess
from pathlib import Path

from docx import Document
import pytest

import contracts
import drafting
import quality
import workflow
from test_handoff_quality import acceptance_verification

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("change", ["sentence-case", "quantity"])
def test_schedule_variation_or_real_defect_reaches_verified_complete_delivery(tmp_path, governed_pdfium, monkeypatch, change):
    run = tmp_path / "run"
    reference_path = run / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    source = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text())
    source["procedures"]["visit_schedule_table"] = []
    source["procedures"]["visit_schedule"][0]["procedures"].extend([
        "demographics", "qPCR collection at 5 mL",
    ])
    reference_path.write_text(json.dumps(source))
    assert workflow.prepare(run)["status"] == "awaiting_approval"
    assert workflow.approve(run, approved_by="Synthetic schedule replay")["status"] == "passed"
    approval = copy.deepcopy(json.loads(reference_path.read_text())["approval"])
    revision = run / "revisions" / approval["revision_id"]
    observed = {"mutated": False, "drafts": None, "reviews": set()}

    def accepted_bytes():
        return {path.name: path.read_bytes() for path in (revision / "hermes/accepted").glob("*.json")}

    real_process = subprocess.run

    def office_process(command, *args, **kwargs):
        # Inject once at the external office boundary, before artifact review
        # hashes exist. Never mutate already-bound verifier inputs.
        if (isinstance(command, (list, tuple)) and "--convert-to" in command
                and "pdf" in command and Path(str(command[-1])) == revision / "candidate/protocol.docx"
                and not observed["mutated"]):
            protocol_path = revision / "candidate/protocol.docx"
            document = Document(protocol_path)
            table = next(t for t in document.tables if t.rows[0].cells[0].text.strip() == "Activity")
            label = "demographics" if change == "sentence-case" else "qPCR collection at 5 mL"
            row = next(row for row in table.rows if row.cells[0].text.strip() == label)
            row.cells[0].text = "Demographics" if change == "sentence-case" else "qPCR collection at 99 mL"
            document.save(protocol_path)
            defects = [f for f in quality.deterministic_content_check(revision, source)
                       if f.get("field") == "procedures.visit_schedule"]
            if change == "sentence-case":
                assert defects == []
            else:
                assert defects and all(f["owner"] == "construction"
                                      and f["action"] == "rebuild_deterministic_structure" for f in defects)
            assert not (run / "output").exists()
            observed["drafts"] = accepted_bytes()
            observed["mutated"] = True
        return real_process(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", office_process)

    def runner(handoffs, _remaining):
        for handoff in handoffs:
            request_path = revision / handoff["request_path"]
            request = json.loads(request_path.read_text())
            if "verification-requests" in handoff["request_path"]:
                observed["reviews"].add(request["review_set"])
                workflow._save_verification_response(revision, request_path, acceptance_verification)
            else:
                if observed["mutated"]:
                    pytest.fail("A generated table must not redispatch accepted prose.")
                response_path = revision / request["response_path"]
                response_path.parent.mkdir(parents=True, exist_ok=True)
                response_path.write_text(json.dumps(drafting.recorded_acceptance_response(request)))

    result = workflow.run_desktop_operation(run, handoff_runner=runner,
        opener=lambda path: Path(path).read_bytes(), operation_id="schedule-replay",
        release_identity={"package_fingerprint": "synthetic-schedule-test"})
    assert result["status"] == "passed", result
    assert result["delivery"]["confirmed"]
    assert sorted(result["client_outputs"]) == ["output/icf.docx", "output/protocol.docx", "output/study.xml"]
    assert result["desktop_reply"]["message"].startswith("Complete verified Branch Document Set delivered.")
    assert observed["mutated"] and observed["reviews"]
    assert accepted_bytes() == observed["drafts"]
    assert json.loads(reference_path.read_text())["approval"] == approval
    state = json.loads((run / "logs/desktop-operation-schedule-replay.json").read_text())
    assert state["deadline_at_epoch"] - state["started_at_epoch"] == 2700
    protocol = Document(run / "output/protocol.docx")
    table = next(t for t in protocol.tables if t.rows[0].cells[0].text.strip() == "Activity")
    assert contracts.protocol_table_rows_match(contracts.protocol_table_contracts(source)["schedule-of-assessments"],
                                             [[cell.text for cell in row.cells] for row in table.rows])
    assert "qPCR collection at 99 mL" not in [row.cells[0].text for row in table.rows]
    manifest = json.loads((revision / "delivery-manifest.json").read_text())
    for item in manifest["client_outputs"]:
        delivered = run / item["path"]
        assert delivered.read_bytes() == (revision / "candidate" / delivered.name).read_bytes()
        assert quality.sha256_file(delivered) == item["sha256"]


@pytest.mark.parametrize("label", ["demographics", "medical history", "distance-corrected defocus curve",
                                  "adverse event and device deficiency monitoring", "exit form"])
def test_sentence_case_descriptor_is_not_a_clinical_change(label):
    contract = {"section_id": "evaluation-procedures", "header_rows": 1,
                "rows": [["Activity", "Visit 1"], [label, "X"]]}
    assert contracts.protocol_table_rows_match(contract, [["Activity", "Visit 1"], [label[0].upper() + label[1:], "X"]])


@pytest.mark.parametrize("rows", [
    [["Activity", "Visit 1", "Visit 2"], ["qPCR collection at 99 mL", "X", ""], ["medical history", "", "X"]],
    [["Activity", "Visit 1", "Visit 2"], ["qPCR collection at 5 ML", "X", ""], ["medical history", "", "X"]],
    [["Activity", "Visit 1", "Visit 2"], ["QPCR collection at 5 mL", "X", ""], ["medical history", "", "X"]],
    [["Activity", "Visit 1", "Visit 2"], ["qPCR collection at 5 mL", "", "X"], ["medical history", "", "X"]],
    [["Activity", "Visit 2", "Visit 1"], ["qPCR collection at 5 mL", "X", ""], ["medical history", "", "X"]],
    [["Activity", "Visit 1", "Visit 2"], ["medical history", "", "X"], ["qPCR collection at 5 mL", "X", ""]],
    [["Activity", "Visit 1", "Visit 2"], ["qPCR collection at 5 mL", "X", ""]],
    [["Activity", "Visit 1", "Visit 2"], ["qPCR collection at 5 mL", "X"], ["medical history", "", "X"]],
    [["Activity", "Visit 1", "Visit 2"], ["qPCR collection at 5 mL", "X", ""], ["medical history", "", "X"], ["medical history", "", "X"]],
    [["Activity", "Visit 1", "Visit 2"], ["qPCR collection at 5 mL", "x", ""], ["medical history", "", "X"]],
])
def test_clinical_cells_and_source_relationships_remain_exact(rows):
    contract = {"section_id": "evaluation-procedures", "header_rows": 1,
        "rows": [["Activity", "Visit 1", "Visit 2"], ["qPCR collection at 5 mL", "X", ""], ["medical history", "", "X"]]}
    assert not contracts.protocol_table_rows_match(contract, rows)
