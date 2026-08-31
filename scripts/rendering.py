"""Word-targeted DOCX rendering from accepted section drafts."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.shared import Inches
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml import etree as ET
from pypdf import PdfReader

from contracts import BOILERPLATE_VERSION, LAYOUT_REPAIR_RULES, canonical_study_type, contracted_template_bundle, get_path, meaningful, protocol_contract, recovery_finding


TOKEN = re.compile(r"\{[#/^]?[A-Za-z_][A-Za-z0-9_.\-\[\]()&]*\}")
INTERNAL_LANGUAGE = re.compile(r"\b(?:section_id|evidence_refs|boilerplate_refs)\s*:", re.I)
DUPLICATE_WORD = re.compile(r"\b([A-Za-z][A-Za-z'-]+)\s+\1\b", re.I)
AUTHORING_LANGUAGE = re.compile(r"table of contents updates automatically|selected consent template", re.I)


class LayoutRepairTargetError(ValueError):
    """A classified repair did not identify one exact generated element."""



def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, Mapping):
        for key in ("text", "label", "measure", "name", "title", "description"):
            if meaningful(value.get(key)):
                return _text(value[key])
        return ""
    if isinstance(value, Iterable):
        return "\n".join(part for item in value if (part := _text(item)))
    return str(value).strip()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return [part.strip() for part in _text(value).splitlines() if part.strip()]
    return [part for item in value if (part := _text(item))]


def _draft_text(model: Mapping[str, Any], section_id: str, *, bullets: bool = False) -> str:
    section = next((item for item in model.get("protocol", []) if item.get("section_id") == section_id), {})
    values = [str(item.get("text") or "").strip() for item in section.get("paragraphs", []) if str(item.get("text") or "").strip()]
    list_values: list[str] = []
    for group in section.get("lists", []):
        list_values.extend(_list(group.get("items") if isinstance(group, Mapping) else group))
    if list_values:
        values.append("\n".join(f"• {item}" for item in list_values))
    return "\n\n".join(values).strip()


def _icf_text(model: Mapping[str, Any], section_id: str) -> str:
    draft = model.get("icf", {}).get(section_id, {})
    values = [str(item.get("text") or "").strip() for item in draft.get("paragraphs", []) if str(item.get("text") or "").strip()]
    for group in draft.get("lists", []):
        values.extend(f"• {item}" for item in _list(group.get("items") if isinstance(group, Mapping) else group))
    return "\n\n".join(values).strip()


def _overview_and_detail(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    paragraphs = [item.strip() for item in text.split("\n\n") if item.strip()]
    if len(paragraphs) > 1:
        return paragraphs[0], "\n\n".join(paragraphs[1:])
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text) if item.strip()]
    return (sentences[0], " ".join(sentences[1:])) if len(sentences) > 1 else (text, "")


def _icf_procedure_parts(model: Mapping[str, Any]) -> tuple[str, str]:
    return _overview_and_detail(_icf_text(model, "icf.procedures"))


def _first_site(reference: Mapping[str, Any]) -> Mapping[str, Any]:
    sites = reference.get("sites") if isinstance(reference.get("sites"), list) else []
    return sites[0] if sites and isinstance(sites[0], Mapping) else {}


def _address(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        keys = ("line1", "address_line1", "street", "city", "state", "country", "zip")
        return ", ".join(_text(value.get(key)) for key in keys if _text(value.get(key)))
    return _text(value)


def _endpoint_text(reference: Mapping[str, Any], kinds: Iterable[str] = ("primary", "secondary", "other")) -> str:
    values = []
    for kind in kinds:
        for item in get_path(reference, f"endpoints.{kind}", []) or []:
            label = _text(item)
            timepoint = _text(item.get("time_point") or item.get("time_frame")) if isinstance(item, Mapping) else ""
            if label:
                values.append(f"{label}{f' ({timepoint})' if timepoint else ''}")
    return "\n".join(f"• {item}" for item in values)


def _document_control_date(reference: Mapping[str, Any]) -> str:
    supplied = _text(get_path(reference, "meta.date"))
    return supplied


def _protocol_short_title(reference: Mapping[str, Any]) -> str:
    supplied = _text(get_path(reference, "study.short_title"))
    if supplied:
        return supplied
    title = _text(get_path(reference, "study.title"))
    branch = canonical_study_type(get_path(reference, "meta.study_type"))
    if branch:
        title = re.sub(rf"^\s*{re.escape(branch)}\s+", "", title, flags=re.I)
    title = re.sub(r"^\s*Evaluation\s+of\s+the\s+", "", title, flags=re.I)
    return title


def _protocol_number(reference: Mapping[str, Any]) -> str:
    return _text(get_path(reference, "meta.protocol_number") or get_path(reference, "regulatory.prs.provider_study_id"))


def render_fields(reference: Mapping[str, Any], model: Mapping[str, Any]) -> dict[str, str]:
    site = _first_site(reference)
    facility = site.get("facility") if isinstance(site.get("facility"), Mapping) else {}
    coordinator = get_path(reference, "parties.study_coordinator", {}) or {}
    investigator = get_path(reference, "parties.principal_investigator", {}) or {}
    sponsor = get_path(reference, "parties.sponsor", {}) or {}
    irb = get_path(reference, "parties.irb", {}) or {}
    raw_facility_address = facility.get("address")
    if isinstance(raw_facility_address, Mapping):
        facility_street = _text(raw_facility_address.get("street") or raw_facility_address.get("address"))
        facility_city = _text(raw_facility_address.get("city") or facility.get("city"))
        facility_state = _text(raw_facility_address.get("state") or facility.get("state"))
        facility_country = _text(raw_facility_address.get("country") or facility.get("country"))
    else:
        facility_street = _text(raw_facility_address)
        facility_city = _text(facility.get("city"))
        facility_state = _text(facility.get("state"))
        facility_country = _text(facility.get("country"))
    facility_locality = ", ".join(filter(None, (facility_city, facility_state, facility_country)))
    visits = get_path(reference, "procedures.visit_schedule", []) or get_path(reference, "procedures.assessments", []) or []
    inclusion = _list(get_path(reference, "population.inclusion_criteria", []))
    branch = canonical_study_type(get_path(reference, "meta.study_type")) or ""
    icf_visits_overview, icf_visit_details = _icf_procedure_parts(model)
    protocol_visits_overview, protocol_visit_details = _overview_and_detail(_draft_text(model, "study-procedure.visits"))
    values = {
        "title": _text(get_path(reference, "study.title")), "studyTitle": _text(get_path(reference, "study.title")),
        "AI_shortTitle": _protocol_short_title(reference),
        "protocolNumber": _protocol_number(reference),
        "version": _text(get_path(reference, "meta.version")),
        "date": _document_control_date(reference),
        "sponsortName": _text(sponsor.get("name")), "sponsorName": _text(sponsor.get("name")),
        "sponsortAdress": _address(sponsor.get("address")), "sponsorAdress": _address(sponsor.get("address")),
        "investigatorName": _text(investigator.get("name")), "principalInvestigatorName": _text(investigator.get("name")),
        "investigatorTitle": _text(investigator.get("title") or investigator.get("degree")),
        "InvestigatorLast": _text(investigator.get("name")).split()[-1] if _text(investigator.get("name")) else "",
        "subInvestigatorHas": "Sub-Investigator" if meaningful(get_path(reference, "parties.sub_investigators")) else "",
        "subInvestigatorName": _text(get_path(reference, "parties.sub_investigators")),
        "ibrName": _text(irb.get("name")), "irbName": _text(irb.get("name")),
        "ibrAdress": _address(irb.get("address")), "irbAdress": _address(irb.get("address")),
        "irbPhone": _text(irb.get("phone")), "irbEmail": _text(irb.get("email")),
        "facilityName": _text(facility.get("name")), "facilityLocation": facility_locality or _address(raw_facility_address),
        "facilityAddress": facility_street or _address(raw_facility_address), "facilityCity": facility_city,
        "studyCordinatorName": _text(coordinator.get("name")),
        "studyCordinatorPhone": _text(coordinator.get("business_phone") or coordinator.get("phone")),
        "studyCordinator24Phone": _text(coordinator.get("office_phone")), "studyCordinatorEmail": _text(coordinator.get("email")),
        "studyContactPhones": " / ".join(filter(None, [_text(coordinator.get("business_phone")), _text(coordinator.get("office_phone"))])),
        "sterlingSecondaryPhone": _text(coordinator.get("office_phone")),
        "objective": "; ".join(_list(get_path(reference, "objectives.primary", []))),
        "studyDesignShort": _text(get_path(reference, "design.study_design")), "sitesNumber": _text(get_path(reference, "design.number_of_sites")),
        "sampleSize": _text(get_path(reference, "population.sample_size")),
        "sampleSizeJustification": _draft_text(model, "sample-size") or _text(get_path(reference, "population.sample_justification")),
        "interventionName": _text(get_path(reference, "design.intervention_name")),
        "daysBeforeScreening": _text(get_path(reference, "procedures.minimum_days_before_screening_without_participation")),
        "inclusionCriteria": "\n".join(f"• {item}" for item in inclusion), "totalVisits": str(len(visits)) if isinstance(visits, list) else "",
        "AI_duration": _text(get_path(reference, "study.timeline")), "AI_populationShort": _text(get_path(reference, "population.study_population")),
        "AI_populationLong": _draft_text(model, "subjects.population"), "AI_introduction": _draft_text(model, "introduction"),
        "AI_inclusionCriteria": _draft_text(model, "subjects.inclusion", bullets=True) or "\n".join(f"• {item}" for item in inclusion),
        "AI_exclusionCriteria": _draft_text(model, "subjects.exclusion", bullets=True) or _draft_text(model, "subjects.eligibility", bullets=True),
        "AI_studyDesignLong": _draft_text(model, "study-design.design"), "AI_methods": _draft_text(model, "study-design.bias"),
        "AI_visitSchedule": protocol_visits_overview, "AI_visitScheduleDetails": protocol_visit_details,
        "AI_measurements": _draft_text(model, "study-procedure.measurements"),
        "AI_measurementsDetails": _draft_text(model, "evaluation-procedures") or _draft_text(model, "study-procedure.measurements"),
        "AI_analysisDataSets": _draft_text(model, "analysis-plan.datasets"), "AI_analysisDataSetsBullets": "",
        "AI_statisticalMethodology": _draft_text(model, "analysis-plan.methodology"),
        "AI_statisticalConsiderations": _draft_text(model, "analysis-plan.considerations"),
        "AI_risks": _draft_text(model, "risks-benefits.risks") or _text(get_path(reference, "risks_benefits.risks")),
        "AI_benefits": _icf_text(model, "icf.benefits") or _draft_text(model, "risks-benefits.benefits"),
        "AI_masked": _text(get_path(reference, "design.masking")), "AI_variables": _endpoint_text(reference),
        "AI_objectivesIntro": _draft_text(model, "objectives"), "AI_primaryOutcome": _endpoint_text(reference, ("primary",)),
        "AI_secondaryOutcomes": _endpoint_text(reference, ("secondary",)), "AI_exploratoryOutcomes": _endpoint_text(reference, ("other",)) or "Not applicable; no exploratory outcomes were specified in the approved source.",
        "AI_studyProcedure": _draft_text(model, "study-procedure.enrollment"), "AI_studyProcedureBullets": "",
        "AI_studyPurpose": _icf_text(model, "icf.study-purpose"), "AI_icfVisitsOverview": icf_visits_overview,
        "AI_visitsDetails": icf_visit_details, "AI_visitsAndLength": _icf_text(model, "icf.duration"),
        "AI_interventionPossibleSideEffects": _icf_text(model, "icf.risks"), "AI_payment": _icf_text(model, "icf.payment"),
        "AI_costs": _icf_text(model, "icf.costs"), "AI_alternatives": _icf_text(model, "icf.alternatives"),
        "AI_privacy": _icf_text(model, "icf.privacy"), "AI_injuryCompensation": _icf_text(model, "icf.injury"),
        "AI_authorizationDuration": _icf_text(model, "icf.privacy"),
        "referencesExists": "REFERENCES" if _text(reference.get("references")) else "",
        "references": _text(reference.get("references")),
        "fundingSourceName": _text(get_path(reference, "parties.funding_source.name")), "fundingSourceAdress": _address(get_path(reference, "parties.funding_source.address")),
        "fundingSourceClarification": _text(get_path(reference, "parties.funding_source.clarification")),
        "testArticle(s)": _text(get_path(reference, "design.arms")) or _text(get_path(reference, "design.intervention_name")),
        "controlArticle(s)": _text(get_path(reference, "design.control")),
    }
    if branch == "Retrospective":
        values["AI_inclusionCriteria"] = _draft_text(model, "subjects.eligibility", bullets=True)
        values["AI_exclusionCriteria"] = _draft_text(model, "subjects.eligibility", bullets=True)
    return {key: value.strip() for key, value in values.items() if isinstance(value, str)}


def _all_paragraphs(document: Document):
    yield from document.paragraphs
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs
    for section in document.sections:
        yield from section.header.paragraphs
        yield from section.footer.paragraphs
        for container in (section.header, section.footer):
            for table in container.tables:
                for row in table.rows:
                    for cell in row.cells:
                        yield from cell.paragraphs


def _replace_paragraph(paragraph, fields: Mapping[str, str]) -> None:
    original = paragraph.text
    if "{" not in original:
        return
    for run in paragraph.runs:
        rendered = run.text
        for token in sorted(set(TOKEN.findall(rendered)), key=len, reverse=True):
            replacement = fields.get(token.strip("{}").lstrip("#^/"), "")
            if token == "{version}" and not replacement:
                rendered = re.sub(r"\b(?:version|v)\s*" + re.escape(token), "", rendered, flags=re.I)
            if re.search(re.escape(token) + r"\s+IRB\b", rendered, re.I) and replacement.casefold().endswith(" irb"):
                replacement = replacement[:-4].rstrip()
            rendered = rendered.replace(token, replacement)
        run.text = rendered
    if "{version}" in original and not fields.get("version") and paragraph.text.strip().casefold() in {"version", "v"}:
        for run in paragraph.runs:
            run.text = ""


def _normalize_generated_placeholder_layout(document: Document) -> None:
    intentionally_indented = {"{AI_inclusionCriteria}", "{AI_exclusionCriteria}"}
    for paragraph in document.paragraphs:
        tokens = set(TOKEN.findall(paragraph.text))
        if not any(token.startswith("{AI_") for token in tokens):
            continue
        if tokens & intentionally_indented:
            paragraph.paragraph_format.right_indent = None
            continue
        paragraph.paragraph_format.left_indent = None
        paragraph.paragraph_format.right_indent = None
        paragraph.paragraph_format.first_line_indent = None
        paragraph.paragraph_format.alignment = None


def _insert_before(target, text: str, style: str) -> None:
    paragraph = target._parent.add_paragraph(text, style=style)
    target._p.addprevious(paragraph._p)


def _ensure_contract_headings(document: Document, branch: str) -> None:
    if branch != "Retrospective": return
    if not any(paragraph.style.name.casefold().startswith("heading") and paragraph.text.strip().startswith("8.1.") for paragraph in document.paragraphs):
        paragraphs = list(document.paragraphs)
        index = next((i for i, paragraph in enumerate(paragraphs) if paragraph.text.strip() == "8. STUDY PROCEDURE"), None)
        if index is not None:
            target = paragraphs[index + 1] if index + 1 < len(paragraphs) else None
            if target is not None: _insert_before(target, "8.1. Informed Consent / Subject Enrollment", "Heading 2")


def _split_heading_content(document: Document) -> None:
    """Keep generated body prose out of Heading runs and therefore out of the Word TOC."""
    for paragraph in list(document.paragraphs):
        if not paragraph.style.name.casefold().startswith("heading") or "\n" not in paragraph.text:
            continue
        lines = [line.strip() for line in paragraph.text.splitlines() if line.strip()]
        if not lines:
            continue
        paragraph.text = lines[0]
        for line in reversed(lines[1:]):
            body = paragraph._parent.add_paragraph(line, style="Normal")
            paragraph._p.addnext(body._p)


def _normalize_protocol_heading_spacing(document: Document) -> None:
    """Keep subsection headings visibly separate from their first body line."""
    for paragraph in document.paragraphs:
        if not paragraph.style.name.casefold().startswith("heading"):
            continue
        paragraph.text = paragraph.text.rstrip()
        paragraph.paragraph_format.keep_with_next = True
        paragraph.paragraph_format.keep_together = True
        if paragraph.paragraph_format.space_after is None or paragraph.paragraph_format.space_after < Pt(6):
            paragraph.paragraph_format.space_after = Pt(6)


def _normalize_protocol_summary_table(document: Document) -> None:
    labels = {
        "objective": "Objective",
        "test article(s)": "Test Article(s)",
        "control article(s)": "Control Article(s)",
        "sample size": "Sample size",
        "study population": "Study Population",
        "number of sites": "Number of sites",
        "study design": "Study Design",
        "masking": "Masking",
        "variables": "Variables",
        "duration/follw-up": "Duration / Follow-up",
        "duration / follow-up": "Duration / Follow-up",
    }
    table = next((
        item for item in document.tables
        if item.rows and item.rows[0].cells[0].text.strip().casefold() == "objective"
        and any(row.cells[0].text.strip().casefold() == "masking" for row in item.rows)
    ), None)
    if table is None:
        return
    optional_labels = {"control article(s)", "masking"}
    for row in list(table.rows):
        paragraph = row.cells[0].paragraphs[0]
        current = paragraph.text.strip().casefold()
        if current in optional_labels and not row.cells[1].text.strip():
            table._tbl.remove(row._tr)
            continue
        if current in labels:
            if paragraph.runs:
                paragraph.runs[0].text = labels[current]
                for extra in paragraph.runs[1:]:
                    extra.text = ""
            else:
                paragraph.add_run(labels[current])
        paragraph.paragraph_format.left_indent = None
        paragraph.paragraph_format.right_indent = None
        paragraph.paragraph_format.first_line_indent = None
        row.height = None
        _prevent_row_split(row)


def _normalize_protocol_title_controls(document: Document, reference: Mapping[str, Any]) -> None:
    """Expose the approved/default Protocol date without inventing a version."""
    protocol_date = _document_control_date(reference)
    if not protocol_date:
        return
    table = next((
        item for item in document.tables
        if item.rows and item.rows[0].cells[0].text.strip().casefold() == "protocol number"
    ), None)
    if table is None:
        return
    existing = next((
        row for row in table.rows
        if row.cells[0].text.strip().casefold() == "protocol date"
    ), None)
    if existing is not None:
        _set_paragraph_text(existing.cells[1].paragraphs[0], protocol_date)
        return
    anchor = table.rows[1] if len(table.rows) > 1 else table.rows[0]
    clone = copy.deepcopy(anchor._tr)
    anchor._tr.addnext(clone)
    inserted = table.rows[list(table._tbl.tr_lst).index(clone)]
    _set_paragraph_text(inserted.cells[0].paragraphs[0], "Protocol Date")
    _set_paragraph_text(inserted.cells[1].paragraphs[0], protocol_date)


def _protocol_heading_key(value: str) -> str:
    first_line = next((line for line in value.splitlines() if line.strip()), "")
    normalized = re.sub(r"(?<=\d)\.(?=\s|$)", "", first_line)
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def _protocol_title_key(value: str) -> str:
    first_line = next((line for line in value.splitlines() if line.strip()), "")
    without_number = re.sub(r"^\s*\d+(?:\s*\.\s*\d+)*\s*\.?\s*", "", first_line)
    return re.sub(r"\s+", " ", without_number).strip().casefold()


def _heading_level(paragraph: Paragraph) -> int | None:
    if not paragraph.style.name.casefold().startswith("heading"):
        return None
    match = re.search(r"(\d+)$", paragraph.style.name)
    return int(match.group(1)) if match else 1


def _set_paragraph_text(paragraph: Paragraph, text: str) -> None:
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)


def _normalize_protocol_container_introductions(
    document: Document,
    branch: str,
    boilerplate: Mapping[str, str],
) -> None:
    sections = list(protocol_contract(branch))
    for index, section in enumerate(sections[:-1]):
        if section.role != "container":
            continue
        next_section = sections[index + 1]
        if not next_section.number.startswith(section.number):
            continue
        expected = _protocol_heading_key(f"{section.number} {section.title}")
        heading = next((
            paragraph for paragraph in document.paragraphs
            if _heading_level(paragraph) is not None and _protocol_heading_key(paragraph.text) == expected
        ), None)
        if heading is None:
            continue
        element = heading._p.getnext()
        exemplar = None
        while element is not None:
            following = element.getnext()
            if element.tag == qn("w:p") and _heading_level(Paragraph(element, document)) is not None:
                break
            if exemplar is None and element.tag == qn("w:p"):
                exemplar = Paragraph(element, document)
            element.getparent().remove(element)
            element = following
        if section.boilerplate_key:
            paragraph = document.add_paragraph()
            _copy_paragraph_design(paragraph, exemplar)
            run = paragraph.add_run(boilerplate[section.boilerplate_key])
            _copy_run_design(run, _first_visible_run(exemplar))
            heading._p.addnext(paragraph._p)


def _study_descriptor(reference: Mapping[str, Any]) -> str:
    branch = (canonical_study_type(get_path(reference, "meta.study_type")) or "clinical").casefold()
    registry_type = _text(get_path(reference, "regulatory.prs.study_type")).casefold()
    intervention_type = _text(get_path(reference, "design.intervention_type")).casefold()
    if registry_type == "observational":
        description = " ".join(part for part in (branch, "observational", intervention_type, "study") if part)
    else:
        description = " ".join(part for part in (branch, registry_type, "study") if part)
    article = "An" if description[:1] in "aeiou" else "A"
    return f"{article} {description}"


def _normalize_source_bound_shell(document: Document, reference: Mapping[str, Any], *, icf: bool) -> None:
    observational = _text(get_path(reference, "regulatory.prs.study_type")).casefold() == "observational"
    irb = _text(get_path(reference, "parties.irb.name"))
    irb_display = irb if "irb" in irb.casefold() else f"{irb} IRB" if irb else "the reviewing IRB"
    for paragraph in list(_all_paragraphs(document)):
        text = paragraph.text
        normalized = text.strip()
        unsupported_protocol_claims = (
            "the study will be registered with clinicaltrials.gov.",
            "the study will be conducted in compliance with the protocol, gcp and applicable regulatory requirements",
        )
        if not icf and any(claim in normalized.casefold() for claim in unsupported_protocol_claims):
            retained_lines = [
                line for line in text.splitlines()
                if line.strip() and line.strip().casefold() not in unsupported_protocol_claims
            ]
            if retained_lines:
                _set_paragraph_text(paragraph, "\n".join(retained_lines))
            else:
                paragraph._element.getparent().remove(paragraph._element)
        elif not icf and normalized.casefold() == "an investigator-initiated clinical trial":
            _set_paragraph_text(paragraph, _study_descriptor(reference))
        elif icf and normalized.upper() == "NOT TO BE USED FOR PARTICIPANT ENROLLMENT":
            paragraph._element.getparent().remove(paragraph._element)
        elif icf:
            replacement = text.replace("Advarra Institutional Review Board (IRB)", irb_display)
            if observational:
                replacement = re.sub(r"\bclinical trial\b", "research study", replacement, flags=re.I)
            prospective_advarra = (
                canonical_study_type(get_path(reference, "meta.study_type")) == "Prospective"
                and str(get_path(reference, "meta.icf_template", "Advarra")).casefold() != "sterling"
            )
            if prospective_advarra and "The above statement" in replacement and "In Case of an Injury Related to This Research Study" in replacement:
                replacement = replacement.split("The above statement", 1)[0].rstrip().rstrip("“\"").strip()
            if replacement != text:
                _set_paragraph_text(paragraph, replacement)


def _replace_protocol_investigator_agreement(
    document: Document,
    boilerplate: Mapping[str, str],
    branch: str,
    authority: Document,
) -> None:
    heading = next((
        paragraph for paragraph in document.paragraphs
        if _protocol_heading_key(paragraph.text) == _protocol_heading_key("2. INVESTIGATOR AGREEMENT")
    ), None)
    if heading is None:
        return
    parent = heading._p.getparent()
    siblings = list(parent)
    start = siblings.index(heading._p)
    for element in siblings[start + 1:]:
        if element.tag == qn("w:sectPr"):
            break
        if element.tag == qn("w:p"):
            paragraph = Paragraph(element, document)
            if _heading_level(paragraph) is not None:
                break
            parent.remove(element)
    agreement_key = "investigator-agreement-retrospective" if branch == "Retrospective" else "investigator-agreement-prospective"
    statements = [
        boilerplate[agreement_key],
        boilerplate["investigator-principle-ethics"],
        boilerplate["investigator-principle-law"],
        boilerplate["investigator-principle-protocol"],
    ]
    exemplars = _protocol_body_exemplars(authority, heading)
    anchor = heading._p
    for index, statement in enumerate(statements):
        exemplar = exemplars[min(index, len(exemplars) - 1)] if exemplars else None
        paragraph = document.add_paragraph()
        _copy_paragraph_design(paragraph, exemplar)
        run = paragraph.add_run(statement)
        _copy_run_design(run, _first_visible_run(exemplar))
        if index:
            _apply_bullet_numbering(document, paragraph)
        anchor.addnext(paragraph._p)
        anchor = paragraph._p


def _draft_blocks(section: Mapping[str, Any]) -> list[tuple[str, bool]]:
    blocks: list[tuple[str, bool]] = []
    for paragraph in section.get("paragraphs", []):
        if not isinstance(paragraph, Mapping):
            continue
        blocks.extend((part.strip(), False) for part in str(paragraph.get("text") or "").split("\n\n") if part.strip())
    for group in section.get("lists", []):
        if not isinstance(group, Mapping):
            continue
        blocks.extend((item, True) for item in _list(group.get("items")))
    return blocks


def _bullet_num_id(document: Document) -> int:
    numbering = document.part.numbering_part.element
    abstracts = {
        item.get(qn("w:abstractNumId")): item
        for item in numbering.findall(qn("w:abstractNum"))
    }

    def is_bullet(abstract) -> bool:
        level = next((item for item in abstract.findall(qn("w:lvl")) if item.get(qn("w:ilvl")) == "0"), None)
        number_format = None if level is None else level.find(qn("w:numFmt"))
        return number_format is not None and number_format.get(qn("w:val")) == "bullet"

    for item in numbering.findall(qn("w:num")):
        abstract_id = item.find(qn("w:abstractNumId"))
        abstract = abstracts.get(None if abstract_id is None else abstract_id.get(qn("w:val")))
        if abstract is not None and is_bullet(abstract):
            return int(item.get(qn("w:numId")))
    abstract_id, _abstract = next(((key, value) for key, value in abstracts.items() if is_bullet(value)), (None, None))
    if abstract_id is None:
        raise ValueError("Client Word template has no bullet numbering definition.")
    existing_ids = [int(item.get(qn("w:numId"))) for item in numbering.findall(qn("w:num"))]
    num_id = max(existing_ids, default=0) + 1
    instance = OxmlElement("w:num")
    instance.set(qn("w:numId"), str(num_id))
    abstract_reference = OxmlElement("w:abstractNumId")
    abstract_reference.set(qn("w:val"), str(abstract_id))
    instance.append(abstract_reference)
    numbering.append(instance)
    return num_id


def _numbering_level(document: Document, number_id: int, level_id: int = 0):
    numbering = document.part.numbering_part.element
    number = next(
        item for item in numbering.findall(qn("w:num"))
        if int(item.get(qn("w:numId"))) == number_id
    )
    abstract_id = int(number.find(qn("w:abstractNumId")).get(qn("w:val")))
    abstract = next(
        item for item in numbering.findall(qn("w:abstractNum"))
        if int(item.get(qn("w:abstractNumId"))) == abstract_id
    )
    return next(
        item for item in abstract.findall(qn("w:lvl"))
        if int(item.get(qn("w:ilvl"))) == level_id
    )


def _apply_authority_bullet_numbering(document: Document, authority: Document) -> None:
    """Use the retained client's real bullet marker, font, and hanging indent."""
    source_paragraph = next((
        paragraph for paragraph in _all_paragraphs(authority)
        if paragraph._p.pPr is not None and paragraph._p.pPr.find(qn("w:numPr")) is not None
    ), None)
    if source_paragraph is None:
        return
    source_numbering = source_paragraph._p.pPr.find(qn("w:numPr"))
    source_number_id = int(source_numbering.find(qn("w:numId")).get(qn("w:val")))
    source_level_id = int(source_numbering.find(qn("w:ilvl")).get(qn("w:val")))
    source_level = _numbering_level(authority, source_number_id, source_level_id)
    number_format = source_level.find(qn("w:numFmt"))
    if number_format is None or number_format.get(qn("w:val")) != "bullet":
        return
    target_level = _numbering_level(document, _bullet_num_id(document))
    target_level.getparent().replace(target_level, copy.deepcopy(source_level))


