"""Regression checks for section ownership exposed by reviewer feedback."""

import json
from pathlib import Path

from docx import Document

from contracts import batch_plan, input_findings, protocol_contract
from drafting import _coverage_findings, _section_payload, create_drafting_request
from quality import create_verification_requests
from rendering import _endpoint_synopsis, _protocol_followup_summary, _protocol_short_title, render_documents, render_fields


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
    assert "endpoint-inventory" in sections["general-information"].owned_concepts
    assert "endpoint-inventory" not in sections["general-information"].do_not_restate_concepts
    assert "study.hypothesis" not in sections["study-procedure.measurements"].evidence
    assert sections["evaluation-procedures"].source_coverage == "table_with_notes"
    assert "statistics.analysis_plan" in sections["analysis-plan.considerations"].evidence
    assert sections["analysis-plan.considerations"].boilerplate_key is None
    assert any("operational detail" in item for item in sections["confidentiality"].content_expectations)

    boilerplate = json.loads((ROOT / "references/fixed-clinical-boilerplate.json").read_text())
    assert "unscheduled visit" in boilerplate["sections"]["unscheduled"].casefold()
    assert "unscheduled contact" not in boilerplate["sections"]["unscheduled"].casefold()


def test_ambispective_descriptive_considerations_do_not_require_method_repetition():
    plan = (
        "Descriptive summaries for historical and prospective measures; paired summaries "
        "for participants with both baseline and Month 3 data."
    )
    request = {"approved_source": {"statistics": {"analysis_plan": plan}}}
    contract = {
        "section_id": "analysis-plan.considerations",
        "source_coverage": "concept_reference",
        "minimum_evidence": ["statistics.analysis_plan"],
        "evidence_scopes": [{"path": "statistics.analysis_plan", "value": plan}],
    }
    assert not _coverage_findings(
        request, contract, "analysis-plan.considerations",
        "Interpretation of historical and prospective measures is descriptive.",
        ["source:statistics.analysis_plan"],
    )
    assert _coverage_findings(
        request, contract, "analysis-plan.considerations",
        "Interpretation will follow the approved plan.",
        ["source:statistics.analysis_plan"],
    )
    qualified = "Descriptive summaries are planned; no inferential hypothesis test is planned."
    request["approved_source"]["statistics"]["analysis_plan"] = qualified
    contract["evidence_scopes"][0]["value"] = qualified
    assert _coverage_findings(
        request, contract, "analysis-plan.considerations",
        "Results will be interpreted descriptively.",
        ["source:statistics.analysis_plan"],
    )


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
    assert "unsupported clinical product claims" in instructions
    assert "generic section 16 privacy prose" in instructions
    assert "defines a completion trigger only if the source provides one" in instructions
    assert "speculative claim that the untested study combination outperforms alternatives" in instructions


def test_content_review_preserves_template_copy_sequence_and_flags_conditional_privacy_scope(tmp_path):
    request = json.loads(create_verification_requests(tmp_path, _source(), {"artifacts": []})[0].read_text())
    instructions = request["instructions"].casefold()
    assert "copy of all pages" in instructions
    assert "signed and dated copy" in instructions
    assert "existing-record collection" in instructions
    assert "privacy" in instructions


def test_optional_short_title_never_blocks_intake_and_long_titles_get_header_fallback():
    source = _source()
    source["study"].pop("short_title")
    source["study"]["title"] = (
        "Visual and Patient-Reported Outcomes after Mix-and-Match Implantation "
        "of an Extended Depth of Focus and a Trifocal Intraocular Lens"
    )
    assert not any(item["field"] == "study.short_title" for item in input_findings(source))
    assert _protocol_short_title(source) == "Visual and Patient-Reported Outcomes after Mix-and-Match Implantation"
    source["study"]["short_title"] = "PureSee and Odyssey Study"
    assert _protocol_short_title(source) == "PureSee and Odyssey Study"


def test_brad_reference_style_header_drops_generic_study_preamble():
    source = _source()
    source["study"].pop("short_title")
    source["study"]["title"] = (
        "A randomized, investigator-masked, longitudinal study evaluating "
        "long-term changes in symptoms and tear production of acoltremon "
        "ophthalmic solution 0.003% compared to control in subjects with dry eye disease"
    )
    concise = _protocol_short_title(source)
    assert concise.startswith("Long-term changes in symptoms")
    assert len(concise) <= 72


