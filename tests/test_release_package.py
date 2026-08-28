import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import workflow
from hermes_e2e import _certified_release
from pypdf import PdfWriter
from quality import rasterize_pdf
import pytest
from workflow import (
    install_release,
    package_release,
    provision_fallback_stack,
    verify_installation,
)


ROOT = Path(__file__).resolve().parents[1]
PDFIUM_WHEEL = "pypdfium2-5.13.0-py3-none-macosx_13_0_arm64.whl"
PDFIUM_SHA256 = "da5c7b74eebf40b5c1fbe1de01aa1edc8827a79fb1efd999616bc20dcaf77ba4"


def test_release_packaging_refuses_an_uncommitted_release_owned_resource(tmp_path):
    dirty_resource = ROOT / "ticket-44-uncommitted-resource.txt"
    dirty_resource.write_text("not committed", encoding="utf-8")
    try:
        with pytest.raises(
            ValueError,
            match="Release-owned resources must be clean and committed: ticket-44-uncommitted-resource.txt",
        ):
            package_release(ROOT, tmp_path / "release.zip")
    finally:
        dirty_resource.unlink(missing_ok=True)


def test_release_provisions_its_one_pdf_renderer_offline(tmp_path, monkeypatch):
    skill_root = tmp_path / "clinical-document-generation"
    wheel_dir = skill_root / "assets/runtime-wheels"
    wheel_dir.mkdir(parents=True)
    shutil.copy2(ROOT / "assets/runtime-wheels" / PDFIUM_WHEEL, wheel_dir / PDFIUM_WHEEL)
    (skill_root / "RELEASE-MANIFEST.json").write_text(
        json.dumps({
            "inventory": {
                "pdf_page_renderer": {
                    "kind": "pypdfium2",
                    "version": "5.13.0",
                    "wheel": f"assets/runtime-wheels/{PDFIUM_WHEEL}",
                    "wheel_sha256": PDFIUM_SHA256,
                    "platform": "macosx_13_0_arm64",
                }
            }
        }),
        encoding="utf-8",
    )
    office = {
        "kind": "LibreOffice",
        "path": "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "source": "host prerequisite",
    }
    monkeypatch.setattr(workflow, "renderers", lambda **_kwargs: [office])

    result = provision_fallback_stack(skill_root)

    assert result == {
        "status": "passed",
        "renderer": office,
        "page_renderer": {
            "kind": "pypdfium2",
            "path": "python:pypdfium2",
            "module": "pypdfium2",
            "python_path": str(skill_root / "runtime/python"),
            "version": "5.13.0",
            "source": "release-owned runtime",
            "wheel": f"assets/runtime-wheels/{PDFIUM_WHEEL}",
            "wheel_sha256": PDFIUM_SHA256,
        },
        "provisioned": {"renderer": False, "page_renderer": True},
    }
    assert (skill_root / "runtime/python/pypdfium2/__init__.py").is_file()
    assert (skill_root / "runtime/python/pypdfium2_raw/libpdfium.dylib").is_file()
    assert not (skill_root / "runtime/LibreOffice.app").exists()
    assert json.loads((skill_root / "runtime/PDF-RENDERER.json").read_text()) == {
        "kind": "pypdfium2",
        "version": "5.13.0",
        "wheel": f"assets/runtime-wheels/{PDFIUM_WHEEL}",
        "wheel_sha256": PDFIUM_SHA256,
    }
    pdf = tmp_path / "one-page.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf.open("wb") as handle:
        writer.write(handle)

    pages = rasterize_pdf(pdf, tmp_path / "pages", result["page_renderer"])

    assert [page.name for page in pages] == ["page-1.png"]
    assert pages[0].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_release_package_contains_hashed_runtime_and_excludes_development_data(tmp_path):
    archive_path = tmp_path / "clinical-document-generation-release.zip"
    result = package_release(ROOT, archive_path)

    assert result["status"] == "passed"
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        prefix = "clinical-document-generation/"
        manifest_name = prefix + "RELEASE-MANIFEST.json"
        manifest = json.loads(archive.read(manifest_name))

        assert prefix + "SKILL.md" in names
        assert prefix + "scripts/workflow.py" in names
        assert prefix + "requirements.txt" in names
        assert prefix + "assets/fallback-fonts/LiberationSans-Regular.ttf" in names
        assert prefix + "assets/fallback-fonts/LICENSE_LIBERATION" in names
        assert prefix + "assets/client-templates/reference/advarra-icf-reference.docx" in names
        assert prefix + f"assets/runtime-wheels/{PDFIUM_WHEEL}" in names
        assert not any(
            "/runtime-wheels/" in name and not name.endswith(PDFIUM_WHEEL)
            for name in names
        )
        assert not any(".test-venv/" in name or ".hermes/" in name for name in names)
        assert not any("/runtime/" in name or name.endswith("/INSTALLATION-ASSURANCE.json") for name in names)
        assert not any(".pytest_cache/" in name or "/source-data/" in name or "/patient-data/" in name for name in names)
        assert not any("/tests/" in name or name.endswith("/artifact.md") for name in names)
        assert {entry["path"] for entry in manifest["files"]} == {
            name.removeprefix(prefix) for name in names if name != manifest_name
        }
        assert manifest["package_fingerprint"] == result["package_fingerprint"]
        assert manifest["git_commit"] == subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert result["git_commit"] == manifest["git_commit"]
        assert manifest["installation"]["entrypoint"] == "SKILL.md"
        assert manifest["inventory"]["implementation"]
        bundles = manifest["inventory"]["contracted_template_bundles"]
        governed = manifest["inventory"]["governed_resources"]
        assert len(bundles) == 5
        assert "templates_and_contracts" not in manifest["inventory"]
        assert set(governed) == {
            path
            for bundle in bundles
            for path in bundle["resource_hashes"]
        }
        packaged_hashes = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
        for bundle in bundles:
            assert all(packaged_hashes[path] == digest for path, digest in bundle["resource_hashes"].items())
        assert manifest["inventory"]["font_fallbacks"]["Noto Sans Symbols"] == ["Liberation Sans"]
        assert manifest["inventory"]["pdf_page_renderer"] == {
            "kind": "pypdfium2",
            "version": "5.13.0",
            "wheel": f"assets/runtime-wheels/{PDFIUM_WHEEL}",
            "wheel_sha256": PDFIUM_SHA256,
            "platform": "macosx_13_0_arm64",
        }
        assert "page_renderer_fallbacks" not in manifest["inventory"]
        assert "page_renderer_at_packaging" not in manifest["inventory"]
        assert manifest["installation"]["required_external_tools"] == [
            "Microsoft Word or LibreOffice"
        ]
        assert "atomic" in manifest["installation"]["activation"]
        assert manifest["excluded_classes"]


