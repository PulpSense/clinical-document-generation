"""A Source Intake Packet is the unit of client input.

Clients submit whatever they already have: one Markdown file, several files, or
a mix of types. These tests hold the packet contract -- every Evidence File is
preserved, identified, and accounted for in one manifest, and nothing is
silently dropped on the way to the reviewer document.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from branch_fixtures import approved_reference, write_reference


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_required_inputs import missing_inputs  # noqa: E402
from create_source_truth_md import document_markdown  # noqa: E402
from source_intake import (  # noqa: E402
    build_packet,
    packet_text,
    read_manifest,
)


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def write_docx(path: Path, paragraphs: list[str]) -> None:
    body = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in paragraphs)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{WORD_NS}"><w:body>{body}</w:body></w:document>'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document)


def entry(manifest: dict, filename: str) -> dict:
    for item in manifest["evidence"]:
        if item["filename"] == filename:
            return item
    raise AssertionError(
        f"{filename!r} not in {[item['filename'] for item in manifest['evidence']]}"
    )


class PacketManifestTests(unittest.TestCase):
    def test_single_markdown_file_is_the_simplest_packet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            source = root / "intake.md"
            source.write_text("# Study notes\nSponsor: Northwind Therapeutics\n", encoding="utf-8")

            manifest = build_packet(run_dir, [source])

            self.assertEqual(len(manifest["evidence"]), 1)
            only = manifest["evidence"][0]
            self.assertEqual(only["filename"], "intake.md")
            self.assertEqual(only["status"], "accepted")
            self.assertEqual(only["media_type"], "text/markdown")
            self.assertEqual(only["order"], 1)
            self.assertTrue((run_dir / only["path"]).is_file())
            self.assertIn("Northwind Therapeutics", packet_text(run_dir))

    def test_multiple_evidence_files_are_preserved_in_one_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            first = root / "intake-form.md"
            first.write_text("Sponsor: Northwind Therapeutics\n", encoding="utf-8")
            second = root / "sponsor-email.txt"
            second.write_text("The IRB of record is Advarra.\n", encoding="utf-8")
            third = root / "endpoints.json"
            third.write_text('{"primary": "Change in symptom score"}\n', encoding="utf-8")

            manifest = build_packet(run_dir, [first, second, third])

            self.assertEqual(len(manifest["evidence"]), 3)
            self.assertEqual([item["order"] for item in manifest["evidence"]], [1, 2, 3])
            self.assertEqual(
                len({item["id"] for item in manifest["evidence"]}),
                3,
                "each Evidence File needs a stable identity",
            )
            for item in manifest["evidence"]:
                self.assertEqual(item["status"], "accepted")
                self.assertTrue((run_dir / item["path"]).is_file())
                self.assertIn("provenance", item)
            combined = packet_text(run_dir)
            for expected in ("Northwind Therapeutics", "Advarra", "Change in symptom score"):
                self.assertIn(expected, combined)

    def test_mixed_supported_types_all_reach_the_extraction_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            markdown = root / "notes.md"
            markdown.write_text("Primary objective: reduce the symptom score.\n", encoding="utf-8")
            docx = root / "protocol-synopsis.docx"
            write_docx(docx, ["The sponsor is Northwind Therapeutics.", "Sample size is 120."])

            manifest = build_packet(run_dir, [markdown, docx])

            self.assertEqual(
                [item["status"] for item in manifest["evidence"]], ["accepted", "accepted"]
            )
            self.assertEqual(
                entry(manifest, "protocol-synopsis.docx")["media_type"],
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            combined = packet_text(run_dir)
            self.assertIn("reduce the symptom score", combined)
            self.assertIn("Northwind Therapeutics", combined)
            self.assertIn("Sample size is 120", combined)

    def test_unsupported_evidence_is_reported_not_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            markdown = root / "notes.md"
            markdown.write_text("Sponsor: Northwind Therapeutics\n", encoding="utf-8")
            image = root / "site-photo.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

            manifest = build_packet(run_dir, [markdown, image])

            self.assertEqual(len(manifest["evidence"]), 2)
            unsupported = entry(manifest, "site-photo.png")
            self.assertEqual(unsupported["status"], "unsupported")
            self.assertTrue(unsupported["error"])
            self.assertTrue(
                (run_dir / unsupported["path"]).is_file(),
                "unsupported evidence is still preserved for the reviewer",
            )
            self.assertEqual(manifest["counts"]["unsupported"], 1)
            self.assertEqual(manifest["counts"]["accepted"], 1)

    def test_unreadable_evidence_names_the_affected_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            broken = root / "corrupt-synopsis.docx"
            broken.write_bytes(b"this is not a docx archive")

            manifest = build_packet(run_dir, [broken])

            failed = entry(manifest, "corrupt-synopsis.docx")
            self.assertEqual(failed["status"], "unreadable")
            self.assertIn("corrupt-synopsis.docx", failed["error"] + failed["filename"])
            self.assertEqual(manifest["counts"]["unreadable"], 1)

    def test_manifest_round_trips_from_the_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            source = root / "intake.md"
            source.write_text("Sponsor: Northwind Therapeutics\n", encoding="utf-8")

            built = build_packet(run_dir, [source])

            self.assertEqual(read_manifest(run_dir), built)


class PacketDrivenSelectionTests(unittest.TestCase):
    def test_icf_template_choice_reads_the_whole_packet(self) -> None:
        from icf_template_selection import resolve_icf_template_choice

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            first = root / "intake-form.md"
            first.write_text("Study of Agent QX in adults.\n", encoding="utf-8")
            second = root / "irb-letter.md"
            second.write_text("The reviewing IRB is Sterling IRB.\n", encoding="utf-8")

            build_packet(run_dir, [first, second])
            reference = approved_reference("prospective")
            reference["meta"]["icf_template"] = None
            reference["parties"]["irb"]["name"] = "Central Ethics Board"

            # Reading only the first Evidence File finds no supported IRB...
            first_only = resolve_icf_template_choice(
                reference, raw_text=first.read_text(encoding="utf-8")
            )
            self.assertIsNone(first_only["choice"])

            # ...but the packet carries the answer in its second file.
            selection = resolve_icf_template_choice(reference, raw_text=packet_text(run_dir))

            self.assertEqual(selection["choice"], "Sterling")


class ConsolidatedBlockerTests(unittest.TestCase):
    def test_repeated_identical_evidence_is_corroboration_not_conflict(self) -> None:
        reference = approved_reference("prospective")
        title = reference["study"]["title"]
        reference["source"]["field_candidates"] = {
            "study.title": [
                {"value": title, "evidence": "input/evidence/001-intake-form.md"},
                {"value": title, "evidence": "input/evidence/002-sponsor-email.md"},
            ]
        }

        self.assertEqual(missing_inputs(reference), [])

    def test_distinct_evidence_produces_one_consolidated_request(self) -> None:
        reference = approved_reference("prospective")
        reference["study"]["hypothesis"] = None
        reference["source"]["field_candidates"] = {
            "study.title": [
                {"value": "Title A", "evidence": "input/evidence/001-intake-form.md"},
                {"value": "Title B", "evidence": "input/evidence/002-sponsor-email.md"},
            ],
            "design.study_design": [
                {"value": "Randomised", "evidence": "input/evidence/001-intake-form.md"},
                {"value": "Single arm", "evidence": "input/evidence/002-sponsor-email.md"},
            ],
        }

        blocking = missing_inputs(reference)

        fields = [item["field"] for item in blocking]
        self.assertIn("study.title", fields)
        self.assertIn("design.study_design", fields)
        self.assertIn("study.hypothesis", fields)
        self.assertEqual(len(fields), len(set(fields)), "one request per field")

    def test_optional_values_and_generic_notes_do_not_block_the_review_document(self) -> None:
        reference = approved_reference("prospective")
        reference["meta"]["version"] = None
        reference["needs_review"] = [
            {"field": "study.title", "issue": "Confirm capitalisation with the sponsor."},
            {"field": "meta.version", "issue": "Optional versioning note."},
        ]

        self.assertEqual(missing_inputs(reference), [])
        self.assertIn("Editable Study Inputs Start Here", document_markdown(reference))


class CreateRunPacketTests(unittest.TestCase):
    """`create_run.py` is the supported entry point for a client submission."""

    def run_create(self, argv: list[str]) -> Path:
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch

        import create_run

        buffer = io.StringIO()
        with patch.object(sys, "argv", ["create_run.py", *argv]), redirect_stdout(buffer):
            self.assertEqual(create_run.main(), 0)
        return Path(buffer.getvalue().strip())

    def test_raw_context_still_creates_a_single_file_packet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "notes.md"
            source.write_text("Retrospective chart review notes.\n", encoding="utf-8")

            self.run_create(
                [
                    "--root", str(root / "runs"),
                    "--slug", "single",
                    "--study-type", "retrospective",
                    "--raw-context", str(source),
                ]
            )
            run_dir = root / "runs" / "single"

            manifest = read_manifest(run_dir)
            self.assertEqual(manifest["counts"]["total"], 1)
            self.assertEqual(manifest["evidence"][0]["filename"], "notes.md")
            self.assertTrue((run_dir / "input" / "raw_context.md").is_file())
            self.assertIn("Retrospective chart review notes.", packet_text(run_dir))

    def test_multiple_evidence_files_become_one_packet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "intake-form.md"
            first.write_text("Prospective study of Agent QX.\n", encoding="utf-8")
            second = root / "irb-letter.md"
            second.write_text("Reviewed by Sterling IRB.\n", encoding="utf-8")
            third = root / "site-photo.png"
            third.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

            self.run_create(
                [
                    "--root", str(root / "runs"),
                    "--slug", "packet",
                    "--study-type", "prospective",
                    "--evidence", str(first),
                    "--evidence", str(second),
                    "--evidence", str(third),
                ]
            )
            run_dir = root / "runs" / "packet"

            manifest = read_manifest(run_dir)
            self.assertEqual(manifest["counts"]["total"], 3)
            self.assertEqual(manifest["counts"]["accepted"], 2)
            self.assertEqual(manifest["counts"]["unsupported"], 1)
            for item in manifest["evidence"]:
                self.assertTrue((run_dir / item["path"]).is_file())

    def test_template_selection_uses_evidence_beyond_the_first_file(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "intake-form.md"
            first.write_text("Prospective study of Agent QX in adults.\n", encoding="utf-8")
            second = root / "irb-letter.md"
            second.write_text("The reviewing board is Sterling IRB.\n", encoding="utf-8")

            self.run_create(
                [
                    "--root", str(root / "runs"),
                    "--slug", "selection",
                    "--study-type", "prospective",
                    "--evidence", str(first),
                    "--evidence", str(second),
                ]
            )
            run_dir = root / "runs" / "selection"

            reference = json.loads(
                (run_dir / "reference" / "study.reference.json").read_text(encoding="utf-8")
            )
            self.assertEqual(reference["meta"]["icf_template"], "Sterling")
            self.assertTrue((run_dir / "templates" / "icf.template.docx").is_file())


class ReviewDocumentTests(unittest.TestCase):
    def test_a_clean_packet_produces_only_the_reviewer_document(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            source = root / "intake.md"
            source.write_text("Complete study notes.\n", encoding="utf-8")
            build_packet(run_dir, [source])
            reference = approved_reference("prospective")
            reference["approval"]["status"] = "pending_review"
            write_reference(run_dir, reference)

            markdown = document_markdown(reference)

            self.assertIn("<!-- field: study.title -->", markdown)
            self.assertNotIn("generated.", markdown)
            self.assertFalse((run_dir / "output").exists())


if __name__ == "__main__":
    unittest.main()
