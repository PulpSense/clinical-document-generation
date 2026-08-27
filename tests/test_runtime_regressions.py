import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn

from contracts import contracted_template_bundle
from quality import RESPONSE_SCHEMA, validate_verifications
import quality
from rendering import render_documents
import rendering
from prs_xml import generate as generate_xml
import workflow


ROOT = Path(__file__).resolve().parents[1]


def _source():
    return json.loads(
        (ROOT / "runs/ps-mm-001/reference/study.reference.json").read_text(encoding="utf-8")
    )


def _visible(document):
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    cells = [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    return "\n".join(paragraphs + cells)


def test_renderer_preflight_reports_exhausted_fallback_stack_when_no_renderer_exists(tmp_path, monkeypatch):
    reference = _source()
    monkeypatch.setattr(quality, "renderers", lambda **_: [])
    report = quality.preflight(ROOT, reference, deadline_seconds=2)

    assert report["status"] == "blocked"
    assert report["smoke"]["status"] == "blocked"
    assert any("renderer" == finding["field"] for finding in report["findings"])


def test_renderer_preflight_records_renderer_font_and_smoke_evidence(tmp_path, monkeypatch):
    reference = _source()
    identity = {"kind": "LibreOffice", "path": "/usr/bin/soffice", "version": "test", "platform": "Linux"}
    monkeypatch.setattr(quality, "renderers", lambda **_: [identity])
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
    report = quality.preflight(ROOT, reference, deadline_seconds=10)

    assert report["status"] == "passed"
    assert report["renderer"] == identity
    assert report["elapsed_seconds"] < report["deadline_seconds"]
    assert report["smoke"] == {"status": "passed", "pdf": "disposable/preflight.pdf", "page_image": "disposable/preflight.png", "pages": 1}


def test_page_renderer_discovers_a_hermes_bundled_binary_when_path_omits_it(tmp_path):
    bundled = tmp_path / ".hermes/bin/pdftoppm"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("#!/bin/sh\n", encoding="utf-8")
    bundled.chmod(0o755)

    identity = quality.page_renderer(environment={"PATH": "/usr/bin:/bin"}, home=tmp_path)

    assert identity is not None
    assert identity["kind"] == "pdftoppm"
    assert identity["path"] == str(bundled)
    assert identity["source"] == "Hermes bundled tools"


def test_page_renderer_exposes_at_least_five_cross_platform_backends():
    assert tuple(quality.PAGE_RENDERER_BACKENDS)[:5] == (
        "pdftoppm",
        "pdftocairo",
        "mutool",
        "ghostscript",
        "imagemagick",
    )


def test_release_owned_pymupdf_ignores_a_cached_host_module(tmp_path, monkeypatch):
    runtime_python = tmp_path / "runtime/python"
    package = runtime_python / "pymupdf"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        """
from pathlib import Path
class Matrix:
    def __init__(self, *_args): pass
class Pixmap:
    def save(self, path): Path(path).write_bytes(b'release-owned')
class Page:
    def get_pixmap(self, **_kwargs): return Pixmap()
class Doc:
    def __len__(self): return 1
    def __getitem__(self, _index): return Page()
    def close(self): pass
def open(_path): return Doc()
""",
        encoding="utf-8",
    )
    host = SimpleNamespace(__file__="/host/pymupdf/__init__.py", open=lambda _path: (_ for _ in ()).throw(AssertionError("host module used")))
    monkeypatch.setitem(quality.sys.modules, "pymupdf", host)
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"pdf")

    pages = quality.rasterize_pdf(
        pdf,
        tmp_path / "pages",
        {
            "kind": "pymupdf",
            "path": "python:pymupdf",
            "module": "pymupdf",
            "python_path": str(runtime_python),
            "source": "verified fallback stack",
        },
    )

    assert pages[0].read_bytes() == b"release-owned"
    assert quality.sys.modules["pymupdf"] is host


def test_renderer_preflight_uses_the_selected_page_renderer(tmp_path, monkeypatch):
    reference = _source()
    renderer_identity = {"kind": "LibreOffice", "path": "/usr/bin/soffice", "version": "test", "platform": "Linux"}
    page_renderer_identity = {"kind": "pdftocairo", "path": "/usr/bin/pdftocairo", "source": "PATH"}
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


def test_renderer_preflight_tries_the_next_backend_when_an_installed_backend_fails(monkeypatch):
    renderer_identity = {"kind": "LibreOffice", "path": "/usr/bin/soffice", "version": "test", "platform": "Linux"}
    broken = {"kind": "pdftoppm", "path": "/broken/pdftoppm", "source": "PATH"}
    working = {"kind": "pymupdf", "path": "python:pymupdf", "source": "Python environment"}
    attempts = []
    monkeypatch.setattr(quality, "renderers", lambda **_: [renderer_identity])
    monkeypatch.setattr(quality, "page_renderers", lambda **_: [broken, working])
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
        if identity == broken:
            raise RuntimeError("broken executable")
        output_dir.mkdir(parents=True, exist_ok=True)
        page = output_dir / "page.png"
        page.write_bytes(b"png")
        return [page]

    monkeypatch.setattr(quality, "_render_pdf", fake_export)
    monkeypatch.setattr(quality, "rasterize_pdf", fake_rasterize)

    report = quality.preflight(ROOT, _source(), deadline_seconds=10)

    assert report["status"] == "passed"
    assert attempts == ["pdftoppm", "pymupdf"]
    assert report["page_renderer"] == working
    assert report["page_renderer_attempts"] == [
        {"renderer": broken, "status": "failed", "issue": "broken executable"},
        {"renderer": working, "status": "passed"},
    ]


