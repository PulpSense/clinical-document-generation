"""Independent regression oracles for PRS transport and source provenance."""
import copy
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import prs_xml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml"
NARRATIVE = {"brief_summary": {"text": "Postoperative knee recovery."},
             "detailed_description": {"text": "Recovery following knee arthroplasty."}}


def source():
    return json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text())


def render(tmp_path, reference):
    output = tmp_path / "study.xml"
    report = prs_xml.generate(TEMPLATE, output, reference, NARRATIVE)
    return output, report, next(ET.parse(output).getroot().iter("clinical_study"))


@pytest.mark.parametrize("raw,canonical", [("All sexes", "All"), ("Both", "All"),
                                            ("All", "All"), ("Male", "Male"), ("Female", "Female"),
                                            (" all   SEXES ", "All"), (" both ", "All"),
                                            ("MALE", "Male"), (" female ", "Female")])
def test_sex_transport_is_canonical_without_mutating_approved_source(tmp_path, raw, canonical):
    reference = source()
    reference["population"].pop("gender", None)
    reference["population"]["sex"] = raw
    original = copy.deepcopy(reference)
    output, report, study = render(tmp_path, reference)
    assert study.findtext("eligibility/gender") == canonical
    assert reference == original
    assert report["status"] == "passed"
    assert prs_xml.validate_output(output, reference, TEMPLATE) == []


@pytest.mark.parametrize("target,raw", [
    ("eligibility/gender", "Unknown"),
    ("eligibility/sampling_method", "Convenience guess"),
    ("eligibility/healthy_volunteers", "Maybe"),
    ("primary_compl_date_type", "Estimated"),
    ("last_follow_up_date_type", "Unknown"),
    ("study_design/study_type", "Prospective"),
])
def test_unknown_source_transport_tokens_are_not_self_validated(tmp_path, target, raw):
    reference = source()
    source_paths = {
        "eligibility/gender": ("population", "sex"),
        "eligibility/sampling_method": ("prs", "sampling_method"),
        "eligibility/healthy_volunteers": ("population", "healthy_volunteers"),
        "primary_compl_date_type": ("prs", "primary_completion_date_type"),
        "last_follow_up_date_type": ("prs", "study_completion_date_type"),
        "study_design/study_type": ("prs", "study_type"),
    }
    section, key = source_paths[target]
    (reference["regulatory"]["prs"] if section == "prs" else reference[section])[key] = raw
    _, report, _ = render(tmp_path, reference)
    assert report["status"] == "blocked"
    assert any(f["field"] == target and f["category"] == "transport_vocabulary"
               for f in report["findings"])


@pytest.mark.parametrize("wrong", ["All sexes", "Both", "Unknown", "Female", ""])
def test_validation_independently_rejects_wrong_gender(tmp_path, wrong, monkeypatch):
    reference = source()
    reference["population"]["sex"] = "All sexes"
    output, _, _ = render(tmp_path, reference)
    # Simulate a mapper defect as well as corrupt XML; validation must not
    # approve it merely because the mapper produces the same wrong value.
    original_fields = prs_xml._fields
    def broken_fields(*args):
        return dict(original_fields(*args), eligibilityGender=wrong)
    monkeypatch.setattr(prs_xml, "_fields", broken_fields)
    tree = ET.parse(output)
    next(tree.getroot().iter("clinical_study")).find("eligibility/gender").text = wrong
    tree.write(output)
    findings = prs_xml.validate_output(output, reference, TEMPLATE)
    assert any(f["field"] in {"gender", "eligibility/gender"} for f in findings)


REQUESTED_FIELDS = {
    "eligibility/gender", "start_date", "start_date_type", "primary_compl_date",
    "primary_compl_date_type", "last_follow_up_date", "last_follow_up_date_type",
    "verification_date", "end_date", "eligibility/sampling_method",
    "eligibility/healthy_volunteers", "condition",
}


@pytest.mark.parametrize("study_type", ["Observational", "Interventional"])
def test_optional_blanks_have_nonblocking_provenance_not_guessed_values(tmp_path, study_type):
    reference = source()
    reference["regulatory"]["prs"]["study_type"] = study_type
    reference["study"]["condition"] = None
    original = copy.deepcopy(reference)
    output, report, study = render(tmp_path, reference)
    assert report["status"] == "passed"
    assert prs_xml.validate_output(output, reference, TEMPLATE) == []
    assert reference == original
    provenance = report["source_provenance"]
    assert set(provenance) == REQUESTED_FIELDS
    for target in REQUESTED_FIELDS:
        assert not study.findtext(target)
        assert provenance[target]["status"] == "missing_source"
        assert provenance[target]["source_path"] is None
        assert provenance[target]["source_paths"]
    assert provenance["condition"]["source_paths"] == ["study.condition"]
    readiness = report["registration_readiness"]
    assert readiness["blocking"] is False
    assert readiness["status"] == "not_assessed"
    assert readiness["study_type"] == study_type
    assert readiness["overall_status"] == reference["regulatory"]["prs"].get("overall_status", "")
    fields = readiness["fields"]
    assert fields["end_date"]["applicability"] == "deprecated"
    assert fields["eligibility/sampling_method"]["applicability"] == (
        "observational_only" if study_type == "Observational" else "not_applicable")
    assert fields["eligibility/healthy_volunteers"]["applicability"] == (
        "optional_observational" if study_type == "Observational" else "review_interventional")


