import json
import os
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
    bind_release_certification,
    install_release,
    package_release,
    provision_fallback_stack,
    verify_installation,
)


ROOT = Path(__file__).resolve().parents[1]
PDFIUM_WHEEL = "pypdfium2-5.13.0-py3-none-macosx_13_0_arm64.whl"
PDFIUM_SHA256 = "da5c7b74eebf40b5c1fbe1de01aa1edc8827a79fb1efd999616bc20dcaf77ba4"


def _certify_archive(archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("clinical-document-generation/RELEASE-MANIFEST.json"))
    identity = {
        "package_fingerprint": manifest["package_fingerprint"],
        "git_commit": manifest["git_commit"],
    }
    configurations = {
        fixture: json.loads((ROOT / f"tests/fixtures/release-certification/{fixture}/fixture.json").read_text())["hermes_configuration"]
        for fixture in workflow.CERTIFICATION_CASE_ORDER
    }

    def passing_case(fixture: str) -> dict:
        output_paths = (
            ["output/protocol.docx"]
            if fixture == "retrospective"
            else ["output/protocol.docx", "output/icf.docx", "output/study.xml"]
        )
        outputs = {
            path: {"path": path, "sha256": "c" * 64, "bytes": 100, "confirmed": True}
            for path in output_paths
        }
        visual_artifacts = [Path(path).stem for path in output_paths if path.endswith(".docx")]
        gates = {gate: "passed" for gate in workflow.CERTIFICATION_GATES}
        if fixture == "retrospective":
            gates["prs_xml"] = "not_applicable"
        return {
            "fixture_id": fixture,
            "status": "passed",
            "findings": [],
            "elapsed_seconds": 600.0,
            "desktop_operation_elapsed_seconds": 599.0,
            "under_15_minutes": True,
            "within_approved_runtime": True,
            "report_sha256": "d" * 64,
            "release_identity": identity,
            "hermes_configuration_sha256": workflow.sha256_value(configurations[fixture]),
            "model_identifiers": ["gpt-5.6-sol"],
            "output_evidence": list(outputs.values()),
            "gate_statuses": gates,
            "layout_checks": {"natural_section_3_flow": "passed", "no_orphan_headings": "passed"},
            "visual_qa": {
                artifact: {
                    "status": "passed",
                    "request_sha256": "e" * 64,
                    "response_sha256": "f" * 64,
                    "producer_model_id": "gpt-5.6-sol",
                    "docx_sha256": outputs[f"output/{artifact}.docx"]["sha256"],
                    "pdf_sha256": "1" * 64,
                    "page_count": 1,
                    "page_sha256": ["2" * 64],
                    "checks": sorted(workflow.CERTIFICATION_VISUAL_CHECKS),
                }
                for artifact in visual_artifacts
            },
            "render_assurance": {
                "active_renderer": {"kind": "LibreOffice"},
                "active_page_renderer": {
                    **workflow.PDF_PAGE_RENDERER,
                    "source": "release-owned runtime",
                },
            },
            "contracted_template_bundle_identity": "3" * 64,
            "layout_preservation_baseline_identity": "4" * 64,
        }

    report = {
        "schema_version": "release-certification-corpus/v1",
        "status": "passed",
        "certification_scope": "complete_three_case_corpus",
        "release_identity": identity,
        "hermes_configurations": configurations,
        "preflight_evidence_sha256": "a" * 64,
        "layout_preservation_evidence": {
            "status": "passed",
            "returncode": 0,
            "sha256": "b" * 64,
            "started_at": "2026-08-28T00:00:00+00:00",
            "completed_at": "2026-08-28T00:01:00+00:00",
            "coverage": [
                "Prospective/Advarra", "Prospective/Sterling",
                "Ambispective/Advarra", "Ambispective/Sterling",
                "Retrospective/Protocol",
            ],
        },
        "case_order": ["retrospective", "ambispective-sterling", "prospective-advarra"],
        "cases": [passing_case(fixture) for fixture in workflow.CERTIFICATION_CASE_ORDER],
        "findings": [],
        "completed_at": "2026-08-28T00:00:00+00:00",
    }
    report_path = archive_path.with_suffix(".certification.json")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    bind_release_certification(archive_path, report_path)


