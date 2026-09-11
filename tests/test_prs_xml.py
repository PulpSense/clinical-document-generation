import json
from pathlib import Path
from xml.etree import ElementTree as ET

from prs_xml import compare_structure, expected_counts, generate, repeated_counts, validate_output


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml"
MANUAL_REFERENCE = ROOT / "assets/client-templates/reference/prs-manual-reference.xml"


def fixture():
    return json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))


def test_endpoint_aliases_and_source_counts_are_preserved(tmp_path):
    reference = fixture(); output = tmp_path / "study.xml"
    report = generate(TEMPLATE, output, reference, {"brief_summary": {"text": "This approved prospective study evaluates recovery outcomes."}, "detailed_description": {"text": "This approved study evaluates recovery and safety outcomes over the planned follow-up period."}})
    assert report["status"] == "passed"
    assert repeated_counts(output) == expected_counts(reference)
    root = ET.parse(output).getroot()
    study = next(root.iter("clinical_study"))
    assert study.findtext("primary_outcome/outcome_measure") == "Primary outcome"
    assert study.findtext("primary_outcome/outcome_time_frame") == "Month 3"
    assert study.findtext("primary_outcome/uid") == reference["regulatory"]["prs"]["study_uid"]
    assert study.findtext("uid") == reference["regulatory"]["prs"]["study_uid"]


def test_generated_xml_preserves_client_template_structure(tmp_path):
    reference = fixture(); output = tmp_path / "study.xml"
    generate(TEMPLATE, output, reference, {"brief_summary": {"text": "This approved prospective study evaluates recovery outcomes."}, "detailed_description": {"text": "This approved study evaluates recovery and safety outcomes over the planned follow-up period."}})
    assert compare_structure(TEMPLATE, output) == []


def test_interventional_xml_uses_its_template_branch_while_preserving_manual_outer_structure(tmp_path):
    reference = fixture()
    reference["regulatory"]["prs"].update({
        "study_type": "Interventional",
        "allocation": "Randomized",
        "intervention_model": "Parallel Assignment",
        "primary_purpose": "Treatment",
    })
    output = tmp_path / "study.xml"

    report = generate(
        TEMPLATE,
        output,
        reference,
        {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}},
        structural_template=MANUAL_REFERENCE,
    )

    assert report["status"] == "passed"
    study_design = next(ET.parse(output).getroot().iter("clinical_study")).find("study_design")
    assert study_design.find("interventional_design") is not None
    assert study_design.find("observational_design") is None


def test_validation_rejects_missing_nested_node_in_selected_design_branch(tmp_path):
    reference = fixture()
    output = tmp_path / "study.xml"
    generate(
        TEMPLATE,
        output,
        reference,
        {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}},
        structural_template=MANUAL_REFERENCE,
    )
    tree = ET.parse(output)
    study = next(tree.getroot().iter("clinical_study"))
    description = study.find("study_design/observational_design/biospecimen_description")
    description.remove(description.find("textblock"))
    tree.write(output, encoding="utf-8", xml_declaration=True)

    findings = validate_output(
        output,
        reference,
        MANUAL_REFERENCE,
        generation_template=TEMPLATE,
    )

    assert any(
        item["field"] == "structure" and "biospecimen_description" in item["issue"]
        for item in findings
    )


def test_location_address_accepts_flat_facility_fields(tmp_path):
    reference = fixture()
    reference["sites"][0]["facility"] = {
        "name": "North Surgical Research Center",
        "address": "220 Clinic Way",
        "city": "Boston",
        "state": "MA",
        "country": "United States",
    }
    output = tmp_path / "study.xml"

    generate(TEMPLATE, output, reference, {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}})
    study = next(ET.parse(output).getroot().iter("clinical_study"))

    assert study.findtext("location/facility/address/city") == "Boston"
    assert study.findtext("location/facility/address/state") == "MA"
    assert study.findtext("location/facility/address/country") == "United States"


