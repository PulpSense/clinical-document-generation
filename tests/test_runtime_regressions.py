import copy
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from contracts import contracted_template_bundle
from quality import RESPONSE_SCHEMA, validate_verifications, verification_request_sha256
import quality
from rendering import render_documents
import rendering
from prs_xml import generate as generate_xml
import workflow


ROOT = Path(__file__).resolve().parents[1]


def _source():
    return json.loads(
        (
            ROOT
            / "tests/fixtures/release-certification/prospective-advarra/approved-reference.json"
        ).read_text(encoding="utf-8")
    )


def _visible(document):
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    cells = [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    return "\n".join(paragraphs + cells)


def _page_identity():
    return {
        "kind": "pypdfium2",
        "path": "python:pypdfium2",
        "module": "pypdfium2",
        "python_path": "/release/runtime/python",
        "source": "release-owned runtime",
    }


def test_renderer_preflight_reports_missing_host_office_when_no_renderer_exists(tmp_path, monkeypatch):
    reference = _source()
    monkeypatch.setattr(quality, "renderers", lambda **_: [])
    report = quality.preflight(ROOT, reference, deadline_seconds=2)

    assert report["status"] == "blocked"
    assert report["smoke"]["status"] == "blocked"
    assert any("renderer" == finding["field"] for finding in report["findings"])


def test_renderer_preflight_records_renderer_font_and_smoke_evidence(tmp_path, monkeypatch):
    reference = _source()
    identity = {"kind": "LibreOffice", "path": "/usr/bin/soffice", "version": "test", "platform": "Linux"}
    page_identity = _page_identity()
    monkeypatch.setattr(quality, "renderers", lambda **_: [identity])
    monkeypatch.setattr(quality, "page_renderers", lambda **_: [page_identity])
    monkeypatch.setattr(quality, "_font_probe", lambda *_args, **_kwargs: (True, "test-font"))

    def fake_export(_docx, output_dir, _identity, **_kwargs):
        from pypdf import PdfWriter
        output = output_dir / "preflight.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with output.open("wb") as handle:
            writer.write(handle)
        return output

    monkeypatch.setattr(quality, "_render_pdf", fake_export)

    def fake_rasterize(_pdf, output_dir, _identity, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        page = output_dir / "page.png"
        page.write_bytes(b"png")
        return [page]

    monkeypatch.setattr(quality, "rasterize_pdf", fake_rasterize)
    report = quality.preflight(ROOT, reference, deadline_seconds=10)

    assert report["status"] == "passed"
    assert report["renderer"] == identity
    assert report["elapsed_seconds"] < report["deadline_seconds"]
    assert report["smoke"] == {"status": "passed", "pdf": "disposable/preflight.pdf", "page_image": "disposable/preflight.png", "pages": 1}


def test_page_renderer_has_one_governed_backend_and_ignores_host_tools(tmp_path):
    assert quality.PAGE_RENDERER_BACKENDS == ("pypdfium2",)
    assert quality.page_renderer(
        environment={"PATH": "/usr/bin:/opt/homebrew/bin"},
        home=tmp_path,
        skill_root=tmp_path,
    ) is None


def test_pdfium_identity_filter_rejects_ambient_interpreter_identity(tmp_path):
    runtime_python = tmp_path / "runtime/python"
    governed = {
        "kind": "pypdfium2",
        "path": "python:pypdfium2",
        "module": "pypdfium2",
        "python_path": str(runtime_python),
        "source": "release-owned runtime",
    }

    assert quality._one_pdfium_renderer([
        {"kind": "pypdfium2", "path": "python:pypdfium2"},
        governed,
    ]) == [governed]


def test_rasterize_pdf_rejects_ambient_pdfium_before_import(tmp_path):
    with pytest.raises(RuntimeError, match="manifest-verified release-owned runtime"):
        quality.rasterize_pdf(
            tmp_path / "unused.pdf",
            tmp_path / "pages",
            {"kind": "pypdfium2", "path": "python:pypdfium2"},
        )


def test_rasterize_pdf_verifies_against_the_current_release_root(
    tmp_path,
    monkeypatch,
    governed_pdfium,
):
    observed_roots = []

    def observe_release_root(_identities, *, skill_root, **_kwargs):
        observed_roots.append(Path(skill_root).resolve())
        return []

    monkeypatch.setattr(quality, "_one_pdfium_renderer", observe_release_root)

    with pytest.raises(RuntimeError, match="manifest-verified release-owned runtime"):
        quality.rasterize_pdf(
            tmp_path / "unused.pdf",
            tmp_path / "pages",
            governed_pdfium,
        )

    assert observed_roots == [ROOT.resolve()]


def test_renderer_discovery_ignores_a_release_local_office_suite(tmp_path, monkeypatch):
    bundled = tmp_path / "runtime/LibreOffice/program/soffice"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("#!/bin/sh\nprintf 'LibreOffice test\\n'\n", encoding="utf-8")
    bundled.chmod(0o755)
    monkeypatch.setattr(quality.platform, "system", lambda: "Linux")
    monkeypatch.setattr(quality, "_executable_candidates", lambda *_args, **_kwargs: iter(()))

    assert quality.renderers(skill_root=tmp_path) == []


def test_renderer_preflight_uses_the_selected_page_renderer(tmp_path, monkeypatch):
    reference = _source()
    renderer_identity = {"kind": "LibreOffice", "path": "/usr/bin/soffice", "version": "test", "platform": "Linux"}
    page_renderer_identity = _page_identity()
    monkeypatch.setattr(quality, "renderers", lambda **_: [renderer_identity])
    monkeypatch.setattr(quality, "page_renderers", lambda **_: [page_renderer_identity])
    monkeypatch.setattr(quality, "_font_probe", lambda *_args, **_kwargs: (True, "test-font"))

    def fake_export(_docx, output_dir, _identity, **_kwargs):
        from pypdf import PdfWriter
        output = output_dir / "preflight.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with output.open("wb") as handle:
            writer.write(handle)
        return output

    def fake_rasterize(_pdf, output_dir, identity, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        page = output_dir / "page.png"
        page.write_bytes(b"png")
        assert identity == page_renderer_identity
        return [page]

    monkeypatch.setattr(quality, "_render_pdf", fake_export)
    monkeypatch.setattr(quality, "rasterize_pdf", fake_rasterize)

    report = quality.preflight(ROOT, reference, deadline_seconds=10)

    assert report["status"] == "passed"
    assert report["page_renderer"] == page_renderer_identity
    assert report["smoke"]["status"] == "passed"


def test_renderer_preflight_stops_when_the_release_owned_pdfium_fails(monkeypatch):
    renderer_identity = {"kind": "LibreOffice", "path": "/usr/bin/soffice", "version": "test", "platform": "Linux"}
    word_identity = {"kind": "Microsoft Word", "path": "/Applications/Microsoft Word.app", "platform": "Darwin"}
    broken = _page_identity()
    unapproved = {"kind": "pdftoppm", "path": "/usr/bin/pdftoppm", "source": "PATH"}
    attempts = []
    monkeypatch.setattr(quality, "renderers", lambda **_: [renderer_identity, word_identity])
    monkeypatch.setattr(quality, "page_renderers", lambda **_: [broken, unapproved])
    monkeypatch.setattr(quality, "_font_probe", lambda *_args, **_kwargs: (True, "test-font"))

    def fake_export(_docx, output_dir, _identity, **_kwargs):
        from pypdf import PdfWriter
        output = output_dir / "preflight.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with output.open("wb") as handle:
            writer.write(handle)
        return output

    def fake_rasterize(_pdf, output_dir, identity, **_kwargs):
        attempts.append(identity["kind"])
        raise RuntimeError("controlled PDFium failure")

    monkeypatch.setattr(quality, "_render_pdf", fake_export)
    monkeypatch.setattr(quality, "rasterize_pdf", fake_rasterize)

    report = quality.preflight(ROOT, _source(), deadline_seconds=10)

    assert report["status"] == "blocked"
    assert attempts == ["pypdfium2"]
    assert report["page_renderer"] is None
    assert report["page_renderer_attempts"] == [
        {"renderer": broken, "status": "failed", "issue": "controlled PDFium failure"},
    ]
    assert len(report["renderer_attempts"]) == 1


def test_renderer_preflight_uses_a_packaged_font_when_host_fonts_are_missing(monkeypatch):
    identity = {"kind": "LibreOffice", "path": "/usr/bin/soffice", "version": "test", "platform": "Linux"}
    page_identity = _page_identity()
    monkeypatch.setattr(quality, "renderers", lambda **_: [identity])
    monkeypatch.setattr(quality, "page_renderers", lambda **_: [page_identity])
    monkeypatch.setattr(quality, "_template_fonts", lambda _path: {"Missing Client Font"})
    monkeypatch.setattr(quality, "_font_probe", lambda *_args, **_kwargs: (False, "not installed"))

    def fake_export(_docx, output_dir, _identity, **_kwargs):
        from pypdf import PdfWriter
        output = output_dir / "preflight.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with output.open("wb") as handle:
            writer.write(handle)
        return output

    def fake_rasterize(_pdf, output_dir, _identity, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        page = output_dir / "page.png"
        page.write_bytes(b"png")
        return [page]

    monkeypatch.setattr(quality, "_render_pdf", fake_export)
    monkeypatch.setattr(quality, "rasterize_pdf", fake_rasterize)

    report = quality.preflight(ROOT, _source(), deadline_seconds=10)

    assert report["status"] == "passed"
    assert report["smoke"]["status"] == "passed"
    assert report["required_fonts"] == ["Missing Client Font"]
    assert report["font_substitutions"] == {"Missing Client Font": "Liberation Sans"}


def test_every_current_template_font_has_an_explicit_packaged_fallback():
    required = {
        font
        for template in (ROOT / "assets/client-templates/reference").glob("*.docx")
        for font in quality._template_fonts(template)
    }

    assert required
    assert not {
        font for font in required
        if font.casefold() not in quality.APPROVED_PACKAGED_FONT_FALLBACKS
    }


def test_renderer_preflight_uses_only_the_approved_packaged_font_for_a_missing_client_font(monkeypatch):
    identity = {"kind": "LibreOffice", "path": "/verified/soffice", "version": "test", "platform": "Darwin", "source": "host prerequisite"}
    page_identity = _page_identity()
    probes = {
        "Noto Sans Symbols": (False, "not installed"),
        "Apple Symbols": (True, "macOS system font inventory"),
    }
    monkeypatch.setattr(quality, "renderers", lambda **_: [identity])
    monkeypatch.setattr(quality, "page_renderers", lambda **_: [page_identity])
    monkeypatch.setattr(quality, "_template_fonts", lambda _path: {"Noto Sans Symbols"})
    monkeypatch.setattr(quality, "_font_probe", lambda font, **_kwargs: probes.get(font, (False, "not installed")))

    def fake_export(_docx, output_dir, _identity, **_kwargs):
        from pypdf import PdfWriter
        output = output_dir / "preflight.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with output.open("wb") as handle:
            writer.write(handle)
        return output

    monkeypatch.setattr(quality, "_render_pdf", fake_export)

    def fake_rasterize(_pdf, output_dir, _identity, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        page = output_dir / "page.png"
        page.write_bytes(b"png")
        return [page]

    monkeypatch.setattr(quality, "rasterize_pdf", fake_rasterize)

    report = quality.preflight(ROOT, _source(), deadline_seconds=10)

    assert report["status"] == "passed"
    assert report["required_fonts"] == ["Noto Sans Symbols"]
    assert report["font_substitutions"] == {"Noto Sans Symbols": "Liberation Sans"}
    assert report["fonts"]["Noto Sans Symbols"] == {
        "available": False,
        "match": "not installed",
        "substitute": "Liberation Sans",
        "substitute_match": "bundled approved compatible font: assets/fallback-fonts/LiberationSans-Regular.ttf",
    }
    assert report["smoke"]["status"] == "passed"


def test_macos_renderer_honors_the_callers_remaining_deadline(tmp_path, monkeypatch):
    source = tmp_path / "source.docx"
    source.write_bytes(b"docx")
    observed = []

    def fake_run(_command, **kwargs):
        observed.append(kwargs["timeout"])
        (tmp_path / "source.pdf").write_bytes(b"pdf")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(quality.subprocess, "run", fake_run)

    quality._render_pdf(
        source,
        tmp_path,
        {"kind": "Microsoft Word", "path": "/Applications/Microsoft Word.app", "platform": "Darwin"},
        timeout_seconds=7.5,
    )

    assert observed == [7.5]


def test_layout_repair_is_scoped_to_one_artifact_and_rule(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    model = {"protocol": [], "icf": {}, "prs": {}}

    baseline = render_documents(ROOT, tmp_path, reference, model)
    icf_before = (tmp_path / "candidate/icf.docx").read_bytes()
    baseline_protocol = Document(tmp_path / "candidate/protocol.docx")
    unaffected_paragraphs_before = tuple(
        paragraph._p.xml
        for paragraph in baseline_protocol.paragraphs
        if paragraph.text.strip() != "5. INTRODUCTION"
    )
    unaffected_tables_before = tuple(table._tbl.xml for table in baseline_protocol.tables)
    geometry_before = _visible_formatting_fingerprint(tmp_path / "candidate/protocol.docx")[1:]
    with zipfile.ZipFile(tmp_path / "candidate/protocol.docx") as package:
        protocol_xml_before = package.read("word/document.xml")
    repaired = render_documents(
        ROOT,
        tmp_path,
        reference,
        model,
        artifact_names={"protocol"},
        layout_repairs={"protocol": ({"rule": "heading_cohesion", "target": "5. INTRODUCTION"},)},
    )

    assert baseline["status"] == repaired["status"] == "passed"
    assert [item["artifact"] for item in repaired["artifacts"]] == ["protocol"]
    assert repaired["layout_repairs"] == {
        "protocol": [{"rule": "heading_cohesion", "target": "5. INTRODUCTION"}],
    }
    assert "layout_repair" not in repaired
    assert (tmp_path / "candidate/icf.docx").read_bytes() == icf_before
    with zipfile.ZipFile(tmp_path / "candidate/protocol.docx") as package:
        assert package.read("word/document.xml") != protocol_xml_before
    repaired_protocol = Document(tmp_path / "candidate/protocol.docx")
    assert tuple(
        paragraph._p.xml
        for paragraph in repaired_protocol.paragraphs
        if paragraph.text.strip() != "5. INTRODUCTION"
    ) == unaffected_paragraphs_before
    assert tuple(table._tbl.xml for table in repaired_protocol.tables) == unaffected_tables_before
    assert _visible_formatting_fingerprint(tmp_path / "candidate/protocol.docx")[1:] == geometry_before
    assert repaired["contracted_template_bundle"]["layout_preservation_baseline"] == baseline["contracted_template_bundle"]["layout_preservation_baseline"]


def test_artificial_pagination_fails_closed_instead_of_removing_template_breaks():
    finding = {
        "category": "visual",
        "artifact": "protocol",
        "check": "artificial_pagination",
        "element": "15. REFERENCES",
        "target_ids": ["layout:protocol"],
        "issue": "A later template-owned heading starts on a new page.",
    }

    plan, unsupported = workflow._layout_repair_plan([finding])

    assert plan == {}
    assert unsupported == [{
        **finding,
        "required": "Classify the visual defect with one supported artifact, Layout Contract check, and exact heading or table-caption element before deterministic repair.",
    }]


def test_excessive_whitespace_at_exact_heading_uses_scoped_cohesion_repair():
    finding = {
        "category": "visual",
        "artifact": "icf",
        "check": "excessive_whitespace",
        "element": "DURATION",
        "target_ids": ["layout:icf"],
        "issue": "A large vertical gap separates DURATION from its first substantive paragraph.",
    }

    plan, unsupported = workflow._layout_repair_plan([finding], icf_template="Sterling")

    assert plan == {"icf": [{"rule": "heading_whitespace_cohesion", "target": "DURATION"}]}
    assert unsupported == []


def test_excessive_whitespace_at_other_sterling_heading_remains_non_destructive():
    finding = {
        "category": "visual",
        "artifact": "icf",
        "check": "excessive_whitespace",
        "element": "RISKS",
        "target_ids": ["layout:icf"],
        "issue": "A large vertical gap follows an unrelated ICF heading.",
    }

    plan, unsupported = workflow._layout_repair_plan([finding], icf_template="Sterling")

    assert plan == {"icf": [{"rule": "heading_cohesion", "target": "RISKS"}]}
    assert unsupported == []


def test_excessive_whitespace_at_advarra_duration_remains_non_destructive():
    finding = {
        "category": "visual",
        "artifact": "icf",
        "check": "excessive_whitespace",
        "element": "DURATION",
        "target_ids": ["layout:icf"],
        "issue": "A large vertical gap follows an Advarra ICF heading.",
    }

    plan, unsupported = workflow._layout_repair_plan([finding], icf_template="Advarra")

    assert plan == {"icf": [{"rule": "heading_cohesion", "target": "DURATION"}]}
    assert unsupported == []


def test_protocol_excessive_whitespace_retains_non_destructive_heading_cohesion():
    finding = {
        "category": "visual",
        "artifact": "protocol",
        "check": "excessive_whitespace",
        "element": "19.2 Study Completion",
        "target_ids": ["layout:protocol"],
        "issue": "A heading is isolated above excessive remaining whitespace.",
    }

    plan, unsupported = workflow._layout_repair_plan([finding])

    assert plan == {"protocol": [{"rule": "heading_cohesion", "target": "19.2 Study Completion"}]}
    assert unsupported == []


def test_heading_cohesion_removes_empty_template_paragraphs_before_its_first_block():
    document = Document()
    document.add_heading("DURATION", level=1)
    document.add_paragraph("")
    document.add_paragraph("")
    document.add_paragraph("")
    document.add_paragraph("The study lasts approximately 14 weeks.")

    rendering._repair_heading_cohesion(
        document,
        "DURATION",
        protocol=False,
        remove_empty_intervening_paragraphs=True,
    )

    duration = next(index for index, paragraph in enumerate(document.paragraphs) if paragraph.text == "DURATION")
    assert document.paragraphs[duration + 1].text == "The study lasts approximately 14 weeks."


def test_heading_whitespace_cohesion_removes_contracted_keep_together_spacers():
    document = Document()
    document.add_heading("DURATION", level=1)
    for _ in range(3):
        spacer = document.add_paragraph("")
        properties = spacer._p.get_or_add_pPr()
        properties.append(OxmlElement("w:keepNext"))
        properties.append(OxmlElement("w:keepLines"))
    document.add_paragraph("The study lasts approximately 14 weeks.")

    rendering._repair_heading_cohesion(
        document,
        "DURATION",
        protocol=False,
        remove_empty_intervening_paragraphs=True,
    )

    duration = next(index for index, paragraph in enumerate(document.paragraphs) if paragraph.text == "DURATION")
    assert document.paragraphs[duration + 1].text == "The study lasts approximately 14 weeks."


def test_sterling_duration_whitespace_repair_removes_contracted_template_spacers(tmp_path):
    reference = json.loads(
        (ROOT / "tests/fixtures/ambispective-acceptance-source.json").read_text(encoding="utf-8")
    )
    reference["meta"]["icf_template"] = "Sterling"
    model = {"protocol": [], "icf": {}, "prs": {}}
    baseline_dir = tmp_path / "baseline"
    repaired_dir = tmp_path / "repaired"

    baseline = render_documents(ROOT, baseline_dir, reference, model, artifact_names={"icf"})
    repaired = render_documents(
        ROOT,
        repaired_dir,
        reference,
        model,
        artifact_names={"icf"},
        layout_repairs={
            "icf": ({"rule": "heading_whitespace_cohesion", "target": "DURATION"},),
        },
    )

    def empty_paragraphs_after_duration(path):
        paragraphs = Document(path).paragraphs
        duration = next(index for index, paragraph in enumerate(paragraphs) if paragraph.text == "DURATION")
        count = 0
        for paragraph in paragraphs[duration + 1 :]:
            if paragraph.text.strip():
                break
            count += 1
        return count

    assert baseline["status"] == repaired["status"] == "passed"
    assert empty_paragraphs_after_duration(baseline_dir / "candidate/icf.docx") == 3
    assert empty_paragraphs_after_duration(repaired_dir / "candidate/icf.docx") == 0


def test_heading_whitespace_cohesion_preserves_empty_section_boundary_paragraph():
    document = Document()
    document.add_heading("DURATION", level=1)
    section_boundary = document.add_paragraph("")
    section_boundary._p.get_or_add_pPr().append(OxmlElement("w:sectPr"))
    document.add_paragraph("The study lasts approximately 14 weeks.")

    rendering._repair_heading_cohesion(
        document,
        "DURATION",
        protocol=False,
        remove_empty_intervening_paragraphs=True,
    )

    duration = next(index for index, paragraph in enumerate(document.paragraphs) if paragraph.text == "DURATION")
    retained = document.paragraphs[duration + 1]
    assert retained.text == ""
    assert retained._p.find(qn("w:pPr") + "/" + qn("w:sectPr")) is not None


def test_heading_whitespace_cohesion_preserves_empty_bookmark_paragraph():
    document = Document()
    document.add_heading("DURATION", level=1)
    bookmark_paragraph = document.add_paragraph("")
    bookmark = OxmlElement("w:bookmarkStart")
    bookmark.set(qn("w:id"), "7")
    bookmark.set(qn("w:name"), "duration-boundary")
    bookmark_paragraph._p.append(bookmark)
    document.add_paragraph("The study lasts approximately 14 weeks.")

    rendering._repair_heading_cohesion(
        document,
        "DURATION",
        protocol=False,
        remove_empty_intervening_paragraphs=True,
    )

    duration = next(index for index, paragraph in enumerate(document.paragraphs) if paragraph.text == "DURATION")
    retained = document.paragraphs[duration + 1]
    assert retained._p.find(qn("w:bookmarkStart")) is not None


def test_heading_whitespace_cohesion_preserves_empty_numbered_paragraph():
    document = Document()
    document.add_heading("DURATION", level=1)
    numbered_paragraph = document.add_paragraph("")
    numbering = OxmlElement("w:numPr")
    level = OxmlElement("w:ilvl")
    level.set(qn("w:val"), "0")
    number_id = OxmlElement("w:numId")
    number_id.set(qn("w:val"), "1")
    numbering.extend((level, number_id))
    numbered_paragraph._p.get_or_add_pPr().append(numbering)
    document.add_paragraph("The study lasts approximately 14 weeks.")

    rendering._repair_heading_cohesion(
        document,
        "DURATION",
        protocol=False,
        remove_empty_intervening_paragraphs=True,
    )

    duration = next(index for index, paragraph in enumerate(document.paragraphs) if paragraph.text == "DURATION")
    retained = document.paragraphs[duration + 1]
    assert retained._p.find(qn("w:pPr") + "/" + qn("w:numPr")) is not None


def test_heading_whitespace_cohesion_preserves_inherited_page_boundary():
    document = Document()
    boundary_style = document.styles.add_style("Boundary Style", WD_STYLE_TYPE.PARAGRAPH)
    boundary_style.paragraph_format.page_break_before = True
    document.add_heading("DURATION", level=1)
    boundary_paragraph = document.add_paragraph("")
    boundary_paragraph.style = boundary_style
    document.add_paragraph("The study lasts approximately 14 weeks.")

    rendering._repair_heading_cohesion(
        document,
        "DURATION",
        protocol=False,
        remove_empty_intervening_paragraphs=True,
    )

    duration = next(index for index, paragraph in enumerate(document.paragraphs) if paragraph.text == "DURATION")
    retained = document.paragraphs[duration + 1]
    assert retained.style.name == "Boundary Style"
    assert retained.style.paragraph_format.page_break_before is True


def _visible_formatting_fingerprint(path):
    document = Document(path)
    paragraph_layout = tuple(
        (
            paragraph.text,
            paragraph.style.name,
            paragraph.alignment,
            paragraph.paragraph_format.keep_with_next,
            paragraph.paragraph_format.page_break_before,
        )
        for paragraph in document.paragraphs
    )
    page_geometry = tuple(
        (
            section.page_width,
            section.page_height,
            section.left_margin,
            section.right_margin,
            section.top_margin,
            section.bottom_margin,
            section.header_distance,
            section.footer_distance,
        )
        for section in document.sections
    )
    tables = tuple(
        tuple(tuple((cell.text, cell.width) for cell in row.cells) for row in table.rows)
        for table in document.tables
    )
    running_text = tuple(
        (
            tuple(paragraph.text for paragraph in section.header.paragraphs),
            tuple(paragraph.text for paragraph in section.footer.paragraphs),
        )
        for section in document.sections
    )
    return paragraph_layout, page_geometry, tables, running_text


@pytest.mark.parametrize(
    ("fixture_name", "icf_family", "candidate_names"),
    (
        ("prospective-acceptance-source.json", "Advarra", ("protocol.docx", "icf.docx")),
        ("prospective-acceptance-source.json", "Sterling", ("protocol.docx", "icf.docx")),
        ("ambispective-acceptance-source.json", "Advarra", ("protocol.docx", "icf.docx")),
        ("ambispective-acceptance-source.json", "Sterling", ("protocol.docx", "icf.docx")),
        ("retrospective-acceptance-source.json", None, ("protocol.docx",)),
    ),
)
def test_parallel_bundle_identity_preserves_candidate_bytes_and_visible_formatting(
    tmp_path,
    monkeypatch,
    fixture_name,
    icf_family,
    candidate_names,
):
    reference = json.loads((ROOT / "tests/fixtures" / fixture_name).read_text(encoding="utf-8"))
    if icf_family is not None:
        reference["meta"]["icf_template"] = icf_family
    model = {"protocol": [], "icf": {}, "prs": {}}
    baseline_dir = tmp_path / "baseline"
    parallel_identity_dir = tmp_path / "parallel-identity"
    monkeypatch.setattr(zipfile.time, "time", lambda: 1_800_000_000.0)

    bundle = contracted_template_bundle(ROOT, reference)
    legacy_bundle = copy.deepcopy(bundle)
    study_type = reference["meta"]["study_type"]
    protocol_name = {
        "Prospective": "prospective-protocol.template.docx",
        "Ambispective": "ambispective-protocol.template.docx",
        "Retrospective": "retrospective-protocol.template.docx",
    }[study_type]
    legacy_bundle["contracted_templates"]["protocol"]["path"] = f"assets/client-templates/docx/{protocol_name}"
    legacy_bundle["client_template_authorities"]["protocol"]["path"] = "assets/client-templates/reference/protocol-reference.docx"
    if icf_family is not None:
        icf_name = (
            "sterling-icf.template.docx"
            if icf_family == "Sterling"
            else "ambispective-icf.template.docx"
            if study_type == "Ambispective"
            else "prospective-icf.template.docx"
        )
        legacy_bundle["contracted_templates"]["icf"]["path"] = f"assets/client-templates/docx/{icf_name}"
        legacy_bundle["client_template_authorities"]["icf"]["path"] = (
            f"assets/client-templates/reference/{icf_family.casefold()}-icf-reference.docx"
        )
    baseline = render_documents(
        ROOT,
        baseline_dir,
        reference,
        model,
        contracted_bundle=legacy_bundle,
    )
    parallel = render_documents(
        ROOT,
        parallel_identity_dir,
        reference,
        model,
        contracted_bundle=bundle,
    )

    assert baseline["status"] == parallel["status"] == "passed"
    assert len(bundle["identity_sha256"]) == 64
    assert parallel["contracted_template_bundle"] == bundle
    for artifact in parallel["artifacts"]:
        assert artifact["template"] == bundle["contracted_templates"][artifact["artifact"]]["path"]
        assert artifact["client_template_authority"] == bundle["client_template_authorities"][artifact["artifact"]]["path"]
    for candidate_name in candidate_names:
        baseline_path = baseline_dir / "candidate" / candidate_name
        parallel_path = parallel_identity_dir / "candidate" / candidate_name
        assert baseline_path.read_bytes() == parallel_path.read_bytes()
        assert _visible_formatting_fingerprint(baseline_path) == _visible_formatting_fingerprint(parallel_path)


def test_layout_retry_persists_scoped_rule_and_the_original_operation_deadline(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    revision_dir = run_dir / "revisions/r-test"
    revision_dir.mkdir(parents=True)
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    working_reference = {"generation": {"layout_repairs": {"icf": [{"rule": "heading_cohesion", "target": "QUESTIONS"}]}}}
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    observed = {}

    def fake_generate(path, **kwargs):
        observed.update({"path": path, **kwargs})
        return {"status": "awaiting_hermes"}

    monkeypatch.setattr(workflow, "generate", fake_generate)
    clock = lambda: 10.0

    workflow._quality_retry(
        run_dir,
        reference_path,
        working_reference,
        reference,
        revision_dir,
        {},
        [{"category": "visual", "field": "protocol", "artifact": "protocol", "check": "orphan_heading", "element": "5. INTRODUCTION", "target_ids": ["layout:protocol"], "recovery_class": "visual_defect", "action": "targeted_layout_repair", "issue": "orphan heading"}],
        "rendered_document_qa",
        operation_deadline=99.0,
        clock=clock,
    )

    persisted = json.loads(reference_path.read_text(encoding="utf-8"))
    assert persisted["generation"]["layout_repairs"] == {
        "icf": [{"rule": "heading_cohesion", "target": "QUESTIONS"}],
        "protocol": [{"rule": "heading_cohesion", "target": "5. INTRODUCTION"}],
    }
    assert persisted["generation"]["pending_layout_artifacts"] == ["protocol"]
    assert "layout_repair_level" not in persisted["generation"]
    assert observed == {"path": run_dir, "operation_deadline": 99.0, "clock": clock}


def test_layout_retry_requires_an_exact_repair_element(tmp_path):
    finding = {
        "category": "visual",
        "artifact": "protocol",
        "check": "orphan_heading",
        "target_ids": ["layout:protocol"],
        "issue": "orphan heading without a bound element",
    }

    plan, unsupported = workflow._layout_repair_plan([finding])

    assert plan == {}
    assert unsupported[0]["required"].endswith(
        "exact heading or table-caption element before deterministic repair."
    )


def test_layout_repair_rejects_a_nonexact_table_target_as_classification(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))

    report = render_documents(
        ROOT,
        tmp_path,
        reference,
        {"protocol": [], "icf": {}, "prs": {}},
        artifact_names={"protocol"},
        layout_repairs={"protocol": ({"rule": "table_pagination", "target": "Table"},)},
    )

    assert report["status"] == "blocked"
    assert report["artifacts"][0]["findings"] == [{
        "category": "layout-repair-classification",
        "field": "protocol",
        "artifact": "protocol",
        "issue": "Layout repair target table must match exactly once; found 0: Table",
    }]

    run_dir = tmp_path / "run"
    revision_dir = run_dir / "revisions/r-test"
    revision_dir.mkdir(parents=True)
    (run_dir / "reference").mkdir()
    findings, block = workflow._document_report_failure(run_dir, revision_dir, report)
    assert findings[0]["target_ids"] == ["layout:protocol"]
    assert block is not None
    assert block["stage"] == "layout_repair_classification"


def test_document_report_failure_preserves_a_governed_drafting_route_through_quality_retry(tmp_path, monkeypatch):
    report = {
        "status": "blocked",
        "artifacts": [{
            "artifact": "icf",
            "findings": [{
                "category": "content",
                "field": "icf.study-purpose",
                "target_ids": ["icf.study-purpose"],
                "issue": "Study-purpose content is missing.",
                "recovery_class": "drafting_defect",
                "action": "retry_drafting_target",
            }],
        }],
    }
    run_dir = tmp_path / "run"
    revision_dir = run_dir / "revisions/r-test"
    revision_dir.mkdir(parents=True)
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({"generation": {}}), encoding="utf-8")

    def fake_schedule_requests(**_kwargs):
        path = revision_dir / "hermes/drafting-requests/icf-study-purpose.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "task": "draft_sections",
            "response_path": "hermes/drafting-responses/icf-study-purpose.json",
        }), encoding="utf-8")
        return [path]

    monkeypatch.setattr(workflow, "schedule_requests", fake_schedule_requests)

    findings, block = workflow._document_report_failure(run_dir, revision_dir, report)
    result = workflow._quality_retry(
        run_dir,
        reference_path,
        {"generation": {}},
        json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8")),
        revision_dir,
        {},
        findings,
        "quality",
    )

    assert block is None
    assert findings == report["artifacts"][0]["findings"]
    assert result["status"] == "awaiting_hermes", result
    assert result["stage"] == "drafting_retry"


def test_partial_render_merge_keeps_each_artifacts_bound_renderer(tmp_path):
    prior = {
        "renderer": {"kind": "Microsoft Word"},
        "page_renderer": {"kind": "pypdfium2"},
        "artifacts": [
            {"artifact": "icf", "pages": []},
            {"artifact": "protocol", "pages": []},
        ],
    }
    initial_paths = quality.create_verification_requests(tmp_path, _source(), prior)
    initial_icf = next(path for path in initial_paths if "visual.icf" in path.name)
    initial_request = json.loads(initial_icf.read_text(encoding="utf-8"))
    response_path = tmp_path / initial_request["response_path"]
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text("{}", encoding="utf-8")
    current = {
        "status": "passed",
        "renderer": {"kind": "LibreOffice"},
        "page_renderer": {"kind": "pypdfium2"},
        "artifacts": [
            {"artifact": "protocol", "renderer": {"kind": "LibreOffice"}, "page_renderer": {"kind": "pypdfium2"}, "pages": []},
        ],
    }

    merged = workflow._merge_artifact_reports(prior, current)
    assurance, assurance_render = workflow._merge_partial_assurance(
        {"render_report": prior},
        {"status": "passed", "render": current},
        {"protocol"},
    )
    paths = quality.create_verification_requests(tmp_path, _source(), merged)
    icf_request = json.loads(next(path for path in paths if "visual.icf" in path.name).read_text(encoding="utf-8"))
    protocol_request = json.loads(next(path for path in paths if "visual.protocol" in path.name).read_text(encoding="utf-8"))

    assert icf_request["request_sha256"] == initial_request["request_sha256"]
    assert response_path.is_file()
    assert icf_request["renderer"] == {"kind": "Microsoft Word"}
    assert protocol_request["renderer"] == {"kind": "LibreOffice"}
    assert assurance["render"] == assurance_render == merged


def test_renderer_preflight_render_verifies_an_uninspectable_font_instead_of_failing(monkeypatch):
    identity = {"kind": "LibreOffice", "path": "/test/soffice", "version": "test", "platform": "Linux"}
    page_identity = _page_identity()
    monkeypatch.setattr(quality, "renderers", lambda **_: [identity])
    monkeypatch.setattr(quality, "page_renderers", lambda **_: [page_identity])
    monkeypatch.setattr(quality, "_template_fonts", lambda _path: {"Client Sans"})
    monkeypatch.setattr(quality, "_font_probe", lambda *_args, **_kwargs: (None, "font inventory unavailable"))

    def fake_export(_docx, output_dir, _identity, **_kwargs):
        from pypdf import PdfWriter
        output = output_dir / "preflight.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with output.open("wb") as handle:
            writer.write(handle)
        return output

    def fake_rasterize(_pdf, output_dir, _identity, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        page = output_dir / "page.png"
        page.write_bytes(b"png")
        return [page]

    monkeypatch.setattr(quality, "_render_pdf", fake_export)
    monkeypatch.setattr(quality, "rasterize_pdf", fake_rasterize)

    report = quality.preflight(ROOT, _source(), deadline_seconds=10)

    assert report["status"] == "passed"
    assert report["font_substitutions"] == {}
    assert report["fonts"]["Client Sans"] == {
        "available": None,
        "match": "font inventory unavailable",
        "resolution": "render_verified",
    }


def test_renderer_preflight_falls_through_a_broken_preferred_renderer(monkeypatch):
    word = {"kind": "Microsoft Word", "path": "/Applications/Microsoft Word.app", "version": "test", "platform": "Darwin"}
    fallback = {"kind": "LibreOffice", "path": "/host/soffice", "version": "test", "platform": "Darwin", "source": "host prerequisite"}
    page_identity = _page_identity()
    monkeypatch.setattr(quality, "renderers", lambda **_: [word, fallback])
    monkeypatch.setattr(quality, "page_renderers", lambda **_: [page_identity])
    monkeypatch.setattr(quality, "_template_fonts", lambda _path: set())

    def fake_export(_docx, output_dir, identity, **_kwargs):
        if identity == word:
            raise RuntimeError("Word automation unavailable")
        from pypdf import PdfWriter
        output = output_dir / "preflight.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with output.open("wb") as handle:
            writer.write(handle)
        return output

    def fake_rasterize(_pdf, output_dir, _identity, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        page = output_dir / "page.png"
        page.write_bytes(b"png")
        return [page]

    monkeypatch.setattr(quality, "_render_pdf", fake_export)
    monkeypatch.setattr(quality, "rasterize_pdf", fake_rasterize)

    report = quality.preflight(ROOT, _source(), deadline_seconds=10)

    assert report["status"] == "passed"
    assert report["renderer"] == fallback
    assert report["renderer_attempts"] == [
        {"renderer": word, "status": "failed", "issue": "Word automation unavailable"},
        {"renderer": fallback, "status": "passed"},
    ]


def test_document_rendering_falls_through_tool_failure_to_the_next_renderer(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    Document().save(candidate / "protocol.docx")
    word = {"kind": "Microsoft Word", "path": "/test/word", "platform": "Darwin"}
    fallback = {"kind": "LibreOffice", "path": "/test/soffice", "platform": "Darwin", "source": "host prerequisite"}
    page_identity = _page_identity()

    def fake_export(docx, output_dir, identity, **_kwargs):
        if identity == word:
            raise RuntimeError("Word automation unavailable")
        from pypdf import PdfWriter
        output = output_dir / f"{docx.stem}.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with output.open("wb") as handle:
            writer.write(handle)
        return output

    def fake_rasterize(_pdf, output_dir, _identity, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        page = output_dir / "page-1.png"
        page.write_bytes(b"png")
        return [page]

    monkeypatch.setattr(quality, "_render_pdf", fake_export)
    monkeypatch.setattr(quality, "rasterize_pdf", fake_rasterize)
    monkeypatch.setattr(quality, "page_renderers", lambda **_: [_page_identity()])
    monkeypatch.setattr(quality, "refresh_toc_from_pdf", lambda *_args: False)
    monkeypatch.setattr(quality, "_blank_pdf_pages", lambda _pdf: [])

    report = quality.render_pages(
        tmp_path,
        renderer_identities=[word, fallback],
        page_renderer_identities=[page_identity],
    )

    assert report["status"] == "passed"
    assert report["renderer"] == fallback
    assert report["renderer_attempts"] == [
        {"renderer": word, "status": "failed", "issue": "Word automation unavailable"},
        {"renderer": fallback, "status": "passed"},
    ]


def test_real_visual_defect_does_not_switch_away_from_the_client_renderer(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    Document().save(candidate / "protocol.docx")
    word = {"kind": "Microsoft Word", "path": "/test/word", "platform": "Darwin"}
    fallback = {"kind": "LibreOffice", "path": "/test/soffice", "platform": "Darwin", "source": "host prerequisite"}
    page_identity = _page_identity()
    rendered_by = []

    def fake_export(docx, output_dir, identity, **_kwargs):
        rendered_by.append(identity["kind"])
        from pypdf import PdfWriter
        output = output_dir / f"{docx.stem}.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with output.open("wb") as handle:
            writer.write(handle)
        return output

    def fake_rasterize(_pdf, output_dir, _identity, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        page = output_dir / "page-1.png"
        page.write_bytes(b"png")
        return [page]

    monkeypatch.setattr(quality, "_render_pdf", fake_export)
    monkeypatch.setattr(quality, "rasterize_pdf", fake_rasterize)
    monkeypatch.setattr(quality, "page_renderers", lambda **_: [_page_identity()])
    monkeypatch.setattr(quality, "refresh_toc_from_pdf", lambda *_args: False)
    monkeypatch.setattr(quality, "_blank_pdf_pages", lambda _pdf: [1])

    report = quality.render_pages(
        tmp_path,
        renderer_identities=[word, fallback],
        page_renderer_identities=[page_identity],
    )

    assert report["status"] == "blocked"
    assert report["renderer"] == word
    assert rendered_by == ["Microsoft Word"]
    assert report["findings"][0]["category"] == "visual"


def test_render_pages_regenerates_only_the_selected_artifact(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    for artifact in ("protocol", "icf"):
        Document().save(candidate / f"{artifact}.docx")
    retained_pdf = tmp_path / "rendered/icf.pdf"
    retained_page = tmp_path / "rendered/icf/page-1.png"
    retained_page.parent.mkdir(parents=True)
    retained_pdf.write_bytes(b"retained-icf-pdf")
    retained_page.write_bytes(b"retained-icf-page")
    rendered = []

    def fake_export(docx, output_dir, _identity, **_kwargs):
        rendered.append(docx.stem)
        from pypdf import PdfWriter
        output = output_dir / f"{docx.stem}.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with output.open("wb") as handle:
            writer.write(handle)
        return output

    def fake_rasterize(_pdf, output_dir, _identity, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        page = output_dir / "page-1.png"
        page.write_bytes(b"protocol-page")
        return [page]

    monkeypatch.setattr(quality, "_render_pdf", fake_export)
    monkeypatch.setattr(quality, "rasterize_pdf", fake_rasterize)
    monkeypatch.setattr(quality, "page_renderers", lambda **_: [_page_identity()])
    monkeypatch.setattr(quality, "refresh_toc_from_pdf", lambda *_args: False)
    monkeypatch.setattr(quality, "_blank_pdf_pages", lambda _pdf: [])

    report = quality.render_pages(
        tmp_path,
        artifact_names={"protocol"},
        renderer_identities=[{"kind": "test", "path": "/test/renderer"}],
        page_renderer_identities=[_page_identity()],
    )

    assert report["status"] == "passed"
    assert rendered == ["protocol"]
    assert [item["artifact"] for item in report["artifacts"]] == ["protocol"]
    assert retained_pdf.read_bytes() == b"retained-icf-pdf"
    assert retained_page.read_bytes() == b"retained-icf-page"


def test_generated_docx_replaces_a_missing_client_font_with_the_selected_fallback(tmp_path):
    render_documents(
        ROOT,
        tmp_path,
        _source(),
        {"protocol": [], "icf": {}, "prs": {}},
        font_substitutions={"Noto Sans Symbols": "Apple Symbols"},
    )

    fonts = quality._template_fonts(tmp_path / "candidate/protocol.docx")

    assert "Noto Sans Symbols" not in fonts
    assert "Apple Symbols" in fonts


def test_symbol_and_text_fonts_have_multiple_cross_platform_fallbacks():
    assert quality._font_fallback_candidates("Noto Sans Symbols")[:5] == (
        "Apple Symbols",
        "Segoe UI Symbol",
        "Arial Unicode MS",
        "Arial Unicode",
        "Symbol",
    )
    assert quality._font_fallback_candidates("Verdana")[:4] == (
        "Arial",
        "Helvetica",
        "Aptos",
        "Calibri",
    )


def test_template_font_inventory_only_requires_fonts_used_by_visible_latin_text(tmp_path):
    document = Document()
    dormant = document.styles.add_style("Dormant client style", WD_STYLE_TYPE.CHARACTER)
    dormant.font.name = "Unavailable Dormant Font"
    run = document.add_paragraph().add_run("Visible Latin text")
    fonts = run._element.get_or_add_rPr().get_or_add_rFonts()
    fonts.set(qn("w:ascii"), "Arial")
    fonts.set(qn("w:hAnsi"), "Arial")
    fonts.set(qn("w:eastAsia"), "Unavailable East Asia Font")
    fonts.set(qn("w:cs"), "Unavailable Complex Script Font")
    path = tmp_path / "font-contract.docx"
    document.save(path)

    assert quality._template_fonts(path) == {"Arial"}


def test_renderer_preflight_can_run_an_actual_local_renderer_smoke_export(monkeypatch):
    identity = quality.renderer()
    page_identity = quality.page_renderer(skill_root=ROOT)
    if identity is None or page_identity is None:
        import pytest
        pytest.skip("No installed release runtime is available in the source checkout")
    monkeypatch.setattr(quality, "_font_probe", lambda *_args, **_kwargs: (True, "test-font"))
    report = quality.preflight(ROOT, _source(), deadline_seconds=30)

    assert report["status"] == "passed"
    assert report["smoke"]["status"] == "passed"
    assert report["smoke"]["pages"] >= 1


def test_approved_investigator_and_facility_values_populate_protocol_agreement(tmp_path):
    reference = _source()
    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})

    document = Document(tmp_path / "candidate/protocol.docx")
    agreement = next(
        table for table in document.tables
        if any("Signature of Investigator" in cell.text for row in table.rows for cell in row.cells)
    )
    values = [cell.text for row in agreement.rows for cell in row.cells]
    assert "Alex Investigator" in values
    assert "MD" in values
    assert "Site One" in values


def test_protocol_visit_schedule_has_rows_when_approved_source_has_assessments_only(tmp_path):
    reference = _source()
    reference["procedures"].pop("visit_schedule", None)
    reference["procedures"].pop("visit_schedule_table", None)
    reference["procedures"]["assessments"] = ["Screening", "Month 1", "Month 3"]
    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})

    document = Document(tmp_path / "candidate/protocol.docx")
    schedule = next(table for table in document.tables if table.cell(0, 0).text.strip() == "Visit Number")
    assert [cell.text for row in schedule.rows[1:] for cell in row.cells]
    assert "Screening" in "\n".join(cell.text for row in schedule.rows for cell in row.cells)


def test_advarra_icf_contact_and_withdrawal_are_source_bound(tmp_path):
    reference = _source()
    model = {
        "protocol": [],
        "prs": {},
        "icf": {
            "icf.contact-information": {
                "paragraphs": [{"text": "Call the study doctor at the toll-free IRB number and ask the Study Subject Adviser."}],
                "lists": [],
            },
            "icf.leaving-study": {
                "paragraphs": [{"text": "Call to schedule study exit procedures."}],
                "lists": [],
            },
        },
    }
    render_documents(ROOT, tmp_path, reference, model)
    visible = _visible(Document(tmp_path / "candidate/icf.docx")).casefold()

    assert "toll-free" not in visible
    assert "study subject adviser" not in visible
    assert "schedule study exit procedures" not in visible
    assert "555-0101" in visible
    assert "no new routine research procedures" in visible


def test_advarra_icf_replaces_unsupported_introduction_and_risk_shell_text(tmp_path):
    reference = _source()
    risk_text = (
        "Taking part may involve inconvenience or discomfort from the study procedures described in this consent form. "
        "There is also a risk that private information could be disclosed, although safeguards will be used to protect it."
    )
    model = {
        "protocol": [],
        "prs": {},
        "icf": {
            "icf.risks": {"paragraphs": [{"text": risk_text}], "lists": []},
        },
    }

    render_documents(ROOT, tmp_path, reference, model)
    visible = _visible(Document(tmp_path / "candidate/icf.docx")).casefold()

    assert "you are being invited to take part in a research study" in visible
    assert "past and present drug use" not in visible
    assert "very serious health consequences" not in visible
    assert "all devices can have side effects" not in visible
    assert "presently unforeseen and unknown risks" not in visible
    assert visible.count(risk_text.casefold()) == 1


def test_protocol_test_article_falls_back_to_approved_intervention_name():
    reference = _source()
    reference["design"].pop("arms", None)

    fields = rendering.render_fields(reference, {"protocol": [], "icf": {}, "prs": {}})

    assert fields["testArticle(s)"] == "Sentinel Patch"


def test_transient_verifier_failure_is_classified_for_retry_without_accepting_qa(tmp_path):
    revision = tmp_path / "revision"
    requests = revision / "hermes/verification-requests"
    responses = revision / "hermes/verification-responses"
    requests.mkdir(parents=True)
    responses.mkdir()
    request = {
        "schema_version": "hermes-verification/v1",
        "request_id": "r.verify.content",
        "task": "clinical_content_verification",
        "response_path": "hermes/verification-responses/r.verify.content.json",
        "sections": [],
        "cross_document_checks": [],
        "artifacts": [],
    }
    request["request_sha256"] = verification_request_sha256(request)
    (requests / "content.json").write_text(json.dumps(request), encoding="utf-8")
    response = {
        "schema_version": RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "task": request["task"],
        "producer": {"model_id": "Verifier"},
        "status": "retryable_error",
        "error": {"type": "api_unavailable", "message": "temporary connection failure"},
    }
    (responses / "r.verify.content.json").write_text(json.dumps(response), encoding="utf-8")

    findings, evidence = validate_verifications(revision)

    assert evidence[request["task"]]
    assert len(findings) == 1
    assert findings[0]["category"] == "reviewer-transient"
    assert findings[0]["target_ids"] == ["verification:content"]
    assert findings[0]["recovery_class"] == "verifier_transient"
    assert findings[0]["action"] == "retry_verifier"


def test_transient_verifier_failure_is_retried_with_a_bounded_counter(tmp_path):
    revision = tmp_path / "revision"
    requests = revision / "hermes/verification-requests"
    requests.mkdir(parents=True)
    for task in ("clinical_content_verification", "rendered_page_visual_verification"):
        request = {
            "schema_version": "hermes-verification/v1",
            "request_id": f"r.verify.{task}",
            "task": task,
            "response_path": f"hermes/verification-responses/{task}.json",
        }
        request["request_sha256"] = verification_request_sha256(request)
        (requests / f"{task}.json").write_text(
            json.dumps(request),
            encoding="utf-8",
        )
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    working = {"generation": {}}
    reference_path.write_text(json.dumps(working), encoding="utf-8")
    finding = {"category": "reviewer-transient", "field": "clinical_content_verification", "target_ids": ["verification:content"], "recovery_class": "verifier_transient", "action": "retry_verifier", "issue": "temporary"}

    result = workflow._quality_retry(run_dir, reference_path, working, {}, revision, {}, [finding], "quality")

    assert result["status"] == "awaiting_hermes"
    assert result["stage"] == "independent_verification_retry"
    state = json.loads(reference_path.read_text(encoding="utf-8"))
    assert state["generation"]["verification_attempts"]["verification:content"] == 1
    assert not (revision / "hermes/verification-responses/clinical_content_verification.json").exists()


def test_quality_retry_rejects_a_finding_without_a_governed_recovery_class(tmp_path):
    run_dir = tmp_path / "run"
    revision = run_dir / "revisions/r-test"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({"generation": {}}), encoding="utf-8")

    result = workflow._quality_retry(
        run_dir,
        reference_path,
        {"generation": {}},
        {},
        revision,
        {},
        [{"category": "visual", "field": "protocol", "issue": "free text must not select recovery"}],
        "quality",
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "recovery_classification"
    assert result["findings"][0]["field"] == "recovery_class"


def test_quality_retry_rejects_a_recovery_class_with_the_wrong_target_type(tmp_path):
    run_dir = tmp_path / "run"
    revision = run_dir / "revisions/r-test"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({"generation": {}}), encoding="utf-8")

    result = workflow._quality_retry(
        run_dir,
        reference_path,
        {"generation": {}},
        {},
        revision,
        {},
        [{
            "category": "verification",
            "field": "content",
            "target_ids": ["verification:content"],
            "recovery_class": "visual_defect",
            "action": "targeted_layout_repair",
            "issue": "category prose must not override the Recovery Class",
        }],
        "quality",
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "recovery_classification"
    assert result["findings"][0]["field"] == "target_ids"


def test_layout_failure_rebuilds_and_reverifies_before_retry_limit(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    revision = run_dir / "revisions/r-test"
    reference_path = run_dir / "reference/study.reference.json"
    verification_response = revision / "hermes/verification-responses/visual.json"
    reference_path.parent.mkdir(parents=True)
    verification_response.parent.mkdir(parents=True)
    verification_request = revision / "hermes/verification-requests/visual.json"
    verification_request.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    verification_response.write_text("{}", encoding="utf-8")
    verification_request.write_text(json.dumps({
        "task": "rendered_page_visual_verification",
        "response_path": "hermes/verification-responses/visual.json",
        "artifacts": [{"artifact": "protocol"}],
    }), encoding="utf-8")
    (revision / "candidate-build.json").write_text("{}", encoding="utf-8")
    rerun = {"status": "awaiting_hermes", "stage": "independent_verification"}
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: rerun)

    result = workflow._quality_retry(
        run_dir,
        reference_path,
        {"generation": {}},
        {},
        revision,
        {},
        [{"category": "visual", "field": "protocol.docx:10", "artifact": "protocol", "check": "orphan_heading", "element": "5. INTRODUCTION", "target_ids": ["layout:protocol.docx"], "recovery_class": "visual_defect", "action": "targeted_layout_repair", "issue": "orphan heading"}],
        "quality",
    )

    assert result == rerun
    state = json.loads(reference_path.read_text(encoding="utf-8"))
    assert state["generation"]["attempts"]["layout:protocol.docx"] == 2
    assert (revision / "candidate-build.json").exists()
    assert not verification_request.exists()
    assert not verification_response.exists()


def test_layout_failure_blocks_only_after_three_total_attempts(tmp_path):
    run_dir = tmp_path / "run"
    revision = run_dir / "revisions/r-test"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    finding = {"category": "visual", "field": "protocol.docx:10", "artifact": "protocol", "check": "orphan_heading", "element": "5. INTRODUCTION", "target_ids": ["layout:protocol.docx"], "recovery_class": "visual_defect", "action": "targeted_layout_repair", "issue": "orphan heading"}

    result = workflow._quality_retry(
        run_dir,
        reference_path,
        {"generation": {}},
        {},
        revision,
        {"layout:protocol.docx": 3},
        [finding],
        "quality",
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "quality"
    assert result["findings"][0]["field"] == "layout:protocol.docx"
    assert "after 3 attempts" in result["findings"][0]["issue"]


def test_prs_generation_validates_against_the_retained_client_manual_authority(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    report = generate_xml(
        ROOT / "assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml",
        tmp_path / "study.xml",
        reference,
        {"brief_summary": {"text": "Approved summary."}, "detailed_description": {"text": "Approved description."}},
        structural_template=ROOT / "assets/client-templates/reference/prs-manual-reference.xml",
    )
    assert report["status"] == "passed"


def test_refresh_toc_uses_layout_extraction_to_find_body_heading(tmp_path, monkeypatch):
    document = Document()
    document.styles.add_style("toc 1", WD_STYLE_TYPE.PARAGRAPH)
    document.add_paragraph("4. TABLE OF CONTENTS", style="Heading 1")
    document.add_paragraph("15. STANDARD EVALUATION PROCEDURES\t5", style="toc 1")
    document.add_paragraph("15. STANDARD EVALUATION PROCEDURES", style="Heading 1")
    docx = tmp_path / "protocol.docx"
    document.save(docx)
    pdf = tmp_path / "protocol.pdf"
    pdf.write_bytes(b"pdf")

    class Page:
        def __init__(self, plain, layout):
            self.plain = plain
            self.layout = layout

        def extract_text(self, extraction_mode=None):
            return self.layout if extraction_mode == "layout" else self.plain

    class Reader:
        def __init__(self, _path):
            self.pages = [
                Page("4. TABLE OF CONTENTS", "4. TABLE OF CONTENTS"),
                Page("15. STANDARD EVALUATION PROCEDURES", "15. STANDARD EVALUATION PROCEDURES"),
                *[Page("", "") for _ in range(7)],
                Page("", "15. STANDARD EVALUATION PROCEDURES"),
            ]

    monkeypatch.setattr(rendering, "PdfReader", Reader)
    assert rendering.refresh_toc_from_pdf(docx, pdf)
    refreshed = Document(docx)
    toc = next(
        paragraph.text
        for paragraph in refreshed.paragraphs
        if paragraph.style.name == "toc 1" and paragraph.text.startswith("15.")
    )
    assert toc.endswith("\t10")


def test_protocol_omits_references_heading_when_no_references_are_supplied():
    document = Document()
    document.add_paragraph("REFERENCES", style="Heading 1")
    document.add_paragraph("")
    authority = Document()
    authority.add_paragraph("REFERENCES", style="Heading 1")

    rendering._ensure_protocol_references(document, authority, {})

    assert "REFERENCES" not in [paragraph.text.strip() for paragraph in document.paragraphs]


def test_layout_failure_invalidates_only_the_affected_artifact_evidence(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    revision = run_dir / "revisions/r-test"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    working = {"generation": {}}
    reference_path.write_text(json.dumps(working), encoding="utf-8")
    retained = (
        "candidate/protocol.docx",
        "candidate/icf.docx",
        "rendered/protocol.pdf",
        "rendered/protocol/page-1.png",
        "rendered/icf.pdf",
        "rendered/icf/page-1.png",
    )
    for relative in retained:
        path = revision / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())
    requests = revision / "hermes/verification-requests"
    responses = revision / "hermes/verification-responses"
    requests.mkdir(parents=True)
    responses.mkdir(parents=True)
    for artifact in ("protocol", "icf"):
        request = {
            "task": "rendered_page_visual_verification",
            "request_id": f"visual-{artifact}",
            "response_path": f"hermes/verification-responses/visual-{artifact}.json",
            "artifacts": [{"artifact": artifact}],
        }
        (requests / f"visual-{artifact}.json").write_text(json.dumps(request), encoding="utf-8")
        (responses / f"visual-{artifact}.json").write_text("{}", encoding="utf-8")
    (revision / "candidate-build.json").write_text("{}", encoding="utf-8")
    resumed = {"status": "awaiting_hermes", "stage": "independent_verification"}
    monkeypatch.setattr(workflow, "generate", lambda _, **_kwargs: resumed)

    result = workflow._quality_retry(
        run_dir,
        reference_path,
        working,
        {"meta": {"study_type": "Retrospective"}},
        revision,
        {},
        [{"category": "visual", "field": "protocol", "artifact": "protocol", "check": "orphan_heading", "element": "5. INTRODUCTION", "target_ids": ["layout:protocol"], "recovery_class": "visual_defect", "action": "targeted_layout_repair", "issue": "orphaned heading"}],
        "quality",
    )

    assert result == resumed
    state = json.loads(reference_path.read_text(encoding="utf-8"))
    assert state["generation"]["attempts"]["layout:protocol"] == 2
    assert state["generation"]["layout_repairs"] == {
        "protocol": [{"rule": "heading_cohesion", "target": "5. INTRODUCTION"}],
    }
    assert not (revision / "candidate/protocol.docx").exists()
    assert not (revision / "rendered/protocol.pdf").exists()
    assert not (revision / "rendered/protocol").exists()
    assert not (requests / "visual-protocol.json").exists()
    assert not (responses / "visual-protocol.json").exists()
    assert (revision / "candidate/icf.docx").is_file()
    assert (revision / "rendered/icf.pdf").is_file()
    assert (revision / "rendered/icf/page-1.png").is_file()
    assert (requests / "visual-icf.json").is_file()
    assert (responses / "visual-icf.json").is_file()
    assert (revision / "candidate-build.json").is_file()
