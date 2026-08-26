#!/usr/bin/env python3
"""The single public lifecycle for the clinical-document skill."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path: sys.path.insert(0, str(SCRIPT_DIR))

from contracts import batch_plan, canonical_study_type, document_set, get_path, icf_contract, parse_source_truth, protocol_contract, repair_report, set_path, source_contract, source_truth_markdown
from drafting import MAX_ATTEMPTS, governing_resources, ingest_responses, invalidate_accepted_targets, merged_drafts, missing_drafts, pending_requests, recorded_acceptance_response, retry_attempts, schedule_requests, sha256_file, sha256_value
from prs_xml import generate as generate_xml
from quality import create_verification_requests, pending_verifications, preflight, quality_report, render_pages, sha256_file as quality_sha256
from rendering import render_documents, template_paths


REFERENCE = Path("reference/study.reference.json")
MAX_VERIFICATION_ATTEMPTS = 3


@dataclass(frozen=True)
class RetryTarget:
    category: str
    value: str

    @classmethod
    def parse(cls, target_id: str) -> "RetryTarget":
        category, separator, value = target_id.partition(":")
        return cls(category, value) if separator else cls("section", target_id)

    @property
    def target_id(self) -> str:
        return self.value if self.category == "section" else f"{self.category}:{self.value}"


VERIFICATION_TASK_BY_TARGET = {
    "content": "clinical_content_verification",
    "visual": "rendered_page_visual_verification",
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict): raise ValueError(f"Expected JSON object: {path}")
    return value


def _read_corpus(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"Expected a JSON list of objects: {path}")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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


def _approval_valid(run_dir: Path, reference: Mapping[str, Any]) -> tuple[bool, str]:
    approval = reference.get("approval") if isinstance(reference.get("approval"), Mapping) else {}
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
    expected_governing = sha256_value(governing_resources(SCRIPT_DIR.parent, snapshot))
    if approval.get("governing_sha256") != expected_governing:
        return False, "Generation contracts, templates, or implementation changed after approval; approve the unchanged Source-of-Truth again to create a new immutable revision."
    return True, ""


_OPTIONAL_REVIEW_FIELDS = (
    "study.condition",
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


def prepare(run_dir: Path, *, today: date | None = None, **_: Any) -> dict[str, Any]:
    """Validate mandatory inputs and create the reviewer-editable source file."""
    run_dir = run_dir.resolve(); reference_path, reference = _reference(run_dir)
    contract = source_contract(reference)
    if contract["status"] != "passed":
        path = run_dir / "reference/missing-inputs.md"; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(repair_report(contract["blocking_findings"]), encoding="utf-8")
        return {"status": "blocked", "stage": "input_collection", "study_type": contract.get("study_type"), "missing": contract["blocking_findings"], "missing_inputs": path.relative_to(run_dir).as_posix(), "client_outputs": []}
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
        "mime_type": "text/markdown",
        "editable": True,
        "inline_chat": False,
        "must_attach": True,
    }
    return {"status": "awaiting_approval", "stage": "source_review", "study_type": contract.get("study_type"), "source_of_truth": relative_source, "review_delivery": review_delivery, "client_outputs": []}


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
    governing = governing_resources(SCRIPT_DIR.parent, reference)
    governing_sha256 = sha256_value(governing)
    revision_identity = sha256_value({
        "approved_source_sha256": digest,
        "approved_reference": _approved_payload(reference),
        "governing_resources": governing,
    })
    revision_id = f"r-{revision_identity[:12]}"
    approval["revision_id"] = revision_id
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


def _awaiting(revision_dir: Path, *, stage: str, paths: list[Path], findings: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    handoffs = []
    for path in paths:
        request = _read(path)
        handoffs.append({
            "request_path": path.relative_to(revision_dir).as_posix(),
            "response_path": str(request["response_path"]),
            "task": str(request["task"]),
            "batch_id": request.get("batch_id"),
        })
    return {
        "status": "awaiting_hermes",
        "stage": stage,
        "revision_id": revision_dir.name,
        "requests": [item["request_path"] for item in handoffs],
        "handoffs": handoffs,
        "findings": list(findings or []),
        "client_outputs": [],
    }


def _candidate_fingerprint(repo_root: Path, revision_dir: Path, reference: Mapping[str, Any], model: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    protocol_template, icf_template = template_paths(repo_root, reference)
    templates = [path for path in (protocol_template, icf_template) if path is not None]
    if canonical_study_type(get_path(reference, "meta.study_type")) != "Retrospective":
        templates.append(repo_root / "assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml")
        templates.append(repo_root / "assets/client-templates/reference/prs-manual-reference.xml")
    implementation_files = [repo_root / "scripts" / name for name in ("workflow.py", "contracts.py", "drafting.py", "rendering.py", "quality.py", "prs_xml.py")]
    accepted_files = sorted((revision_dir / "hermes/accepted").glob("*.json"))
    payload = {
        "approved_reference_sha256": sha256_file(revision_dir / "approved-reference.json"),
        "approved_source_sha256": get_path(reference, "approval.source_sha256"),
        "drafting_resources": governing_resources(repo_root, reference),
        "templates": {path.relative_to(repo_root).as_posix(): sha256_file(path) for path in templates},
        "implementation": {path.name: sha256_file(path) for path in implementation_files},
        "accepted_drafts": {path.relative_to(revision_dir).as_posix(): sha256_file(path) for path in accepted_files},
        "merged_model_sha256": sha256_value(model),
    }
    return sha256_value(payload), payload


def _cached_build(revision_dir: Path, fingerprint: str) -> dict[str, Any] | None:
    path = revision_dir / "candidate-build.json"
    if not path.is_file():
        return None
    try:
        build = _read(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if build.get("fingerprint") != fingerprint:
        return None
    for artifact in build.get("candidate_files", []):
        target = revision_dir / str(artifact.get("path"))
        if not target.is_file() or sha256_file(target) != artifact.get("sha256"):
            return None
    render_report = build.get("render_report", {})
    for artifact in render_report.get("artifacts", []):
        for key in ("docx", "pdf"):
            target = revision_dir / str(artifact.get(key))
            if not target.is_file() or sha256_file(target) != artifact.get(f"{key}_sha256"):
                return None
        for page in artifact.get("pages", []):
            target = revision_dir / str(page.get("path"))
            if not target.is_file() or sha256_file(target) != page.get("sha256"):
                return None
    return build


def _record_build(revision_dir: Path, fingerprint: str, governing: Mapping[str, Any], document_report: Mapping[str, Any], xml_report: Mapping[str, Any] | None, render_report: Mapping[str, Any]) -> dict[str, Any]:
    candidate_files = [{"path": path.relative_to(revision_dir).as_posix(), "sha256": sha256_file(path), "bytes": path.stat().st_size} for path in sorted((revision_dir / "candidate").glob("*")) if path.is_file()]
    build = {"fingerprint": fingerprint, "governing_resources": dict(governing), "candidate_files": candidate_files, "document_report": dict(document_report), "xml_report": dict(xml_report) if xml_report else None, "render_report": dict(render_report)}
    _write(revision_dir / "candidate-build.json", build)
    return build


def _drafting_evidence(revision_dir: Path) -> list[dict[str, Any]]:
    evidence = []
    for path in sorted((revision_dir / "hermes/accepted").glob("*.json")):
        item = _read(path)
        request_id = str(item.get("request_id") or "")
        accepted_request = revision_dir / "hermes/accepted-requests" / f"{request_id}.json"
        evidence.append({
            "path": path.relative_to(revision_dir).as_posix(),
            "sha256": sha256_file(path),
            "request_id": request_id,
            "request_sha256": item.get("request_sha256"),
            "accepted_request_path": accepted_request.relative_to(revision_dir).as_posix() if accepted_request.is_file() else None,
            "accepted_request_file_sha256": sha256_file(accepted_request) if accepted_request.is_file() else None,
            "producer": item.get("producer"),
        })
    return evidence


def _publish(run_dir: Path, revision_dir: Path, reference: Mapping[str, Any], quality: Mapping[str, Any]) -> dict[str, Any]:
    sources = sorted((revision_dir / "candidate").glob("*.docx")) + sorted((revision_dir / "candidate").glob("*.xml"))
    expected = set(document_set(get_path(reference, "meta.study_type")))
    actual = {source.name for source in sources}
    if actual != expected:
        raise RuntimeError(f"Atomic publication requires the exact branch document set; expected={sorted(expected)}, actual={sorted(actual)}")
    output = run_dir / "output"
    staging = Path(tempfile.mkdtemp(prefix=".output-staging-", dir=run_dir))
    backup: Path | None = None
    try:
        for source in sources:
            shutil.copy2(source, staging / source.name)
        if output.exists():
            backup = Path(tempfile.mkdtemp(prefix=".output-backup-", dir=run_dir))
            backup.rmdir()
            os.replace(output, backup)
        try:
            os.replace(staging, output)
        except Exception:
            if backup is not None and backup.exists() and not output.exists():
                os.replace(backup, output)
            raise
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    if backup is not None and backup.exists():
        shutil.rmtree(backup)
    published = [
        {"path": (output / source.name).relative_to(run_dir).as_posix(), "sha256": quality_sha256(output / source.name), "bytes": (output / source.name).stat().st_size}
        for source in sources
    ]
    build_path = revision_dir / "candidate-build.json"
    build = _read(build_path) if build_path.is_file() else {}
    manifest = {"status": "passed", "revision_id": revision_dir.name, "study_type": canonical_study_type(reference.get("meta", {}).get("study_type")), "approved_source_sha256": reference.get("approval", {}).get("source_sha256"), "approved_reference_sha256": sha256_file(revision_dir / "approved-reference.json"), "candidate_build_sha256": sha256_file(build_path) if build_path.is_file() else None, "governing_resources": build.get("governing_resources", {}), "drafting_evidence": _drafting_evidence(revision_dir), "quality": quality, "client_outputs": published}
    _write(revision_dir / "delivery-manifest.json", manifest); _write(run_dir / "logs/generation-report.json", manifest)
    return {"status": "passed", "stage": "delivery", "revision_id": revision_dir.name, "client_outputs": [item["path"] for item in published], "manifest": (revision_dir / "delivery-manifest.json").relative_to(run_dir).as_posix()}


def _clear_verification_responses(revision_dir: Path, tasks: set[str] | None = None) -> None:
    for request_path in (revision_dir / "hermes/verification-requests").glob("*.json"):
        try:
            request = _read(request_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if tasks is None or str(request.get("task")) in tasks:
            (revision_dir / str(request.get("response_path", ""))).unlink(missing_ok=True)


def _archive_failed_attempt(revision_dir: Path, stage: str, findings: list[Mapping[str, Any]]) -> Path:
    """Preserve the complete failed candidate and QA evidence before any retry mutation."""
    archive_root = revision_dir / "attempts"
    archive_root.mkdir(parents=True, exist_ok=True)
    safe_stage = _slug(stage)
    sequence = 1
    while (archive_root / f"{safe_stage}-a{sequence:02d}").exists():
        sequence += 1
    destination = archive_root / f"{safe_stage}-a{sequence:02d}"
    destination.mkdir()
    retained = (
        Path("candidate"),
        Path("rendered"),
        Path("candidate-build.json"),
        Path("hermes/accepted"),
        Path("hermes/accepted-requests"),
        Path("hermes/verification-requests"),
        Path("hermes/verification-responses"),
    )
    for relative in retained:
        source = revision_dir / relative
        target = destination / relative
        if source.is_dir():
            shutil.copytree(source, target)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    files = {
        path.relative_to(destination).as_posix(): sha256_file(path)
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }
    _write(destination / "attempt-manifest.json", {
        "revision_id": revision_dir.name,
        "stage": stage,
        "attempt": sequence,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "findings": [dict(item) for item in findings],
        "files": files,
    })
    return destination


def _quality_retry(
    run_dir: Path,
    reference_path: Path,
    working_reference: dict[str, Any],
    approved_reference: Mapping[str, Any],
    revision_dir: Path,
    prior_attempts: Mapping[str, int],
    findings: list[Mapping[str, Any]],
    stage: str,
) -> dict[str, Any]:
    """Retry draftable targets; deterministic layout defects require an actual repair."""
    _archive_failed_attempt(revision_dir, stage, findings)
    transient = [item for item in findings if item.get("category") == "reviewer-transient"]
    if transient:
        verification_attempts = working_reference.setdefault("generation", {}).setdefault("verification_attempts", {})
        exhausted = []
        tasks = set()
        for item in transient:
            target = str((item.get("target_ids") or [item.get("field")])[0])
            next_attempt = int(verification_attempts.get(target, 0)) + 1
            verification_attempts[target] = next_attempt
            retry_target = RetryTarget.parse(target)
            task = VERIFICATION_TASK_BY_TARGET.get(retry_target.value) if retry_target.category == "verification" else None
            if task:
                tasks.add(task)
            if next_attempt > MAX_VERIFICATION_ATTEMPTS:
                exhausted.append({
                    **dict(item),
                    "field": target,
                    "issue": f"Reviewer retry limit reached after {MAX_VERIFICATION_ATTEMPTS} attempts. {item.get('issue', '')}".strip(),
                })
        _write(reference_path, working_reference)
        if exhausted:
            path = run_dir / "reference/repair-report.md"
            path.write_text(repair_report(exhausted), encoding="utf-8")
            return {"status": "blocked", "stage": "reviewer_retry_limit", "findings": exhausted, "repair_report": path.relative_to(run_dir).as_posix(), "client_outputs": []}
        _clear_verification_responses(revision_dir, tasks)
        remaining = [item for item in findings if item.get("category") != "reviewer-transient"]
        if not remaining:
            return _awaiting(
                revision_dir,
                stage="independent_verification_retry",
                paths=sorted((revision_dir / "hermes/verification-requests").glob("*.json")),
                findings=transient,
            )
        findings = remaining
    known_sections = {section.section_id for section in protocol_contract(str(get_path(approved_reference, "meta.study_type", "")))}
    if canonical_study_type(get_path(approved_reference, "meta.study_type")) != "Retrospective":
        known_sections.update(section.section_id for section in icf_contract(
            str(get_path(approved_reference, "meta.study_type", "")),
            str(get_path(approved_reference, "meta.icf_template", "Advarra")),
        ))
        known_sections.update(("prs.brief-summary", "prs.detailed-description"))
    draftable_sections = {
        section_id
        for batch in batch_plan(
            str(get_path(approved_reference, "meta.study_type", "")),
            str(get_path(approved_reference, "meta.icf_template", "Advarra")),
        )
        for section_id in batch.section_ids
    }
    normalized: list[dict[str, Any]] = []
    for raw in findings:
        finding = dict(raw)
        targets = [str(item) for item in finding.get("target_ids", []) if item] if isinstance(finding.get("target_ids"), list) else []
        if not targets:
            field = str(finding.get("field") or "")
            if field in known_sections:
                targets = [field]
            elif finding.get("category") == "visual" or "visual" in field:
                targets = [f"layout:{finding.get('artifact') or 'documents'}"]
            elif "content" in field or finding.get("category") == "verification":
                targets = ["verification:content"]
            else:
                targets = ["layout:documents"]
        finding["target_ids"] = targets
        normalized.append(finding)
    targets = {RetryTarget.parse(target) for finding in normalized for target in finding["target_ids"]}
    section_targets = {
        target.target_id
        for target in targets
        if target.category == "section" and target.target_id in draftable_sections
    }
    deterministic_targets = {
        target.target_id
        for target in targets
        if target.category == "section"
        and target.target_id in known_sections
        and target.target_id not in draftable_sections
    }
    has_layout_target = any(target.category == "layout" for target in targets)
    if deterministic_targets and not section_targets:
        path = run_dir / "reference/repair-report.md"
        path.write_text(repair_report(normalized), encoding="utf-8")
        return {
            "status": "blocked",
            "stage": "deterministic_repair",
            "findings": normalized,
            "repair_report": path.relative_to(run_dir).as_posix(),
            "client_outputs": [],
        }
    attempts, exhausted = retry_attempts(normalized, prior_attempts)
    working_reference.setdefault("generation", {})["attempts"] = attempts
    _write(reference_path, working_reference)
    if exhausted:
        path = run_dir / "reference/repair-report.md"; path.write_text(repair_report(exhausted), encoding="utf-8")
        return {"status": "blocked", "stage": stage, "findings": exhausted, "repair_report": path.relative_to(run_dir).as_posix(), "client_outputs": []}
    if section_targets:
        invalidate_accepted_targets(revision_dir, section_targets)
        (revision_dir / "candidate-build.json").unlink(missing_ok=True)
        _clear_verification_responses(revision_dir)
        created = schedule_requests(repo_root=SCRIPT_DIR.parent, revision_dir=revision_dir, revision_id=revision_dir.name, reference=approved_reference, attempts=attempts, wave="quality-retry", findings=normalized)
        if created:
            return _awaiting(revision_dir, stage="drafting_retry", paths=created, findings=normalized)
    if has_layout_target:
        for relative in (
            "candidate",
            "rendered",
            "hermes/verification-requests",
            "hermes/verification-responses",
        ):
            shutil.rmtree(revision_dir / relative, ignore_errors=True)
        (revision_dir / "candidate-build.json").unlink(missing_ok=True)
    else:
        tasks = {
            task
            for target in targets
            if target.category == "verification"
            for task in [VERIFICATION_TASK_BY_TARGET.get(target.value)]
            if task is not None
        }
        _clear_verification_responses(revision_dir, tasks or None)
    return generate(run_dir)


def generate(run_dir: Path, **_: Any) -> dict[str, Any]:
    """Advance one approved revision until it needs Hermes work or passes."""
    run_dir = run_dir.resolve(); reference_path, working_reference = _reference(run_dir)
    approved, approval_issue = _approval_valid(run_dir, working_reference)
    revision_id = str(working_reference.get("approval", {}).get("revision_id") or "")
    revision_dir = run_dir / "revisions" / revision_id
    reference = _read(revision_dir / "approved-reference.json") if approved else working_reference
    contract = source_contract(reference)
    if contract["status"] != "passed" or not approved:
        findings = list(contract["blocking_findings"])
        if not approved: findings.append({"category": "approval", "field": "approval", "issue": approval_issue})
        return {"status": "blocked", "stage": "approval_gate", "findings": findings, "client_outputs": []}
    if not revision_id or not revision_dir.is_dir(): return {"status": "blocked", "stage": "revision", "findings": [{"category": "revision", "field": "revision_id", "issue": "Approved immutable revision is missing."}], "client_outputs": []}
    state = working_reference.setdefault("generation", {})
    expected_governing = governing_resources(SCRIPT_DIR.parent, reference)
    governing_sha256 = sha256_value(expected_governing)
    prior_governing_sha256 = state.get("governing_sha256")
    if prior_governing_sha256 is not None and prior_governing_sha256 != governing_sha256:
        return {
            "status": "blocked",
            "stage": "revision",
            "findings": [{
                "category": "revision",
                "field": revision_id,
                "issue": "Generation resources changed inside an immutable revision.",
                "required": "Approve the unchanged Source-of-Truth again to create a new revision.",
            }],
            "client_outputs": [],
        }
    elif prior_governing_sha256 is None:
        state["governing_sha256"] = governing_sha256
        _write(reference_path, working_reference)
    preflight_report = state.get("renderer_preflight")
    if not isinstance(preflight_report, Mapping) or preflight_report.get("status") != "passed":
        preflight_report = preflight(SCRIPT_DIR.parent, reference)
        if preflight_report["status"] != "passed":
            state["renderer_preflight"] = preflight_report
            _write(reference_path, working_reference)
            return {"status": "blocked", "stage": "renderer_preflight", "findings": preflight_report["findings"], "renderer_preflight": preflight_report, "client_outputs": []}
        state["renderer_preflight"] = preflight_report
        _write(reference_path, working_reference)
    attempts = state.setdefault("attempts", {})
    persisted_exhaustion = [
        {"category": "retry", "field": str(target), "issue": f"Retry limit reached after {MAX_ATTEMPTS} attempts.", "required": "Reviewer intervention before a new approved revision."}
        for target, count in attempts.items() if int(count) > MAX_ATTEMPTS
    ]
    if persisted_exhaustion:
        path = run_dir / "reference/repair-report.md"; path.write_text(repair_report(persisted_exhaustion), encoding="utf-8")
        return {"status": "blocked", "stage": "retry_limit", "findings": persisted_exhaustion, "repair_report": path.relative_to(run_dir).as_posix(), "client_outputs": []}
    drafting_findings = ingest_responses(revision_dir, expected_governing)
    if drafting_findings:
        attempts, exhausted = retry_attempts(drafting_findings, attempts); state["attempts"] = attempts; _write(reference_path, working_reference)
        source_gaps = [item for item in drafting_findings if item.get("category") in {"source-evidence", "request-integrity"}]
        if source_gaps or exhausted:
            path = run_dir / "reference/repair-report.md"; path.write_text(repair_report([*source_gaps, *exhausted]), encoding="utf-8")
            return {"status": "blocked", "stage": "drafting", "findings": [*source_gaps, *exhausted], "repair_report": path.relative_to(run_dir).as_posix(), "client_outputs": []}
        created = schedule_requests(repo_root=SCRIPT_DIR.parent, revision_dir=revision_dir, revision_id=revision_id, reference=reference, attempts=attempts, wave="retry", findings=drafting_findings)
        if created: return _awaiting(revision_dir, stage="drafting_retry", paths=created, findings=drafting_findings)
    created = schedule_requests(repo_root=SCRIPT_DIR.parent, revision_dir=revision_dir, revision_id=revision_id, reference=reference, attempts=attempts, wave="initial")
    pending = pending_requests(revision_dir, expected_governing)
    if created or pending: return _awaiting(revision_dir, stage="drafting", paths=pending or created)
    missing = missing_drafts(revision_dir, reference, SCRIPT_DIR.parent)
    if missing: return {"status": "blocked", "stage": "drafting", "findings": [{"category": "drafting", "field": item, "issue": "Required section has no accepted draft after all requests were processed."} for item in missing], "client_outputs": []}

    model = merged_drafts(revision_dir, reference)
    fingerprint, governing = _candidate_fingerprint(SCRIPT_DIR.parent, revision_dir, reference, model)
    build = _cached_build(revision_dir, fingerprint)
    if build is None:
        document_report = render_documents(SCRIPT_DIR.parent, revision_dir, reference, model)
        if document_report["status"] != "passed":
            findings = [{**finding, "target_ids": [f"layout:{item['artifact']}"]} for item in document_report["artifacts"] for finding in item["findings"]]
            return _quality_retry(run_dir, reference_path, working_reference, reference, revision_dir, attempts, findings, "rendering")
        xml_report = None
        if canonical_study_type(reference.get("meta", {}).get("study_type")) != "Retrospective":
            template = SCRIPT_DIR.parent / "assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml"
            xml_report = generate_xml(
                template,
                revision_dir / "candidate/study.xml",
                reference,
                model.get("prs", {}),
                structural_template=SCRIPT_DIR.parent / "assets/client-templates/reference/prs-manual-reference.xml",
            )
            if xml_report["status"] != "passed":
                findings = [{**finding, "target_ids": ["layout:xml"]} for finding in xml_report["findings"]]
                return _quality_retry(run_dir, reference_path, working_reference, reference, revision_dir, attempts, findings, "xml")
        render_report = render_pages(revision_dir, renderer_identity=preflight_report["renderer"])
        if render_report["status"] != "passed":
            findings = [{**finding, "target_ids": ["layout:documents"]} for finding in render_report["findings"]]
            return _quality_retry(run_dir, reference_path, working_reference, reference, revision_dir, attempts, findings, "rendered_document_qa")
        build = _record_build(revision_dir, fingerprint, governing, document_report, xml_report, render_report)
    else:
        document_report = build["document_report"]
        xml_report = build.get("xml_report")
        render_report = build["render_report"]
    create_verification_requests(revision_dir, reference, render_report)
    pending_checks = pending_verifications(revision_dir)
    if pending_checks: return _awaiting(revision_dir, stage="independent_verification", paths=pending_checks)
    final_quality = quality_report(revision_dir, reference, render_report, xml_report)
    if final_quality["status"] != "passed":
        return _quality_retry(run_dir, reference_path, working_reference, reference, revision_dir, attempts, final_quality["findings"], "quality")
    return _publish(run_dir, revision_dir, reference, final_quality)


def _save_recorded_handoff(revision_dir: Path, request_path: Path) -> None:
    request = _read(request_path)
    response = recorded_acceptance_response(request)
    _write(revision_dir / request["response_path"], response)


def _save_verification_response(revision_dir: Path, request_path: Path, responder: Callable[[Mapping[str, Any]], Mapping[str, Any]]) -> None:
    request = _read(request_path)
    _write(revision_dir / request["response_path"], responder(request))


def run_release_gate(
    repo_root: Path,
    *,
    verification_responder: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Exercise all six lifecycle cases; genuine verifier responses remain external."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if evidence_root is not None:
        root = evidence_root.resolve()
    else:
        base = (repo_root / ".scratch/release-gate" / timestamp).resolve()
        root = base
        suffix = 1
        while root.exists():
            root = base.with_name(f"{base.name}-{suffix}")
            suffix += 1
    root.mkdir(parents=True, exist_ok=True)
    results = []
    corpus = _read_corpus(repo_root / "tests/fixtures/branch-acceptance-corpus.json")
    for case in [item for item in corpus if str(item.get("profile", "")).endswith("complete")]:
            branch = str(case["study_type"]); richness = str(case["profile"]).split("-", 1)[0]
            run_dir = root / str(case["fixture_id"])
            if not (run_dir / REFERENCE).is_file():
                reference = _read(repo_root / str(case["source_fixture"]))
                reference["meta"]["protocol_number"] = f"{branch[:3].upper()}-{richness}-26"; reference["study"]["title"] = f"{branch} {richness} acceptance study"; reference["study"]["short_title"] = f"{branch} {richness} acceptance"
                if richness == "rich" and branch != "Retrospective":
                    reference["meta"]["icf_template"] = "Sterling"
                if richness == "rich":
                    reference["study"]["background"] = f"{reference['study']['background'].rstrip('.')} with extended follow-up."
                    reference["study"]["timeline"] = "6 months"
                    reference["procedures"]["assessments"] = list(reference["procedures"].get("assessments", [])) + ["Extended follow-up assessment"]
                    reference["procedures"]["visit_schedule_table"] = list(reference["procedures"].get("visit_schedule_table", [])) + [{"visitNumber": "4", "visitName": "Month 6", "visitWindow": "±14 days", "CRFnumber": "CRF-04"}]
                    reference["population"]["sample_size"] = "80 participants"
                    for item in reference["population"].get("sample_size_evidence", []):
                        if isinstance(item, dict): item["value"] = "80 participants"
                    for item in reference.get("statistics", {}).get("sample_size_evidence", []):
                        if isinstance(item, dict): item["value"] = "80 participants"
                    if branch != "Retrospective":
                        reference["endpoints"].setdefault("other", []).extend([{"label": "Extended follow-up outcome", "time_point": "Month 6"}, {"label": "Participant experience outcome", "time_point": "Month 6"}])
                        reference["design"]["interventions"] = [{"name": "Sentinel Patch", "type": "Device", "description": "Primary monitoring configuration.", "arm_group_label": "Primary cohort"}, {"name": "Sentinel Patch Extended", "type": "Device", "description": "Extended monitoring configuration.", "arm_group_label": "Extended cohort"}]
                        reference["design"]["arms"] = [{"name": "Primary cohort", "description": "Primary observational cohort."}, {"name": "Extended cohort", "description": "Extended observational cohort."}]
                    if reference.get("sites"):
                        second_site = copy.deepcopy(reference["sites"][0]); second_site["facility"]["name"] = "Site Two"; second_site["contact"]["name"] = "Taylor Coordinator"; second_site["contact"]["email"] = "taylor@example.org"; second_site["investigators"][0]["name"] = "Morgan Investigator"
                        reference["sites"].append(second_site); reference["design"]["number_of_sites"] = 2
                        reference["design"]["study_design"] = str(reference["design"]["study_design"]).replace("single-center", "multicenter")
                reference["approval"] = {"status": "draft"}; _write(run_dir / REFERENCE, reference)
                first = prepare(run_dir)
                if first.get("status") != "awaiting_approval": results.append({"case": run_dir.name, "status": "failed", "result": first}); continue
                approval = approve(run_dir, approved_by="Recorded Acceptance")
                if approval.get("status") != "passed": results.append({"case": run_dir.name, "status": "failed", "result": approval}); continue
            reference = _read(run_dir / REFERENCE)
            result: dict[str, Any] = {}
            for _attempt in range(12):
                result = generate(run_dir)
                if result.get("status") != "awaiting_hermes": break
                revision_dir = run_dir / "revisions" / str(result["revision_id"])
                for relative in result.get("requests", []):
                    request_path = revision_dir / relative
                    if "verification-requests" in relative:
                        if verification_responder is not None:
                            _save_verification_response(revision_dir, request_path, verification_responder)
                    else:
                        _save_recorded_handoff(revision_dir, request_path)
                if result.get("stage") == "independent_verification" and verification_responder is None:
                    break
            results.append({"case": run_dir.name, "corpus": case, "icf_template": get_path(reference, "meta.icf_template"), "source_sha256": sha256_value(_approved_payload(reference)), "status": "passed" if result.get("status") == "passed" else "failed", "result": result})
    passed = all(item["status"] == "passed" for item in results)
    awaiting = any(item.get("result", {}).get("status") == "awaiting_hermes" for item in results)
    synthetic_verification = bool(verification_responder is not None and getattr(verification_responder, "synthetic", False))
    recorded_drafting = True
    status = "structural_passed" if passed and recorded_drafting else "passed" if passed else "awaiting_hermes" if awaiting else "blocked"
    assurance = "synthetic-structural-only" if synthetic_verification else "recorded-drafting-structural-only"
    report = {"status": status, "assurance": assurance, "recorded_drafting": recorded_drafting, "cases": results, "distinct_source_count": len({item.get("source_sha256") for item in results}), "visual_evidence": "external image inspection required; no automated visual approval is fabricated", "evidence_root": root.as_posix()}
    _write(root / "release-gate-report.json", report); return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--run-dir"); parser.add_argument("--stage", choices=("prepare", "approve", "validate", "generate")); parser.add_argument("--approved-by", default="client"); parser.add_argument("--source-md"); parser.add_argument("--release-gate", action="store_true"); parser.add_argument("--release-gate-root")
    args = parser.parse_args(argv)
    if args.release_gate: result = run_release_gate(SCRIPT_DIR.parent, evidence_root=Path(args.release_gate_root) if args.release_gate_root else None)
    else:
        if not args.run_dir or not args.stage: parser.error("--run-dir and --stage are required unless --release-gate is used")
        run_dir = Path(args.run_dir).expanduser().resolve()
        result = {"prepare": prepare, "approve": approve, "validate": validate, "generate": generate}[args.stage](run_dir, approved_by=args.approved_by, source_md=Path(args.source_md).expanduser() if args.source_md else None)
    print(json.dumps(result, indent=2, ensure_ascii=False)); return 0 if result.get("status") in {"passed", "awaiting_approval", "awaiting_hermes"} else 1


__all__ = ["approve", "generate", "prepare", "run_release_gate", "validate"]


if __name__ == "__main__": raise SystemExit(main())
