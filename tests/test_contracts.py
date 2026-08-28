import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from contracts import ContractedTemplateBundleError, ICF_STUDY_SECTIONS, PROSPECTIVE_REQUIRED, RETROSPECTIVE_REQUIRED, DOCUMENT_SETS, batch_plan, contracted_template_bundle, icf_contract, input_findings, parse_source_truth, protocol_contract, source_contract, source_truth_markdown


ROOT = Path(__file__).resolve().parents[1]


def fixture(name):
    return json.loads((ROOT / "tests/fixtures" / name).read_text(encoding="utf-8"))


def test_branch_document_sets_are_exact():
    assert DOCUMENT_SETS["Prospective"] == ("protocol.docx", "icf.docx", "study.xml")
    assert DOCUMENT_SETS["Ambispective"] == ("protocol.docx", "icf.docx", "study.xml")
    assert DOCUMENT_SETS["Retrospective"] == ("protocol.docx",)


@pytest.mark.parametrize(
    ("study_type", "icf_family", "protocol_template", "icf_template", "icf_authority", "has_prs"),
    (
        ("Prospective", "Advarra", "prospective-protocol.template.docx", "prospective-icf.template.docx", "advarra-icf-reference.docx", True),
        ("Prospective", "Sterling", "prospective-protocol.template.docx", "sterling-icf.template.docx", "sterling-icf-reference.docx", True),
        ("Ambispective", "Advarra", "ambispective-protocol.template.docx", "ambispective-icf.template.docx", "advarra-icf-reference.docx", True),
        ("Ambispective", "Sterling", "ambispective-protocol.template.docx", "sterling-icf.template.docx", "sterling-icf-reference.docx", True),
        ("Retrospective", None, "retrospective-protocol.template.docx", None, None, False),
    ),
)
def test_every_supported_selection_resolves_one_complete_contracted_template_bundle(
    study_type,
    icf_family,
    protocol_template,
    icf_template,
    icf_authority,
    has_prs,
):
    meta = {"study_type": study_type}
    if icf_family is not None:
        meta["icf_template"] = icf_family

    bundle = contracted_template_bundle(ROOT, {"meta": meta})

    assert bundle["selection"] == {"study_type": study_type, "icf_family": icf_family}
    assert bundle["contracted_templates"]["protocol"]["path"].endswith(protocol_template)
    assert (bundle["contracted_templates"].get("icf") or {}).get("path", "").endswith(icf_template or "")
    assert bundle["client_template_authorities"]["protocol"]["path"].endswith("protocol-reference.docx")
    assert (bundle["client_template_authorities"].get("icf") or {}).get("path", "").endswith(icf_authority or "")
    assert (bundle["prs_authority"] is not None) is has_prs
    assert len(bundle["document_section_contract"]["sha256"]) == 64
    assert len(bundle["fixed_clinical_boilerplate"]["sha256"]) == 64
    assert len(bundle["approved_font_plan"]["sha256"]) == 64
    assert len(bundle["identity_sha256"]) == 64
    assert bundle["resource_hashes"]
    assert all(len(digest) == 64 for digest in bundle["resource_hashes"].values())

    baseline = bundle["layout_preservation_baseline"]
    assert baseline["schema_version"] == "layout-preservation-baseline/v1"
    assert len(baseline["sha256"]) == 64
    assert set(baseline["artifacts"]) == set(bundle["contracted_templates"])
    for artifact, identity in baseline["artifacts"].items():
        assert identity == {
            "contracted_template": bundle["contracted_templates"][artifact],
            "client_template_authority": bundle["client_template_authorities"][artifact],
        }
        for resource in identity.values():
            path = ROOT / resource["path"]
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == resource["sha256"]


def test_contracted_template_bundle_identity_is_stable_and_covers_every_selected_resource():
    reference = {"meta": {"study_type": "Ambispective", "icf_template": "Sterling"}}

    first = contracted_template_bundle(ROOT, reference)
    second = contracted_template_bundle(ROOT, reference)

    assert first == second
    governed_paths = {
        item["path"]
        for group in (
            first["contracted_templates"],
            first["client_template_authorities"],
            first["prs_authority"],
        )
        for item in group.values()
    }
    governed_paths.add(first["fixed_clinical_boilerplate"]["path"])
    governed_paths.update(first["approved_font_plan"]["packaged_font_assets"])
    assert governed_paths == set(first["resource_hashes"])
    assert all(
        first["resource_hashes"][item["path"]] == item["sha256"]
        for group in (
            first["contracted_templates"],
            first["client_template_authorities"],
            first["prs_authority"],
            first["approved_font_plan"]["packaged_font_assets"],
        )
        for item in group.values()
    )


@pytest.mark.parametrize(
    "reference",
    (
        {"meta": {}},
        {"meta": {"study_type": "Prospective"}},
        {"meta": {"study_type": "Prospective", "icf_template": "Uncontracted"}},
    ),
)
def test_missing_or_uncontracted_selection_produces_one_bundle_contract_failure(reference):
    with pytest.raises(ContractedTemplateBundleError) as raised:
        contracted_template_bundle(ROOT, reference)

    assert raised.value.finding["field"] == "contracted_template_bundle"


