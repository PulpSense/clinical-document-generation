from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from acceptance_corpus import (  # noqa: E402
    ACCEPTANCE_CORPUS,
    BRANCH_TEMPLATE_MATRIX,
    drafting_task_budget,
    verification_task_budget,
)
from clinical_document_workflow import branch_contract  # noqa: E402
from prs_xml_contract import compare_structure  # noqa: E402


class BranchAcceptanceCorpusTests(unittest.TestCase):
    def test_corpus_has_sparse_and_rich_complete_studies_for_every_branch(self) -> None:
        by_branch = {}
        for fixture in ACCEPTANCE_CORPUS:
            if fixture.profile not in {"sparse-complete", "rich-complete"}:
                continue
            by_branch.setdefault(fixture.study_type, set()).add(fixture.profile)

        self.assertEqual(
            by_branch,
            {
                "Prospective": {"sparse-complete", "rich-complete"},
                "Ambispective": {"sparse-complete", "rich-complete"},
                "Retrospective": {"sparse-complete", "rich-complete"},
            },
        )
        self.assertEqual(
            len([fixture for fixture in ACCEPTANCE_CORPUS if fixture.profile in {"sparse-complete", "rich-complete"}]),
            6,
        )
        for fixture in ACCEPTANCE_CORPUS:
            self.assertTrue((REPO_ROOT / fixture.path).is_file(), fixture.path)

    def test_every_contracted_template_uses_the_public_branch_contract(self) -> None:
        for study_type, template in BRANCH_TEMPLATE_MATRIX:
            with self.subTest(study_type=study_type, template=template):
                reference = {"meta": {"study_type": study_type}}
                if template is not None:
                    reference["meta"]["icf_template"] = template
                replacement = branch_contract(reference)["replacement_workflow"]
                self.assertEqual(len(replacement["drafting_batches"]), drafting_task_budget(study_type))
                self.assertEqual(len(replacement["verification_tasks"]), verification_task_budget(study_type))

    def test_corpus_records_known_regressions_and_negative_fixtures(self) -> None:
        regression_paths = {fixture.path for fixture in ACCEPTANCE_CORPUS if fixture.regression}
        self.assertIn("tests/final_inputs/prospective_table_input_no_icf_template.md", regression_paths)
        self.assertIn("tests/final_inputs/prospective_non_table_input_no_icf_template.md", regression_paths)
        golden = REPO_ROOT / "assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml"
        defective = REPO_ROOT / "tests/fixtures/prs-xml-defective.xml"
        self.assertTrue(defective.is_file())
        self.assertTrue(compare_structure(golden, defective))


if __name__ == "__main__":
    unittest.main()
