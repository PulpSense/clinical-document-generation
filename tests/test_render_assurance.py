import hashlib
import zipfile
from pathlib import Path

from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from quality import RECOVERY_POLICIES, page_renderers, rasterize_pdf, render_assurance


ROOT = Path(__file__).resolve().parents[1]


def test_release_owned_pdfium_is_the_only_page_renderer(tmp_path):
    runtime = tmp_path / "runtime"
    runtime_python = runtime / "python"
    (runtime_python / "pypdfium2").mkdir(parents=True)
    (runtime_python / "pypdfium2/__init__.py").write_text("", encoding="utf-8")
    (runtime_python / "pypdfium2_raw").mkdir()
    (runtime_python / "pypdfium2_raw/__init__.py").write_text("", encoding="utf-8")
    wheel = tmp_path / "assets/runtime-wheels/pdfium.whl"
    wheel.parent.mkdir(parents=True)
    wheel.write_bytes(b"governed wheel")
    files = {
        "pypdfium2/__init__.py": hashlib.sha256(b"").hexdigest(),
        "pypdfium2_raw/__init__.py": hashlib.sha256(b"").hexdigest(),
    }
    (tmp_path / "RELEASE-MANIFEST.json").write_text(
        __import__("json").dumps({"inventory": {"pdf_page_renderer": {
            "kind": "pypdfium2", "version": "5.13.0",
            "wheel": "assets/runtime-wheels/pdfium.whl",
            "wheel_sha256": hashlib.sha256(b"governed wheel").hexdigest(),
            "platform": "macosx_13_0_arm64",
        }}}), encoding="utf-8",
    )
    (runtime / "PDF-RENDERER.json").write_text(
        __import__("json").dumps({
            "kind": "pypdfium2", "version": "5.13.0",
            "wheel": "assets/runtime-wheels/pdfium.whl",
            "wheel_sha256": hashlib.sha256(b"governed wheel").hexdigest(),
            "platform": "macosx_13_0_arm64", "installed_files": files,
        }),
        encoding="utf-8",
    )

    assert page_renderers(
        environment={"PATH": "/usr/bin:/opt/homebrew/bin"},
        skill_root=tmp_path,
    ) == [
        {
            "kind": "pypdfium2",
            "path": "python:pypdfium2",
            "module": "pypdfium2",
            "python_path": str(runtime_python),
            "version": "5.13.0",
            "source": "release-owned runtime",
            "wheel": "assets/runtime-wheels/pdfium.whl",
            "wheel_sha256": hashlib.sha256(b"governed wheel").hexdigest(),
        }
    ]


def test_pdfium_rasterization_does_not_require_optional_pillow(tmp_path, monkeypatch):
    pdf = tmp_path / "one-page.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with pdf.open("wb") as handle:
        writer.write(handle)
    monkeypatch.setitem(__import__("sys").modules, "PIL", None)
    runtime_python = tmp_path / "runtime-python"
    with zipfile.ZipFile(ROOT / "assets/runtime-wheels/pypdfium2-5.13.0-py3-none-macosx_13_0_arm64.whl") as wheel:
        wheel.extractall(runtime_python)

    pages = rasterize_pdf(pdf, tmp_path / "pages", {
        "kind": "pypdfium2", "path": "python:pypdfium2", "module": "pypdfium2",
        "python_path": str(runtime_python),
    })

    assert pages[0].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


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