def test_release_package_can_be_installed_and_imported_without_checkout(tmp_path):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    install_dir = tmp_path / "hermes-skills"
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(install_dir)
    skill_dir = install_dir / "clinical-document-generation"
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", "scripts/workflow.py", "scripts/contracts.py", "scripts/drafting.py", "scripts/rendering.py", "scripts/quality.py", "scripts/prs_xml.py"],
        cwd=skill_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (skill_dir / "agents/openai.yaml").is_file()
    certified_workflow, identity = _certified_release(skill_dir)
    assert callable(certified_workflow.run_desktop_operation)
    assert identity["package_fingerprint"]
    assert identity["source"] == "release_certification_candidate"


def test_failed_installation_smoke_keeps_the_active_skill_unchanged(tmp_path):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    skills_dir = tmp_path / "skills"
    active = skills_dir / "clinical-document-generation"
    active.mkdir(parents=True)
    (active / "marker.txt").write_text("previous verified release", encoding="utf-8")

    result = install_release(
        archive_path,
        skills_dir,
        verifier=lambda _candidate: {"status": "blocked", "findings": [{"issue": "smoke failed"}]},
        provisioner=lambda _candidate: {"status": "passed"},
    )

    assert result["status"] == "blocked"
    assert (active / "marker.txt").read_text(encoding="utf-8") == "previous verified release"


def test_verified_installation_atomically_retains_the_previous_release(tmp_path):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    skills_dir = tmp_path / "skills"
    active = skills_dir / "clinical-document-generation"
    active.mkdir(parents=True)
    (active / "marker.txt").write_text("previous verified release", encoding="utf-8")

    def verified(candidate):
        return {"status": "passed", "renderer": {"kind": "LibreOffice", "path": str(candidate / "runtime/soffice")}}

    result = install_release(
        archive_path,
        skills_dir,
        verifier=verified,
        provisioner=lambda _candidate: {"status": "passed", "renderer": {"kind": "LibreOffice"}},
    )

    assert result["status"] == "passed"
    assert (active / "SKILL.md").is_file()
    assert (skills_dir / ".clinical-document-generation.previous/marker.txt").read_text(encoding="utf-8") == "previous verified release"
    assurance = json.loads((active / "INSTALLATION-ASSURANCE.json").read_text(encoding="utf-8"))
    assert assurance["assurance"]["renderer"]["path"] == str(active / "runtime/soffice")


def test_installation_smoke_uses_public_assurance_with_the_release_owned_page_renderer(tmp_path, monkeypatch):
    bundled = {
        "kind": "pypdfium2",
        "path": "python:pypdfium2",
        "module": "pypdfium2",
        "python_path": str(tmp_path / "runtime/python"),
        "source": "release-owned runtime",
    }
    observed = {}
    monkeypatch.setattr(workflow, "_manifest_integrity", lambda _root: [])
    monkeypatch.setattr(workflow, "renderers", lambda **_kwargs: [{"kind": "LibreOffice", "source": "verified fallback stack"}])
    monkeypatch.setattr(workflow, "page_renderers", lambda **_kwargs: [bundled])

    def fake_assurance(_root, revision_dir, _reference, **kwargs):
        observed["pages"] = kwargs["page_renderer_identities"]
        observed["candidate"] = (revision_dir / "candidate/installation-smoke.docx").is_file()
        document = workflow.Document(revision_dir / "candidate/installation-smoke.docx")
        observed["fonts"] = {
            run.font.name
            for paragraph in document.paragraphs
            for run in paragraph.runs
            if run.font.name
        }
        return {
            "schema_version": "render-assurance/v1",
            "status": "passed",
            "fonts": {},
            "font_substitutions": {},
            "candidate": {"files": []},
            "render": {
                "status": "passed",
                "renderer": {"kind": "LibreOffice", "source": "verified fallback stack"},
                "page_renderer": bundled,
                "renderer_attempts": [],
                "page_renderer_attempts": [],
                "artifacts": [],
                "findings": [],
            },
            "findings": [],
        }

    monkeypatch.setattr(workflow, "render_assurance", fake_assurance)
    fallback_fonts = tmp_path / "assets/fallback-fonts"
    fallback_fonts.mkdir(parents=True)
    (fallback_fonts / "font.ttf").write_bytes(b"font")

    result = verify_installation(tmp_path)

    assert result["status"] == "passed"
    assert observed["pages"] == [bundled]
    assert observed["candidate"] is True
    assert observed["fonts"] == {"Liberation Sans", "Liberation Serif", "Liberation Mono"}