def test_observational_scalar_fields_map_without_changing_manual_structure(tmp_path):
    reference = fixture()
    reference["study"]["condition"] = "Postoperative Pain"
    reference["regulatory"]["prs"].update({
        "time_perspective": "Other",
        "start_date": "2026-08-24",
        "start_date_type": "Actual",
        "verification_date": "2026-08",
        "primary_completion_date": "2026-11-24",
        "primary_completion_date_type": "Anticipated",
        "study_completion_date": "2026-11-24",
        "study_completion_date_type": "Anticipated",
    })
    output = tmp_path / "study.xml"

    generate(TEMPLATE, output, reference, {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}})
    study = next(ET.parse(output).getroot().iter("clinical_study"))

    assert study.findtext("condition") == "Postoperative Pain"
    assert study.findtext("study_design/observational_design/timing") == "Other"
    assert study.findtext("start_date") == "2026-08-24"
    assert study.findtext("start_date_type") == "Actual"
    assert study.findtext("verification_date") == "2026-08"
    assert study.findtext("primary_compl_date") == "2026-11-24"
    assert study.findtext("primary_compl_date_type") == "Anticipated"
    assert study.findtext("last_follow_up_date") == "2026-11-24"
    assert study.findtext("last_follow_up_date_type") == "Anticipated"
    assert compare_structure(TEMPLATE, output) == []


def test_screening_washout_is_included_in_prs_eligibility(tmp_path):
    reference = fixture(); output = tmp_path / "study.xml"
    generate(TEMPLATE, output, reference, {"brief_summary": {"text": "This approved prospective study evaluates recovery outcomes."}, "detailed_description": {"text": "This approved study evaluates recovery and safety outcomes over the planned follow-up period."}})

    study = next(ET.parse(output).getroot().iter("clinical_study"))
    criteria = study.findtext("eligibility/criteria/textblock") or ""
    if not criteria:
        criteria = " ".join(study.find("eligibility").itertext())
    assert "30 days without participation in another study before screening" in criteria


def test_screening_washout_does_not_duplicate_supplied_day_units(tmp_path):
    reference = fixture()
    reference["procedures"]["minimum_days_before_screening_without_participation"] = "30 days"
    output = tmp_path / "study.xml"

    generate(
        TEMPLATE,
        output,
        reference,
        {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}},
    )

    study = next(ET.parse(output).getroot().iter("clinical_study"))
    criteria = study.findtext("eligibility/criteria/textblock") or ""
    if not criteria:
        criteria = " ".join(study.find("eligibility").itertext())
    assert "30 days without participation in another study before screening" in criteria
    assert "days days" not in criteria


def test_screening_washout_preserves_approved_interventional_study_qualifier(tmp_path):
    reference = fixture()
    reference["population"]["exclusion_criteria"].append(
        "Participation in another interventional study within 30 days before screening."
    )
    output = tmp_path / "study.xml"

    generate(
        TEMPLATE,
        output,
        reference,
        {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}},
    )

    study = next(ET.parse(output).getroot().iter("clinical_study"))
    criteria = study.findtext("eligibility/criteria/textblock") or ""
    assert "30 days without participation in another interventional study before screening" in criteria


def test_optional_prs_roles_are_not_inferred_and_official_affiliation_uses_the_approved_site(tmp_path):
    reference = fixture()
    reference["regulatory"]["prs"].pop("responsible_party_type", None)
    output = tmp_path / "study.xml"

    generate(TEMPLATE, output, reference, {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}})
    study = next(ET.parse(output).getroot().iter("clinical_study"))
    responsible = study.find("sponsors/resp_party")
    assert responsible is not None
    assert all(not (child.text or "").strip() for child in responsible)
    assert study.findtext("overall_official/affiliation") == reference["sites"][0]["facility"]["name"]


def test_study_coordinator_role_is_not_emitted_as_a_prs_degree(tmp_path):
    reference = fixture()
    reference["parties"]["study_coordinator"].pop("degree", None)
    reference["parties"]["study_coordinator"].pop("degrees", None)
    reference["parties"]["study_coordinator"]["title"] = "Study Coordinator"
    output = tmp_path / "study.xml"

    report = generate(
        TEMPLATE,
        output,
        reference,
        {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}},
    )
    study = next(ET.parse(output).getroot().iter("clinical_study"))

    assert report["status"] == "passed"
    assert not (study.findtext("overall_contact/degrees") or "").strip()


