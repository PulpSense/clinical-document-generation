"""Synthetic minimized blocked-wording replay, not captured archive or fresh review.

Real ingestion, construction, exact-artifact checks and Desktop publication run.
Controlled responders provide no independent clinical or visual certification.
"""
from finding_policy import blocks_construction
import copy
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document
import pytest

import drafting
import quality
import workflow
from test_concept_reference_grounding import ANALYSIS_PLAN
from test_handoff_quality import acceptance_verification

ROOT = Path(__file__).resolve().parents[1]
TEXTS = (
    "Results will be interpreted descriptively to characterize the observed outcomes.",
    "Results will be interpreted within the descriptive scope of the approved analysis plan.",
)


def _run(tmp_path, branch, family, profile=None):
    text = "Interpret results descriptively." if profile == "sparse" else TEXTS[0]
    run = tmp_path / "controlled-replay"
    reference_path = run / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    source = json.loads((ROOT / f"tests/fixtures/{branch.lower()}-acceptance-source.json").read_text())
    source["meta"]["icf_template"] = family
    source["statistics"].update(analysis_plan=ANALYSIS_PLAN, software=None)
    if profile == "rich":
        source["study"]["background"] += " Personnel collect observations during scheduled visits and use reminder calls to support follow-up.[7]\nReferences:\n7. Doe A. Monitoring study. 2026;20:1-8. doi:10.1234/example."
        source["procedures"]["retention"] = "Personnel will telephone enrolled participants to remind them about scheduled follow-up appointments."
        source["statistics"]["analysis_plan"] += " Interpret results cautiously because the sample size is 40."
        text = "Interpret results cautiously because the sample size is forty."
        if branch != "Retrospective":
            source["procedures"]["minimum_days_before_screening_without_participation"] = "ninety days"
            source["population"]["inclusion_criteria"].append("No participation in other research for ninety days before screening.")
    if profile == "review-fixes":
        source["procedures"]["completion"] = "Participant completion requires attendance at the final assessment."
        source["study"]["completion"] = "Study closeout requires verification of all case records."
        if branch == "Retrospective":
            source["population"]["inclusion_criteria"] = ["Records describe adults who underwent cataract extraction."]
        else:
            source["study"].update(title="Monitoring recovery", short_title="Monitoring recovery",
                hypothesis="Monitoring describes recovery.", timeline="3 months")
            source["objectives"]["primary"] = ["Describe recovery."]
            source["endpoints"]["primary"] = [{"label": "Recovery", "time_point": "Month 3"}]
            source["design"]["study_design"] = "Observational monitoring study."
    source["approval"] = {"status": "draft"}
    reference_path.write_text(json.dumps(source))
    assert workflow.prepare(run)["status"] == "awaiting_approval"
    assert workflow.approve(run, approved_by="Synthetic controlled replay")["status"] == "passed"
    approved = json.loads(reference_path.read_text())
    revision = run / "revisions" / approved["approval"]["revision_id"]
    approval = copy.deepcopy(approved["approval"])
    observed = {"draft_attempts": 0, "review_cautions": []}

    def review(request):
        response = acceptance_verification(request)
        if profile and request["task"] == "clinical_content_verification":
            response["status"] = "blocked"
            for row in response["section_assessments"]:
                if row["section_id"] == "objectives":
                    row["status"] = "blocked"
            response["findings"] = [{
                "finding_id": "controlled-editorial", "category": "content", "check": "editorial_relevance",
                "artifact": "protocol", "target_ids": ["objectives"],
                "issue": "The source-derived synopsis is concise but repetitive.",
                "affected_passage": "Study synopsis", "recommended_action": "Optional wording improvement",
                "material": False, "safety_critical": False, "contradiction": False,
                "obscures_required_information": False, "materially_unusable": False,
            }]
        return response

    def runner(handoffs, _remaining):
        for handoff in handoffs:
            request_path = revision / handoff["request_path"]
            request = json.loads(request_path.read_text())
            if "verification-requests" in handoff["request_path"]:
                if request["task"] == "clinical_content_verification":
                    observed["review_cautions"].extend(request["lexical_review_cautions"])
                workflow._save_verification_response(revision, request_path, review)
                continue
            response = drafting.recorded_acceptance_response(request)
            if profile == "review-fixes" and request["artifact"] == "prs":
                response["narrative"]["brief_summary"]["text"] = "Observational monitoring measures recovery after three months."
            for item in list(response.get("section_results", [])):
                if profile == "review-fixes":
                    replacements = {
                        "endpoint-criteria.completion": "Subjects finish participation once they attend the last evaluation.",
                        "endpoint-criteria.study-completion": "The project ends after every participant file has been checked. The planned timeline is 3 months.",
                        "icf.duration": "Participation lasts three months.",
                    }
                    if item["section_id"] in replacements:
                        item["paragraphs"][0]["text"] = replacements[item["section_id"]]
                    if branch == "Retrospective" and item["section_id"] == "subjects.eligibility":
                        for paragraph in item.get("paragraphs", []):
                            paragraph["text"] = paragraph["text"].replace("Records describe adults who underwent cataract extraction.", "Files concern grown patients treated by removing a clouded lens.")
                        for group in item.get("lists", []):
                            group["items"] = [value.replace("Records describe adults who underwent cataract extraction.", "Files concern grown patients treated by removing a clouded lens.") for value in group["items"]]
                if item["section_id"] == "analysis-plan.methodology":
                    item["paragraphs"][0]["text"] = source["statistics"]["analysis_plan"]
                if item["section_id"] != "analysis-plan.considerations":
                    continue
                observed["draft_attempts"] += 1
                item["paragraphs"] = [{"text": text, "evidence_refs": ["source:statistics.analysis_plan"], "boilerplate_refs": []}]
                item["lists"] = []
            path = revision / request["response_path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(response))

    result = workflow.run_desktop_operation(
        run, handoff_runner=runner, opener=lambda path: Path(path).read_bytes(),
        operation_id="synthetic-blocked-wording", release_identity={"package_fingerprint": "controlled-source-test"},
    )
    assert result["status"] == "passed", result
    assert result["stage"] == "desktop_delivery"
    assert result["delivery"]["confirmed"] is True
    expected = ["output/protocol.docx"] if branch == "Retrospective" else ["output/icf.docx", "output/protocol.docx", "output/study.xml"]
    assert sorted(result["client_outputs"]) == expected
    assert sorted(p.name for p in (run / "output").iterdir()) == [Path(p).name for p in expected]
    assert result["desktop_reply"]["delivery_status"] == "confirmed"
    assert result["desktop_reply"]["message"].startswith("Complete verified Branch Document Set delivered.")
    if observed["review_cautions"]:
        assert "Reviewer-resolved wording uncertainty — Protocol" in result["desktop_reply"]["message"]
    assert json.loads(reference_path.read_text())["approval"] == approval
    state = json.loads((run / "logs/desktop-operation-synthetic-blocked-wording.json").read_text())
    assert state["deadline_at_epoch"] - state["started_at_epoch"] == 2700
    manifest = json.loads((revision / "delivery-manifest.json").read_text())
    for item in manifest["client_outputs"]:
        delivered = run / item["path"]
        assert delivered.read_bytes() == (revision / "candidate" / delivered.name).read_bytes()
        assert quality.sha256_file(delivered) == item["sha256"]
    protocol = Document(run / "output/protocol.docx")
    body = "\n".join(p.text for p in protocol.paragraphs)
    assert text in body
    assert "lexical-evidence-uncertainty" not in body
    assert source["study"]["title"] in body
    table_text = "\n".join(cell.text for table in protocol.tables for row in table.rows for cell in row.cells)
    assert "40 participants" in body + table_text
    assert ("Recovery" if profile == "review-fixes" and branch != "Retrospective" else "Primary outcome") in body + table_text
    assert "Month" in body + table_text
    if branch != "Retrospective":
        xml = ET.parse(run / "output/study.xml")
        assert next(xml.getroot().iter("enrollment")).text == "40"
        consent = Document(run / "output/icf.docx")
        consent_text = "\n".join(p.text for p in consent.paragraphs).casefold()
        assert "voluntary" in consent_text
        assert "lexical-evidence-uncertainty" not in consent_text
    assert quality.deterministic_content_check(revision, source) == [] or all(
        not blocks_construction(f)
        for f in quality.deterministic_content_check(revision, source)
    )
    return result, observed, manifest



@pytest.mark.parametrize("branch,family", [("Retrospective", "Advarra"), ("Prospective", "Advarra"),
    ("Prospective", "Sterling"), ("Ambispective", "Advarra"), ("Ambispective", "Sterling")])
def test_complete_verified_branch_set_and_truthful_message(tmp_path, governed_pdfium, branch, family):
    result, observed, manifest = _run(tmp_path, branch, family)
    assert observed["review_cautions"]
    assert manifest["quality"]["final_exact_artifact_review"]["every_page"] is True
    assert manifest["quality"]["resolved_evidence_cautions"]
    assert any(c.get("resolution") == "independent_content_review_passed"
               for c in result["desktop_reply"]["cautions"])


@pytest.mark.parametrize("branch,family", [("Retrospective", "Advarra"), ("Prospective", "Advarra"),
    ("Prospective", "Sterling"), ("Ambispective", "Advarra"), ("Ambispective", "Sterling")])
@pytest.mark.parametrize("profile", ["sparse", "rich"])
def test_sparse_and_rich_complete_sources_deliver_with_controlled_editorial_review(tmp_path, governed_pdfium, branch, family, profile):
    result, observed, manifest = _run(tmp_path, branch, family, profile=profile)
    assert observed["draft_attempts"] == 1
    assert any(c.get("check") == "editorial_relevance" for c in result["desktop_reply"]["cautions"])
    assert manifest["quality"]["final_exact_artifact_review"]["every_page"] is True
    if profile != "rich":
        assert manifest["quality"]["resolved_evidence_cautions"]


@pytest.mark.parametrize("branch,family", [("Prospective", "Advarra"), ("Retrospective", "Advarra")])
def test_review_paraphrases_and_concise_sections_deliver_actual_branch_set(tmp_path, governed_pdfium, branch, family):
    result, observed, manifest = _run(tmp_path, branch, family, profile="review-fixes")
    assert manifest["quality"]["final_exact_artifact_review"]["every_page"] is True
    assert observed["draft_attempts"] == 1
    targets = {c["section_id"] for c in observed["review_cautions"]}
    if branch == "Prospective":
        assert {"icf.duration", "prs.brief-summary", "endpoint-criteria.completion", "endpoint-criteria.study-completion"} <= targets
    else:
        assert "subjects.eligibility" in targets
    assert all(c.get("resolution") == "independent_content_review_passed" for c in manifest["quality"]["resolved_evidence_cautions"])