def _apply_bullet_numbering(document: Document, paragraph: Paragraph) -> None:
    properties = paragraph._p.get_or_add_pPr()
    existing = properties.find(qn("w:numPr"))
    if existing is not None:
        properties.remove(existing)
    numbering = OxmlElement("w:numPr")
    level = OxmlElement("w:ilvl")
    level.set(qn("w:val"), "0")
    number = OxmlElement("w:numId")
    number.set(qn("w:val"), str(_bullet_num_id(document)))
    numbering.extend((level, number))
    properties.append(numbering)
    paragraph.paragraph_format.left_indent = None
    paragraph.paragraph_format.first_line_indent = None


def _normalize_typed_bullet_paragraphs(document: Document) -> None:
    """Promote mapped bullet text into native Word list paragraphs."""
    for paragraph in list(_all_paragraphs(document)):
        lines = [line.strip() for line in paragraph.text.splitlines() if line.strip()]
        if not lines or not all(line.startswith("•") for line in lines):
            continue
        items = [line.removeprefix("•").strip() for line in lines]
        _set_paragraph_text(paragraph, items[0])
        _apply_bullet_numbering(document, paragraph)
        anchor = paragraph._p
        for item in items[1:]:
            following = paragraph._parent.add_paragraph()
            _copy_paragraph_design(following, paragraph)
            _set_paragraph_text(following, item)
            _apply_bullet_numbering(document, following)
            anchor.addnext(following._p)
            anchor = following._p


