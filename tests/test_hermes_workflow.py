"""The complete Hermes workflow, from Source Intake Packet to package.

These scenarios walk the supported commands in the order Hermes runs them:
build the packet, extract a draft reference, gate the Required Source Inputs,
produce the reviewer-facing Source-of-Truth Markdown, wait for an explicit
approval, regenerate the narrative from approved facts, and only then generate,
gate, and evidence the branch document set.

The Extraction Pass itself is model-owned, so each scenario supplies the draft
reference Hermes would have written. Everything around it is the deterministic
layer under test.
"""

from __future__ import annotations

import io
import json
import re
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from branch_fixtures import approved_reference, generated_modules, write_reference


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import create_run  # noqa: E402
import create_source_truth_md  # noqa: E402
from check_required_inputs import missing_inputs  # noqa: E402
from generate_branch_documents import generate_branch  # noqa: E402
from parse_source_truth_md import parse_approved_markdown  # noqa: E402
from render_templates import visible_text_from_word_xml  # noqa: E402
from run_branch_smoke import run_smoke  # noqa: E402
from source_intake import packet_text, read_manifest, unreadable_report  # noqa: E402


REVIEW_MD = "reference/source-of-truth.md"


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return visible_text_from_word_xml(archive.read("word/document.xml").decode())


def write_files(root: Path, files: dict) -> list[Path]:
    paths = []
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = root / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        paths.append(path)
    return paths


def start_run(root: Path, slug: str, branch: str, evidence: list[Path]) -> Path:
    """Create the run and its Source Intake Packet, as Hermes does."""
    argv = [
        "create_run.py",
        "--root", str(root / "runs"),
        "--slug", slug,
        "--study-type", branch.lower(),
    ]
    for path in evidence:
        argv.extend(["--evidence", str(path)])
    buffer = io.StringIO()
    with patch.object(sys, "argv", argv), redirect_stdout(buffer):
        assert create_run.main() == 0
    return root / "runs" / slug


def extract(run_dir: Path, draft: dict) -> dict:
    """Stand in for the model-owned Extraction Pass."""
    existing = json.loads(
        (run_dir / "reference" / "study.reference.json").read_text(encoding="utf-8")
    )
    meta = draft.setdefault("meta", {})
    # The run already resolved operational metadata; extraction must not lose it.
    for key in ("icf_template", "document_set", "created_at"):
        if existing.get("meta", {}).get(key) and not meta.get(key):
            meta[key] = existing["meta"][key]
    draft["approval"] = {
        "status": "pending_review",
        "review_file": None,
        "approved_by": None,
        "approved_at": None,
        "notes": None,
    }
    write_reference(run_dir, draft)
    return draft


def create_review_document(run_dir: Path) -> int:
    """Run the reviewer-document command. Non-zero means blockers remain."""
    argv = [
        "create_source_truth_md.py",
        "--run-dir", str(run_dir),
        "--output", str(run_dir / REVIEW_MD),
        "--require-complete",
    ]
    buffer = io.StringIO()
    with patch.object(sys, "argv", argv), redirect_stdout(buffer):
        return create_source_truth_md.main()


def edit_field(markdown: str, field_id: str, value: str) -> str:
    pattern = re.compile(
        r"(<!--\s*field:\s*" + re.escape(field_id) + r"\s*-->\n).*?(\n<!--\s*/field\s*-->)",
        re.DOTALL,
    )
    updated, count = pattern.subn(lambda m: m.group(1) + value + m.group(2), markdown)
    if count != 1:
        raise AssertionError(f"Expected one {field_id} block, found {count}.")
    return updated


def approve(run_dir: Path, *, edits: dict | None = None, status: str = "approved") -> dict:
    review = run_dir / REVIEW_MD
    markdown = review.read_text(encoding="utf-8")
    for field_id, value in (edits or {}).items():
        markdown = edit_field(markdown, field_id, value)
    review.write_text(markdown, encoding="utf-8")
    return parse_approved_markdown(run_dir, review, approval_status=status)


