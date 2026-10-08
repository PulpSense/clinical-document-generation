"""Explicit ordinary-generation finding decisions during expand–contract migration.

Producers classify findings from evidence at their own boundary. This module
never guesses severity from prose, section names, or absent metadata. Unknown or malformed records retain their evidence as a code-owned
classification failure; they cannot authorize construction or publication.
"""
from __future__ import annotations

from typing import Any, Mapping

CLASSIFICATIONS = frozenset({
    "editorial_warning", "semantic_uncertainty", "essential_defect", "technical_failure",
})
REPAIR_OWNERS = frozenset({
    "none", "independent_review", "drafting", "construction", "rendering",
    "review_response", "source", "runtime", "integrity",
})


def classify_finding(
    finding: Mapping[str, Any], *, classification: str, reason: str, repair_owner: str,
) -> dict[str, Any]:
    """Attach an explicit, validated decision contract without mutating evidence."""
    policy = {"classification": classification, "reason": reason, "repair_owner": repair_owner}
    _validate(policy)
    result = {**finding, "finding_policy": policy}
    result.pop("publication_disposition", None)
    return result


def _validate(policy: Mapping[str, Any]) -> None:
    classification = policy.get("classification")
    owner = policy.get("repair_owner")
    if classification not in CLASSIFICATIONS or owner not in REPAIR_OWNERS:
        raise ValueError("Finding policy requires an explicit classification and repair owner.")
    if not isinstance(policy.get("reason"), str) or not policy["reason"].strip():
        raise ValueError("Finding policy requires an evidenced reason.")
    if classification == "semantic_uncertainty" and owner != "independent_review":
        raise ValueError("Semantic uncertainty requires independent review.")
    if classification == "editorial_warning" and owner not in {"none", "independent_review"}:
        raise ValueError("Editorial warnings cannot demand an essential repair.")
    if classification in {"essential_defect", "technical_failure"} and owner in {"none", "independent_review"}:
        raise ValueError("Essential and technical findings require a repair owner.")


def finding_classification(finding: Mapping[str, Any]) -> str | None:
    """Return explicit classification; malformed migrated records fail closed."""
    if "finding_policy" not in finding:
        return None
    policy = finding["finding_policy"]
    if not isinstance(policy, Mapping):
        raise ValueError("Finding policy must be a structured contract.")
    _validate(policy)
    return str(policy["classification"])


def blocks_construction(finding: Mapping[str, Any]) -> bool:
    classification = finding_classification(normalize_finding(finding, producer="stage-decision"))
    return classification in {"essential_defect", "technical_failure"}


def blocks_publication(finding: Mapping[str, Any]) -> bool:
    classification = finding_classification(normalize_finding(finding, producer="stage-decision"))
    return classification != "editorial_warning"


def normalize_finding(finding: Mapping[str, Any], *, producer: str) -> dict[str, Any]:
    """Validate an ordinary record, preserving unknown evidence for maintenance."""
    try:
        classification = finding_classification(finding)
        if classification is None:
            raise ValueError("Producer did not declare a finding policy.")
        # Recovery metadata is a separate transport contract. A declared repair
        # may not silently send a proven cause to a different clinical owner.
        route_owners = {
            "drafting_defect": {"drafting"},
            "deterministic_structure_defect": {"construction"},
            "document_structure_defect": {"construction", "integrity"},
            "visual_defect": {"rendering"},
            "verifier_transient": {"review_response", "integrity"},
            "transport_fault": {"runtime"},
            "adapter_fault": {"runtime"},
            "font_capability_uncertainty": {"runtime"},
            "capability_gap": {"construction", "runtime", "integrity"},
        }
        recovery_class = finding.get("recovery_class")
        if classification in {"essential_defect", "technical_failure"} and recovery_class in route_owners:
            if finding["finding_policy"]["repair_owner"] not in route_owners[recovery_class]:
                raise ValueError("Finding repair owner contradicts its declared Recovery Class.")
    except (ValueError, TypeError) as exc:
        return classify_finding({
            "category": "recovery-classification", "code": "finding-policy-classification",
            "field": producer, "issue": "The ordinary finding classification requires code maintenance.",
            "classification_error": str(exc), "original_finding": dict(finding),
            "recovery_class": "capability_gap", "action": "preserve_and_stop", "owner": "capability_gap",
        }, classification="technical_failure", reason="finding-policy-classification", repair_owner="construction")
    result = dict(finding)
    result.pop("publication_disposition", None)
    return result


def declare_finding(finding: Mapping[str, Any], *, classification: str, reason: str, repair_owner: str) -> dict[str, Any]:
    """Complete a producer's explicit conditional policy without losing its caution.

    Existing policies are produced by trusted branch-specific code. External
    reviewer metadata never supplies this contract. Invalid policies are retained
    as classification failures rather than exceptions or invented clinical flaws.
    """
    if "finding_policy" in finding:
        return normalize_finding(finding, producer=reason)
    return classify_finding(finding, classification=classification, reason=reason, repair_owner=repair_owner)
