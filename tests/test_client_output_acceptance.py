import json
import re
import zipfile
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader, PdfWriter

from contracts import batch_plan
from drafting import create_drafting_request, recorded_acceptance_response, validate_response
from quality import deterministic_content_check, render_pages, sha256_file
from rendering import refresh_toc_from_pdf, render_documents, render_fields


ROOT = Path(__file__).resolve().parents[1]


def _visible_text(document: Document) -> str:
    values = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            values.extend(cell.text for cell in row.cells)
    for section in document.sections:
        values.extend(paragraph.text for paragraph in section.header.paragraphs)
        values.extend(paragraph.text for paragraph in section.footer.paragraphs)
        for container in (section.header, section.footer):
            for table in container.tables:
                for row in table.rows:
                    values.extend(cell.text for cell in row.cells)
    return "\n".join(values)


def _points(value):
    return None if value is None else round(value.pt, 2)


def _paragraph_rhythm(paragraph):
    formatting = paragraph.paragraph_format
    line_spacing = formatting.line_spacing
    if line_spacing is not None and not isinstance(line_spacing, float):
        line_spacing = _points(line_spacing)
    return {
        "space_before": _points(formatting.space_before),
        "space_after": _points(formatting.space_after),
        "line_spacing": line_spacing,
        "left_indent": _points(formatting.left_indent),
        "first_line_indent": _points(formatting.first_line_indent),
    }


def _run_typography(paragraph):
    run = next((item for item in paragraph.runs if item.text.strip()), None)
    if run is None:
        return None
    return {
        "font": run.font.name,
        "size": _points(run.font.size),
        "bold": run.bold,
        "italic": run.italic,
    }


def _doc_default_font(docx_path: Path):
    with zipfile.ZipFile(docx_path) as package:
        styles = package.read("word/styles.xml")
    import xml.etree.ElementTree as ET

    root = ET.fromstring(styles)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    fonts = root.find("./w:docDefaults/w:rPrDefault/w:rPr/w:rFonts", namespace)
    if fonts is None:
        return None, None
    return fonts.get(qn("w:ascii")), fonts.get(qn("w:hAnsi"))


def _numbering_level_signature(document: Document, paragraph):
    numbering_properties = paragraph._p.get_or_add_pPr().find(qn("w:numPr"))
    assert numbering_properties is not None
    number_id = int(numbering_properties.find(qn("w:numId")).get(qn("w:val")))
    level_id = int(numbering_properties.find(qn("w:ilvl")).get(qn("w:val")))
    numbering_root = document.part.numbering_part.element
    number = next(
        item for item in numbering_root.findall(qn("w:num"))
        if int(item.get(qn("w:numId"))) == number_id
    )
    abstract_id = int(number.find(qn("w:abstractNumId")).get(qn("w:val")))
    abstract = next(
        item for item in numbering_root.findall(qn("w:abstractNum"))
        if int(item.get(qn("w:abstractNumId"))) == abstract_id
    )
    level = next(
        item for item in abstract.findall(qn("w:lvl"))
        if int(item.get(qn("w:ilvl"))) == level_id
    )
    marker = level.find(qn("w:lvlText"))
    indentation = level.find(f"{qn('w:pPr')}/{qn('w:ind')}")
    fonts = level.find(f"{qn('w:rPr')}/{qn('w:rFonts')}")
    return {
        "marker": None if marker is None else marker.get(qn("w:val")),
        "left": None if indentation is None else indentation.get(qn("w:left")),
        "hanging": None if indentation is None else indentation.get(qn("w:hanging")),
        "font": None if fonts is None else fonts.get(qn("w:ascii")),
    }


def test_recorded_acceptance_coverage_sentences_are_section_specific(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    batch = next(item for item in batch_plan("Prospective") if item.batch_id == "protocol-operations")
    request_path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-section-specific",
        reference=reference,
        batch=batch,
        attempts={section_id: 1 for section_id in batch.section_ids},
        wave="initial",
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    response = recorded_acceptance_response(request)
    paragraphs = {
        result["section_id"]: [item["text"] for item in result["paragraphs"]]
        for result in response["section_results"]
    }

    duplicates = {
        text
        for section_paragraphs in paragraphs.values()
        for text in section_paragraphs
        if sum(text in other for other in paragraphs.values()) > 1
    }

    assert duplicates == set()


def test_recorded_retrospective_schedule_uses_readable_visit_list(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/retrospective-acceptance-source.json").read_text(encoding="utf-8"))
    reference["procedures"]["visit_schedule_table"].append({
        "visitNumber": "4",
        "visitName": "Month 6",
        "visitWindow": "±14 days",
        "CRFnumber": "CRF-04",
    })
    batch = next(item for item in batch_plan("Retrospective") if item.batch_id == "protocol-operations")
    request_path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-readable-schedule",
        reference=reference,
        batch=batch,
        attempts={section_id: 1 for section_id in batch.section_ids},
        wave="initial",
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))

    response = recorded_acceptance_response(request)

    enrollment = next(item for item in response["section_results"] if item["section_id"] == "study-procedure.enrollment")
    visible = "\n".join(
        [paragraph["text"] for paragraph in enrollment["paragraphs"]]
        + [item for group in enrollment["lists"] for item in group["items"]]
    )
    assert "approved visit schedule table is" not in visible.casefold()
    assert enrollment["lists"] == [{
        "items": [
            "Visit 1: Baseline (Day 0; CRF BL).",
            "Visit 2: Month 3 (Day 90 +/- 7; CRF M3).",
            "Visit 4: Month 6 (±14 days; CRF-04).",
        ],
        "evidence_refs": ["source:procedures.visit_schedule_table"],
        "boilerplate_refs": [],
    }]


def test_sterling_icf_removes_review_metadata_and_uses_heading_styles(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    reference["meta"]["icf_template"] = "Sterling"

    report = render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})
    assert report["status"] == "passed"

    output_path = tmp_path / "candidate/icf.docx"
    output = Document(output_path)
    mapped_headings = {"PURPOSE", "DURATION", "PROCEDURES", "POTENTIAL BENEFITS", "COSTS TO YOU"}
    heading_paragraphs = {paragraph.text.strip(): paragraph for paragraph in output.paragraphs if paragraph.text.strip() in mapped_headings}
    assert set(heading_paragraphs) == mapped_headings
    assert all(paragraph.style.name.casefold().startswith("heading") for paragraph in heading_paragraphs.values())
    for index, paragraph in enumerate(output.paragraphs):
        normalized = re.sub(r"\s+", " ", paragraph.text).strip()
        if not normalized.startswith(("COMPENSATION TO YOU", "STUDY COMPLICATIONS", "PARTICIPANT STATEMENT")):
            continue
        if index and output.paragraphs[index - 1].text.strip():
            assert paragraph.paragraph_format.space_before is not None
            assert paragraph.paragraph_format.space_before >= Pt(6)

    with zipfile.ZipFile(output_path) as package:
        names = set(package.namelist())
        assert not {name for name in names if "comments" in name.casefold() or name == "word/people.xml"}
        package_xml = "\n".join(
            package.read(name).decode("utf-8", errors="ignore")
            for name in names
            if name.endswith((".xml", ".rels"))
        )
    assert "trackRevisions" not in package_xml
    assert "commentRangeStart" not in package_xml
    assert "commentReference" not in package_xml


def test_rendering_uses_prs_provider_study_id_when_protocol_number_is_absent(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    reference["meta"].pop("protocol_number", None)
    reference.setdefault("regulatory", {}).setdefault("prs", {})["provider_study_id"] = "AS-SP-001"
    reference["meta"]["icf_template"] = "Sterling"

    report = render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})

    assert report["status"] == "passed"
    assert "AS-SP-001" in _visible_text(Document(tmp_path / "candidate/protocol.docx"))
    assert "AS-SP-001" in _visible_text(Document(tmp_path / "candidate/icf.docx"))


