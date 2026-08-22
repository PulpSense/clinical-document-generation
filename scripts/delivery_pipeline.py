#!/usr/bin/env python3
"""Controlled fail-closed review, repair, and client handoff pipeline."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from audit_static_toc import audit as audit_toc
from complete_protocol import protocol_completeness_missing
from delivery_gates import audit_docx_package, audit_generated_outputs, repair_docx_package
from export_docx_to_pdf import export_docx
from quality_contract import repair_report_markdown, validate_source_contract
from refresh_static_toc import refresh_docx
from validate_prs_xml import validate as validate_prs_xml


class DeliveryBlockedError(ValueError):
    """Raised when the final client-facing handoff cannot be validated."""


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _finding(field: str, issue: str, gate: str, evidence: str) -> dict[str, str]:
    return {"field": field, "issue": issue, "gate": gate, "evidence_required": evidence, "severity": "blocking"}


def _review_pass(name: str, findings: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"name": name, "status": "passed" if not findings else "failed", "finding_count": len(findings), "findings": findings, **extra}


def _review_once(
    run_dir: Path,
    outputs: list[str],
    *,
    require_source_contract: bool,
    require_renderer: bool,
    export_render: bool = True,
) -> dict[str, Any]:
    reference_path = run_dir / "reference/study.reference.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    content_findings = protocol_completeness_missing(reference, strict_operational=True)
    content = [_finding(item["field"], item["issue"], "Content Completeness Gate", "Approved Source-of-Truth evidence or a reviewer repair.") for item in content_findings]
    if require_source_contract:
        contract = validate_source_contract(reference, require_approval=True, require_tables=True, run_dir=run_dir)
        content.extend(_finding(item["field"], item["issue"], "Source Completeness Gate", item.get("evidence_required", "Approved source evidence or reviewer decision.")) for item in contract["blocking_findings"])
    for relative in outputs:
        if relative.endswith(".xml"):
            xml_path = run_dir / relative
            if not xml_path.is_file():
                content.append(_finding(relative, "Declared PRS XML output does not exist.", "PRS XML Gate", "A generated XML artifact for the branch document set."))
                continue
            xml_errors, _xml_report = validate_prs_xml(xml_path, reference)
            content.extend(_finding(relative, error, "PRS XML Gate", "A schema-valid PRS XML artifact whose repeated rows match the approved reference.") for error in xml_errors)
    content_pass = _review_pass("content_completeness_and_source_fidelity", content, contract_checked=require_source_contract)
    _write_json(run_dir / "logs/reviews/content-completeness.json", content_pass)

    package_findings: list[dict[str, Any]] = []
    package_reports = []
    if not outputs:
        package_findings.append(_finding("outputs", "No generated client artifact was supplied to the delivery pipeline.", "Client Handoff Gate", "At least one generated artifact that passed every required gate."))
    for relative in outputs:
        path = run_dir / relative
        if not path.exists():
            package_findings.append(_finding(relative, "Declared generated artifact does not exist.", "Client Handoff Gate", "The declared output path must exist after generation."))
            continue
        if path.suffix.lower() != ".docx" or not path.exists():
            continue
        errors = audit_docx_package(path)
        package_findings.extend(_finding(item["field"], item["issue"], "Package Hygiene Gate", "A valid, renderer-openable DOCX package without disallowed assets.") for item in errors)
        package_reports.append({"output": relative, "errors": errors, "size_bytes": path.stat().st_size})
    package = _review_pass("package_hygiene", package_findings, packages=package_reports)
    _write_json(run_dir / "logs/reviews/package-hygiene.json", package)

    structure_report = audit_generated_outputs(run_dir, outputs)
    structure_findings = [_finding(item["field"], item["issue"], "DOCX Structure Gate", "A structurally valid DOCX with complete sections, tables, and no unresolved placeholders.") for item in structure_report.get("failures", [])]
    structure = _review_pass("docx_structure_and_table_geometry", structure_findings, audit=structure_report)
    _write_json(run_dir / "logs/reviews/docx-structure.json", structure)

    visual_findings: list[dict[str, Any]] = []
    toc_findings: list[dict[str, Any]] = []
    render_report: dict[str, Any] = {"status": "skipped", "message": "Protocol output was not rendered."}
    toc_report: dict[str, Any] = {"status": "skipped", "reason": "No rendered PDF evidence supplied."}
    protocol = run_dir / "output/protocol.docx"
    pdf = run_dir / "logs/docx-render/protocol.pdf"
    if protocol.exists() and export_render:
        render_report, render_code = export_docx(protocol, pdf, require_renderer=require_renderer)
        _write_json(run_dir / "logs/docx-render/protocol.json", render_report)
        if render_report.get("status") == "exported":
            try:
                refresh_report = refresh_docx(protocol, pdf, protocol)
                _write_json(run_dir / "logs/toc-refresh.json", refresh_report)
                second_render, second_code = export_docx(protocol, pdf, require_renderer=True)
                _write_json(run_dir / "logs/docx-render/protocol-second.json", second_render)
                if second_code:
                    visual_findings.append(_finding("rendering", second_render.get("message", "Second render failed."), "Visual Layout Gate", "A successful final render from the configured Client Rendering Authority."))
                toc_report = audit_toc(protocol, pdf)
                toc_report["status"] = "passed" if not (toc_report["mismatch_count"] or toc_report["missing_count"] or toc_report["alignment_mismatch_count"]) else "failed"
                _write_json(run_dir / "logs/toc-audit.json", toc_report)
                for item in toc_report.get("mismatches", []) + toc_report.get("missing", []) + toc_report.get("alignment_mismatches", []):
                    toc_findings.append(_finding(item.get("title", "static_toc"), item.get("reason", "Static TOC does not match the final rendered document."), "Static TOC Gate", "A second render with matching page numbers, all required entries, and right dot-leader alignment."))
            except (OSError, ValueError, SystemExit) as exc:
                toc_findings.append(_finding("static_toc", str(exc), "Static TOC Gate", "A final render that can be refreshed and audited."))
        elif render_code:
            visual_findings.append(_finding("rendering", render_report.get("message", "Renderer unavailable."), "Visual Layout Gate", "A successful render, or an explicitly accepted renderer-unavailable limitation."))
    visual = _review_pass("visual_layout", visual_findings, render=render_report)
    toc = _review_pass("static_toc", toc_findings, audit=toc_report)
    _write_json(run_dir / "logs/reviews/visual-layout.json", visual)
    _write_json(run_dir / "logs/reviews/static-toc.json", toc)

    return {
        "status": "passed" if all(item["status"] == "passed" for item in (content_pass, package, structure, visual, toc)) else "failed",
        "review_passes": {
            "content": content_pass,
            "package": package,
            "structure": structure,
            "visual": visual,
            "toc": toc,
        },
        "internal_artifacts": [
            "logs/generation-report.json",
            "logs/reviews/",
            "logs/docx-render/",
            "logs/toc-refresh.json",
            "logs/toc-audit.json",
            "reference/repair-report.md",
        ],
    }


def run_delivery_pipeline(
    run_dir: Path,
    outputs: list[str],
    *,
    require_source_contract: bool = False,
    require_renderer: bool = False,
    max_repairs: int = 1,
) -> dict[str, Any]:
    """Run read-only reviews, apply only controlled repairs, then rerun all gates."""
    started = time.perf_counter()
    attempts = []
    report = _review_once(
        run_dir,
        outputs,
        require_source_contract=require_source_contract,
        require_renderer=require_renderer,
    )
    attempts.append({"phase": "initial", "status": report["status"]})
    if report["status"] != "passed" and max_repairs > 0:
        repairs = []
        for relative in outputs:
            path = run_dir / relative
            if path.suffix.lower() == ".docx" and path.exists():
                result = repair_docx_package(path)
                if result.get("changed"):
                    repairs.append(result)
        if repairs:
            report = _review_once(
                run_dir,
                outputs,
                require_source_contract=require_source_contract,
                require_renderer=require_renderer,
            )
            attempts.append({"phase": "after_controlled_repair", "status": report["status"], "repairs": repairs})
        else:
            attempts.append({"phase": "repair", "status": "no_recoverable_repair"})
    report["attempts"] = attempts
    report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    report["max_repairs"] = max_repairs
    if report["status"] != "passed":
        findings = [finding for review in report["review_passes"].values() for finding in review.get("findings", [])]
        repair_path = run_dir / "reference/repair-report.md"
        repair_path.parent.mkdir(parents=True, exist_ok=True)
        repair_path.write_text(repair_report_markdown(findings), encoding="utf-8")
        report["repair_report"] = "reference/repair-report.md"
        report["client_outputs"] = []
    else:
        report["client_outputs"] = [relative for relative in outputs if (run_dir / relative).is_file()]
    _write_json(run_dir / "logs/delivery-pipeline.json", report)
    return report


def validated_client_outputs(run_dir: Path, report: dict[str, Any]) -> list[Path]:
    """Expose only outputs named by a passing delivery pipeline."""
    if report.get("status") != "passed":
        return []
    return [run_dir / relative for relative in report.get("client_outputs", []) if (run_dir / relative).is_file()]