def test_general_information_uses_complete_endpoint_synopsis_and_final_visit():
    source = _source()
    synopsis = _endpoint_synopsis(source)
    assert "Primary endpoint:" in synopsis
    assert "Primary outcome (Month 3)" in synopsis
    assert "Safety outcome (Month 3)" in synopsis
    assert "Section 8.1" not in synopsis
    assert "Section 6" not in synopsis
    source["study"]["timeline"] = "Enrollment: 6 months; follow-up: 3 months; data analysis: 1 month."
    source["procedures"]["visit_schedule_table"] = [
        {"visitNumber": "1", "visitName": "Preoperative screening", "timing": "Before surgery", "procedures": []},
        {"visitNumber": "2", "visitName": "3-month postoperative visit", "timing": "3 months postoperatively", "procedures": []},
    ]
    assert _protocol_followup_summary(source) == "3 months"


def test_variables_lists_every_approved_endpoint_for_future_protocols():
    source = _source()
    source["endpoints"]["primary"].append({"label": "Additional primary measure", "time_point": "Month 6"})
    source["endpoints"]["secondary"].append({"label": "Participant symptoms", "time_point": "Month 6"})
    lines = _endpoint_synopsis(source).splitlines()
    assert lines == [
        "Primary endpoints:",
        "• Primary outcome (Month 3)",
        "• Additional primary measure (Month 6)",
        "Secondary endpoints:",
        "• Safety outcome (Month 3)",
        "• Participant symptoms (Month 6)",
    ]


def test_variables_accepts_prs_endpoint_time_frame_field():
    source = _source()
    source["endpoints"]["primary"] = [{"outcome_measure": "Visual acuity", "outcome_time_frame": "6 months"}]
    assert "Visual acuity (6 months)" in _endpoint_synopsis(source)


def test_long_title_fallback_ends_at_a_complete_phrase():
    source = _source()
    source["study"].pop("short_title", None)
    source["study"]["title"] = (
        "Visual Outcomes and Patient-Reported Symptoms after Bilateral Implantation "
        "of an Extended Depth of Focus or a Full Range of Vision Intraocular Lens"
    )
    assert _protocol_short_title(source) == "Visual Outcomes and Patient-Reported Symptoms"
    source["study"]["title"] = (
        "Clinical Evaluation of Visual Acuity and Patient Satisfaction after Surgery "
        "with TECNIS PureSee Intraocular Lenses"
    )
    assert _protocol_short_title(source) == "Clinical Evaluation of Visual Acuity and Patient Satisfaction"
    source["study"]["title"] = (
        "A Study of Visual Acuity and Patient Satisfaction in Patients with Bilateral "
        "Intraocular Lens Implantation"
    )
    assert _protocol_short_title(source) == "A Study of Visual Acuity and Patient Satisfaction"
    source["study"]["title"] = (
        "Visual Acuity and Patient Satisfaction in Adults Receiving Bilateral "
        "TECNIS PureSee Intraocular Lens Implantation"
    )
    assert _protocol_short_title(source) == "Visual Acuity and Patient Satisfaction in Adults"


def test_icf_sample_size_does_not_duplicate_template_sentence_period():
    source = _source()
    source["population"]["sample_size"] = "72 subjects total; 36 per cohort."
    assert render_fields(source, {})["sampleSize"] == "72 subjects total; 36 per cohort"


def test_completion_and_bias_contracts_do_not_require_repeated_design_or_visit_inventory():
    sections = {item.section_id: item for item in protocol_contract("Prospective")}
    assert "every approved visit" not in " ".join(sections["endpoint-criteria.study-completion"].content_expectations)
    assert "no masking" not in " ".join(sections["study-design.bias"].content_expectations)
    assert "study.timeline" in sections["endpoint-criteria.study-completion"].evidence


def test_ambispective_privacy_and_completion_requests_keep_distinct_section_owners():
    source = json.loads((ROOT / "tests/fixtures/release-certification/ambispective-sterling/approved-reference.json").read_text())
    source["confidentiality"]["data_handling"] = (
        "Study IDs replace names in the analysis dataset. The identity link is encrypted and "
        "restricted to the investigator. Records are retained for three years after closeout."
    )
    source["study"]["timeline"] = (
        "Historical record review plus prospective baseline through Month 3 follow-up, "
        "with prospective participation lasting approximately 14 weeks."
    )
    sections = {item.section_id: item for item in protocol_contract("Ambispective")}
    boilerplate = json.loads((ROOT / "references/fixed-clinical-boilerplate.json").read_text())["sections"]

    ethics = _section_payload(sections["ethics.confidentiality"], boilerplate, source)
    privacy = _section_payload(sections["confidentiality"], boilerplate, source)
    participant = _section_payload(sections["endpoint-criteria.completion"], boilerplate, source)
    study = _section_payload(sections["endpoint-criteria.study-completion"], boilerplate, source)

    assert "confidentiality.data_handling" not in ethics["minimum_evidence"]
    assert "confidentiality.data_handling" in privacy["minimum_evidence"]
    assert participant["minimum_evidence"] == ["study.timeline"]
    assert "study.timeline" in study["minimum_evidence"]
    assert "do not restate" in " ".join(ethics["content_expectations"]).casefold()
    assert "study-wide timeline" in " ".join(participant["content_expectations"]).casefold()

    source["ethics"] = {"confidentiality": "The ethics committee may inspect source records on site."}
    ethics_with_rule = _section_payload(sections["ethics.confidentiality"], boilerplate, source)
    assert "ethics.confidentiality" in ethics_with_rule["minimum_evidence"]


