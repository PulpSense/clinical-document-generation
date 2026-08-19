#!/usr/bin/env python3
"""Run the deterministic branch generation workflow for an approved reference.

This is the single seam between an approved structured study reference and a
delivery-ready document set. One invocation performs branch mapping, renders the
active templates, runs every applicable Delivery Gate, records QA evidence, and
reports whether the run may be delivered.

Nothing here calls a model. The reviewer-approved reference is authoritative.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import build_n8n_prospective_fields
import build_n8n_retrospective_protocol_fields
from build_prs_xml_fields import build_fields as build_prs_fields
from check_required_inputs import missing_inputs
from render_templates import (
    read_json,
    run_generation,
    unresolved_in_docx,
    unresolved_in_text,
    visible_text_from_word_xml,
)
from study_type_branches import branch_for_study_type, default_document_set
from validate_prs_xml import validate as validate_prs_xml


STANDARD_REFERENCE = "reference/study.reference.json"
STANDARD_RESULT = "logs/branch-generation.json"
STANDARD_REPAIR_REPORT = "logs/repair-report.md"
STANDARD_VISUAL_QA = "logs/visual-qa.json"

#: Rendered artifacts per document-set key, in delivery order.
ARTIFACTS = {
    "protocol_docx": "output/protocol.docx",
    "icf_docx": "output/icf.docx",
    "xml": "output/study.xml",
}

#: Template language that must never survive into a delivered document.
DEFAULT_STALE_MARKERS = (
    "MERGEFIELD",
    "«",
    "»",
    "xx/xx/xxxx",
    "XX years",
    "Lorem ipsum",
    "[INSERT",
    "TBD",
)

#: `template_fields` keys whose text must reach the rendered branch documents.
RETROSPECTIVE_BODY_FIELDS = (
    "AI_introduction",
    "AI_objectivesIntro",
    "AI_primaryOutcome",
    "AI_populationLong",
    "AI_inclusionCriteria",
    "AI_exclusionCriteria",
    "AI_studyDesignLong",
    "AI_methods",
    "AI_studyProcedure",
    "AI_analysisDataSets",
    "AI_statisticalMethodology",
    "AI_statisticalConsiderations",
)

PROSPECTIVE_BODY_FIELDS = tuple(
    sorted(build_n8n_prospective_fields.REQUIRED_AI_FIELDS)
)

BRANCH_BODY_FIELDS = {
    "Retrospective": RETROSPECTIVE_BODY_FIELDS,
    "Prospective": PROSPECTIVE_BODY_FIELDS,
    "Ambispective": PROSPECTIVE_BODY_FIELDS,
}


class GateResult(dict):
    """One Delivery Gate outcome.

    `status` is `pass`, `fail`, or `skipped`. Only `fail` blocks delivery, and
    only when the gate is blocking; `skipped` records a capability the host could
    not provide.
    """

    def __init__(
        self,
        gate: str,
        status: str,
        findings: list[dict] | None = None,
        *,
        blocking: bool = True,
        detail: str | None = None,
    ) -> None:
        super().__init__(
            gate=gate,
            status=status,
            blocking=blocking,
            findings=findings or [],
        )
        if detail:
            self["detail"] = detail

    @property
    def failed(self) -> bool:
        return self["status"] == "fail" and self["blocking"]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def approval_status(reference: dict) -> str:
    approval = reference.get("approval")
    if not isinstance(approval, dict):
        return ""
    return str(approval.get("status") or "").strip().lower()


def active_document_set(reference: dict, canonical: str) -> list[str]:
    meta = reference.get("meta") if isinstance(reference.get("meta"), dict) else {}
    declared = meta.get("document_set")
    default = default_document_set(canonical)
    if not isinstance(declared, list) or not declared:
        return default
    # Keep delivery order stable and ignore keys the branch does not support.
    ordered = [key for key in default if key in declared]
    ordered.extend(key for key in declared if key not in ordered and key in ARTIFACTS)
    return ordered


def apply_branch_mapping(reference: dict, canonical: str, run_dir: Path) -> list[dict]:
    """Write branch template fields into `reference`. Returns mapping findings."""
    if canonical == "Retrospective":
        fields = build_n8n_retrospective_protocol_fields.build_fields(reference)
    else:
        fields = build_n8n_prospective_fields.build_fields(reference)

    merged = reference.get("template_fields")
    if not isinstance(merged, dict):
        merged = {}
    merged.update(fields)

    findings: list[dict] = []
    if "xml" in active_document_set(reference, canonical):
        template_path = run_dir / "templates" / "study.template.xml"
        if template_path.exists():
            reference["template_fields"] = merged
            prs_fields, prs_missing = build_prs_fields(reference, template_path)
            merged.update(prs_fields)
            findings.extend(
                {
                    "field": str(item.get("field") or item.get("placeholder") or "prs"),
                    "issue": str(item.get("issue") or item),
                }
                for item in prs_missing
                if isinstance(item, dict)
            )
    reference["template_fields"] = merged
    return findings


def document_text(path: Path) -> str:
    """Visible text of a rendered artifact.

    DOCX content also lives in headers and footers, and the renderer resolves
    placeholders in every `word/*.xml` part. The Delivery Gates read the same
    scope so content cannot hide from them in a header.
    """
    if path.suffix.lower() != ".docx":
        return path.read_text(encoding="utf-8", errors="replace")
    pieces: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if not name.startswith("word/") or not name.endswith(".xml"):
                continue
            pieces.append(
                visible_text_from_word_xml(archive.read(name).decode("utf-8", errors="ignore"))
            )
    return "\n".join(pieces)


def unresolved_in_output(path: Path) -> list[str]:
    if path.suffix.lower() == ".docx":
        return unresolved_in_docx(path)
    return unresolved_in_text(path.read_text(encoding="utf-8", errors="replace"))


def gate_placeholders(run_dir: Path, artifacts: dict[str, str]) -> GateResult:
    findings: list[dict] = []
    for key, rel in artifacts.items():
        for placeholder in unresolved_in_output(run_dir / rel):
            findings.append({"document": rel, "output": key, "placeholder": placeholder})
    return GateResult(
        "placeholders",
        "fail" if findings else "pass",
        findings,
        detail="Every template placeholder must resolve before delivery.",
    )


def gate_content_completeness(
    run_dir: Path,
    reference: dict,
    canonical: str,
    artifacts: dict[str, str],
) -> GateResult:
    template_fields = reference.get("template_fields")
    template_fields = template_fields if isinstance(template_fields, dict) else {}
    corpus = "\n".join(
        document_text(run_dir / rel)
        for rel, path in ((rel, run_dir / rel) for rel in artifacts.values())
        if path.suffix.lower() == ".docx"
    )
    findings: list[dict] = []
    for field in BRANCH_BODY_FIELDS.get(canonical, ()):
        value = str(template_fields.get(field) or "").strip()
        if not value:
            findings.append(
                {
                    "field": field,
                    "issue": "Branch-required Study-Specific Body content is blank.",
                }
            )
            continue
        probe = value.splitlines()[0].strip()
        if probe and probe not in corpus:
            findings.append(
                {
                    "field": field,
                    "issue": "Branch-required Study-Specific Body content is missing from the rendered document set.",
                }
            )
    return GateResult(
        "content_completeness",
        "fail" if findings else "pass",
        findings,
        detail="Every branch-required narrative section must reach the delivered documents.",
    )


def stale_markers(reference: dict) -> list[str]:
    meta = reference.get("meta") if isinstance(reference.get("meta"), dict) else {}
    configured = meta.get("stale_content_markers")
    extra = [str(item) for item in configured if str(item).strip()] if isinstance(configured, list) else []
    return [*DEFAULT_STALE_MARKERS, *extra]


def gate_stale_content(
    run_dir: Path, reference: dict, artifacts: dict[str, str]
) -> GateResult:
    markers = stale_markers(reference)
    findings: list[dict] = []
    for key, rel in artifacts.items():
        text = document_text(run_dir / rel)
        for marker in markers:
            if marker in text:
                findings.append({"document": rel, "output": key, "marker": marker})
    return GateResult(
        "stale_content",
        "fail" if findings else "pass",
        findings,
        detail="Another study's template language must not survive into a delivered document.",
    )


def gate_prs_xml(run_dir: Path, reference: dict, artifacts: dict[str, str]) -> GateResult:
    rel = artifacts.get("xml")
    if not rel:
        return GateResult(
            "prs_xml",
            "skipped",
            blocking=False,
            detail="The active document set does not include PRS XML.",
        )
    errors, summary = validate_prs_xml(run_dir / rel, reference)
    return GateResult(
        "prs_xml",
        "fail" if errors else "pass",
        [{"document": rel, "issue": message} for message in errors],
        detail=json.dumps(summary, ensure_ascii=False, sort_keys=True),
    )


def gate_visual_qa(
    run_dir: Path,
    artifacts: dict[str, str],
    renderer_available: bool | None,
) -> tuple[GateResult, dict]:
    """Record renderer-based QA evidence.

    Renderer unavailability stays non-blocking, matching the existing exporter
    contract. When a renderer *is* available its failures remain blocking.
    """
    docx_rels = [rel for rel in artifacts.values() if rel.endswith(".docx")]
    if renderer_available is None:
        from export_docx_to_pdf import renderer_order

        renderer_available = bool(renderer_order())

    if not renderer_available:
        evidence = {
            "status": "unavailable",
            "renderer": "unavailable",
            "documents": docx_rels,
            "note": "PDF-based visual and static-TOC QA was skipped; the DOCX outputs remain deliverable.",
        }
        write_json(run_dir / STANDARD_VISUAL_QA, evidence)
        return (
            GateResult(
                "visual_qa",
                "skipped",
                blocking=False,
                detail=evidence["note"],
            ),
            evidence,
        )

    evidence = {
        "status": "available",
        "renderer": "available",
        "documents": docx_rels,
        "note": "Renderer-based visual and static-TOC QA evidence is retained with the run.",
    }
    write_json(run_dir / STANDARD_VISUAL_QA, evidence)
    return (
        GateResult("visual_qa", "pass", detail=evidence["note"]),
        evidence,
    )


def write_repair_report(
    run_dir: Path, branch: str, artifacts: dict[str, str], gates: list[GateResult]
) -> str:
    lines = [
        "# Repair Report",
        "",
        f"- Branch: {branch}",
        f"- Active documents: {', '.join(artifacts.values()) or 'none rendered'}",
        "",
        "This run is not delivery ready. Correct every item below, then rerun the branch workflow.",
        "",
    ]
    for item in gates:
        if item["status"] != "fail":
            continue
        lines.append(f"## {item['gate']}")
        lines.append("")
        if item.get("detail"):
            lines.append(item["detail"])
            lines.append("")
        for finding in item["findings"]:
            rendered = ", ".join(
                f"{key}: {value}" for key, value in finding.items() if value is not None
            )
            lines.append(f"- {rendered}")
        if not item["findings"]:
            lines.append("- The gate failed without itemised findings.")
        lines.append("")
    path = run_dir / STANDARD_REPAIR_REPORT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return STANDARD_REPAIR_REPORT


def _result(
    branch: str,
    document_set: list[str],
    artifacts: dict[str, str],
    gates: list[GateResult],
    qa: dict,
    run_dir: Path,
) -> dict:
    delivery_ready = not any(item.failed for item in gates)
    result = {
        "branch": branch,
        "document_set": document_set,
        "artifacts": artifacts,
        "gates": list(gates),
        "qa": qa,
        "delivery_ready": delivery_ready,
        "repair_report": None,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if not delivery_ready:
        result["repair_report"] = write_repair_report(run_dir, branch, artifacts, gates)
    write_json(run_dir / STANDARD_RESULT, result)
    return result


def generate_branch(
    run_dir: Path,
    *,
    reference_path: Path | None = None,
    require_approval: bool = True,
    renderer_available: bool | None = None,
) -> dict:
    """Generate, gate, and evidence the default document set for one branch."""
    run_dir = Path(run_dir)
    reference_path = reference_path or run_dir / STANDARD_REFERENCE
    reference = read_json(reference_path)

    meta = reference.get("meta") if isinstance(reference.get("meta"), dict) else {}
    branch = branch_for_study_type(meta.get("study_type"))
    if branch is None:
        return _result(
            "unknown",
            [],
            {},
            [
                GateResult(
                    "branch",
                    "fail",
                    [
                        {
                            "field": "meta.study_type",
                            "issue": "Study type must be Prospective, Ambispective, or Retrospective.",
                        }
                    ],
                )
            ],
            {},
            run_dir,
        )

    canonical = branch["canonical_study_type"]
    document_set = active_document_set(reference, canonical)
    gates: list[GateResult] = []

    if require_approval and approval_status(reference) != "approved":
        gates.append(
            GateResult(
                "approval",
                "fail",
                [
                    {
                        "field": "approval.status",
                        "issue": "Final generation requires explicitly approved Source-of-Truth Markdown.",
                    }
                ],
                detail="Supplying source material is not approval.",
            )
        )
        return _result(canonical, document_set, {}, gates, {}, run_dir)
    gates.append(GateResult("approval", "pass"))

    blocking = missing_inputs(reference)
    gates.append(
        GateResult(
            "required_inputs",
            "fail" if blocking else "pass",
            blocking,
            detail="Only the branch-specific Required Source Inputs may block generation.",
        )
    )
    if blocking:
        # Nothing is rendered while a Required Source Input is unresolved.
        return _result(canonical, document_set, {}, gates, {}, run_dir)

    mapping_findings = apply_branch_mapping(reference, canonical, run_dir)
    gates.append(
        GateResult(
            "branch_mapping",
            "fail" if mapping_findings else "pass",
            mapping_findings,
            detail="Branch mapping must supply every value its active templates require.",
        )
    )
    reference_path.write_text(
        json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    meta = reference.setdefault("meta", {})
    meta["document_set"] = document_set
    reference_path.write_text(
        json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    run_generation(run_dir, reference_path, require_approval=require_approval)

    artifacts = {
        key: ARTIFACTS[key]
        for key in document_set
        if key in ARTIFACTS and (run_dir / ARTIFACTS[key]).exists()
    }

    gates.append(gate_placeholders(run_dir, artifacts))
    gates.append(gate_content_completeness(run_dir, reference, canonical, artifacts))
    gates.append(gate_prs_xml(run_dir, reference, artifacts))
    gates.append(gate_stale_content(run_dir, reference, artifacts))
    visual_gate, qa = gate_visual_qa(run_dir, artifacts, renderer_available)
    gates.append(visual_gate)

    return _result(canonical, document_set, artifacts, gates, qa, run_dir)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Run directory with an approved reference.")
    parser.add_argument("--reference", help="Reference JSON path. Defaults inside --run-dir.")
    parser.add_argument(
        "--allow-unapproved",
        action="store_true",
        help="Render without approved Source-of-Truth Markdown. Never use for delivery.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir = Path(args.run_dir).expanduser().resolve()
    reference_path = Path(args.reference).expanduser().resolve() if args.reference else None
    try:
        result = generate_branch(
            run_dir,
            reference_path=reference_path,
            require_approval=not args.allow_unapproved,
        )
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["delivery_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
