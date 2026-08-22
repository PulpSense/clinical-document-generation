"""Contract and package hygiene checks for internal ICF candidates.

The ICF is assembled from the selected client template.  This module owns the
branch-specific hierarchy and the read-only checks that keep template review
residue or stale study facts from becoming client-facing output.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable
import xml.etree.ElementTree as ET

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{" + WORD_NS + "}"


@dataclass(frozen=True)
class ICFSection:
    section_id: str
    title: str
    role: str = "leaf"
    repair: str = ""


ADVARA_TITLES = (
    "INTRODUCTION", "PURPOSE OF THE STUDY", "WHAT WILL HAPPEN DURING THE STUDY",
    "LENGTH OF THE STUDY AND NUMBER OF PARTICIPANTS EXPECTED", "SIDE EFFECTS AND OTHER RISKS",
    "POSSIBLE BENEFITS OF THE STUDY", "PAYMENT FOR BEING IN THE STUDY", "ADDITIONAL COSTS",
    "ALTERNATIVES TO PARTICIPATION", "RELEASE OF MEDICAL RECORDS AND PRIVACY", "LEGAL RIGHTS",
    "NEW FINDINGS", "WHOM TO CONTACT ABOUT THIS STUDY", "LEAVING THE STUDY",
    "AGREEMENT TO BE IN THE STUDY", "IF YOU DO NOT AGREE WITH THE STATEMENT ABOVE, YOU SHOULD NOT SIGN THIS INFORMED CONSENT DOCUMENT.",
)
STERLING_TITLES = (
    "KEY INFORMATION", "BACKGROUND", "PURPOSE", "DURATION", "PROCEDURES",
    "POTENTIAL RISKS, SIDE EFFECTS, DISCOMFORTS, INCONVENIENCES", "POTENTIAL BENEFITS",
    "ALTERNATIVE TREATMENTS", "NEW INFORMATION", "COMPENSATION TO YOU", "COSTS TO YOU",
    "VOLUNTARY PARTICIPATION/WITHDRAWAL", "STUDY COMPLICATIONS AND COMPENSATION",
    "CONFIDENTIALITY AND AUTHORIZATION TO COLLECT, USE AND DISCLOSE YOUR MEDICAL INFORMATION",
    "QUESTIONS", "PARTICIPANT STATEMENT AND AUTHORIZATION",
)


def _sections(titles: Iterable[str], prefix: str = "icf") -> tuple[ICFSection, ...]:
    return tuple(ICFSection(f"{prefix}.{index + 1}", title) for index, title in enumerate(titles))


def icf_contract(study_type: str, template: str) -> tuple[ICFSection, ...]:
    """Return the selected branch's visible ICF leaf contract in order."""
    branch = str(study_type or "").casefold()
    choice = str(template or "").casefold()
    if branch not in {"prospective", "ambispective"}:
        raise ValueError(f"ICF is not supported for study type {study_type!r}.")
    if choice == "advarra":
        titles = list(ADVARA_TITLES)
        if branch == "prospective":
            titles.remove("NEW FINDINGS")
        else:
            titles.insert(titles.index("LEGAL RIGHTS"), "IN CASE OF AN INJURY RELATED TO THIS RESEARCH STUDY")
        sections = list(_sections(titles, "advarra"))
        for index, section in enumerate(sections):
            if section.title == "LEGAL RIGHTS":
                sections[index] = ICFSection(section.section_id, section.title, repair="Remove invalid cross-reference to a nonexistent injury section.")
        return tuple(sections)
    if choice == "sterling":
        return _sections(STERLING_TITLES, "sterling-" + branch)
    raise ValueError(f"Unsupported ICF template {template!r}.")


def unified_icf_batch() -> Any:
    """Return the single model-facing batch used for participant-facing ICF prose."""
    from prospective import ProspectiveDraftingBatch

    return ProspectiveDraftingBatch(
        "icf-narrative",
        tuple(section.section_id for section in icf_contract("Prospective", "Advarra")),
        ("study", "objectives", "population", "procedures", "risks_benefits", "parties", "sites"),
        ("protocol-foundations",),
    )


