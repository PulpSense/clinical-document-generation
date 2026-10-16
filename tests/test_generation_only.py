"""Controlled construction tests; no live model or clinical-quality claims."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from docx import Document
from xml.etree import ElementTree

import drafting
import prs_xml
import rendering
import workflow

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def office_refresh(monkeypatch):
    """Workflow tests isolate office processing; real pagination has separate coverage."""
    calls = []
    def refresh(path):
        calls.append(path)
        return {"status": "passed", "renderer": "controlled-test-double"}
    monkeypatch.setattr(workflow, "refresh_protocol_fields", refresh)
    return calls


@pytest.mark.parametrize("extra_args", [[], ["--generation-only"]])
def test_public_generate_command_uses_experimental_drafting(tmp_path, extra_args):
    approved_run(tmp_path)
    process = subprocess.run(
        [sys.executable, str(ROOT / "scripts/workflow.py"), "--run-dir", str(tmp_path),
         "--stage", "generate", *extra_args], capture_output=True, text=True, check=True)
    result = json.loads(process.stdout)
    assert result["mode"] == "generation_only"
    assert result["status"] == "awaiting_hermes"
    assert result["handoffs"]
    assert all(item["task"] in {"section_drafting", "prs_narrative_drafting"}
               for item in result["handoffs"])


def approved_run(path, branch="Prospective", family="Sterling"):
    source = json.loads((ROOT / f"tests/fixtures/release-certification/{branch.lower()}"
                         f"{'-' + family.lower() if branch != 'Retrospective' else ''}/approved-reference.json").read_text())
    reference = path / "reference/study.reference.json"
    reference.parent.mkdir(parents=True)
    reference.write_text(json.dumps(source))
    assert workflow.prepare(path)["status"] == "awaiting_approval"
    assert workflow.approve(path, approved_by="controlled-test-owner")["status"] == "passed"


def complete(path):
    result = workflow.generate_only(path)
    for _ in range(4):
        if result["status"] != "awaiting_hermes":
            return result
        workspace = Path(result["workspace"])
        for relative in result["requests"]:
            request = json.loads((workspace / relative).read_text())
            assert request["task"] in {"section_drafting", "prs_narrative_drafting"}
            response = drafting.recorded_acceptance_response(request)
            (workspace / request["response_path"]).write_text(json.dumps(response))
        result = workflow.generate_only(path)
    pytest.fail(f"Experiment did not finish: {result}")


@pytest.mark.parametrize("branch,family", [("Prospective", "Advarra"), ("Prospective", "Sterling"),
                                           ("Ambispective", "Advarra"), ("Ambispective", "Sterling"),
                                           ("Retrospective", None)])
def test_complete_native_set_without_post_generation_gates(tmp_path, monkeypatch, branch, family, office_refresh):
    approved_run(tmp_path, branch, family)

    def unexpected(*_args, **_kwargs):
        pytest.fail("Generation-only called a post-generation gate or repair")

    for name in ("render_assurance", "create_verification_requests", "quality_report", "_quality_retry",
                 "_schedule_native_repair", "_publish"):
        assert not hasattr(workflow, name)
    monkeypatch.setattr(rendering, "audit_docx", unexpected)
    monkeypatch.setattr(prs_xml, "validate_output", unexpected)
    monkeypatch.setattr(prs_xml, "quality_report", unexpected)
    result = complete(tmp_path)
    assert result["status"] == "unreviewed", result
    assert not result["client_outputs"]
    expected = {"protocol.docx"}
    if branch != "Retrospective":
        expected |= {"icf.docx", "study.xml"}
    assert {Path(item["absolute_path"]).name for item in result["experimental_outputs"]} == expected
    minutes, seconds = divmod(round(result['elapsed_seconds'], 2), 60)
    assert result["delivery_message"] == "Here are the documents:\n\n" + "\n".join(
        f"- [{Path(item['absolute_path']).name}](<{item['absolute_path']}>)"
        for item in result["experimental_outputs"]) + f"\n\nGeneration time: {int(minutes)} minutes {seconds:.2f} seconds."
    for entry in result["experimental_outputs"]:
        file = Path(entry["absolute_path"])
        assert file.is_file()
        Document(file) if file.suffix == ".docx" else ElementTree.parse(file)
    workspace = Path(result["workspace"])
    assert not list(workspace.rglob("*.pdf"))
    assert not (workspace / "verification").exists()
    assert {path.name for path in (tmp_path / "output").iterdir()} == expected
    assert not (tmp_path / "generation-only-output").exists()
    assert Path(result["notice"]).parent == workspace
    for name in expected:
        assert list(tmp_path.rglob(name)) == [tmp_path / "output" / name]
    assert workflow.generate_only(tmp_path) == result
    assert office_refresh == [workspace / "candidate/protocol.docx"]
    file = Path(result["experimental_outputs"][0]["absolute_path"])
    file.write_bytes(b"changed")
    assert workflow.generate_only(tmp_path)["stage"] == "file_integrity"


def test_office_failure_returns_construction_feedback_without_publishing(tmp_path, monkeypatch):
    approved_run(tmp_path)
    calls = []
    def unavailable(path):
        calls.append(path)
        raise RuntimeError("Office field-refresh executable is unavailable.")
    monkeypatch.setattr(workflow, "refresh_protocol_fields", unavailable)
    result = complete(tmp_path)
    assert result["status"] == "blocked"
    assert result["stage"] == "office_field_refresh"
    assert len(calls) == 1
    assert not list(tmp_path.glob("generation-only-output/**/*"))
    assert not (tmp_path / "output").exists()


def test_existing_output_is_preserved(tmp_path):
    approved_run(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    existing = output / "protocol.docx"
    existing.write_bytes(b"existing document")
    result = complete(tmp_path)
    assert result["stage"] == "output_conflict"
    assert existing.read_bytes() == b"existing document"
    assert not (tmp_path / "generation-only-output").exists()


def test_n8n_prompts_keep_original_messages_and_resolve_inputs(tmp_path):
    approved_run(tmp_path)
    result = workflow.generate_only(tmp_path)
    workspace = Path(result["workspace"])
    library = json.loads((ROOT / "references/generation-only-n8n-prompts.json").read_text())
    mapped, fallback = set(), set()
    for relative in result["requests"]:
        request = json.loads((workspace / relative).read_text())
        profile = request["generation_only_prompts"]
        assert drafting._trusted_request_valid(workspace, request)
        fallback.update(profile["current_instruction_targets"])
        for prompt in profile["prompts"]:
            assert prompt["original_messages"] == library["nodes"][prompt["node"]]["messages"]
            assert all("{{" not in message["content"] for message in prompt["messages"])
            mapped.update(item["section_id"] for item in prompt["targets"])
        if profile["prompts"]:
            changed = copy.deepcopy(request)
            changed["generation_only_prompts"]["prompts"][0]["messages"][0]["content"] += "tampered"
            assert not drafting._trusted_request_valid(workspace, changed)
    assert {"introduction", "subjects.population", "icf.study-purpose", "icf.procedures"} <= mapped
    assert {"confidentiality", "icf.privacy", "icf.injury"} <= fallback


def test_source_approval_remains_required_and_bound(tmp_path):
    approved_run(tmp_path)
    reference = json.loads((tmp_path / "reference/study.reference.json").read_text())
    source = tmp_path / reference["source"]["source_of_truth_file"]
    source.write_text(source.read_text() + "\nChanged after approval.\n")
    result = workflow.generate_only(tmp_path)
    assert result["stage"] == "approval_gate"
    assert not list(tmp_path.rglob("generation-only.json"))


def test_prompt_inputs_preserve_approved_articles_and_regulatory_aliases():
    source = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text())
    source["design"]["test_articles"] = "Approved test device"
    source["design"]["control_articles"] = "Approved comparator"
    source["regulatory"]["fda_regulated_device"] = "Yes"
    source["regulatory"]["prs"].pop("fda_regulated_device", None)
    payload = drafting.generation_only_prompt_payload(ROOT, source, [{"section_id": "introduction"}])
    input_message = payload["prompts"][0]["messages"][-1]["content"]
    assert "Approved test device" in input_message
    assert "Approved comparator" in input_message
    assert "Yes" in input_message


def test_response_shape_can_be_fixed_without_a_review_or_repair_loop(tmp_path):
    approved_run(tmp_path)
    result = workflow.generate_only(tmp_path)
    workspace = Path(result["workspace"])
    request = json.loads((workspace / result["requests"][0]).read_text())
    response = drafting.recorded_acceptance_response(request)
    response["section_results"][0]["paragraphs"] = [{"text": ""}]
    response["section_results"][0]["lists"] = []
    file = workspace / request["response_path"]
    file.write_text(json.dumps(response))
    assert workflow.generate_only(tmp_path)["stage"] == "drafting_response"
    # No evidence-ref or interpretation metadata is required for the experiment.
    response = drafting.recorded_acceptance_response(request)
    for item in response["section_results"]:
        item.pop("schedule_interpretation", None)
        item.pop("benefit_interpretation", None)
        item["paragraphs"] = [{"text": "A deliberately unreviewed controlled test paragraph."}]
        item["lists"] = []
    file.write_text(json.dumps(response))
    assert workflow.generate_only(tmp_path)["status"] == "awaiting_hermes"
    assert (workspace / "hermes/accepted-requests" / file.name).is_file()