def test_explicit_responsible_party_type_enables_source_bound_role_mapping(tmp_path):
    reference = fixture()
    reference["regulatory"]["prs"]["responsible_party_type"] = "Principal Investigator"
    output = tmp_path / "study.xml"

    generate(TEMPLATE, output, reference, {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}})
    study = next(ET.parse(output).getroot().iter("clinical_study"))

    assert study.findtext("sponsors/resp_party/resp_party_type") == "Principal Investigator"
    assert study.findtext("sponsors/resp_party/name_title") == reference["parties"]["principal_investigator"]["name"]
    assert study.findtext("sponsors/resp_party/investigator_affiliation") == reference["sites"][0]["facility"]["name"]


def test_parties_responsible_party_maps_to_manual_xml_and_is_validated(tmp_path):
    reference = fixture()
    reference["parties"]["responsible_party"] = {
        "name_title": "Morgan Sponsor, Director of Clinical Research",
        "organization": "Approved Sponsor Organization",
        "email": "morgan.sponsor@example.org",
        "phone": "555-200-1000",
        "phone_ext": "42",
        "type": "Sponsor",
    }
    output = tmp_path / "study.xml"

    report = generate(
        TEMPLATE,
        output,
        reference,
        {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}},
    )
    study = next(ET.parse(output).getroot().iter("clinical_study"))

    assert report["status"] == "passed"
    assert study.findtext("sponsors/resp_party/name_title") == "Morgan Sponsor, Director of Clinical Research"
    assert study.findtext("sponsors/resp_party/organization") == "Approved Sponsor Organization"
    assert study.findtext("sponsors/resp_party/email") == "morgan.sponsor@example.org"
    assert study.findtext("sponsors/resp_party/phone") == "555-200-1000"
    assert study.findtext("sponsors/resp_party/phone_ext") == "42"
    assert study.findtext("sponsors/resp_party/resp_party_type") == "Sponsor"
    assert compare_structure(TEMPLATE, output) == []

    tree = ET.parse(output)
    next(tree.getroot().iter("clinical_study")).find("sponsors/resp_party/email").text = ""
    tree.write(output, encoding="utf-8", xml_declaration=True)

    findings = validate_output(output, reference, TEMPLATE)
    assert any(item["field"] == "email" and "responsible_party" in item["issue"] for item in findings)


def test_prs_overall_backup_contact_maps_to_manual_xml_and_is_validated(tmp_path):
    reference = fixture()
    reference["regulatory"]["prs"]["overall_contact_backup"] = {
        "name": "Taylor Backup Contact",
        "degrees": "RN",
        "phone": "555-200-2000",
        "phone_ext": "17",
        "email": "taylor.backup@example.org",
    }
    output = tmp_path / "study.xml"

    report = generate(
        TEMPLATE,
        output,
        reference,
        {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}},
    )
    study = next(ET.parse(output).getroot().iter("clinical_study"))

    assert report["status"] == "passed"
    assert study.findtext("overall_contact_backup/first_name") == "Taylor"
    assert study.findtext("overall_contact_backup/middle_name") == "Backup"
    assert study.findtext("overall_contact_backup/last_name") == "Contact"
    assert study.findtext("overall_contact_backup/degrees") == "RN"
    assert study.findtext("overall_contact_backup/phone") == "555-200-2000"
    assert study.findtext("overall_contact_backup/phone_ext") == "17"
    assert study.findtext("overall_contact_backup/email") == "taylor.backup@example.org"
    assert compare_structure(TEMPLATE, output) == []

    tree = ET.parse(output)
    next(tree.getroot().iter("clinical_study")).find("overall_contact_backup/phone").text = ""
    tree.write(output, encoding="utf-8", xml_declaration=True)

    findings = validate_output(output, reference, TEMPLATE)
    assert any(item["field"] == "phone" and "overall_contact_backup" in item["issue"] for item in findings)


