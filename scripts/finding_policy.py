"""Explicit ordinary-generation finding decisions during expand–contract migration.

Producers classify findings from evidence at their own boundary. This module
never guesses severity from prose, section names, or absent metadata. Unmigrated
findings retain their existing publication_disposition behavior.
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
    # Keep legacy consumers compatible during producer-by-producer migration.
    if classification in {"editorial_warning", "semantic_uncertainty"}:
        result["publication_disposition"] = "warning"
    else:
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
    classification = finding_classification(finding)
    if classification is None:
        return finding.get("publication_disposition") != "warning"
    return classification in {"essential_defect", "technical_failure"}


def blocks_publication(finding: Mapping[str, Any]) -> bool:
    classification = finding_classification(finding)
    if classification is None:
        return finding.get("publication_disposition") != "warning"
    return classification != "editorial_warning"
