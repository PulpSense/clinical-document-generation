"""Hermes drafting handoff, response validation, merging, and retries.

Production code in this module never writes clinical prose and never calls a
model. It writes scoped request JSON and consumes response JSON supplied by
the Hermes orchestration in ``SKILL.md``. ``RecordedHandoff`` is an
acceptance-test adapter, not a production drafting path.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from contracts import (
    BOILERPLATE_VERSION,
    CONTRACT_VERSION,
    FORBIDDEN_DRAFT_LANGUAGE,
    SAFETY_ROLE_RESPONSIBILITY_CONCEPTS,
    BatchSpec,
    SectionSpec,
    batch_plan,
    canonical_study_type,
    contracted_template_bundle,
    get_path,
    icf_contract,
    meaningful,
    protocol_contract,
    source_evidence_coverage_map,
)


REQUEST_SCHEMA = "hermes-request/v2"
RESPONSE_SCHEMA = "hermes-response/v2"
TOPOLOGY_VERSION = "clinical-drafting-v1"
PROMPT_VERSION = "section-drafting-v11-source-constrained-boilerplate"
MAX_ATTEMPTS = 3
PLACEHOLDER = re.compile(r"\{[#/^]?[A-Za-z_][A-Za-z0-9_.\-\[\]()&]*\}")
IMPLEMENTATION_FILES = ("contracts.py", "drafting.py", "prs_xml.py", "quality.py", "rendering.py", "workflow.py")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def request_sha256(request: Mapping[str, Any]) -> str:
    unsigned = copy.deepcopy(dict(request))
    unsigned.pop("request_sha256", None)
    return sha256_value(unsigned)


def request_hash_valid(request: Mapping[str, Any]) -> bool:
    supplied = str(request.get("request_sha256") or "")
    return bool(supplied) and supplied == request_sha256(request)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _request_ledger_path(revision_dir: Path, request_id: str) -> Path:
    # Hermes may write requests/responses, but it must not be able to rewrite
    # the producer-owned trust record used to authenticate those requests.
    return revision_dir / "request-ledger" / f"{request_id}.json"


def _request_constraints() -> list[str]:
    return [
        "The Source-of-Truth is approved and source intake is closed. Do not request additional reviewer input.",
        "Use only supplied approved evidence and listed Fixed Clinical Boilerplate.",
        "Listed Fixed Clinical Boilerplate is authorized only where applicable and consistent with the approved source. The approved source supersedes boilerplate; boilerplate must not expand decision-making authority, termination grounds, completion criteria, procedures, or safety obligations.",
        "When a section lists both Fixed Clinical Boilerplate and minimum evidence, include all material source facts and only applicable, nonconflicting boilerplate; omit boilerplate clauses that would alter a source rule.",
        "Do not invent study-specific facts, procedures, risks, benefits, safety obligations, legal promises, or regulatory claims.",
        "Return exactly one result for every requested section ID.",
        "Use only the drafted or fixed_boilerplate outcome. Sparse sections may use only applicable, source-consistent listed Fixed Clinical Boilerplate.",
        "Return structured section content, not a whole document or document markup.",
        "Write separately contracted sections independently; do not repeat an exact sentence or paragraph, including any exact list item, across target sections unless the listed Fixed Clinical Boilerplate explicitly requires it. When contracts cover overlapping facts, express each section's distinct purpose without copying schedule prose verbatim.",
        "Use participant-facing language for ICF sections.",
        "Satisfy every section's content_expectations and cover every material value named by minimum_evidence.",
        "Use reference_detail_target_words only as a soft compression signal; semantic source coverage governs acceptance, and concise complete prose must not be padded, repeated, or invented to meet a length target.",
        "Explicitly distinguish the study objective, hypothesis, and endpoints when they describe different constructs.",
        "When the approved source does not define an instrument, scoring rule, denominator, missing-data method, date, or version, do not invent one or expose an internal source-gap note.",
        "Do not use an evidence reference unless the returned prose or list actually contains the material fact it supports.",
        "Every paragraph object and every list object must include at least one evidence_refs or boilerplate_refs value allowed by its section contract. If prose only introduces an already-cited list, omit that paragraph instead of returning empty reference arrays.",
    ]


def _prs_section_payload(target: str) -> dict[str, Any]:
    contracts = {
        "prs.brief-summary": {
            "minimum_evidence": ["study.title", "study.hypothesis", "objectives.primary", "endpoints.primary", "design.study_design"],
            "content_expectations": ["Give a concise public summary of the study purpose, hypothesis, primary endpoint, and design using all material approved facts."],
        },
        "prs.detailed-description": {
            "minimum_evidence": [
                "study.background", "study.hypothesis", "objectives.primary", "design.study_design",
                "endpoints.primary", "endpoints.secondary", "population.study_population", "procedures.assessments",
            ],
            "content_expectations": ["Explain the approved background, hypothesis, objectives, design, population, procedures, and every endpoint in registry-ready prose."],
        },
    }
    contract = contracts[target]
    return {
        "section_id": target,
        "required": True,
        "allowed_modes": ["agent_draft"],
        "minimum_evidence": contract["minimum_evidence"],
        "fixed_boilerplate": [],
        "content_expectations": contract["content_expectations"],
        "source_coverage": "all_material_items" if target == "prs.detailed-description" else "all_material_evidence",
    }


def _expected_section_contracts(
    repo_root: Path,
    reference: Mapping[str, Any],
    batch: BatchSpec,
    targets: Iterable[str],
    *,
    contracted_bundle: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    target_list = list(targets)
    if batch.artifact == "prs":
        allowed = {"prs.brief-summary", "prs.detailed-description"}
        if not target_list or not set(target_list) <= allowed:
            raise ValueError("PRS narrative requests may target only brief and detailed descriptions.")
        return [_prs_section_payload(target) for target in target_list]
    branch = canonical_study_type(get_path(reference, "meta.study_type")) or ""
    known = (
        {section.section_id: section for section in protocol_contract(branch)}
        if batch.artifact == "protocol"
        else {section.section_id: section for section in icf_contract(branch, str(get_path(reference, "meta.icf_template", "Advarra")))}
    )
    unknown = sorted(set(target_list) - set(known))
    if unknown:
        raise ValueError(f"Draft request contains unknown section IDs: {', '.join(unknown)}")
    boilerplate = load_boilerplate(repo_root, reference, contracted_bundle=contracted_bundle)
    return [_section_payload(known[target], boilerplate, reference) for target in target_list]


def _request_matches_approved_reference(
    revision_dir: Path,
    request: Mapping[str, Any],
    expected_governing: Mapping[str, Any] | None = None,
) -> bool:
    """Reconstruct every source-bearing request field from the immutable approval snapshot."""
    snapshot_path = revision_dir / "approved-reference.json"
    if not snapshot_path.is_file():
        return False
    try:
        repo_root = Path(__file__).resolve().parents[1]
        reference = _read_json(snapshot_path)
        branch = canonical_study_type(get_path(reference, "meta.study_type")) or ""
        icf_template = get_path(reference, "meta.icf_template")
        plan = batch_plan(branch, str(icf_template or "Advarra"))
        batch = next(item for item in plan if item.batch_id == request.get("batch_id"))
        contracts = request.get("section_contracts")
        if not isinstance(contracts, list):
            return False
        targets = [str(item.get("section_id")) for item in contracts if isinstance(item, Mapping)]
        attempts = request.get("attempts")
        if not targets or not isinstance(attempts, Mapping) or set(map(str, attempts)) != set(targets):
            return False
        if expected_governing is None:
            bundle = contracted_template_bundle(repo_root, reference)
            expected_governing = governing_resources(repo_root, reference, contracted_bundle=bundle)
        else:
            bundle = expected_governing.get("contracted_template_bundle")
            if not isinstance(bundle, Mapping):
                return False
        scoped = _scoped_source(reference, batch.field_families)
        expected_contracts = _expected_section_contracts(
            repo_root,
            reference,
            batch,
            targets,
            contracted_bundle=bundle,
        )
        expected_task = "prs_narrative_drafting" if batch.artifact == "prs" else "section_drafting"
        request_id = str(request.get("request_id") or "")
        wave = str(request.get("wave") or "")
        normalized_attempts = {target: int(attempts[target]) for target in targets}
        expected_request_id = _request_id(
            str(request.get("revision_id") or ""),
            batch.batch_id,
            normalized_attempts,
            wave,
            sha256_value(expected_governing),
        )
        return all((
            request.get("schema_version") == REQUEST_SCHEMA,
            request_id == expected_request_id,
            request.get("task") == expected_task,
            request.get("artifact") == batch.artifact,
            request.get("branch") == {"study_type": branch, "icf_template": icf_template},
            request.get("topology_version") == TOPOLOGY_VERSION,
            request.get("prompt_version") == PROMPT_VERSION,
            request.get("governing_resources") == expected_governing,
            request.get("approved_source") == scoped,
            request.get("approved_input") == _source_items(scoped),
            contracts == expected_contracts,
            request.get("constraints") == _request_constraints(),
            request.get("response_path") == f"hermes/responses/{request_id}.json",
            set(targets) <= set(batch.section_ids),
            all(1 <= attempt <= MAX_ATTEMPTS for attempt in normalized_attempts.values()),
        ))
    except (OSError, ValueError, KeyError, StopIteration, TypeError, json.JSONDecodeError):
        return False


def _trusted_request_valid(
    revision_dir: Path,
    request: Mapping[str, Any],
    expected_governing: Mapping[str, Any] | None = None,
) -> bool:
    request_id = str(request.get("request_id") or "")
    record_path = _request_ledger_path(revision_dir, request_id)
    if not request_id or not record_path.is_file():
        return False
    try:
        record = _read_json(record_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return (
        record.get("request_id") == request_id
        and record.get("request_sha256") == request.get("request_sha256")
        and record.get("request_sha256") == request_sha256(request)
        and _request_matches_approved_reference(revision_dir, request, expected_governing)
    )


def load_boilerplate(
    repo_root: Path,
    reference: Mapping[str, Any],
    *,
    contracted_bundle: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    bundle = contracted_bundle or contracted_template_bundle(repo_root, reference)
    payload = _read_json(repo_root / str(bundle["fixed_clinical_boilerplate"]["path"]))
    if payload.get("version") != BOILERPLATE_VERSION:
        raise ValueError("Fixed Clinical Boilerplate version does not match the contract.")
    sections = payload.get("sections")
    if not isinstance(sections, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in sections.items()):
        raise ValueError("Fixed Clinical Boilerplate must contain a string map named sections.")
    return dict(sections)


def governing_resources(
    repo_root: Path,
    reference: Mapping[str, Any],
    *,
    contracted_bundle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    bundle = dict(contracted_bundle or contracted_template_bundle(repo_root, reference))
    implementation = [repo_root / "scripts" / name for name in IMPLEMENTATION_FILES]
    return {
        "approved_source_sha256": get_path(reference, "approval.source_sha256"),
        "source_evidence_coverage_map": source_evidence_coverage_map(reference),
        "contracted_template_bundle": bundle,
        "implementation_sha256": {path.relative_to(repo_root).as_posix(): sha256_file(path) for path in implementation},
        "topology_version": TOPOLOGY_VERSION,
        "prompt_version": PROMPT_VERSION,
        "producer_policy": "nonempty-model-id",
    }


def _scoped_source(reference: Mapping[str, Any], families: Iterable[str]) -> dict[str, Any]:
    return {family: copy.deepcopy(reference[family]) for family in families if family in reference}


def _source_items(value: Any, prefix: str = "") -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(child, Mapping):
                items.extend(_source_items(child, path))
            else:
                items.append({"path": path, "value": child, "sha256": sha256_value(child)})
    return items


_SOURCE_DETAIL_RATIOS = {
    "introduction": 0.70,
    "subjects.inclusion": 0.75,
    "subjects.exclusion": 0.75,
    "study-design.design": 0.65,
    "study-procedure.visits": 0.65,
    "study-procedure.measurements": 0.60,
    "analysis-plan.datasets": 0.65,
    "analysis-plan.methodology": 0.65,
    "sample-size": 0.60,
    "confidentiality": 0.65,
    "financial-injury": 0.65,
    "risks-benefits.risks": 0.70,
    "risks-benefits.benefits": 0.70,
}


def _source_detail_budget(reference: Mapping[str, Any], section: SectionSpec) -> tuple[int, int]:
    """Measure unique approved detail and set a floor only for source-rich sections."""
    seen: set[str] = set()
    words = 0
    for path in section.evidence:
        for leaf in _leaf_texts(get_path(reference, path)):
            normalized = re.sub(r"\s+", " ", leaf).strip().casefold()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            words += len(re.findall(r"\b[\w'-]+\b", leaf))
    ratio = _SOURCE_DETAIL_RATIOS.get(section.section_id, 0.0)
    return words, int(words * ratio) if ratio and words >= 80 else 0


def _focused_evidence_value(value: Any, focus_terms: Iterable[str]) -> str:
    """Return the source-owned clause fragment relevant to one narrow section."""
    terms = tuple(term.casefold() for term in focus_terms)
    excerpts = []
    leading_verbs = {
        "analyze", "assess", "compare", "describe", "evaluate", "monitor",
        "report", "review", "summarize", "tabulate",
    }
    for leaf in _leaf_texts(value):
        for clause in re.split(r"(?<=[.!?])\s+|(?<=;)\s+", leaf):
            lowered = clause.casefold()
            matches = [lowered.find(term) for term in terms if term in lowered]
            if not matches:
                continue
            start = min(matches)
            prefix = clause[:start]
            negation = re.search(r"\b(?:no|not|without)\b(?:\s+[A-Za-z-]+){0,3}\s*$", prefix, re.I)
            if negation:
                excerpt = clause[negation.start():].strip()
            else:
                excerpt = clause[start:].strip()
                first_word = re.match(r"[A-Za-z]+", clause)
                if first_word and first_word.group(0).casefold() in leading_verbs:
                    excerpt = f"{first_word.group(0)} {excerpt}"
            excerpts.append(excerpt)
    return " ".join(dict.fromkeys(excerpts))


def _section_payload(
    section: SectionSpec,
    boilerplate: Mapping[str, str],
    reference: Mapping[str, Any],
) -> dict[str, Any]:
    allowed = ["agent_draft"]
    boilerplate_items: list[dict[str, str]] = []
    if section.boilerplate_key:
        allowed.append("fixed_boilerplate")
        text = boilerplate.get(section.boilerplate_key)
        if not text:
            raise ValueError(f"Missing Fixed Clinical Boilerplate: {section.boilerplate_key}")
        boilerplate_items.append({"boilerplate_id": section.boilerplate_key, "text": text, "sha256": sha256_value(text)})
    approved_source_words, minimum_detail_words = _source_detail_budget(reference, section)
    evidence_scopes = []
    for path, focus_terms in section.evidence_scopes:
        value = get_path(reference, path)
        scoped_value = _focused_evidence_value(value, focus_terms)
        evidence_scopes.append({
            "path": path,
            "focus_terms": list(focus_terms),
            "value": scoped_value,
            "sha256": sha256_value(scoped_value),
        })
    scoped_values = {
        item["path"]: item["value"]
        for item in evidence_scopes
    }
    minimum_evidence = [
        path for path in section.evidence
        if path not in scoped_values or scoped_values[path]
    ]
    return {
        "section_id": section.section_id,
        "number": section.number,
        "title": section.title,
        "role": section.role,
        "required": section.required,
        "allowed_modes": allowed,
        "minimum_evidence": minimum_evidence,
        "fixed_boilerplate": boilerplate_items,
        "content_expectations": list(section.content_expectations),
        "source_coverage": section.source_coverage,
        "evidence_scopes": evidence_scopes,
        "approved_source_word_count": approved_source_words,
        "reference_detail_target_words": minimum_detail_words,
    }


def _request_id(revision_id: str, batch_id: str, attempts: Mapping[str, int], wave: str, governing_sha256: str = "") -> str:
    attempt = max(attempts.values(), default=1)
    target_key = sha256_value({"targets": sorted(attempts), "governing": governing_sha256})[:8]
    return f"{revision_id}.draft.{batch_id}.{wave}.a{attempt}.{target_key}"


def accepted_draft(revision_dir: Path, section_id: str, expected_governing: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    path = revision_dir / "hermes/accepted" / f"{section_id.replace('/', '_')}.json"
    if not path.is_file():
        return None
    draft = _read_json(path)
    if expected_governing is not None and draft.get("governing_resources") != dict(expected_governing):
        return None
    request_id = str(draft.get("request_id") or "")
    accepted_request_path = revision_dir / "hermes/accepted-requests" / f"{request_id}.json"
    if not request_id or not accepted_request_path.is_file():
        return None
    accepted_request = _read_json(accepted_request_path)
    if not _trusted_request_valid(revision_dir, accepted_request, expected_governing) or draft.get("request_sha256") != accepted_request.get("request_sha256"):
        return None
    if expected_governing is not None and accepted_request.get("governing_resources") != dict(expected_governing):
        return None
    return draft


def accepted_prs_record(revision_dir: Path, expected_governing: Mapping[str, Any] | None = None) -> dict[str, Any]:
    path = revision_dir / "hermes/accepted/prs-narrative.json"
    if not path.is_file():
        return {}
    accepted = _read_json(path)
    if expected_governing is not None and accepted.get("governing_resources") != dict(expected_governing):
        return {}
    request_id = str(accepted.get("request_id") or "")
    request_path = revision_dir / "hermes/accepted-requests" / f"{request_id}.json"
    if not request_id or not request_path.is_file():
        return {}
    request = _read_json(request_path)
    if not _trusted_request_valid(revision_dir, request, expected_governing) or accepted.get("request_sha256") != request.get("request_sha256"):
        return {}
    return accepted


def accepted_context(revision_dir: Path, batch: BatchSpec, expected_governing: Mapping[str, Any]) -> list[dict[str, Any]]:
    if batch.batch_id != "prs-narrative":
        return []
    foundations = next((item for item in batch_plan("Prospective") if item.batch_id == "protocol-foundations"), None)
    return [draft for section_id in (foundations.section_ids if foundations else ()) if (draft := accepted_draft(revision_dir, section_id, expected_governing))]


def create_drafting_request(
    *,
    repo_root: Path,
    revision_dir: Path,
    revision_id: str,
    reference: Mapping[str, Any],
    batch: BatchSpec,
    target_ids: Iterable[str] | None = None,
    attempts: Mapping[str, int],
    wave: str,
    findings: Iterable[Mapping[str, Any]] = (),
    contracted_bundle: Mapping[str, Any] | None = None,
) -> Path:
    snapshot_path = revision_dir / "approved-reference.json"
    if not snapshot_path.is_file():
        _write_json(snapshot_path, reference)
    elif _read_json(snapshot_path) != dict(reference):
        raise ValueError("Drafting reference does not match the immutable approved-reference snapshot.")
    branch = canonical_study_type(get_path(reference, "meta.study_type")) or ""
    targets = tuple(target_ids or batch.section_ids)
    bundle = dict(contracted_bundle or contracted_template_bundle(repo_root, reference))
    sections = _expected_section_contracts(
        repo_root,
        reference,
        batch,
        targets,
        contracted_bundle=bundle,
    )
    scoped = _scoped_source(reference, batch.field_families)
    governing = governing_resources(repo_root, reference, contracted_bundle=bundle)
    request_id = _request_id(revision_id, batch.batch_id, attempts, wave, sha256_value(governing))
    response_path = revision_dir / "hermes/responses" / f"{request_id}.json"
    payload: dict[str, Any] = {
        "schema_version": REQUEST_SCHEMA,
        "request_id": request_id,
        "revision_id": revision_id,
        "task": "section_drafting" if batch.artifact != "prs" else "prs_narrative_drafting",
        "wave": wave,
        "batch_id": batch.batch_id,
        "artifact": batch.artifact,
        "branch": {"study_type": branch, "icf_template": get_path(reference, "meta.icf_template")},
        "topology_version": TOPOLOGY_VERSION,
        "prompt_version": PROMPT_VERSION,
        "governing_resources": governing,
        "attempts": {target: int(attempts[target]) for target in targets},
        "approved_input": _source_items(scoped),
        "approved_source": scoped,
        "source_evidence_coverage_map": source_evidence_coverage_map(reference),
        "evidence_checklist": [
            {
                "section_id": str(section.get("section_id") or ""),
                "required_source_paths": list(section.get("minimum_evidence") or []),
                "approved_values": {
                    str(path): get_path(reference, str(path))
                    for path in section.get("minimum_evidence") or []
                },
            }
            for section in sections
        ],
        "section_contracts": sections,
        "accepted_context": accepted_context(revision_dir, batch, governing),
        "prior_target_drafts": [draft for target in targets if (draft := accepted_draft(revision_dir, target, governing))],
        "findings": [dict(item) for item in findings],
        "constraints": _request_constraints(),
        "response_path": response_path.relative_to(revision_dir).as_posix(),
    }
    payload["request_sha256"] = request_sha256(payload)
    request_path = revision_dir / "hermes/requests" / f"{request_id}.json"
    ledger_path = _request_ledger_path(revision_dir, request_id)
    if ledger_path.is_file():
        recorded = _read_json(ledger_path)
        if recorded.get("request_sha256") != payload["request_sha256"]:
            raise ValueError(f"Draft request identity collision: {request_id}")
    response_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(request_path, payload)
    _write_json(ledger_path, {"request_id": request_id, "request_sha256": payload["request_sha256"]})
    return request_path


def _response_path(revision_dir: Path, request: Mapping[str, Any]) -> Path:
    return revision_dir / str(request["response_path"])


def _request_metadata_current(request: Mapping[str, Any], expected_governing: Mapping[str, Any] | None = None) -> bool:
    if request.get("schema_version") != REQUEST_SCHEMA or request.get("prompt_version") != PROMPT_VERSION:
        return False
    return expected_governing is None or request.get("governing_resources") == dict(expected_governing)


def _current_request(revision_dir: Path, request: Mapping[str, Any], expected_governing: Mapping[str, Any] | None = None) -> bool:
    return _request_metadata_current(request, expected_governing) and _trusted_request_valid(revision_dir, request)


def pending_requests(revision_dir: Path, expected_governing: Mapping[str, Any] | None = None) -> list[Path]:
    result = []
    for path in sorted((revision_dir / "hermes/requests").glob("*.json")):
        request = _read_json(path)
        if not _current_request(revision_dir, request, expected_governing):
            continue
        if not _response_path(revision_dir, request).is_file() and not (revision_dir / "hermes/accepted-requests" / path.name).is_file():
            result.append(path)
    return result


def _allowed_evidence(request: Mapping[str, Any]) -> set[str]:
    return {f"source:{item.get('path')}" for item in request.get("approved_input", []) if isinstance(item, Mapping)}


_GROUNDING_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "is", "it",
    "of", "on", "or", "that", "the", "their", "this", "to", "was", "were", "will", "with",
    "approved", "clinical", "evaluation", "participant", "participants", "prospective", "research",
    "retrospective", "study", "subject", "subjects",
}

_GROUNDING_TOKEN_EQUIVALENTS = {
    # A source may name the clinical state while client-facing prose describes
    # the person who has it. Keep these equivalences explicit and narrow so
    # all other clinical concepts and every numeric value remain observable.
    "pregnancy": "pregnancy",
    "pregnant": "pregnancy",
}

_NON_SUBSTANTIVE_LIST_ITEMS = {
    "n/a", "na", "no", "none", "not applicable", "other", "same", "unknown", "yes",
}


def _leaf_texts(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return [text for child in value.values() for text in _leaf_texts(child)]
    if isinstance(value, list):
        return [text for child in value for text in _leaf_texts(child)]
    text = str(value or "").strip()
    return [text] if text else []


def _grounding_tokens(value: str) -> set[str]:
    return {
        _GROUNDING_TOKEN_EQUIVALENTS.get(token.rstrip("s"), token.rstrip("s"))
        for token in re.findall(r"[A-Za-z0-9]+", value.casefold())
        if (len(token) > 1 or token.isdigit()) and token not in _GROUNDING_STOPWORDS
    }


def _substantive_list_item(value: str) -> bool:
    """Accept concise clinical terms while continuing to reject non-content."""
    text = re.sub(r"\s+", " ", value).strip()
    lowered = text.casefold().strip(" .,:;!?()[]{}")
    if (
        not text
        or PLACEHOLDER.search(text)
        or lowered in _NON_SUBSTANTIVE_LIST_ITEMS
        or any(token in lowered for token in FORBIDDEN_DRAFT_LANGUAGE)
    ):
        return False
    return bool(_grounding_tokens(text))


def _party_words(value: str) -> list[str]:
    return re.findall(r"[^\W_]+|\d+", unicodedata.normalize("NFC", value).casefold())


_SAFETY_RESPONSIBILITY_ACTION_TOKENS = {
    "assess_safety_events": {
        "asse", "assess", "assesse", "assessed", "assessing", "assessment",
        "evaluate", "evaluated", "evaluating", "evaluation",
        "investigate", "investigated", "investigating", "investigation",
        "monitor", "monitored", "monitoring", "review", "reviewed", "reviewing",
    },
    "report_safety_events": {
        "communicate", "communicated", "communicating", "communication",
        "document", "documented", "documenting", "documentation",
        "escalate", "escalated", "escalating", "escalation",
        "notify", "notified", "notifying", "notification",
        "report", "reported", "reporting", "submit", "submitted", "submitting", "submission",
    },
}
_SAFETY_DIRECT_ACTION_TOKENS = {
    "assess_safety_events": {
        "asse", "assess", "assesse", "assessed",
        "evaluate", "evaluated",
        "investigate", "investigated",
        "monitor", "monitored",
        "review", "reviewed",
    },
    "report_safety_events": {
        "communicate", "communicated",
        "document", "documented",
        "escalate", "escalated",
        "notify", "notified",
        "report", "reported",
        "submit", "submitted",
    },
}
_SAFETY_NEGATION_TOKENS = {"no", "not", "never", "neither", "nor", "without"}
_SAFETY_EVENT_OBJECT_TOKENS = {"ae", "complaint", "event", "incident", "sae"}
_SAFETY_OBJECT_MODIFIERS = {
    "adverse", "all", "any", "approved", "clinical", "device", "potential",
    "quality", "related", "safety", "serious", "study", "such", "suspected", "the", "these", "those",
}
_SAFETY_TRAILING_ADVERBS = {"directly", "independently", "promptly"}
_SAFETY_DESCRIPTIVE_REVIEW_OBJECTS = {"chart", "data", "document", "record"}


def _structured_safety_role_records(value: Any) -> list[tuple[str, set[str], set[str]]]:
    """Return exact party labels/tokens and controlled responsibilities."""
    if not isinstance(value, list):
        return []
    records: list[tuple[str, set[str], set[str]]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        party = unicodedata.normalize("NFC", str(item.get("party") or "").strip())
        party_tokens = set(_party_words(party))
        responsibilities = {
            part.strip()
            for part in str(item.get("responsibilities") or "").split(";")
            if part.strip() in SAFETY_ROLE_RESPONSIBILITY_CONCEPTS
        }
        if party_tokens and responsibilities:
            records.append((party, party_tokens, responsibilities))
    return records


def _structured_safety_role_prose(value: Any) -> str:
    """Render governed safety responsibilities as one party-bound sentence per record."""
    sentences = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, Mapping):
            continue
        party = str(item.get("party") or "").strip()
        concepts = {
            part.strip()
            for part in str(item.get("responsibilities") or "").split(";")
        }
        actions = []
        if "assess_safety_events" in concepts:
            actions.append("assesses safety events")
        if "report_safety_events" in concepts:
            actions.append("reports safety events")
        if party and actions:
            subject = party if party.casefold().startswith("the ") else f"The {party}"
            sentences.append(f"{subject} {' and '.join(actions)}.")
    return " ".join(sentences)


def _maximal_approved_party_spans(
    text: str,
    role_records: list[tuple[str, set[str], set[str]]],
) -> list[tuple[str, int, int]]:
    """Resolve exact party mentions longest-first so overlapping labels stay distinct."""
    text = unicodedata.normalize("NFC", text)
    folded_parts: list[str] = []
    folded_offsets: list[int] = []
    for index, character in enumerate(text):
        folded = character.casefold()
        folded_parts.append(folded)
        folded_offsets.extend([index] * len(folded))
    folded_text = "".join(folded_parts)
    candidates: list[tuple[str, int, int]] = []
    for party, _party_tokens, _responsibilities in role_records:
        folded_party = unicodedata.normalize("NFC", party).casefold().strip()
        if folded_party.startswith("the "):
            folded_party = folded_party[4:].lstrip()
        parts = folded_party.split()
        if not parts:
            continue
        source = r"\s+".join(map(re.escape, parts))
        for match in re.finditer(
            rf"(?<!\w)(?:the\s+)?{source}(?!\w)",
            folded_text,
        ):
            candidates.append((
                party,
                folded_offsets[match.start()],
                folded_offsets[match.end() - 1] + 1,
            ))
    selected: list[tuple[str, int, int]] = []
    for candidate in sorted(candidates, key=lambda item: (-(item[2] - item[1]), item[1], item[0].casefold())):
        if any(candidate[1] < end and start < candidate[2] for _party, start, end in selected):
            continue
        selected.append(candidate)
    return sorted(selected, key=lambda item: item[1])


def _is_descriptive_safety_clause(
    tokens: list[str],
    approved_risk_tokens: list[str],
) -> bool:
    """Accept only complete actor-free boundary, risk, and record-review shapes."""
    exact_descriptions = {
        ("safety", "event", "chart", "review", "wa", "completed"),
        ("safety", "data", "are", "provided", "by", "the", "chart", "review"),
    }
    if tuple(tokens) in exact_descriptions:
        return True
    risk_prefixes = (
        ["for", "quality", "complaint", "and", "adverse", "event", "the", "approved", "risk", "i"],
        ["for", "quality", "complaint", "and", "adverse", "event", "approved", "risk", "include"],
    )
    if approved_risk_tokens and any(
        tokens == [*prefix, *approved_risk_tokens] for prefix in risk_prefixes
    ):
        return True
    review_tokens = tokens[1:] if tokens[:1] == ["the"] else tokens
    if (
        len(review_tokens) >= 5
        and review_tokens[0] in _SAFETY_DESCRIPTIVE_REVIEW_OBJECTS
        and review_tokens[1] == "review"
        and review_tokens[2] in {"contained", "identified", "included", "summarized"}
        and review_tokens[3] in {"adverse", "approved", "quality", "safety", "serious"}
        and review_tokens[4] in _SAFETY_EVENT_OBJECT_TOKENS
        and len(review_tokens) == 5
    ):
        return True
    retrospective_tokens = tokens[1:] if tokens[:1] in (["available"], ["historical"], ["retrospective"]) else tokens
    if (
        len(retrospective_tokens) == 8
        and retrospective_tokens[0] == "safety"
        and retrospective_tokens[1] in {"data", "event", "information"}
        and retrospective_tokens[2] in {"wa", "were"}
        and retrospective_tokens[3] in {"abstracted", "included", "summarized"}
        and retrospective_tokens[4] in {"from", "in"}
        and retrospective_tokens[5] == "the"
        and retrospective_tokens[6] in _SAFETY_DESCRIPTIVE_REVIEW_OBJECTS
        and retrospective_tokens[7] == "review"
    ):
        return True
    return False


def _direct_safety_role_errors(
    content: str,
    role_records: list[tuple[str, set[str], set[str]]],
    approved_risks: Any,
) -> list[str]:
    """Validate the governed one-party/direct-action/safety-object sentence grammar."""
    normalized_content = unicodedata.normalize("NFC", content)
    action_concepts = {
        token: concept
        for concept, tokens in _SAFETY_DIRECT_ACTION_TOKENS.items()
        for token in tokens
    }
    all_actions = set(action_concepts)
    responsibility_claim_tokens = set().union(
        *_SAFETY_RESPONSIBILITY_ACTION_TOKENS.values()
    )
    approved = {party.casefold(): responsibilities for party, _tokens, responsibilities in role_records}
    approved_risk_tokens = [
        token.rstrip("s")
        for leaf in _leaf_texts(approved_risks)
        for token in _party_words(leaf)
    ]
    seen: set[str] = set()
    errors: list[str] = []
    protected_content = list(normalized_content)
    for _party, start, end in _maximal_approved_party_spans(normalized_content, role_records):
        for index in range(start, end):
            if protected_content[index] == ".":
                protected_content[index] = "\u2024"
    for clause in re.split(r"[.!?;\n]+", "".join(protected_content)):
        clause = clause.replace("\u2024", ".")
        clause = clause.strip()
        if not clause:
            continue
        tokens = [word.rstrip("s") for word in _party_words(clause)]
        token_set = set(tokens)
        spans = _maximal_approved_party_spans(clause, role_records)
        has_event_object = bool(token_set & _SAFETY_EVENT_OBJECT_TOKENS)
        safety_context = has_event_object or "safety" in token_set
        approved_party_claim = bool(
            spans and token_set & responsibility_claim_tokens
        )
        if not (safety_context or approved_party_claim):
            continue
        if not spans and _is_descriptive_safety_clause(tokens, approved_risk_tokens):
            continue
        if len(spans) != 1 or clause[:spans[0][1]].strip():
            errors.append("unapproved-or-nondirect-party")
            continue
        party, _start, end = spans[0]
        predicate = [word.rstrip("s") for word in _party_words(clause[end:])]
        while predicate and predicate[-1] in _SAFETY_TRAILING_ADVERBS:
            predicate.pop()
        if not predicate or set(predicate) & _SAFETY_NEGATION_TOKENS:
            errors.append(f"{party}:invalid-direct-statement")
            continue
        concepts: set[str] = set()
        segments: list[list[str]] = [[]]
        for token in predicate:
            if token == "and":
                segments.append([])
            else:
                segments[-1].append(token)
        has_explicit_object = False
        previous_had_object = False
        valid_chain = bool(segments) and all(segments)
        for segment in segments:
            if not valid_chain:
                break
            concept = action_concepts.get(segment[0])
            if concept:
                concepts.add(concept)
                object_tokens = segment[1:]
            elif concepts and previous_had_object:
                object_tokens = segment
            else:
                valid_chain = False
                break
            event_count = sum(
                token in _SAFETY_EVENT_OBJECT_TOKENS for token in object_tokens
            )
            if (object_tokens and event_count != 1) or any(
                token not in (_SAFETY_EVENT_OBJECT_TOKENS | _SAFETY_OBJECT_MODIFIERS)
                for token in object_tokens
            ):
                valid_chain = False
                break
            previous_had_object = event_count == 1
            has_explicit_object = has_explicit_object or previous_had_object
        if not valid_chain or not has_explicit_object:
            errors.append(f"{party}:invalid-action-chain")
            continue
        party_key = party.casefold()
        if concepts != approved.get(party_key, set()):
            errors.append(f"{party}:responsibility-mismatch")
            continue
        seen.add(party_key)
    for party, _party_tokens, _responsibilities in role_records:
        if party.casefold() not in seen:
            errors.append(f"{party}:missing-direct-statement")
    return errors


def evidence_grounded(content: str, value: Any, *, all_items: bool = False) -> bool:
    """Require observable anchors for every material scalar supplied by a cited source path."""
    content_tokens = _grounding_tokens(content)
    def numeric_tokens(text: str) -> set[str]:
        values = set()
        for token in re.findall(r"\d+(?:\.\d+)?", text.casefold()):
            if "." in token:
                whole, fraction = token.split(".", 1)
                values.add(f"{int(whole)}.{fraction.rstrip('0') or '0'}")
            else:
                values.add(str(int(token)))
        return values

    content_numbers = numeric_tokens(content)
    leaves = _leaf_texts(value)
    if not leaves:
        return True
    negative_source_values = {"none", "no", "n/a", "na", "not applicable"}
    negative_content_tokens = {"no", "not", "none", "without", "neither"}
    if all(leaf.casefold().strip().rstrip(".") in negative_source_values for leaf in leaves):
        return bool(content_tokens & negative_content_tokens)
    def grounded(leaf: str) -> bool:
        expected = _grounding_tokens(leaf)
        if not expected:
            expected = {token.rstrip("s") for token in re.findall(r"[A-Za-z0-9]+", leaf.casefold()) if token}
        if not expected:
            return True
        numbers = numeric_tokens(leaf)
        if not numbers <= content_numbers:
            return False
        required = min(12, max(1, math.ceil(len(expected) * 0.45)))
        return len(expected & content_tokens) >= required

    if all_items:
        return all(grounded(leaf) for leaf in leaves)
    combined = " ".join(leaves)
    return grounded(combined)


def _material_source(request: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    source = {
        str(item.get("path")): item.get("value")
        for item in request.get("approved_input", [])
        if isinstance(item, Mapping)
    }
    scopes = {
        str(item.get("path")): item.get("value")
        for item in contract.get("evidence_scopes", [])
        if isinstance(item, Mapping)
    }
    material: dict[str, Any] = {}
    for path in map(str, contract.get("minimum_evidence", [])):
        value = scopes[path] if path in scopes else source.get(path)
        if _leaf_texts(value):
            material[path] = value
    return material


def _coverage_findings(
    request: Mapping[str, Any],
    contract: Mapping[str, Any],
    section_id: str,
    content: str,
    evidence_refs: Iterable[str],
    role_content: str | None = None,
) -> list[dict[str, Any]]:
    if contract.get("source_coverage") not in {"all_material_evidence", "all_material_items"}:
        return []
    material = _material_source(request, contract)
    cited = set(map(str, evidence_refs))
    missing = [path for path in material if f"source:{path}" not in cited]
    findings: list[dict[str, Any]] = []
    if missing:
        findings.append({
            "category": "drafting",
            "field": section_id,
            "issue": f"Section omits material approved evidence: {', '.join(missing)}.",
            "next_action": "Cover every material minimum_evidence value; do not replace supplied detail with generic prose.",
        })
    all_items = contract.get("source_coverage") == "all_material_items"
    ungrounded = [
        path
        for path, value in material.items()
        if f"source:{path}" in cited
        and not (section_id == "quality-safety" and path == "safety.roles")
        and not evidence_grounded(content, value, all_items=all_items)
    ]
    if ungrounded:
        findings.append({
            "category": "drafting",
            "field": section_id,
            "issue": f"Evidence references are present but their material facts are not observable in the section: {', '.join(ungrounded)}.",
            "next_action": "Revise the section so each cited source contributes its concrete names, values, time points, criteria, or clinical concepts.",
        })
    if section_id == "quality-safety" and "safety.roles" in material:
        role_records = _structured_safety_role_records(material["safety.roles"])
        if not role_records:
            findings.append({
                "category": "drafting",
                "field": section_id,
                "issue": "Approved safety roles are not structured party/responsibility records.",
                "next_action": "Return to Source Review and record every responsible party separately from its responsibilities.",
            })
        missing_assignments = _direct_safety_role_errors(
            content if role_content is None else role_content,
            role_records,
            material.get("risks_benefits.risks"),
        )
        if missing_assignments:
            findings.append({
                "category": "drafting",
                "field": section_id,
                "issue": (
                    "Section omits the approved safety role assignment: "
                    + ", ".join(missing_assignments)
                    + "."
                ),
                "next_action": "Name every approved party and state each assigned safety responsibility in that party's sentence.",
            })
    return findings


def _reference_next_action(
    request: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    content_type: str,
    position: int,
) -> str:
    allowed_request_evidence = _allowed_evidence(request)
    evidence_refs = sorted(
        f"source:{path}"
        for path in map(str, contract.get("minimum_evidence", []))
        if f"source:{path}" in allowed_request_evidence
    )
    boilerplate_refs = sorted(
        str(item.get("boilerplate_id"))
        for item in contract.get("fixed_boilerplate", [])
        if isinstance(item, Mapping) and item.get("boilerplate_id")
    )
    choices = []
    if evidence_refs:
        choices.append(f"evidence_refs=[{', '.join(evidence_refs)}]")
    if boilerplate_refs:
        choices.append(f"boilerplate_refs=[{', '.join(boilerplate_refs)}]")
    allowed = " or ".join(choices) or "an allowed section reference"
    suffix = (
        " If it only introduces an already-cited list, omit the paragraph."
        if content_type == "Paragraph"
        else ""
    )
    return f"{content_type} {position} must include at least one of {allowed}.{suffix}"


def _validate_paragraph(
    paragraph: Any,
    request: Mapping[str, Any],
    contract: Mapping[str, Any],
    section_id: str,
    position: int = 1,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    if not isinstance(paragraph, Mapping):
        return None, [{"category": "drafting", "field": section_id, "issue": "A paragraph result is not an object.", "next_action": "Return paragraphs with text and evidence_refs."}]
    text = str(paragraph.get("text") or "").strip()
    evidence_refs = paragraph.get("evidence_refs") if isinstance(paragraph.get("evidence_refs"), list) else []
    boilerplate_refs = paragraph.get("boilerplate_refs") if isinstance(paragraph.get("boilerplate_refs"), list) else []
    if len(text.split()) < 5:
        findings.append({"category": "drafting", "field": section_id, "issue": "Section prose is not substantive.", "next_action": "Return a complete source-grounded sentence."})
    lowered = text.casefold()
    if PLACEHOLDER.search(text) or any(token in lowered for token in FORBIDDEN_DRAFT_LANGUAGE):
        findings.append({"category": "drafting", "field": section_id, "issue": "Section contains a placeholder or internal drafting language.", "next_action": "Replace it with supported client-facing prose."})
    request_evidence = _allowed_evidence(request)
    section_evidence = {f"source:{path}" for path in contract.get("minimum_evidence", [])}
    invalid_evidence = sorted(set(map(str, evidence_refs)) - request_evidence)
    unrelated_evidence = sorted(set(map(str, evidence_refs)) - section_evidence) if evidence_refs else []
    allowed_boilerplate = {item["boilerplate_id"] for item in contract.get("fixed_boilerplate", []) if isinstance(item, Mapping)}
    invalid_boilerplate = sorted(set(map(str, boilerplate_refs)) - allowed_boilerplate)
    if invalid_evidence:
        findings.append({"category": "drafting", "field": section_id, "issue": f"Unsupported evidence references: {', '.join(invalid_evidence)}", "next_action": "Cite only evidence included in the request."})
    elif unrelated_evidence:
        findings.append({"category": "drafting", "field": section_id, "issue": f"Evidence is not approved for this section: {', '.join(unrelated_evidence)}", "next_action": "Cite the section's listed evidence or Fixed Clinical Boilerplate."})
    if invalid_boilerplate:
        findings.append({"category": "drafting", "field": section_id, "issue": f"Unsupported boilerplate references: {', '.join(invalid_boilerplate)}", "next_action": "Use only listed Fixed Clinical Boilerplate."})
    if not evidence_refs and not boilerplate_refs:
        findings.append({"category": "drafting", "field": section_id, "issue": "Paragraph has no approved evidence or boilerplate reference.", "next_action": _reference_next_action(request, contract, content_type="Paragraph", position=position)})
    return {"text": text, "evidence_refs": list(map(str, evidence_refs)), "boilerplate_refs": list(map(str, boilerplate_refs))}, findings


def _validate_list(
    group: Any,
    request: Mapping[str, Any],
    contract: Mapping[str, Any],
    section_id: str,
    position: int = 1,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not isinstance(group, Mapping):
        return None, [{"category": "drafting", "field": section_id, "issue": "A list result is not an object.", "next_action": "Return items with evidence_refs and boilerplate_refs."}]
    items = [str(item).strip() for item in group.get("items", []) if str(item).strip()] if isinstance(group.get("items"), list) else []
    evidence_refs = list(map(str, group.get("evidence_refs") or [])); boilerplate_refs = list(map(str, group.get("boilerplate_refs") or []))
    findings: list[dict[str, Any]] = []
    if not items or any(not _substantive_list_item(item) for item in items):
        findings.append({"category": "drafting", "field": section_id, "issue": "List items are empty, placeholders, or not substantive.", "next_action": "Return complete source-grounded list items."})
    section_evidence = {f"source:{path}" for path in contract.get("minimum_evidence", [])}
    invalid_evidence = sorted(set(evidence_refs) - _allowed_evidence(request)); unrelated = sorted(set(evidence_refs) - section_evidence)
    allowed_boilerplate = {item["boilerplate_id"] for item in contract.get("fixed_boilerplate", []) if isinstance(item, Mapping)}
    invalid_boilerplate = sorted(set(boilerplate_refs) - allowed_boilerplate)
    if invalid_evidence or unrelated: findings.append({"category": "drafting", "field": section_id, "issue": f"List uses unsupported section evidence: {', '.join(invalid_evidence or unrelated)}", "next_action": "Cite only listed section evidence."})
    if invalid_boilerplate: findings.append({"category": "drafting", "field": section_id, "issue": f"List uses unsupported boilerplate: {', '.join(invalid_boilerplate)}", "next_action": "Use only listed Fixed Clinical Boilerplate."})
    if not evidence_refs and not boilerplate_refs: findings.append({"category": "drafting", "field": section_id, "issue": "List has no approved evidence or boilerplate reference.", "next_action": _reference_next_action(request, contract, content_type="List", position=position)})
    return {"items": items, "evidence_refs": evidence_refs, "boilerplate_refs": boilerplate_refs}, findings


def _normalized_prose(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _raw_content_items(item: Mapping[str, Any]) -> list[tuple[str, list[str], list[str]]]:
    content: list[tuple[str, list[str], list[str]]] = []
    for paragraph in item.get("paragraphs") or []:
        if isinstance(paragraph, Mapping):
            content.append((
                str(paragraph.get("text") or ""),
                list(map(str, paragraph.get("evidence_refs") or [])),
                list(map(str, paragraph.get("boilerplate_refs") or [])),
            ))
    for group in item.get("lists") or []:
        if not isinstance(group, Mapping):
            continue
        evidence_refs = list(map(str, group.get("evidence_refs") or []))
        boilerplate_refs = list(map(str, group.get("boilerplate_refs") or []))
        for value in group.get("items") or []:
            content.append((str(value), evidence_refs, boilerplate_refs))
    return content


def _is_authorized_boilerplate_content(
    text: str,
    evidence_refs: list[str],
    boilerplate_refs: list[str],
    contract: Mapping[str, Any],
) -> bool:
    if evidence_refs or len(boilerplate_refs) != 1:
        return False
    boilerplate_ref = boilerplate_refs[0]
    return any(
        isinstance(block, Mapping)
        and str(block.get("boilerplate_id") or "") == boilerplate_ref
        and str(block.get("text") or "") == text
        and str(block.get("sha256") or "") == sha256_value(text)
        for block in contract.get("fixed_boilerplate") or []
    )


def _fixed_outcome_is_authorized(item: Mapping[str, Any], contract: Mapping[str, Any]) -> bool:
    if "fixed_boilerplate" not in contract.get("allowed_modes", []):
        return False
    fixed = [block for block in contract.get("fixed_boilerplate") or [] if isinstance(block, Mapping)]
    paragraphs = [paragraph for paragraph in item.get("paragraphs") or [] if isinstance(paragraph, Mapping)]
    if item.get("lists") or len(paragraphs) != len(fixed) or not fixed:
        return False
    return all(
        str(paragraph.get("text") or "") == str(block.get("text") or "")
        and str(block.get("sha256") or "") == sha256_value(paragraph.get("text"))
        and not (paragraph.get("evidence_refs") or [])
        and list(map(str, paragraph.get("boilerplate_refs") or [])) == [str(block.get("boilerplate_id") or "")]
        for paragraph, block in zip(paragraphs, fixed)
    )


def _cross_section_duplicate_pairs(
    records: Iterable[tuple[str, Mapping[str, Any], Mapping[str, Any]]],
) -> list[tuple[str, str]]:
    """Return section pairs that repeat non-boilerplate prose of eight words or more."""
    seen: dict[str, tuple[str, bool]] = {}
    duplicate_pairs: set[tuple[str, str]] = set()
    for section_id, item, contract in records:
        for text, evidence_refs, boilerplate_refs in _raw_content_items(item):
            key = _normalized_prose(text)
            if len(key.split()) < 8:
                continue
            authorized_boilerplate = _is_authorized_boilerplate_content(
                text,
                evidence_refs,
                boilerplate_refs,
                contract,
            )
            prior = seen.get(key)
            if prior is None:
                seen[key] = (section_id, authorized_boilerplate)
                continue
            prior_section, prior_boilerplate = prior
            if prior_section == section_id or (prior_boilerplate and authorized_boilerplate):
                continue
            duplicate_pairs.add(tuple(sorted((prior_section, section_id))))
    return sorted(duplicate_pairs)


def validate_response(request: Mapping[str, Any], response: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    for field in ("schema_version", "request_id", "request_sha256", "revision_id", "task", "batch_id"):
        expected = RESPONSE_SCHEMA if field == "schema_version" else request.get(field)
        if response.get(field) != expected:
            findings.append({"category": "drafting", "field": field, "issue": f"Response binding mismatch for {field}.", "next_action": "Return the exact request identifiers and schema."})
    producer = response.get("producer")
    if not isinstance(producer, Mapping) or not str(producer.get("model_id") or "").strip():
        findings.append({"category": "drafting", "field": "producer.model_id", "issue": "Response does not identify the producing model.", "next_action": "Record the actual model identity."})
    if findings:
        return None, findings
    if request.get("task") == "prs_narrative_drafting":
        narrative = response.get("narrative")
        section_ids = {"brief_summary": "prs.brief-summary", "detailed_description": "prs.detailed-description"}
        contracts = {str(item.get("section_id")): item for item in request.get("section_contracts", []) if isinstance(item, Mapping)}
        expected_keys = {key for key, section_id in section_ids.items() if section_id in contracts}
        if not isinstance(narrative, Mapping) or set(narrative) != expected_keys:
            findings.append({"category": "drafting", "field": "prs-narrative", "target_ids": sorted(contracts), "issue": f"PRS response must contain exactly the requested narrative values: {sorted(expected_keys)}.", "next_action": "Return only the requested narrative fields."})
            return None, findings
        clean: dict[str, Any] = {}
        for key, item in narrative.items():
            section_id = section_ids[key]
            section_finding_count = len(findings)
            if not isinstance(item, Mapping):
                findings.append({"category": "drafting", "field": section_id, "target_ids": [section_id], "issue": "PRS narrative item is not an object.", "next_action": "Return text and evidence_refs."})
                continue
            text = str(item.get("text") or "").strip()
            if re.search(r"</?[A-Za-z_][^>]*>", text) or len(text.split()) < 8:
                findings.append({"category": "drafting", "field": section_id, "target_ids": [section_id], "issue": "PRS narrative is empty, too short, or contains XML markup.", "next_action": "Return source-grounded prose only."})
            evidence_refs = list(map(str, item.get("evidence_refs") or []))
            contract = contracts.get(section_id, {})
            invalid = sorted(set(evidence_refs) - _allowed_evidence(request))
            target_evidence = {f"source:{path}" for path in contract.get("minimum_evidence", [])}
            unrelated = sorted(set(evidence_refs) - target_evidence)
            if invalid:
                findings.append({"category": "drafting", "field": section_id, "target_ids": [section_id], "issue": f"PRS narrative cites unsupported evidence: {', '.join(invalid)}", "next_action": "Cite only approved request evidence."})
            elif unrelated:
                findings.append({"category": "drafting", "field": section_id, "target_ids": [section_id], "issue": f"Evidence is not approved for this target: {', '.join(unrelated)}", "next_action": "Cite only the target's listed minimum_evidence."})
            elif not evidence_refs:
                findings.append({"category": "drafting", "field": section_id, "target_ids": [section_id], "issue": "PRS narrative lacks valid approved evidence references.", "next_action": "Cite the target's listed minimum_evidence."})
            findings.extend(_coverage_findings(request, contract, section_id, text, evidence_refs))
            for finding in findings[section_finding_count:]:
                finding["target_ids"] = [section_id]
            if len(findings) == section_finding_count:
                clean[key] = {
                    "text": text,
                    "evidence_refs": evidence_refs,
                    "producer": dict(producer),
                    "request_id": request.get("request_id"),
                    "request_sha256": request.get("request_sha256"),
                }
        accepted = {"kind": "prs", "narrative": clean, "producer": dict(producer), "governing_resources": dict(request.get("governing_resources", {})), "request_id": request.get("request_id"), "request_sha256": request.get("request_sha256")}
        return (accepted if clean else None), findings
    expected_contracts = {item["section_id"]: item for item in request.get("section_contracts", [])}
    results = response.get("section_results")
    if not isinstance(results, list):
        return None, findings + [{"category": "drafting", "field": request.get("batch_id"), "issue": "Response has no section_results list.", "next_action": "Return one result per requested section."}]
    result_ids = [str(item.get("section_id")) for item in results if isinstance(item, Mapping)]
    if len(result_ids) != len(set(result_ids)):
        findings.append({"category": "drafting", "field": request.get("batch_id"), "issue": "Response repeats a section ID.", "next_action": "Return each requested section exactly once."})
    missing = sorted(set(expected_contracts) - set(result_ids))
    unknown = sorted(set(result_ids) - set(expected_contracts))
    if missing or unknown:
        findings.append({"category": "drafting", "field": request.get("batch_id"), "issue": f"Section response mismatch; missing={missing}, unknown={unknown}.", "next_action": "Return exactly the requested section IDs."})
    for item in results:
        if not isinstance(item, Mapping) or str(item.get("section_id")) not in expected_contracts:
            continue
        section_id = str(item["section_id"])
        contract = expected_contracts[section_id]
        outcome = str(item.get("outcome") or "")
        if outcome == "drafted" and "agent_draft" not in contract.get("allowed_modes", []):
            findings.append({
                "category": "drafting",
                "field": section_id,
                "target_ids": [section_id],
                "issue": "The section contract does not authorize the drafted outcome.",
                "next_action": "Use only a mode explicitly authorized by the section contract.",
            })
        elif outcome == "fixed_boilerplate" and not _fixed_outcome_is_authorized(item, contract):
            findings.append({
                "category": "drafting",
                "field": section_id,
                "target_ids": [section_id],
                "issue": "The section contract does not authorize the fixed_boilerplate outcome or the returned content is not its exact authorized boilerplate.",
                "next_action": "Use the exact listed Fixed Clinical Boilerplate with its matching boilerplate reference, or return an authorized agent draft.",
            })
    has_blocking_contract_findings = bool(findings)
    duplicate_records = (
        (section_id, item, expected_contracts[section_id])
        for item in results
        if isinstance(item, Mapping)
        and (section_id := str(item.get("section_id") or "")) in expected_contracts
    )
    duplicate_target_ids: set[str] = set()
    for prior_section, section_id in _cross_section_duplicate_pairs(duplicate_records):
        duplicate_target_ids.update((prior_section, section_id))
        findings.append({
            "category": "drafting",
            "field": section_id,
            "target_ids": [prior_section, section_id],
            "issue": f"Exact prose is duplicated across separately contracted sections {prior_section} and {section_id}.",
            "next_action": "Rewrite each target with independent source-grounded prose.",
        })
    if has_blocking_contract_findings:
        return None, findings
    accepted: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, Mapping) or str(item.get("section_id")) not in expected_contracts:
            continue
        section_id = str(item["section_id"])
        section_finding_count = len(findings)
        outcome = str(item.get("outcome") or "")
        if outcome == "source_gap":
            findings.append({"category": "drafting", "field": section_id, "issue": "Post-approval drafting attempted to reopen source intake.", "required": ", ".join(map(str, expected_contracts[section_id].get("minimum_evidence") or [])), "next_action": "Retry from the approved evidence and listed Fixed Clinical Boilerplate without requesting more reviewer input."})
            continue
        if outcome not in {"drafted", "fixed_boilerplate"}:
            findings.append({"category": "drafting", "field": section_id, "issue": "Unknown section outcome.", "next_action": "Use drafted or fixed_boilerplate."})
            continue
        paragraphs = item.get("paragraphs") if isinstance(item.get("paragraphs"), list) else []
        clean_paragraphs: list[dict[str, Any]] = []
        for position, paragraph in enumerate(paragraphs, start=1):
            clean, paragraph_findings = _validate_paragraph(paragraph, request, expected_contracts[section_id], section_id, position)
            findings.extend(paragraph_findings)
            if clean:
                clean_paragraphs.append(clean)
        raw_lists = item.get("lists") if isinstance(item.get("lists"), list) else []
        lists = []
        for position, group in enumerate(raw_lists, start=1):
            clean_group, list_findings = _validate_list(group, request, expected_contracts[section_id], section_id, position)
            findings.extend(list_findings)
            if clean_group: lists.append(clean_group)
        combined_content = "\n".join(
            [paragraph["text"] for paragraph in clean_paragraphs]
            + [item for group in lists for item in group["items"]]
        )
        combined_evidence = [
            evidence
            for content_item in [*clean_paragraphs, *lists]
            for evidence in content_item.get("evidence_refs", [])
        ]
        role_content_parts = [
            paragraph["text"]
            for paragraph in clean_paragraphs
            if not _is_authorized_boilerplate_content(
                paragraph["text"],
                paragraph.get("evidence_refs", []),
                paragraph.get("boilerplate_refs", []),
                expected_contracts[section_id],
            )
        ]
        role_content_parts.extend(
            value
            for group in lists
            if not _is_authorized_boilerplate_content(
                "\n".join(group["items"]),
                group.get("evidence_refs", []),
                group.get("boilerplate_refs", []),
                expected_contracts[section_id],
            )
            for value in group["items"]
        )
        findings.extend(_coverage_findings(
            request,
            expected_contracts[section_id],
            section_id,
            combined_content,
            combined_evidence,
            "\n".join(role_content_parts),
        ))
        if not clean_paragraphs and not lists:
            findings.append({"category": "drafting", "field": section_id, "issue": "Required section has no substantive paragraphs or list items.", "next_action": "Return complete source-grounded content."})
        if len(findings) == section_finding_count and section_id not in duplicate_target_ids:
            accepted.append({"section_id": section_id, "attempt": int(request.get("attempts", {}).get(section_id, 1)), "batch_id": request.get("batch_id"), "artifact": request.get("artifact"), "outcome": outcome, "paragraphs": clean_paragraphs, "lists": lists, "producer": dict(producer), "request_id": request.get("request_id"), "request_sha256": request.get("request_sha256"), "governing_resources": dict(request.get("governing_resources", {}))})
    return {"kind": "sections", "drafts": accepted}, findings


def ingest_responses(revision_dir: Path, expected_governing: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Validate available Hermes responses and persist only accepted drafts."""
    findings: list[dict[str, Any]] = []
    for request_path in sorted((revision_dir / "hermes/requests").glob("*.json")):
        accepted_request = revision_dir / "hermes/accepted-requests" / request_path.name
        request = _read_json(request_path)
        if not _request_metadata_current(request, expected_governing):
            continue
        target_ids = [str(item.get("section_id")) for item in request.get("section_contracts", []) if isinstance(item, Mapping)]
        if not _trusted_request_valid(revision_dir, request, expected_governing):
            findings.append({
                "category": "request-integrity",
                "field": str(request.get("batch_id") or request_path.stem),
                "target_ids": target_ids,
                "issue": "Drafting request content does not match the trusted hash recorded when the request was created.",
                "required": "Restore the deterministic request or create a new approved revision.",
            })
            continue
        if accepted_request.is_file():
            recorded = _read_json(accepted_request)
            if not _trusted_request_valid(revision_dir, recorded, expected_governing) or _canonical(recorded) != _canonical(request):
                findings.append({
                    "category": "request-integrity",
                    "field": str(request.get("batch_id") or request_path.stem),
                    "target_ids": target_ids,
                    "issue": "Accepted drafting request no longer matches the immutable request record.",
                    "required": "Restore the accepted request or create a new approved revision.",
                })
            continue
        response_path = _response_path(revision_dir, request)
        if not response_path.is_file():
            continue
        if (revision_dir / "hermes/rejected" / response_path.name).is_file():
            continue
        try:
            response = _read_json(response_path)
            accepted, response_findings = validate_response(request, response)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            accepted, response_findings = None, [{
                "category": "drafting",
                "field": request.get("batch_id", "unknown"),
                "issue": f"Hermes response could not be read: {exc}",
                "next_action": "Replace it with valid response JSON.",
            }]
        for finding in response_findings:
            field = str(finding.get("field") or "")
            explicit_targets = [
                str(target) for target in finding.get("target_ids", [])
                if str(target) in target_ids
            ] if isinstance(finding.get("target_ids"), list) else []
            finding["target_ids"] = explicit_targets or ([field] if field in target_ids else target_ids)
        if accepted:
            if accepted["kind"] == "prs":
                accepted_path = revision_dir / "hermes/accepted/prs-narrative.json"
                if accepted_path.is_file():
                    existing = _read_json(accepted_path)
                    if existing.get("governing_resources") == accepted.get("governing_resources"):
                        merged = dict(existing)
                        merged["narrative"] = {**dict(existing.get("narrative") or {}), **dict(accepted.get("narrative") or {})}
                        accepted = merged
                _write_json(accepted_path, accepted)
            else:
                for draft in accepted["drafts"]:
                    _write_json(revision_dir / "hermes/accepted" / f"{draft['section_id'].replace('/', '_')}.json", draft)
        has_accepted_content = bool(
            accepted
            and (
                (accepted.get("kind") == "sections" and accepted.get("drafts"))
                or (accepted.get("kind") == "prs" and accepted.get("narrative"))
            )
        )
        if has_accepted_content:
            accepted_request.parent.mkdir(parents=True, exist_ok=True)
            accepted_request.write_text(request_path.read_text(encoding="utf-8"), encoding="utf-8")
        if response_findings:
            findings.extend(response_findings)
            rejected = revision_dir / "hermes/rejected" / response_path.name
            _write_json(rejected, {"request": request_path.name, "findings": response_findings})
            continue
        if not accepted:
            continue
    return findings