def _replace_protocol_leaf_bodies(
    document: Document,
    model: Mapping[str, Any],
    branch: str,
    authority: Document,
) -> None:
    """Use the client shell for design and accepted section drafts for clinical body content."""
    drafts = {str(item.get("section_id")): item for item in model.get("protocol", []) if isinstance(item, Mapping)}
    table_sections = {"study-procedure.visits", "quality-safety.reporting", "evaluation-procedures"}
    for section in protocol_contract(branch):
        if section.role == "container":
            continue
        blocks = _draft_blocks(drafts.get(section.section_id, {}))
        if not blocks:
            continue
        expected = _protocol_heading_key(f"{section.number} {section.title}")
        heading = next((
            paragraph for paragraph in document.paragraphs
            if _heading_level(paragraph) is not None and _protocol_heading_key(paragraph.text) == expected
        ), None)
        if heading is None:
            continue
        if "\n" in heading.text:
            heading_text = next((line.strip() for line in heading.text.splitlines() if line.strip()), "")
            _set_paragraph_text(heading, heading_text)
        level = _heading_level(heading) or 1
        parent = heading._p.getparent()
        siblings = list(parent)
        start = siblings.index(heading._p)
        removable = []
        caption_open = False
        for element in siblings[start + 1:]:
            if element.tag == qn("w:sectPr"):
                break
            if element.tag == qn("w:p"):
                paragraph = Paragraph(element, document)
                next_level = _heading_level(paragraph)
                if next_level is not None and next_level <= level:
                    break
                if (
                    not paragraph.text.strip()
                    and paragraph._p.xpath('.//w:br[@w:type="page"]')
                ):
                    following = element.getnext()
                    while following is not None and following.tag == qn("w:p"):
                        following_paragraph = Paragraph(following, document)
                        if following_paragraph.text.strip():
                            break
                        following = following.getnext()
                    if (
                        following is not None
                        and following.tag == qn("w:p")
                        and _heading_level(Paragraph(following, document)) is not None
                    ):
                        break
                if section.section_id in table_sections and paragraph.text.strip().casefold().startswith("table "):
                    caption_open = True
                    continue
                if section.section_id in table_sections and caption_open:
                    continue
            elif element.tag == qn("w:tbl") and section.section_id in table_sections:
                caption_open = False
                continue
            removable.append(element)
        for element in removable:
            parent.remove(element)
        exemplar = _protocol_body_exemplar(authority, heading)
        anchor = heading._p
        for text, is_list in blocks:
            paragraph = document.add_paragraph()
            _copy_paragraph_design(paragraph, exemplar)
            run = paragraph.add_run(text)
            _copy_run_design(run, _first_visible_run(exemplar))
            if is_list:
                _apply_bullet_numbering(document, paragraph)
            anchor.addnext(paragraph._p)
            anchor = paragraph._p


def _icf_heading_key(value: str) -> str:
    normalized = re.sub(r"\s*/\s*", "/", str(value).upper())
    normalized = normalized.replace("&", "AND")
    return re.sub(r"[^A-Z0-9/]+", " ", normalized).strip()


_ADVARRA_ICF_HEADINGS = {
    "icf.study-purpose": "PURPOSE OF THE STUDY",
    "icf.procedures": "WHAT WILL HAPPEN DURING THE STUDY",
    "icf.duration": "LENGTH OF THE STUDY AND NUMBER OF PARTICIPANTS EXPECTED",
    "icf.risks": "SIDE EFFECTS AND OTHER RISKS",
    "icf.benefits": "POSSIBLE BENEFITS OF THE STUDY",
    "icf.payment": "PAYMENT FOR BEING IN THE STUDY",
    "icf.costs": "ADDITIONAL COSTS",
    "icf.alternatives": "ALTERNATIVES TO PARTICIPATION",
    "icf.privacy": "RELEASE OF MEDICAL RECORDS AND PRIVACY",
    "icf.injury": "IN CASE OF AN INJURY RELATED TO THIS RESEARCH STUDY",
}
_STERLING_ICF_HEADINGS = {
    "icf.study-purpose": "PURPOSE",
    "icf.procedures": "PROCEDURES",
    "icf.duration": "DURATION",
    "icf.risks": "POTENTIAL RISKS, EFFECTS, DISCOMFORTS, INCONVENIENCES",
    "icf.benefits": "POTENTIAL BENEFITS",
    "icf.payment": "COMPENSATION TO YOU",
    "icf.costs": "COSTS TO YOU",
    "icf.alternatives": "ALTERNATIVE TREATMENTS",
    "icf.privacy": "CONFIDENTIALITY AUTHORIZATION TO COLLECT, USE DISCLOSE YOUR MEDICAL INFORMATION",
    "icf.injury": "STUDY COMPLICATIONS COMPENSATION",
}
_ADVARRA_RETAINED_HEADINGS = {
    "INTRODUCTION", "LEGAL RIGHTS", "NEW FINDINGS", "WHOM TO CONTACT ABOUT THIS STUDY",
    "LEAVING THE STUDY", "AGREEMENT TO BE IN THE STUDY",
}
_STERLING_RETAINED_HEADINGS = {
    "AUTHORIZATION TO USE AND DISCLOSE MEDICAL INFORMATION", "KEY INFORMATION", "BACKGROUND",
    "INFORMATION", "VOLUNTARY PARTICIPATION/WITHDRAWAL", "QUESTIONS",
    "PARTICIPANT STATEMENT AUTHORIZATION",
}
_ADVARRA_ICF_HEADING_KEYS = {
    _icf_heading_key(value)
    for value in set(_ADVARRA_ICF_HEADINGS.values()) | _ADVARRA_RETAINED_HEADINGS
}
_STERLING_ICF_HEADING_KEYS = {
    _icf_heading_key(value)
    for value in set(_STERLING_ICF_HEADINGS.values()) | _STERLING_RETAINED_HEADINGS
}

_REVIEW_PARTS = {
    "word/comments.xml",
    "word/commentsExtended.xml",
    "word/commentsExtensible.xml",
    "word/commentsIds.xml",
    "word/people.xml",
}
_REVISION_ELEMENTS = {
    "commentRangeStart", "commentRangeEnd", "commentReference",
    "del", "moveFrom", "moveFromRangeStart", "moveFromRangeEnd",
    "pPrChange", "rPrChange", "sectPrChange", "tblPrChange", "tblGridChange",
    "tcPrChange", "trPrChange", "numberingChange",
}
_ACCEPTED_REVISION_ELEMENTS = {"ins", "moveTo"}


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _clean_review_xml(name: str, data: bytes) -> bytes:
    """Accept tracked insertions and remove comments, deletions, and hidden review runs."""
    try:
        root = ET.fromstring(data)
    except ET.XMLSyntaxError:
        return data
    changed = False
    if name == "[Content_Types].xml":
        for child in list(root):
            if str(child.attrib.get("PartName", "")).lstrip("/") in _REVIEW_PARTS:
                root.remove(child); changed = True
    elif name.endswith(".rels"):
        for child in list(root):
            target = str(child.attrib.get("Target", "")).rsplit("/", 1)[-1].casefold()
            relationship_type = str(child.attrib.get("Type", "")).casefold()
            if target in {"comments.xml", "commentsextended.xml", "commentsextensible.xml", "commentsids.xml", "people.xml"} or "comments" in relationship_type or relationship_type.endswith("/people"):
                root.remove(child); changed = True
    else:
        for parent in list(root.iter()):
            for child in list(parent):
                local = _local_name(child)
                if local == "trackRevisions" or local in _REVISION_ELEMENTS:
                    parent.remove(child); changed = True
                elif local in _ACCEPTED_REVISION_ELEMENTS:
                    index = list(parent).index(child)
                    for accepted_child in list(child):
                        parent.insert(index, accepted_child); index += 1
                    parent.remove(child); changed = True
                elif local == "r":
                    properties = next((item for item in list(child) if _local_name(item) == "rPr"), None)
                    if properties is not None and any(_local_name(item) in {"vanish", "webHidden"} for item in properties):
                        parent.remove(child); changed = True
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) if changed else data


def _strip_review_metadata(path: Path) -> None:
    temporary_handle = tempfile.NamedTemporaryFile(prefix=f".{path.stem}-clean-", suffix=".docx", dir=path.parent, delete=False)
    temporary = Path(temporary_handle.name)
    temporary_handle.close()
    try:
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w") as destination:
            for item in source.infolist():
                if item.filename in _REVIEW_PARTS:
                    continue
                data = source.read(item.filename)
                if item.filename.endswith((".xml", ".rels")):
                    data = _clean_review_xml(item.filename, data)
                destination.writestr(item, data)
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _is_icf_heading(paragraph: Paragraph) -> bool:
    text = re.sub(r"\s+", " ", paragraph.text).strip()
    if not text or text in {"AND", "OR", "YES", "NO", "N/A"} or "{" in text or len(text) > 140:
        return False
    letters = "".join(character for character in text if character.isalpha())
    return bool(letters) and letters == letters.upper() and len(text.split()) <= 16


def _normalize_icf_heading_styles(document: Document, *, sterling: bool = False) -> None:
    try:
        heading_style = document.styles["Heading ICF Section"]
    except KeyError:
        heading_style = document.styles.add_style("Heading ICF Section", WD_STYLE_TYPE.PARAGRAPH)
        heading_style.base_style = document.styles["Normal"]
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), "0")
        heading_style.element.get_or_add_pPr().append(outline)
    for index, paragraph in enumerate(document.paragraphs):
        if _is_icf_heading(paragraph):
            paragraph.style = heading_style
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
            paragraph.paragraph_format.right_indent = Inches(0)
            paragraph.paragraph_format.keep_with_next = True
            paragraph.paragraph_format.keep_together = True
            if sterling and index and document.paragraphs[index - 1].text.strip():
                paragraph.paragraph_format.space_before = Pt(6)
            following = paragraph._p.getnext()
            while following is not None and following.tag == qn("w:p"):
                spacer = Paragraph(following, document)
                if spacer.text.strip() or any(token in spacer._p.xml for token in ("<w:br", "<w:sectPr", "<w:pBdr")):
                    break
                spacer.paragraph_format.keep_with_next = True
                spacer.paragraph_format.keep_together = True
                following = following.getnext()


def _icf_blocks(model: Mapping[str, Any], section_id: str) -> list[tuple[str, bool]]:
    draft = model.get("icf", {}).get(section_id, {})
    blocks: list[tuple[str, bool]] = []
    for paragraph in draft.get("paragraphs", []):
        if isinstance(paragraph, Mapping):
            blocks.extend((part.strip(), False) for part in str(paragraph.get("text") or "").split("\n\n") if part.strip())
    for group in draft.get("lists", []):
        if isinstance(group, Mapping):
            blocks.extend((item, True) for item in _list(group.get("items")))
    return blocks