def test_sterling_icf_replaces_example_shell_policies_with_authorized_content(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    reference["meta"]["icf_template"] = "Sterling"
    risk_text = (
        "Taking part may involve inconvenience or discomfort from the study procedures described in this consent form. "
        "There is also a risk that private information could be disclosed, although safeguards will be used to protect it."
    )
    privacy_text = (
        "By signing this form, you authorize the study team to collect, use, and disclose the medical and study information "
        "described in this form for this research. Records will use appropriate identifiers and access controls."
    )
    model = {
        "protocol": [],
        "prs": {},
        "icf": {
            "icf.risks": {"paragraphs": [{"text": risk_text}], "lists": []},
            "icf.privacy": {"paragraphs": [{"text": privacy_text}], "lists": []},
        },
    }

    render_documents(ROOT, tmp_path, reference, model)
    visible = _visible_text(Document(tmp_path / "candidate/icf.docx"))

    assert visible.count(risk_text) == 2  # key information and the full risks section
    assert "risks or inconveniences that are currently unknown" not in visible
    assert "in a timely manner" not in visible
    assert "Sterling Institutional Review Board" not in visible
    assert "Example IRB" in visible
    assert "555-0100" in visible
    assert "irb@example.org" in visible
    assert "no new routine research procedures will be performed unless you separately agree" in visible
    assert "the FDA" not in visible


def test_protocol_removes_unsupported_template_governance_claims(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))

    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})
    visible = _visible_text(Document(tmp_path / "candidate/protocol.docx")).casefold()

    assert "will be registered with clinicaltrials.gov" not in visible
    assert "will be conducted in compliance with the protocol, gcp" not in visible
    assert "the study will be conducted under the approved protocol" in visible


def test_sterling_icf_does_not_duplicate_flat_site_address(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    reference["meta"]["icf_template"] = "Sterling"
    reference["sites"][0]["facility"] = {
        "name": "North Surgical Research Center",
        "address": "220 Clinic Way",
        "city": "Boston",
        "state": "MA",
        "country": "United States",
    }

    model = {"protocol": [], "icf": {}, "prs": {}}
    fields = render_fields(reference, model)
    render_documents(ROOT, tmp_path, reference, model)
    visible = _visible_text(Document(tmp_path / "candidate/icf.docx"))

    assert fields["facilityAddress"] == "220 Clinic Way"
    assert fields["facilityLocation"] == "Boston, MA, United States"
    assert "Boston, MA, United States" in visible


def test_sterling_icf_uses_real_page_and_page_count_fields_in_every_footer(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    reference["meta"]["icf_template"] = "Sterling"

    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})

    with zipfile.ZipFile(tmp_path / "candidate/icf.docx") as package:
        footers = [package.read(name) for name in package.namelist() if name.startswith("word/footer") and name.endswith(".xml")]

    assert len(footers) == 2
    assert all(b"<w:pgNum" not in footer for footer in footers)
    assert all(b"> PAGE \\* arabic \\* MERGEFORMAT </w:instrText>" in footer for footer in footers)
    assert all(b"> NUMPAGES \\* arabic \\* MERGEFORMAT </w:instrText>" in footer for footer in footers)


def test_sterling_icf_retains_every_client_shell_section_and_signature_block(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    reference["meta"]["icf_template"] = "Sterling"
    model = {
        "protocol": [],
        "prs": {},
        "icf": {
            section_id: {"paragraphs": [{"text": f"Approved content for {section_id}."}], "lists": []}
            for section_id in ("icf.costs", "icf.alternatives", "icf.privacy", "icf.injury")
        },
    }

    render_documents(ROOT, tmp_path, reference, model)
    visible = " ".join(_visible_text(Document(tmp_path / "candidate/icf.docx")).split())

    for title in (
        "AUTHORIZATION TO USE AND DISCLOSE MEDICAL INFORMATION",
        "KEY INFORMATION",
        "BACKGROUND",
        "INFORMATION",
        "VOLUNTARY PARTICIPATION/WITHDRAWAL",
        "QUESTIONS",
        "PARTICIPANT STATEMENT AUTHORIZATION",
        "Signature of Participant",
    ):
        assert title in visible


def test_sterling_icf_keeps_withdrawal_heading_with_body_and_avoids_forced_signature_page(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    reference["meta"]["icf_template"] = "Sterling"

    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})
    document = Document(tmp_path / "candidate/icf.docx")

    withdrawal = next(paragraph for paragraph in document.paragraphs if paragraph.text.strip() == "VOLUNTARY PARTICIPATION/WITHDRAWAL")
    assert withdrawal.paragraph_format.keep_with_next is True
    assert withdrawal.paragraph_format.keep_together is True
    withdrawal_index = next(index for index, paragraph in enumerate(document.paragraphs) if paragraph._p is withdrawal._p)
    spacer = document.paragraphs[withdrawal_index + 1]
    assert not spacer.text.strip()
    assert spacer.paragraph_format.keep_with_next is True
    assert spacer.paragraph_format.keep_together is True
    questions = next(paragraph for paragraph in document.paragraphs if paragraph.text.strip() == "QUESTIONS")
    assert questions.paragraph_format.page_break_before is not True

    signature_index = next(
        index
        for index, paragraph in enumerate(document.paragraphs)
        if " ".join(paragraph.text.split()) == "PARTICIPANT STATEMENT AUTHORIZATION"
    )
    signature = document.paragraphs[signature_index]
    assert not signature._p.xpath('.//w:br[@w:type="page"]')
    signature_tail = document.paragraphs[signature_index:]
    assert all(paragraph.paragraph_format.keep_with_next is True for paragraph in signature_tail[:-1])
    assert all(paragraph.paragraph_format.keep_together is True for paragraph in signature_tail)


