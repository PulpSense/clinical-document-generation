"""The documented starred lists, not downstream output needs, own intake."""
import json
import re
from pathlib import Path

import pytest

from contracts import PROSPECTIVE_REQUIRED, RETROSPECTIVE_REQUIRED, parse_source_truth
from prs_xml import generate as generate_xml
from workflow import prepare

ROOT = Path(__file__).resolve().parents[1]


def reference_for(branch):
    return json.loads((ROOT / f"tests/fixtures/{branch.lower()}-acceptance-source.json").read_text())


def prepare_reference(tmp_path, reference):
    path = tmp_path / "reference/study.reference.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(reference))
    return prepare(tmp_path)


@pytest.mark.parametrize("branch", ["Prospective", "Ambispective", "Retrospective"])
def test_required_fields_exactly_match_documented_starred_list(branch):
    retrospective = branch == "Retrospective"
    name = "retrospective-required-inputs.md" if retrospective else "starred-fillout-required-inputs.md"
    document = (ROOT / "references" / name).read_text()
    starred = document.split("## Starred Fields\n", 1)[1].split("## Optional Fields", 1)[0]
    documented = re.findall(r"^- `([^`]+)`", starred, re.MULTILINE)
    requirements = RETROSPECTIVE_REQUIRED if retrospective else PROSPECTIVE_REQUIRED
    actual = [item.field for item in requirements]
    assert len(documented) == (21 if retrospective else 35)
    assert len(actual) == len(set(actual))
    assert set(actual) == set(documented)


@pytest.mark.parametrize("branch", ["Prospective", "Ambispective"])
@pytest.mark.parametrize("missing", ["evidence", "provider_id", "classification"])
def test_missing_optional_input_does_not_block_preparation(tmp_path, branch, missing):
    reference = reference_for(branch)
    if missing == "evidence":
        for family in ("population", "statistics"):
            reference[family].pop("sample_size_evidence", None)
    elif missing == "provider_id":
        reference["regulatory"]["prs"].pop("provider_study_id", None)
        reference["meta"].pop("protocol_number", None)
    else:
        reference["regulatory"]["prs"].pop("study_type", None)
        reference["design"]["study_design"] = f"{branch}, single-center device study."
    result = prepare_reference(tmp_path, reference)
    assert result["status"] == "awaiting_approval", result
    assert (tmp_path / result["source_of_truth"]).is_file()
    assert not (tmp_path / "reference/missing-inputs.md").exists()


@pytest.mark.parametrize("branch", ["Prospective", "Ambispective", "Retrospective"])
def test_missing_required_sample_justification_still_blocks(tmp_path, branch):
    reference = reference_for(branch)
    reference["population"].pop("sample_justification", None)
    reference["statistics"].pop("sample_size_justification", None)
    result = prepare_reference(tmp_path, reference)
    assert result["status"] == "blocked"
    assert any(row["field"] == "population.sample_justification" and row["issue"] == "Required Source Input is missing." for row in result["missing"])


@pytest.mark.parametrize("branch", ["Prospective", "Ambispective"])
@pytest.mark.parametrize("family", ["statistics", "population"])
def test_optional_supplied_evidence_survives_preparation_and_review(tmp_path, branch, family):
    reference = reference_for(branch)
    evidence = reference[family]["sample_size_evidence"]
    other = "population" if family == "statistics" else "statistics"
    reference[other].pop("sample_size_evidence", None)
    result = prepare_reference(tmp_path, reference)
    assert result["status"] == "awaiting_approval", result
    prepared = json.loads((tmp_path / "reference/study.reference.json").read_text())
    parsed = parse_source_truth((tmp_path / result["source_of_truth"]).read_text(), prepared)
    assert prepared[family]["sample_size_evidence"] == evidence
    assert parsed[family]["sample_size_evidence"] == evidence


@pytest.mark.parametrize("branch", ["Prospective", "Ambispective"])
@pytest.mark.parametrize("family", ["statistics", "population"])
@pytest.mark.parametrize("evidence", ["not typed rows", [{"study": "Incomplete evidence"}]])
def test_invalid_optional_supplied_evidence_still_blocks(tmp_path, branch, family, evidence):
    reference = reference_for(branch)
    for key in ("population", "statistics"):
        reference[key].pop("sample_size_evidence", None)
    reference[family]["sample_size_evidence"] = evidence
    result = prepare_reference(tmp_path, reference)
    assert result["status"] == "blocked"
    assert any("sample_size_evidence" in row["field"] and row["issue"] != "Required Source Input is missing." for row in result["technical_findings"])


@pytest.mark.parametrize("field", ["provider_study_id", "study_type"])
def test_missing_optional_intake_prs_value_still_fails_downstream_xml(tmp_path, field):
    reference = reference_for("Prospective")
    reference["regulatory"]["prs"].pop(field, None)
    if field == "provider_study_id":
        reference["meta"].pop("protocol_number", None)
    else:
        reference["design"]["study_design"] = "Prospective, single-center device study."
    assert prepare_reference(tmp_path, reference)["status"] == "awaiting_approval"
    report = generate_xml(
        ROOT / "assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml",
        tmp_path / "study.xml",
        reference,
        {"brief_summary": {"text": "Summary."}, "detailed_description": {"text": "Description."}},
    )
    assert report["status"] == "blocked"
    assert any(row["field"] == field and row["issue"] == "Required PRS value is empty." for row in report["findings"])
