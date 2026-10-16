#!/usr/bin/env python3
"""Source preparation, approval and generation-only native document lifecycle."""
from __future__ import annotations
import argparse
import copy
import json
import os
import shutil
import sys
import tempfile
import zipfile
from xml.etree import ElementTree
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from docx import Document
from docx.opc.exceptions import PackageNotFoundError

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from contracts import contracted_template_bundle, document_set, get_path, parse_source_truth, repair_report, set_path, source_contract, source_truth_markdown
from drafting import governing_resources, ingest_responses, merged_drafts, missing_drafts, pending_requests, schedule_requests, sha256_file, sha256_value
from prs_xml import generate as generate_xml
from rendering import render_documents, refresh_protocol_fields
from contracts import applicable_required_inputs, required_input_value



REFERENCE = Path("reference/study.reference.json")

def _write_atomic_run_state(path: Path, value: Mapping[str, Any]) -> None:
    """Commit run state without exposing partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)

def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if exc.errno not in {22, 45}:
            raise
    finally:
        os.close(descriptor)

def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict): raise ValueError(f"Expected JSON object: {path}")
    return value

def _write(path: Path, value: Mapping[str, Any]) -> None:
    _write_atomic_run_state(path, value)

def _reference(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    path = run_dir / REFERENCE
    if not path.is_file(): raise FileNotFoundError(f"Create {path} from the study inputs before running prepare.")
    return path, _read(path)

def _slug(value: Any) -> str:
    text = "".join(character.lower() if character.isalnum() else "-" for character in str(value or "study"))
    return "-".join(part for part in text.split("-") if part)[:60] or "study"

def _source_path(run_dir: Path, reference: Mapping[str, Any]) -> Path:
    recorded = reference.get("source", {}).get("source_of_truth_file") if isinstance(reference.get("source"), Mapping) else None
    if recorded:
        path = Path(str(recorded)); return path if path.is_absolute() else run_dir / path
    protocol = reference.get("meta", {}).get("protocol_number") if isinstance(reference.get("meta"), Mapping) else "study"
    title = reference.get("study", {}).get("title") if isinstance(reference.get("study"), Mapping) else "study"
    return run_dir / "reference" / f"source-of-truth--{_slug(protocol)}--{_slug(title)}.md"

def _approved_payload(reference: Mapping[str, Any]) -> dict[str, Any]:
    """Return only reviewer-controlled and approval-bound data."""
    payload = copy.deepcopy(dict(reference))
    payload.pop("generation", None)
    payload.pop("approval", None)
    return payload

def _approval_valid(
    run_dir: Path,
    reference: Mapping[str, Any],
    *,
    contracted_bundle: Mapping[str, Any] | None = None,
) -> tuple[bool, str]:
    approval_value = reference.get("approval")
    approval: Mapping[str, Any] = approval_value if isinstance(approval_value, Mapping) else {}
    source = _source_path(run_dir, reference)
    if str(approval.get("status", "")).casefold() != "approved": return False, "The Source-of-Truth Markdown has not been explicitly approved."
    if not source.is_file(): return False, "The approved Source-of-Truth Markdown is missing."
    if approval.get("source_sha256") != sha256_file(source): return False, "The Source-of-Truth Markdown changed after approval; approve the current file again."
    revision_id = str(approval.get("revision_id") or "")
    snapshot_path = run_dir / "revisions" / revision_id / "approved-reference.json"
    approved_source = run_dir / "revisions" / revision_id / "approved-source.md"
    if not revision_id or not snapshot_path.is_file() or not approved_source.is_file():
        return False, "The write-once approved revision snapshot is missing."
    if sha256_file(approved_source) != approval.get("source_sha256"):
        return False, "The approved revision copy of the Source-of-Truth is not hash-identical."
    if approval.get("approved_reference_sha256") != sha256_file(snapshot_path):
        return False, "The approved reference snapshot changed after approval."
    snapshot = _read(snapshot_path)
    if _approved_payload(reference) != _approved_payload(snapshot):
        return False, "Study inputs changed after approval; prepare and approve a new Source-of-Truth revision."
    snapshot_approval_value = snapshot.get("approval")
    snapshot_approval: Mapping[str, Any] = snapshot_approval_value if isinstance(snapshot_approval_value, Mapping) else {}
    recorded_source_identity = str(approval.get("source_approval_identity") or "")
    snapshot_source_identity = str(snapshot_approval.get("source_approval_identity") or "")
    if recorded_source_identity or snapshot_source_identity:
        expected_source_identity = sha256_value({
            "approved_source_sha256": approval.get("source_sha256"),
            "approved_reference": _approved_payload(snapshot),
        })
        if (
            recorded_source_identity != expected_source_identity
            or snapshot_source_identity != expected_source_identity
        ):
            return False, "The Source approval identity does not match the immutable approved source."
    # Approval is bound to reviewer-controlled source identity. Generation
    # authority is rebound by candidate fingerprints and the immutable gate
    # ledger, so an internal code/template repair does not demand reapproval.
    return True, ""

_OPTIONAL_REVIEW_FIELDS = (
    "study.condition",
    "design.intervention_description",
    "procedures.methods",
    "procedures.unscheduled_visits",
    "procedures.discontinuation",
    "procedures.termination",
    "procedures.study_termination",
    "statistics.methodology",
    "statistics.analysis_populations",
    "statistics.missing_data_handling",
    "safety.general_information",
    "safety.monitoring",
    "safety.adverse_events",
    "safety.follow_up",
    "confidentiality.data_handling",
    "confidentiality.publication",
    "risks_benefits.risks",
    "risks_benefits.risk_mitigation",
    "risks_benefits.benefits",
    "risks_benefits.costs",
    "risks_benefits.alternatives",
    "risks_benefits.privacy",
    "risks_benefits.injury_handling",
)

_OPTIONAL_PRS_REVIEW_FIELDS = (
    "regulatory.prs.observational_study_design",
    "regulatory.prs.time_perspective",
    "regulatory.prs.verification_date",
    "regulatory.prs.start_date",
    "regulatory.prs.start_date_type",
    "regulatory.prs.primary_completion_date",
    "regulatory.prs.primary_completion_date_type",
    "regulatory.prs.study_completion_date",
    "regulatory.prs.study_completion_date_type",
    "regulatory.prs.patient_registry",
    "regulatory.prs.target_duration_quantity",
    "regulatory.prs.target_duration_units",
)

def _ensure_optional_review_fields(reference: dict[str, Any], branch: str | None) -> None:
    missing = object()
    paths = _OPTIONAL_REVIEW_FIELDS + (_OPTIONAL_PRS_REVIEW_FIELDS if branch != "Retrospective" else ())
    for path in paths:
        if get_path(reference, path, missing) is missing:
            set_path(reference, path, None)
    for outcome_kind in ("primary", "secondary", "other"):
        outcomes = get_path(reference, f"endpoints.{outcome_kind}")
        if not isinstance(outcomes, list):
            continue
        for outcome in outcomes:
            if isinstance(outcome, dict):
                outcome.setdefault("description", "")
                outcome.setdefault("analysis_method", "")

def _intake_review_guidance(reference: Mapping[str, Any]) -> dict[str, Any]:
    """Expose original extraction evidence to AI; do not infer a clinical conflict."""
    requirements = applicable_required_inputs(reference)
    return {
        "instructions": (
            "Before requesting Source-of-Truth approval, compare the original input evidence, "
            "supplied candidate values, declared aliases and raw sample-size evidence rows with this obligatory-input checklist. "
            "AI determines whether facts are actually missing or conflicting; parser inability, "
            "paraphrases and different units or representations are not proof of a conflict. "
            "Apply references/intake-workflow.md's study-design clarification guidance: compare declared "
            "study type with explicit treatment-assignment descriptions, resolve actual disagreement "
            "with the user before requesting approval, and record the clarified facts in the editable source. "
            "For observational studies, an assigned test article is not required. AI may derive a descriptive "
            "activity name or classification from explicit source facts, or record not applicable; show "
            "these normalizations in the Source-of-Truth for approval. Preserve routine product use without "
            "implying study assignment. Ask one consolidated question for actual missing obligatory facts and unresolved material "
            "source conflicts. Keep optional inputs optional. Resolve extraction omissions from supplied "
            "evidence yourself, then regenerate the editable file and obtain one explicit approval. "
            "Do not request approval of a source whose actual material conflicts remain unresolved."
        ),
        "obligatory_inputs": [
            {"field": requirement.field, "label": requirement.label or requirement.field,
             "value": copy.deepcopy(required_input_value(reference, requirement)),
             "supplied_representations": {
                 path: copy.deepcopy(get_path(reference, path))
                 for path in (requirement.field, *requirement.aliases)
                 if get_path(reference, path) is not None
             }} for requirement in requirements
        ],
        "field_candidates": copy.deepcopy(get_path(reference, "source.field_candidates", {})),
        "sample_size_evidence": {
            path: copy.deepcopy(get_path(reference, path))
            for path in ("population.sample_size_evidence", "statistics.sample_size_evidence")
            if get_path(reference, path) is not None
        },
    }

def prepare(run_dir: Path, *, today: date | None = None, **_: Any) -> dict[str, Any]:
    """Validate mandatory inputs and create the reviewer-editable source file."""
    run_dir = run_dir.resolve(); reference_path, reference = _reference(run_dir)
    intake_review = _intake_review_guidance(reference)
    contract = source_contract(reference, derive_prs_study_type=True)
    if contract["status"] != "passed":
        reference_dir = run_dir / "reference"
        reference_dir.mkdir(parents=True, exist_ok=True)
        source_report = reference_dir / "missing-inputs.md"
        technical_report = reference_dir / "technical-validation-report.md"
        if contract["source_gaps"]:
            source_report.write_text(repair_report(contract["source_gaps"]), encoding="utf-8")
        else:
            source_report.unlink(missing_ok=True)
        if contract["technical_findings"]:
            technical_report.write_text(repair_report(contract["technical_findings"]), encoding="utf-8")
        else:
            technical_report.unlink(missing_ok=True)
        return {
            "status": "blocked",
            "stage": "input_collection" if contract["source_gaps"] else "technical_validation",
            "study_type": contract.get("study_type"),
            "intake_review": intake_review,
            "missing": contract["source_gaps"],
            "source_gaps": contract["source_gaps"],
            "technical_findings": contract["technical_findings"],
            "findings": contract["blocking_findings"],
            "missing_inputs": source_report.relative_to(run_dir).as_posix() if contract["source_gaps"] else None,
            "technical_report": technical_report.relative_to(run_dir).as_posix() if contract["technical_findings"] else None,
            "client_outputs": [],
        }
    reference = contract["normalized_reference"]
    _ensure_optional_review_fields(reference, contract.get("study_type"))
    meta = reference.setdefault("meta", {})
    if not str(meta.get("date") or "").strip():
        meta["date"] = (today or date.today()).strftime("%d %b %Y")
    if meta.get("version") is None:
        meta["version"] = ""
    source = _source_path(run_dir, reference); source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(source_truth_markdown(reference), encoding="utf-8")
    reference.setdefault("source", {})["source_of_truth_file"] = source.relative_to(run_dir).as_posix()
    reference["approval"] = {"status": "awaiting_approval", "review_file": source.relative_to(run_dir).as_posix()}
    _write(reference_path, reference)
    (run_dir / "reference/missing-inputs.md").unlink(missing_ok=True)
    relative_source = source.relative_to(run_dir).as_posix()
    review_delivery = {
        "mode": "file",
        "role": "editable_source_of_truth",
        "path": relative_source,
        "absolute_path": source.resolve().as_posix(),
        "filename": source.name,
        "link": f"[{source.name}](<{source.resolve().as_posix()}>)",
        "mime_type": "text/markdown",
        "editable": True,
        "inline_chat": False,
        "must_attach": True,
    }
    source_review_reply = {
        "message": f"Please review or edit the Source-of-Truth: {review_delivery['link']}\n\nApprove this file when the study facts are correct.",
        "attachments": [dict(review_delivery)],
        "inline_source": False,
    }
    return {"status": "awaiting_approval", "stage": "source_review", "study_type": contract.get("study_type"), "source_of_truth": relative_source, "review_delivery": review_delivery, "source_review_reply": source_review_reply, "intake_review": intake_review, "client_outputs": []}

def approve(run_dir: Path, *, approved_by: str = "client", source_md: Path | None = None, **_: Any) -> dict[str, Any]:
    """Parse the current reviewer file exactly and bind explicit approval."""
    run_dir = run_dir.resolve(); reference_path, prior = _reference(run_dir)
    source = source_md.resolve() if source_md else _source_path(run_dir, prior)
    if not source.is_file(): raise FileNotFoundError(source)
    reference_dir = (run_dir / "reference").resolve()
    try: source.relative_to(reference_dir)
    except ValueError:
        canonical = reference_dir / "approved-source-of-truth.md"; shutil.copy2(source, canonical); source = canonical
    parsed = parse_source_truth(source.read_text(encoding="utf-8"), prior)
    contract = source_contract(parsed)
    report_path = run_dir / "reference/review-parse-report.md"
    report_path.write_text(repair_report(contract["blocking_findings"]), encoding="utf-8")
    if contract["status"] != "passed":
        return {"status": "blocked", "stage": "approval", "findings": contract["blocking_findings"], "client_outputs": []}
    reference = contract["normalized_reference"]
    reference.pop("generation", None)
    reference.setdefault("source", {})["source_of_truth_file"] = source.relative_to(run_dir).as_posix()
    digest = sha256_file(source)
    approval = {"status": "approved", "approved_by": approved_by, "approved_at": datetime.now(timezone.utc).isoformat(), "review_file": source.relative_to(run_dir).as_posix(), "source_sha256": digest}
    reference["approval"] = approval
    bundle = contracted_template_bundle(SCRIPT_DIR.parent, reference)
    governing = governing_resources(SCRIPT_DIR.parent, reference, contracted_bundle=bundle)
    governing_sha256 = sha256_value(governing)
    source_approval_identity = sha256_value({
        "approved_source_sha256": digest,
        "approved_reference": _approved_payload(reference),
    })
    revision_identity = source_approval_identity
    revision_id = f"r-{revision_identity[:12]}"
    approval["revision_id"] = revision_id
    approval["source_approval_identity"] = source_approval_identity
    approval["generation_authority_sha256"] = governing_sha256
    # Retain the legacy audit key without using it as source-approval identity.
    approval["governing_sha256"] = governing_sha256
    revision_dir = run_dir / "revisions" / revision_id
    snapshot_path = revision_dir / "approved-reference.json"
    approved_source_path = revision_dir / "approved-source.md"
    if revision_dir.exists():
        if not snapshot_path.is_file() or not approved_source_path.is_file():
            return {"status": "blocked", "stage": "approval", "findings": [{"category": "revision", "field": revision_id, "issue": "An incomplete revision already occupies the approved source hash."}], "client_outputs": []}
        existing = _read(snapshot_path)
        if _approved_payload(existing) != _approved_payload(reference) or sha256_file(approved_source_path) != digest:
            return {"status": "blocked", "stage": "approval", "findings": [{"category": "revision", "field": revision_id, "issue": "A different write-once revision already occupies the approved source hash."}], "client_outputs": []}
        reference["approval"] = dict(existing.get("approval", approval))
    else:
        revision_dir.mkdir(parents=True)
        _write(snapshot_path, reference)
        approved_source_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    reference["approval"]["approved_reference_sha256"] = sha256_file(snapshot_path)
    _write(reference_path, reference)
    return {"status": "passed", "stage": "approval", "revision_id": revision_id, "source_sha256": digest, "client_outputs": []}

def validate(run_dir: Path, **_: Any) -> dict[str, Any]:
    run_dir = run_dir.resolve(); _, reference = _reference(run_dir)
    contract = source_contract(reference); approved, approval_issue = _approval_valid(run_dir, reference)
    findings = list(contract["blocking_findings"])
    if not approved: findings.append({"category": "approval", "field": "approval", "issue": approval_issue})
    return {"status": "passed" if not findings else "blocked", "stage": "readiness", "study_type": contract.get("study_type"), "findings": findings, "client_outputs": []}

def _awaiting(revision_dir: Path, *, stage: str, paths: Sequence[Path], findings: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    handoffs = [{"request_path": path.relative_to(revision_dir).as_posix(),
                 "response_path": str((request := _read(path))["response_path"]),
                 "task": str(request["task"]), "batch_id": request.get("batch_id")}
                for path in paths]
    return {"status": "awaiting_hermes", "stage": stage, "revision_id": revision_dir.name,
            "requests": [item["request_path"] for item in handoffs], "handoffs": handoffs,
            "findings": list(findings or []), "client_outputs": []}

def generate_only(run_dir: Path) -> dict[str, Any]:
    """Experimental drafting and first native assembly, without review or repair."""
    run_dir = run_dir.expanduser().resolve()
    _, working = _reference(run_dir)
    approved, issue = _approval_valid(run_dir, working)
    if not approved:
        return {"status": "blocked", "stage": "approval_gate", "findings": [{"issue": issue}], "client_outputs": []}
    revision = run_dir / "revisions" / working["approval"]["revision_id"]
    reference = _read(revision / "approved-reference.json")
    bundle = contracted_template_bundle(SCRIPT_DIR.parent, reference)
    governing = governing_resources(SCRIPT_DIR.parent, reference, contracted_bundle=bundle)
    identity = sha256_value(governing)
    workspace = revision / "generation-only" / identity[:16]
    workspace.mkdir(parents=True, exist_ok=True)
    marker = workspace / "generation-only.json"
    if not marker.exists():
        _write(marker, {"profile": "n8n-with-brad-corrections/v1", "governing_sha256": identity,
                        "started_at": datetime.now(timezone.utc).isoformat()})
    base = {"mode": "generation_only", "workspace": str(workspace),
            "revision_id": working["approval"]["revision_id"], "client_outputs": []}
    manifest_path = workspace / "experiment-manifest.json"
    if manifest_path.is_file():
        saved = _read(manifest_path)
        for entry in saved["experimental_outputs"]:
            path = Path(entry["absolute_path"])
            if not path.is_file() or sha256_file(path) != entry["sha256"]:
                return {**base, "status": "blocked", "stage": "file_integrity",
                        "findings": [{"issue": f"Saved experimental output changed or is missing: {path}"}]}
        return saved
    # Invalid response JSON can be corrected manually without invoking any
    # content reviewer or automatic drafting/repair loop.
    for rejected in (workspace / "hermes/rejected").glob("*.json"):
        (workspace / "hermes/accepted-requests" / rejected.name).unlink(missing_ok=True)
        rejected.unlink()
    findings = ingest_responses(workspace, governing)
    if findings:
        return {**base, "status": "blocked", "stage": "drafting_response",
                "findings": findings, "experimental_outputs": []}
    schedule_requests(repo_root=SCRIPT_DIR.parent, revision_dir=workspace,
                      revision_id=working["approval"]["revision_id"], reference=reference,
                      wave="generation-only", contracted_bundle=bundle)
    pending = pending_requests(workspace, governing)
    if pending:
        result = _awaiting(workspace, stage="drafting", paths=pending)
        return {**result, **base}
    missing = missing_drafts(workspace, reference, SCRIPT_DIR.parent, contracted_bundle=bundle)
    if missing:
        return {**base, "status": "blocked", "stage": "drafting_response",
                "findings": [{"issue": f"Missing draft: {target}"} for target in missing]}
    model = merged_drafts(workspace, reference, governing)
    _write(workspace / "merged-drafts.json", model)
    report = render_documents(SCRIPT_DIR.parent, workspace, reference, model,
                              contracted_bundle=bundle, audit_output=False)
    _write(workspace / "assembly-report.json", report)
    if report["status"] != "passed":
        return {**base, "status": "blocked", "stage": "assembly", "findings": report["artifacts"]}
    try:
        field_refresh = refresh_protocol_fields(workspace / "candidate/protocol.docx")
    except (OSError, RuntimeError, ValueError) as exc:
        return {**base, "status": "blocked", "stage": "office_field_refresh",
                "findings": [{"issue": str(exc)}], "experimental_outputs": []}
    _write(workspace / "office-field-refresh.json", field_refresh)
    if bundle.get("prs_authority"):
        prs = bundle["prs_authority"]
        generate_xml(SCRIPT_DIR.parent / prs["generation_template"]["path"],
                     workspace / "candidate/study.xml", reference, model["prs"],
                     structural_template=SCRIPT_DIR.parent / prs["structural_reference"]["path"],
                     check_output=False)
    names = document_set(get_path(reference, "meta.study_type"))
    try:
        # Availability checks only: native files exist and can be opened. No
        # quality, content, visual, XML contract or publication gate runs here.
        for name in names:
            path = workspace / "candidate" / name
            if path.suffix == ".docx":
                Document(path)
            else:
                ElementTree.parse(path)
    except (OSError, ValueError, zipfile.BadZipFile, PackageNotFoundError, ElementTree.ParseError) as exc:
        return {**base, "status": "blocked", "stage": "file_integrity", "findings": [{"issue": str(exc)}]}
    output = run_dir / "output"
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        return {**base, "status": "blocked", "stage": "output_conflict",
                "findings": [{"issue": f"Output folder is not empty; use a new run folder: {output}"}]}
    entries = []
    for name in names:
        path = output / name
        shutil.move(str(workspace / "candidate" / name), str(path))
        entries.append({"absolute_path": str(path), "path": path.relative_to(run_dir).as_posix(),
                        "sha256": sha256_file(path), "link": f"[{name}](<{path.as_posix()}>)"})
    notice = workspace / "README.txt"
    notice.write_text(
        "UNREVIEWED EXPERIMENT — not client-ready.\n"
        "Generated using n8n prompts with approved-source and Brad editorial corrections, "
        "plus current instructions for additional sections and the current DOCX/XML builders.\n"
        "One office pagination pass populated TOC fields; its internal PDF was discarded.\n"
        "No content review, visual review, post-generation quality gates or automatic repairs ran.\n"
        "Inspect these files against the approved source and references/brad-review-coverage.md.\n",
        encoding="utf-8")
    started = datetime.fromisoformat(_read(marker)["started_at"])
    elapsed_seconds = (datetime.now(timezone.utc) - started).total_seconds()
    minutes, seconds = divmod(round(elapsed_seconds, 2), 60)
    result = {**base, "status": "unreviewed", "stage": "generation_only_complete",
              "experimental_outputs": entries, "notice": str(notice),
              "delivery_message": "Here are the documents:\n\n" + "\n".join(
                  f"- {entry['link']}" for entry in entries)
                  + f"\n\nGeneration time: {int(minutes)} minutes {seconds:.2f} seconds.",
              "manifest": str(manifest_path), "governing_sha256": identity,
              "elapsed_seconds": elapsed_seconds,
              "assessments": {"content": "not_run", "visual": "not_run"}}
    result["office_field_refresh"] = field_refresh
    _write(manifest_path, result)
    return result

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare, approve and generate native clinical documents.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--stage", choices=("prepare", "approve", "validate", "generate"), required=True)
    parser.add_argument("--approved-by", default="client")
    parser.add_argument("--source-md")
    parser.add_argument("--generation-only", action="store_true", help="Compatibility flag; generation always uses this profile.")
    args = parser.parse_args(argv)
    if args.generation_only and args.stage != "generate":
        parser.error("--generation-only requires --stage generate")
    run_dir = Path(args.run_dir).expanduser().resolve()
    result = {"prepare": prepare, "approve": approve, "validate": validate, "generate": generate_only}[args.stage](
        run_dir, **({"approved_by": args.approved_by,
                    "source_md": Path(args.source_md).expanduser() if args.source_md else None}
                   if args.stage == "approve" else {}))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") in {"passed", "awaiting_approval", "awaiting_hermes", "unreviewed"} else 1


__all__ = ["prepare", "approve", "validate", "generate_only"]

if __name__ == "__main__":
    raise SystemExit(main())
