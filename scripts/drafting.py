"""Drafting seam for future Hermes batch orchestration.

The expand step deliberately keeps model orchestration outside deterministic
Python.  This module defines the small batch-plan value used by later work and
does not call a model API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from retrospective import SectionDraft, merge_section_drafts, retrospective_batch_plan


@dataclass(frozen=True)
class DraftingBatch:
    """A stable, named group of section IDs assigned to one drafting pass."""

    batch_id: str
    section_ids: tuple[str, ...]
    prerequisite_ids: tuple[str, ...] = ()


def plan_batches(batch_specs: Iterable[DraftingBatch]) -> tuple[DraftingBatch, ...]:
    """Normalize a drafting topology without invoking an external model."""
    batches = tuple(batch_specs)
    if len({batch.batch_id for batch in batches}) != len(batches):
        raise ValueError("Drafting batch IDs must be unique.")
    return batches


def plan_retrospective_batches() -> tuple[DraftingBatch, ...]:
    """Expose the retrospective topology through the DraftingBatch seam."""
    return tuple(
        DraftingBatch(item["batch_id"], tuple(item["section_ids"]))
        for item in retrospective_batch_plan()
    )


__all__ = ["DraftingBatch", "SectionDraft", "plan_batches", "plan_retrospective_batches", "retrospective_batch_plan", "merge_section_drafts"]