def test_internally_inconsistent_bundle_produces_one_contract_failure(tmp_path):
    release = tmp_path / "release"
    shutil.copytree(ROOT / "assets", release / "assets")
    shutil.copytree(ROOT / "references", release / "references")
    boilerplate_path = release / "references/fixed-clinical-boilerplate.json"
    boilerplate = json.loads(boilerplate_path.read_text(encoding="utf-8"))
    boilerplate["version"] = "uncontracted-version"
    boilerplate_path.write_text(json.dumps(boilerplate), encoding="utf-8")

    with pytest.raises(ContractedTemplateBundleError) as raised:
        contracted_template_bundle(
            release,
            {"meta": {"study_type": "Prospective", "icf_template": "Advarra"}},
        )

    assert raised.value.finding["field"] == "contracted_template_bundle"
    assert "version does not match" in raised.value.finding["issue"]


@pytest.mark.parametrize(
    "relative",
    (
        "assets/client-templates/docx/prospective-protocol.template.docx",
        "assets/client-templates/reference/advarra-icf-reference.docx",
        "assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml",
        "assets/fallback-fonts/LiberationSans-Regular.ttf",
    ),
)
def test_corrupt_governed_asset_produces_one_contract_failure_before_drafting(tmp_path, relative):
    release = tmp_path / "release"
    shutil.copytree(ROOT / "assets", release / "assets")
    shutil.copytree(ROOT / "references", release / "references")
    (release / relative).write_bytes(b"not a valid governed asset")

    with pytest.raises(ContractedTemplateBundleError) as raised:
        contracted_template_bundle(
            release,
            {"meta": {"study_type": "Prospective", "icf_template": "Advarra"}},
        )

    assert raised.value.finding["field"] == "contracted_template_bundle"


def test_governed_resource_mutation_changes_bundle_identity(tmp_path):
    release = tmp_path / "release"
    shutil.copytree(ROOT / "assets", release / "assets")
    shutil.copytree(ROOT / "references", release / "references")
    reference = {"meta": {"study_type": "Prospective", "icf_template": "Advarra"}}
    before = contracted_template_bundle(release, reference)
    sterling_before = contracted_template_bundle(
        release,
        {"meta": {"study_type": "Prospective", "icf_template": "Sterling"}},
    )
    authority_path = release / "assets/client-templates/reference/advarra-icf-reference.docx"
    authority_path.write_bytes(authority_path.read_bytes() + b"governed-mutation")

    after = contracted_template_bundle(release, reference)
    sterling_after = contracted_template_bundle(
        release,
        {"meta": {"study_type": "Prospective", "icf_template": "Sterling"}},
    )

    relative = "assets/client-templates/reference/advarra-icf-reference.docx"
    assert after["resource_hashes"][relative] != before["resource_hashes"][relative]
    assert after["identity_sha256"] != before["identity_sha256"]
    assert sterling_after["identity_sha256"] == sterling_before["identity_sha256"]


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
    retrospective = {section.section_id: section for section in protocol_contract("Retrospective")}
    icf = {section.section_id: section for section in ICF_STUDY_SECTIONS}

    assert {"study.hypothesis", "endpoints.primary"} <= set(protocol["introduction"].evidence)
    assert {"study.hypothesis", "endpoints.primary", "endpoints.secondary"} <= set(protocol["objectives"].evidence)
    assert {"study.hypothesis", "endpoints.primary", "endpoints.secondary"} <= set(protocol["study-procedure.measurements"].evidence)
    assert {"endpoints.primary", "endpoints.secondary"} <= set(protocol["analysis-plan.methodology"].evidence)
    assert {"study.hypothesis", "objectives.secondary", "endpoints.primary", "endpoints.secondary"} <= set(retrospective["objectives"].evidence)
    assert {"study.hypothesis", "endpoints.primary"} <= set(icf["icf.study-purpose"].evidence)


def test_completion_sections_require_every_approved_visit_and_time_point():
    protocol = {section.section_id: section for section in protocol_contract("Prospective")}

    for section_id in ("endpoint-criteria.completion", "endpoint-criteria.study-completion"):
        section = protocol[section_id]
        assert "procedures.assessments" in section.evidence
        assert section.source_coverage == "all_material_items"
        assert any("every approved visit" in item for item in section.content_expectations)
        assert any("time point" in item for item in section.content_expectations)


def test_protocol_ethics_and_confidentiality_use_substantive_boilerplate():
    protocol = {section.section_id: section for section in protocol_contract("Ambispective")}

    assert protocol["ethics"].role == "container"
    assert protocol["ethics"].batch_id == ""
    assert protocol["ethics"].boilerplate_key == "ethics"
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


def test_prs_study_type_is_required_before_source_approval():
    reference = fixture("ambispective-acceptance-source.json")
    reference["regulatory"]["prs"].pop("study_type")
    reference["design"]["study_design"] = "Ambispective, single-center, single-arm device study."

    contract = source_contract(reference)

    assert contract["status"] == "blocked"
    assert any(
        item["field"] == "regulatory.prs.study_type"
        and item["issue"] == "Required Source Input is missing."
        for item in contract["blocking_findings"]
    )


