from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from prs_xml_contract import compare_structure, repeated_counts  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml"
DEFECTIVE = ROOT / "tests/fixtures/prs-xml-defective.xml"


class PrsXmlContractTests(unittest.TestCase):
    def test_sanitized_golden_matches_itself_and_defective_fixture_fails(self) -> None:
        self.assertEqual(compare_structure(GOLDEN, GOLDEN), [])
        findings = compare_structure(GOLDEN, DEFECTIVE)
        self.assertTrue(findings)
        self.assertTrue(any("optional-node" in finding or "missing" in finding for finding in findings))

    def test_structural_comparison_ignores_values_and_repeat_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "candidate.xml"
            candidate.write_text(GOLDEN.read_text(encoding="utf-8").replace("{briefTitle}", "A &amp; B"), encoding="utf-8")
            self.assertEqual(compare_structure(GOLDEN, candidate), [])
            self.assertEqual(repeated_counts(candidate)["intervention"], 2)


if __name__ == "__main__":
    unittest.main()
