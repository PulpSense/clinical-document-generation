import hashlib
import base64
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import workflow
import quality
from hermes_e2e import _certified_release
from pypdf import PdfWriter
from quality import rasterize_pdf
import pytest
from workflow import (
    bind_release_certification,
    install_release,
    package_release,
    provision_render_assurance,
    verify_installation,
)


ROOT = Path(__file__).resolve().parents[1]
PDFIUM_WHEEL = "pypdfium2-5.13.0-py3-none-macosx_13_0_arm64.whl"
PDFIUM_SHA256 = "da5c7b74eebf40b5c1fbe1de01aa1edc8827a79fb1efd999616bc20dcaf77ba4"
TEST_CERTIFICATION_KEY = ROOT / "tests/fixtures/test-certification-signing-key.json"
TEST_CERTIFICATION_KEY_ID = json.loads(
    TEST_CERTIFICATION_KEY.read_text(encoding="utf-8")
)["key_id"]


def _installation_staging(tmp_path: Path) -> Path:
    staging = tmp_path / ".clinical-document-generation.install-test"
    staging.mkdir(parents=True, exist_ok=True)
    return staging


def _pdfium_manifest_identity():
    return {
        "kind": "pypdfium2",
        "version": "5.13.0",
        "wheel": f"assets/runtime-wheels/{PDFIUM_WHEEL}",
        "wheel_sha256": PDFIUM_SHA256,
        "platform": "macosx_13_0_arm64",
        "runtime_inventory": workflow._pdfium_wheel_inventory(
            ROOT / "assets/runtime-wheels" / PDFIUM_WHEEL
        ),
    }