def regenerate_narrative(run_dir: Path, branch: str) -> None:
    """Hermes rewrites the narrative modules from the approved facts."""
    reference = json.loads(
        (run_dir / "reference" / "study.reference.json").read_text(encoding="utf-8")
    )
    reference["generated"] = generated_modules(branch)
    write_reference(run_dir, reference)


def gate(result: dict, name: str) -> dict:
    for item in result["gates"]:
        if item["gate"] == name:
            return item
    raise AssertionError(f"Gate {name!r} missing.")


PROSPECTIVE_EVIDENCE = {
    "intake-form.md": (
        "# Study intake\n"
        "Sponsor: Northwind Therapeutics\n"
        "Prospective study of Agent QX in adults with Chronic Condition Y.\n"
    ),
    "irb-letter.md": "The reviewing board of record is Advarra IRB.\n",
    "endpoints.json": '{"primary": "Change in symptom score at week 12"}\n',
}


class SinglePacketScenarioTests(unittest.TestCase):
    def test_single_markdown_packet_reaches_an_approved_document_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = write_files(
                root / "inbox",
                {"notes.md": "Prospective study of Agent QX. Reviewed by Advarra IRB.\n"},
            )
            run_dir = start_run(root, "single", "prospective", evidence)
            extract(run_dir, approved_reference("prospective"))

            self.assertEqual(create_review_document(run_dir), 0)
            self.assertTrue((run_dir / REVIEW_MD).is_file())
            approve(run_dir)
            regenerate_narrative(run_dir, "prospective")
            result = generate_branch(run_dir, renderer_available=False)

            self.assertTrue(result["delivery_ready"], result["gates"])
            self.assertEqual(
                sorted(result["artifacts"]), ["icf_docx", "protocol_docx", "xml"]
            )
            self.assertEqual(read_manifest(run_dir)["counts"]["total"], 1)


