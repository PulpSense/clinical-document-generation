from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from tests.test_quality_contract import QualityContractTests  # noqa: E402
import workflow  # noqa: E402
from workflow import approve, generate, prepare, validate  # noqa: E402


class WorkflowInterfaceTests(unittest.TestCase):
    def write_run(self, root: Path) -> Path:
        run_dir = root / "run"
        (run_dir / "input").mkdir(parents=True)
        (run_dir / "reference").mkdir(parents=True)
        reference = copy.deepcopy(QualityContractTests().complete_reference("Prospective"))
        (run_dir / "input/raw_context.md").write_text("Generate the clinical documents.", encoding="utf-8")
        (run_dir / "reference/study.reference.json").write_text(
            json.dumps(reference), encoding="utf-8"
        )
        return run_dir

    def test_public_workflow_exposes_only_the_four_lifecycle_operations(self) -> None:
        self.assertEqual(
            set(workflow.__all__),
            {"prepare", "approve", "validate", "generate"},
        )

    def test_prepare_and_validate_cross_the_public_seam(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self.write_run(Path(temporary))

            prepared = prepare(run_dir)
            readiness = validate(run_dir)

            self.assertEqual(prepared["status"], "blocked")
            self.assertEqual(readiness["stage"], "readiness")
            self.assertEqual(readiness["status"], "blocked")

    def test_public_workflow_is_the_only_lifecycle_entrypoint(self) -> None:
        self.assertTrue((REPO_ROOT / "scripts/workflow.py").is_file())
        self.assertFalse((REPO_ROOT / "scripts/clinical_document_workflow.py").exists())

    def test_public_workflow_owns_the_lifecycle_implementation(self) -> None:
        source = Path(workflow.__file__).read_text(encoding="utf-8")
        self.assertIn("def prepare_run(", source)
        self.assertIn("def generate_approved_run(", source)


if __name__ == "__main__":
    unittest.main()