def _write_release_manifest(skill_root: Path, payload: dict) -> None:
    manifest = json.loads(json.dumps(payload))
    manifest.pop("package_fingerprint", None)
    manifest["package_fingerprint"] = workflow.sha256_value(manifest)
    (skill_root / "RELEASE-MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def _passing_provisioner(candidate: Path) -> dict:
    result = workflow._provision_page_renderer(candidate)
    if result.get("status") != "passed":
        return result
    return {
        **result,
        "renderer": {"kind": "LibreOffice", "path": "/controlled/soffice"},
    }


def _certify_archive(
    archive_path: Path,
    *,
    include_evidence: bool = True,
    include_preflight_logs: bool = True,
    sign: bool = True,
    bind_report: bool = True,
) -> None:
    test_key = json.loads(TEST_CERTIFICATION_KEY.read_text(encoding="utf-8"))
    test_public_key = {
        key: value for key, value in test_key.items()
        if key not in {"private_exponent", "test_only"}
    }
    package_release(
        ROOT,
        archive_path,
        certification_public_key=test_public_key,
    )
    with zipfile.ZipFile(archive_path) as archive:
        manifest_bytes = archive.read("clinical-document-generation/RELEASE-MANIFEST.json")
        manifest = json.loads(manifest_bytes)
    identity = {
        "package_fingerprint": manifest["package_fingerprint"],
        "git_commit": manifest["git_commit"],
    }
    configurations = {
        fixture: json.loads((ROOT / f"tests/fixtures/release-certification/{fixture}/fixture.json").read_text())["hermes_configuration"]
        for fixture in workflow.CERTIFICATION_CASE_ORDER
    }
    bundle_by_fixture = {}
    fixture_selections = {
        "retrospective": ("Retrospective", None),
        "ambispective-sterling": ("Ambispective", "Sterling"),
        "prospective-advarra": ("Prospective", "Advarra"),
    }
    for fixture, selection in fixture_selections.items():
        bundle_by_fixture[fixture] = next(
            bundle for bundle in manifest["inventory"]["contracted_template_bundles"]
            if (
                bundle["selection"]["study_type"], bundle["selection"]["icf_family"],
            ) == selection
        )

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
            "contracted_template_bundle_identity": bundle_by_fixture[fixture]["identity_sha256"],
            "layout_preservation_baseline_identity": bundle_by_fixture[fixture]["layout_preservation_baseline"]["sha256"],
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
        "completed_at": "2026-08-28T00:02:00+00:00",
    }
    if include_evidence:
        entries = []

        def add(
            identity_name: str,
            kind: str,
            content: bytes,
            *,
            case_id: str | None = None,
            path: str | None = None,
        ) -> dict:
            entry = _embedded_evidence_entry(
                identity_name,
                content,
                kind=kind,
                case_id=case_id,
                path=path,
            )
            entries.append(entry)
            return entry

        add("release-manifest", "release_manifest", manifest_bytes)
        synthetic_python_runtime = {
            "version": "3.11.15",
            "implementation": "cpython",
            "executable_sha256": "9" * 64,
        }
        preflight_log_entries = {}
        if include_preflight_logs:
            for check_name in ("static_release_checks", "repository_regression_suite"):
                preflight_log_entries[check_name] = add(
                    check_name,
                    "preflight_log",
                    f"passing synthetic preflight log:{check_name}\n".encode(),
                    path=f"global/preflight-logs/{check_name}.log",
                )
        preflight = add(
            "preflight",
            "preflight",
            json.dumps({
                "schema_version": "release-certification-preflight/v1",
                "status": "passed",
                "candidate": identity,
                "python_runtime": synthetic_python_runtime,
                "checks": {
                    "layout_preservation_corpus": {"status": "passed", "returncode": 0},
                    "deterministic_branch_acceptance_corpus": {"status": "passed", "returncode": 0},
                    **{
                        name: {
                            "status": "passed",
                            "returncode": 0,
                            "sha256": (preflight_log_entries.get(name) or {}).get(
                                "sha256", "0" * 64
                            ),
                        }
                        for name in ("static_release_checks", "repository_regression_suite")
                    },
                },
            }, sort_keys=True).encode(),
        )
        report["preflight_evidence_sha256"] = preflight["sha256"]
        layout = add(
            "layout-preservation",
            "layout_preservation",
            json.dumps(report["layout_preservation_evidence"], sort_keys=True).encode(),
        )
        report["layout_preservation_evidence"]["sha256"] = layout["sha256"]
        add(
            "deterministic-corpus",
            "deterministic_corpus",
            json.dumps({
                "status": "passed",
                "case_ids": list(workflow.DETERMINISTIC_BRANCH_ACCEPTANCE_CASES),
            }, sort_keys=True).encode(),
        )
        add(
            "runtime-identity",
            "runtime_identity",
            json.dumps({
                "release_identity": identity,
                "python": synthetic_python_runtime,
                "page_renderer": manifest["inventory"]["pdf_page_renderer"],
                "hermes_configuration_sha256": {
                    fixture: workflow.sha256_value(configuration)
                    for fixture, configuration in configurations.items()
                },
                "production_modules": {
                    item["path"]: item["sha256"]
                    for item in manifest["files"]
                    if item["path"].startswith("scripts/") and item["path"].endswith(".py")
                },
            }, sort_keys=True).encode(),
        )
        for case in report["cases"]:
            fixture = case["fixture_id"]
            output_entries = []
            for output in case["output_evidence"]:
                content = f"synthetic certification output:{fixture}:{output['path']}".encode()
                entry = add(
                    f"{fixture}-output-{Path(output['path']).name}",
                    "output",
                    content,
                    case_id=fixture,
                    path=f"cases/{fixture}/{output['path']}",
                )
                output.update(
                    sha256=entry["sha256"], bytes=entry["bytes"], confirmed=True
                )
                output_entries.append(dict(output))
            delivery_manifest = {
                "status": "passed",
                "release_identity": identity,
                "client_outputs": output_entries,
                "quality": {"status": "passed"},
            }
            add(
                f"{fixture}-delivery-manifest",
                "delivery_manifest",
                json.dumps(delivery_manifest, sort_keys=True).encode(),
                case_id=fixture,
                path=f"cases/{fixture}/delivery-manifest.json",
            )
            add(
                f"{fixture}-desktop-state",
                "desktop_operation_state",
                json.dumps({
                    "status": "passed",
                    "release_identity": {**identity, "hermes_configuration": configurations[fixture]},
                    "result": {"status": "passed", "delivery": {"confirmed": True}},
                    "cleanup": {"owned_processes_reaped": True},
                }, sort_keys=True).encode(),
                case_id=fixture,
                path=f"cases/{fixture}/desktop-operation.json",
            )
            add(
                f"{fixture}-delivery-confirmation",
                "delivery_confirmation",
                json.dumps({"confirmed": True, "opened": output_entries}, sort_keys=True).encode(),
                case_id=fixture,
                path=f"cases/{fixture}/delivery-confirmation.json",
            )
            fixture_artifacts = {}
            for identity_suffix, kind in (
                ("fixture-source", "fixture_source"),
                ("approved-source", "approved_source"),
                ("approved-reference", "approved_reference"),
            ):
                retained = add(
                    f"{fixture}-{identity_suffix}",
                    kind,
                    f"synthetic non-private {kind}:{fixture}".encode(),
                    case_id=fixture,
                    path=f"cases/{fixture}/fixture/{identity_suffix}.dat",
                )
                artifact_name = {
                    "fixture_source": "source_input",
                    "approved_source": "approved_source",
                    "approved_reference": "approved_reference",
                }[kind]
                fixture_artifacts[artifact_name] = {"sha256": retained["sha256"]}
            add(
                f"{fixture}-fixture-manifest",
                "fixture_manifest",
                json.dumps({
                    "fixture_id": fixture,
                    "synthetic": True,
                    "contains_private_data": False,
                    "artifacts": fixture_artifacts,
                    "approved_normalization": {
                        "source_input_sha256": fixture_artifacts["source_input"]["sha256"],
                        "approved_source_sha256": fixture_artifacts["approved_source"]["sha256"],
                    },
                }, sort_keys=True).encode(),
                case_id=fixture,
                path=f"cases/{fixture}/fixture/fixture.json",
            )
            drafting_request = {
                "request_id": f"{fixture}-draft",
                "request_sha256": hashlib.sha256(f"{fixture}-draft".encode()).hexdigest(),
                "task": "section_drafting",
            }
            add(
                f"{fixture}-drafting-request",
                "drafting_request",
                json.dumps(drafting_request, sort_keys=True).encode(),
                case_id=fixture,
                path=f"cases/{fixture}/drafting-request.json",
            )
            add(
                f"{fixture}-drafting-response",
                "drafting_response",
                json.dumps({
                    **drafting_request,
                    "status": "passed",
                    "producer": {"model_id": "gpt-5.6-sol"},
                }, sort_keys=True).encode(),
                case_id=fixture,
                path=f"cases/{fixture}/drafting-response.json",
            )
            content_request = {
                "request_id": f"{fixture}-content",
                "request_sha256": hashlib.sha256(f"{fixture}-content".encode()).hexdigest(),
                "task": "clinical_content_verification",
            }
            add(
                f"{fixture}-content-request",
                "verification_request",
                json.dumps(content_request, sort_keys=True).encode(),
                case_id=fixture,
                path=f"cases/{fixture}/content-request.json",
            )
            add(
                f"{fixture}-content-response",
                "verification_response",
                json.dumps({
                    **content_request,
                    "status": "passed",
                    "producer": {"model_id": "gpt-5.6-sol"},
                    "section_assessments": [{"status": "passed"}],
                    "cross_document_assessments": [{"status": "passed"}],
                }, sort_keys=True).encode(),
                case_id=fixture,
                path=f"cases/{fixture}/content-response.json",
            )
            for artifact, visual in case["visual_qa"].items():
                pdf = add(
                    f"{fixture}-{artifact}-pdf",
                    "pdf",
                    f"synthetic-pdf:{fixture}:{artifact}".encode(),
                    case_id=fixture,
                    path=f"cases/{fixture}/rendered/{artifact}.pdf",
                )
                page = add(
                    f"{fixture}-{artifact}-page-1",
                    "page_image",
                    f"synthetic-page:{fixture}:{artifact}:1".encode(),
                    case_id=fixture,
                    path=f"cases/{fixture}/pages/{artifact}/page-1.png",
                )
                output = next(
                    item for item in case["output_evidence"]
                    if item["path"] == f"output/{artifact}.docx"
                )
                request = {
                    "request_id": f"{fixture}-{artifact}-visual",
                    "request_sha256": hashlib.sha256(
                        f"{fixture}-{artifact}-visual".encode()
                    ).hexdigest(),
                    "task": "rendered_page_visual_verification",
                    "artifacts": [{
                        "artifact": artifact,
                        "docx_sha256": output["sha256"],
                        "pdf_sha256": pdf["sha256"],
                        "pages": [{"page": 1, "sha256": page["sha256"]}],
                    }],
                }
                request_entry = add(
                    f"{fixture}-{artifact}-visual-request",
                    "verification_request",
                    json.dumps(request, sort_keys=True).encode(),
                    case_id=fixture,
                    path=f"cases/{fixture}/{artifact}-visual-request.json",
                )
                response_entry = add(
                    f"{fixture}-{artifact}-parent-review",
                    "parent_page_review",
                    json.dumps({
                        **request,
                        "status": "passed",
                        "producer": {"model_id": "gpt-5.6-sol", "source": "desktop_parent"},
                        "page_assessments": [{
                            "artifact": artifact,
                            "page": 1,
                            "sha256": page["sha256"],
                            "status": "passed",
                            "checks": sorted(workflow.CERTIFICATION_VISUAL_CHECKS),
                        }],
                    }, sort_keys=True).encode(),
                    case_id=fixture,
                    path=f"cases/{fixture}/{artifact}-parent-review.json",
                )
                visual.update(
                    request_sha256=request_entry["sha256"],
                    response_sha256=response_entry["sha256"],
                    docx_sha256=output["sha256"],
                    pdf_sha256=pdf["sha256"],
                    page_sha256=[page["sha256"]],
                )
            add(
                f"{fixture}-parent-process-marker",
                "parent_process_marker",
                json.dumps({
                    "status": "completed",
                    "completion_requirement": "Desktop parent must inspect every bound page image.",
                    "required_producer_model_id": "gpt-5.6-sol",
                }, sort_keys=True).encode(),
                case_id=fixture,
                path=f"cases/{fixture}/parent-process-review.json",
            )
            case_report = {
                "schema_version": "release-certification-case/v1",
                "fixture_id": fixture,
                "status": "passed",
                "release_identity": identity,
                "hermes_configuration": configurations[fixture],
                "model_identifiers": ["gpt-5.6-sol"],
                "output_evidence": case["output_evidence"],
                "visual_qa": case["visual_qa"],
            }
            case_entry = add(
                f"{fixture}-case-report",
                "case_report",
                json.dumps(case_report, sort_keys=True).encode(),
                case_id=fixture,
                path=f"cases/{fixture}/case-report.json",
            )
            case["report_sha256"] = case_entry["sha256"]
        metadata = [
            {key: value for key, value in entry.items() if key != "content_base64"}
            for entry in entries
        ]
        report["evidence_bundle"] = {
            "schema_version": "release-certification-evidence/v1",
            "inventory_sha256": workflow.sha256_value(metadata),
            "total_bytes": sum(entry["bytes"] for entry in entries),
            "entries": entries,
        }
    if sign:
        report = workflow._sign_release_certification(report, TEST_CERTIFICATION_KEY)
    report_path = archive_path.with_suffix(".certification.json")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    if bind_report:
        bind_release_certification(
            archive_path,
            report_path,
            trusted_certification_key_id=test_key["key_id"],
        )


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


