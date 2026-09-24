"""Regression checks for section ownership exposed by reviewer feedback."""

import json
from pathlib import Path

from contracts import batch_plan, protocol_contract
from drafting import _coverage_findings, create_drafting_request
from quality import create_verification_requests


ROOT = Path(__file__).resolve().parents[1]


def _source():
    return json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text())


def test_objectives_request_asks_for_purpose_without_endpoint_inventory(tmp_path):
    source = _source()
    batch = next(item for item in batch_plan("Prospective") if item.batch_id == "protocol-foundations")
    path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-editorial-objectives",
        reference=source,
        batch=batch,
        attempts={section_id: 1 for section_id in batch.section_ids},
        wave="initial",
    )
    request = json.loads(path.read_text())
    sections = {item["section_id"]: item for item in request["section_contracts"]}
    objectives = sections["objectives"]
    design = sections["study-design.design"]

    assert "endpoint-inventory" not in objectives["concept_ownership"]["owns"]
    assert "endpoint-inventory" in design["concept_ownership"]["owns"]
    assert "endpoints.secondary" not in objectives["minimum_evidence"]
    assert "endpoints.other" not in objectives["minimum_evidence"]
    assert {"endpoints.primary", "endpoints.secondary", "endpoints.other"} <= set(design["minimum_evidence"])


def test_methods_and_schedule_requests_do_not_demand_irrelevant_restatement():
    sections = {item.section_id: item for item in protocol_contract("Prospective")}
    assert "study.hypothesis" not in sections["study-procedure.measurements"].evidence
    assert sections["evaluation-procedures"].source_coverage == "table_with_notes"
    assert "statistics.analysis_plan" in sections["analysis-plan.considerations"].evidence
    assert sections["analysis-plan.considerations"].boilerplate_key is None
    assert any("operational detail" in item for item in sections["confidentiality"].content_expectations)

    boilerplate = json.loads((ROOT / "references/fixed-clinical-boilerplate.json").read_text())
    assert "unscheduled visit" in boilerplate["sections"]["unscheduled"].casefold()
    assert "unscheduled contact" not in boilerplate["sections"]["unscheduled"].casefold()


def test_schedule_prose_accepts_brief_table_introduction():
    source = _source()
    request = {"approved_source": source}
    contract = {
        "source_coverage": "table_with_notes",
        "minimum_evidence": ["procedures.assessments", "procedures.visit_schedule_table"],
    }
    assert not _coverage_findings(
        request, contract, "evaluation-procedures",
        "The scheduled visits and study assessments are shown in Table 15.1.",
        ["source:procedures.visit_schedule_table"],
    )


def test_content_review_explicitly_checks_section_purpose_and_editorial_relevance(tmp_path):
    request = json.loads(create_verification_requests(tmp_path, _source(), {"artifacts": []})[0].read_text())
    instructions = request["instructions"].casefold()
    assert "section purpose" in instructions
    assert "redundant" in instructions
    assert "self-referential" in instructions