def test_site_backup_contact_maps_to_manual_xml_and_is_validated(tmp_path):
    reference = fixture()
    reference["sites"][0]["contact_backup"] = {
        "name": "Riley Site Backup",
        "degree": "CCRC",
        "business_phone": "555-200-3000",
        "extension": "9",
        "email": "riley.backup@example.org",
    }
    output = tmp_path / "study.xml"

    report = generate(
        TEMPLATE,
        output,
        reference,
        {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}},
    )
    study = next(ET.parse(output).getroot().iter("clinical_study"))

    assert report["status"] == "passed"
    assert study.findtext("location/contact_backup/first_name") == "Riley"
    assert study.findtext("location/contact_backup/middle_name") == "Site"
    assert study.findtext("location/contact_backup/last_name") == "Backup"
    assert study.findtext("location/contact_backup/degrees") == "CCRC"
    assert study.findtext("location/contact_backup/phone") == "555-200-3000"
    assert study.findtext("location/contact_backup/phone_ext") == "9"
    assert study.findtext("location/contact_backup/email") == "riley.backup@example.org"
    assert compare_structure(TEMPLATE, output) == []

    tree = ET.parse(output)
    next(tree.getroot().iter("clinical_study")).find("location/contact_backup/email").text = ""
    tree.write(output, encoding="utf-8", xml_declaration=True)

    findings = validate_output(output, reference, TEMPLATE)
    assert any(item["field"] == "location[1].contact_backup.email" for item in findings)


def test_enrollment_uses_the_approved_total_instead_of_concatenating_subgroup_counts(tmp_path):
    reference = fixture()
    reference["population"]["sample_size"] = "80 participants (40 per cohort)"
    output = tmp_path / "study.xml"

    generate(TEMPLATE, output, reference, {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}})
    study = next(ET.parse(output).getroot().iter("clinical_study"))

    assert study.findtext("enrollment") == "80"
    assert validate_output(output, reference, TEMPLATE) == []


def test_supplied_manual_prs_scalar_fields_survive_mapping_and_validation(tmp_path):
    reference = fixture()
    reference["study"]["acronym"] = "RECOVER"
    reference["population"].update({"gender_based": "Yes", "gender_description": "Approved gender eligibility description"})
    reference["parties"]["collaborator"] = {"name": "Approved Collaborator"}
    reference["regulatory"]["prs"].update({
        "has_dmc": "Yes",
        "fda_regulated_device": "Yes",
        "ipd_description": "Approved IPD description",
        "ipd_time_frame": "Five years after publication",
        "ipd_access_criteria": "Qualified researchers with an approved proposal",
    })
    output = tmp_path / "study.xml"

    report = generate(TEMPLATE, output, reference, {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}})
    study = next(ET.parse(output).getroot().iter("clinical_study"))

    assert report["status"] == "passed"
    assert study.findtext("oversight_info/has_dmc") == "Yes"
    assert study.findtext("oversight_info/fda_regulated_device") == "Yes"
    assert study.findtext("eligibility/gender_based") == "Yes"
    assert study.findtext("eligibility/gender_description/textblock") == "Approved gender eligibility description"
    assert study.findtext("acronym") == "RECOVER"
    assert study.findtext("sponsors/collaborator/agency") == "Approved Collaborator"
    assert study.findtext("ipd_sharing_statement/ipd_description/textblock") == "Approved IPD description"
    assert validate_output(output, reference, TEMPLATE) == []


def test_stable_study_and_outcome_uids_are_derived_when_the_source_omits_them(tmp_path):
    reference = fixture()
    reference["regulatory"]["prs"].pop("study_uid", None)
    output = tmp_path / "study.xml"

    report = generate(TEMPLATE, output, reference, {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}})
    study = next(ET.parse(output).getroot().iter("clinical_study"))
    uids = [study.findtext("uid")] + [node.findtext("uid") for tag in ("primary_outcome", "secondary_outcome", "other_outcome") for node in study.findall(tag)]

    assert report["status"] == "passed"
    assert all(uids)
    assert len(set(uids)) == 1
    assert validate_output(output, reference, TEMPLATE) == []


def test_known_defective_xml_does_not_match_client_structure():
    defective = ROOT / "tests/fixtures/prs-xml-defective.xml"
    assert compare_structure(TEMPLATE, defective)


def test_free_text_primary_outcome_cannot_silently_generate_zero_blocks(tmp_path):
    reference = fixture(); reference["endpoints"]["primary"] = "Primary outcome at Month 3"
    output = tmp_path / "study.xml"
    report = generate(TEMPLATE, output, reference, {"brief_summary": {"text": "This approved prospective study evaluates recovery outcomes."}, "detailed_description": {"text": "This approved study evaluates recovery and safety outcomes over the planned follow-up period."}})
    assert report["status"] == "blocked"
    assert any(item["field"] == "endpoints.primary" for item in report["findings"])


