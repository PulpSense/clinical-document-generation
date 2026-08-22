#!/usr/bin/env python3
"""Controlled fail-closed review, repair, and client handoff pipeline."""

from __future__ import annotations

import json
import hashlib
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from audit_static_toc import audit as audit_toc
from complete_protocol import protocol_completeness_missing
from delivery_gates import audit_docx_package, audit_generated_outputs, repair_docx_package
from export_docx_to_pdf import export_docx
from quality_contract import repair_report_markdown, validate_source_contract
from refresh_static_toc import refresh_docx
from validate_prs_xml import validate as validate_prs_xml
from render_templates import unresolved_in_docx, visible_text_from_word_xml
from pdf_text import extract_pdf_pages


PROSPECTIVE_ADVARRA_DOCUMENT_SET = (
    "output/protocol.docx",
    "output/icf.docx",
    "output/study.xml",
)
AMBISPECTIVE_DOCUMENT_SET = PROSPECTIVE_ADVARRA_DOCUMENT_SET
BRANCH_DOCUMENT_SETS = {
    "Prospective": PROSPECTIVE_ADVARRA_DOCUMENT_SET,
    "Ambispective": AMBISPECTIVE_DOCUMENT_SET,
}
MAX_TARGET_ATTEMPTS = 3


class DeliveryBlockedError(ValueError):
    """Raised when the final client-facing handoff cannot be validated."""


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _finding(field: str, issue: str, gate: str, evidence: str) -> dict[str, str]:
    return {"field": field, "issue": issue, "gate": gate, "evidence_required": evidence, "severity": "blocking"}


def _review_pass(name: str, findings: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"name": name, "status": "passed" if not findings else "failed", "finding_count": len(findings), "findings": findings, **extra}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        with zipfile.ZipFile(path) as archive:
            return "\n".join(
                visible_text_from_word_xml(archive.read(name).decode("utf-8", errors="ignore"))
                for name in archive.namelist()
                if name.startswith("word/") and name.endswith(".xml")
            )
    if path.suffix.lower() == ".xml":
        return " ".join(part.text or "" for part in ET.parse(path).getroot().iter())
    return path.read_text(encoding="utf-8", errors="replace")


def _prospective_package_findings(run_dir: Path, outputs: list[str], study_type: str) -> list[dict[str, Any]]:
    expected = set(BRANCH_DOCUMENT_SETS[study_type])
    observed = set(outputs)
    findings: list[dict[str, Any]] = []
    for relative in sorted(expected - observed):
        findings.append(_finding(relative, "Required Branch Document Set artifact is missing.", "Branch Package Gate", "A generated Protocol DOCX, ICF DOCX, and PRS XML."))
    for relative in sorted(observed - expected):
        findings.append(_finding(relative, f"Artifact is not part of the {study_type} Branch Document Set.", "Branch Package Gate", "Only Protocol DOCX, ICF DOCX, and PRS XML may be client-facing."))
    paths = {relative: run_dir / relative for relative in expected & observed}
    for relative, path in paths.items():
        if not path.is_file():
            findings.append(_finding(relative, "Required artifact does not exist.", "Branch Package Gate", "The generated artifact at the manifest path."))
    if findings:
        return findings

    reference = json.loads((run_dir / "reference/study.reference.json").read_text(encoding="utf-8"))
    shared = {
        "study.title": str((reference.get("study") or {}).get("title") or "").strip(),
        "meta.protocol_number": str((reference.get("meta") or {}).get("protocol_number") or "").strip(),
    }
    for relative, path in paths.items():
        text = _artifact_text(path)
        for field, value in shared.items():
            if value and value not in text:
                findings.append(_finding(f"{relative}:{field}", "Shared approved study fact is absent from the artifact.", "Cross-Document Consistency Gate", f"The approved source value `{value}` in the generated artifact."))
        if path.suffix.lower() == ".docx":
            unresolved = unresolved_in_docx(path)
            for token in unresolved:
                findings.append(_finding(f"{relative}:{token}", "Unresolved placeholder remains in the artifact.", "Content Completeness Gate", "A fully rendered artifact with no unresolved placeholders."))
    if study_type == "Ambispective":
        from icf import audit_icf_document, icf_contract

        icf_path = run_dir / "output/icf.docx"
        if icf_path.is_file():
            findings.extend(
                _finding(item["field"], item["issue"], "Cross-Document Consistency Gate", "The Ambispective existing-records disclosure inside the study-procedures section.")
                for item in audit_icf_document(icf_path, icf_contract("Ambispective", (reference.get("meta") or {}).get("icf_template")), reference)
            )
    return findings