def missing_drafts(
    revision_dir: Path,
    reference: Mapping[str, Any],
    repo_root: Path | None = None,
    *,
    contracted_bundle: Mapping[str, Any] | None = None,
) -> list[str]:
    branch = canonical_study_type(get_path(reference, "meta.study_type")) or ""
    expected = (
        governing_resources(repo_root, reference, contracted_bundle=contracted_bundle)
        if repo_root is not None
        else None
    )
    required = [section.section_id for section in protocol_contract(branch) if section.role == "leaf"]
    if branch != "Retrospective":
        required.extend(section.section_id for section in icf_contract(branch, str(get_path(reference, "meta.icf_template", "Advarra"))))
        prs_record = accepted_prs_record(revision_dir, expected)
        narrative = prs_record.get("narrative", {})
        if not isinstance(narrative, Mapping):
            narrative = {}
        if "brief_summary" not in narrative:
            required.append("prs.brief-summary")
        if "detailed_description" not in narrative:
            required.append("prs.detailed-description")
    return [section_id for section_id in required if section_id.startswith("prs.") or accepted_draft(revision_dir, section_id, expected) is None]


def schedule_requests(
    *,
    repo_root: Path,
    revision_dir: Path,
    revision_id: str,
    reference: Mapping[str, Any],
    attempts: Mapping[str, int] | None = None,
    wave: str = "initial",
    findings: Iterable[Mapping[str, Any]] = (),
    contracted_bundle: Mapping[str, Any] | None = None,
) -> list[Path]:
    """Create one scoped request per ready batch; prerequisites are explicit."""
    attempts = dict(attempts or {})
    bundle = dict(contracted_bundle or contracted_template_bundle(repo_root, reference))
    expected = governing_resources(repo_root, reference, contracted_bundle=bundle)
    created: list[Path] = []
    finding_list = list(findings)
    plan = batch_plan(
        str(get_path(reference, "meta.study_type", "")),
        str(get_path(reference, "meta.icf_template", "Advarra")),
    )
    for batch in plan:
        if batch.prerequisites and any(
            any(accepted_draft(revision_dir, section_id, expected) is None for section_id in prerequisite.section_ids)
            for prerequisite_id in batch.prerequisites
            for prerequisite in plan
            if prerequisite.batch_id == prerequisite_id
        ):
            continue
        if batch.artifact == "prs":
            prs_record = accepted_prs_record(revision_dir, expected)
            narrative = prs_record.get("narrative", {})
            narrative = narrative if isinstance(narrative, Mapping) else {}
            key_by_target = {"prs.brief-summary": "brief_summary", "prs.detailed-description": "detailed_description"}
            targets = [target for target in batch.section_ids if key_by_target[target] not in narrative]
        else:
            targets = [section_id for section_id in batch.section_ids if accepted_draft(revision_dir, section_id, expected) is None]
        if not targets:
            continue
        target_findings = [item for item in finding_list if item.get("field") in targets or item.get("field") == batch.batch_id or any(target in targets for target in item.get("target_ids", []) if isinstance(item.get("target_ids"), list))]
        target_attempts = {target: int(attempts.get(target, 1)) for target in targets}
        request_id = _request_id(revision_id, batch.batch_id, target_attempts, wave, sha256_value(expected))
        existing = revision_dir / "hermes/requests" / f"{request_id}.json"
        if existing.is_file():
            continue
        created.append(create_drafting_request(
            repo_root=repo_root,
            revision_dir=revision_dir,
            revision_id=revision_id,
            reference=reference,
            batch=batch,
            target_ids=targets,
            attempts=target_attempts,
            wave=wave,
            findings=target_findings,
            contracted_bundle=bundle,
        ))
    return created