def test_xml_validation_rejects_a_missing_approved_study_uid(tmp_path):
    reference = fixture()
    output = tmp_path / "study.xml"
    generate(TEMPLATE, output, reference, {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}})
    tree = ET.parse(output)
    study = next(tree.getroot().iter("clinical_study"))
    study.find("uid").text = ""
    tree.write(output, encoding="utf-8", xml_declaration=True)

    findings = validate_output(output, reference, TEMPLATE)

    assert any(item["field"] == "uid" for item in findings)


def test_xml_validation_rejects_mutation_of_every_source_backed_repeated_block(tmp_path):
    reference = fixture()
    reference["design"]["interventions"] = [{
        "type": "Device",
        "name": "Sentinel Patch",
        "description": "Approved device description",
        "arm_group_label": "Sentinel cohort",
    }]
    reference["design"]["arms"] = [{
        "label": "Sentinel cohort",
        "type": "Experimental",
        "description": "Approved arm description",
    }]
    reference["endpoints"]["primary"] = [{
        "measure": "Approved pain measure",
        "time_frame": "Month 3",
        "description": "Approved primary outcome description",
    }]
    output = tmp_path / "study.xml"
    generate(TEMPLATE, output, reference, {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}})
    tree = ET.parse(output)
    study = next(tree.getroot().iter("clinical_study"))
    study.find("intervention/intervention_description/textblock").text = "Changed intervention"
    study.find("arm_group/arm_group_description/textblock").text = "Changed arm"
    study.find("primary_outcome/outcome_description/textblock").text = "Changed outcome"
    study.find("location/facility/name").text = "Changed facility"
    tree.write(output, encoding="utf-8", xml_declaration=True)

    findings = validate_output(output, reference, TEMPLATE)

    fields = {item["field"] for item in findings}
    assert "intervention[1].intervention_description" in fields
    assert "arm_group[1].arm_group_description" in fields
    assert "primary_outcome[1].outcome_description" in fields
    assert "location[1].facility.name" in fields


def test_xml_validation_rejects_source_scalar_mutation_and_preserves_structured_contact_aliases(tmp_path):
    reference = fixture()
    reference["sites"][0]["contact"] = {
        "first_name": "Jordan",
        "middle_name": "Lee",
        "last_name": "Coordinator",
        "degrees": "RN",
        "phone": "+1 555 0100",
        "phone_ext": "42",
        "email": "jordan@example.org",
    }
    output = tmp_path / "study.xml"
    generate(TEMPLATE, output, reference, {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}})

    study = next(ET.parse(output).getroot().iter("clinical_study"))
    assert study.findtext("location/contact/first_name") == "Jordan"
    assert study.findtext("location/contact/middle_name") == "Lee"
    assert study.findtext("location/contact/last_name") == "Coordinator"
    assert study.findtext("location/contact/phone_ext") == "42"

    tree = ET.parse(output)
    next(tree.getroot().iter("clinical_study")).find("official_title").text = "WRONG"
    tree.write(output, encoding="utf-8", xml_declaration=True)
    fields = {item["field"] for item in validate_output(output, reference, TEMPLATE)}
    assert "official_title" in fields


def test_manual_structural_authority_rejects_an_extra_top_level_element(tmp_path):
    reference = fixture()
    reference["regulatory"]["prs"].update({
        "study_type": "Interventional",
        "allocation": "Randomized",
        "intervention_model": "Parallel Assignment",
        "primary_purpose": "Treatment",
    })
    output = tmp_path / "study.xml"
    generate(
        TEMPLATE,
        output,
        reference,
        {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}},
        structural_template=MANUAL_REFERENCE,
    )
    tree = ET.parse(output)
    ET.SubElement(next(tree.getroot().iter("clinical_study")), "unauthorized_extension").text = "wrong"
    tree.write(output, encoding="utf-8", xml_declaration=True)

    findings = validate_output(
        output,
        reference,
        MANUAL_REFERENCE,
        generation_template=TEMPLATE,
    )

    assert any(item["field"] == "structure" for item in findings)
