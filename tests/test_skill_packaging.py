"""A skill package is only as trustworthy as the smoke evidence behind it.

Packaging must be refused unless every supported branch generated its complete
default document set and passed every applicable Delivery Gate, with the
evidence retained so the released version can be audited afterwards.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

from branch_fixtures import approved_reference


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from package_skill import PackagingRefused, package_skill  # noqa: E402
from run_branch_smoke import SMOKE_BRANCHES, main as smoke_main, run_smoke  # noqa: E402


def unavailable_exporter(docx_path: Path, pdf_path: Path) -> dict:
    return {
        "status": "unavailable",
        "message": "No usable DOCX-to-PDF renderer was found.",
        "attempts": [{"renderer": "pages", "available": False}],
    }


def failing_exporter(docx_path: Path, pdf_path: Path) -> dict:
    return {"status": "error", "message": "renderer crashed"}


def branch_result(evidence: dict, branch: str) -> dict:
    for item in evidence["branches"]:
        if item["branch"] == branch:
            return item
    raise AssertionError(f"{branch} missing from {[b['branch'] for b in evidence['branches']]}")


class BranchSmokeTests(unittest.TestCase):
    def test_one_command_smokes_every_supported_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = run_smoke(Path(temporary), renderer_available=False)

            self.assertEqual(
                [item["branch"] for item in evidence["branches"]],
                ["Prospective", "Ambispective", "Retrospective"],
            )
            self.assertEqual(sorted(SMOKE_BRANCHES), ["Ambispective", "Prospective", "Retrospective"])
            self.assertTrue(evidence["package_eligible"], evidence["branches"])

    def test_no_renderer_flag_skips_renderer_backed_qa(self) -> None:
        """Running the smoke must not be able to launch a renderer unasked."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = smoke_main(["--root", str(root), "--no-renderer"])

            self.assertEqual(exit_code, 0)
            evidence = json.loads((root / "skill-smoke.json").read_text(encoding="utf-8"))
            self.assertTrue(evidence["package_eligible"], evidence["failed_branches"])
            for item in evidence["branches"]:
                visual = [g for g in item["gates"] if g["gate"] == "visual_qa"][0]
                self.assertEqual(visual["status"], "skipped")
                self.assertFalse(visual["blocking"])

    def test_evidence_identifies_outputs_gates_and_qa_limitations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = run_smoke(root, renderer_available=False)

            prospective = branch_result(evidence, "Prospective")
            self.assertEqual(
                prospective["document_set"], ["protocol_docx", "icf_docx", "xml"]
            )
            self.assertEqual(
                sorted(prospective["artifacts"]), ["icf_docx", "protocol_docx", "xml"]
            )
            gates = {item["gate"]: item["status"] for item in prospective["gates"]}
            for required in (
                "required_inputs",
                "placeholders",
                "content_completeness",
                "visit_table",
                "prs_xml",
                "stale_content",
                "visual_qa",
            ):
                self.assertIn(required, gates)
            self.assertEqual(gates["visual_qa"], "skipped")
            self.assertEqual(prospective["qa"]["renderer"], "unavailable")

            retrospective = branch_result(evidence, "Retrospective")
            self.assertEqual(retrospective["document_set"], ["protocol_docx"])

            saved = json.loads((root / "skill-smoke.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["package_eligible"], evidence["package_eligible"])

    def test_renderer_unavailability_does_not_make_the_skill_ineligible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = run_smoke(
                Path(temporary), renderer_available=True, exporter=unavailable_exporter
            )

            self.assertTrue(evidence["package_eligible"], evidence["branches"])

    def test_available_renderer_failure_makes_the_skill_ineligible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = run_smoke(
                Path(temporary), renderer_available=True, exporter=failing_exporter
            )

            self.assertFalse(evidence["package_eligible"])

    def test_a_failing_branch_makes_the_skill_ineligible(self) -> None:
        broken = approved_reference("retrospective")
        broken["generated"]["protocol"]["methods"] = ""

        with tempfile.TemporaryDirectory() as temporary:
            evidence = run_smoke(
                Path(temporary),
                renderer_available=False,
                fixtures={"Retrospective": broken},
            )

            self.assertFalse(evidence["package_eligible"])
            retrospective = branch_result(evidence, "Retrospective")
            self.assertFalse(retrospective["delivery_ready"])
            self.assertTrue(branch_result(evidence, "Prospective")["delivery_ready"])

    def test_stale_content_prevents_eligibility(self) -> None:
        tainted = approved_reference("prospective")
        tainted["generated"]["protocol"]["methods"] = (
            "Participants follow the Sunrise Cardiology Registry procedure."
        )
        tainted["meta"]["stale_content_markers"] = ["Sunrise Cardiology Registry"]

        with tempfile.TemporaryDirectory() as temporary:
            evidence = run_smoke(
                Path(temporary), renderer_available=False, fixtures={"Prospective": tainted}
            )

            self.assertFalse(evidence["package_eligible"])
            gates = {
                item["gate"]: item["status"]
                for item in branch_result(evidence, "Prospective")["gates"]
            }
            self.assertEqual(gates["stale_content"], "fail")

    def test_invalid_prs_xml_prevents_eligibility(self) -> None:
        invalid = approved_reference("prospective")
        invalid["regulatory"]["prs"]["study_uid"] = ""

        with tempfile.TemporaryDirectory() as temporary:
            evidence = run_smoke(
                Path(temporary), renderer_available=False, fixtures={"Prospective": invalid}
            )

            self.assertFalse(evidence["package_eligible"])


class PackagingTests(unittest.TestCase):
    def test_passing_smoke_produces_an_auditable_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "clinical-document-generation.zip"

            result = package_skill(
                archive_path, smoke_root=root / "smoke", renderer_available=False
            )

            self.assertTrue(archive_path.is_file())
            self.assertTrue(result["package_eligible"])
            self.assertEqual(result["archive"], str(archive_path))
            self.assertEqual(
                [item["branch"] for item in result["smoke"]["branches"]],
                ["Prospective", "Ambispective", "Retrospective"],
            )

    def test_package_contains_the_complete_skill_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "skill.zip"
            package_skill(archive_path, smoke_root=root / "smoke", renderer_available=False)

            with zipfile.ZipFile(archive_path) as archive:
                self.assertIsNone(archive.testzip())
                names = set(archive.namelist())

            self.assertIn("SKILL.md", names)
            self.assertIn("README.md", names)
            self.assertIn("scripts/generate_branch_documents.py", names)
            self.assertIn("references/template-contract.md", names)
            self.assertIn(
                "assets/client-templates/docx/prospective-protocol.template.docx", names
            )
            self.assertIn(
                "assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml",
                names,
            )
            self.assertIn("smoke-evidence.json", names)
            for script in sorted((REPO_ROOT / "scripts").glob("*.py")):
                self.assertIn(f"scripts/{script.name}", names)

    def test_packaging_is_refused_when_a_branch_fails(self) -> None:
        broken = approved_reference("ambispective")
        broken["study"]["hypothesis"] = None

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "skill.zip"

            with self.assertRaises(PackagingRefused) as raised:
                package_skill(
                    archive_path,
                    smoke_root=root / "smoke",
                    renderer_available=False,
                    fixtures={"Ambispective": broken},
                )

            self.assertIn("Ambispective", str(raised.exception))
            self.assertFalse(archive_path.exists(), "a refused package must not be written")

    def test_refusal_retains_the_evidence_that_caused_it(self) -> None:
        broken = approved_reference("prospective")
        broken["generated"]["protocol"]["visitScheduleTable"] = []
        broken["procedures"]["assessments"] = None

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(PackagingRefused):
                package_skill(
                    root / "skill.zip",
                    smoke_root=root / "smoke",
                    renderer_available=False,
                    fixtures={"Prospective": broken},
                )

            evidence = json.loads((root / "smoke" / "skill-smoke.json").read_text(encoding="utf-8"))
            self.assertFalse(evidence["package_eligible"])


if __name__ == "__main__":
    unittest.main()