def test_prs_provider_study_id_is_required_before_source_approval():
    reference = fixture("prospective-acceptance-source.json")
    reference["regulatory"]["prs"].pop("provider_study_id", None)
    reference["meta"].pop("protocol_number")

    contract = source_contract(reference)

    assert contract["status"] == "blocked"
    assert any(
        item["field"] == "regulatory.prs.provider_study_id"
        for item in contract["blocking_findings"]
    )


def test_prs_study_type_must_be_a_supported_registry_classification():
    reference = fixture("ambispective-acceptance-source.json")
    reference["regulatory"]["prs"]["study_type"] = "Ambispective"

    contract = source_contract(reference)

    assert contract["status"] == "blocked"
    assert any(
        item["field"] == "regulatory.prs.study_type"
        and item["issue"] == "PRS study type must be Observational or Interventional."
        for item in contract["blocking_findings"]
    )


def test_prs_study_type_rejects_noncanonical_reviewer_value():
    reference = fixture("prospective-acceptance-source.json")
    reference["regulatory"]["prs"]["study_type"] = " observational "

    contract = source_contract(reference)

    assert contract["status"] == "blocked"
    assert contract["normalized_reference"]["regulatory"]["prs"]["study_type"] == " observational "


def test_prs_study_type_uses_unambiguous_approved_design_evidence():
    reference = fixture("ambispective-acceptance-source.json")
    reference["regulatory"]["prs"].pop("study_type")

    contract = source_contract(reference, derive_prs_study_type=True)

    assert contract["status"] == "passed"
    assert contract["normalized_reference"]["regulatory"]["prs"]["study_type"] == "Observational"


@pytest.mark.parametrize(
    ("design", "expected"),
    (
        ("Observational", "Observational"),
        ("Study type: Observational", "Observational"),
        ("Interventional, randomized study", "Interventional"),
    ),
)
def test_prs_study_type_uses_direct_unambiguous_classification_forms(design, expected):
    reference = fixture("prospective-acceptance-source.json")
    reference["regulatory"]["prs"].pop("study_type")
    reference["design"]["study_design"] = design

    contract = source_contract(reference, derive_prs_study_type=True)

    assert contract["status"] == "passed"
    assert contract["normalized_reference"]["regulatory"]["prs"]["study_type"] == expected


@pytest.mark.parametrize(
    "design",
    (
        "This is not an interventional study.",
        "Whether this study is interventional remains unknown.",
        "This may be an interventional study.",
        "This might be observational.",
        "The proposed classification is interventional.",
        "Interventional?",
        "This is not necessarily an interventional study.",
        "If approved, this will be an observational study.",
        "It is allegedly an observational study.",
        "The study is an observational study; however, this classification is tentative.",
        "The study is an interventional study. This classification is unconfirmed.",
        "Ambispective, single-center observational device study with classification pending.",
    ),
)
def test_prs_study_type_does_not_infer_from_negated_or_uncertain_design(design):
    reference = fixture("prospective-acceptance-source.json")
    reference["regulatory"]["prs"].pop("study_type")
    reference["design"]["study_design"] = design

    contract = source_contract(reference, derive_prs_study_type=True)

    assert contract["status"] == "blocked"
    assert any(
        item["field"] == "regulatory.prs.study_type"
        for item in contract["blocking_findings"]
    )


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


def test_retrospective_safety_roles_require_structured_party_responsibility_records():
    reference = fixture("retrospective-acceptance-source.json")
    assert not any(item["field"] == "safety.roles" for item in input_findings(reference))

    malformed_values = [
        "The investigator assesses and reports safety events.",
        [{"party": {"name": "investigator"}, "responsibilities": "assess_safety_events"}],
        [{"party": "investigator", "responsibilities": ["assess_safety_events"]}],
        [{"party": "investigator", "responsibilities": "assess_safety_events", "extra": "x"}],
        [{"party": "investigator", "responsibilities": "unknown_concept"}],
        [
            {"party": "investigator", "responsibilities": "assess_safety_events"},
            {"party": "Investigator", "responsibilities": "report_safety_events"},
        ],
        [
            {"party": "sponsor", "responsibilities": "assess_safety_events"},
            {"party": "the sponsor", "responsibilities": "report_safety_events"},
        ],
        [
            {"party": "study physician", "responsibilities": "assess_safety_events"},
            {"party": "study-physician", "responsibilities": "report_safety_events"},
        ],
        [
            {"party": "José Müller", "responsibilities": "assess_safety_events"},
            {"party": "Jose\u0301 Mu\u0308ller", "responsibilities": "report_safety_events"},
        ],
    ]
    for malformed in malformed_values:
        working = fixture("retrospective-acceptance-source.json")
        working["safety"]["roles"] = malformed
        finding = next(
            item for item in input_findings(working)
            if item["field"] == "safety.roles"
        )
        assert "structured party/responsibility records" in finding["issue"]