def test_production_certification_public_key_identity_is_canonical_and_pinned():
    public_key = json.loads(
        (ROOT / workflow.RELEASE_CERTIFICATION_PUBLIC_KEY).read_text(encoding="utf-8")
    )
    identity = {
        "algorithm": public_key["algorithm"],
        "exponent": public_key["exponent"],
        "modulus": public_key["modulus"],
    }

    assert "private_exponent" not in public_key
    assert workflow.sha256_value(identity) == public_key["key_id"]
    assert quality.release_certification_key_id(public_key) == public_key["key_id"]
    assert public_key["key_id"] == workflow.RELEASE_CERTIFICATION_TRUSTED_KEY_ID

    test_key = json.loads(TEST_CERTIFICATION_KEY.read_text(encoding="utf-8"))
    assert quality.release_certification_key_id(test_key) == test_key["key_id"]


def test_release_provisions_its_one_pdf_renderer_offline(tmp_path, monkeypatch):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    staging = _installation_staging(tmp_path)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(staging)
    skill_root = staging / "clinical-document-generation"
    office = {
        "kind": "LibreOffice",
        "path": "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "source": "host prerequisite",
    }
    monkeypatch.setattr(workflow, "renderers", lambda **_kwargs: [office])

    result = provision_render_assurance(skill_root)

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
    assert marker == {
        "kind": "pypdfium2",
        "version": "5.13.0",
        "wheel": f"assets/runtime-wheels/{PDFIUM_WHEEL}",
        "wheel_sha256": PDFIUM_SHA256,
        "platform": "macosx_13_0_arm64",
        "status": "provisioned",
        "inventory_source": "RELEASE-MANIFEST.json",
    }
    pdf = tmp_path / "one-page.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf.open("wb") as handle:
        writer.write(handle)

    monkeypatch.setattr(quality, "__file__", str(skill_root / "scripts/quality.py"))
    native_modules_before = {
        name: module for name, module in sys.modules.items()
        if name == "pypdfium2" or name.startswith("pypdfium2.")
        or name == "pypdfium2_raw" or name.startswith("pypdfium2_raw.")
    }
    pages = rasterize_pdf(
        pdf,
        tmp_path / "pages",
        result["page_renderer"],
        require_promoted_runtime=False,
    )
    repeated_pages = rasterize_pdf(
        pdf,
        tmp_path / "repeated-pages",
        result["page_renderer"],
        require_promoted_runtime=False,
    )

    assert [page.name for page in pages] == ["page-1.png"]
    assert pages[0].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert repeated_pages[0].read_bytes() == pages[0].read_bytes()
    assert {
        name: module for name, module in sys.modules.items()
        if name == "pypdfium2" or name.startswith("pypdfium2.")
        or name == "pypdfium2_raw" or name.startswith("pypdfium2_raw.")
    } == native_modules_before


def test_release_installation_fails_closed_without_a_host_office_renderer(tmp_path, monkeypatch):
    skill_root = _installation_staging(tmp_path) / "clinical-document-generation"
    wheel_dir = skill_root / "assets/runtime-wheels"
    wheel_dir.mkdir(parents=True)
    shutil.copy2(ROOT / "assets/runtime-wheels" / PDFIUM_WHEEL, wheel_dir / PDFIUM_WHEEL)
    _write_release_manifest(skill_root, {
        "inventory": {"pdf_page_renderer": _pdfium_manifest_identity()}
    })
    monkeypatch.setattr(workflow, "renderers", lambda **_kwargs: [])

    assert provision_render_assurance(skill_root) == {
        "status": "blocked",
        "findings": [{
            "category": "installation",
            "field": "office_renderer",
            "code": "installation.office_renderer_required",
            "issue": "Install or enable Microsoft Word or LibreOffice on the host, then rerun release installation.",
        }],
    }