def _copy_paragraph_design(paragraph: Paragraph, exemplar: Paragraph | None) -> None:
    if exemplar is None:
        return
    paragraph.style = exemplar.style
    if exemplar._p.pPr is not None:
        copied = copy.deepcopy(exemplar._p.pPr)
        existing = paragraph._p.pPr
        if existing is None:
            paragraph._p.insert(0, copied)
        else:
            paragraph._p.replace(existing, copied)


def _first_visible_run(paragraph: Paragraph | None):
    if paragraph is None:
        return None
    return next((run for run in paragraph.runs if run.text.strip()), None)


def _copy_run_design(run, exemplar) -> None:
    if exemplar is None or exemplar._r.rPr is None:
        return
    existing = run._r.rPr
    copied = copy.deepcopy(exemplar._r.rPr)
    if existing is None:
        run._r.insert(0, copied)
    else:
        run._r.replace(existing, copied)


def _apply_authority_styles(document: Document, authority: Document) -> None:
    """Transplant the client's document defaults and named styles without replacing content."""
    target = document.styles.element
    source = authority.styles.element
    source_defaults = source.find(qn("w:docDefaults"))
    target_defaults = target.find(qn("w:docDefaults"))
    if source_defaults is not None:
        copied_defaults = copy.deepcopy(source_defaults)
        if target_defaults is None:
            target.insert(0, copied_defaults)
        else:
            target.replace(target_defaults, copied_defaults)

    target_styles = {
        style.get(qn("w:styleId")): style
        for style in target.findall(qn("w:style"))
    }
    for source_style in source.findall(qn("w:style")):
        style_id = source_style.get(qn("w:styleId"))
        copied_style = copy.deepcopy(source_style)
        if style_id in target_styles:
            target.replace(target_styles[style_id], copied_style)
        else:
            target.append(copied_style)


def _protocol_generic_body_exemplar(authority: Document) -> Paragraph | None:
    paragraphs = authority.paragraphs
    heading_index = next((
        index for index, paragraph in enumerate(paragraphs)
        if _heading_level(paragraph) == 2
        and _protocol_title_key(paragraph.text) == "informed consent / subject enrollment"
    ), None)
    if heading_index is not None:
        return next((
            paragraph for paragraph in paragraphs[heading_index + 1:]
            if paragraph.text.strip() and _heading_level(paragraph) is None
        ), None)
    return next((
        paragraph for paragraph in paragraphs
        if _heading_level(paragraph) is None and paragraph.text.strip() and paragraph.style.style_id == "Normal"
        and paragraph.paragraph_format.alignment in (None, WD_ALIGN_PARAGRAPH.LEFT)
    ), None)


def _protocol_body_exemplars(authority: Document, heading: Paragraph) -> list[Paragraph]:
    title_key = _protocol_title_key(heading.text)
    heading_level = _heading_level(heading)
    paragraphs = authority.paragraphs
    heading_index = next((
        index for index, paragraph in enumerate(paragraphs)
        if _heading_level(paragraph) == heading_level and _protocol_title_key(paragraph.text) == title_key
    ), None)
    if heading_index is not None:
        exemplars: list[Paragraph] = []
        for paragraph in paragraphs[heading_index + 1:]:
            if _heading_level(paragraph) is not None:
                break
            if paragraph.text.strip():
                exemplars.append(paragraph)
        if exemplars:
            first = exemplars[0].text.strip().casefold()
            if not first.startswith(("table ", "figure ")):
                return exemplars
    fallback = _protocol_generic_body_exemplar(authority)
    return [fallback] if fallback is not None else []


def _protocol_body_exemplar(authority: Document, heading: Paragraph) -> Paragraph | None:
    exemplars = _protocol_body_exemplars(authority, heading)
    return exemplars[0] if exemplars else None


def _apply_protocol_authority_layout(document: Document, authority: Document) -> None:
    authority_headings: dict[tuple[int, str], Paragraph] = {}
    fallback: dict[int, Paragraph] = {}
    for paragraph in authority.paragraphs:
        level = _heading_level(paragraph)
        if level is None:
            continue
        authority_headings[(level, _protocol_title_key(paragraph.text))] = paragraph
        fallback.setdefault(level, paragraph)
    for paragraph in document.paragraphs:
        level = _heading_level(paragraph)
        if level is None:
            continue
        exemplar = authority_headings.get((level, _protocol_title_key(paragraph.text))) or fallback.get(level)
        if exemplar is None:
            continue
        _copy_paragraph_design(paragraph, exemplar)
        source_run = _first_visible_run(exemplar)
        for run in paragraph.runs:
            _copy_run_design(run, source_run)


def _replace_protocol_signature_table(document: Document, authority: Document) -> None:
    """Retain the client signing layout and populate its approved identifiers."""
    output_table = next((
        table for table in document.tables
        if any("Signature of Investigator" in cell.text for row in table.rows for cell in row.cells)
    ), None)
    authority_table = next((
        table for table in authority.tables
        if any("Signature of Investigator" in cell.text for row in table.rows for cell in row.cells)
    ), None)
    if output_table is None or authority_table is None:
        return
    output_table._tbl.getparent().replace(output_table._tbl, copy.deepcopy(authority_table._tbl))
    populated = next(
        (
            table for table in document.tables
            if any("Signature of Investigator" in cell.text for row in table.rows for cell in row.cells)
        ),
        None,
    )
    if populated is None:
        return
def _populate_protocol_signature_values(document: Document, reference: Mapping[str, Any]) -> None:
    table = next(
        (
            table for table in document.tables
            if any("Signature of Investigator" in cell.text for row in table.rows for cell in row.cells)
        ),
        None,
    )
    if table is None:
        return
    site = _first_site(reference)
    investigator = get_path(reference, "parties.principal_investigator", {}) or {}
    if not isinstance(investigator, Mapping) or not _text(investigator.get("name")):
        site_investigators = site.get("investigators") if isinstance(site.get("investigators"), list) else []
        investigator = site_investigators[0] if site_investigators and isinstance(site_investigators[0], Mapping) else {}
    facility = site.get("facility") if isinstance(site.get("facility"), Mapping) else {}
    address = facility.get("address")
    city = _text(address.get("city") if isinstance(address, Mapping) else facility.get("city"))
    values = {
        "Investigator Name (print or type)": _text(investigator.get("name")),
        "Investigator’s Title": _text(investigator.get("role") or investigator.get("title") or investigator.get("degrees") or investigator.get("degree")),
        "Name of Facility": _text(facility.get("name")),
        "Location of Facility (City)": city,
    }
    rows = list(table.rows)
    for row_index, row in enumerate(rows):
        for index, cell in enumerate(row.cells):
            label = re.sub(r"\s+", " ", cell.text).strip()
            for expected, value in values.items():
                if not label.startswith(expected):
                    continue
                if index + 1 < len(row.cells):
                    row.cells[index + 1].text = value
                elif row_index + 1 < len(rows):
                    rows[row_index + 1].cells[0].text = value
                else:
                    cell.text = f"{cell.text}\n{value}" if value else cell.text
                break


def _normalize_protocol_running_header(document: Document) -> None:
    """Keep the compact client page control together on one rendered line."""
    for section in document.sections:
        for table in section.header.tables:
            for row in table.rows:
                for cell in row.cells:
                    if "PAGE" not in cell._tc.xml or "NUMPAGES" not in cell._tc.xml:
                        continue
                    properties = cell._tc.get_or_add_tcPr()
                    if properties.find(qn("w:noWrap")) is None:
                        properties.append(OxmlElement("w:noWrap"))


def _ensure_protocol_references(document: Document, authority: Document, reference: Mapping[str, Any]) -> None:
    """Render supplied citations without leaving an orphaned empty heading."""
    references = _text(reference.get("references"))
    heading = next((paragraph for paragraph in document.paragraphs if paragraph.text.strip() == "REFERENCES"), None)
    if not references:
        if heading is not None:
            heading._element.getparent().remove(heading._element)
        return
    if heading is None:
        heading = document.add_paragraph()
    _set_paragraph_text(heading, "REFERENCES")
    authority_heading = next((paragraph for paragraph in authority.paragraphs if paragraph.text.strip() == "REFERENCES"), None)
    if authority_heading is not None:
        _copy_paragraph_design(heading, authority_heading)
        source_run = _first_visible_run(authority_heading)
        for run in heading.runs:
            _copy_run_design(run, source_run)
    else:
        heading.style = document.styles["Heading 1"]

    paragraphs = document.paragraphs
    heading_index = next(index for index, paragraph in enumerate(paragraphs) if paragraph._p is heading._p)
    body = next((
        paragraph for paragraph in paragraphs[heading_index + 1:]
        if paragraph.text.strip() and _heading_level(paragraph) is None
    ), None)
    if body is None:
        body = document.add_paragraph()
    _set_paragraph_text(body, references)
    exemplar = _protocol_generic_body_exemplar(authority)
    _copy_paragraph_design(body, exemplar)
    source_run = _first_visible_run(exemplar)
    for run in body.runs:
        _copy_run_design(run, source_run)


def _plain_blank(paragraph: Paragraph) -> bool:
    return not paragraph.text.strip() and not any(
        marker in paragraph._p.xml for marker in ("<w:br", "<w:sectPr", "<w:pBdr", "<w:tab")
    )


def _section_paragraphs(document: Document, heading: Paragraph, heading_keys: set[str]) -> list[Paragraph]:
    paragraphs = document.paragraphs
    start = next(index for index, paragraph in enumerate(paragraphs) if paragraph._p is heading._p)
    end = next((
        index for index in range(start + 1, len(paragraphs))
        if _icf_heading_key(paragraphs[index].text) in heading_keys
    ), len(paragraphs))
    return paragraphs[start + 1:end]


def _replace_edge_spacers(
    document: Document,
    heading: Paragraph,
    section: list[Paragraph],
    source_prefix: list[Paragraph],
    source_suffix: list[Paragraph],
) -> None:
    leading: list[Paragraph] = []
    for paragraph in section:
        if not _plain_blank(paragraph):
            break
        leading.append(paragraph)
    for paragraph in leading:
        paragraph._element.getparent().remove(paragraph._element)
    anchor = heading._p
    for exemplar in source_prefix:
        spacer = document.add_paragraph()
        _copy_paragraph_design(spacer, exemplar)
        anchor.addnext(spacer._p)
        anchor = spacer._p

    section_now = _section_paragraphs(
        document,
        heading,
        _ADVARRA_ICF_HEADING_KEYS | _STERLING_ICF_HEADING_KEYS,
    )
    trailing: list[Paragraph] = []
    for paragraph in reversed(section_now):
        if not _plain_blank(paragraph):
            break
        trailing.insert(0, paragraph)
    for paragraph in trailing:
        paragraph._element.getparent().remove(paragraph._element)
    section_now = _section_paragraphs(
        document,
        heading,
        _ADVARRA_ICF_HEADING_KEYS | _STERLING_ICF_HEADING_KEYS,
    )
    anchor = section_now[-1]._p if section_now else heading._p
    for exemplar in source_suffix:
        spacer = document.add_paragraph()
        _copy_paragraph_design(spacer, exemplar)
        anchor.addnext(spacer._p)
        anchor = spacer._p


def _apply_icf_authority_layout(
    document: Document,
    authority: Document,
    model: Mapping[str, Any],
    *,
    sterling: bool,
) -> None:
    headings = _STERLING_ICF_HEADINGS if sterling else _ADVARRA_ICF_HEADINGS
    retained = _STERLING_RETAINED_HEADINGS if sterling else _ADVARRA_RETAINED_HEADINGS
    heading_keys = {_icf_heading_key(value) for value in set(headings.values()) | retained}
    authority_by_key = {
        _icf_heading_key(paragraph.text): paragraph
        for paragraph in authority.paragraphs
        if _icf_heading_key(paragraph.text) in heading_keys
    }
    for output_heading in document.paragraphs:
        source_heading = authority_by_key.get(_icf_heading_key(output_heading.text))
        if source_heading is None:
            continue
        _copy_paragraph_design(output_heading, source_heading)
        source_heading_run = _first_visible_run(source_heading)
        for run in output_heading.runs:
            _copy_run_design(run, source_heading_run)
    for section_id, title in headings.items():
        blocks = _icf_blocks(model, section_id)
        key = _icf_heading_key(title)
        if not blocks or key not in authority_by_key:
            continue
        output_heading = next((paragraph for paragraph in document.paragraphs if _icf_heading_key(paragraph.text) == key), None)
        source_heading = authority_by_key[key]
        if output_heading is None:
            continue
        source_section = _section_paragraphs(authority, source_heading, heading_keys)
        source_prefix: list[Paragraph] = []
        for paragraph in source_section:
            if not _plain_blank(paragraph):
                break
            source_prefix.append(paragraph)
        source_suffix: list[Paragraph] = []
        for paragraph in reversed(source_section):
            if not _plain_blank(paragraph):
                break
            source_suffix.insert(0, paragraph)
        source_body = next((paragraph for paragraph in source_section if paragraph.text.strip()), None)
        if source_body is not None:
            source_run = _first_visible_run(source_body)
            generated_texts = [text for text, _is_list in blocks]
            for paragraph in _section_paragraphs(document, output_heading, heading_keys):
                if not any(text in paragraph.text for text in generated_texts):
                    continue
                numbering = None if paragraph._p.pPr is None else paragraph._p.pPr.find(qn("w:numPr"))
                numbering = None if numbering is None else copy.deepcopy(numbering)
                _copy_paragraph_design(paragraph, source_body)
                if numbering is not None:
                    paragraph._p.get_or_add_pPr().append(numbering)
                paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
                paragraph.paragraph_format.right_indent = Inches(0)
                for run in paragraph.runs:
                    _copy_run_design(run, source_run)
        _replace_edge_spacers(
            document,
            output_heading,
            _section_paragraphs(document, output_heading, heading_keys),
            source_prefix,
            source_suffix,
        )