def verify_branch_document_set(run_dir: Path, outputs: list[str], *, require_renderer: bool = False) -> dict[str, Any]:
    """Verify a prospective package without changing any generated artifact."""
    reference = json.loads((run_dir / "reference/study.reference.json").read_text(encoding="utf-8"))
    branch = str((reference.get("meta") or {}).get("study_type") or "")
    if branch not in BRANCH_DOCUMENT_SETS:
        return {"status": "failed", "review_passes": {"consistency": _review_pass("cross_document_consistency", [_finding("meta.study_type", "Branch package verification is not supported for this study type.", "Branch Package Gate", "Prospective or Ambispective branch metadata.")]), "structure": _review_pass("section_substance_and_structure", []), "visual": _review_pass("visual_layout_all_pages", [])}, "manual_verification_required": False}
    package_findings = _prospective_package_findings(run_dir, outputs, branch)
    if any(item.get("gate") == "Branch Package Gate" for item in package_findings):
        consistency = _review_pass("cross_document_consistency", package_findings)
        return {
            "status": "failed",
            "review_passes": {
                "consistency": consistency,
                "structure": _review_pass("section_substance_and_structure", []),
                "visual": _review_pass("visual_layout_all_pages", [], evidence={}),
            },
            "manual_verification_required": False,
        }
    structure = audit_generated_outputs(run_dir, outputs)
    structure_findings = [
        _finding(item.get("field", "unknown"), item.get("issue", "Structure check failed."), "Document Structure Gate", "A structurally valid Protocol and ICF with substantive contracted sections.")
        for item in structure.get("failures", [])
    ]
    consistency = _review_pass("cross_document_consistency", package_findings)
    structure_pass = _review_pass("section_substance_and_structure", structure_findings, audit=structure)

    visual_findings: list[dict[str, Any]] = []
    visual_evidence: dict[str, Any] = {}
    for relative in ("output/protocol.docx", "output/icf.docx"):
        path = run_dir / relative
        if not path.is_file():
            continue
        pdf_path = run_dir / "logs/docx-render" / f"{path.stem}.pdf"
        render, code = export_docx(path, pdf_path, require_renderer=require_renderer)
        evidence: dict[str, Any] = {"render": render, "pages": []}
        if render.get("status") == "exported" and pdf_path.is_file():
            pages = extract_pdf_pages(pdf_path)
            evidence["pages"] = [
                {"artifact": relative, "page": index, "status": "passed" if page.strip() else "failed", "evidence_sha256": _sha256(pdf_path)}
                for index, page in enumerate(pages, start=1)
            ]
            for item in evidence["pages"]:
                if item["status"] == "failed":
                    visual_findings.append(_finding(f"{relative}:page:{item['page']}", "Rendered page contains no inspectable evidence.", "Visual Layout Gate", "Rendered page evidence for every Protocol and ICF page."))
        elif code:
            visual_findings.append(_finding(f"{relative}:rendering", render.get("message", "Renderer failed."), "Visual Layout Gate", "A successful render by the Active Renderer."))
        visual_evidence[relative] = evidence
    visual = _review_pass("visual_layout_all_pages", visual_findings, evidence=visual_evidence)
    return {
        "status": "passed" if all(item["status"] == "passed" for item in (consistency, structure_pass, visual)) else "failed",
        "review_passes": {"consistency": consistency, "structure": structure_pass, "visual": visual},
        "manual_verification_required": any(item.get("render", {}).get("status") == "unavailable" for item in visual_evidence.values()),
    }