def _hermes_config(skills_dir: Path) -> Path:
    path = skills_dir.parent / "config.yaml"
    path.write_text(
        "model:\n  default: gpt-5.6-sol\n"
        "agent:\n  max_turns: 500\n  reasoning_effort: medium\n"
        "skills:\n  external_dirs:\n    - " + str(skills_dir / "clinical-document-generation") + "\n"
        "  clinical_document_generation:\n"
        "    source: clinical-release-certification\n"
        "    max_turns: 80\n"
        "    skill: clinical-document-drafting\n"
        "    safe_mode: true\n"
        "    model_identifier: gpt-5.6-sol\n"
        "    reasoning_configuration: Hermes Desktop governed default\n",
        encoding="utf-8",
    )
    return path


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
    marker = json.loads((skill_root / "runtime/PDF-RENDERER.json").read_text())
    installed_files = marker.pop("installed_files")
    assert marker == {
        "kind": "pypdfium2",
        "version": "5.13.0",
        "wheel": f"assets/runtime-wheels/{PDFIUM_WHEEL}",
        "wheel_sha256": PDFIUM_SHA256,
        "platform": "macosx_13_0_arm64",
    }
    assert installed_files["pypdfium2/__init__.py"]
    assert installed_files["pypdfium2_raw/libpdfium.dylib"]
    pdf = tmp_path / "one-page.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf.open("wb") as handle:
        writer.write(handle)

    pages = rasterize_pdf(pdf, tmp_path / "pages", result["page_renderer"])

    assert [page.name for page in pages] == ["page-1.png"]
    assert pages[0].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_release_renderer_rejects_and_repairs_tampered_runtime(tmp_path, monkeypatch):
    skill_root = tmp_path / "clinical-document-generation"
    wheel_dir = skill_root / "assets/runtime-wheels"
    wheel_dir.mkdir(parents=True)
    shutil.copy2(ROOT / "assets/runtime-wheels" / PDFIUM_WHEEL, wheel_dir / PDFIUM_WHEEL)
    (skill_root / "RELEASE-MANIFEST.json").write_text(json.dumps({
        "inventory": {"pdf_page_renderer": {
            "kind": "pypdfium2",
            "version": "5.13.0",
            "wheel": f"assets/runtime-wheels/{PDFIUM_WHEEL}",
            "wheel_sha256": PDFIUM_SHA256,
            "platform": "macosx_13_0_arm64",
        }}
    }), encoding="utf-8")
    monkeypatch.setattr(workflow, "renderers", lambda **_kwargs: [{
        "kind": "LibreOffice", "path": "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    }])

    assert provision_fallback_stack(skill_root)["status"] == "passed"
    target = skill_root / "runtime/python/pypdfium2/__init__.py"
    expected = target.read_bytes()
    target.write_text("tampered", encoding="utf-8")

    assert workflow.page_renderers(skill_root=skill_root) == []
    repaired = provision_fallback_stack(skill_root)

    assert repaired["status"] == "passed"
    assert repaired["provisioned"]["page_renderer"] is True
    assert target.read_bytes() == expected


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
        assert not any(name.startswith(prefix + "docs/") for name in names)
        assert not any(name == prefix + ".gitignore" for name in names)
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
        assert set(manifest["inventory"]["implementation"]) == {
            f"scripts/{name}" for name in workflow.PRODUCTION_MODULES
        }
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
        env={**os.environ, "PYTHONPYCACHEPREFIX": str(tmp_path / "pycache")},
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
    _certify_archive(archive_path)
    skills_dir = tmp_path / "skills"
    active = skills_dir / "clinical-document-generation"
    active.mkdir(parents=True)
    (active / "marker.txt").write_text("previous verified release", encoding="utf-8")

    result = install_release(
        archive_path,
        skills_dir,
        hermes_config_path=_hermes_config(skills_dir),
        verifier=lambda _candidate: {"status": "blocked", "findings": [{"issue": "smoke failed"}]},
        provisioner=lambda _candidate: {"status": "passed"},
    )

    assert result["status"] == "blocked"
    assert (active / "marker.txt").read_text(encoding="utf-8") == "previous verified release"


def test_verified_installation_atomically_retains_the_previous_release(tmp_path):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    _certify_archive(archive_path)
    skills_dir = tmp_path / "skills"
    active = skills_dir / "clinical-document-generation"
    active.mkdir(parents=True)
    (active / "marker.txt").write_text("previous verified release", encoding="utf-8")

    def verified(candidate):
        return {"status": "passed", "renderer": {"kind": "LibreOffice", "path": str(candidate / "runtime/soffice")}}

    result = install_release(
        archive_path,
        skills_dir,
        hermes_config_path=_hermes_config(skills_dir),
        verifier=verified,
        provisioner=lambda _candidate: {"status": "passed", "renderer": {"kind": "LibreOffice"}},
    )

    assert result["status"] == "passed"
    assert (active / "SKILL.md").is_file()
    assert (skills_dir / ".clinical-document-generation.previous/marker.txt").read_text(encoding="utf-8") == "previous verified release"
    assurance = json.loads((active / "INSTALLATION-ASSURANCE.json").read_text(encoding="utf-8"))
    assert assurance["assurance"]["renderer"]["path"] == str(active / "runtime/soffice")
    promotion = json.loads((active / "PROMOTION-RECORD.json").read_text(encoding="utf-8"))
    assert promotion["status"] == "active"
    assert promotion["package_fingerprint"]
    assert promotion["certification"]["status"] == "passed"
    assert promotion["certification"]["model_identifiers"] == ["gpt-5.6-sol"]
    assert promotion["hermes_discovery"] == str(active)


def test_unsigned_or_unlisted_release_cannot_displace_active(tmp_path):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    skills_dir = tmp_path / "skills"
    active = skills_dir / "clinical-document-generation"
    active.mkdir(parents=True)
    (active / "marker.txt").write_text("active", encoding="utf-8")

    unsigned = install_release(
        archive_path,
        skills_dir,
        hermes_config_path=_hermes_config(skills_dir),
        verifier=lambda _candidate: {"status": "passed"},
        provisioner=lambda _candidate: {"status": "passed"},
    )

    assert unsigned["status"] == "blocked"
    assert unsigned["stage"] == "promotion_eligibility"
    assert (active / "marker.txt").read_text(encoding="utf-8") == "active"

    _certify_archive(archive_path)
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr("clinical-document-generation/unlisted.txt", "unexpected")
    unlisted = install_release(
        archive_path,
        skills_dir,
        hermes_config_path=_hermes_config(skills_dir),
        verifier=lambda _candidate: {"status": "passed"},
        provisioner=lambda _candidate: {"status": "passed"},
    )

    assert unlisted["status"] == "blocked"
    assert any("Unlisted packaged files" in finding["issue"] for finding in unlisted["findings"])
    assert (active / "marker.txt").read_text(encoding="utf-8") == "active"


def test_skeletal_certification_and_normalized_zip_alias_are_rejected(tmp_path):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("clinical-document-generation/RELEASE-MANIFEST.json"))
    skeletal = tmp_path / "skeletal.json"
    skeletal.write_text(json.dumps({
        "schema_version": "release-certification-corpus/v1",
        "status": "passed",
        "certification_scope": "complete_three_case_corpus",
        "release_identity": {
            "git_commit": manifest["git_commit"],
            "package_fingerprint": manifest["package_fingerprint"],
        },
        "findings": [],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="does not pass and bind"):
        bind_release_certification(archive_path, skeletal)

    _certify_archive(archive_path)
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr(
            "clinical-document-generation/./RELEASE-CERTIFICATION.json",
            b"{}",
        )


def test_certification_binding_rejects_nested_identity_mutations(tmp_path):
    raw_archive = tmp_path / "raw.zip"
    package_release(ROOT, raw_archive)
    template_archive = tmp_path / "template.zip"
    shutil.copy2(raw_archive, template_archive)
    _certify_archive(raw_archive)
    report_path = raw_archive.with_suffix(".certification.json")
    baseline = json.loads(report_path.read_text(encoding="utf-8"))

    mutations = (
        lambda report: report["layout_preservation_evidence"].update(status="failed"),
        lambda report: report["cases"][0]["visual_qa"]["protocol"].update(producer_model_id="other-model"),
        lambda report: report["cases"][0]["render_assurance"]["active_page_renderer"].update(version="0.0.0"),
        lambda report: report.update(completed_at="not-a-timestamp"),
        lambda report: report["cases"][0].update(report_sha256="z" * 64),
        lambda report: report["hermes_configurations"]["retrospective"].update(layout_preservation_notes=["mutated"]),
    )
    for index, mutate in enumerate(mutations):
        candidate = tmp_path / f"candidate-{index}.zip"
        shutil.copy2(template_archive, candidate)
        report = json.loads(json.dumps(baseline))
        mutate(report)
        mutated_report = tmp_path / f"mutated-{index}.json"
        mutated_report.write_text(json.dumps(report), encoding="utf-8")

        with pytest.raises(ValueError, match="does not pass and bind"):
            bind_release_certification(candidate, mutated_report)
    skills_dir = tmp_path / "skills"
    with pytest.raises(ValueError, match="duplicate normalized target"):
        install_release(
            archive_path,
            skills_dir,
            hermes_config_path=_hermes_config(skills_dir),
            verifier=lambda _candidate: {"status": "passed"},
            provisioner=lambda _candidate: {"status": "passed"},
        )

def test_incompatible_hermes_discovery_stops_before_activation(tmp_path):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    _certify_archive(archive_path)
    skills_dir = tmp_path / "skills"
    active = skills_dir / "clinical-document-generation"
    active.mkdir(parents=True)
    (active / "marker.txt").write_text("active", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("skills:\n  external_dirs:\n    - /editable/clinical-document-generation\n", encoding="utf-8")

    result = install_release(
        archive_path,
        skills_dir,
        hermes_config_path=config,
        verifier=lambda _candidate: {"status": "passed"},
        provisioner=lambda _candidate: {"status": "passed"},
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "promotion_eligibility"
    assert result["findings"][-1]["field"] == "hermes_configuration"
    assert (active / "marker.txt").read_text(encoding="utf-8") == "active"


def test_one_rollback_operation_verifies_previous_and_quarantines_active(tmp_path):
    skills_dir = tmp_path / "skills"
    active = skills_dir / "clinical-document-generation"
    previous = skills_dir / ".clinical-document-generation.previous"
    for release, fingerprint, marker in (
        (active, "suspect-fingerprint", "suspect"),
        (previous, "verified-fingerprint", "verified previous"),
    ):
        release.mkdir(parents=True)
        (release / "marker.txt").write_text(marker, encoding="utf-8")
        (release / "RELEASE-MANIFEST.json").write_text(
            json.dumps({"package_fingerprint": fingerprint}),
            encoding="utf-8",
        )
    historical_revision = skills_dir / "runs/revision-1.json"
    historical_revision.parent.mkdir()
    historical_revision.write_text('{"package_fingerprint":"suspect-fingerprint"}', encoding="utf-8")
    verified = []

    result = workflow.rollback_release(
        skills_dir,
        verifier=lambda release: verified.append(release) or {"status": "passed"},
    )

    assert result["status"] == "passed"
    assert result["stage"] == "rolled_back"
    assert verified == [previous]
    assert (active / "marker.txt").read_text(encoding="utf-8") == "verified previous"
    quarantine = Path(result["quarantined"])
    assert quarantine.parent == skills_dir
    assert quarantine.name == ".clinical-document-generation.quarantine-suspect-fingerprint"
    assert (quarantine / "marker.txt").read_text(encoding="utf-8") == "suspect"
    assert not previous.exists()
    assert historical_revision.read_text(encoding="utf-8") == (
        '{"package_fingerprint":"suspect-fingerprint"}'
    )


def test_failed_rollback_verification_leaves_active_and_previous_unchanged(tmp_path):
    skills_dir = tmp_path / "skills"
    active = skills_dir / "clinical-document-generation"
    previous = skills_dir / ".clinical-document-generation.previous"
    active.mkdir(parents=True)
    previous.mkdir()
    (active / "marker.txt").write_text("active", encoding="utf-8")
    (previous / "marker.txt").write_text("previous", encoding="utf-8")

    result = workflow.rollback_release(
        skills_dir,
        verifier=lambda _release: {
            "status": "blocked",
            "findings": [{"issue": "controlled smoke failure"}],
        },
    )

    assert result == {
        "status": "blocked",
        "stage": "rollback_smoke",
        "findings": [{"issue": "controlled smoke failure"}],
        "active_release_retained": True,
        "previous_release_retained": True,
    }
    assert (active / "marker.txt").read_text(encoding="utf-8") == "active"
    assert (previous / "marker.txt").read_text(encoding="utf-8") == "previous"


def test_activation_reduces_displaced_release_to_lightweight_history(tmp_path):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    _certify_archive(archive_path)
    skills_dir = tmp_path / "skills"
    active = skills_dir / "clinical-document-generation"
    previous = skills_dir / ".clinical-document-generation.previous"
    for release, fingerprint in (
        (active, "immediate-previous"),
        (previous, "historical-release"),
    ):
        (release / "runtime").mkdir(parents=True)
        (release / "runtime/full-runtime.bin").write_bytes(b"full runtime")
        (release / "RELEASE-MANIFEST.json").write_text(
            json.dumps({
                "git_commit": f"commit-{fingerprint}",
                "package_fingerprint": fingerprint,
            }),
            encoding="utf-8",
        )
    (previous / "PROMOTION-RECORD.json").write_text(
        json.dumps({"certification": {"status": "passed", "report_sha256": "report-hash"}}),
        encoding="utf-8",
    )

    result = install_release(
        archive_path,
        skills_dir,
        hermes_config_path=_hermes_config(skills_dir),
        verifier=lambda _candidate: {"status": "passed"},
        provisioner=lambda _candidate: {"status": "passed"},
    )

    assert result["status"] == "passed"
    assert "name: clinical-document-generation" in (active / "SKILL.md").read_text(encoding="utf-8")
    assert (previous / "runtime/full-runtime.bin").read_bytes() == b"full runtime"
    history_path = Path(result["retained_history"])
    assert history_path == skills_dir / "release-history/historical-release.json"
    assert json.loads(history_path.read_text(encoding="utf-8")) == {
        "schema_version": "release-history/v1",
        "git_commit": "commit-historical-release",
        "package_fingerprint": "historical-release",
        "certification": {"status": "passed", "report_sha256": "report-hash"},
    }
    assert not any(
        path.name.startswith(".clinical-document-generation.previous-")
        for path in skills_dir.iterdir()
    )


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