def _insert_icf_blocks(document: Document, anchor, blocks: list[tuple[str, bool]], exemplar: Paragraph | None) -> None:
    for text, is_list in blocks:
        paragraph = document.add_paragraph()
        _copy_paragraph_design(paragraph, exemplar)
        run = paragraph.add_run(text)
        source_run = next((item for item in (exemplar.runs if exemplar is not None else []) if item.text.strip()), None)
        if source_run is not None and source_run._r.rPr is not None:
            run._r.insert(0, copy.deepcopy(source_run._r.rPr))
        if is_list:
            _apply_bullet_numbering(document, paragraph)
        else:
            paragraph.paragraph_format.left_indent = Inches(0)
            paragraph.paragraph_format.first_line_indent = Inches(0)
        paragraph.paragraph_format.right_indent = Inches(0)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        anchor.addnext(paragraph._p)
        anchor = paragraph._p


def _icf_section_elements(document: Document, heading: Paragraph, heading_texts: set[str]) -> tuple[list[Any], Paragraph | None]:
    parent = heading._p.getparent()
    siblings = list(parent)
    start = siblings.index(heading._p)
    elements: list[Any] = []
    exemplar = None
    for element in siblings[start + 1:]:
        if element.tag == qn("w:sectPr"):
            break
        if element.tag == qn("w:p"):
            paragraph = Paragraph(element, document)
            if _icf_heading_key(paragraph.text) in heading_texts:
                break
            if exemplar is None and paragraph.text.strip():
                exemplar = paragraph
        elements.append(element)
    return elements, exemplar


def _populate_icf_sections(document: Document, model: Mapping[str, Any], *, sterling: bool) -> None:
    """Keep the client shell while ensuring every accepted ICF section is visible."""
    headings = _STERLING_ICF_HEADINGS if sterling else _ADVARRA_ICF_HEADINGS
    retained_headings = _STERLING_RETAINED_HEADINGS if sterling else _ADVARRA_RETAINED_HEADINGS
    heading_texts = {_icf_heading_key(title) for title in set(headings.values()) | retained_headings}
    paragraphs = list(document.paragraphs)
    heading_by_id = {
        section_id: next((paragraph for paragraph in paragraphs if _icf_heading_key(paragraph.text) == _icf_heading_key(title)), None)
        for section_id, title in headings.items()
    }

    # These sections contain example-study prose in the client authorities.
    # Their accepted source-bound drafts are the body; the heading design is retained.
    source_bound_sections = ("icf.costs", "icf.alternatives", "icf.risks")
    for section_id in source_bound_sections:
        heading = heading_by_id.get(section_id)
        blocks = _icf_blocks(model, section_id)
        if heading is None or not blocks:
            continue
        elements, exemplar = _icf_section_elements(document, heading, heading_texts)
        for element in elements:
            element.getparent().remove(element)
        _insert_icf_blocks(document, heading._p, blocks, exemplar)

    # Privacy and injury retain the client's heading design, but their body is
    # entirely source-bound. The authority documents contain example-study
    # regulators, jurisdictions, payment terms, and cross-border claims.
    for section_id in ("icf.privacy", "icf.injury"):
        blocks = _icf_blocks(model, section_id)
        if not blocks:
            continue
        heading = heading_by_id.get(section_id)
        if heading is None:
            continue
        elements, exemplar = _icf_section_elements(document, heading, heading_texts)
        for element in elements:
            element.getparent().remove(element)
        _insert_icf_blocks(document, heading._p, blocks, exemplar)


def _remove_advarra_example_study_prose(document: Document) -> None:
    """Remove study-specific sample prose while retaining standard client boilerplate."""
    prefixes = (
        "to be in this research study, you cannot already be participating in another medical research study",
        "you will have eye tests and procedures performed",
        "side effects and risks of this study are the same as would be expected after",
        "the following are possible side effects or complications of any",
        "the study doctor is the sponsor for this study and is being paid",
        "you must tell the study doctor or study staff about all side effects",
        "a description of this research study will be available on http://www.clinicaltrials.gov, as required by u.s. law",
    )
    for paragraph in list(document.paragraphs):
        if paragraph.text.strip().casefold().startswith(prefixes):
            paragraph._element.getparent().remove(paragraph._element)


def _normalize_advarra_legal_rights(document: Document, reference: Mapping[str, Any]) -> None:
    """Retain the Advarra Legal Rights shell while carrying supplied injury handling."""
    injury_handling = _text(get_path(reference, "risks_benefits.injury_handling"))
    if not injury_handling:
        return
    heading = next((
        paragraph for paragraph in document.paragraphs
        if _icf_heading_key(paragraph.text) == _icf_heading_key("LEGAL RIGHTS")
    ), None)
    if heading is None:
        return
    heading_texts = {
        _icf_heading_key(title)
        for title in set(_ADVARRA_ICF_HEADINGS.values()) | _ADVARRA_RETAINED_HEADINGS
    }
    elements, exemplar = _icf_section_elements(document, heading, heading_texts)
    if any(
        element.tag == qn("w:p")
        and " ".join(Paragraph(element, document).text.split()) == " ".join(injury_handling.split())
        for element in elements
    ):
        return
    anchor = elements[-1] if elements else heading._p
    _insert_icf_blocks(document, anchor, [(injury_handling, False)], exemplar)


def _normalize_icf_withdrawal(document: Document, boilerplate: Mapping[str, str]) -> None:
    paragraphs = list(document.paragraphs)
    start = next((
        index for index, paragraph in enumerate(paragraphs)
        if paragraph.text.strip().casefold().startswith("your part in this study may be stopped")
    ), None)
    if start is None:
        return
    end = next((
        index for index in range(start + 1, len(paragraphs))
        if paragraphs[index].text.strip().casefold().startswith("check your preference below")
        or paragraphs[index].text.strip().upper() in {"AGREEMENT TO BE IN THE STUDY", "PARTICIPANT STATEMENT AUTHORIZATION"}
    ), len(paragraphs))
    first = paragraphs[start]
    replacement = document.add_paragraph()
    _copy_paragraph_design(replacement, first)
    replacement.add_run(boilerplate["icf-withdrawal"])
    first._p.addprevious(replacement._p)
    for paragraph in paragraphs[start:end]:
        paragraph._element.getparent().remove(paragraph._element)


def _replace_sterling_section_body(document: Document, heading_title: str, blocks: list[tuple[str, bool]]) -> None:
    heading_texts = {
        _icf_heading_key(title)
        for title in set(_STERLING_ICF_HEADINGS.values()) | _STERLING_RETAINED_HEADINGS
    }
    heading = next(
        (paragraph for paragraph in document.paragraphs if _icf_heading_key(paragraph.text) == _icf_heading_key(heading_title)),
        None,
    )
    if heading is None:
        return
    elements, exemplar = _icf_section_elements(document, heading, heading_texts)
    spacer = next(
        (
            element
            for element in elements[:1]
            if element.tag == qn("w:p") and not Paragraph(element, document).text.strip()
        ),
        None,
    )
    for element in elements:
        if element is not spacer:
            element.getparent().remove(element)
    anchor = spacer if spacer is not None else heading._p
    _insert_icf_blocks(document, anchor, blocks, exemplar)


def _replace_icf_section_body(
    document: Document,
    heading_title: str,
    blocks: list[tuple[str, bool]],
    *,
    sterling: bool,
) -> None:
    """Replace a client shell body with approved/source-bound participant text."""
    headings = _STERLING_ICF_HEADINGS if sterling else _ADVARRA_ICF_HEADINGS
    heading_texts = {
        _icf_heading_key(title)
        for title in set(headings.values()) | (_STERLING_RETAINED_HEADINGS if sterling else _ADVARRA_RETAINED_HEADINGS)
    }
    heading = next(
        (paragraph for paragraph in document.paragraphs if _icf_heading_key(paragraph.text) == _icf_heading_key(heading_title)),
        None,
    )
    if heading is None:
        return
    elements, exemplar = _icf_section_elements(document, heading, heading_texts)
    for element in elements:
        element.getparent().remove(element)
    _insert_icf_blocks(document, heading._p, blocks, exemplar)


def _normalize_advarra_contact_sections(document: Document, reference: Mapping[str, Any], boilerplate: Mapping[str, str]) -> None:
    coordinator = get_path(reference, "parties.study_coordinator", {}) or {}
    irb = get_path(reference, "parties.irb", {}) or {}
    coordinator_phone = _text(coordinator.get("business_phone") or coordinator.get("phone"))
    irb_details = ", ".join(filter(None, (_text(irb.get("name")), _text(irb.get("phone")), _text(irb.get("email")))))
    contact = "For questions about this study, contact the study coordinator or study staff"
    contact += f" at {coordinator_phone}." if coordinator_phone else "."
    rights = "For questions about your rights as a research participant, contact"
    rights += f" {irb_details}." if irb_details else " the reviewing institutional review board."
    _replace_icf_section_body(
        document,
        "INTRODUCTION",
        [(boilerplate["icf-introduction"], False)],
        sterling=False,
    )
    _replace_icf_section_body(
        document,
        "WHOM TO CONTACT ABOUT THIS STUDY",
        [(contact, False), (rights, False)],
        sterling=False,
    )
    _replace_icf_section_body(
        document,
        "LEAVING THE STUDY",
        [(boilerplate["icf-withdrawal"], False)],
        sterling=False,
    )


def _normalize_sterling_retained_sections(
    document: Document,
    reference: Mapping[str, Any],
    boilerplate: Mapping[str, str],
) -> None:
    _replace_sterling_section_body(
        document,
        "INFORMATION",
        [(boilerplate["icf-new-findings"], False)],
    )
    _replace_sterling_section_body(
        document,
        "VOLUNTARY PARTICIPATION/WITHDRAWAL",
        [(boilerplate["icf-withdrawal"], False)],
    )
    coordinator = get_path(reference, "parties.study_coordinator", {}) or {}
    investigator = get_path(reference, "parties.principal_investigator", {}) or {}
    irb = get_path(reference, "parties.irb", {}) or {}
    phones = " / ".join(
        filter(None, [_text(coordinator.get("business_phone")), _text(coordinator.get("office_phone"))])
    )
    investigator_name = _text(investigator.get("name"))
    research_contact = "If you have questions, concerns, or complaints about the research study"
    if investigator_name and phones:
        research_contact += f", contact {investigator_name} or the study staff at {phones}."
    elif investigator_name:
        research_contact += f", contact {investigator_name}."
    elif phones:
        research_contact += f", contact the study staff at {phones}."
    else:
        research_contact += ", contact the study staff."
    irb_contact = "If you have questions about your rights as a research participant, contact"
    irb_details = ", ".join(filter(None, [_text(irb.get("name")), _text(irb.get("phone")), _text(irb.get("email"))]))
    irb_contact += f" {irb_details}." if irb_details else " the reviewing institutional review board."
    _replace_sterling_section_body(
        document,
        "QUESTIONS",
        [(research_contact, False), (irb_contact, False)],
    )


def _normalize_icf_front_matter(document: Document, reference: Mapping[str, Any]) -> None:
    if document.tables:
        front = document.tables[0]
        site = _first_site(reference)
        facility = site.get("facility") if isinstance(site.get("facility"), Mapping) else {}
        coordinator = get_path(reference, "parties.study_coordinator", {}) or {}
        replacements = {
            "Telephone:": ("Study Coordinator Telephone:", _text(coordinator.get("business_phone") or coordinator.get("phone"))),
            "Address:": ("Study Site Address:", _address(facility.get("address"))),
        }
        for row in front.rows:
            label = row.cells[0].text.strip()
            if label not in replacements:
                continue
            new_label, value = replacements[label]
            _set_paragraph_text(row.cells[0].paragraphs[0], new_label)
            _set_paragraph_text(row.cells[1].paragraphs[0], value)


def _complex_field_runs(field_name: str, source_run) -> list[Any]:
    """Build a Word field while retaining the legacy footer run's typography."""
    properties = source_run.find(qn("w:rPr"))

    def field_run(child) -> Any:
        run = OxmlElement("w:r")
        if properties is not None:
            run.append(copy.deepcopy(properties))
        run.append(child)
        return run

    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = f" {field_name} \\* arabic \\* MERGEFORMAT "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    cached = OxmlElement("w:t")
    cached.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    return [field_run(child) for child in (begin, instruction, separate, cached, end)]


def _repair_sterling_footer_page_fields(document: Document) -> None:
    """Replace Sterling's non-field pgNum marker with real PAGE fields in every footer part."""
    seen: set[int] = set()
    for section in document.sections:
        reference_types = {
            reference.get(qn("w:type"))
            for reference in section._sectPr.findall(qn("w:footerReference"))
        }
        footers = []
        if "default" in reference_types:
            footers.append(section.footer)
        if "even" in reference_types:
            footers.append(section.even_page_footer)
        if "first" in reference_types:
            footers.append(section.first_page_footer)
        for footer in footers:
            if id(footer._element) in seen:
                continue
            seen.add(id(footer._element))
            for paragraph in footer.paragraphs:
                for run in list(paragraph._p.findall(qn("w:r"))):
                    if run.find(qn("w:pgNum")) is None:
                        continue
                    index = list(paragraph._p).index(run)
                    paragraph._p.remove(run)
                    for offset, replacement in enumerate(_complex_field_runs("PAGE", run)):
                        paragraph._p.insert(index + offset, replacement)