def test_sparse_ambispective_requests_keep_methods_interpretation_and_completion_useful():
    source = json.loads((ROOT / "tests/fixtures/release-certification/ambispective-sterling/approved-reference.json").read_text())
    source["procedures"]["methods"] = ""
    source["procedures"]["completion"] = ""
    source["study"]["timeline"] = "Historical record review plus prospective baseline through Month 3 follow-up."
    source["statistics"]["analysis_plan"] = "Descriptive summaries of historical and prospective observations."
    sections = {item.section_id: item for item in protocol_contract("Ambispective")}
    boilerplate = json.loads((ROOT / "references/fixed-clinical-boilerplate.json").read_text())["sections"]

    measurements = _section_payload(sections["study-procedure.measurements"], boilerplate, source)
    considerations = _section_payload(sections["analysis-plan.considerations"], boilerplate, source)
    completion = _section_payload(sections["endpoint-criteria.completion"], boilerplate, source)
    sample_size = _section_payload(sections["sample-size"], boilerplate, source)

    assert "assessment activities" in " ".join(measurements["content_expectations"]).casefold()
    assert "endpoint restatement" in " ".join(measurements["content_expectations"]).casefold()
    assert "paired-summary" in " ".join(considerations["content_expectations"]).casefold()
    assert "descriptive" in " ".join(considerations["content_expectations"]).casefold()
    assert "anticipated end" in " ".join(completion["content_expectations"]).casefold()
    assert "no formal completion criterion" in " ".join(completion["content_expectations"]).casefold()
    assert "population.sample_size_evidence" not in sample_size["minimum_evidence"]
    assert "statistics.sample_size_evidence" not in sample_size["minimum_evidence"]
    assert sample_size["table_evidence"] == ["population.sample_size_evidence", "statistics.sample_size_evidence"]
    assert "sample-size evidence table" in " ".join(sample_size["content_expectations"]).casefold()


def test_design_and_analysis_requests_keep_each_fact_in_its_own_section():
    source = _source()
    source["design"]["treatment_assignment"] = (
        "The treating surgeon and patient selected the lens before enrollment. "
        "Enrollment does not determine lens selection or change planned treatment."
    )
    source["statistics"]["bias_minimization"] = (
        "Both cohorts use the same testing conditions and assessment schedule. "
        "Differences may reflect patient selection."
    )
    source["statistics"]["analysis_plan"] = (
        "All enrolled participants enter safety summaries. Outcome data are summarized by cohort. "
        "Available observations will be analyzed without imputation. A participant with earlier-visit "
        "data but no Month 6 assessment contributes to earlier summaries, not to the Month 6 endpoint."
    )
    sections = {item.section_id: item for item in protocol_contract("Prospective")}
    boilerplate = json.loads((ROOT / "references/fixed-clinical-boilerplate.json").read_text())["sections"]
    design = _section_payload(sections["study-design.design"], boilerplate, source)
    bias = _section_payload(sections["study-design.bias"], boilerplate, source)
    method = _section_payload(sections["analysis-plan.methodology"], boilerplate, source)
    assert "design.treatment_assignment" in design["minimum_evidence"]
    assert "design.study_design" not in bias["minimum_evidence"]
    assert "before enrollment" in " ".join(design["content_expectations"])
    assert "do not repeat" in " ".join(bias["content_expectations"]).casefold()
    method_scope = next(item["value"] for item in method["evidence_scopes"] if item["path"] == "statistics.analysis_plan")
    assert "without imputation" in method_scope
    assert "earlier-visit" not in method_scope


def test_editorial_contracts_do_not_feed_other_sections_into_introduction_or_closeout():
    sections = {item.section_id: item for item in protocol_contract("Prospective")}
    assert sections["introduction"].evidence == ("study.background",)
    assert sections["introduction"].source_coverage == "rationale_summary"
    assert sections["objectives"].evidence == ("objectives.primary", "objectives.secondary")
    assert sections["endpoint-criteria.study-completion"].evidence == ("study.timeline", "study.completion")

    source = _source()
    source["statistics"]["analysis_plan"] = (
        "Visual acuity will be summarized with mean and standard deviation. "
        "No inferential hypothesis test is planned for this descriptive study."
    )
    boilerplate = json.loads((ROOT / "references/fixed-clinical-boilerplate.json").read_text())["sections"]
    considerations = _section_payload(sections["analysis-plan.considerations"], boilerplate, source)
    scoped = next(item["value"] for item in considerations["evidence_scopes"] if item["path"] == "statistics.analysis_plan")
    assert "inferential" in scoped.casefold()
    assert "visual acuity" not in scoped.casefold()

    bias = _section_payload(sections["study-design.bias"], boilerplate, source)
    assert "design.study_design" not in bias["minimum_evidence"]
    source["design"]["study_design"] = "Randomized, double-masked study with allocation concealment."
    controlled_bias = _section_payload(sections["study-design.bias"], boilerplate, source)
    assert "design.study_design" in controlled_bias["minimum_evidence"]