@pytest.mark.parametrize(
    ("kind", "marker"),
    (
        ("pdftoppm", "-singlefile"),
        ("pdftocairo", "-singlefile"),
        ("mutool", "draw"),
        ("ghostscript", "-sDEVICE=png16m"),
        ("imagemagick", "-density"),
    ),
)
def test_executable_page_renderer_backends_normalize_first_page_output(tmp_path, monkeypatch, kind, marker):
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"pdf")
    output_dir = tmp_path / "pages"

    def fake_run(command, **_kwargs):
        assert command[0] == f"/test/{kind}"
        assert marker in command
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "page-0.png").write_bytes(b"png")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(quality.subprocess, "run", fake_run)

    pages = quality.rasterize_pdf(
        pdf,
        output_dir,
        {"kind": kind, "path": f"/test/{kind}", "source": "test"},
        first_page_only=True,
    )

    assert pages == [output_dir / "page.png"]
    assert pages[0].read_bytes() == b"png"


def test_renderer_preflight_uses_a_packaged_font_when_host_fonts_are_missing(monkeypatch):
    identity = {"kind": "LibreOffice", "path": "/usr/bin/soffice", "version": "test", "platform": "Linux"}
    page_identity = {"kind": "pymupdf", "path": "python:pymupdf", "module": "pymupdf", "source": "bundled"}
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


def test_renderer_preflight_uses_only_the_approved_packaged_fallback_for_a_missing_client_font(monkeypatch):
    identity = {"kind": "LibreOffice", "path": "/verified/soffice", "version": "test", "platform": "Darwin", "source": "verified fallback stack"}
    probes = {
        "Noto Sans Symbols": (False, "not installed"),
        "Apple Symbols": (True, "macOS system font inventory"),
    }
    monkeypatch.setattr(quality, "renderers", lambda **_: [identity])
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
        {"kind": "Pages", "path": "/Applications/Pages.app", "platform": "Darwin"},
        timeout_seconds=7.5,
    )

    assert observed == [7.5]