def _compact_icf_signature_end(document: Document) -> None:
    """Avoid a client-template spacer forcing the final copy statement onto an otherwise blank page."""
    agreement = next((
        paragraph for paragraph in document.paragraphs
        if _icf_heading_key(paragraph.text) in {
            _icf_heading_key("AGREEMENT TO BE IN THE STUDY"),
            _icf_heading_key("PARTICIPANT STATEMENT AUTHORIZATION"),
        }
    ), None)
    if agreement is not None:
        for line_break in agreement._p.iter(qn("w:br")):
            if line_break.get(qn("w:type")) in {"column", "page"}:
                line_break.getparent().remove(line_break)
        agreement.paragraph_format.page_break_before = None
        removed = 0
        previous = agreement._p.getprevious()
        while previous is not None and removed < 2 and previous.tag == qn("w:p"):
            paragraph = Paragraph(previous, document)
            if paragraph.text.strip() or any(token in paragraph._p.xml for token in ("<w:tab", "<w:pBdr", "<w:sectPr", "<w:br")):
                break
            before = previous.getprevious()
            previous.getparent().remove(previous)
            previous = before
            removed += 1
        if _icf_heading_key(agreement.text) == _icf_heading_key("PARTICIPANT STATEMENT AUTHORIZATION"):
            paragraphs = list(document.paragraphs)
            signature_index = next(index for index, paragraph in enumerate(paragraphs) if paragraph._p is agreement._p)
            questions = next((
                paragraph for paragraph in paragraphs[:signature_index]
                if _icf_heading_key(paragraph.text) == _icf_heading_key("QUESTIONS")
            ), None)
            if questions is not None:
                # Generated content can end exactly at a page boundary. A
                # forced break here would then create a textless page.
                questions.paragraph_format.page_break_before = None
            signature_tail = paragraphs[signature_index:]
            for paragraph in signature_tail:
                paragraph.paragraph_format.keep_together = True
            for paragraph in signature_tail[:-1]:
                paragraph.paragraph_format.keep_with_next = True
    final = next((
        paragraph for paragraph in document.paragraphs
        if paragraph.text.strip().casefold() == "you will be given a signed and dated copy of this informed consent document to keep."
    ), None)
    if final is None:
        return
    final.paragraph_format.space_before = Pt(0)
    final.paragraph_format.space_after = Pt(0)
    no_sign = next((
        paragraph for paragraph in document.paragraphs
        if paragraph.text.strip().casefold().startswith("if you do not agree with the statement above")
    ), None)
    if no_sign is not None:
        element = no_sign._p.getnext()
        while element is not None and element is not final._p:
            following = element.getnext()
            if element.tag == qn("w:p"):
                paragraph = Paragraph(element, document)
                if not paragraph.text.strip() and "<w:tab" not in paragraph._p.xml:
                    element.getparent().remove(element)
                    break
            element = following
    previous = final._p.getprevious()
    if previous is not None and previous.tag == qn("w:p") and not "".join(previous.itertext()).strip():
        previous.getparent().remove(previous)
    paragraphs = list(document.paragraphs)
    no_sign_index = next((
        index for index, paragraph in enumerate(paragraphs)
        if paragraph.text.strip().casefold().startswith("if you do not agree with the statement above")
    ), None)
    final_index = next((index for index, paragraph in enumerate(paragraphs) if paragraph._p is final._p), None)
    if no_sign_index is not None and final_index is not None:
        for paragraph in paragraphs[no_sign_index:final_index]:
            paragraph.paragraph_format.keep_with_next = True
            paragraph.paragraph_format.keep_together = True


def _normalize_icf_preferences(document: Document) -> None:
    preference_paragraphs: list[Paragraph] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text.startswith(("Yes, inform my primary care physician", "No, do not inform my primary care physician")):
            continue
        paragraph.text = f"☐ {text}"
        properties = paragraph._p.get_or_add_pPr()
        numbering = properties.find(qn("w:numPr"))
        if numbering is not None:
            properties.remove(numbering)
        paragraph.paragraph_format.left_indent = Inches(0.35)
        paragraph.paragraph_format.first_line_indent = Inches(-0.2)
        preference_paragraphs.append(paragraph)
    heading = next((
        paragraph for paragraph in document.paragraphs
        if paragraph.text.strip().casefold().startswith("check your preference below")
    ), None)
    paragraphs = list(document.paragraphs)
    if heading is not None and preference_paragraphs:
        start = next(index for index, paragraph in enumerate(paragraphs) if paragraph._p is heading._p)
        end = next(index for index, paragraph in enumerate(paragraphs) if paragraph._p is preference_paragraphs[-1]._p)
        block = paragraphs[start:end + 1]
    else:
        block = ([heading] if heading is not None else []) + preference_paragraphs
    for paragraph in block:
        paragraph.paragraph_format.keep_together = True
    for paragraph in block[:-1]:
        paragraph.paragraph_format.keep_with_next = True


def _replace_static_toc(document: Document) -> None:
    paragraphs = list(document.paragraphs)
    start = next((i for i, p in enumerate(paragraphs) if p.text.strip().startswith("1. TITLE PAGE") and "..." in p.text), None)
    body = next((i for i, p in enumerate(paragraphs) if i > (start or 0) and p.style.name.casefold().startswith("heading") and p.text.strip().startswith(("4. INTRODUCTION", "5. INTRODUCTION"))), None)
    if start is None or body is None: return
    anchor = paragraphs[start]
    field_paragraph = document.add_paragraph()
    run = field_paragraph.add_run(); begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText"); instruction.set(qn("xml:space"), "preserve"); instruction.text = ' TOC \\o "1-2" \\h \\z \\u '
    separate = OxmlElement("w:fldChar"); separate.set(qn("w:fldCharType"), "separate")
    placeholder = OxmlElement("w:t"); placeholder.text = ""
    end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
    for node in (begin, instruction, separate, placeholder, end): run._r.append(node)
    anchor._p.addprevious(field_paragraph._p)
    preserve_from = body
    for index in range(body - 1, start - 1, -1):
        paragraph = paragraphs[index]
        if paragraph.text.strip():
            break
        properties = paragraph._p.find(qn("w:pPr"))
        section = None if properties is None else properties.find(qn("w:sectPr"))
        section_type = None if section is None else section.find(qn("w:type"))
        if (
            paragraph._p.xpath('.//w:br[@w:type="page"]')
            or section is not None
            and (section_type is None or section_type.get(qn("w:val")) != "continuous")
        ):
            preserve_from = index
    for paragraph in paragraphs[start:preserve_from]:
        paragraph._element.getparent().remove(paragraph._element)


def _visit_rows(document: Document, reference: Mapping[str, Any]) -> None:
    rows = get_path(reference, "procedures.visit_schedule_table", []) or get_path(reference, "procedures.visit_schedule", []) or []
    if not rows:
        rows = [{"visitName": item} for item in _list(get_path(reference, "procedures.assessments", []))]
    if not isinstance(rows, list) or not rows:
        return
    for table in document.tables:
        template_index = next((i for i, row in enumerate(table.rows) if any("{AI_visit" in cell.text or "{visitsTable}" in cell.text for cell in row.cells)), None)
        if template_index is None:
            continue
        template = table.rows[template_index]._tr
        table._tbl.remove(template)
        rendered_rows: list[tuple[str, str, str, str]] = []
        for index, item in enumerate(rows, 1):
            table._tbl.append(copy.deepcopy(template))
            record = item if isinstance(item, Mapping) else {"visitName": item}
            values = (
                _text(record.get("visitNumber")) or str(index),
                _text(record.get("visitName") or record.get("visit")),
                _text(record.get("visitWindow") or record.get("timing")),
                _text(record.get("CRFnumber")),
            )
            rendered_rows.append(values)
            for cell, value in zip(table.rows[-1].cells, values):
                cell.text = value
        if rendered_rows and not any(values[3] for values in rendered_rows):
            for row in table._tbl.tr_lst:
                cells = row.tc_lst
                if len(cells) > 3:
                    row.remove(cells[3])
            grid_columns = table._tbl.tblGrid.gridCol_lst
            if len(grid_columns) > 3:
                table._tbl.tblGrid.remove(grid_columns[3])


def _apply_protocol_visit_table_layout(document: Document, authority: Document) -> None:
    """Apply the client's compact three-column Visit Schedule table pattern."""
    output = next((
        table for table in document.tables
        if len(table.columns) == 3 and len(table.rows[0].cells) == 3
        and "Visit Name" in table.rows[0].cells[1].text
    ), None)
    source = next((
        table for table in authority.tables
        if len(table.columns) == 3 and table.rows[0].cells[0].text.strip() == "Visit Number"
    ), None)
    if output is None or source is None:
        return
    output._tbl.replace(output._tbl.tblPr, copy.deepcopy(source._tbl.tblPr))
    output._tbl.replace(output._tbl.tblGrid, copy.deepcopy(source._tbl.tblGrid))
    for row_index, row in enumerate(output.rows):
        # The client pattern rules the heading and the first data boundary,
        # then leaves later visit rows open. Reusing row 1 for every visit
        # introduced horizontal separators that are absent from the authority.
        source_row = source.rows[min(row_index, 2)]
        source_properties = source_row._tr.trPr
        target_properties = row._tr.trPr
        if source_properties is not None:
            copied = copy.deepcopy(source_properties)
            if target_properties is None:
                row._tr.insert(0, copied)
            else:
                row._tr.replace(target_properties, copied)
        for cell_index, cell in enumerate(row.cells):
            text = source_row.cells[cell_index].text if row_index == 0 else cell.text
            _copy_cell_design(cell, source_row.cells[cell_index], text)
    caption = next(
        (paragraph for paragraph in document.paragraphs if paragraph.text.strip().startswith("Table 9.2-1")),
        None,
    )
    if caption is not None:
        caption.paragraph_format.keep_with_next = True
        caption.paragraph_format.keep_together = True


def _normalize_protocol_contact_table(document: Document) -> None:
    table = next((
        table for table in document.tables
        if table.rows and any(
            "business" in re.sub(r"\s+", " ", cell.text).casefold()
            and "phone" in re.sub(r"\s+", " ", cell.text).casefold()
            for cell in table.rows[0].cells
        )
    ), None)
    if table is None:
        return
    headers = [re.sub(r"\s+", " ", cell.text).strip().casefold() for cell in table.rows[0].cells]
    if len(headers) == 4:
        widths = [Inches(1.30), Inches(1.15), Inches(2.50), Inches(1.15)]
        for column, width in zip(table._tbl.tblGrid.gridCol_lst, widths):
            column.w = width
        for row in table.rows:
            for cell, width in zip(row.cells, widths):
                cell.width = width
    phone_columns = [index for index, header in enumerate(headers) if "phone" in header]
    email_columns = [index for index, header in enumerate(headers) if "email" in header or "e-mail" in header]
    if len(headers) >= 4:
        phone_columns = sorted(set(phone_columns) | {1, 3})
    for row in table.rows[1:]:
        for index in sorted(set(phone_columns + email_columns)):
            if index >= len(row.cells):
                continue
            cell = row.cells[index]
            properties = cell._tc.get_or_add_tcPr()
            if properties.find(qn("w:noWrap")) is None:
                properties.append(OxmlElement("w:noWrap"))
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(9 if index in email_columns else 10)


def _procedure_items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for value_item in value if (item := _text(value_item))]
    return [item.strip() for item in re.split(r"[;\n]", _text(value)) if item.strip()]


def _copy_cell_design(destination, source, text: str, *, compact: bool = False) -> None:
    destination_properties = destination._tc.get_or_add_tcPr()
    source_properties = source._tc.tcPr
    if source_properties is not None:
        destination_properties.getparent().replace(destination_properties, copy.deepcopy(source_properties))
    destination_properties = destination._tc.get_or_add_tcPr()
    for tag in ("w:vMerge", "w:hMerge", "w:gridSpan"):
        inherited_merge = destination_properties.find(qn(tag))
        if inherited_merge is not None:
            destination_properties.remove(inherited_merge)
    destination.text = ""
    paragraph = destination.paragraphs[0]
    source_paragraph = source.paragraphs[0]
    if source_paragraph._p.pPr is not None:
        copied = copy.deepcopy(source_paragraph._p.pPr)
        existing = paragraph._p.pPr
        if existing is None:
            paragraph._p.insert(0, copied)
        else:
            paragraph._p.replace(existing, copied)
    run = paragraph.add_run(text)
    source_run = next((item for item in source_paragraph.runs if item.text.strip()), source_paragraph.runs[0] if source_paragraph.runs else None)
    if source_run is not None and source_run._r.rPr is not None:
        run._r.insert(0, copy.deepcopy(source_run._r.rPr))
    if compact:
        run.font.size = Pt(7)
    destination.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def _set_repeat_header(row) -> None:
    properties = row._tr.get_or_add_trPr()
    header = properties.find(qn("w:tblHeader"))
    if header is None:
        header = OxmlElement("w:tblHeader")
        properties.append(header)
    header.set(qn("w:val"), "true")


def _prevent_row_split(row) -> None:
    properties = row._tr.get_or_add_trPr()
    if properties.find(qn("w:cantSplit")) is None:
        properties.append(OxmlElement("w:cantSplit"))


def _normalize_protocol_table_pagination(document: Document) -> None:
    """Keep client table headers and rows intact across rendered pages."""
    visit_caption = next(
        (paragraph for paragraph in document.paragraphs if paragraph.text.strip().startswith("Table 9.2-1")),
        None,
    )
    if visit_caption is not None:
        visit_caption.paragraph_format.keep_with_next = True
        visit_caption.paragraph_format.keep_together = True
    for table in document.tables:
        for row in table.rows:
            _prevent_row_split(row)
        if not table.rows or table.rows[0].cells[0].text.strip() != "Study Staff":
            continue
        _set_repeat_header(table.rows[0])
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.keep_together = True
        for cell in table.rows[0].cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.keep_with_next = True
        for row in table.rows[1:]:
            properties = row._tr.get_or_add_trPr()
            header = properties.find(qn("w:tblHeader"))
            if header is not None:
                properties.remove(header)
        previous = table._tbl.getprevious()
        if previous is not None and previous.tag == qn("w:p"):
            caption_tail = Paragraph(previous, document)
            caption_tail.paragraph_format.keep_with_next = True
            caption_tail.paragraph_format.keep_together = True
            before = previous.getprevious()
            if before is not None and before.tag == qn("w:p"):
                caption_head = Paragraph(before, document)
                if caption_head.text.strip().startswith("Table 13.3.-1"):
                    caption_head.paragraph_format.keep_with_next = True
                    caption_head.paragraph_format.keep_together = True
                    caption_head.paragraph_format.page_break_before = None


