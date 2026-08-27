import hashlib
from pathlib import Path

from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from quality import RECOVERY_POLICIES, render_assurance


ROOT = Path(__file__).resolve().parents[1]


def test_recovery_classes_have_one_governed_action_each():
    assert RECOVERY_POLICIES == {
        "adapter_fault": "advance_adapter",
        "font_capability_uncertainty": "bounded_smoke_render",
        "document_structure_defect": "preserve_and_stop",
        "visual_defect": "targeted_layout_repair",
        "drafting_defect": "retry_drafting_target",
        "verifier_transient": "retry_verifier",
        "transport_fault": "retry_exact_bytes",
    }


def _write_text_pdf(path: Path) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
        })
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (Render Assurance) Tj ET")
    page[NameObject("/Contents")] = stream
    with path.open("wb") as handle:
        writer.write(handle)


def _bundle() -> dict:
    return {
        "approved_font_plan": {
            "approved_fallbacks": {"missing sans": "Liberation Sans"},
            "packaged_families": {"Liberation Sans": "LiberationSans-Regular.ttf"},
            "packaged_font_assets": {
                "Liberation Sans": "assets/fallback-fonts/LiberationSans-Regular.ttf"
            },
        }
    }


def test_render_assurance_records_tri_state_fonts_and_binds_substitutions_to_exact_artifacts(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    document = Document()
    for font in ("Available Sans", "Missing Sans", "Unknown Sans"):
        run = document.add_paragraph().add_run(font)
        run.font.name = font
    document.save(candidate / "protocol.docx")

    states = {
        "Available Sans": (True, "host inventory"),
        "Missing Sans": (False, "host inventory"),
        "Unknown Sans": (None, "inventory unavailable"),
    }

    def rebuild(substitutions):
        rebuilt = Document(candidate / "protocol.docx")
        for paragraph in rebuilt.paragraphs:
            for run in paragraph.runs:
                if run.font.name in substitutions:
                    run.font.name = substitutions[run.font.name]
        rebuilt.save(candidate / "protocol.docx")
        return {"status": "passed"}

    def export(docx, output_dir, _identity, **_kwargs):
        pdf = output_dir / f"{docx.stem}.pdf"
        _write_text_pdf(pdf)
        return pdf

    def rasterize(_pdf, output_dir, _identity, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        page = output_dir / "page-1.png"
        page.write_bytes(b"page image")
        return [page]

    office = {"kind": "LibreOffice", "path": "/controlled/soffice"}
    pages = {"kind": "pymupdf", "path": "python:pymupdf"}
    report = render_assurance(
        ROOT,
        tmp_path,
        {},
        contracted_bundle=_bundle(),
        renderer_identities=[office],
        page_renderer_identities=[pages],
        font_probe=lambda font, **_kwargs: states[font],
        rebuild_candidate=rebuild,
        office_exporter=export,
        page_exporter=rasterize,
        blank_page_detector=lambda _pdf: [],
    )

    assert report["status"] == "passed"
    assert {font: evidence["state"] for font, evidence in report["fonts"].items()} == {
        "Available Sans": "available",
        "Missing Sans": "missing-or-unusable",
        "Unknown Sans": "unknown",
    }
    assert report["fonts"]["Unknown Sans"]["resolution"] == "render_verified"
    assert report["font_substitutions"] == {"Missing Sans": "Liberation Sans"}
    assert report["candidate"]["font_substitutions"] == report["font_substitutions"]
    assert report["candidate"]["font_evidence"] == report["fonts"]
    rebuilt_fonts = {run.font.name for paragraph in Document(candidate / "protocol.docx").paragraphs for run in paragraph.runs}
    assert rebuilt_fonts == {"Available Sans", "Liberation Sans", "Unknown Sans"}
    artifact = report["render"]["artifacts"][0]
    assert artifact["renderer"] == office
    assert artifact["page_renderer"] == pages
    assert artifact["font_substitutions"] == report["font_substitutions"]
    assert artifact["font_evidence"] == report["fonts"]
    for path_key, hash_key in (("docx", "docx_sha256"), ("pdf", "pdf_sha256")):
        assert hashlib.sha256((tmp_path / artifact[path_key]).read_bytes()).hexdigest() == artifact[hash_key]
    assert hashlib.sha256((tmp_path / artifact["pages"][0]["path"]).read_bytes()).hexdigest() == artifact["pages"][0]["sha256"]


def test_render_assurance_advances_ordered_adapters_with_governed_recovery_records(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    document = Document()
    document.add_paragraph("Complete candidate")
    document.save(candidate / "protocol.docx")
    original = (candidate / "protocol.docx").read_bytes()
    word = {"kind": "Microsoft Word", "path": "/controlled/word"}
    libreoffice = {"kind": "LibreOffice", "path": "/controlled/soffice"}
    poppler = {"kind": "pdftoppm", "path": "/controlled/pdftoppm"}
    pymupdf = {"kind": "pymupdf", "path": "python:pymupdf"}

    def export(docx, output_dir, identity, **_kwargs):
        if identity == word:
            raise RuntimeError("controlled office failure")
        pdf = output_dir / f"{docx.stem}.pdf"
        _write_text_pdf(pdf)
        return pdf

    def rasterize(_pdf, output_dir, identity, **_kwargs):
        if identity == poppler:
            raise RuntimeError("controlled page failure")
        output_dir.mkdir(parents=True, exist_ok=True)
        page = output_dir / "page-1.png"
        page.write_bytes(b"page image")
        return [page]

    report = render_assurance(
        ROOT,
        tmp_path,
        {},
        contracted_bundle=_bundle(),
        renderer_identities=[word, libreoffice],
        page_renderer_identities=[poppler, pymupdf],
        font_probe=lambda _font, **_kwargs: (True, "available"),
        office_exporter=export,
        page_exporter=rasterize,
        blank_page_detector=lambda _pdf: [],
    )

    assert report["status"] == "passed"
    assert (candidate / "protocol.docx").read_bytes() == original
    assert report["render"]["renderer_attempts"] == [
        {
            "adapter": word,
            "status": "failed",
            "recovery_class": "adapter_fault",
            "action": "advance_adapter",
            "issue": "controlled office failure",
        },
        {"adapter": libreoffice, "status": "passed"},
    ]
    assert report["render"]["page_renderer_attempts"] == [
        {
            "adapter": poppler,
            "status": "failed",
            "recovery_class": "adapter_fault",
            "action": "advance_adapter",
            "issue": "controlled page failure",
        },
        {"adapter": pymupdf, "status": "passed"},
    ]


def test_render_assurance_exhaustion_preserves_candidate_and_emits_one_diagnostic(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    document = Document()
    document.add_paragraph("Structurally valid candidate")
    document.save(candidate / "protocol.docx")
    original_hash = hashlib.sha256((candidate / "protocol.docx").read_bytes()).hexdigest()
    word = {"kind": "Microsoft Word", "path": "/controlled/word"}
    libreoffice = {"kind": "LibreOffice", "path": "/controlled/soffice"}

    report = render_assurance(
        ROOT,
        tmp_path,
        {},
        contracted_bundle=_bundle(),
        renderer_identities=[word, libreoffice],
        page_renderer_identities=[{"kind": "pymupdf", "path": "python:pymupdf"}],
        font_probe=lambda _font, **_kwargs: (True, "available"),
        office_exporter=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("controlled failure")),
        page_exporter=lambda *_args, **_kwargs: [],
    )

    assert report["status"] == "blocked"
    assert report["candidate"]["files"] == [{
        "path": "candidate/protocol.docx",
        "sha256": original_hash,
        "bytes": (candidate / "protocol.docx").stat().st_size,
    }]
    assert report["diagnostic"]["recovery_class"] == "adapter_fault"
    assert report["diagnostic"]["action"] == "preserve_candidate_and_stop"
    assert report["diagnostic"]["office_attempts"] == report["render"]["renderer_attempts"]
    assert report["diagnostic"]["page_attempts"] == []
    assert len(report["findings"]) == 1
