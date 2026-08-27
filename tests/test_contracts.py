import copy
import json
from pathlib import Path

import pytest

from contracts import ICF_STUDY_SECTIONS, PROSPECTIVE_REQUIRED, RETROSPECTIVE_REQUIRED, DOCUMENT_SETS, batch_plan, icf_contract, input_findings, parse_source_truth, protocol_contract, source_truth_markdown


ROOT = Path(__file__).resolve().parents[1]


def fixture(name):
    return json.loads((ROOT / "tests/fixtures" / name).read_text(encoding="utf-8"))


def test_branch_document_sets_are_exact():
    assert DOCUMENT_SETS["Prospective"] == ("protocol.docx", "icf.docx", "study.xml")
    assert DOCUMENT_SETS["Ambispective"] == ("protocol.docx", "icf.docx", "study.xml")
    assert DOCUMENT_SETS["Retrospective"] == ("protocol.docx",)


def test_branch_section_contracts_have_no_duplicate_ids_and_expected_roots():
    for branch, last_root in (("Prospective", "19."), ("Ambispective", "19."), ("Retrospective", "13.")):
        sections = protocol_contract(branch)
        assert len({item.section_id for item in sections}) == len(sections)
        assert any(item.number == last_root for item in sections)


def test_parallel_drafting_topology_and_prs_dependency():
    plan = {batch.batch_id: batch for batch in batch_plan("Prospective")}
    assert not plan["protocol-foundations"].prerequisites
    assert not plan["protocol-operations"].prerequisites
    assert not plan["protocol-analysis-and-oversight"].prerequisites
    assert not plan["icf-narrative"].prerequisites
    assert plan["prs-narrative"].prerequisites == ("protocol-foundations",)


def test_icf_contract_is_template_and_branch_specific_for_research_injury():
    prospective_advarra = {section.section_id for section in icf_contract("Prospective", "Advarra")}
    prospective_sterling = {section.section_id for section in icf_contract("Prospective", "Sterling")}
    ambispective_advarra = {section.section_id for section in icf_contract("Ambispective", "Advarra")}

    assert "icf.injury" not in prospective_advarra
    assert "icf.injury" in prospective_sterling
    assert "icf.injury" in ambispective_advarra


def test_screening_washout_is_contractually_bound_to_protocol_and_icf():
    protocol = {section.section_id: section for section in protocol_contract("Prospective")}
    icf = {section.section_id: section for section in ICF_STUDY_SECTIONS}

    assert "procedures.minimum_days_before_screening_without_participation" in protocol["subjects.inclusion"].evidence
    assert "procedures.minimum_days_before_screening_without_participation" in icf["icf.procedures"].evidence


def test_hypothesis_and_endpoints_are_bound_to_the_sections_that_explain_them():
    protocol = {section.section_id: section for section in protocol_contract("Prospective")}
    icf = {section.section_id: section for section in ICF_STUDY_SECTIONS}

    assert {"study.hypothesis", "endpoints.primary"} <= set(protocol["introduction"].evidence)
    assert {"study.hypothesis", "endpoints.primary", "endpoints.secondary"} <= set(protocol["objectives"].evidence)
    assert {"study.hypothesis", "endpoints.primary", "endpoints.secondary"} <= set(protocol["study-procedure.measurements"].evidence)
    assert {"endpoints.primary", "endpoints.secondary"} <= set(protocol["analysis-plan.methodology"].evidence)
    assert {"study.hypothesis", "endpoints.primary"} <= set(icf["icf.study-purpose"].evidence)


def test_protocol_confidentiality_uses_substantive_confidentiality_boilerplate():
    protocol = {section.section_id: section for section in protocol_contract("Ambispective")}

    assert protocol["ethics.confidentiality"].boilerplate_key == "confidentiality-cross-reference"


def test_each_drafting_batch_exposes_every_source_family_required_by_its_sections():
    for branch in ("Prospective", "Ambispective", "Retrospective"):
        sections = {section.section_id: section for section in protocol_contract(branch)}
        if branch != "Retrospective":
            sections.update({section.section_id: section for section in ICF_STUDY_SECTIONS})

        for batch in batch_plan(branch):
            if batch.artifact == "prs":
                continue
            exposed = set(batch.field_families)
            for section_id in batch.section_ids:
                required = {path.split(".", 1)[0] for path in sections[section_id].evidence}
                assert required <= exposed, (
                    f"{branch} {batch.batch_id} omits source families required by "
                    f"{section_id}: {sorted(required - exposed)}"
                )