def bind_generation_manifest(run_dir: Path, manifest_path: Path, outputs: list[str], verification: dict[str, Any]) -> dict[str, Any]:
    """Bind exact inputs, contracts, renderer evidence, and artifact hashes to a revision manifest."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    reference = json.loads((run_dir / "reference/study.reference.json").read_text(encoding="utf-8"))
    manifest["branch_document_set"] = list(outputs)
    study_type = str((reference.get("meta") or {}).get("study_type") or "Prospective")
    icf_template = str((reference.get("meta") or {}).get("icf_template") or "Advarra").casefold()
    manifest["contracts"] = {**manifest.get("contracts", {}), "branch": f"{study_type.casefold()}-{icf_template}-package-v1", "source": "quality_contract", "prs_xml": "prs_xml_contract"}
    manifest["boilerplate"] = {"protocol": f"{study_type.casefold()}-protocol.template.docx", "icf": f"{icf_template}-icf.template.docx", "prs_xml": "clinicaltrials_prs_full_placeholder_template.xml"}
    template_paths = {
        "protocol": run_dir / "templates/protocol.template.docx",
        "icf": run_dir / "templates/icf.template.docx",
        "prs_xml": run_dir / "templates/study.template.xml",
    }
    manifest["templates"] = [
        {"path": str(path.relative_to(run_dir)), "sha256": _sha256(path)}
        for path in template_paths.values()
        if path.is_file()
    ]
    manifest["model"] = reference.get("generation", {}).get("model") or "gpt-5.5"
    manifest["renderer_evidence"] = verification.get("review_passes", {}).get("visual", {}).get("evidence", {})
    manifest["verification"] = verification
    manifest["artifacts"] = [{"path": relative, "sha256": _sha256(run_dir / relative)} for relative in outputs if (run_dir / relative).is_file()]
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def _classified_repair_report(findings: list[dict[str, Any]]) -> str:
    classes = {
        "Source-evidence gap": {"Source Completeness Gate", "Content Completeness Gate"},
        "Drafting failure": {"Content Completeness Gate"},
        "Cross-document contradiction": {"Cross-Document Consistency Gate"},
        "Document-structure failure": {"Package Hygiene Gate", "DOCX Structure Gate", "Document Structure Gate", "PRS XML Gate", "Branch Package Gate"},
        "Renderer failure": {"Visual Layout Gate"},
        "Visual defect": {"Static TOC Gate"},
    }
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in classes}
    for finding in findings:
        gate = str(finding.get("gate", ""))
        category = next((name for name, gates in classes.items() if gate in gates), "Document-structure failure")
        grouped[category].append(finding)
    lines = ["# Repair Report", "", "The Branch Document Set is blocked; no client-facing artifact is exposed.", ""]
    for category, items in grouped.items():
        if not items:
            continue
        lines.extend([f"## {category}", ""])
        for item in items:
            lines.extend([
                f"- `{item.get('field', 'unknown')}`: {item.get('issue', 'Review required.')}",
                f"  - Gate: {item.get('gate', 'unknown')}",
                f"  - Evidence/action: {item.get('evidence_required', 'Resolve and rerun the affected target.')}",
            ])
        lines.append("")
    return "\n".join(lines)


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
    max_repairs: int = MAX_TARGET_ATTEMPTS - 1,
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
    reference = json.loads((run_dir / "reference/study.reference.json").read_text(encoding="utf-8"))
    meta = reference.get("meta") if isinstance(reference.get("meta"), dict) else {}
    if str(meta.get("study_type", "")).casefold() in {"prospective", "ambispective"}:
        branch_report = verify_branch_document_set(run_dir, outputs, require_renderer=require_renderer)
        report["branch_package"] = branch_report
        report["review_passes"]["content"]["findings"].extend(branch_report["review_passes"]["consistency"]["findings"])
        report["review_passes"]["structure"]["findings"].extend(branch_report["review_passes"]["structure"]["findings"])
        report["review_passes"]["visual"]["findings"].extend(branch_report["review_passes"]["visual"]["findings"])
        report["status"] = "passed" if branch_report["status"] == "passed" and all(
            item["status"] == "passed" for item in report["review_passes"].values()
        ) else "failed"
    attempts.append({"phase": "initial", "status": report["status"]})
    if report["status"] != "passed" and max_repairs > 0:
        for repair_number in range(1, min(max_repairs, MAX_TARGET_ATTEMPTS - 1) + 1):
            repairs = []
            for relative in outputs:
                path = run_dir / relative
                if path.suffix.lower() == ".docx" and path.exists():
                    result = repair_docx_package(path)
                    if result.get("changed"):
                        repairs.append(result)
            if not repairs:
                attempts.append({"phase": "repair", "attempt": repair_number, "status": "no_recoverable_repair", "reused_section_drafts": True})
                break
            report = _review_once(
                run_dir,
                outputs,
                require_source_contract=require_source_contract,
                require_renderer=require_renderer,
            )
            if str(meta.get("study_type", "")).casefold() in {"prospective", "ambispective"}:
                branch_report = verify_branch_document_set(run_dir, outputs, require_renderer=require_renderer)
                report["branch_package"] = branch_report
                report["status"] = "passed" if branch_report["status"] == "passed" and report["status"] == "passed" else "failed"
            attempts.append({"phase": "after_controlled_repair", "attempt": repair_number, "status": report["status"], "repairs": repairs, "reused_section_drafts": True})
            if report["status"] == "passed":
                break
    report["attempts"] = attempts
    report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    report["max_repairs"] = max_repairs
    report["max_target_attempts"] = MAX_TARGET_ATTEMPTS
    if report["status"] != "passed":
        findings = [finding for review in report["review_passes"].values() for finding in review.get("findings", [])]
        repair_path = run_dir / "reference/repair-report.md"
        repair_path.parent.mkdir(parents=True, exist_ok=True)
        repair_path.write_text(_classified_repair_report(findings), encoding="utf-8")
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