def _has_page_boundary_before(paragraph: Paragraph) -> bool:
    if (
        paragraph.paragraph_format.page_break_before is True
        or paragraph.style.paragraph_format.page_break_before is True
    ):
        return True
    previous = paragraph._p.getprevious()
    while previous is not None and previous.tag == qn("w:p"):
        if previous.xpath('.//w:br[@w:type="page"]'):
            return True
        properties = previous.find(qn("w:pPr"))
        section = None if properties is None else properties.find(qn("w:sectPr"))
        if section is not None:
            section_type = section.find(qn("w:type"))
            if section_type is None or section_type.get(qn("w:val")) != "continuous":
                return True
        if Paragraph(previous, paragraph._parent).text.strip():
            break
        previous = previous.getprevious()
    return False


def _normalize_protocol_section_pagination(document: Document) -> None:
    """Preserve template breaks and guarantee only the two TOC boundaries."""
    headings = [
        paragraph for paragraph in document.paragraphs
        if _heading_level(paragraph) is not None
    ]
    toc_index = next((
        index for index, paragraph in enumerate(headings)
        if "table of contents" in _protocol_heading_key(paragraph.text)
    ), None)
    if toc_index is None:
        return
    first_body = next((
        paragraph for paragraph in headings[toc_index + 1:]
        if re.match(r"^\d+(?:\.\d+)*\.?\s+", paragraph.text.strip())
    ), None)
    for boundary in (headings[toc_index], first_body):
        if boundary is not None and not _has_page_boundary_before(boundary):
            boundary.paragraph_format.page_break_before = True


def _protect_protocol_heading_content(document: Document) -> None:
    """Keep each body heading and intervening template spacers with content."""
    blocks = list(document.element.body.iterchildren())
    for index, element in enumerate(blocks):
        if element.tag != qn("w:p"):
            continue
        heading = Paragraph(element, document)
        if _heading_level(heading) is None:
            continue
        heading.paragraph_format.keep_with_next = True
        heading.paragraph_format.keep_together = True
        for following in blocks[index + 1:]:
            if following.tag == qn("w:tbl"):
                break
            if following.tag != qn("w:p"):
                break
            paragraph = Paragraph(following, document)
            if paragraph.text.strip() and _heading_level(paragraph) is None:
                break
            paragraph.paragraph_format.keep_with_next = True
            paragraph.paragraph_format.keep_together = True


