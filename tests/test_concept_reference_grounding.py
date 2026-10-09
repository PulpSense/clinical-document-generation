"""Brief source references can proceed to review without copying owning sections."""

import json
from pathlib import Path

import drafting
import quality
import rendering
import pytest
from contracts import batch_plan


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PLAN = (
    "For variables measured on a continuous scale, summaries will include the sample "
    "size, mean, standard deviation, median, minimum, and maximum. For variables "
    "measured on a categorical scale, summaries will provide the number and percentage "
    "of subjects who provided each score or change in scores. These summaries will "
    "be provided for all eyes completing the study."
)


def considerations_request(tmp_path, plan=ANALYSIS_PLAN):
    reference = json.loads(
        (ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text()
    )
    reference["statistics"].update({"analysis_plan": plan, "software": None})
    batch = next(
        item for item in batch_plan("Prospective")
        if item.batch_id == "protocol-analysis-and-oversight"
    )
    request_path = drafting.create_drafting_request(
        repo_root=ROOT, revision_dir=tmp_path, revision_id="r-descriptive",
        reference=reference, batch=batch,
        target_ids=("analysis-plan.considerations",),
        attempts={"analysis-plan.considerations": 1}, wave="initial",
    )
    return json.loads(request_path.read_text()), reference


def considerations_response(request, text):
    response = drafting.response_template(request, model_id="recorded-client-run")
    response["section_results"] = [{
        "section_id": "analysis-plan.considerations", "outcome": "drafted",
        "paragraphs": [{"text": text,
                        "evidence_refs": ["source:statistics.analysis_plan"],
                        "boilerplate_refs": []}],
        "lists": [],
    }]
    return response


@pytest.mark.parametrize("text", [
    "Results will be interpreted descriptively to characterize the observed outcomes.",
    "Results will be interpreted within the descriptive scope of the approved analysis plan.",
    "Results will be interpreted descriptively, reflecting the observed continuous-scale "
    "variables and the distribution of subjects' categorical scores or changes in scores.",
    "Interpretation of variables measured on continuous and categorical scales is descriptive, "
    "characterizing the observed measurements and the number and percentage of subjects "
    "providing each score or change in scores.",
    "Results will be interpreted descriptively, characterizing variables measured on "
    "continuous and categorical scales, including scores or changes in scores.",
    "Results should be interpreted descriptively, reflecting the planned summaries of "
    "variables measured on continuous and categorical scales.",
])
def test_descriptive_interpretation_without_literal_source_keyword_is_accepted(tmp_path, text):
    request, _reference = considerations_request(tmp_path)
    response = considerations_response(request, text)

    accepted, findings = drafting.validate_response(request, response)

    assert [item["section_id"] for item in accepted["drafts"]] == [
        "analysis-plan.considerations"
    ]
    assert findings
    assert all(item.get("publication_disposition") == "warning" for item in findings)
    assert accepted["drafts"][0]["warnings"] == findings


def test_concept_warning_survives_ingestion_and_reaches_independent_review(tmp_path):
    request, reference = considerations_request(tmp_path)
    response = considerations_response(
        request, "Results will be interpreted descriptively to characterize the observed outcomes."
    )
    response_path = tmp_path / request["response_path"]
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(json.dumps(response))

    assert drafting.ingest_responses(tmp_path, request["governing_resources"]) == []
    draft = drafting.accepted_draft(
        tmp_path, "analysis-plan.considerations", request["governing_resources"]
    )
    assert draft is not None
    assert draft["warnings"]
    assert not (tmp_path / "hermes/rejected").exists()
    rendering.render_documents(ROOT, tmp_path, reference, drafting.merged_drafts(tmp_path, reference, request["governing_resources"]))
    paths = quality.create_verification_requests(tmp_path, reference, {"artifacts": []})
    content_request = json.loads(paths[0].read_text())
    cautions = [item for item in content_request["lexical_review_cautions"]
                if item["section_id"] == "analysis-plan.considerations"]
    assert cautions
    assert all(item["section_id"] == "analysis-plan.considerations" for item in cautions)
    assert all(warning in [item["caution"] for item in cautions] for warning in draft["warnings"])


@pytest.mark.parametrize("citation", [[], ["source:study.title"]])
def test_missing_or_unrelated_citation_still_rejects_concept_draft(tmp_path, citation):
    request, _reference = considerations_request(tmp_path)
    response = considerations_response(request, "Results will be interpreted descriptively.")
    response["section_results"][0]["paragraphs"][0]["evidence_refs"] = citation

    accepted, findings = drafting.validate_response(request, response)

    assert accepted["drafts"] == []
    assert any(item.get("publication_disposition") != "warning" for item in findings)


def test_unobserved_narrative_number_requires_source_grounded_review(tmp_path):
    request, _reference = considerations_request(
        tmp_path, "Interpret results cautiously because the sample size is 35."
    )
    response = considerations_response(request, "Results will be interpreted cautiously.")

    accepted, findings = drafting.validate_response(request, response)

    assert accepted["drafts"]
    assert any(
        "statistics.analysis_plan" in item["issue"]
        and item.get("publication_disposition") == "warning"
        for item in findings
    )