def merged_drafts(
    revision_dir: Path,
    reference: Mapping[str, Any],
    expected_governing: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the deterministic, section-addressed generation model."""
    branch = canonical_study_type(get_path(reference, "meta.study_type")) or ""
    protocol: list[dict[str, Any]] = []
    for section in protocol_contract(branch):
        entry = section.public()
        draft = accepted_draft(revision_dir, section.section_id, expected_governing)
        entry["paragraphs"] = list(draft.get("paragraphs") or []) if draft else []
        entry["lists"] = list(draft.get("lists") or []) if draft else []
        protocol.append(entry)
    icf = {}
    for section in icf_contract(branch, str(get_path(reference, "meta.icf_template", "Advarra"))):
        draft = accepted_draft(revision_dir, section.section_id, expected_governing)
        icf[section.section_id] = draft or {}
    prs = accepted_prs_record(revision_dir, expected_governing).get("narrative", {})
    return {"protocol": protocol, "icf": icf, "prs": prs}


def accepted_cross_section_duplicate_findings(
    revision_dir: Path,
    reference: Mapping[str, Any],
    expected_governing: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Find authenticated Protocol prose collisions before candidate rendering."""
    branch = canonical_study_type(get_path(reference, "meta.study_type")) or ""
    records: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
    for section in protocol_contract(branch):
        draft = accepted_draft(revision_dir, section.section_id, expected_governing)
        if draft is None:
            continue
        request = _read_json(
            revision_dir / "hermes/accepted-requests" / f"{draft['request_id']}.json"
        )
        contract = next(
            (
                item for item in request.get("section_contracts") or []
                if isinstance(item, Mapping) and item.get("section_id") == section.section_id
            ),
            {},
        )
        records.append((section.section_id, draft, contract))
    return [
        {
            "category": "content",
            "field": current,
            "target_ids": [prior, current],
            "issue": f"Exact prose is duplicated across authenticated Protocol sections {prior} and {current} before rendering.",
            "recovery_class": "drafting_defect",
            "action": "retry_drafting_target",
        }
        for prior, current in _cross_section_duplicate_pairs(records)
    ]


def retry_attempts(findings: Iterable[Mapping[str, Any]], prior: Mapping[str, int]) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Increment only retryable targets; source intake is closed after approval."""
    attempts = dict(prior)
    exhausted: list[dict[str, Any]] = []
    retry_targets: dict[str, Mapping[str, Any]] = {}
    for finding in findings:
        if finding.get("category") in {"source-evidence", "request-integrity"}: continue
        targets = finding.get("target_ids") if isinstance(finding.get("target_ids"), list) else [finding.get("field")]
        for target in targets:
            if target: retry_targets.setdefault(str(target), finding)
    for target, finding in retry_targets.items():
        next_attempt = int(attempts.get(target, 1)) + 1; attempts[target] = next_attempt
        if next_attempt > MAX_ATTEMPTS:
            exhausted.append({**dict(finding), "field": target, "issue": f"Retry limit reached after {MAX_ATTEMPTS} attempts. {finding.get('issue', '')}".strip()})
    return attempts, exhausted


def invalidate_accepted_targets(revision_dir: Path, target_ids: Iterable[str]) -> None:
    targets = {str(target) for target in target_ids}
    prs_path = revision_dir / "hermes/accepted/prs-narrative.json"
    if targets & {"prs.brief-summary", "prs.detailed-description"} and prs_path.is_file():
        accepted = _read_json(prs_path)
        narrative = dict(accepted.get("narrative") or {})
        if "prs.brief-summary" in targets:
            narrative.pop("brief_summary", None)
        if "prs.detailed-description" in targets:
            narrative.pop("detailed_description", None)
        if narrative:
            accepted["narrative"] = narrative
            _write_json(prs_path, accepted)
        else:
            prs_path.unlink()
    for target in targets:
        if target.startswith("prs."):
            continue
        (revision_dir / "hermes/accepted" / f"{target.replace('/', '_')}.json").unlink(missing_ok=True)


def response_template(request: Mapping[str, Any], *, model_id: str = "Hermes subagent") -> dict[str, Any]:
    """Return the exact response envelope a Hermes subagent must fill."""
    base = {
        "schema_version": RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "revision_id": request["revision_id"],
        "task": request["task"],
        "batch_id": request["batch_id"],
        "producer": {"model_id": model_id},
    }
    if request["task"] == "prs_narrative_drafting":
        keys = {
            "prs.brief-summary": "brief_summary",
            "prs.detailed-description": "detailed_description",
        }
        base["narrative"] = {
            keys[section["section_id"]]: {"text": "", "evidence_refs": []}
            for section in request["section_contracts"]
        }
    else:
        base["section_results"] = [{
            "section_id": section["section_id"],
            "outcome": "drafted",
            "paragraphs": [{"text": "", "evidence_refs": [], "boilerplate_refs": []}],
            "lists": [],
        } for section in request["section_contracts"]]
    return base


def recorded_acceptance_response(request: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic acceptance fixture adapter; never used in production."""
    response = response_template(request, model_id="RecordedAcceptance/v1")
    source = {str(item.get("path")): item.get("value") for item in request.get("approved_input", []) if isinstance(item, Mapping)}

    def value_text(value: Any) -> str:
        if isinstance(value, str): return value.strip()
        if isinstance(value, Mapping):
            return "; ".join(value_text(item) for item in value.values() if value_text(item))
        if isinstance(value, list): return "; ".join(value_text(item) for item in value if value_text(item))
        return "" if value is None else str(value)

    evidence = [(path, value_text(value)) for path, value in source.items() if value_text(value)]
    if request["task"] == "prs_narrative_drafting":
        title = next((value for path, value in evidence if path == "study.title"), "The approved study")
        background = next((value for path, value in evidence if path == "study.background"), title)
        hypothesis = next((value for path, value in evidence if path == "study.hypothesis"), "")
        objective = next((value for path, value in evidence if path.startswith("objectives.primary")), background)
        design = next((value for path, value in evidence if path == "design.study_design"), "")
        endpoint = next((value for path, value in evidence if path == "endpoints.primary"), "")
        secondary_endpoints = next((value for path, value in evidence if path == "endpoints.secondary"), "")
        population = next((value for path, value in evidence if path == "population.study_population"), "")
        assessments = next((value for path, value in evidence if path == "procedures.assessments"), "")
        narratives = {
            "brief_summary": {
                "text": " ".join(filter(None, [
                    f"{title}.",
                    f"The primary objective is {objective}.",
                    f"The study hypothesis is {hypothesis}." if hypothesis else "",
                    f"The primary endpoint is {endpoint}." if endpoint else "",
                    f"The approved study design is {design}.",
                ])),
                "evidence_refs": [
                    "source:study.title", "source:study.hypothesis", "source:objectives.primary",
                    "source:endpoints.primary", "source:design.study_design",
                ],
            },
            "detailed_description": {
                "text": "\n\n".join(filter(None, [
                    f"Background: {background}.",
                    f"Study hypothesis: {hypothesis}." if hypothesis else "",
                    f"Primary objective: {objective}.",
                    f"Study design: {design}.",
                    f"Study population: {population}.",
                    f"Study procedures and assessments: {assessments}.",
                    f"Primary endpoint: {endpoint}.",
                    f"Secondary endpoints: {secondary_endpoints}." if secondary_endpoints else "",
                ])),
                "evidence_refs": [
                    "source:study.background", "source:study.hypothesis", "source:objectives.primary", "source:design.study_design",
                    "source:population.study_population", "source:procedures.assessments", "source:endpoints.primary", "source:endpoints.secondary",
                ],
            },
        }
        available_refs = {f"source:{path}" for path, _value in evidence}
        for value in narratives.values():
            value["evidence_refs"] = [ref for ref in value["evidence_refs"] if ref in available_refs]
        response["narrative"] = {key: value for key, value in narratives.items() if key in response["narrative"]}
        return response
    for result, contract in zip(response["section_results"], request["section_contracts"]):
        fixed = contract.get("fixed_boilerplate") or []
        allowed_paths = [path for path in contract.get("minimum_evidence", []) if path in source and value_text(source[path])]
        section_id = str(contract.get("section_id"))
        if section_id == "study-procedure.enrollment" and fixed and allowed_paths:
            block = fixed[0]
            assessment_values = _leaf_texts(source.get("procedures.assessments"))
            assessments = "; ".join(assessment_values).rstrip(".")
            raw_schedule = source.get("procedures.visit_schedule_table") or source.get("procedures.visit_schedule") or []
            visit_items = []
            if isinstance(raw_schedule, list):
                for index, item in enumerate(raw_schedule, 1):
                    if isinstance(item, Mapping):
                        number = value_text(item.get("visitNumber")) or str(index)
                        name = value_text(item.get("visitName") or item.get("visit")) or f"Visit {number}"
                        crf = value_text(item.get("CRFnumber"))
                        crf_label = crf if crf.casefold().startswith("crf") else f"CRF {crf}" if crf else ""
                        details = [
                            value_text(item.get("visitWindow") or item.get("timing")),
                            crf_label,
                        ]
                        detail = "; ".join(value for value in details if value)
                        visit_items.append(f"Visit {number}: {name}{f' ({detail})' if detail else ''}.")
                    elif value_text(item):
                        visit_items.append(f"Visit {index}: {value_text(item)}.")
            timeline = value_text(source.get("study.timeline")).rstrip(".")
            detail_parts = []
            if assessments:
                detail_parts.append(f"The record review includes these approved assessments: {assessments}.")
            if timeline:
                detail_parts.append(f"The study timeline is {timeline}.")
            detail_refs = [
                f"source:{path}"
                for path in ("procedures.assessments", "study.timeline")
                if path in allowed_paths
            ]
            result["outcome"] = "drafted"
            result["paragraphs"] = [
                {"text": block["text"], "evidence_refs": [], "boilerplate_refs": [block["boilerplate_id"]]},
            ]
            if detail_parts:
                result["paragraphs"].append({
                    "text": " ".join(detail_parts),
                    "evidence_refs": detail_refs,
                    "boilerplate_refs": [],
                })
            if visit_items:
                result["lists"] = [{
                    "items": visit_items,
                    "evidence_refs": ["source:procedures.visit_schedule_table"],
                    "boilerplate_refs": [],
                }]
        elif fixed:
            block = fixed[0]
            result["outcome"] = "fixed_boilerplate"
            result["paragraphs"] = [{"text": block["text"], "evidence_refs": [], "boilerplate_refs": [block["boilerplate_id"]]}]
        elif allowed_paths:
            path = allowed_paths[0]; value = value_text(source[path])
            if section_id == "quality-safety" and isinstance(source.get("safety.roles"), list):
                role_prose = _structured_safety_role_prose(source["safety.roles"])
                risks = value_text(source.get("risks_benefits.risks")).rstrip(".")
                prose = role_prose
                if risks:
                    prose += f" Approved risks include {risks.casefold()}."
            elif section_id == "introduction": prose = value.rstrip(".") + "."
            elif section_id == "objectives":
                primary = value_text(source.get("objectives.primary")).rstrip(".")
                secondary = value_text(source.get("objectives.secondary")).rstrip(".")
                prose = f"The primary objective of this study is to {primary.removesuffix(' outcomes').casefold()} outcomes."
                if secondary:
                    prose += f" The secondary objective is to {secondary.removesuffix(' outcomes').casefold()} outcomes."
            elif section_id.startswith("subjects.population"): prose = f"The study population consists of {value.rstrip('.').casefold()}."
            elif section_id.endswith("inclusion"): prose = f"Participants must meet the following inclusion requirements: {value.rstrip('.')} ."
            elif section_id.endswith("eligibility"):
                inclusion = value_text(source.get("population.inclusion_criteria")).rstrip(".")
                exclusion = value_text(source.get("population.exclusion_criteria")).rstrip(".")
                prose = f"Participants must meet these inclusion criteria: {inclusion}. Participants are excluded when these criteria apply: {exclusion}."
            elif section_id.endswith("exclusion"): prose = f"Eligibility will be determined using these criteria: {value.rstrip('.')} ."
            elif section_id == "icf.study-purpose": prose = f"The purpose of this study is to {value.rstrip('.').removesuffix(' outcomes').casefold()} outcomes."
            elif section_id == "icf.procedures": prose = f"If you choose to take part, the study team will complete these assessments: {value.rstrip('.')} ."
            elif section_id == "icf.duration": prose = f"Your participation is expected to last {value.rstrip('.')} ."
            elif section_id == "icf.risks": prose = f"The possible risks or discomforts include {value.rstrip('.').casefold()}."
            elif section_id == "icf.benefits": prose = value.rstrip(".") + "."
            elif section_id == "icf.payment": prose = f"For this study, {value.rstrip('.').casefold()}."
            elif section_id == "study-design.design":
                design_text = value.rstrip('.').casefold()
                article = "an" if design_text[:1] in "aeiou" else "a"
                prose = f"This is {article} {design_text}."
            elif section_id == "study-procedure.visits": prose = f"Study visits and examinations include {value.rstrip('.')} ."
            elif section_id == "study-procedure.measurements": prose = f"At applicable visits, the study methods and measurements include {value.rstrip('.')} ."
            elif section_id == "evaluation-procedures": prose = f"The standard evaluations include {value.rstrip('.')} ."
            elif section_id == "analysis-plan.datasets": prose = "The analysis data sets will be organized around the outcome and safety-event summaries."
            elif section_id == "analysis-plan.methodology": prose = "The planned method is descriptive summarization of outcomes and safety events."
            elif section_id == "analysis-plan.considerations": prose = "Interpretation will separately consider outcome summaries and safety-event summaries."
            elif section_id == "sample-size":
                sample_size = value_text(source.get("population.sample_size")).rstrip(".")
                justification = value_text(source.get("population.sample_justification")).rstrip(".")
                prose = f"The planned sample size is {sample_size}."
                if justification:
                    prose += f" This sample size was selected to support {justification.casefold()}."
            elif section_id.startswith("risks-benefits.risks"): prose = f"The study risks include {value.rstrip('.').casefold()} ."
            elif section_id.startswith("risks-benefits.benefits"): prose = value.rstrip(".") + "."
            else: prose = f"For {str(contract.get('title') or section_id).casefold()}, the study will use {value.rstrip('.')} ."
            prose = prose.replace(" .", ".")
            refs = [f"source:{item}" for item in allowed_paths if value_text(source.get(item))]
            result["paragraphs"] = [{"text": prose, "evidence_refs": refs, "boilerplate_refs": []}]
        elif evidence:
            path, value = evidence[0]
            result["paragraphs"] = [{"text": f"The study information specifies that {value.rstrip('.')}.", "evidence_refs": [f"source:{path}"], "boilerplate_refs": []}]
        else:
            result.update({"outcome": "drafted", "paragraphs": []})
    for result, contract in zip(response["section_results"], request["section_contracts"]):
        section_id = str(contract.get("section_id"))
        allowed_paths = [
            path for path in contract.get("minimum_evidence", [])
            if path in source and value_text(source[path])
        ]
        existing = "\n".join(
            [str(item.get("text") or "") for item in result.get("paragraphs", []) if isinstance(item, Mapping)]
            + [str(value) for group in result.get("lists", []) if isinstance(group, Mapping) for value in group.get("items", [])]
        )
        used_refs = {
            str(ref)
            for item in [*result.get("paragraphs", []), *result.get("lists", [])]
            if isinstance(item, Mapping)
            for ref in item.get("evidence_refs", [])
        }
        all_items = contract.get("source_coverage") == "all_material_items"
        for path in allowed_paths:
            ref = f"source:{path}"
            if ref in used_refs and evidence_grounded(existing, source[path], all_items=all_items):
                continue
            label = path.rsplit(".", 1)[-1].replace("_", " ")
            section_label = str(contract.get("title") or result.get("section_id") or "section").strip().casefold()
            if path == "procedures.minimum_days_before_screening_without_participation":
                duration = value_text(source[path]).rstrip(".")
                if not re.search(r"\bdays?\s*$", duration, re.I):
                    duration = f"{duration} days"
                text = (
                    f"At least {duration} without participation "
                    "in another study are required before screening."
                )
            elif section_id == "quality-safety" and path == "safety.roles":
                text = _structured_safety_role_prose(source[path])
            else:
                text = (
                    f"For {section_label}, the approved {label} is "
                    f"{value_text(source[path]).rstrip('.')} ."
                ).replace(" .", ".")
            result.setdefault("paragraphs", []).append({"text": text, "evidence_refs": [ref], "boilerplate_refs": []})
            existing += "\n" + text
            used_refs.add(ref)
        if allowed_paths and result.get("outcome") == "fixed_boilerplate":
            result["outcome"] = "drafted"
    return response


__all__ = [
    "MAX_ATTEMPTS", "accepted_cross_section_duplicate_findings", "accepted_draft", "create_drafting_request", "ingest_responses",
    "evidence_grounded", "governing_resources", "invalidate_accepted_targets", "merged_drafts", "missing_drafts", "pending_requests", "response_template",
    "recorded_acceptance_response", "retry_attempts", "schedule_requests", "sha256_file", "sha256_value", "validate_response",
]
