"""Reviewer resolution in Source-of-Truth Markdown is authoritative.

These tests walk the real review loop: extraction leaves a Required Source Input
Conflict, the reviewer resolves it in the Markdown, the approved Markdown is
reparsed, and the run continues. Nothing the reviewer decided may be resurrected
by pre-approval extraction state.
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

from branch_fixtures import (
    approved_reference,
    build_run,
    generated_modules,
    write_reference,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_required_inputs import missing_inputs  # noqa: E402
from create_source_truth_md import document_markdown  # noqa: E402
from generate_branch_documents import generate_branch  # noqa: E402
from parse_source_truth_md import parse_approved_markdown  # noqa: E402


TITLE_A = "A Study of Agent QX in Adults With Chronic Condition Y"
TITLE_B = "Agent QX for Chronic Condition Y: A Randomised Study"


def set_field(markdown: str, field_id: str, value: str) -> str:
    """Simulate a reviewer editing one field block in the Markdown."""
    pattern = re.compile(
        r"(<!--\s*field:\s*" + re.escape(field_id) + r"\s*-->\n).*?(\n<!--\s*/field\s*-->)",
        re.DOTALL,
    )
    updated, count = pattern.subn(lambda m: m.group(1) + value + m.group(2), markdown)
    if count != 1:
        raise AssertionError(f"Expected exactly one {field_id} block, found {count}.")
    return updated


def conflicted_run(run_dir: Path) -> dict:
    """A prospective run whose extraction found two distinct titles."""
    reference = build_run(run_dir, "prospective")
    reference["study"]["title"] = TITLE_A
    reference["source"]["field_candidates"] = {
        "study.title": [
            {"value": TITLE_A, "evidence": "input/intake-form.md"},
            {"value": TITLE_B, "evidence": "input/sponsor-email.md"},
        ]
    }
    reference["needs_review"] = [
        {
            "field": "study.title",
            "kind": "conflict",
            "issue": "Two distinct study titles were extracted from the Source Intake Packet.",
        }
    ]
    reference["approval"] = {
        "status": "pending_review",
        "review_file": None,
        "approved_by": None,
        "approved_at": None,
        "notes": None,
    }
    write_reference(run_dir, reference)
    return reference


def approve(run_dir: Path, markdown: str, *, status: str = "approved") -> dict:
    source_md = run_dir / "reference" / "source-of-truth.md"
    source_md.write_text(markdown, encoding="utf-8")
    return parse_approved_markdown(run_dir, source_md, approval_status=status)


class ConflictResolutionTests(unittest.TestCase):
    def test_conflict_blocks_until_the_reviewer_resolves_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = conflicted_run(run_dir)

            blocking = missing_inputs(reference)

            self.assertIn("study.title", [item["field"] for item in blocking])

    def test_resolved_conflict_does_not_block_the_next_required_input_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = conflicted_run(run_dir)
            markdown = set_field(document_markdown(reference), "study.title", TITLE_B)

            result = approve(run_dir, markdown)

            self.assertEqual(result["approval_status"], "approved")
            updated = result["reference"]
            self.assertEqual(updated["study"]["title"], TITLE_B)
            self.assertEqual(missing_inputs(updated), [])

    def test_stale_field_candidates_are_cleared_by_approved_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = conflicted_run(run_dir)
            markdown = set_field(document_markdown(reference), "study.title", TITLE_B)

            updated = approve(run_dir, markdown)["reference"]

            candidates = updated["source"]["field_candidates"]
            self.assertNotIn("study.title", candidates)

    def test_unresolved_candidates_survive_when_the_reviewer_leaves_them_blank(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = conflicted_run(run_dir)
            markdown = set_field(document_markdown(reference), "study.title", "")

            updated = approve(run_dir, markdown)["reference"]

            self.assertIn("study.title", updated["source"]["field_candidates"])
            self.assertIn(
                "study.title", [item["field"] for item in missing_inputs(updated)]
            )

    def test_explicitly_unresolved_review_state_still_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = conflicted_run(run_dir)
            reference["needs_review"][0]["unresolved"] = True
            write_reference(run_dir, reference)
            markdown = set_field(document_markdown(reference), "study.title", TITLE_B)

            updated = approve(run_dir, markdown)["reference"]

            self.assertEqual(
                [item["field"] for item in updated["needs_review"]], ["study.title"]
            )
            self.assertIn(
                "study.title", [item["field"] for item in missing_inputs(updated)]
            )

    def test_resolved_review_items_do_not_survive_as_stale_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = conflicted_run(run_dir)
            markdown = set_field(document_markdown(reference), "study.title", TITLE_B)

            updated = approve(run_dir, markdown)["reference"]

            self.assertEqual(updated["needs_review"], [])

    def test_operational_metadata_survives_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = conflicted_run(run_dir)
            markdown = set_field(document_markdown(reference), "study.title", TITLE_B)

            updated = approve(run_dir, markdown)["reference"]

            self.assertEqual(updated["meta"]["study_type"], "Prospective")
            self.assertEqual(updated["meta"]["icf_template"], "advarra")
            self.assertEqual(
                updated["meta"]["document_set"], ["protocol_docx", "icf_docx", "xml"]
            )
            self.assertEqual(updated["regulatory"]["xml_profile"], "clinicaltrials-prs")

    def test_approved_reviewer_strings_are_preserved_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = conflicted_run(run_dir)
            reviewer_string = "  Agent QX (QX-101) — a  deliberately odd   title  "
            markdown = set_field(document_markdown(reference), "study.short_title", reviewer_string)

            updated = approve(run_dir, markdown)["reference"]

            self.assertEqual(updated["study"]["short_title"], reviewer_string.strip())

    def test_rendering_stays_blocked_until_approval_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = conflicted_run(run_dir)
            markdown = set_field(document_markdown(reference), "study.title", TITLE_B)

            approve(run_dir, markdown, status="pending_review")
            blocked = generate_branch(run_dir, renderer_available=False)

            self.assertFalse(blocked["delivery_ready"])
            self.assertEqual(blocked["artifacts"], {})
            self.assertFalse((run_dir / "output" / "protocol.docx").exists())

    def test_approved_markdown_clears_draft_narrative_for_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = conflicted_run(run_dir)
            markdown = set_field(document_markdown(reference), "study.title", TITLE_B)

            updated = approve(run_dir, markdown)["reference"]

            # Draft prose was written from pre-approval facts, so it must not
            # survive into the approved reference.
            self.assertEqual(updated["generated"], {})

    def test_full_conflict_resolution_loop_reaches_a_delivered_document_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = conflicted_run(run_dir)
            markdown = set_field(document_markdown(reference), "study.title", TITLE_B)

            approved = approve(run_dir, markdown)["reference"]
            # Hermes rewrites the narrative modules from the approved facts.
            approved["generated"] = generated_modules("prospective")
            write_reference(run_dir, approved)
            result = generate_branch(run_dir, renderer_available=False)

            self.assertTrue(result["delivery_ready"], result["gates"])
            self.assertEqual(
                sorted(result["artifacts"]), ["icf_docx", "protocol_docx", "xml"]
            )
            self.assertIn(TITLE_B, (run_dir / "output" / "study.xml").read_text(encoding="utf-8"))


class ApprovalStateTests(unittest.TestCase):
    def test_supplying_source_material_is_not_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = approved_reference("retrospective")
            reference["approval"]["status"] = "pending_review"
            build_run(run_dir, "retrospective")
            write_reference(run_dir, reference)

            result = generate_branch(run_dir, renderer_available=False)

            self.assertFalse(result["delivery_ready"])
            approval = [g for g in result["gates"] if g["gate"] == "approval"][0]
            self.assertEqual(approval["status"], "fail")


if __name__ == "__main__":
    unittest.main()