def test_prospective_advarra_repairs_legal_rights_without_inventing_injury_section(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    model = {
        "protocol": [],
        "prs": {},
        "icf": {
            "icf.injury": {
                "paragraphs": [{"text": "This draft must not create a template section."}],
                "lists": [],
            }
        },
    }

    render_documents(ROOT, tmp_path, reference, model)
    visible = _visible_text(Document(tmp_path / "candidate/icf.docx"))

    assert "IN CASE OF AN INJURY RELATED TO THIS RESEARCH STUDY" not in visible
    assert "This draft must not create a template section." not in visible
    assert "The above statement" not in visible
    assert "You do not lose any legal rights by signing and dating this consent document." in visible


def test_shallow_section_draft_cannot_pass_content_depth_gate(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    batch = next(item for item in batch_plan("Prospective") if item.batch_id == "protocol-foundations")
    request_path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-depth",
        reference=reference,
        batch=batch,
        attempts={section_id: 1 for section_id in batch.section_ids},
        wave="initial",
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    response = recorded_acceptance_response(request)
    introduction = next(item for item in response["section_results"] if item["section_id"] == "introduction")
    introduction["paragraphs"] = [
        {
            **introduction["paragraphs"][0],
            "text": "This study evaluates the approved clinical objective using the stated design.",
        }
    ]
    introduction["lists"] = []

    accepted, findings = validate_response(request, response)
    accepted_ids = {draft["section_id"] for draft in (accepted or {}).get("drafts", [])}

    assert "introduction" not in accepted_ids
    assert any(item["field"] == "introduction" for item in findings)


def test_client_protocol_template_renders_source_supported_schedule_of_assessments(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    report = render_documents(ROOT, tmp_path, reference, {
        "protocol": [{
            "section_id": "quality-safety.reporting",
            "paragraphs": [{"text": "Approved safety events will be recorded and reported under the study procedures."}],
            "lists": [],
        }],
        "icf": {},
        "prs": {},
    })
    protocol_report = next(item for item in report["artifacts"] if item["artifact"] == "protocol")
    assert protocol_report["status"] == "passed"

    output = Document(tmp_path / "candidate/protocol.docx")
    assessment = next(table for table in output.tables if "Device initiation" in "\n".join(cell.text for row in table.rows for cell in row.cells))
    assessment_table = "\n".join(cell.text for row in assessment.rows for cell in row.cells)

    assert "Activity" in assessment_table
    assert "Baseline" in assessment_table
    assert "Consent" in assessment_table
    assert "X" in assessment_table
    grid_widths = [int(column.w) for column in assessment._tbl.tblGrid.gridCol_lst]
    assert grid_widths[0] > max(grid_widths[1:])
    assert assessment.cell(0, 0)._tc is assessment.cell(1, 0)._tc
    first_column = [row.tc_lst[0] for row in assessment._tbl.tr_lst]
    merge_values = [
        None if (merge := cell.tcPr.find(qn("w:vMerge"))) is None else merge.get(qn("w:val"))
        for cell in first_column
    ]
    first_widths = [int(cell.tcPr.find(qn("w:tcW")).get(qn("w:w"))) for cell in first_column]
    assert merge_values[:2] == ["restart", None]
    assert merge_values[2:] == [None] * (len(merge_values) - 2)
    assert len(set(first_widths)) == 1
    assert first_widths[0] == round(grid_widths[0] / 635)
    continuation_borders = first_column[1].tcPr.find(qn("w:tcBorders"))
    continuation_top = None if continuation_borders is None else continuation_borders.find(qn("w:top"))
    assert continuation_top is None or continuation_top.get(qn("w:val")) == "nil"
    for cell in assessment._tbl.tr_lst[-1].tc_lst:
        bottom = cell.tcPr.find(f"{qn('w:tcBorders')}/{qn('w:bottom')}")
        assert bottom is not None
        assert bottom.get(qn("w:val")) == "double"

    contact = next(table for table in output.tables if table.rows[0].cells[0].text.strip() == "Study Staff")
    assert contact.rows[0]._tr.get_or_add_trPr().find(qn("w:tblHeader")) is not None
    assert all(
        row._tr.get_or_add_trPr().find(qn("w:tblHeader")) is None
        for row in contact.rows[1:]
    )
    assert all(row._tr.get_or_add_trPr().find(qn("w:cantSplit")) is not None for row in contact.rows)
    assert all(
        paragraph.paragraph_format.keep_together is True
        for row in contact.rows
        for cell in row.cells
        for paragraph in cell.paragraphs
    )
    assert all(
        paragraph.paragraph_format.keep_with_next is True
        for cell in contact.rows[0].cells
        for paragraph in cell.paragraphs
    )
    contact_caption_tail = Paragraph(contact._tbl.getprevious(), output)
    contact_caption_head = Paragraph(contact_caption_tail._p.getprevious(), output)
    assert contact_caption_head.text.strip().startswith("Table 13.3.-1")
    assert contact_caption_tail.text.strip() == "Contact Information for Study"
    assert contact_caption_head.paragraph_format.keep_with_next is True
    assert contact_caption_tail.paragraph_format.keep_with_next is True
    assert contact_caption_head.paragraph_format.page_break_before is not True


def test_table_specific_break_requires_a_classified_table_repair(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))

    report = render_documents(
        ROOT,
        tmp_path,
        reference,
        {"protocol": [], "icf": {}, "prs": {}},
        artifact_names={"protocol"},
        layout_repairs={"protocol": ({"rule": "table_pagination", "target": "Table 13.3.-1"},)},
    )

    assert report["layout_repairs"] == {
        "protocol": [{"rule": "table_pagination", "target": "Table 13.3.-1"}],
    }
    protocol = Document(tmp_path / "candidate/protocol.docx")
    contact = next(table for table in protocol.tables if table.rows[0].cells[0].text.strip() == "Study Staff")
    caption_tail = Paragraph(contact._tbl.getprevious(), protocol)
    caption_head = Paragraph(caption_tail._p.getprevious(), protocol)
    assert caption_head.text.strip().startswith("Table 13.3.-1")
    assert not re.match(r"^\d+(?:\.\d+)*\.?\s+", caption_head.text.strip())
    assert caption_head.paragraph_format.page_break_before is True
    visits_caption = next(
        paragraph for paragraph in protocol.paragraphs
        if paragraph.text.strip().startswith("Table 9.2-1")
    )
    assert visits_caption.paragraph_format.page_break_before is not True


def test_client_templates_normalize_visual_edge_cases(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    model = {
        "protocol": [{
            "section_id": "analysis-plan.datasets",
            "paragraphs": [{"text": "The analysis data sets include all approved study measures."}],
            "lists": [],
        }],
        "icf": {
            "icf.risks": {
                "paragraphs": [{"text": "Taking part may involve inconvenience or discomfort from the approved procedures."}],
                "lists": [],
            }
        },
        "prs": {},
    }

    report = render_documents(ROOT, tmp_path, reference, model)
    assert report["status"] == "passed"

    icf = Document(tmp_path / "candidate/icf.docx")
    icf_reference = Document(ROOT / "assets/client-templates/reference/advarra-icf-reference.docx")
    risk = next(paragraph for paragraph in icf.paragraphs if paragraph.text.startswith("Taking part may involve"))
    reference_risk_heading_index = next(
        index for index, paragraph in enumerate(icf_reference.paragraphs)
        if paragraph.text.strip() == "SIDE EFFECTS AND OTHER RISKS"
    )
    reference_risk = next(
        paragraph for paragraph in icf_reference.paragraphs[reference_risk_heading_index + 1:]
        if paragraph.text.strip()
    )
    assert _paragraph_rhythm(risk) == _paragraph_rhythm(reference_risk)
    preferences = [paragraph for paragraph in icf.paragraphs if paragraph.text.strip().startswith(("☐ Yes,", "☐ No,"))]
    assert len(preferences) == 2
    assert all(paragraph._p.pPr is None or paragraph._p.pPr.find(qn("w:numPr")) is None for paragraph in preferences)
    preference_heading = next(
        paragraph for paragraph in icf.paragraphs
        if paragraph.text.strip().startswith("Check your preference below")
    )
    preference_heading_index = next(
        index for index, paragraph in enumerate(icf.paragraphs)
        if paragraph._p is preference_heading._p
    )
    final_preference_index = next(
        index for index, paragraph in enumerate(icf.paragraphs)
        if paragraph._p is preferences[-1]._p
    )
    preference_block = icf.paragraphs[preference_heading_index:final_preference_index + 1]
    assert all(paragraph.paragraph_format.keep_with_next is True for paragraph in preference_block[:-1])
    assert all(
        paragraph.paragraph_format.keep_together is True
        for paragraph in preference_block
    )
    agreement_index = next(index for index, paragraph in enumerate(icf.paragraphs) if paragraph.text.strip() == "AGREEMENT TO BE IN THE STUDY")
    assert not (agreement_index >= 2 and not icf.paragraphs[agreement_index - 1].text.strip() and not icf.paragraphs[agreement_index - 2].text.strip())
    agreement = icf.paragraphs[agreement_index]
    reference_agreement = next(
        paragraph for paragraph in icf_reference.paragraphs
        if paragraph.text.strip() == "AGREEMENT TO BE IN THE STUDY"
    )
    assert _paragraph_rhythm(agreement) == _paragraph_rhythm(reference_agreement)
    no_sign_index = next(
        index
        for index, paragraph in enumerate(icf.paragraphs)
        if paragraph.text.strip().startswith("IF YOU DO NOT AGREE WITH THE STATEMENT ABOVE")
    )
    final_copy_index = next(
        index
        for index, paragraph in enumerate(icf.paragraphs)
        if paragraph.text.strip() == "You will be given a signed and dated copy of this informed consent document to keep."
    )
    assert all(
        paragraph.paragraph_format.keep_with_next is True
        for paragraph in icf.paragraphs[no_sign_index:final_copy_index]
    )

    protocol = Document(tmp_path / "candidate/protocol.docx")
    protocol_reference = Document(ROOT / "assets/client-templates/reference/protocol-reference.docx")
    analysis_heading = next(paragraph for paragraph in protocol.paragraphs if paragraph.text.strip().startswith("10.1. Analysis Data Sets"))
    reference_analysis_heading = next(
        paragraph for paragraph in protocol_reference.paragraphs
        if paragraph.text.strip().startswith("10.1. Analysis Data Sets")
    )
    assert _paragraph_rhythm(analysis_heading) == _paragraph_rhythm(reference_analysis_heading)
    summary_tables = [
        table
        for table in protocol.tables
        if any(row.cells[0].text.strip() in {"Objective", "Variables"} for row in table.rows)
    ]
    assert len(summary_tables) == 1
    assert summary_tables[0].rows[0].cells[0].text.strip() == "Objective"
    assert any(row.cells[0].text.strip() == "Variables" for row in summary_tables[0].rows)
    assert all(row.height is None for row in summary_tables[0].rows)
    visit_caption = next(paragraph for paragraph in protocol.paragraphs if paragraph.text.strip().startswith("Table 9.2-1"))
    assert visit_caption.paragraph_format.keep_with_next is True
    toc_rows = [paragraph for paragraph in protocol.paragraphs if paragraph.style.name.casefold() in {"toc 1", "toc 2"}]
    for paragraph in toc_rows:
        assert "\t" not in paragraph.text
        assert "......" in paragraph.text
        assert paragraph.text.rstrip()[-1:].isdigit()
    contact_table = next(
        table for table in protocol.tables
        if any("Business" in cell.text and "Phone" in cell.text for row in table.rows for cell in row.cells)
    )
    assert contact_table.rows[0].cells[3].width >= contact_table.rows[0].cells[1].width
    for row in contact_table.rows[1:]:
        for cell_index in (1, 3):
            assert cell_index < len(row.cells)
            assert row.cells[cell_index]._tc.get_or_add_tcPr().find(qn("w:noWrap")) is not None


def test_generated_protocol_and_icf_lists_use_word_numbering_not_typed_bullet_characters(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    protocol_item = "Approved protocol eligibility item for Word numbering."
    icf_item = "Approved participant procedure item for Word numbering."
    model = {
        "protocol": [{"section_id": "subjects.inclusion", "paragraphs": [], "lists": [{"items": [protocol_item]}]}],
        "icf": {"icf.procedures": {"paragraphs": [], "lists": [{"items": [icf_item]}]}},
        "prs": {},
    }

    render_documents(ROOT, tmp_path, reference, model)
    protocol = Document(tmp_path / "candidate/protocol.docx")
    icf = Document(tmp_path / "candidate/icf.docx")

    for document, item in ((protocol, protocol_item), (icf, icf_item)):
        paragraph = next(paragraph for paragraph in document.paragraphs if paragraph.text == item)
        assert not paragraph.text.startswith("•")
        assert paragraph._p.get_or_add_pPr().find(qn("w:numPr")) is not None
        assert len(paragraph._p.findall(qn("w:pPr"))) == 1


def test_icf_overview_and_visit_detail_placeholders_do_not_duplicate_the_same_draft(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    model = {
        "protocol": [],
        "prs": {},
        "icf": {
            "icf.procedures": {
                "paragraphs": [{
                    "text": "Historical records are reviewed. At Baseline, the Sentinel Patch is initiated.",
                    "evidence_refs": ["source:procedures.visit_schedule"],
                    "boilerplate_refs": [],
                }],
                "lists": [],
            }
        },
    }
    render_documents(ROOT, tmp_path, reference, model)
    visible = _visible_text(Document(tmp_path / "candidate/icf.docx"))

    assert visible.count("Historical records are reviewed.") == 1
    assert visible.count("At Baseline, the Sentinel Patch is initiated.") == 1


def test_advarra_icf_uses_every_accepted_study_section_and_removes_example_study_prose(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/ambispective-acceptance-source.json").read_text(encoding="utf-8"))
    section_ids = (
        "icf.study-purpose", "icf.procedures", "icf.duration", "icf.risks", "icf.benefits",
        "icf.payment", "icf.costs", "icf.alternatives", "icf.privacy", "icf.injury",
    )
    markers = {
        section_id: f"Approved participant-facing content for {section_id.replace('.', ' ')} appears here."
        for section_id in section_ids
    }
    model = {
        "protocol": [],
        "prs": {},
        "icf": {
            section_id: {
                "paragraphs": [{"text": marker, "evidence_refs": [], "boilerplate_refs": []}],
                "lists": [],
            }
            for section_id, marker in markers.items()
        },
    }

    render_documents(ROOT, tmp_path, reference, model)
    output = Document(tmp_path / "candidate/icf.docx")
    visible = _visible_text(output)

    assert all(marker in visible for marker in markers.values())
    assert "eye tests and procedures" not in visible.casefold()
    assert "no additional side effects or risks expected" not in visible.casefold()
    assert 'w:type="column"' not in output.element.xml


def test_quality_gate_rejects_example_study_prose_not_supported_by_the_source(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/ambispective-acceptance-source.json").read_text(encoding="utf-8"))
    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})
    icf_path = tmp_path / "candidate/icf.docx"
    icf = Document(icf_path)
    icf.add_paragraph("You will have eye tests and procedures performed for this study.")
    icf.save(icf_path)

    findings = deterministic_content_check(tmp_path, reference)

    assert any("example-study" in item["issue"].casefold() for item in findings)


def test_protocol_summary_table_keeps_client_label_width_and_source_masking(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    model = {
        "protocol": [
            {"section_id": "objectives", "paragraphs": [], "lists": [{"items": ["Describe recovery outcomes."]}]},
            {"section_id": "study-design.bias", "paragraphs": [{"text": "Bias-control narrative belongs in Section 8.2."}], "lists": []},
        ],
        "icf": {},
        "prs": {},
    }
    render_documents(ROOT, tmp_path, reference, model)
    output = Document(tmp_path / "candidate/protocol.docx")
    summary = next(table for table in output.tables if table.rows[0].cells[0].text.strip() == "Objective")
    values = {row.cells[0].text.strip(): row.cells[1].text.strip() for row in summary.rows}

    assert all(row.cells[0].paragraphs[0].paragraph_format.right_indent is None for row in summary.rows)
    assert not values["Objective"].startswith("•")
    assert values["Masking"] == "None"
    assert "Bias-control narrative" not in values["Masking"]


def test_protocol_visit_overview_and_detail_placeholders_do_not_duplicate_the_same_draft(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    model = {
        "protocol": [{
            "section_id": "study-procedure.visits",
            "paragraphs": [{"text": "Four study time points are planned. Baseline includes device initiation."}],
            "lists": [],
        }],
        "icf": {},
        "prs": {},
    }
    render_documents(ROOT, tmp_path, reference, model)
    document = Document(tmp_path / "candidate/protocol.docx")
    visible = _visible_text(document)

    assert visible.count("Four study time points are planned.") == 1
    assert visible.count("Baseline includes device initiation.") == 1
    generated = [paragraph for paragraph in document.paragraphs if "study time points" in paragraph.text or "device initiation" in paragraph.text]
    assert all(paragraph.paragraph_format.left_indent is None for paragraph in generated)
    assert all(paragraph.paragraph_format.right_indent is None for paragraph in generated)


def test_visit_schedule_omits_crf_column_when_source_has_no_crf_values(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    for visit in reference["procedures"]["visit_schedule_table"]:
        visit.pop("CRFnumber", None)
    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})
    output = Document(tmp_path / "candidate/protocol.docx")
    schedule = next(table for table in output.tables if len(table.rows[0].cells) > 1 and "Visit Name" in table.rows[0].cells[1].text)

    assert len(schedule.columns) == 3
    assert all("CRF" not in cell.text for row in schedule.rows for cell in row.cells)
    authority = Document(ROOT / "assets/client-templates/reference/protocol-reference.docx")
    authority_schedule = next(
        table for table in authority.tables
        if len(table.columns) == 3 and table.rows[0].cells[0].text.strip() == "Visit Number"
    )
    output_grid = [column.w for column in schedule._tbl.tblGrid.gridCol_lst]
    authority_grid = [column.w for column in authority_schedule._tbl.tblGrid.gridCol_lst]
    output_width = schedule._tbl.tblPr.find(qn("w:tblW"))
    authority_width = authority_schedule._tbl.tblPr.find(qn("w:tblW"))
    output_fills = [cell._tc.tcPr.find(qn("w:shd")).get(qn("w:fill")) for cell in schedule.rows[0].cells]
    authority_fills = [cell._tc.tcPr.find(qn("w:shd")).get(qn("w:fill")) for cell in authority_schedule.rows[0].cells]

    assert schedule.style.style_id == authority_schedule.style.style_id
    assert output_grid == authority_grid
    assert output_width.get(qn("w:w")) == authority_width.get(qn("w:w"))
    assert output_fills == authority_fills
    output_second_data_borders = [
        cell._tc.tcPr.find(qn("w:tcBorders"))
        for cell in schedule.rows[2].cells
    ]
    authority_second_data_borders = [
        cell._tc.tcPr.find(qn("w:tcBorders"))
        for cell in authority_schedule.rows[2].cells
    ]
    border_signature = lambda borders: None if borders is None else [
        (border.tag, tuple(sorted(border.attrib.items())))
        for border in borders
    ]
    assert [border_signature(borders) for borders in output_second_data_borders] == [
        border_signature(borders) for borders in authority_second_data_borders
    ]


def test_protocol_uses_source_bound_section_drafts_not_example_study_body_text(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    model = {
        "protocol": [
            {"section_id": "study-procedure.discontinued", "paragraphs": [{"text": "Participants may withdraw at any time; information collected before withdrawal may remain in the study records."}], "lists": []},
            {"section_id": "endpoint-criteria.discontinuation", "paragraphs": [{"text": "A participant may discontinue participation at any time without penalty."}], "lists": []},
            {"section_id": "quality-safety.general", "paragraphs": [{"text": "Safety information and product quality complaints will be documented and reviewed under the approved study safety procedures."}], "lists": []},
            {"section_id": "quality-safety.analysis", "paragraphs": [{"text": "Safety findings will be summarized using the event categories and timing available in the study data."}], "lists": []},
            {"section_id": "ethics.confidentiality", "paragraphs": [{"text": "Study records will use appropriate identifiers and access controls for authorized personnel."}], "lists": []},
        ],
        "icf": {},
        "prs": {},
    }
    render_documents(ROOT, tmp_path, reference, model)
    output = Document(tmp_path / "candidate/protocol.docx")
    visible = _visible_text(output).casefold()

    assert len(output.sections) == 1
    assert "safety findings will be summarized" in visible
    assert "ocular adverse" not in visible
    assert "performed on eyes" not in visible
    assert "prior to surgery" not in visible
    assert "prior to visit 7" not in visible


def test_observational_outputs_remove_unapproved_template_study_claims(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/ambispective-acceptance-source.json").read_text(encoding="utf-8"))
    reference["meta"].pop("version", None)
    reference["parties"]["irb"]["approval_status"] = "Pending"
    reference["safety"] = {}
    reference["ethics"] = {}
    reference["parties"]["funding_source"] = {"name": "ACME Foundation"}
    reference["risks_benefits"] = {"compensation_or_reimbursement": "None"}
    model = {
        "protocol": [],
        "icf": {
            "icf.injury": {"paragraphs": [{"text": "Study personnel will evaluate and document research-related medical concerns."}], "lists": []},
            "icf.costs": {"paragraphs": [{"text": "No study-related cost terms are specified in the approved study information."}], "lists": []},
        },
        "prs": {},
    }

    report = render_documents(ROOT, tmp_path, reference, model)
    assert report["status"] == "passed"
    protocol = Document(tmp_path / "candidate/protocol.docx")
    icf = Document(tmp_path / "candidate/icf.docx")
    protocol_visible = _visible_text(protocol)
    icf_visible = _visible_text(icf)

    title_table = next(table for table in protocol.tables if table.cell(0, 0).text.strip() == "Protocol Number")
    assert title_table.cell(1, 1).text.strip() == ""
    assert "An ambispective observational device study" in protocol_visible
    assert "investigator-initiated clinical trial" not in protocol_visible
    assert "All subjects will be monitored for adverse events" not in protocol_visible
    assert "1996 version of the Declaration of Helsinki" not in protocol_visible
    assert "approval prior to initiating the study" not in protocol_visible
    assert "funding only" not in protocol_visible.casefold()

    assert "NOT TO BE USED FOR PARTICIPANT ENROLLMENT" not in icf_visible
    assert "description of this clinical trial" not in icf_visible
    assert "Advarra Institutional Review Board" not in icf_visible
    assert reference["parties"]["irb"]["name"] in icf_visible
    assert "all charges for medical care" not in icf_visible
    assert "insurance company" not in icf_visible


def test_protocol_agreement_and_icf_shell_are_source_bound(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/ambispective-acceptance-source.json").read_text(encoding="utf-8"))
    reference["meta"]["version"] = ""
    reference["meta"]["date"] = "24 Aug 2026"
    reference["sites"][0]["facility"]["address"] = {
        "street": "220 Clinic Way", "city": "Boston", "state": "MA", "country": "United States"
    }
    model = {
        "protocol": [],
        "icf": {
            "icf.privacy": {"paragraphs": [{"text": "Your records will use coded identifiers and may be reviewed only by authorized study and oversight personnel."}], "lists": []},
            "icf.injury": {"paragraphs": [{"text": "Contact the study doctor promptly if you believe a study activity caused an injury."}], "lists": []},
            "icf.costs": {"paragraphs": [{"text": "Before you sign, the study team will explain whether any research costs are your responsibility."}], "lists": []},
        },
        "prs": {},
    }

    render_documents(ROOT, tmp_path, reference, model)
    protocol = Document(tmp_path / "candidate/protocol.docx")
    icf = Document(tmp_path / "candidate/icf.docx")
    protocol_visible = _visible_text(protocol).casefold()
    icf_visible = _visible_text(icf).casefold()

    assert "study products" not in protocol_visible
    assert "serious adverse events defined in section 13" not in protocol_visible
    assert "firm in another country" not in icf_visible
    assert "health canada" not in icf_visible
    assert "as required by u.s. law" not in icf_visible
    title = next(table for table in protocol.tables if table.rows[0].cells[0].text.strip() == "Protocol Number")
    title_values = {row.cells[0].text.strip(): row.cells[1].text.strip() for row in title.rows}
    assert title_values["Protocol Date"] == "24 Aug 2026"
    assert title_values["Amendment Number"] == ""
    header_control = "\n".join(
        cell.text
        for section in icf.sections
        for table in section.header.tables
        for row in table.rows
        for cell in row.cells
    ).casefold()
    assert "24 aug 2026" not in header_control

    front = icf.tables[0]
    labels = [row.cells[0].text.strip() for row in front.rows]
    values = [row.cells[1].text.strip() for row in front.rows]
    assert "Study Coordinator Telephone:" in labels
    assert "Study Site Address:" in labels
    assert reference["parties"]["study_coordinator"]["business_phone"] in values
    assert any(reference["sites"][0]["facility"]["address"]["street"] in value for value in values)

    summary = next(table for table in protocol.tables if table.rows[0].cells[0].text.strip() == "Objective")
    summary_values = {row.cells[0].text.strip(): row.cells[1].text.strip() for row in summary.rows}
    assert "Hypothesis" not in summary_values
    assert summary_values["Test Article(s)"]


def test_retrospective_enrollment_body_is_inserted_after_template_heading_normalization(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/retrospective-acceptance-source.json").read_text(encoding="utf-8"))
    expected = "This retrospective study uses existing records and the approved record-review sequence."
    model = {
        "protocol": [{
            "section_id": "study-procedure.enrollment",
            "paragraphs": [{"text": expected}],
            "lists": [],
        }],
        "icf": {},
        "prs": {},
    }

    report = render_documents(ROOT, tmp_path, reference, model)

    assert report["status"] == "passed"
    protocol = Document(tmp_path / "candidate/protocol.docx")
    paragraphs = protocol.paragraphs
    heading_index = next(index for index, paragraph in enumerate(paragraphs) if paragraph.text.strip().startswith("8.1. Informed Consent"))
    next_heading = next(
        index for index in range(heading_index + 1, len(paragraphs))
        if paragraphs[index].style.name.casefold().startswith("heading")
    )
    assert expected in "\n".join(paragraph.text for paragraph in paragraphs[heading_index + 1:next_heading])


def test_retrospective_inline_template_body_is_not_duplicated(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/retrospective-acceptance-source.json").read_text(encoding="utf-8"))
    expected = "The analysis data sets will be organized around the approved outcome summaries."
    model = {
        "protocol": [{
            "section_id": "analysis-plan.datasets",
            "paragraphs": [{"text": expected}],
            "lists": [],
        }],
        "icf": {},
        "prs": {},
    }

    render_documents(ROOT, tmp_path, reference, model)

    protocol = Document(tmp_path / "candidate/protocol.docx")
    assert _visible_text(protocol).count(expected) == 1
    heading_index = next(
        index for index, paragraph in enumerate(protocol.paragraphs)
        if paragraph.text.strip() == "9.1. Analysis Data Sets"
    )
    assert protocol.paragraphs[heading_index].style.name == "Heading 2"
    assert protocol.paragraphs[heading_index + 1].text == expected
    assert protocol.paragraphs[heading_index + 1].style.name == "Normal"


def test_ambispective_body_sections_follow_template_pagination_and_spacing(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/ambispective-acceptance-source.json").read_text(encoding="utf-8"))

    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})

    protocol = Document(tmp_path / "candidate/protocol.docx")
    authority = Document(ROOT / "assets/client-templates/reference/protocol-reference.docx")
    for title in ("3. GENERAL INFORMATION", "16. CONFIDENTIALITY"):
        heading = next(
            paragraph for paragraph in protocol.paragraphs
            if paragraph.text.strip() == title
        )
        authority_heading = next(
            paragraph for paragraph in authority.paragraphs
            if " ".join(paragraph.text.split()) == title
        )
        assert heading.paragraph_format.page_break_before is not True
        assert _paragraph_rhythm(heading) == _paragraph_rhythm(authority_heading)
    toc_index = next(
        index for index, paragraph in enumerate(protocol.paragraphs)
        if paragraph.text.strip() == "4. TABLE OF CONTENTS"
    )
    body_headings = [
        paragraph for paragraph in protocol.paragraphs[toc_index + 1:]
        if paragraph.style.name.casefold().startswith("heading")
    ]
    assert all(paragraph.paragraph_format.page_break_before is not True for paragraph in body_headings)


def test_every_protocol_and_icf_family_uses_natural_body_pagination(tmp_path):
    cases = (
        ("prospective-acceptance-source.json", "Advarra"),
        ("prospective-acceptance-source.json", "Sterling"),
        ("ambispective-acceptance-source.json", "Advarra"),
        ("ambispective-acceptance-source.json", "Sterling"),
        ("retrospective-acceptance-source.json", None),
    )
    for fixture_name, icf_family in cases:
        reference = json.loads((ROOT / "tests/fixtures" / fixture_name).read_text(encoding="utf-8"))
        if icf_family is not None:
            reference["meta"]["icf_template"] = icf_family
        output = tmp_path / f"{reference['meta']['study_type']}-{icf_family or 'none'}"

        document_report = render_documents(ROOT, output, reference, {"protocol": [], "icf": {}, "prs": {}})
        render_report = render_pages(output)

        assert document_report["status"] == "passed"
        assert render_report["status"] == "passed"
        expected_artifacts = {"protocol", "icf"} if icf_family is not None else {"protocol"}
        assert {artifact["artifact"] for artifact in render_report["artifacts"]} == expected_artifacts
        assert all(
            page["sha256"] == sha256_file(output / page["path"])
            for artifact in render_report["artifacts"]
            for page in artifact["pages"]
        )

        protocol = Document(output / "candidate/protocol.docx")
        rendered_protocol = next(artifact for artifact in render_report["artifacts"] if artifact["artifact"] == "protocol")
        protocol_pages = [
            " ".join((page.extract_text() or "").split())
            for page in PdfReader(output / rendered_protocol["pdf"]).pages
        ]
        protocol_number = reference["meta"]["protocol_number"]
        assert all(protocol_number in page and "Page" in page for page in protocol_pages)
        assert "1. TITLE PAGE" in protocol_pages[0]
        toc_heading = next(
            paragraph.text.strip() for paragraph in protocol.paragraphs
            if "TABLE OF CONTENTS" in paragraph.text
            and paragraph.style.name.casefold().startswith("heading")
        )
        introduction_heading = next(
            paragraph.text.strip() for paragraph in protocol.paragraphs
            if "INTRODUCTION" in paragraph.text
            and paragraph.style.name.casefold().startswith("heading")
        )
        toc_page = next(index for index, page in enumerate(protocol_pages) if toc_heading in page)
        assert toc_page > 0
        assert any(
            index > toc_page and introduction_heading in page
            for index, page in enumerate(protocol_pages)
        )
        sparse_pages = [page for page in protocol_pages if len(page.split()) < 50]
        assert all("Duration / Follow- up" in page for page in sparse_pages)
        if any("Table 9.2-1. Visit Schedule" in paragraph.text for paragraph in protocol.paragraphs):
            assert any(
                "Table 9.2-1. Visit Schedule" in page
                and "Visit Number Visit Name Visit Window CRF Number" in page
                for page in protocol_pages
            )
        if any("Table 13.3.-1" in paragraph.text for paragraph in protocol.paragraphs):
            assert any(
                "Table 13.3.-1" in page
                and "Study Staff Business Phone e-mail 24-hour Office Phone" in page
                for page in protocol_pages
            )
        general_information = next((
            paragraph.text.strip() for paragraph in protocol.paragraphs
            if "GENERAL INFORMATION" in paragraph.text
            and paragraph.style.name.casefold().startswith("heading")
        ), None)
        if general_information is not None:
            section_three_page = next(
                page for page in protocol_pages
                if general_information in page and toc_heading not in page
            )
            assert "2. INVESTIGATOR AGREEMENT" in section_three_page
            assert len(section_three_page.split()) >= 100
        numbered_body_headings = [
            paragraph
            for paragraph in protocol.paragraphs
            if paragraph.style.name.casefold().startswith("heading")
            and re.match(r"^\d+(?:\.\d+)*\.?\s+", paragraph.text.strip())
            and "TITLE PAGE" not in paragraph.text
            and "TABLE OF CONTENTS" not in paragraph.text
        ]
        assert numbered_body_headings
        body = list(protocol.element.body)
        normalized_pages = [re.sub(r"[^a-z0-9]+", " ", page.casefold()).strip() for page in protocol_pages]
        for heading in numbered_body_headings:
            heading_index = body.index(heading._p)
            first_content = None
            for element in body[heading_index + 1:]:
                if element.tag == qn("w:tbl"):
                    table = Table(element, protocol)
                    first_content = " ".join(cell.text for cell in table.rows[0].cells) if table.rows else ""
                    break
                if element.tag != qn("w:p"):
                    continue
                paragraph = Paragraph(element, protocol)
                if paragraph.style.name.casefold().startswith("heading"):
                    break
                if paragraph.text.strip():
                    first_content = paragraph.text
                    break
            if not first_content:
                continue
            heading_marker = " ".join(re.findall(r"[a-z0-9]+", heading.text.casefold()))
            content_marker = " ".join(re.findall(r"[a-z0-9]+", first_content.casefold())[:4])
            assert any(
                heading_marker in page
                and content_marker in page[page.index(heading_marker) + len(heading_marker):]
                for page in normalized_pages
            ), f"Rendered heading is orphaned from first content: {heading.text}"
        assert all(paragraph.paragraph_format.page_break_before is not True for paragraph in numbered_body_headings)
        assert all(
            paragraph.paragraph_format.keep_with_next is True
            or paragraph.style.paragraph_format.keep_with_next is True
            for paragraph in numbered_body_headings
        )
        long_body = next(
            paragraph
            for paragraph in sorted(protocol.paragraphs, key=lambda item: len(item.text), reverse=True)
            if len(paragraph.text) > 200 and not paragraph.style.name.casefold().startswith("heading")
        )
        assert long_body.paragraph_format.keep_together is not True

        if icf_family is not None:
            icf = Document(output / "candidate/icf.docx")
            rendered_icf = next(artifact for artifact in render_report["artifacts"] if artifact["artifact"] == "icf")
            icf_pages = [
                " ".join((page.extract_text() or "").split())
                for page in PdfReader(output / rendered_icf["pdf"]).pages
            ]
            assert all(protocol_number in page and "Page" in page for page in icf_pages)
            assert all(len(page.split()) >= 50 for page in icf_pages)
            icf_headings = [
                paragraph
                for paragraph in icf.paragraphs
                if paragraph.style.name == "Heading ICF Section"
            ]
            assert icf_headings
            assert all(paragraph.paragraph_format.keep_with_next is True for paragraph in icf_headings)


def test_protocol_headings_keep_their_first_content_and_front_matter_boundaries(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/ambispective-acceptance-source.json").read_text(encoding="utf-8"))

    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})

    protocol = Document(tmp_path / "candidate/protocol.docx")
    headings = [
        paragraph for paragraph in protocol.paragraphs
        if paragraph.style.name.casefold().startswith("heading")
    ]
    assert headings
    assert all(
        paragraph.paragraph_format.keep_with_next is True
        or paragraph.style.paragraph_format.keep_with_next is True
        for paragraph in headings
    )
    summary_heading = next(
        paragraph for paragraph in headings
        if paragraph.text.strip() == "3. GENERAL INFORMATION"
    )
    summary_index = list(protocol.element.body).index(summary_heading._p)
    assert list(protocol.element.body)[summary_index + 1].tag == qn("w:tbl")

    title_heading = next(paragraph for paragraph in headings if paragraph.text.strip() == "1. TITLE PAGE")
    toc_heading = next(paragraph for paragraph in headings if paragraph.text.strip() == "4. TABLE OF CONTENTS")
    assert title_heading._p.xpath('following::w:br[@w:type="page"]')
    assert toc_heading._p.xpath('preceding::w:br[@w:type="page"]')

    visits_heading = next(
        paragraph for paragraph in headings
        if paragraph.text.strip().startswith("9.2. Visits and Examinations")
    )
    body = list(protocol.element.body)
    visits_index = body.index(visits_heading._p)
    table_index = next(
        index for index in range(visits_index + 1, len(body))
        if body[index].tag == qn("w:tbl")
    )
    protected_chain = [Paragraph(body[index], protocol) for index in range(visits_index, table_index)]
    assert all(paragraph.paragraph_format.keep_with_next is True for paragraph in protected_chain)


def test_rendered_ambispective_section_three_flows_after_investigator_agreement(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/ambispective-acceptance-source.json").read_text(encoding="utf-8"))
    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})

    report = render_pages(tmp_path)

    assert report["status"] == "passed"
    protocol = next(item for item in report["artifacts"] if item["artifact"] == "protocol")
    assert protocol["docx_sha256"] == sha256_file(tmp_path / protocol["docx"])
    assert protocol["pdf_sha256"] == sha256_file(tmp_path / protocol["pdf"])
    assert all(page["sha256"] == sha256_file(tmp_path / page["path"]) for page in protocol["pages"])
    pages = [" ".join((page.extract_text() or "").split()) for page in PdfReader(tmp_path / protocol["pdf"]).pages]
    section_three_page = next(text for text in pages if "3. GENERAL INFORMATION" in text)
    section_sixteen_page = next(text for text in pages if "16. CONFIDENTIALITY" in text)
    visits_heading_page = next(
        text for text in pages
        if "9.2. Visits and Examinations" in text and "4. TABLE OF CONTENTS" not in text
    )
    title_page = next(text for text in pages if "1. TITLE PAGE" in text)
    toc_page = next(text for text in pages if "4. TABLE OF CONTENTS" in text)
    assert "2. INVESTIGATOR AGREEMENT" not in title_page
    assert "Sample size 40 participants" not in toc_page
    assert "2. INVESTIGATOR AGREEMENT" in section_three_page
    assert "Objective" in section_three_page
    assert len(section_three_page.split()) >= 120
    assert "15. STANDARD EVALUATION PROCEDURES" in section_sixteen_page
    assert "Table 9.2-1. Visit Schedule" in visits_heading_page


def test_content_gate_rejects_same_section_duplicates_and_flattened_schedule_prose(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/retrospective-acceptance-source.json").read_text(encoding="utf-8"))
    duplicate = "The analysis data sets will be organized around the approved outcome summaries."
    raw_schedule = (
        "For informed consent / subject enrollment, the approved visit schedule table is "
        "BL; Baseline; 1; Day 0; M3; Month 3; 2; Day 90 +/- 7."
    )
    model = {
        "protocol": [
            {"section_id": "study-procedure.enrollment", "paragraphs": [{"text": raw_schedule}], "lists": []},
            {
                "section_id": "analysis-plan.datasets",
                "paragraphs": [{"text": duplicate}, {"text": duplicate}],
                "lists": [],
            },
        ],
        "icf": {},
        "prs": {},
    }
    render_documents(ROOT, tmp_path, reference, model)

    findings = deterministic_content_check(tmp_path, reference)

    issues = "\n".join(item["issue"] for item in findings)
    assert "duplicated in protocol section analysis-plan.datasets" in issues
    assert "flattened visit-schedule serialization" in issues


def test_generated_documents_retain_client_typography_and_section_rhythm(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/ambispective-acceptance-source.json").read_text(encoding="utf-8"))
    protocol_text = "The approved analysis population includes source-supported study records and observations."
    risk_text = "Taking part may involve only the source-supported study risks described here."
    model = {
        "protocol": [{
            "section_id": "analysis-plan.datasets",
            "paragraphs": [{"text": protocol_text, "evidence_refs": [], "boilerplate_refs": []}],
            "lists": [],
        }],
        "icf": {
            "icf.risks": {
                "paragraphs": [{"text": risk_text, "evidence_refs": [], "boilerplate_refs": []}],
                "lists": [],
            }
        },
        "prs": {},
    }

    render_documents(ROOT, tmp_path, reference, model)

    protocol_path = tmp_path / "candidate/protocol.docx"
    protocol = Document(protocol_path)
    protocol_reference_path = ROOT / "assets/client-templates/reference/protocol-reference.docx"
    protocol_reference = Document(protocol_reference_path)
    assert _doc_default_font(protocol_path) == _doc_default_font(protocol_reference_path)
    assert protocol.styles["Normal"].font.size == protocol_reference.styles["Normal"].font.size
    protocol_body = next(paragraph for paragraph in protocol.paragraphs if paragraph.text == protocol_text)
    reference_analysis_index = next(
        index for index, paragraph in enumerate(protocol_reference.paragraphs)
        if paragraph.text.strip().startswith("10.1. Analysis Data Sets")
        and paragraph.style.name.casefold().startswith("heading")
    )
    reference_protocol_body = next(
        paragraph for paragraph in protocol_reference.paragraphs[reference_analysis_index + 1:]
        if paragraph.text.strip()
    )
    assert protocol_body.style.style_id == reference_protocol_body.style.style_id
    assert _paragraph_rhythm(protocol_body) == _paragraph_rhythm(reference_protocol_body)
    assert _run_typography(protocol_body) == _run_typography(reference_protocol_body)

    icf_path = tmp_path / "candidate/icf.docx"
    icf_reference_path = ROOT / "assets/client-templates/reference/advarra-icf-reference.docx"
    icf = Document(icf_path)
    icf_reference = Document(icf_reference_path)
    assert _doc_default_font(icf_path) == _doc_default_font(icf_reference_path)
    heading_text = "SIDE EFFECTS AND OTHER RISKS"
    output_heading_index = next(index for index, paragraph in enumerate(icf.paragraphs) if paragraph.text.strip() == heading_text)
    reference_heading_index = next(
        index for index, paragraph in enumerate(icf_reference.paragraphs) if paragraph.text.strip() == heading_text
    )
    output_heading = icf.paragraphs[output_heading_index]
    reference_heading = icf_reference.paragraphs[reference_heading_index]
    output_spacer = icf.paragraphs[output_heading_index + 1]
    reference_spacer = icf_reference.paragraphs[reference_heading_index + 1]
    output_body = next(paragraph for paragraph in icf.paragraphs[output_heading_index + 1:] if paragraph.text.strip())
    reference_body = next(
        paragraph for paragraph in icf_reference.paragraphs[reference_heading_index + 1:] if paragraph.text.strip()
    )

    assert output_body.text == risk_text
    assert not output_spacer.text.strip()
    assert _paragraph_rhythm(output_spacer) == _paragraph_rhythm(reference_spacer)
    assert output_heading.style.name == "Heading ICF Section"
    assert output_heading.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.LEFT
    assert _points(output_heading.paragraph_format.right_indent) in (None, 0)
    assert _points(output_heading.paragraph_format.left_indent) == _points(reference_heading.paragraph_format.left_indent)
    assert _points(output_heading.paragraph_format.space_after) == _points(reference_heading.paragraph_format.space_after)
    assert _paragraph_rhythm(output_body) == _paragraph_rhythm(reference_body)
    assert output_body.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.LEFT
    assert _run_typography(output_heading) == _run_typography(reference_heading)
    assert _run_typography(output_body) == _run_typography(reference_body)


def test_protocol_investigator_agreement_uses_client_intro_and_bullet_designs(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/ambispective-acceptance-source.json").read_text(encoding="utf-8"))
    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})

    output = Document(tmp_path / "candidate/protocol.docx")
    authority = Document(ROOT / "assets/client-templates/reference/protocol-reference.docx")
    output_heading_index = next(
        index for index, paragraph in enumerate(output.paragraphs)
        if "INVESTIGATOR AGREEMENT" in paragraph.text and paragraph.style.name.casefold().startswith("heading")
    )
    authority_heading_index = next(
        index for index, paragraph in enumerate(authority.paragraphs)
        if "INVESTIGATOR AGREEMENT" in paragraph.text and paragraph.style.name.casefold().startswith("heading")
    )
    output_body = [paragraph for paragraph in output.paragraphs[output_heading_index + 1:] if paragraph.text.strip()][:4]
    authority_body = [paragraph for paragraph in authority.paragraphs[authority_heading_index + 1:] if paragraph.text.strip()][:4]

    assert len(output_body) == len(authority_body) == 4
    assert _paragraph_rhythm(output_body[0]) == _paragraph_rhythm(authority_body[0])
    assert _run_typography(output_body[0]) == _run_typography(authority_body[0])
    assert all(paragraph._p.get_or_add_pPr().find(qn("w:numPr")) is not None for paragraph in output_body[1:])
    assert all(_run_typography(output_body[index]) == _run_typography(authority_body[index]) for index in range(1, 4))
    assert all(
        _numbering_level_signature(output, output_body[index])
        == _numbering_level_signature(authority, authority_body[index])
        for index in range(1, 4)
    )


def test_protocol_signature_block_retains_client_completion_lines(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/ambispective-acceptance-source.json").read_text(encoding="utf-8"))
    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})

    output = Document(tmp_path / "candidate/protocol.docx")
    authority = Document(ROOT / "assets/client-templates/reference/protocol-reference.docx")
    output_table = next(
        table for table in output.tables
        if any("Signature of Investigator" in cell.text for row in table.rows for cell in row.cells)
    )
    authority_table = next(
        table for table in authority.tables
        if any("Signature of Investigator" in cell.text for row in table.rows for cell in row.cells)
    )

    output_text = " ".join(cell.text for row in output_table.rows for cell in row.cells)
    assert "Alex Investigator" in output_text
    assert "MD" in output_text
    assert "Site One" in output_text
    assert output_table.style.style_id == authority_table.style.style_id
    assert [column.w for column in output_table._tbl.tblGrid.gridCol_lst] == [
        column.w for column in authority_table._tbl.tblGrid.gridCol_lst
    ]


def test_protocol_omits_empty_references_section_without_inventing_citations(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/ambispective-acceptance-source.json").read_text(encoding="utf-8"))
    reference.pop("references", None)
    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})

    output = Document(tmp_path / "candidate/protocol.docx")
    visible = "\n".join(paragraph.text for paragraph in output.paragraphs)
    assert "REFERENCES" not in visible
    assert "Source of Truth" not in visible


def test_sterling_icf_removes_template_review_highlighting(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    reference["meta"]["icf_template"] = "Sterling"
    model = {"protocol": [], "prs": {}, "icf": {
        "icf.risks": {"paragraphs": [{"text": "Authorized sparse risk text."}], "lists": []},
        "icf.benefits": {"paragraphs": [{"text": "Authorized benefit text."}], "lists": []},
        "icf.alternatives": {"paragraphs": [{"text": "Authorized alternatives text."}], "lists": []},
        "icf.costs": {"paragraphs": [{"text": "Authorized cost text."}], "lists": []},
    }}
    render_documents(ROOT, tmp_path, reference, model)

    output = Document(tmp_path / "candidate/icf.docx")
    runs = [run for paragraph in output.paragraphs for run in paragraph.runs]

    assert all(run.font.highlight_color is None for run in runs)


def test_protocol_running_header_uses_concise_title_and_nonwrapping_page_control(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/ambispective-acceptance-source.json").read_text(encoding="utf-8"))
    reference["study"].pop("short_title", None)
    reference["study"]["title"] = "Ambispective Evaluation of the Sentinel Patch in Adults With Postoperative Pain"
    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})

    output = Document(tmp_path / "candidate/protocol.docx")
    header = output.sections[0].header.tables[0]
    assert header.cell(0, 0).text.strip() == "Sentinel Patch in Adults With Postoperative Pain"
    assert header.cell(0, 1)._tc.tcPr.find(qn("w:noWrap")) is not None
    page_control = header.cell(0, 1).paragraphs[0]
    assert "PAGE" in page_control._p.xml
    assert "NUMPAGES" in page_control._p.xml
    assert not page_control._p.xpath('.//w:br')


def test_protocol_cached_toc_uses_client_dot_leaders_and_subsection_indent(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/ambispective-acceptance-source.json").read_text(encoding="utf-8"))
    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})
    protocol_path = tmp_path / "candidate/protocol.docx"
    pdf_path = tmp_path / "protocol.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    assert refresh_toc_from_pdf(protocol_path, pdf_path) is True
    output = Document(protocol_path)
    authority = Document(ROOT / "assets/client-templates/reference/protocol-reference.docx")
    toc_rows = [paragraph for paragraph in output.paragraphs if paragraph.style.name.casefold() in {"toc 1", "toc 2"}]
    heading_one = next(paragraph for paragraph in toc_rows if paragraph.text.strip().startswith("7. SUBJECTS"))
    heading_two = next(paragraph for paragraph in toc_rows if paragraph.text.strip().startswith("7.1."))
    assert _points(heading_one.paragraph_format.left_indent) == _points(authority.styles["toc 1"].paragraph_format.left_indent)
    assert _points(heading_two.paragraph_format.left_indent) == _points(authority.styles["toc 2"].paragraph_format.left_indent)
    assert "\t" not in heading_one.text
    assert "......" in heading_one.text
    assert 'TOC \\o "1-2"' not in "\n".join(paragraph._p.xml for paragraph in toc_rows)
    assert not any(
        [cell.text.strip() for cell in table.rows[0].cells] == ["Section", "Page"]
        for table in output.tables
    )


def test_protocol_duplicate_titles_and_table_sections_use_client_body_design(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/ambispective-acceptance-source.json").read_text(encoding="utf-8"))
    safety_text = "Source-supported general safety information appears in this section."
    assessment_text = "Source-supported assessment information introduces the schedule table."
    model = {
        "protocol": [
            {"section_id": "quality-safety.general", "paragraphs": [{"text": safety_text}], "lists": []},
            {"section_id": "evaluation-procedures", "paragraphs": [{"text": assessment_text}], "lists": []},
        ],
        "icf": {},
        "prs": {},
    }
    render_documents(ROOT, tmp_path, reference, model)

    output = Document(tmp_path / "candidate/protocol.docx")
    authority = Document(ROOT / "assets/client-templates/reference/protocol-reference.docx")
    authority_heading_index = next(
        index for index, paragraph in enumerate(authority.paragraphs)
        if paragraph.text.strip().startswith("9.1. Informed Consent")
        and paragraph.style.name.casefold().startswith("heading")
    )
    authority_body = next(
        paragraph for paragraph in authority.paragraphs[authority_heading_index + 1:]
        if paragraph.text.strip()
    )

    for text in (safety_text, assessment_text):
        paragraph = next(item for item in output.paragraphs if item.text == text)
        assert paragraph.style.style_id == authority_body.style.style_id
        assert _paragraph_rhythm(paragraph) == _paragraph_rhythm(authority_body)
        assert _run_typography(paragraph) == _run_typography(authority_body)