def _structural_validation(revision_dir: Path, *expected_files: str) -> dict:
    return {
        "status": "structurally_valid",
        "expected_files": list(expected_files),
        "candidate_files": [
            {
                "path": path.relative_to(revision_dir).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
            for path in sorted((revision_dir / "candidate").glob("*"))
            if path.is_file()
        ],
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
    pages = {"kind": "pypdfium2", "path": "python:pypdfium2"}
    report = render_assurance(
        ROOT,
        tmp_path,
        {},
        contracted_bundle=_bundle(),
        structural_validation=_structural_validation(tmp_path, "protocol.docx"),
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
    pdfium = {"kind": "pypdfium2", "path": "python:pypdfium2"}

    def export(docx, output_dir, identity, **_kwargs):
        if identity == word:
            raise RuntimeError("controlled office failure")
        pdf = output_dir / f"{docx.stem}.pdf"
        _write_text_pdf(pdf)
        return pdf

    def rasterize(_pdf, output_dir, identity, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        page = output_dir / "page-1.png"
        page.write_bytes(b"page image")
        return [page]

    report = render_assurance(
        ROOT,
        tmp_path,
        {},
        contracted_bundle=_bundle(),
        structural_validation=_structural_validation(tmp_path, "protocol.docx"),
        renderer_identities=[word, libreoffice],
        page_renderer_identities=[pdfium],
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
        {"adapter": pdfium, "status": "passed"},
    ]


def test_render_assurance_stops_when_the_one_pdfium_renderer_fails(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    document = Document()
    document.add_paragraph("Complete candidate")
    document.save(candidate / "protocol.docx")
    pdfium = {"kind": "pypdfium2", "path": "python:pypdfium2"}
    unapproved_host_renderer = {
        "kind": "pdftoppm",
        "path": "/controlled/pdftoppm",
    }

    def export(docx, output_dir, _identity, **_kwargs):
        pdf = output_dir / f"{docx.stem}.pdf"
        _write_text_pdf(pdf)
        return pdf

    used = []

    def rasterize(_pdf, output_dir, identity, **_kwargs):
        used.append(identity)
        if identity == pdfium:
            raise RuntimeError("controlled PDFium failure")
        output_dir.mkdir(parents=True, exist_ok=True)
        page = output_dir / "page-1.png"
        page.write_bytes(b"unapproved page image")
        return [page]

    report = render_assurance(
        ROOT,
        tmp_path,
        {},
        contracted_bundle=_bundle(),
        structural_validation=_structural_validation(tmp_path, "protocol.docx"),
        renderer_identities=[{"kind": "LibreOffice", "path": "/controlled/soffice"}],
        page_renderer_identities=[pdfium, unapproved_host_renderer],
        font_probe=lambda _font, **_kwargs: (True, "available"),
        office_exporter=export,
        page_exporter=rasterize,
        blank_page_detector=lambda _pdf: [],
    )

    assert report["status"] == "blocked"
    assert used == [pdfium]
    assert report["render"]["page_renderer_attempts"] == [{
        "adapter": pdfium,
        "status": "failed",
        "recovery_class": "adapter_fault",
        "action": "stop",
        "issue": "controlled PDFium failure",
    }]
    assert report["findings"] == [{
        "category": "renderer",
        "field": "rendering",
        "issue": "The release-owned pypdfium2 page renderer failed.",
        "recovery_class": "adapter_fault",
        "action": "stop",
    }]


def test_render_assurance_exhaustion_preserves_candidate_and_emits_one_diagnostic(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    document = Document()
    document.add_paragraph("Structurally valid candidate")
    document.save(candidate / "protocol.docx")
    stale_pdf = tmp_path / "rendered/protocol.pdf"
    stale_page = tmp_path / "rendered/protocol/page-1.png"
    stale_page.parent.mkdir(parents=True)
    stale_pdf.write_bytes(b"stale pdf")
    stale_page.write_bytes(b"stale page")
    original_hash = hashlib.sha256((candidate / "protocol.docx").read_bytes()).hexdigest()
    word = {"kind": "Microsoft Word", "path": "/controlled/word"}
    libreoffice = {"kind": "LibreOffice", "path": "/controlled/soffice"}

    report = render_assurance(
        ROOT,
        tmp_path,
        {},
        contracted_bundle=_bundle(),
        structural_validation=_structural_validation(tmp_path, "protocol.docx"),
        renderer_identities=[word, libreoffice],
        page_renderer_identities=[{"kind": "pypdfium2", "path": "python:pypdfium2"}],
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
    assert report["diagnostic"]["action"] == RECOVERY_POLICIES["adapter_fault"]
    assert report["diagnostic"]["outcome"] == "adapters_exhausted"
    assert report["diagnostic"]["candidate_disposition"] == "preserved"
    assert report["diagnostic"]["office_attempts"] == report["render"]["renderer_attempts"]
    assert report["diagnostic"]["page_attempts"] == []
    assert len(report["findings"]) == 1
    assert not stale_pdf.exists()
    assert not stale_page.exists()


def test_render_assurance_reuses_a_substituted_candidate_without_oscillating(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    document = Document()
    run = document.add_paragraph().add_run("Missing font")
    run.font.name = "Missing Sans"
    document.save(candidate / "protocol.docx")
    rebuilds = []

    def rebuild(substitutions):
        rebuilds.append(dict(substitutions))
        rebuilt = Document(candidate / "protocol.docx")
        for paragraph in rebuilt.paragraphs:
            for run in paragraph.runs:
                if run.font.name in substitutions:
                    run.font.name = substitutions[run.font.name]
        rebuilt.save(candidate / "protocol.docx")
        return {"status": "passed"}

    def probe(font, **_kwargs):
        return (False, "missing") if font == "Missing Sans" else (True, "available")

    def fail_export(*_args, **_kwargs):
        raise RuntimeError("controlled failure")

    first = render_assurance(
        ROOT,
        tmp_path,
        {},
        contracted_bundle=_bundle(),
        structural_validation=_structural_validation(tmp_path, "protocol.docx"),
        renderer_identities=[{"kind": "LibreOffice", "path": "/controlled/soffice"}],
        page_renderer_identities=[{"kind": "pypdfium2", "path": "python:pypdfium2"}],
        font_probe=probe,
        rebuild_candidate=rebuild,
        office_exporter=fail_export,
    )
    substituted_hash = hashlib.sha256((candidate / "protocol.docx").read_bytes()).hexdigest()
    second = render_assurance(
        ROOT,
        tmp_path,
        {},
        contracted_bundle=_bundle(),
        structural_validation=_structural_validation(tmp_path, "protocol.docx"),
        candidate_font_substitutions=first["font_substitutions"],
        renderer_identities=[{"kind": "LibreOffice", "path": "/controlled/soffice"}],
        page_renderer_identities=[{"kind": "pypdfium2", "path": "python:pypdfium2"}],
        font_probe=probe,
        rebuild_candidate=rebuild,
        office_exporter=fail_export,
    )

    assert first["font_substitutions"] == second["font_substitutions"] == {"Missing Sans": "Liberation Sans"}
    assert rebuilds == [{"Missing Sans": "Liberation Sans"}]
    assert hashlib.sha256((candidate / "protocol.docx").read_bytes()).hexdigest() == substituted_hash


def test_render_assurance_rejects_an_incomplete_branch_candidate(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    Document().save(candidate / "protocol.docx")

    report = render_assurance(
        ROOT,
        tmp_path,
        {},
        contracted_bundle=_bundle(),
        structural_validation=_structural_validation(
            tmp_path,
            "protocol.docx",
            "icf.docx",
            "study.xml",
        ),
        renderer_identities=[],
        page_renderer_identities=[],
    )

    assert report["status"] == "blocked"
    assert report["render"]["status"] == "not_run"
    assert report["findings"][0]["recovery_class"] == "document_structure_defect"
    assert "complete structurally validated" in report["findings"][0]["issue"]


def test_render_assurance_revalidates_the_exact_candidate_after_font_substitution(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    document = Document()
    run = document.add_paragraph().add_run("Missing font")
    run.font.name = "Missing Sans"
    document.save(candidate / "protocol.docx")
    (candidate / "study.xml").write_text("<study />", encoding="utf-8")

    def rebuild(_substitutions):
        (candidate / "study.xml").unlink()
        return {"status": "passed"}

    report = render_assurance(
        ROOT,
        tmp_path,
        {},
        contracted_bundle=_bundle(),
        structural_validation=_structural_validation(
            tmp_path,
            "protocol.docx",
            "study.xml",
        ),
        renderer_identities=[{"kind": "LibreOffice", "path": "/controlled/soffice"}],
        page_renderer_identities=[{"kind": "pypdfium2", "path": "python:pypdfium2"}],
        font_probe=lambda font, **_kwargs: (False, "missing") if font == "Missing Sans" else (True, "available"),
        rebuild_candidate=rebuild,
    )

    assert report["status"] == "blocked"
    assert report["render"]["status"] == "not_run"
    assert report["findings"][0]["recovery_class"] == "document_structure_defect"
    assert report["structural_validation"]["revalidated_after_substitution"] is False