def verify_icf_sections(drafts: Iterable[Any], study_type: str, template: str) -> list[dict[str, str]]:
    """Fail closed when a unified ICF batch omits or weakly drafts a leaf."""
    values = {str(draft.section_id): str(draft.content or "").strip() for draft in drafts if getattr(draft, "accepted", True)}
    findings: list[dict[str, str]] = []
    for section in icf_contract(study_type, template):
        content = values.get(section.section_id, "")
        if not content:
            findings.append({"section_id": section.section_id, "category": "drafting", "issue": "Required ICF leaf section is not substantive."})
        elif any(token in content.casefold() for token in ("{", "todo", "tbd", "needs review", "internal only")):
            findings.append({"section_id": section.section_id, "category": "drafting", "issue": "ICF section contains unresolved drafting language."})
    return findings


def _text(element: ET.Element) -> str:
    return re.sub(r"\s+", " ", " ".join(item.text or "" for item in element.iter(W + "t"))).strip()


def audit_icf_document(path: Path, contract: Iterable[ICFSection], reference: dict[str, Any]) -> list[dict[str, str]]:
    """Audit a rendered ICF without rewriting it or releasing it."""
    contract = tuple(contract)
    errors: list[dict[str, str]] = []
    try:
        with zipfile.ZipFile(path) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
            root = ET.fromstring(members["word/document.xml"])
            all_xml = b"\n".join(members.values()).decode("utf-8", "ignore")
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        return [{"field": str(path), "issue": f"ICF document cannot be parsed: {exc}."}]

    if re.search(r"<w:(?:commentRangeStart|commentReference|ins|del|moveFrom|moveTo)\b", all_xml):
        errors.append({"field": "word/document.xml", "issue": "Comments or tracked changes remain in the ICF candidate."})
    if re.search(r"<w:vanish\b", all_xml):
        errors.append({"field": "word/document.xml", "issue": "Hidden review content remains in the ICF candidate."})
    if not re.search(r"<w:instrText[^>]*>\s*PAGE\s*</w:instrText>", all_xml, re.I):
        errors.append({"field": "page_fields", "issue": "ICF candidate has no Word PAGE field for page furniture."})
    if not any(name.startswith("word/footer") and name.endswith(".xml") for name in members):
        errors.append({"field": "footers", "issue": "ICF candidate has no Word footer part."})

    body_text = _text(root).casefold()
    source_text = json.dumps(reference, ensure_ascii=False).casefold()
    stale = ("cataract", "handpiece", "eye tests", "eye test", "device")
    for fact in stale:
        if fact in body_text and fact not in source_text:
            errors.append({"field": "word/document.xml", "issue": f"Unsupported stale template fact remains: {fact}."})

    expected = {section.title for section in contract}
    paragraphs = root.findall(".//" + W + "p")
    paragraph_texts = [_text(paragraph) for paragraph in paragraphs]
    contract_titles = {section.title for section in contract}
    for paragraph in paragraphs:
        title = _text(paragraph)
        visible_heading = title in expected or (
            title and title == title.upper() and len(title) >= 4 and not title.endswith(":")
        )
        if not visible_heading:
            continue
        style = paragraph.find("./" + W + "pPr/" + W + "pStyle")
        if style is None or not style.get(W + "val", "").casefold().startswith("heading"):
            errors.append({"field": title, "issue": "Visible ICF heading does not use a Word heading style."})
    for index, title in enumerate(paragraph_texts):
        if title not in contract_titles:
            continue
        substantive = False
        for following in paragraph_texts[index + 1:]:
            if not following:
                continue
            if following in contract_titles or (following == following.upper() and len(following) >= 4 and not following.endswith(":")):
                break
            substantive = True
            break
        if not substantive:
            errors.append({"field": title, "issue": "Required ICF leaf heading has no substantive participant-facing body content."})
    for section in contract:
        if section.title.casefold() not in body_text:
            errors.append({"field": section.title, "issue": "Required ICF heading is missing."})
    if "in case of an injury related to this research study" in body_text and "in case of an injury related to this research study" not in {title.casefold() for title in expected} and "legal rights" in body_text:
        errors.append({"field": "LEGAL RIGHTS", "issue": "Prospective Legal Rights still references a nonexistent injury section."})
    return errors