def test_release_renderer_rejects_tampered_runtime_without_silent_repair(tmp_path, monkeypatch):
    skill_root = _installation_staging(tmp_path) / "clinical-document-generation"
    wheel_dir = skill_root / "assets/runtime-wheels"
    wheel_dir.mkdir(parents=True)
    shutil.copy2(ROOT / "assets/runtime-wheels" / PDFIUM_WHEEL, wheel_dir / PDFIUM_WHEEL)
    _write_release_manifest(skill_root, {
        "inventory": {"pdf_page_renderer": _pdfium_manifest_identity()}
    })
    monkeypatch.setattr(workflow, "renderers", lambda **_kwargs: [{
        "kind": "LibreOffice", "path": "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    }])

    assert provision_render_assurance(skill_root)["status"] == "passed"
    target = skill_root / "runtime/python/pypdfium2/__init__.py"
    target.write_text("tampered", encoding="utf-8")

    assert workflow.page_renderers(skill_root=skill_root) == []
    result = provision_render_assurance(skill_root)

    assert result["status"] == "blocked"
    assert result["findings"][0]["code"] == "renderer.pdfium_runtime_file_changed"
    assert result["findings"][0]["path"] == "pypdfium2/__init__.py"
    assert target.read_text(encoding="utf-8") == "tampered"


def test_runtime_marker_cannot_attest_to_a_tampered_pdfium_runtime(tmp_path, monkeypatch):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    staging = _installation_staging(tmp_path)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(staging)
    skill_root = staging / "clinical-document-generation"
    monkeypatch.setattr(workflow, "renderers", lambda **_kwargs: [{
        "kind": "LibreOffice", "path": "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    }])
    assert provision_render_assurance(skill_root)["status"] == "passed"

    target = skill_root / "runtime/python/pypdfium2/__init__.py"
    target.write_text("tampered", encoding="utf-8")
    marker_path = skill_root / "runtime/PDF-RENDERER.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["installed_files"] = {
        path.relative_to(skill_root / "runtime/python").as_posix(): workflow.sha256_file(path)
        for path in (skill_root / "runtime/python").rglob("*")
        if path.is_file()
    }
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    assert workflow.page_renderers(skill_root=skill_root) == []


def test_runtime_inventory_requires_a_valid_manifest_fingerprint(tmp_path, monkeypatch):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    staging = _installation_staging(tmp_path)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(staging)
    skill_root = staging / "clinical-document-generation"
    monkeypatch.setattr(workflow, "renderers", lambda **_kwargs: [{
        "kind": "LibreOffice", "path": "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    }])
    assert provision_render_assurance(skill_root)["status"] == "passed"

    target = skill_root / "runtime/python/pypdfium2/__init__.py"
    original = target.read_bytes()
    target.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    manifest_path = skill_root / "RELEASE-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    inventory = manifest["inventory"]["pdf_page_renderer"]["runtime_inventory"]
    entry = next(item for item in inventory if item["path"] == "pypdfium2/__init__.py")
    entry["sha256"] = workflow.sha256_file(target)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    verification = quality._pdfium_runtime_integrity(skill_root)

    assert verification["status"] == "blocked"
    assert verification["finding"]["code"] == "renderer.pdfium_manifest_fingerprint_invalid"
    assert verification["finding"]["path"] == "RELEASE-MANIFEST.json"


def test_promoted_runtime_inventory_cannot_rebind_its_package_fingerprint(
    tmp_path,
    governed_pdfium,
):
    package = tmp_path / "release.zip"
    workflow.package_release(ROOT, package)
    extraction_root = _installation_staging(tmp_path)
    with zipfile.ZipFile(package) as archive:
        archive.extractall(extraction_root)
    skill_root = extraction_root / "clinical-document-generation"
    assert workflow._provision_page_renderer(skill_root)["status"] == "passed"
    assert quality._pdfium_runtime_integrity(
        skill_root, require_promoted_runtime=False
    )["status"] == "passed"
    assert quality._pdfium_runtime_integrity(skill_root)["status"] == "blocked"

    manifest_path = skill_root / "RELEASE-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    promoted_fingerprint = manifest["package_fingerprint"]
    assurance_path = skill_root / "INSTALLATION-ASSURANCE.json"
    assurance_path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    (skill_root / "PROMOTION-RECORD.json").write_text(
        json.dumps({
            "schema_version": "promoted-release/v1",
            "status": "active",
            "package_fingerprint": promoted_fingerprint,
            "runtime_assurance_sha256": workflow.sha256_file(assurance_path),
        }),
        encoding="utf-8",
    )

    entry = manifest["inventory"]["pdf_page_renderer"]["runtime_inventory"][0]
    target = skill_root / "runtime/python" / entry["path"]
    original = target.read_bytes()
    target.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    entry["sha256"] = workflow.sha256_file(target)
    _write_release_manifest(skill_root, manifest)

    verification = quality._pdfium_runtime_integrity(skill_root)

    assert verification["status"] == "blocked"
    assert verification["finding"]["code"] == (
        "renderer.pdfium_promotion_fingerprint_mismatch"
    )
    assert verification["finding"]["path"] == "PROMOTION-RECORD.json"


@pytest.mark.parametrize(("mutation", "code", "path"), [
    ("missing", "renderer.pdfium_runtime_file_missing", "pypdfium2/__init__.py"),
    ("extra", "renderer.pdfium_runtime_file_extra", "unexpected.py"),
    ("symlink", "renderer.pdfium_runtime_symlink", "pypdfium2/__init__.py"),
    ("changed", "renderer.pdfium_runtime_file_changed", "pypdfium2/__init__.py"),
    ("same-length", "renderer.pdfium_runtime_file_changed", "pypdfium2/__init__.py"),
])
def test_runtime_inventory_mutations_fail_closed_with_stable_diagnostic(
    tmp_path, monkeypatch, mutation, code, path
):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    staging = _installation_staging(tmp_path)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(staging)
    skill_root = staging / "clinical-document-generation"
    monkeypatch.setattr(workflow, "renderers", lambda **_kwargs: [{
        "kind": "LibreOffice", "path": "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    }])
    assert provision_render_assurance(skill_root)["status"] == "passed"
    runtime = skill_root / "runtime/python"
    target = runtime / "pypdfium2/__init__.py"
    if mutation == "missing":
        target.unlink()
    elif mutation == "extra":
        (runtime / "unexpected.py").write_text("unexpected", encoding="utf-8")
    elif mutation == "symlink":
        target.unlink()
        target.symlink_to(runtime / "pypdfium2/version.py")
    elif mutation == "changed":
        target.write_text("changed", encoding="utf-8")
    else:
        original = target.read_bytes()
        target.write_bytes(bytes([original[0] ^ 1]) + original[1:])

    result = provision_render_assurance(skill_root)

    assert result["status"] == "blocked"
    assert result["findings"][0]["category"] == "installation"
    assert result["findings"][0]["field"] == "pdf_page_renderer"
    assert result["findings"][0]["code"] == code
    assert result["findings"][0]["path"] == path


def test_later_render_assurance_reports_exact_runtime_integrity_failure(
    tmp_path, monkeypatch
):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    staging = _installation_staging(tmp_path)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(staging)
    skill_root = staging / "clinical-document-generation"
    office = {
        "kind": "LibreOffice",
        "path": "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "source": "host prerequisite",
    }
    monkeypatch.setattr(workflow, "renderers", lambda **_kwargs: [office])
    assert provision_render_assurance(skill_root)["status"] == "passed"
    manifest = json.loads(
        (skill_root / "RELEASE-MANIFEST.json").read_text(encoding="utf-8")
    )
    assurance_path = skill_root / "INSTALLATION-ASSURANCE.json"
    assurance_path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    (skill_root / "PROMOTION-RECORD.json").write_text(json.dumps({
        "schema_version": "promoted-release/v1",
        "status": "active",
        "package_fingerprint": manifest["package_fingerprint"],
        "runtime_assurance_sha256": workflow.sha256_file(assurance_path),
    }), encoding="utf-8")
    (skill_root / "runtime/python/pypdfium2/__init__.py").unlink()
    monkeypatch.setattr(quality, "__file__", str(skill_root / "scripts/quality.py"))
    monkeypatch.setattr(quality, "renderers", lambda **_kwargs: [office])

    result = quality.render_pages(tmp_path / "revision")

    assert result["status"] == "blocked"
    assert result["findings"][0]["code"] == "renderer.pdfium_runtime_file_missing"
    assert result["findings"][0]["path"] == "pypdfium2/__init__.py"


@pytest.mark.parametrize(("symlink_level", "code", "path"), [
    ("runtime", "renderer.pdfium_runtime_directory_symlink", "runtime"),
    ("python", "renderer.pdfium_runtime_root_symlink", "runtime/python"),
])
def test_runtime_root_symlink_escape_fails_closed_with_exact_path(
    tmp_path, monkeypatch, symlink_level, code, path
):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    staging = _installation_staging(tmp_path)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(staging)
    skill_root = staging / "clinical-document-generation"
    monkeypatch.setattr(workflow, "renderers", lambda **_kwargs: [{
        "kind": "LibreOffice", "path": "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    }])
    assert provision_render_assurance(skill_root)["status"] == "passed"
    symlink = skill_root / ("runtime" if symlink_level == "runtime" else "runtime/python")
    external_runtime = tmp_path / f"external-{symlink_level}"
    shutil.copytree(symlink, external_runtime)
    shutil.rmtree(symlink)
    symlink.symlink_to(external_runtime, target_is_directory=True)

    assert workflow.page_renderers(skill_root=skill_root) == []
    finding = workflow._pdfium_runtime_integrity(skill_root)["finding"]
    assert finding["code"] == code
    assert finding["path"] == path
    result = provision_render_assurance(skill_root)
    assert result["status"] == "blocked"
    assert result["findings"][0]["code"] == code


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
        assert manifest["inventory"]["pdf_page_renderer"] == _pdfium_manifest_identity()
        assert "page_renderer_fallbacks" not in manifest["inventory"]
        assert "page_renderer_at_packaging" not in manifest["inventory"]
        assert manifest["installation"]["required_external_tools"] == [
            "Microsoft Word or LibreOffice"
        ]
        assert "atomic" in manifest["installation"]["activation"]
        assert manifest["excluded_classes"]


def test_release_manifest_binds_expected_pdfium_extraction_inventory(tmp_path):
    archive_path = tmp_path / "release.zip"

    package_release(ROOT, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("clinical-document-generation/RELEASE-MANIFEST.json"))
    inventory = manifest["inventory"]["pdf_page_renderer"]["runtime_inventory"]
    assert inventory
    assert inventory == sorted(inventory, key=lambda item: item["path"])
    assert all(set(item) == {"path", "bytes", "sha256"} for item in inventory)
    assert all(item["path"] and not item["path"].startswith(("/", "../")) for item in inventory)
    assert all(item["bytes"] >= 0 and len(item["sha256"]) == 64 for item in inventory)
    assert any(item["path"] == "pypdfium2/__init__.py" for item in inventory)
    assert any(item["path"] == "pypdfium2_raw/libpdfium.dylib" for item in inventory)


@pytest.mark.parametrize("member_name", [
    "../escape.py",
    "/absolute.py",
    "package/./alias.py",
    "package//alias.py",
    "package\\alias.py",
    "package/./",
    "package/../",
    "package//",
    "package\\/",
    "/absolute/",
])
def test_pdfium_wheel_inventory_rejects_noncanonical_paths(tmp_path, member_name):
    wheel = tmp_path / "unsafe.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(member_name, b"unsafe")

    with pytest.raises(ValueError, match="unsafe or duplicate extraction path"):
        workflow._pdfium_wheel_inventory(wheel)


def test_pdfium_wheel_inventory_accepts_canonical_directory_members(tmp_path):
    wheel = tmp_path / "safe.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("package/", b"")
        archive.writestr("package/module.py", b"safe")

    assert workflow._pdfium_wheel_inventory(wheel) == [{
        "path": "package/module.py",
        "bytes": 4,
        "sha256": hashlib.sha256(b"safe").hexdigest(),
    }]


@pytest.mark.parametrize("members", [
    (("Foo.py", b"one"), ("foo.py", b"two")),
    (("Package/", b""), ("package/", b"")),
])
def test_pdfium_wheel_inventory_rejects_case_colliding_members(tmp_path, members):
    wheel = tmp_path / "case-collision.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, payload in members:
            archive.writestr(name, payload)

    with pytest.raises(ValueError, match="unsafe or duplicate extraction path"):
        workflow._pdfium_wheel_inventory(wheel)


def test_pdfium_manifest_rejects_escaping_runtime_inventory(tmp_path):
    skill_root = tmp_path / "clinical-document-generation"
    wheel_dir = skill_root / "assets/runtime-wheels"
    wheel_dir.mkdir(parents=True)
    shutil.copy2(ROOT / "assets/runtime-wheels" / PDFIUM_WHEEL, wheel_dir / PDFIUM_WHEEL)
    identity = _pdfium_manifest_identity()
    identity["runtime_inventory"][0]["path"] = "../escape"
    _write_release_manifest(skill_root, {
        "inventory": {"pdf_page_renderer": identity}
    })

    result = workflow._provision_page_renderer(skill_root)

    assert result["status"] == "blocked"
    assert result["findings"][0]["code"] == "installation.pdfium_manifest_inventory_invalid"


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
        trusted_certification_key_id=TEST_CERTIFICATION_KEY_ID,
        verifier=lambda _candidate: {"status": "blocked", "findings": [{"issue": "smoke failed"}]},
        provisioner=_passing_provisioner,
    )

    assert result["status"] == "blocked"
    assert (active / "marker.txt").read_text(encoding="utf-8") == "previous verified release"


def test_installation_smoke_timeout_returns_terminal_finding(tmp_path, monkeypatch):
    candidate = tmp_path / "clinical-document-generation"
    candidate.mkdir()

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(workflow.subprocess, "run", timeout)

    assert workflow._installation_smoke_result(candidate) == {
        "status": "blocked",
        "findings": [{
            "category": "installation",
            "field": "smoke",
            "code": "installation.smoke_timeout",
            "timeout_seconds": 180,
            "issue": "Installation smoke exceeded 180 seconds.",
        }],
    }


def test_installer_hooks_cannot_bypass_unconditional_runtime_rehash(tmp_path):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    _certify_archive(archive_path)
    skills_dir = tmp_path / "skills"

    result = install_release(
        archive_path,
        skills_dir,
        hermes_config_path=_hermes_config(skills_dir),
        trusted_certification_key_id=TEST_CERTIFICATION_KEY_ID,
        verifier=lambda _candidate: {"status": "passed"},
        provisioner=lambda _candidate: {"status": "passed"},
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "provision_integrity"
    assert result["findings"][0]["code"] == "renderer.pdfium_runtime_missing"


def test_installer_rehashes_runtime_after_verifier_hook(tmp_path):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    _certify_archive(archive_path)
    skills_dir = tmp_path / "skills"

    def mutating_verifier(candidate):
        runtime_file = candidate / "runtime/python/pypdfium2/__init__.py"
        runtime_file.write_bytes(runtime_file.read_bytes() + b"tampered")
        return {"status": "passed"}

    result = install_release(
        archive_path,
        skills_dir,
        hermes_config_path=_hermes_config(skills_dir),
        trusted_certification_key_id=TEST_CERTIFICATION_KEY_ID,
        verifier=mutating_verifier,
        provisioner=_passing_provisioner,
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "installation_integrity"
    assert result["findings"][0]["code"] == "renderer.pdfium_runtime_file_changed"
    assert result["findings"][0]["path"] == "pypdfium2/__init__.py"


def test_installer_rehashes_manifest_and_certification_after_verifier_hook(tmp_path):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    _certify_archive(archive_path)
    skills_dir = tmp_path / "skills"

    def mutating_verifier(candidate):
        production_module = candidate / "scripts/quality.py"
        production_module.write_bytes(production_module.read_bytes() + b"\n# tampered\n")
        return {"status": "passed"}

    result = install_release(
        archive_path,
        skills_dir,
        hermes_config_path=_hermes_config(skills_dir),
        trusted_certification_key_id=TEST_CERTIFICATION_KEY_ID,
        verifier=mutating_verifier,
        provisioner=_passing_provisioner,
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "installation_integrity"
    assert any(
        item.get("field") == "scripts/quality.py"
        and "hash does not match" in item.get("issue", "")
        for item in result["findings"]
    )
    assert not (skills_dir / "clinical-document-generation").exists()


def test_complete_integrity_revalidation_precedes_verifier_hook(tmp_path):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    _certify_archive(archive_path)
    skills_dir = tmp_path / "skills"
    active = skills_dir / "clinical-document-generation"
    active.mkdir(parents=True)
    (active / "marker.txt").write_text("previous verified release", encoding="utf-8")
    verifier_called = False

    def symlink_substituting_provisioner(candidate):
        provision = _passing_provisioner(candidate)
        production_module = candidate / "scripts/quality.py"
        alias = candidate / "runtime/manifest-owned-alias.py"
        alias.write_bytes(production_module.read_bytes())
        production_module.unlink()
        production_module.symlink_to("../runtime/manifest-owned-alias.py")
        return provision

    def verifier_tripwire(_candidate):
        nonlocal verifier_called
        verifier_called = True
        return {"status": "passed"}

    result = install_release(
        archive_path,
        skills_dir,
        hermes_config_path=_hermes_config(skills_dir),
        trusted_certification_key_id=TEST_CERTIFICATION_KEY_ID,
        verifier=verifier_tripwire,
        provisioner=symlink_substituting_provisioner,
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "provision_integrity"
    assert verifier_called is False
    assert any("symbolic link" in finding.get("issue", "") for finding in result["findings"])
    assert (active / "marker.txt").read_text(encoding="utf-8") == "previous verified release"


def test_installer_rejects_post_verifier_manifest_symlink_substitution(tmp_path):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    _certify_archive(archive_path)
    skills_dir = tmp_path / "skills"

    def symlink_substituting_verifier(candidate):
        production_module = candidate / "scripts/quality.py"
        alias = candidate / "runtime/manifest-owned-alias.py"
        alias.parent.mkdir(parents=True, exist_ok=True)
        alias.write_bytes(production_module.read_bytes())
        production_module.unlink()
        production_module.symlink_to("../runtime/manifest-owned-alias.py")
        return {"status": "passed"}

    result = install_release(
        archive_path,
        skills_dir,
        hermes_config_path=_hermes_config(skills_dir),
        trusted_certification_key_id=TEST_CERTIFICATION_KEY_ID,
        verifier=symlink_substituting_verifier,
        provisioner=_passing_provisioner,
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "installation_integrity"
    assert any(
        item.get("field") == "scripts/quality.py"
        and "symbolic link" in item.get("issue", "")
        for item in result["findings"]
    )
    assert not (skills_dir / "clinical-document-generation").exists()


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
        trusted_certification_key_id=TEST_CERTIFICATION_KEY_ID,
        verifier=verified,
        provisioner=_passing_provisioner,
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
    assert quality._pdfium_runtime_integrity(active)["status"] == "passed"
    assurance_path = active / "INSTALLATION-ASSURANCE.json"
    assurance_bytes = assurance_path.read_bytes()
    assurance_path.write_bytes(assurance_bytes + b"\n")
    changed_assurance = quality._pdfium_runtime_integrity(active)
    assert changed_assurance["status"] == "blocked"
    assert changed_assurance["finding"] == {
        "category": "renderer",
        "field": "page_renderer",
        "code": "renderer.pdfium_installation_assurance_mismatch",
        "path": "INSTALLATION-ASSURANCE.json",
        "issue": "The promoted release does not match its bound installation assurance.",
    }
    assurance_path.unlink()
    missing_assurance = quality._pdfium_runtime_integrity(active)
    assert missing_assurance["status"] == "blocked"
    assert missing_assurance["finding"]["code"] == (
        "renderer.pdfium_installation_assurance_mismatch"
    )
    assurance_path.symlink_to(tmp_path / "external-assurance.json")
    symlinked_assurance = quality._pdfium_runtime_integrity(active)
    assert symlinked_assurance["status"] == "blocked"
    assert symlinked_assurance["finding"]["code"] == (
        "renderer.pdfium_installation_assurance_mismatch"
    )
    assurance_path.unlink()
    assurance_path.write_bytes(assurance_bytes)
    assert quality._pdfium_runtime_integrity(active)["status"] == "passed"
    (active / "PROMOTION-RECORD.json").unlink()
    missing_promotion = quality._pdfium_runtime_integrity(active)
    assert missing_promotion["status"] == "blocked"
    assert missing_promotion["finding"]["code"] == (
        "renderer.pdfium_promotion_record_invalid"
    )
    assert missing_promotion["finding"]["path"] == "PROMOTION-RECORD.json"
    (active / "INSTALLATION-ASSURANCE.json").unlink()
    both_records_missing = quality._pdfium_runtime_integrity(active)
    assert both_records_missing["status"] == "blocked"
    assert both_records_missing["finding"]["code"] == (
        "renderer.pdfium_promotion_record_invalid"
    )
    explicit_candidate_mode = quality._pdfium_runtime_integrity(
        active, require_promoted_runtime=False
    )
    assert explicit_candidate_mode["status"] == "blocked"
    assert explicit_candidate_mode["finding"]["code"] == (
        "renderer.pdfium_promotion_record_invalid"
    )


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
        trusted_certification_key_id=TEST_CERTIFICATION_KEY_ID,
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
        trusted_certification_key_id=TEST_CERTIFICATION_KEY_ID,
        verifier=lambda _candidate: {"status": "passed"},
        provisioner=lambda _candidate: {"status": "passed"},
    )

    assert unlisted["status"] == "blocked"
    assert any("Unlisted packaged files" in finding["issue"] for finding in unlisted["findings"])
    assert (active / "marker.txt").read_text(encoding="utf-8") == "active"


@pytest.mark.parametrize("member_name", [
    "clinical-document-generation/./rogue.txt",
    "clinical-document-generation//rogue.txt",
    "clinical-document-generation/sub/../rogue.txt",
])
def test_release_archive_rejects_unique_noncanonical_member_paths(
    tmp_path, member_name
):
    archive_path = tmp_path / "noncanonical.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(member_name, b"rogue")

    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match="noncanonical member path"):
            workflow._validated_archive_members(archive, tmp_path / "extract")


@pytest.mark.parametrize(("mutation", "message"), [
    ("count", "too many members"),
    ("member_size", "member exceeds"),
    ("total_size", "total uncompressed"),
    ("ratio", "compression ratio"),
])
def test_release_archive_is_bounded_before_extraction(tmp_path, mutation, message):
    archive_path = tmp_path / "bounded.zip"
    member_count = workflow.RELEASE_ARCHIVE_MAX_MEMBERS + 1 if mutation == "count" else 6
    with zipfile.ZipFile(archive_path, "w") as archive:
        for index in range(member_count):
            archive.writestr(f"clinical-document-generation/member-{index}.bin", b"x")

    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if mutation == "member_size":
            members[0].file_size = workflow.RELEASE_ARCHIVE_MAX_MEMBER_BYTES + 1
            members[0].compress_size = members[0].file_size
        elif mutation == "total_size":
            per_member = workflow.RELEASE_ARCHIVE_MAX_TOTAL_BYTES // len(members) + 1
            for member in members:
                member.file_size = per_member
                member.compress_size = per_member
        elif mutation == "ratio":
            members[0].compress_size = 1
            members[0].file_size = workflow.RELEASE_ARCHIVE_MAX_COMPRESSION_RATIO + 1
        with pytest.raises(ValueError, match=message):
            workflow._validated_archive_members(archive, tmp_path / "extract")


def test_installation_and_runtime_share_manifest_fingerprint_verifier():
    assert workflow._manifest_package_fingerprint is quality._manifest_package_fingerprint
    manifest = {"schema_version": "release-manifest/v1", "inventory": {}}
    recorded, computed = quality._manifest_package_fingerprint(manifest)
    assert recorded == ""
    manifest["package_fingerprint"] = computed
    assert quality._manifest_package_fingerprint(manifest) == (computed, computed)


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

    with pytest.raises(ValueError, match="evidence bundle|does not pass and bind"):
        bind_release_certification(archive_path, skeletal)

    _certify_archive(archive_path)
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr(
            "clinical-document-generation/./RELEASE-CERTIFICATION.json",
            b"{}",
        )
    skills_dir = tmp_path / "skills"
    with pytest.raises(ValueError, match="noncanonical member path"):
        install_release(
            archive_path,
            skills_dir,
            hermes_config_path=_hermes_config(skills_dir),
            trusted_certification_key_id=TEST_CERTIFICATION_KEY_ID,
            verifier=lambda _candidate: {"status": "passed"},
            provisioner=lambda _candidate: {"status": "passed"},
        )


def test_digest_shaped_certification_summary_cannot_bind_without_evidence_bundle(
    tmp_path,
):
    archive_path = tmp_path / "forged-summary.zip"
    package_release(ROOT, archive_path)

    with pytest.raises(ValueError, match="evidence bundle"):
        _certify_archive(archive_path, include_evidence=False)


def _embedded_evidence_entry(
    identity: str,
    content: bytes,
    *,
    kind: str = "preflight",
    case_id: str | None = None,
    path: str | None = None,
) -> dict:
    return {
        "identity": identity,
        "kind": kind,
        "case_id": case_id,
        "path": path or f"global/{identity}.json",
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


@pytest.mark.parametrize(("mutation", "message"), [
    ("traversal", "noncanonical evidence path"),
    ("duplicate", "duplicate evidence identity"),
    ("changed", "evidence bytes do not match"),
    ("oversized", "evidence item exceeds"),
])
def test_certification_evidence_inventory_fails_closed(mutation, message):
    first = _embedded_evidence_entry("preflight", b"{}")
    entries = [first]
    if mutation == "traversal":
        first["path"] = "global/../private.json"
    elif mutation == "duplicate":
        entries.append(_embedded_evidence_entry("PREFLIGHT", b"{}"))
    elif mutation == "changed":
        first["content_base64"] = base64.b64encode(b"changed").decode("ascii")
    else:
        first["bytes"] = workflow.CERTIFICATION_EVIDENCE_MAX_ITEM_BYTES + 1

    with pytest.raises(ValueError, match=message):
        workflow._validated_certification_evidence({
            "schema_version": "release-certification-evidence/v1",
            "entries": entries,
        })


def test_oversized_certification_report_is_rejected_before_json_parsing(tmp_path):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    oversized = tmp_path / "oversized-certification.json"
    with oversized.open("wb") as stream:
        stream.truncate(workflow.CERTIFICATION_REPORT_MAX_BYTES + 1)

    with pytest.raises(ValueError, match="governed encoded byte limit"):
        bind_release_certification(archive_path, oversized)


def test_coherently_fabricated_unsigned_evidence_cannot_bind(tmp_path):
    unsigned = tmp_path / "unsigned.zip"
    package_release(ROOT, unsigned)
    candidate = tmp_path / "candidate.zip"
    shutil.copy2(unsigned, candidate)
    _certify_archive(unsigned, sign=False, bind_report=False)

    with pytest.raises(ValueError, match="attestation|signature"):
        bind_release_certification(candidate, unsigned.with_suffix(".certification.json"))


def test_coherently_signed_attacker_key_cannot_replace_the_production_trust_root(tmp_path):
    archive_path = tmp_path / "attacker-key.zip"
    _certify_archive(archive_path)
    report_path = archive_path.with_suffix(".certification.json")

    with pytest.raises(ValueError, match="public key"):
        bind_release_certification(archive_path, report_path)


def test_certification_requires_both_preflight_logs(tmp_path):
    unsigned = tmp_path / "unsigned.zip"
    package_release(ROOT, unsigned)
    candidate = tmp_path / "candidate.zip"
    shutil.copy2(unsigned, candidate)
    _certify_archive(unsigned, include_preflight_logs=False, bind_report=False)

    with pytest.raises(ValueError, match="preflight logs"):
        bind_release_certification(candidate, unsigned.with_suffix(".certification.json"))


def test_rehashed_visual_request_artifact_substitution_cannot_bind(tmp_path):
    unsigned = tmp_path / "unsigned.zip"
    package_release(ROOT, unsigned)
    candidate = tmp_path / "candidate.zip"
    shutil.copy2(unsigned, candidate)
    _certify_archive(unsigned)
    report = json.loads(
        unsigned.with_suffix(".certification.json").read_text(encoding="utf-8")
    )
    entry = next(
        item for item in report["evidence_bundle"]["entries"]
        if item["kind"] == "verification_request"
        and json.loads(base64.b64decode(item["content_base64"]))
        .get("task") == "rendered_page_visual_verification"
    )
    request = json.loads(base64.b64decode(entry["content_base64"]))
    previous_request_sha256 = entry["sha256"]
    request["artifacts"][0].update(
        docx_sha256="3" * 64,
        pdf_sha256="4" * 64,
    )
    request["artifacts"][0]["pages"][0]["sha256"] = "5" * 64
    _replace_embedded_content(entry, json.dumps(request, sort_keys=True).encode())
    case = next(item for item in report["cases"] if item["fixture_id"] == entry["case_id"])
    visual = next(
        item for item in case["visual_qa"].values()
        if item["request_sha256"] == previous_request_sha256
    )
    visual["request_sha256"] = entry["sha256"]
    _rehash_embedded_evidence(report)
    report = workflow._sign_release_certification(report, TEST_CERTIFICATION_KEY)
    forged = tmp_path / "visual-substitution.json"
    forged.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="independent verification"):
        bind_release_certification(candidate, forged)


def test_rehashed_fixture_source_substitution_cannot_bind(tmp_path):
    unsigned = tmp_path / "unsigned.zip"
    package_release(ROOT, unsigned)
    candidate = tmp_path / "candidate.zip"
    shutil.copy2(unsigned, candidate)
    _certify_archive(unsigned)
    report_path = unsigned.with_suffix(".certification.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    entry = next(
        item for item in report["evidence_bundle"]["entries"]
        if item["kind"] == "fixture_source"
    )
    substituted = b"different synthetic source with recomputed identities"
    entry.update(
        bytes=len(substituted),
        sha256=hashlib.sha256(substituted).hexdigest(),
        content_base64=base64.b64encode(substituted).decode("ascii"),
    )
    metadata = [
        {key: value for key, value in item.items() if key != "content_base64"}
        for item in report["evidence_bundle"]["entries"]
    ]
    report["evidence_bundle"].update(
        inventory_sha256=workflow.sha256_value(metadata),
        total_bytes=sum(item["bytes"] for item in report["evidence_bundle"]["entries"]),
    )
    forged = tmp_path / "rehashed-substitution.json"
    forged.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="independent verification"):
        bind_release_certification(candidate, forged)


def _rehash_embedded_evidence(report: dict) -> None:
    entries = report["evidence_bundle"]["entries"]
    metadata = [
        {key: value for key, value in item.items() if key != "content_base64"}
        for item in entries
    ]
    report["evidence_bundle"].update(
        inventory_sha256=workflow.sha256_value(metadata),
        total_bytes=sum(item["bytes"] for item in entries),
    )


def _replace_embedded_content(entry: dict, content: bytes) -> None:
    entry.update(
        bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        content_base64=base64.b64encode(content).decode("ascii"),
    )


def test_signed_unrelated_binary_evidence_cannot_be_smuggled_into_certification(tmp_path):
    archive_path = tmp_path / "release.zip"
    _certify_archive(archive_path)
    report = json.loads(archive_path.with_suffix(".certification.json").read_text())
    report["evidence_bundle"]["entries"].append(_embedded_evidence_entry(
        "retrospective-private-session-export",
        b"Patient: Private Person\nAPI_KEY=secret\nprivate session log\n",
        kind="pdf",
        case_id="retrospective",
        path="cases/retrospective/private-session-export.pdf",
    ))
    _rehash_embedded_evidence(report)
    report.pop("evidence_attestation", None)
    report = workflow._sign_release_certification(report, TEST_CERTIFICATION_KEY)
    forged = tmp_path / "forged-certification.json"
    forged.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="independent verification"):
        bind_release_certification(
            archive_path,
            forged,
            trusted_certification_key_id=TEST_CERTIFICATION_KEY_ID,
        )


def test_rehashed_certification_evidence_attacks_cannot_bind(tmp_path):
    unsigned = tmp_path / "unsigned.zip"
    package_release(ROOT, unsigned)
    _certify_archive(unsigned)
    baseline = json.loads(
        unsigned.with_suffix(".certification.json").read_text(encoding="utf-8")
    )

    def mutate_bytes(report, kind):
        entry = next(item for item in report["evidence_bundle"]["entries"] if item["kind"] == kind)
        _replace_embedded_content(entry, b"substituted evidence bytes")

    def mutate_json(report, kind, mutation):
        entry = next(item for item in report["evidence_bundle"]["entries"] if item["kind"] == kind)
        payload = json.loads(base64.b64decode(entry["content_base64"]))
        mutation(payload)
        _replace_embedded_content(entry, json.dumps(payload, sort_keys=True).encode())

    attacks = (
        lambda report: mutate_bytes(report, "output"),
        lambda report: mutate_bytes(report, "page_image"),
        lambda report: mutate_json(
            report, "runtime_identity", lambda payload: payload["python"].update(version="0.0")
        ),
        lambda report: mutate_json(
            report, "parent_process_marker", lambda payload: payload.update(status="failed")
        ),
        lambda report: mutate_json(
            report, "verification_response", lambda payload: payload.update(status="failed")
        ),
        lambda report: report["evidence_bundle"]["entries"].remove(next(
            item for item in report["evidence_bundle"]["entries"] if item["kind"] == "pdf"
        )),
        lambda report: report["evidence_bundle"]["entries"].append(
            _embedded_evidence_entry(
                "private-session-log",
                b"private session transcript",
                kind="private_session_log",
                path="global/private-session.log",
            )
        ),
        lambda report: mutate_bytes(report, "release_manifest"),
    )
    for index, attack in enumerate(attacks):
        report = json.loads(json.dumps(baseline))
        attack(report)
        _rehash_embedded_evidence(report)
        forged = tmp_path / f"attack-{index}.json"
        forged.write_text(json.dumps(report), encoding="utf-8")
        candidate = tmp_path / f"candidate-{index}.zip"
        shutil.copy2(unsigned, candidate)
        try:
            bind_release_certification(candidate, forged)
        except ValueError as exc:
            assert "independent verification" in str(exc)
        else:
            pytest.fail(f"Rehashed certification evidence attack {index} bound successfully.")


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
        lambda report: report["cases"][0].update(contracted_template_bundle_identity="5" * 64),
        lambda report: report["cases"][0].update(layout_preservation_baseline_identity="6" * 64),
        lambda report: report["layout_preservation_evidence"].update(completed_at="2026-08-27T23:59:00+00:00"),
    )
    for index, mutate in enumerate(mutations):
        candidate = tmp_path / f"candidate-{index}.zip"
        shutil.copy2(template_archive, candidate)
        report = json.loads(json.dumps(baseline))
        mutate(report)
        mutated_report = tmp_path / f"mutated-{index}.json"
        mutated_report.write_text(json.dumps(report), encoding="utf-8")

        with pytest.raises(ValueError, match="independent verification|does not pass and bind"):
            bind_release_certification(candidate, mutated_report)
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
        trusted_certification_key_id=TEST_CERTIFICATION_KEY_ID,
        verifier=lambda _candidate: {"status": "passed"},
        provisioner=lambda _candidate: {"status": "passed"},
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "promotion_eligibility"
    assert result["findings"][-1]["field"] == "hermes_configuration"
    assert (active / "marker.txt").read_text(encoding="utf-8") == "active"


def test_hermes_configuration_requires_typed_exact_governed_values(tmp_path):
    archive_path = tmp_path / "release.zip"
    package_release(ROOT, archive_path)
    _certify_archive(archive_path)
    for index, replacement in enumerate((
        ("safe_mode: true", 'safe_mode: "true"'),
        ("model_identifier: gpt-5.6-sol", "model_identifier: GPT-5.6-SOL"),
        ("skill: clinical-document-drafting", "skill: Clinical-Document-Drafting"),
    )):
        skills_dir = tmp_path / f"skills-{index}"
        config = _hermes_config(skills_dir)
        config.write_text(
            config.read_text(encoding="utf-8").replace(*replacement),
            encoding="utf-8",
        )

        result = install_release(
            archive_path,
            skills_dir,
            hermes_config_path=config,
            trusted_certification_key_id=TEST_CERTIFICATION_KEY_ID,
            verifier=lambda _candidate: {"status": "passed"},
            provisioner=lambda _candidate: {"status": "passed"},
        )

        assert result["status"] == "blocked"
        assert result["findings"][-1]["field"] == "hermes_configuration"

    skills_dir = tmp_path / "skills-decoy"
    config = _hermes_config(skills_dir)
    active_line = "    - " + str(skills_dir / "clinical-document-generation") + "\n"
    config.write_text(
        config.read_text(encoding="utf-8").replace(active_line, "")
        + "decoy:\n  external_dirs:\n" + active_line,
        encoding="utf-8",
    )
    decoy = install_release(
        archive_path,
        skills_dir,
        hermes_config_path=config,
        trusted_certification_key_id=TEST_CERTIFICATION_KEY_ID,
        verifier=lambda _candidate: {"status": "passed"},
        provisioner=lambda _candidate: {"status": "passed"},
    )

    assert decoy["status"] == "blocked"
    assert decoy["findings"][-1]["field"] == "hermes_configuration"

    skills_dir = tmp_path / "skills-split"
    config = _hermes_config(skills_dir)
    text = config.read_text(encoding="utf-8")
    text = text.replace("  clinical_document_generation:\n", "skills:\n  clinical_document_generation:\n")
    config.write_text(text, encoding="utf-8")
    split = install_release(
        archive_path,
        skills_dir,
        hermes_config_path=config,
        trusted_certification_key_id=TEST_CERTIFICATION_KEY_ID,
        verifier=lambda _candidate: {"status": "passed"},
        provisioner=lambda _candidate: {"status": "passed"},
    )

    assert split["status"] == "blocked"
    assert split["findings"][-1]["field"] == "hermes_configuration"


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
        trusted_certification_key_id=TEST_CERTIFICATION_KEY_ID,
        verifier=lambda _candidate: {"status": "passed"},
        provisioner=_passing_provisioner,
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
    monkeypatch.setattr(workflow, "renderers", lambda **_kwargs: [{"kind": "LibreOffice", "source": "host prerequisite"}])
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
                "renderer": {"kind": "LibreOffice", "source": "host prerequisite"},
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