def test_every_leaf_section_has_required_evidence_or_controlled_boilerplate():
    for branch, requirements in (("Prospective", PROSPECTIVE_REQUIRED), ("Ambispective", PROSPECTIVE_REQUIRED), ("Retrospective", RETROSPECTIVE_REQUIRED)):
        required_paths = {path for item in requirements for path in (item.field, *item.aliases)}
        sections = list(protocol_contract(branch))
        if branch != "Retrospective":
            sections.extend(ICF_STUDY_SECTIONS)
        unsupported = [
            section.section_id
            for section in sections
            if section.role != "container"
            and not section.boilerplate_key
            and not required_paths.intersection(section.evidence)
        ]
        assert unsupported == []


def test_all_acceptance_sources_satisfy_mandatory_inputs():
    for name in ("prospective-acceptance-source.json", "ambispective-acceptance-source.json", "retrospective-acceptance-source.json"):
        assert input_findings(fixture(name)) == []


def test_source_markdown_round_trip_preserves_nested_site_investigator():
    reference = fixture("prospective-acceptance-source.json")
    parsed = parse_source_truth(source_truth_markdown(reference), reference)
    assert parsed["sites"][0]["investigators"][0]["name"] == "Alex Investigator"
    assert parsed["procedures"]["visit_schedule_table"][2]["visitName"] == "Month 3"
    assert parsed["meta"]["icf_template"] == reference["meta"]["icf_template"]
    assert not {"template_fields", "generated", "needs_review"} & set(parsed)


def test_source_markdown_rejects_deleted_or_added_field_markers():
    reference = fixture("prospective-acceptance-source.json")
    markdown = source_truth_markdown(reference)
    start = markdown.index("<!-- field: study.short_title -->")
    end = markdown.index("<!-- /field -->", start) + len("<!-- /field -->")

    with pytest.raises(ValueError, match="marker set"):
        parse_source_truth(markdown[:start] + markdown[end:], reference)

    added = markdown + "\n<!-- field: study.unexpected -->\nvalue\n<!-- /field -->\n"
    with pytest.raises(ValueError, match="marker set"):
        parse_source_truth(added, reference)


def test_missing_obligatory_input_blocks_without_filler():
    reference = fixture("prospective-acceptance-source.json")
    reference["study"]["title"] = ""
    findings = input_findings(reference)
    assert any(item["field"] == "study.title" for item in findings)


def test_conflicting_sample_size_evidence_blocks_approval():
    reference = fixture("prospective-acceptance-source.json")
    reference["population"]["sample_size"] = "80 participants"
    findings = input_findings(reference)
    assert any(item["field"] == "population.sample_size_evidence" for item in findings)
    assert any(item["field"] == "statistics.sample_size_evidence" for item in findings)


def test_schedule_cannot_extend_beyond_study_timeline():
    reference = fixture("prospective-acceptance-source.json")
    reference["procedures"]["visit_schedule_table"].append({"visitNumber": "4", "visitName": "Month 6", "visitWindow": "±14 days", "CRFnumber": "M6"})
    findings = input_findings(reference)
    assert any(item["field"] == "study.timeline" for item in findings)


def test_word_timeline_and_string_schedule_are_compared():
    reference = fixture("prospective-acceptance-source.json")
    reference["study"]["timeline"] = "three months"
    reference["procedures"]["visit_schedule"] = ["Baseline", "Month 6"]
    findings = input_findings(reference)
    assert any(item["field"] == "study.timeline" for item in findings)


def test_prs_outcomes_must_be_structured_and_have_measure_and_time_frame():
    reference = fixture("prospective-acceptance-source.json")
    reference["endpoints"]["primary"] = "Primary outcome at Month 3"
    assert any(item["field"] == "endpoints.primary" for item in input_findings(reference))
    reference["endpoints"]["primary"] = [{"label": "Primary outcome"}]
    assert any(item["field"] == "endpoints.primary.0.time_frame" for item in input_findings(reference))


def test_retrospective_multisite_count_is_not_compared_with_the_single_required_facility_row():
    reference = fixture("retrospective-acceptance-source.json")
    reference["design"]["number_of_sites"] = "3"
    reference["design"]["study_design"] = "Retrospective multicenter record review"

    assert not any(item["field"] == "design.number_of_sites" for item in input_findings(reference))