def test_editorial_validation_catches_brad_repetitions_without_rejecting_concise_prose():
    source = _source()
    request = {"approved_source": source}
    introduction = {"source_coverage": "rationale_summary", "minimum_evidence": ["study.background"]}
    assert _coverage_findings(
        request, introduction, "introduction",
        "The hypothesis is favorable. The primary endpoint is visual acuity.",
        ["source:study.background"],
    )
    assert not _coverage_findings(
        request, introduction, "introduction",
        source["study"]["background"],
        ["source:study.background"],
    )
    source["study"]["background"] = (
        "Evidence is limited for outcomes after mixed implantation of lenses in the two eyes."
    )
    assert _coverage_findings(
        request, introduction, "introduction",
        "Mix-and-match implantation may offer wider vision with fewer disturbances than bilateral implantation. "
        "Evidence is limited for outcomes after mixed implantation of lenses in the two eyes.",
        ["source:study.background"],
    )
    objectives = {"concept_ownership": {"owns": ["study-objectives"]}, "minimum_evidence": ["objectives.primary"]}
    assert _coverage_findings(request, objectives, "objectives", "The primary endpoint is visual acuity.", ["source:objectives.primary"])
    assert not _coverage_findings(request, objectives, "objectives", "Evaluate vision and patient satisfaction.", ["source:objectives.primary"])

    completion = {"source_coverage": "concept_reference", "minimum_evidence": ["study.timeline"]}
    assert _coverage_findings(
        request, completion, "endpoint-criteria.study-completion",
        "Study closeout follows the approved timeline. The exit form is completed at the final visit.",
        ["source:study.timeline"],
    )

    request["approved_source"]["statistics"]["analysis_plan"] = "No inferential hypothesis test is planned."
    considerations = {
        "source_coverage": "concept_reference",
        "minimum_evidence": ["statistics.analysis_plan"],
        "evidence_scopes": [{"path": "statistics.analysis_plan", "value": "No inferential hypothesis test is planned."}],
    }
    verbose = (
        "No inferential hypothesis test is planned. Visual acuity and defocus curves will be summarized "
        "using means and standard deviations. Questionnaire responses will be counted in every category. "
        "Safety events will be categorized by seriousness, severity, relationship, action, and outcome. "
        "Participants with evaluable visits enter each corresponding analysis set. These summaries describe "
        "observed study outcomes and should be interpreted as descriptive rather than inferential evidence."
    )
    assert _coverage_findings(request, considerations, "analysis-plan.considerations", verbose, ["source:statistics.analysis_plan"])
    assert not _coverage_findings(
        request, considerations, "analysis-plan.considerations",
        "No inferential hypothesis test is planned; results will be interpreted descriptively.",
        ["source:statistics.analysis_plan"],
    )


def test_generated_header_and_schedule_activity_follow_reviewed_case(tmp_path):
    source = _source()
    source["study"]["short_title"] = "Recovery Study"
    source["procedures"]["visit_schedule_table"] = [
        {"visitNumber": "1", "visitName": "Screening", "timing": "Preoperative", "procedures": ["demographics"]},
        {"visitNumber": "2", "visitName": "Postoperative visit", "timing": "Month 3", "procedures": ["Visual acuity"]},
    ]
    render_documents(ROOT, tmp_path, source, {"protocol": [], "icf": {}, "prs": {}}, artifact_names={"protocol"})
    document = Document(tmp_path / "candidate/protocol.docx")
    headers = [cell.text for section in document.sections for table in section.header.tables for row in table.rows for cell in row.cells]
    assert "Recovery Study" in headers
    assert source["study"]["title"] not in headers
    matrix = next(table for table in document.tables if any(cell.text == "Demographics" for row in table.rows for cell in row.cells))
    assert any(row.cells[0].text == "Demographics" for row in matrix.rows)
    variables = next(row.cells[1].text for table in document.tables for row in table.rows if row.cells[0].text.strip() == "Variables")
    assert "Primary outcome" in variables and "Safety outcome" in variables
    assert "see Section" not in variables
