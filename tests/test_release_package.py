import json
import subprocess
import sys
import zipfile
from pathlib import Path

import workflow
from workflow import install_release, package_release, verify_installation


ROOT = Path(__file__).resolve().parents[1]


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
        assert not any(".test-venv/" in name or ".hermes/" in name for name in names)
        assert not any("/runtime/" in name or name.endswith("/INSTALLATION-ASSURANCE.json") for name in names)
        assert not any(".pytest_cache/" in name or "/source-data/" in name or "/patient-data/" in name for name in names)
        assert not any("/tests/" in name or name.endswith("/artifact.md") for name in names)
        assert {entry["path"] for entry in manifest["files"]} == {
            name.removeprefix(prefix) for name in names if name != manifest_name
        }
        assert manifest["package_fingerprint"] == result["package_fingerprint"]
        assert manifest["installation"]["entrypoint"] == "SKILL.md"
        assert manifest["inventory"]["implementation"]
        assert manifest["inventory"]["font_fallbacks"]["Noto Sans Symbols"] == ["Liberation Sans"]
        assert manifest["inventory"]["page_renderer_fallbacks"][:5] == [
            "pdftoppm",
            "pdftocairo",
            "mutool",
            "ghostscript",
            "imagemagick",
        ]
        assert manifest["installation"]["required_external_tools"] == []
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


def test_installation_smoke_requires_the_release_owned_page_renderer(tmp_path, monkeypatch):
    bundled = {
        "kind": "pymupdf",
        "path": "python:pymupdf",
        "module": "pymupdf",
        "python_path": str(tmp_path / "runtime/python"),
        "source": "verified fallback stack",
    }
    host = {"kind": "pdftoppm", "path": "/usr/bin/pdftoppm", "source": "PATH"}
    observed = {}
    monkeypatch.setattr(workflow, "_manifest_integrity", lambda _root: [])
    monkeypatch.setattr(workflow, "renderers", lambda **_kwargs: [{"kind": "LibreOffice", "source": "verified fallback stack"}])
    monkeypatch.setattr(workflow, "page_renderers", lambda **_kwargs: [host, bundled])

    def fake_preflight(_root, _reference, **kwargs):
        observed["pages"] = kwargs["page_renderer_identities"]
        return {
            "status": "passed",
            "renderer": {"kind": "LibreOffice", "source": "verified fallback stack"},
            "renderer_candidates": [],
            "page_renderer": bundled,
            "fonts": {},
            "smoke": {"status": "passed"},
            "findings": [],
        }

    monkeypatch.setattr(workflow, "preflight", fake_preflight)
    fallback_fonts = tmp_path / "assets/fallback-fonts"
    fallback_fonts.mkdir(parents=True)
    (fallback_fonts / "font.ttf").write_bytes(b"font")

    result = verify_installation(tmp_path)

    assert result["status"] == "passed"
    assert observed["pages"] == [bundled]