def _layout_target_key(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _target_heading(document: Document, target: str, *, protocol: bool) -> Paragraph:
    target_key = _protocol_heading_key(target) if protocol else _layout_target_key(target)
    headings = [
        paragraph
        for paragraph in document.paragraphs
        if _heading_level(paragraph) is not None
        and (
            _protocol_heading_key(paragraph.text) if protocol else _layout_target_key(paragraph.text)
        ) == target_key
    ]
    if len(headings) != 1:
        raise LayoutRepairTargetError(
            f"Layout repair target heading must match exactly once; found {len(headings)}: {target}"
        )
    return headings[0]


def _first_substantive_block(document: Document, heading: Paragraph) -> Paragraph | Table | None:
    element = heading._p.getnext()
    while element is not None and element.tag != qn("w:sectPr"):
        if element.tag == qn("w:tbl"):
            return Table(element, document)
        if element.tag == qn("w:p"):
            paragraph = Paragraph(element, document)
            if _heading_level(paragraph) is not None:
                return None
            if paragraph.text.strip():
                return paragraph
        element = element.getnext()
    return None


def _repair_heading_cohesion(document: Document, target: str, *, protocol: bool) -> None:
    """Strengthen only the heading/content pair named by visual evidence."""
    heading = _target_heading(document, target, protocol=protocol)
    heading.paragraph_format.keep_with_next = True
    heading.paragraph_format.keep_together = True
    heading.paragraph_format.widow_control = True
    block = _first_substantive_block(document, heading)
    if isinstance(block, Paragraph):
        # Widow control preserves a visible first fragment without making a long
        # section indivisible.
        block.paragraph_format.widow_control = True
    elif isinstance(block, Table) and block.rows:
        _prevent_row_split(block.rows[0])
        for cell in block.rows[0].cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.widow_control = True


def _table_caption_paragraphs(document: Document, table: Table) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    previous = table._tbl.getprevious()
    while previous is not None and previous.tag == qn("w:p") and len(paragraphs) < 3:
        paragraph = Paragraph(previous, document)
        if paragraph.text.strip():
            paragraphs.append(paragraph)
        previous = previous.getprevious()
    paragraphs.reverse()
    return paragraphs


def _target_table(document: Document, target: str) -> tuple[Table, Paragraph | None]:
    target_key = _layout_target_key(target).rstrip(".:")
    matches: list[tuple[Table, Paragraph | None]] = []
    for table in document.tables:
        captions = _table_caption_paragraphs(document, table)
        caption = next((
            paragraph for paragraph in captions
            if target_key == _layout_target_key(paragraph.text).rstrip(".:")
        ), None)
        first_row = " ".join(cell.text for cell in table.rows[0].cells) if table.rows else ""
        if caption is not None or target_key == _layout_target_key(first_row).rstrip(".:"):
            matches.append((table, caption))
    if len(matches) != 1:
        raise LayoutRepairTargetError(
            f"Layout repair target table must match exactly once; found {len(matches)}: {target}"
        )
    return matches[0]


def _repair_table_pagination(document: Document, target: str) -> None:
    """Repair only the table identified by a classified rendered finding."""
    table, caption = _target_table(document, target)
    for row in table.rows:
        _prevent_row_split(row)
    if caption is not None:
        caption.paragraph_format.keep_with_next = True
        caption.paragraph_format.keep_together = True
        # A table-specific boundary must never be attached to a numbered body
        # heading; only a separately identified caption may own it.
        if not re.match(r"^\d+(?:\.\d+)*\.?\s+", caption.text.strip()):
            caption.paragraph_format.page_break_before = True


def _assessment_matrix(document: Document, reference: Mapping[str, Any], authority_path: Path) -> None:
    """Populate Table 15.1 only from approved visit/procedure relationships."""
    placeholder = next((paragraph for paragraph in document.paragraphs if "{visitsTable}" in paragraph.text), None)
    if placeholder is None:
        return
    schedule = get_path(reference, "procedures.visit_schedule", []) or []
    visits: list[dict[str, Any]] = []
    if isinstance(schedule, list):
        for index, item in enumerate(schedule, 1):
            if not isinstance(item, Mapping):
                continue
            visits.append({
                "name": _text(item.get("visit") or item.get("visitName")) or f"Visit {index}",
                "timing": _text(item.get("timing") or item.get("visitWindow")),
                "procedures": _procedure_items(item.get("procedures")),
            })
    activities = list(dict.fromkeys(activity for visit in visits for activity in visit["procedures"]))
    matrix_mode = bool(visits and activities)
    if matrix_mode:
        def header_label(visit: Mapping[str, Any]) -> str:
            name, timing = str(visit["name"]), str(visit["timing"])
            if not timing:
                return name
            if re.fullmatch(r"day\s*[+-]?\d+", timing, re.I):
                return f"{name}\n({timing})"
            return timing

        row_values = [
            ["Activity", *[header_label(visit) for visit in visits]],
            ["", *[f"Visit {index}" for index, _visit in enumerate(visits, 1)]],
            *[
                [activity, *["X" if activity in visit["procedures"] else "" for visit in visits]]
                for activity in activities
            ],
        ]
        header_rows = 2
    else:
        entries: list[tuple[str, str]] = []
        schedule_table = get_path(reference, "procedures.visit_schedule_table", []) or []
        if isinstance(schedule_table, list):
            for item in schedule_table:
                if isinstance(item, Mapping):
                    label = _text(item.get("visitName") or item.get("visit"))
                    timing = _text(item.get("visitWindow") or item.get("timing"))
                    if label:
                        entries.append((label, timing))
        if not entries:
            entries = [(item, "") for item in _list(get_path(reference, "procedures.assessments", []))]
        if not entries:
            return
        row_values = [["Approved visit or assessment", "Approved timing"], *[list(item) for item in entries]]
        header_rows = 1

    authority = Document(authority_path)
    design = authority.tables[-1]
    table = document.add_table(rows=len(row_values), cols=len(row_values[0]))
    destination_properties = table._tbl.tblPr
    destination_properties.getparent().replace(destination_properties, copy.deepcopy(design._tbl.tblPr))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    compact = len(row_values[0]) > 6
    for row_index, values in enumerate(row_values):
        source_row_index = min(row_index, len(design.rows) - 1)
        for column_index, value in enumerate(values):
            source_column_index = 0 if column_index == 0 else min(column_index, len(design.columns) - 1)
            _copy_cell_design(
                table.rows[row_index].cells[column_index],
                design.rows[source_row_index].cells[source_column_index],
                value,
                compact=compact or (row_index < header_rows and len(row_values[0]) > 4),
            )
        _prevent_row_split(table.rows[row_index])
        if row_index < header_rows:
            _set_repeat_header(table.rows[row_index])
    if matrix_mode and header_rows == 2:
        table.cell(0, 0).merge(table.cell(1, 0))
        continuation = table._tbl.tr_lst[1].tc_lst[0]
        continuation_properties = continuation.get_or_add_tcPr()
        continuation_borders = continuation_properties.find(qn("w:tcBorders"))
        if continuation_borders is None:
            continuation_borders = OxmlElement("w:tcBorders")
            continuation_properties.append(continuation_borders)
        continuation_top = continuation_borders.find(qn("w:top"))
        if continuation_top is None:
            continuation_top = OxmlElement("w:top")
            continuation_borders.append(continuation_top)
        continuation_top.set(qn("w:val"), "nil")
    available_width = document.sections[0].page_width - document.sections[0].left_margin - document.sections[0].right_margin
    first_width = int(available_width * (0.40 if len(row_values[0]) > 3 else 0.55))
    other_width = int((available_width - first_width) / max(1, len(row_values[0]) - 1))
    for row in table.rows:
        for index, cell in enumerate(row.cells):
            cell.width = first_width if index == 0 else other_width
    for row in table._tbl.tr_lst:
        for index, cell in enumerate(row.tc_lst):
            width = first_width if index == 0 else other_width
            width_twips = round(width / 635)
            properties = cell.get_or_add_tcPr()
            cell_width = properties.find(qn("w:tcW"))
            if cell_width is None:
                cell_width = OxmlElement("w:tcW")
                properties.insert(0, cell_width)
            cell_width.set(qn("w:w"), str(width_twips))
            cell_width.set(qn("w:type"), "dxa")
    for index, grid_column in enumerate(table._tbl.tblGrid.gridCol_lst):
        grid_column.w = first_width if index == 0 else other_width
    for cell in table._tbl.tr_lst[-1].tc_lst:
        properties = cell.get_or_add_tcPr()
        borders = properties.find(qn("w:tcBorders"))
        if borders is None:
            borders = OxmlElement("w:tcBorders")
            properties.append(borders)
        bottom = borders.find(qn("w:bottom"))
        if bottom is None:
            bottom = OxmlElement("w:bottom")
            borders.append(bottom)
        for key, value in (("w:val", "double"), ("w:sz", "6"), ("w:space", "0"), ("w:color", "auto")):
            bottom.set(qn(key), value)
    placeholder._p.addprevious(table._tbl)
    placeholder._element.getparent().remove(placeholder._element)


def _template_document(
    reference: Mapping[str, Any],
    model: Mapping[str, Any],
    template_path: Path,
    *,
    authority_path: Path,
    icf: bool,
    boilerplate: Mapping[str, str],
    layout_repair_rules: Iterable[Mapping[str, str]] = (),
) -> Document:
    """Populate the selected Contracted Template without replacing its Layout Contract."""
    document = Document(template_path)
    sterling = icf and str(get_path(reference, "meta.icf_template", "Advarra")).casefold() == "sterling"
    authority = Document(authority_path)
    _apply_authority_styles(document, authority)
    _apply_authority_bullet_numbering(document, authority)
    fields = render_fields(reference, model)
    _normalize_generated_placeholder_layout(document)
    if not icf:
        _assessment_matrix(document, reference, authority_path)
    _visit_rows(document, reference)
    for paragraph in list(_all_paragraphs(document)):
        _replace_paragraph(paragraph, fields)
    _normalize_typed_bullet_paragraphs(document)
    if icf:
        if sterling:
            _repair_sterling_footer_page_fields(document)
        _populate_icf_sections(document, model, sterling=sterling)
        if not sterling:
            _remove_advarra_example_study_prose(document)
        if sterling:
            _normalize_sterling_retained_sections(document, reference, boilerplate)
        else:
            _normalize_icf_withdrawal(document, boilerplate)
            _normalize_advarra_contact_sections(document, reference, boilerplate)
        _normalize_icf_front_matter(document, reference)
        _normalize_source_bound_shell(document, reference, icf=True)
        if not sterling:
            _normalize_advarra_legal_rights(document, reference)
        _apply_icf_authority_layout(document, authority, model, sterling=sterling)
        _normalize_icf_preferences(document)
        _compact_icf_signature_end(document)
        _normalize_icf_heading_styles(document, sterling=sterling)
    else:
        branch = canonical_study_type(get_path(reference, "meta.study_type")) or ""
        _normalize_source_bound_shell(document, reference, icf=False)
        _replace_protocol_investigator_agreement(document, boilerplate, branch, authority)
        _replace_protocol_signature_table(document, authority)
        _populate_protocol_signature_values(document, reference)
        _normalize_protocol_running_header(document)
        _apply_protocol_visit_table_layout(document, authority)
        _ensure_contract_headings(document, branch)
        _normalize_protocol_container_introductions(document, branch, boilerplate)
        _replace_protocol_leaf_bodies(document, model, branch, authority)
        _normalize_protocol_title_controls(document, reference)
        _normalize_protocol_summary_table(document)
        _ensure_protocol_references(document, authority, reference)
        _split_heading_content(document)
        _replace_static_toc(document)
        _apply_protocol_authority_layout(document, authority)
        _normalize_protocol_section_pagination(document)
        _normalize_protocol_contact_table(document)
        _normalize_protocol_table_pagination(document)
        _protect_protocol_heading_content(document)
    for repair in layout_repair_rules:
        rule = repair["rule"]
        target = repair["target"]
        if rule == "heading_cohesion":
            _repair_heading_cohesion(document, target, protocol=not icf)
        elif rule == "table_pagination":
            _repair_table_pagination(document, target)
    _set_update_fields(document)
    return document


def _set_update_fields(document: Document) -> None:
    settings = document.settings.element
    element = settings.find(qn("w:updateFields"))
    if element is None:
        element = OxmlElement("w:updateFields")
        settings.append(element)
    element.set(qn("w:val"), "true")


def _cell(cell, value: Any, *, bold: bool = False) -> None:
    cell.text = ""; paragraph = cell.paragraphs[0]; run = paragraph.add_run(_text(value)); run.bold = bold
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def _boilerplate(repo_root: Path, bundle: Mapping[str, Any]) -> dict[str, str]:
    relative = str(bundle["fixed_clinical_boilerplate"]["path"])
    payload = json.loads((repo_root / relative).read_text(encoding="utf-8"))
    if payload.get("version") != BOILERPLATE_VERSION or not isinstance(payload.get("sections"), dict):
        raise ValueError("Fixed Clinical Boilerplate does not match the rendering contract.")
    return {str(key): str(value) for key, value in payload["sections"].items()}


def refresh_toc_from_pdf(docx_path: Path, pdf_path: Path) -> bool:
    """Populate the Word TOC cache from current rendered-page evidence."""
    document = Document(docx_path)
    pages = []
    for page in PdfReader(pdf_path).pages:
        try:
            extracted = page.extract_text(extraction_mode="layout")
        except TypeError:  # Compatibility with older pypdf releases.
            try:
                extracted = page.extract_text()
            except KeyError:  # A valid blank page may have no /Contents object.
                extracted = ""
        except KeyError:  # A valid blank page may have no /Contents object.
            extracted = ""
        pages.append(re.sub(r"\s+", " ", extracted or "").casefold())
    headings = [(paragraph.text.strip(), paragraph.style.name) for paragraph in document.paragraphs if paragraph.text.strip() and paragraph.style.name in {"Heading 1", "Heading 2"}]
    toc_heading = next((heading for heading, _style in headings if "TABLE OF CONTENTS" in heading.upper()), "")
    if not toc_heading:
        return False
    toc_matches = [index for index, page in enumerate(pages, 1) if re.sub(r"\s+", " ", toc_heading).casefold() in page]
    toc_page = toc_matches[0] if toc_matches else 0
    page_map = {}
    for heading, _style in headings:
        normalized = re.sub(r"\s+", " ", heading).casefold()
        matches = [index for index, page in enumerate(pages, 1) if normalized in page]
        if matches:
            body_matches = [page for page in matches if page > toc_page]
            page_map[heading] = body_matches[-1] if body_matches else matches[0]
    toc_title = next((paragraph for paragraph in document.paragraphs if paragraph.text.strip() == toc_heading), None)
    if toc_title is None:
        return False
    stale_tables = [
        table for table in document.tables
        if table.rows and [cell.text.strip() for cell in table.rows[0].cells] == ["Section", "Page"]
    ]
    for table in stale_tables:
        table._tbl.getparent().remove(table._tbl)
    stale_rows = [
        paragraph for paragraph in document.paragraphs
        if paragraph.style.name.casefold() in {"toc 1", "toc 2"}
        or 'TOC \\o "1-2"' in paragraph._p.xml
    ]
    for paragraph in stale_rows:
        paragraph._p.getparent().remove(paragraph._p)

    anchor = toc_title._p
    created: list[Paragraph] = []
    for heading, style in headings:
        paragraph = document.add_paragraph(style="toc 2" if style == "Heading 2" else "toc 1")
        paragraph.paragraph_format.left_indent = paragraph.style.paragraph_format.left_indent
        paragraph.paragraph_format.tab_stops.add_tab_stop(
            Inches(5.75), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS
        )
        page_number = str(page_map.get(heading, ""))
        paragraph.add_run(f"{heading}\t{page_number}" if page_number else f"{heading}......")
        anchor.addnext(paragraph._p)
        anchor = paragraph._p
        created.append(paragraph)
    if not created:
        return False
    document.save(docx_path)
    return True


def audit_docx(path: Path, *, required_phrases: Iterable[str] = ()) -> list[dict[str, Any]]:
    document = Document(path)
    paragraph_texts = [paragraph.text for paragraph in _all_paragraphs(document)]
    text = "\n".join(paragraph_texts)
    findings = [
        recovery_finding(
            {"category": "rendering", "field": path.name, "issue": f"Unresolved template token: {token}"},
            "document_structure_defect",
        )
        for token in sorted(set(TOKEN.findall(text)))
    ]
    if INTERNAL_LANGUAGE.search(text) or "evidence_refs" in text or "{\"" in text:
        findings.append(recovery_finding({"category": "rendering", "field": path.name, "issue": "Internal structured drafting data leaked into visible text."}, "document_structure_defect"))
    if AUTHORING_LANGUAGE.search(text):
        findings.append(recovery_finding({"category": "rendering", "field": path.name, "issue": "Internal template or authoring guidance leaked into visible text."}, "document_structure_defect"))
    duplicate = next((match for paragraph_text in paragraph_texts if (match := DUPLICATE_WORD.search(paragraph_text))), None)
    if duplicate:
        findings.append(recovery_finding({"category": "rendering", "field": path.name, "issue": f"Visible text repeats the word '{duplicate.group(1)}' consecutively."}, "document_structure_defect"))
    for phrase in required_phrases:
        if phrase and phrase.casefold() not in text.casefold():
            findings.append(recovery_finding({"category": "rendering", "field": path.name, "issue": f"Required visible content is absent: {phrase}"}, "document_structure_defect"))
    with zipfile.ZipFile(path) as package:
        names = set(package.namelist())
        if names & _REVIEW_PARTS:
            findings.append(recovery_finding({"category": "rendering", "field": path.name, "issue": "Comments or reviewer identity parts remain in the DOCX package."}, "document_structure_defect"))
        review_xml = "\n".join(
            package.read(name).decode("utf-8", errors="ignore")
            for name in names
            if name.endswith((".xml", ".rels"))
        )
    if any(marker in review_xml for marker in ("trackRevisions", "commentRangeStart", "commentReference", "<w:del", "<w:moveFrom")):
        findings.append(recovery_finding({"category": "rendering", "field": path.name, "issue": "Tracked changes, comments, or hidden review markup remain in the DOCX package."}, "document_structure_defect"))
    if path.stem == "icf":
        non_heading = [paragraph.text.strip() for paragraph in document.paragraphs if _is_icf_heading(paragraph) and not paragraph.style.name.casefold().startswith("heading")]
        if non_heading:
            findings.append(recovery_finding({"category": "rendering", "field": path.name, "target_ids": ["layout:icf"], "issue": f"Visible ICF headings lack Word heading styles: {non_heading}"}, "visual_defect"))
    return findings


def template_paths(
    repo_root: Path,
    reference: Mapping[str, Any],
    *,
    contracted_bundle: Mapping[str, Any] | None = None,
) -> tuple[Path, Path | None]:
    bundle = contracted_bundle or contracted_template_bundle(repo_root, reference)
    templates = bundle["contracted_templates"]
    protocol = repo_root / str(templates["protocol"]["path"])
    icf_resource = templates.get("icf")
    return protocol, repo_root / str(icf_resource["path"]) if icf_resource else None


def _clear_icf_review_highlighting(document: Document) -> None:
    for paragraph in _all_paragraphs(document):
        for run in paragraph.runs:
            if run.font.highlight_color is not None:
                run.font.highlight_color = None
                run.font.italic = False


def _apply_font_substitutions(document: Document, substitutions: Mapping[str, str]) -> int:
    """Replace unavailable font declarations throughout the generated package."""
    normalized = {
        str(source).casefold(): str(target)
        for source, target in substitutions.items()
        if str(source).strip() and str(target).strip() and str(source).casefold() != str(target).casefold()
    }
    if not normalized:
        return 0
    replaceable_attributes = {"ascii", "hAnsi", "eastAsia", "cs", "font", "name", "typeface"}
    replacements = 0
    for part in document.part.package.parts:
        root = getattr(part, "_element", None)
        if root is None:
            continue
        for element in root.iter():
            for attribute, value in list(element.attrib.items()):
                if ET.QName(attribute).localname not in replaceable_attributes:
                    continue
                replacement = normalized.get(str(value).casefold())
                if replacement is not None:
                    element.set(attribute, replacement)
                    replacements += 1
    return replacements


def render_documents(
    repo_root: Path,
    revision_dir: Path,
    reference: Mapping[str, Any],
    model: Mapping[str, Any],
    *,
    contracted_bundle: Mapping[str, Any] | None = None,
    font_substitutions: Mapping[str, str] | None = None,
    artifact_names: Iterable[str] | None = None,
    layout_repairs: Mapping[str, Iterable[Mapping[str, str]]] | None = None,
) -> dict[str, Any]:
    output = revision_dir / "candidate"; output.mkdir(parents=True, exist_ok=True)
    fields = render_fields(reference, model)
    bundle = dict(contracted_bundle or contracted_template_bundle(repo_root, reference))
    protocol_template, icf_template = template_paths(repo_root, reference, contracted_bundle=bundle)
    boilerplate = _boilerplate(repo_root, bundle)
    substitutions = dict(font_substitutions or {})
    selected = set(artifact_names or bundle["contracted_templates"])
    unknown_artifacts = selected - set(bundle["contracted_templates"])
    if unknown_artifacts:
        raise ValueError(f"Unknown layout-repair artifacts: {sorted(unknown_artifacts)}")
    normalized_repairs: dict[str, list[dict[str, str]]] = {}
    for artifact, repairs in dict(layout_repairs or {}).items():
        if artifact not in selected:
            continue
        normalized: dict[tuple[str, str], dict[str, str]] = {}
        for repair in repairs:
            if not isinstance(repair, Mapping):
                raise ValueError(f"Layout repair for {artifact} must identify a rule and target.")
            rule = str(repair.get("rule") or "").strip()
            target = re.sub(r"\s+", " ", str(repair.get("target") or "")).strip()
            normalized[(rule, target)] = {"rule": rule, "target": target}
        normalized_repairs[artifact] = [normalized[key] for key in sorted(normalized)]
    unknown_rules = {
        f"{artifact}:{repair['rule']}"
        for artifact, repairs in normalized_repairs.items()
        for repair in repairs
        if repair["rule"] not in LAYOUT_REPAIR_RULES[artifact] or not repair["target"]
    }
    if unknown_rules:
        raise ValueError(f"Unknown Layout Contract repair rules: {sorted(unknown_rules)}")
    results = []
    for kind, template in (("protocol", protocol_template), ("icf", icf_template)):
        if template is None or kind not in selected: continue
        authority = repo_root / str(bundle["client_template_authorities"][kind]["path"])
        if not template.is_file():
            results.append({"artifact": kind, "path": "", "status": "blocked", "findings": [{"category": "rendering", "field": kind, "issue": f"Contracted client template is missing: {template}"}]})
            continue
        try:
            document = _template_document(
                reference,
                model,
                template,
                authority_path=authority,
                icf=kind == "icf",
                boilerplate=boilerplate,
                layout_repair_rules=normalized_repairs.get(kind, ()),
            )
        except LayoutRepairTargetError as exc:
            results.append({
                "artifact": kind,
                "path": "",
                "status": "blocked",
                "findings": [{
                    "category": "layout-repair-classification",
                    "field": kind,
                    "artifact": kind,
                    "issue": str(exc),
                }],
            })
            continue
        if kind == "icf":
            _clear_icf_review_highlighting(document)
        font_replacements = _apply_font_substitutions(document, substitutions)
        path = output / f"{kind}.docx"; document.save(path); _strip_review_metadata(path)
        phrases = [_text(get_path(reference, "study.title")), _text(get_path(reference, "meta.protocol_number"))]
        findings = audit_docx(path, required_phrases=phrases)
        results.append({"artifact": kind, "path": path.relative_to(revision_dir).as_posix(), "template": template.relative_to(repo_root).as_posix(), "template_sha256": _sha256_file(template), "client_template_authority": authority.relative_to(repo_root).as_posix(), "client_template_authority_sha256": _sha256_file(authority), "font_replacements": font_replacements, "status": "passed" if not findings else "blocked", "findings": findings})
    return {
        "status": "passed" if all(item["status"] == "passed" for item in results) else "blocked",
        "contracted_template_bundle": bundle,
        "font_substitutions": substitutions,
        "layout_repairs": normalized_repairs,
        "artifacts": results,
    }


__all__ = ["audit_docx", "refresh_toc_from_pdf", "render_documents", "render_fields", "template_paths"]
