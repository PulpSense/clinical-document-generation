#!/usr/bin/env python3
"""Build n8n-compatible retrospective protocol template fields."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STANDARD_REFERENCE = "reference/study.reference.json"
NBSP_BULLET = "•\u00a0\u00a0\u00a0\u00a0"
OPTIONAL_TEMPLATE_FIELDS = {
    "AI_exploratoryOutcomes",
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def get_path(data: Any, dotted_path: str, default: Any = None) -> Any:
    current = data
    for part in dotted_path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else default
        else:
            return default
        if current is None:
            return default
    return current


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(text(item) for item in value if text(item))
    if isinstance(value, dict):
        for key in ("text", "name", "title", "description", "measure"):
            if value.get(key):
                return text(value[key])
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def first_text(*values: Any) -> str:
    for value in values:
        rendered = text(value).strip()
        if rendered:
            return rendered
    return ""


def normalized_text(value: str) -> str:
    return re.sub(r"\W+", " ", value).strip().lower()


def funding_clarification(reference: dict, funding_name: str) -> str:
    explicit = first_text(get_path(reference, "parties.funding_source.clarification"))
    if explicit and normalized_text(explicit) != normalized_text(funding_name):
        return explicit
    if re.search(r"\b(no external funding|investigator[- ]initiated)\b", funding_name, re.IGNORECASE):
        return ""
    return "funding only, this is an investigator-initiated study"


def bulletize(value: Any) -> str:
    rendered = text(value).replace("≥", ">=").replace("≤", "<=").strip()
    if not rendered:
        return ""
    lines = []
    for raw_line in rendered.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[•*\-]\s*", "", line)
        lines.append(NBSP_BULLET + line)
    return "\n".join(lines)


def join_paragraphs(*values: Any) -> str:
    paragraphs = [text(value).strip() for value in values if text(value).strip()]
    return "\n\n".join(paragraphs)


def investigator_initials(name: str) -> str:
    before_comma = name.split(",", 1)[0].strip()
    initials = "".join(part[0].upper() for part in re.split(r"\s+", before_comma) if part)
    return initials or "PROT"


def protocol_number(reference: dict) -> str:
    explicit = first_text(get_path(reference, "meta.protocol_number"))
    if explicit:
        return explicit
    pi_name = first_text(get_path(reference, "parties.principal_investigator.name"))
    year = datetime.now(timezone.utc).strftime("%y")
    return f"{investigator_initials(pi_name)}-{year}-01"


def name_without_repeated_title(name: str, title: str) -> str:
    if not name or not title:
        return name
    pattern = re.compile(rf",\s*{re.escape(title.strip())}$", re.IGNORECASE)
    return pattern.sub("", name).strip()


def address(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        ordered_keys = ["line1", "address_line1", "street", "city", "state", "country", "zip"]
        parts = [text(value.get(key)).strip() for key in ordered_keys if text(value.get(key)).strip()]
        return ", ".join(parts)
    return text(value)


def first_site(reference: dict) -> dict:
    sites = reference.get("sites")
    if isinstance(sites, list) and sites and isinstance(sites[0], dict):
        return sites[0]
    return {}


def list_article_names(value: Any) -> str:
    if isinstance(value, list):
        names = []
        for item in value:
            if isinstance(item, dict):
                names.append(first_text(item.get("Article"), item.get("article"), item.get("name"), item.get("label")))
            else:
                names.append(text(item))
        return "\n".join(item for item in names if item)
    return text(value)


def references_text(reference: dict) -> str:
    refs = reference.get("references") or get_path(reference, "source.references") or []
    if not isinstance(refs, list):
        return text(refs)
    lines = []
    for index, item in enumerate(refs, start=1):
        rendered = first_text(item.get("Reference") if isinstance(item, dict) else None, item)
        if rendered:
            lines.append(f"{index}.\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0{rendered}")
    return "\n".join(lines)


def display_path(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def build_fields(reference: dict) -> dict:
    generated = reference.get("generated") if isinstance(reference.get("generated"), dict) else {}
    protocol = generated.get("protocol") if isinstance(generated.get("protocol"), dict) else {}
    site = first_site(reference)
    facility = site.get("facility") if isinstance(site.get("facility"), dict) else {}
    funding_name = first_text(
        get_path(reference, "parties.funding_source.name"),
        get_path(reference, "parties.funding.name"),
    )
    funding_address = first_text(
        address(get_path(reference, "parties.funding_source.address")),
        address(get_path(reference, "parties.funding.address")),
    )
    subinvestigator = first_text(
        get_path(reference, "parties.sub_investigator.name"),
        get_path(reference, "parties.subinvestigator.name"),
        get_path(reference, "parties.sub_investigator"),
    )
    investigator_title = first_text(
        get_path(reference, "parties.principal_investigator.title"),
        get_path(reference, "parties.principal_investigator.degree"),
    )
    investigator_name = name_without_repeated_title(
        first_text(get_path(reference, "parties.principal_investigator.name")),
        investigator_title,
    )
    test_articles = first_text(
        list_article_names(get_path(reference, "source.n8n_form_fields.areThereAnyTestArticles")),
        list_article_names(get_path(reference, "design.test_articles")),
        list_article_names(get_path(reference, "design.arms")),
    )
    refs = references_text(reference)
    funding_clarification_value = funding_clarification(reference, funding_name) if funding_name else ""

    fields = {
        "AI_shortTitle": first_text(get_path(reference, "study.short_title"), protocol.get("shortTitle")),
        "date": first_text(get_path(reference, "meta.date"), datetime.now(timezone.utc).strftime("%d %b %Y")),
        "title": first_text(get_path(reference, "study.title")),
        "protocolNumber": protocol_number(reference),
        "irbName": first_text(get_path(reference, "parties.irb.name"), get_path(reference, "parties.ethics_committee.name")),
        "irbAdress": first_text(
            get_path(reference, "parties.irb.address"),
            join_paragraphs(get_path(reference, "parties.irb.address_line1"), get_path(reference, "parties.irb.address_line2")),
            get_path(reference, "parties.ethics_committee.address"),
        ),
        "sponsortName": first_text(get_path(reference, "parties.sponsor.name")),
        "sponsortAdress": first_text(address(get_path(reference, "parties.sponsor.address"))),
        "fundingSourceName": f"\n{funding_name}" if funding_name else "",
        "fundingSourceAdress": f"\n{funding_address}" if funding_address else "",
        "fundingSourceClarification": f"\n\n{funding_clarification_value}" if funding_clarification_value else "",
        "testArticle(s)": test_articles,
        "investigatorName": investigator_name,
        "subInvestigatorHas": "Sub-Investigator" if subinvestigator else "",
        "subInvestigatorName": subinvestigator,
        "investigatorTitle": investigator_title,
        "facilityName": first_text(facility.get("name"), get_path(reference, "parties.sponsor.name")),
        "facilityCity": first_text(get_path(site, "facility.address.city")),
        "AI_introduction": first_text(
            protocol.get("introduction"),
            join_paragraphs(protocol.get("introduction_background"), protocol.get("introduction_purpose")),
        ),
        "AI_objectivesIntro": first_text(protocol.get("objectivesIntro"), protocol.get("objectives_intro")),
        "AI_primaryOutcome": bulletize(first_text(protocol.get("primaryOutcomes"), protocol.get("primary_outcomes_bullets"))),
        "AI_secondaryOutcomes": bulletize(
            first_text(protocol.get("secondaryOutcomes"), protocol.get("secondary_outcomes_bullets"))
        ),
        "AI_exploratoryOutcomes": bulletize(
            first_text(protocol.get("exploratoryOutcomes"), protocol.get("exploratory_outcomes_bullets"))
        ),
        "AI_populationLong": first_text(protocol.get("populationLong"), protocol.get("population_long")).replace("≥", ">=").replace("≤", "<="),
        "AI_inclusionCriteria": bulletize(
            first_text(protocol.get("inclusionCriteria"), protocol.get("inclusion_criteria_bullets"))
        ),
        "AI_exclusionCriteria": bulletize(
            first_text(protocol.get("exclusionCriteria"), protocol.get("exclusion_criteria_bullets"))
        ),
        "AI_studyDesignLong": first_text(protocol.get("studyDesignLong"), protocol.get("study_design")),
        "AI_methods": first_text(protocol.get("methods")),
        "AI_analysisDataSets": first_text(protocol.get("analysisDataSets"), protocol.get("analysis_data_sets")),
        "AI_analysisDataSetsBullets": bulletize(
            first_text(protocol.get("analysisDataSetsBullets"), protocol.get("analysis_data_sets_bullets"))
        ),
        "AI_statisticalMethodology": first_text(
            protocol.get("statisticalMethodology"),
            protocol.get("statistical_methodology"),
        ),
        "AI_statisticalConsiderations": first_text(
            protocol.get("statisticalConsiderations"),
            protocol.get("statistical_considerations"),
        ),
        "sampleSizeJustification": first_text(
            protocol.get("sampleSizeJustification"),
            protocol.get("sample_size_justification"),
            get_path(reference, "population.sample_justification"),
            get_path(reference, "statistics.sample_size_justification"),
        ),
        "referencesExists": "REFERENCES" if refs else "",
        "references": refs,
        "AI_studyProcedure": first_text(protocol.get("studyProcedure"), protocol.get("study_procedure")),
        "AI_studyProcedureBullets": bulletize(
            first_text(protocol.get("studyProcedureBullets"), protocol.get("study_procedure_bullets"))
        ),
    }
    return fields


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Run directory containing reference/study.reference.json.")
    parser.add_argument("--reference", help="Reference JSON path. Defaults to reference/study.reference.json.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write the reference. Return nonzero if any required n8n template fields are blank.",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    reference_path = Path(args.reference).expanduser().resolve() if args.reference else run_dir / STANDARD_REFERENCE
    reference = load_json(reference_path)
    fields = build_fields(reference)
    blank = [
        key
        for key, value in fields.items()
        if key.startswith("AI_") and key not in OPTIONAL_TEMPLATE_FIELDS and not str(value).strip()
    ]

    if args.check:
        print(json.dumps({"blank_ai_fields": blank, "template_fields": fields}, indent=2, ensure_ascii=False))
        return 1 if blank else 0

    merged = reference.get("template_fields")
    if not isinstance(merged, dict):
        merged = {}
    merged.update(fields)
    reference["template_fields"] = merged
    reference_path.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "updated": display_path(reference_path, run_dir),
                "field_count": len(fields),
                "blank_ai_fields": blank,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