def test_layout_repair_profile_changes_the_generated_document(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/retrospective-acceptance-source.json").read_text(encoding="utf-8"))
    baseline_dir = tmp_path / "baseline"
    repaired_dir = tmp_path / "repaired"

    baseline = render_documents(ROOT, baseline_dir, reference, {"protocol": [], "icf": {}, "prs": {}})
    repaired = render_documents(
        ROOT,
        repaired_dir,
        reference,
        {"protocol": [], "icf": {}, "prs": {}},
        layout_repair_level=1,
    )

    assert baseline["status"] == repaired["status"] == "passed"
    assert repaired["layout_repair"]["level"] == 1
    assert repaired["layout_repair"]["changes"] > 0
    assert (baseline_dir / "candidate/protocol.docx").read_bytes() != (repaired_dir / "candidate/protocol.docx").read_bytes()


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

    baseline = render_documents(ROOT, baseline_dir, reference, model)
    bundle = contracted_template_bundle(ROOT, reference)
    parallel = render_documents(ROOT, parallel_identity_dir, reference, model)

    assert baseline["status"] == parallel["status"] == "passed"
    assert len(bundle["identity_sha256"]) == 64
    for candidate_name in candidate_names:
        baseline_path = baseline_dir / "candidate" / candidate_name
        parallel_path = parallel_identity_dir / "candidate" / candidate_name
        assert baseline_path.read_bytes() == parallel_path.read_bytes()
        assert _visible_formatting_fingerprint(baseline_path) == _visible_formatting_fingerprint(parallel_path)


def test_layout_retry_persists_repair_and_the_original_operation_deadline(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    revision_dir = run_dir / "revisions/r-test"
    revision_dir.mkdir(parents=True)
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    working_reference = {"generation": {}}
    reference = json.loads((ROOT / "tests/fixtures/retrospective-acceptance-source.json").read_text(encoding="utf-8"))
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
        [{"category": "visual", "field": "protocol", "target_ids": ["layout:protocol"], "issue": "overflow"}],
        "rendered_document_qa",
        operation_deadline=99.0,
        clock=clock,
    )

    persisted = json.loads(reference_path.read_text(encoding="utf-8"))
    assert persisted["generation"]["layout_repair_level"] == 1
    assert observed == {"path": run_dir, "operation_deadline": 99.0, "clock": clock}


def test_renderer_preflight_render_verifies_an_uninspectable_font_instead_of_failing(monkeypatch):
    identity = {"kind": "LibreOffice", "path": "/test/soffice", "version": "test", "platform": "Linux"}
    page_identity = {"kind": "pymupdf", "path": "python:pymupdf", "module": "pymupdf", "source": "bundled"}
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
    fallback = {"kind": "LibreOffice", "path": "/bundled/soffice", "version": "test", "platform": "Darwin", "source": "verified fallback stack"}
    page_identity = {"kind": "pymupdf", "path": "python:pymupdf", "module": "pymupdf", "source": "bundled"}
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
    fallback = {"kind": "LibreOffice", "path": "/test/soffice", "platform": "Darwin", "source": "verified fallback stack"}
    page_identity = {"kind": "pymupdf", "path": "python:pymupdf", "module": "pymupdf"}

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
    fallback = {"kind": "LibreOffice", "path": "/test/soffice", "platform": "Darwin", "source": "verified fallback stack"}
    page_identity = {"kind": "pymupdf", "path": "python:pymupdf", "module": "pymupdf"}
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
    if identity is None:
        import pytest
        pytest.skip("No supported local renderer installed")
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
    assert "Dana Roberts" in values
    assert "MD" in values
    assert "North Neurology Research Center" in values
    assert "Boston" in "\n".join(values)


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
    assert "555-310-2000" in visible
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

    assert fields["testArticle(s)"] == "Meridian Monitor"


def test_transient_verifier_failure_is_classified_for_retry_without_accepting_qa(tmp_path):
    revision = tmp_path / "revision"
    requests = revision / "hermes/verification-requests"
    responses = revision / "hermes/verification-responses"
    requests.mkdir(parents=True)
    responses.mkdir()
    request = {
        "schema_version": "hermes-verification/v1",
        "request_id": "r.verify.content",
        "request_sha256": "request-hash",
        "task": "clinical_content_verification",
        "response_path": "hermes/verification-responses/r.verify.content.json",
        "sections": [],
        "cross_document_checks": [],
        "artifacts": [],
    }
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


def test_transient_verifier_failure_is_retried_with_a_bounded_counter(tmp_path):
    revision = tmp_path / "revision"
    requests = revision / "hermes/verification-requests"
    requests.mkdir(parents=True)
    for task in ("clinical_content_verification", "rendered_page_visual_verification"):
        (requests / f"{task}.json").write_text(
            json.dumps({"task": task, "response_path": f"hermes/verification-responses/{task}.json"}),
            encoding="utf-8",
        )
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    working = {"generation": {}}
    reference_path.write_text(json.dumps(working), encoding="utf-8")
    finding = {"category": "reviewer-transient", "field": "clinical_content_verification", "target_ids": ["verification:content"], "issue": "temporary"}

    result = workflow._quality_retry(run_dir, reference_path, working, {}, revision, {}, [finding], "quality")

    assert result["status"] == "awaiting_hermes"
    assert result["stage"] == "independent_verification_retry"
    state = json.loads(reference_path.read_text(encoding="utf-8"))
    assert state["generation"]["verification_attempts"]["verification:content"] == 1
    assert not (revision / "hermes/verification-responses/clinical_content_verification.json").exists()


def test_layout_failure_rebuilds_and_reverifies_before_retry_limit(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    revision = run_dir / "revisions/r-test"
    reference_path = run_dir / "reference/study.reference.json"
    verification_response = revision / "hermes/verification-responses/visual.json"
    reference_path.parent.mkdir(parents=True)
    verification_response.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    verification_response.write_text("{}", encoding="utf-8")
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
        [{"category": "visual", "field": "protocol.docx:10", "target_ids": ["layout:protocol.docx"], "issue": "orphan heading"}],
        "quality",
    )

    assert result == rerun
    state = json.loads(reference_path.read_text(encoding="utf-8"))
    assert state["generation"]["attempts"]["layout:protocol.docx"] == 2
    assert not (revision / "candidate-build.json").exists()
    assert not verification_response.exists()


def test_layout_failure_blocks_only_after_three_total_attempts(tmp_path):
    run_dir = tmp_path / "run"
    revision = run_dir / "revisions/r-test"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    finding = {"category": "visual", "field": "protocol.docx:10", "target_ids": ["layout:protocol.docx"], "issue": "orphan heading"}

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


def test_layout_failure_rebuilds_the_candidate_before_blocking(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    revision = run_dir / "revisions/r-test"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    working = {"generation": {}}
    reference_path.write_text(json.dumps(working), encoding="utf-8")
    for relative in ("candidate", "rendered", "hermes/verification-responses"):
        path = revision / relative
        path.mkdir(parents=True)
        (path / "stale").write_text("stale", encoding="utf-8")
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
        [{"category": "visual", "field": "protocol", "target_ids": ["layout:protocol"], "issue": "orphaned heading"}],
        "quality",
    )

    assert result == resumed
    state = json.loads(reference_path.read_text(encoding="utf-8"))
    assert state["generation"]["attempts"]["layout:protocol"] == 2
    assert not (revision / "candidate").exists()
    assert not (revision / "rendered").exists()
    assert not (revision / "candidate-build.json").exists()
    assert not (revision / "hermes/verification-responses").exists()
