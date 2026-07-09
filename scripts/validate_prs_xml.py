#!/usr/bin/env python3
"""Validate a rendered ClinicalTrials.gov PRS XML output."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


STANDARD_REFERENCE = "reference/study.reference.json"
STANDARD_XML = "output/study.xml"
STANDARD_REPORT = "logs/prs-xml-validation.json"
TOKEN_RE = re.compile(r"\{[#/^]?[A-Za-z_][A-Za-z0-9_.\-\[\]\(\)&]*\}")
FORBIDDEN_EXACT = {"none", "n/a", "na", "http://", "https://"}
ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
VERIFICATION_DATE_RE = re.compile(r"\d{4}-\d{2}")
PRS_AGE_RE = re.compile(r"\d+(?:\.\d+)? (Years|Months|Weeks|Days|Hours|Minutes)")


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def display_path(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def text_of(element: ET.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def direct_children(parent: ET.Element, tag: str) -> list[ET.Element]:
    return [child for child in list(parent) if child.tag == tag]


def direct_child(parent: ET.Element, tag: str) -> ET.Element | None:
    for child in list(parent):
        if child.tag == tag:
            return child
    return None


def nested_child(parent: ET.Element, path: list[str]) -> ET.Element | None:
    current: ET.Element | None = parent
    for tag in path:
        if current is None:
            return None
        current = direct_child(current, tag)
    return current


def rendered_counts(study: ET.Element) -> dict[str, int]:
    return {
        "intervention": len(direct_children(study, "intervention")),
        "arm_group": len(direct_children(study, "arm_group")),
        "primary_outcome": len(direct_children(study, "primary_outcome")),
        "secondary_outcome": len(direct_children(study, "secondary_outcome")),
        "other_outcome": len(direct_children(study, "other_outcome")),
    }


def expected_counts(reference: dict) -> dict[str, int]:
    fields = reference.get("template_fields") if isinstance(reference.get("template_fields"), dict) else {}
    counts = fields.get("__prs_counts") if isinstance(fields.get("__prs_counts"), dict) else {}
    return {key: int(counts.get(key, 0)) for key in ["intervention", "arm_group", "primary_outcome", "secondary_outcome", "other_outcome"]}


def validate_outcome_block(block: ET.Element, label: str, index: int, errors: list[str]) -> None:
    required_text = ["outcome_measure", "outcome_time_frame", "uid"]
    for tag in required_text:
        element = direct_child(block, tag)
        if element is None:
            errors.append(f"{label}[{index}] missing <{tag}>")
        elif not text_of(element):
            errors.append(f"{label}[{index}] has empty <{tag}>")
    description = nested_child(block, ["outcome_description", "textblock"])
    if description is None:
        errors.append(f"{label}[{index}] missing <outcome_description><textblock>")


def validate(xml_path: Path, reference: dict) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    xml_text = xml_path.read_text(encoding="utf-8")
    unresolved = sorted(set(TOKEN_RE.findall(xml_text)))
    if unresolved:
        errors.append(f"unresolved placeholders remain: {unresolved}")

    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as exc:
        return [f"XML parse error: {exc}"], {"unresolved": unresolved}

    root = tree.getroot()
    study = None
    for element in root.iter():
        if element.tag == "clinical_study":
            study = element
            break
    if study is None:
        return ["missing <clinical_study>"], {"unresolved": unresolved}

    for element in root.iter():
        value = text_of(element)
        if value.lower() in FORBIDDEN_EXACT:
            errors.append(f"<{element.tag}> contains forbidden literal `{value}`")
        if element.tag == "country" and value.upper() == "USA":
            errors.append("<country> must be `United States`, not `USA`")

    counts = rendered_counts(study)
    expected = expected_counts(reference)
    for key, expected_value in expected.items():
        if counts.get(key) != expected_value:
            errors.append(f"{key} count is {counts.get(key)}, expected {expected_value}")

    if direct_child(study, "overall_contact") is None:
        errors.append("missing <overall_contact>")
    if direct_child(study, "overall_contact_backup") is None:
        errors.append("missing <overall_contact_backup>")

    resp_party_type = nested_child(study, ["sponsors", "resp_party", "resp_party_type"])
    expected_resp_party = str(
        (reference.get("template_fields") or {}).get("responsiblePartyType")
        or ""
    ).strip()
    if expected_resp_party and text_of(resp_party_type) != expected_resp_party:
        errors.append(f"resp_party_type is `{text_of(resp_party_type)}`, expected `{expected_resp_party}`")

    for tag in ["primary_outcome", "secondary_outcome", "other_outcome"]:
        for index, block in enumerate(direct_children(study, tag), start=1):
            validate_outcome_block(block, tag, index, errors)

    approval_status = text_of(nested_child(study, ["oversight_info", "irb_info", "approval_status"]))
    if approval_status and approval_status not in {"Pending", "Approved", "Exempt", "Not Approved"}:
        errors.append(f"approval_status `{approval_status}` is not a normalized PRS status")

    sampling_method = text_of(nested_child(study, ["eligibility", "sampling_method"]))
    if sampling_method and sampling_method not in {"Non-Probability Sample", "Probability Sample"}:
        errors.append(f"sampling_method `{sampling_method}` is not a valid PRS sampling method label")

    enrollment = text_of(direct_child(study, "enrollment"))
    if enrollment and not re.fullmatch(r"\d+", enrollment):
        errors.append(f"enrollment `{enrollment}` must be numeric")

    minimum_age = text_of(nested_child(study, ["eligibility", "minimum_age"]))
    if minimum_age and not PRS_AGE_RE.fullmatch(minimum_age):
        errors.append(f"minimum_age `{minimum_age}` must use PRS age format like `50 Years`")

    for tag in ["start_date", "end_date", "last_follow_up_date", "primary_compl_date"]:
        value = text_of(direct_child(study, tag))
        if value and not ISO_DATE_RE.fullmatch(value):
            errors.append(f"{tag} `{value}` must use YYYY-MM-DD")

    verification_date = text_of(direct_child(study, "verification_date"))
    if verification_date and not VERIFICATION_DATE_RE.fullmatch(verification_date):
        errors.append(f"verification_date `{verification_date}` must use YYYY-MM")

    study_design = direct_child(study, "study_design")
    if study_design is not None:
        observational_design = direct_child(study_design, "observational_design")
        interventional_design = direct_child(study_design, "interventional_design")
        study_type = text_of(direct_child(study_design, "study_type"))
        if observational_design is not None and study_type != "Observational":
            errors.append("study_type must be `Observational` when observational_design is present")
        if interventional_design is not None and study_type != "Interventional":
            errors.append("study_type must be `Interventional` when interventional_design is present")
        if observational_design is not None and interventional_design is not None:
            errors.append("study_design must not contain both observational_design and interventional_design")
        number_of_groups = text_of(nested_child(study_design, ["observational_design", "number_of_groups"]))
        if number_of_groups and not re.fullmatch(r"\d+", number_of_groups):
            errors.append(f"number_of_groups `{number_of_groups}` must be numeric")
        number_of_arms = text_of(nested_child(study_design, ["interventional_design", "number_of_arms"]))
        if number_of_arms and not re.fullmatch(r"\d+", number_of_arms):
            errors.append(f"number_of_arms `{number_of_arms}` must be numeric")

    study_uid = text_of(direct_child(study, "uid"))
    outcome_uids = [
        text_of(direct_child(block, "uid"))
        for tag in ["primary_outcome", "secondary_outcome", "other_outcome"]
        for block in direct_children(study, tag)
    ]
    nonempty_outcome_uids = [uid for uid in outcome_uids if uid]
    unique_outcome_uids = sorted(set(nonempty_outcome_uids))
    if study_uid and any(uid != study_uid for uid in nonempty_outcome_uids):
        errors.append(f"all outcome uid values must match study uid `{study_uid}`")
    elif len(unique_outcome_uids) > 1:
        errors.append(f"outcome uid values differ: {unique_outcome_uids}")

    metadata = {
        "unresolved": unresolved,
        "rendered_counts": counts,
        "expected_counts": expected,
    }
    return errors, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Run directory containing reference and output XML.")
    parser.add_argument("--reference", help="Reference JSON path. Defaults to reference/study.reference.json.")
    parser.add_argument("--xml", help="Rendered XML path. Defaults to output/study.xml.")
    parser.add_argument("--report", help="Report path. Defaults to logs/prs-xml-validation.json.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    reference_path = Path(args.reference).expanduser().resolve() if args.reference else run_dir / STANDARD_REFERENCE
    xml_path = Path(args.xml).expanduser().resolve() if args.xml else run_dir / STANDARD_XML
    report_path = Path(args.report).expanduser().resolve() if args.report else run_dir / STANDARD_REPORT

    reference = load_json(reference_path)
    errors, metadata = validate(xml_path, reference)
    report = {
        "run_dir": ".",
        "reference": display_path(reference_path, run_dir),
        "xml": display_path(xml_path, run_dir),
        "valid": not errors,
        "error_count": len(errors),
        "errors": errors,
        **metadata,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