def test_provenance_distinguishes_supplied_mapping_loss_from_missing_source(tmp_path):
    reference = source()
    reference["population"]["sex"] = "All sexes"
    reference["regulatory"]["prs"]["last_follow_up_date"] = "2026-12-01"
    output, report, _ = render(tmp_path, reference)
    provenance = report["source_provenance"]
    assert provenance["eligibility/gender"]["status"] == "mapped"
    assert provenance["eligibility/gender"]["source_value"] == "All sexes"
    assert provenance["eligibility/gender"]["expected_value"] == "All"
    assert provenance["last_follow_up_date"]["source_path"] == "regulatory.prs.last_follow_up_date"
    tree = ET.parse(output)
    study = next(tree.getroot().iter("clinical_study"))
    study.find("last_follow_up_date").text = ""
    study.find("condition").text = "Guessed from narrative"
    tree.write(output)
    audit = prs_xml.quality_report(output, reference)
    assert audit["source_provenance"]["last_follow_up_date"]["status"] == "mapping_failure"
    assert audit["source_provenance"]["condition"]["status"] == "unsourced_output"
    assert any(f["field"] == "last_follow_up_date" for f in prs_xml.validate_output(output, reference, TEMPLATE))


def test_readiness_information_does_not_weaken_existing_required_gate(tmp_path):
    reference = source()
    reference["population"]["sample_size"] = None
    _, report, _ = render(tmp_path, reference)
    assert report["status"] == "blocked"
    assert any(f["field"] == "enrollment" for f in report["findings"])
    assert report["registration_readiness"]["blocking"] is False


@pytest.mark.parametrize("raw", ["yes", "no", "Yes", "No"])
@pytest.mark.parametrize("sampling", ["Probability Sample", "Non-Probability Sample"])
def test_known_optional_transport_tokens_pass_without_defaults(tmp_path, raw, sampling):
    reference = source()
    reference["population"]["healthy_volunteers"] = raw
    reference["regulatory"]["prs"].update({
        "sampling_method": sampling, "primary_completion_date_type": "Actual",
        "study_completion_date_type": "Anticipated",
    })
    output, report, study = render(tmp_path, reference)
    assert report["status"] == "passed"
    assert study.findtext("eligibility/healthy_volunteers") == raw
    assert study.findtext("eligibility/sampling_method") == sampling
    assert not study.findtext("primary_compl_date")
    assert not study.findtext("last_follow_up_date")
    assert prs_xml.validate_output(output, reference, TEMPLATE) == []


def test_gender_alias_precedence_is_source_bound(tmp_path):
    reference = source()
    reference["population"].update({"gender": "Female", "sex": "All sexes"})
    _, report, study = render(tmp_path, reference)
    assert study.findtext("eligibility/gender") == "Female"
    assert report["status"] == "passed"
    assert report["source_provenance"]["eligibility/gender"]["source_path"] == "population.gender"


def test_known_source_vocabulary_case_and_space_variants_are_canonical(tmp_path):
    reference = source()
    reference["regulatory"]["prs"].update({
        "study_type": " observational ", "sampling_method": " non-probability   sample ",
        "primary_completion_date_type": "actual", "study_completion_date_type": " ANTICIPATED ",
    })
    original = copy.deepcopy(reference)
    output, report, study = render(tmp_path, reference)
    assert study.findtext("primary_compl_date_type") == "Actual"
    assert study.findtext("last_follow_up_date_type") == "Anticipated"
    assert study.findtext("eligibility/sampling_method") == "Non-Probability Sample"
    assert study.findtext("study_design/study_type") == "Observational"
    assert report["status"] == "passed"
    assert reference == original
    assert prs_xml.validate_output(output, reference, TEMPLATE) == []
    assert report["source_provenance"]["primary_compl_date_type"]["status"] == "mapped"


@pytest.mark.parametrize("target", sorted(REQUESTED_FIELDS))
def test_supplied_scalar_omission_is_a_mapping_failure_not_optional_absence(tmp_path, target):
    reference = source()
    reference["population"].update({"sex": "All sexes", "healthy_volunteers": "No"})
    reference["study"]["condition"] = "Approved condition"
    reference["regulatory"]["prs"].update({
        "start_date": "2026-01", "start_date_type": "Actual", "end_date": "2026-12",
        "verification_date": "2026-09", "primary_completion_date": "2026-11",
        "primary_completion_date_type": "Anticipated", "study_completion_date": "2026-12",
        "study_completion_date_type": "Anticipated", "sampling_method": "Probability Sample",
    })
    output, report, _ = render(tmp_path, reference)
    assert report["status"] == "passed"
    assert report["source_provenance"][target]["status"] == "mapped"
    tree = ET.parse(output)
    element = next(tree.getroot().iter("clinical_study")).find(target)
    assert element is not None
    element.text = ""
    tree.write(output)
    assert any(f["field"] in {target, target.rsplit("/", 1)[-1]}
               for f in prs_xml.validate_output(output, reference, TEMPLATE))
    assert prs_xml.quality_report(output, reference)["source_provenance"][target]["status"] == "mapping_failure"