def sanitize_icf_document(path: Path, contract: Iterable[ICFSection], reference: dict[str, Any]) -> dict[str, Any]:
    """Rebuild an ICF from a clean package, removing review residue.

    This is deliberately limited to structural hygiene and known template
    defects. It does not invent participant-facing prose.
    """
    contract = tuple(contract)
    source_text = json.dumps(reference, ensure_ascii=False).casefold()
    stale = ("cataract", "handpiece", "eye tests", "eye test", "device")
    changed: list[str] = []
    with zipfile.ZipFile(path) as archive:
        members = {item.filename: archive.read(item.filename) for item in archive.infolist()}

    for name, raw in list(members.items()):
        if name.startswith("word/comments"):
            del members[name]
            changed.append(name)
            continue
        if not name.endswith(".xml"):
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            continue
        local_changed = False
        for parent in list(root.iter()):
            for child in list(parent):
                if child.tag in {W + "ins", W + "del", W + "moveFrom", W + "moveTo", W + "commentRangeStart", W + "commentRangeEnd", W + "commentReference"}:
                    parent.remove(child)
                    local_changed = True
        for parent in list(root.iter()):
            for child in list(parent):
                if child.tag == W + "r" and child.find("./" + W + "rPr/" + W + "vanish") is not None:
                    parent.remove(child)
                    local_changed = True
        if name.startswith("word/"):
            for paragraph in root.findall(".//" + W + "p"):
                text_nodes = paragraph.findall(".//" + W + "t")
                text = "".join(node.text or "" for node in text_nodes)
                title = text.strip()
                visible_heading = title in {section.title for section in contract} or (
                    title and title == title.upper() and len(title) >= 4 and not title.endswith(":")
                )
                if visible_heading:
                    ppr = paragraph.find("./" + W + "pPr")
                    if ppr is None:
                        ppr = ET.Element(W + "pPr")
                        paragraph.insert(0, ppr)
                    style = ppr.find("./" + W + "pStyle")
                    if style is None:
                        style = ET.SubElement(ppr, W + "pStyle")
                    if style.get(W + "val") != "Heading1":
                        style.set(W + "val", "Heading1")
                        local_changed = True
                if any(fact in text.casefold() and fact not in source_text for fact in stale):
                    parent = next((candidate for candidate in root.iter() if paragraph in list(candidate)), None)
                    if parent is not None:
                        parent.remove(paragraph)
                        local_changed = True
                        continue
                if "the above statement" in text.casefold() and "in case of an injury" in text.casefold():
                    replacement = re.sub(r"\s*The above statement,.*?negligence\.", "", text, flags=re.I)
                    if text_nodes:
                        text_nodes[0].text = replacement
                        for node in text_nodes[1:]:
                            node.text = ""
                        local_changed = True
        if name == "word/_rels/document.xml.rels":
            for relationship in list(root):
                if "comment" in (relationship.get("Target") or "").casefold():
                    root.remove(relationship)
                    local_changed = True
        if name == "[Content_Types].xml":
            for override in list(root):
                if "comment" in (override.get("PartName") or "").casefold():
                    root.remove(override)
                    local_changed = True
        if local_changed:
            members[name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            changed.append(name)

    if not changed:
        return {"changed": False, "members": []}
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".docx", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(temporary_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, raw in members.items():
                archive.writestr(name, raw)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return {"changed": True, "members": sorted(set(changed))}


__all__ = ["ICFSection", "audit_icf_document", "icf_contract", "sanitize_icf_document", "unified_icf_batch", "verify_icf_sections"]