class MultiFilePacketScenarioTests(unittest.TestCase):
    def test_every_readable_evidence_file_is_preserved_and_used(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = write_files(root / "inbox", PROSPECTIVE_EVIDENCE)
            run_dir = start_run(root, "multi", "prospective", evidence)

            manifest = read_manifest(run_dir)
            self.assertEqual(manifest["counts"]["accepted"], 3)
            combined = packet_text(run_dir)
            for expected in ("Northwind Therapeutics", "Advarra IRB", "Change in symptom score"):
                self.assertIn(expected, combined)

            extract(run_dir, approved_reference("prospective"))
            self.assertEqual(create_review_document(run_dir), 0)
            approve(run_dir)
            regenerate_narrative(run_dir, "prospective")
            result = generate_branch(run_dir, renderer_available=False)

            self.assertTrue(result["delivery_ready"], result["gates"])
            for item in manifest["evidence"]:
                self.assertTrue((run_dir / item["path"]).is_file(), item["filename"])

    def test_mixed_packet_reports_unsupported_and_unreadable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = write_files(
                root / "inbox",
                {
                    "intake-form.md": "Prospective study of Agent QX. Advarra IRB.\n",
                    "site-photo.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 24,
                    "corrupt-synopsis.docx": b"not really a docx",
                },
            )
            run_dir = start_run(root, "mixed", "prospective", evidence)

            manifest = read_manifest(run_dir)
            self.assertEqual(manifest["counts"]["total"], 3)
            self.assertEqual(manifest["counts"]["accepted"], 1)
            self.assertEqual(manifest["counts"]["unsupported"], 1)
            self.assertEqual(manifest["counts"]["unreadable"], 1)

            reported = unreadable_report(run_dir)
            names = {item["filename"] for item in reported}
            self.assertEqual(names, {"site-photo.png", "corrupt-synopsis.docx"})
            for item in reported:
                self.assertTrue(item["error"], item["filename"])

            # The readable evidence still carries the run forward.
            extract(run_dir, approved_reference("prospective"))
            self.assertEqual(create_review_document(run_dir), 0)


class BlockerScenarioTests(unittest.TestCase):
    def test_missing_required_inputs_produce_one_request_and_no_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = write_files(root / "inbox", {"notes.md": "Sparse notes. Advarra IRB.\n"})
            run_dir = start_run(root, "sparse", "prospective", evidence)
            draft = approved_reference("prospective")
            draft["study"]["hypothesis"] = None
            draft["study"]["background"] = None
            draft["population"]["sample_size"] = None
            extract(run_dir, draft)

            self.assertEqual(create_review_document(run_dir), 1)
            self.assertFalse((run_dir / REVIEW_MD).exists())

            report = (run_dir / "reference" / "missing-inputs.md").read_text(encoding="utf-8")
            for field in ("study.hypothesis", "study.background", "population.sample_size"):
                self.assertIn(field, report)

            result = generate_branch(run_dir, renderer_available=False)
            self.assertFalse(result["delivery_ready"])
            self.assertEqual(result["artifacts"], {})
            self.assertFalse((run_dir / "output" / "protocol.docx").exists())

    def test_a_conflict_stops_until_the_reviewer_resolves_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = write_files(root / "inbox", PROSPECTIVE_EVIDENCE)
            run_dir = start_run(root, "conflict", "prospective", evidence)
            draft = approved_reference("prospective")
            draft["source"]["field_candidates"] = {
                "population.sample_size": [
                    {"value": 120, "evidence": "input/evidence/001-intake-form.md"},
                    {"value": 150, "evidence": "input/evidence/003-endpoints.json"},
                ]
            }
            extract(run_dir, draft)

            self.assertEqual(create_review_document(run_dir), 1)
            self.assertIn(
                "population.sample_size",
                (run_dir / "reference" / "missing-inputs.md").read_text(encoding="utf-8"),
            )

            # The reviewer resolves it, and the run continues.
            draft["source"]["field_candidates"] = {}
            draft["population"]["sample_size"] = 150
            extract(run_dir, draft)
            self.assertEqual(create_review_document(run_dir), 0)
            approve(run_dir)
            regenerate_narrative(run_dir, "prospective")

            result = generate_branch(run_dir, renderer_available=False)
            self.assertTrue(result["delivery_ready"], result["gates"])


class ApprovalScenarioTests(unittest.TestCase):
    def test_supplying_a_packet_is_never_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = write_files(root / "inbox", PROSPECTIVE_EVIDENCE)
            run_dir = start_run(root, "unapproved", "prospective", evidence)
            extract(run_dir, approved_reference("prospective"))
            self.assertEqual(create_review_document(run_dir), 0)

            blocked = generate_branch(run_dir, renderer_available=False)
            self.assertFalse(blocked["delivery_ready"])
            self.assertEqual(gate(blocked, "approval")["status"], "fail")
            self.assertEqual(blocked["artifacts"], {})

            # A review that requests changes is still not approval.
            approve(run_dir, status="changes_requested")
            still_blocked = generate_branch(run_dir, renderer_available=False)
            self.assertFalse(still_blocked["delivery_ready"])

            approve(run_dir)
            regenerate_narrative(run_dir, "prospective")
            released = generate_branch(run_dir, renderer_available=False)
            self.assertTrue(released["delivery_ready"], released["gates"])

    def test_approved_reviewer_strings_survive_into_the_rendered_documents(self) -> None:
        reviewer_title = "Agent QX in Adults With Chronic Condition Y: A Reviewer-Corrected Title"

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = write_files(root / "inbox", PROSPECTIVE_EVIDENCE)
            run_dir = start_run(root, "authoritative", "prospective", evidence)
            extract(run_dir, approved_reference("prospective"))
            self.assertEqual(create_review_document(run_dir), 0)

            approve(run_dir, edits={"study.title": reviewer_title})
            regenerate_narrative(run_dir, "prospective")
            result = generate_branch(run_dir, renderer_available=False)

            self.assertTrue(result["delivery_ready"], result["gates"])
            self.assertIn(reviewer_title, docx_text(run_dir / "output" / "protocol.docx"))
            self.assertIn(reviewer_title, docx_text(run_dir / "output" / "icf.docx"))
            self.assertIn(
                reviewer_title, (run_dir / "output" / "study.xml").read_text(encoding="utf-8")
            )


class EveryBranchScenarioTests(unittest.TestCase):
    def walk(self, branch: str) -> tuple[Path, dict]:
        root = Path(self.temporary)
        evidence = write_files(
            root / f"inbox-{branch}",
            {"notes.md": f"{branch} study of Agent QX. Reviewed by Advarra IRB.\n"},
        )
        run_dir = start_run(root, branch, branch, evidence)
        extract(run_dir, approved_reference(branch))
        self.assertEqual(create_review_document(run_dir), 0)
        approve(run_dir)
        regenerate_narrative(run_dir, branch)
        return run_dir, generate_branch(run_dir, renderer_available=False)

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.temporary = self._temporary.name
        self.addCleanup(self._temporary.cleanup)

    def test_prospective_scenario_produces_its_default_set(self) -> None:
        _, result = self.walk("prospective")
        self.assertTrue(result["delivery_ready"], result["gates"])
        self.assertEqual(sorted(result["artifacts"]), ["icf_docx", "protocol_docx", "xml"])

    def test_ambispective_scenario_produces_its_default_set(self) -> None:
        _, result = self.walk("ambispective")
        self.assertTrue(result["delivery_ready"], result["gates"])
        self.assertEqual(sorted(result["artifacts"]), ["icf_docx", "protocol_docx", "xml"])

    def test_retrospective_scenario_produces_only_its_protocol(self) -> None:
        run_dir, result = self.walk("retrospective")
        self.assertTrue(result["delivery_ready"], result["gates"])
        self.assertEqual(sorted(result["artifacts"]), ["protocol_docx"])
        self.assertFalse((run_dir / "output" / "icf.docx").exists())
        self.assertFalse((run_dir / "output" / "study.xml").exists())

    def test_successful_scenario_records_validation_and_qa_evidence(self) -> None:
        run_dir, result = self.walk("prospective")

        saved = json.loads((run_dir / "logs" / "branch-generation.json").read_text())
        self.assertTrue(saved["delivery_ready"])
        self.assertEqual(saved["artifacts"], result["artifacts"])

        qa = json.loads((run_dir / "logs" / "visual-qa.json").read_text())
        self.assertEqual(qa["status"], "unavailable")
        self.assertIn("skipped", qa["note"])

        self.assertEqual(gate(result, "prs_xml")["status"], "pass")
        self.assertEqual(gate(result, "visit_table")["status"], "pass")


class PackageEligibilityScenarioTests(unittest.TestCase):
    def test_every_scenario_reaching_delivery_also_reaches_package_eligibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = run_smoke(Path(temporary), renderer_available=False)

            self.assertTrue(evidence["package_eligible"], evidence["failed_branches"])
            for record in evidence["branches"]:
                self.assertTrue(record["delivery_ready"], record["branch"])
                self.assertIsNone(record["repair_report"], record["branch"])

    def test_a_failed_delivery_gate_stops_the_scenario_being_reported_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = write_files(root / "inbox", PROSPECTIVE_EVIDENCE)
            run_dir = start_run(root, "tainted", "prospective", evidence)
            extract(run_dir, approved_reference("prospective"))
            self.assertEqual(create_review_document(run_dir), 0)
            approve(run_dir)

            reference = json.loads(
                (run_dir / "reference" / "study.reference.json").read_text(encoding="utf-8")
            )
            reference["generated"] = generated_modules("prospective")
            reference["generated"]["protocol"]["methods"] = (
                "Participants follow the Sunrise Cardiology Registry handpiece procedure."
            )
            reference["meta"]["stale_content_markers"] = ["Sunrise Cardiology Registry"]
            write_reference(run_dir, reference)

            result = generate_branch(run_dir, renderer_available=False)

            self.assertFalse(result["delivery_ready"])
            self.assertEqual(gate(result, "stale_content")["status"], "fail")
            self.assertTrue((run_dir / result["repair_report"]).is_file())
            saved = json.loads((run_dir / "logs" / "branch-generation.json").read_text())
            self.assertFalse(saved["delivery_ready"])


if __name__ == "__main__":
    unittest.main()
