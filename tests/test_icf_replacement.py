from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from clinical_document_workflow import branch_contract  # noqa: E402
from icf import (  # noqa: E402
    audit_icf_document,
    icf_contract,
    unified_icf_batch,
)
from prospective import prospective_batch_plan  # noqa: E402


class IcfReplacementTests(unittest.TestCase):
    def test_prospective_branch_has_one_unified_icf_batch(self) -> None:
        batches = prospective_batch_plan()
        self.assertEqual([batch.batch_id for batch in batches], [
            "protocol-foundations",
            "protocol-operations",
            "protocol-analysis-and-oversight",
            "prs-narrative",
            "icf-narrative",
        ])
        self.assertEqual(unified_icf_batch(), batches[-1])
        self.assertEqual(batches[-1].section_ids, tuple(item.section_id for item in icf_contract("Prospective", "Advarra")))

    def test_branch_contract_exposes_icf_contract_and_complete_candidate_visibility(self) -> None:
        contract = branch_contract({"meta": {"study_type": "Prospective", "icf_template": "Advarra"}})
        workflow = contract["replacement_workflow"]
        self.assertEqual(workflow["icf_contract"], "advarra-prospective-v1")
        self.assertEqual(workflow["drafting_batches"][-1]["batch_id"], "icf-narrative")
        self.assertEqual(workflow["candidate_visibility"], "internal_until_complete_branch_package")

    def test_advarra_prospective_contract_repairs_legal_reference_without_injury_section(self) -> None:
        contract = icf_contract("Prospective", "Advarra")
        titles = [item.title for item in contract]
        self.assertIn("LEGAL RIGHTS", titles)
        self.assertNotIn("IN CASE OF AN INJURY RELATED TO THIS RESEARCH STUDY", titles)
        self.assertEqual(
            next(item for item in contract if item.title == "LEGAL RIGHTS").repair,
            "Remove invalid cross-reference to a nonexistent injury section.",
        )

    def test_advarra_ambispective_contract_places_records_disclosure_in_procedures(self) -> None:
        procedure = next(section for section in icf_contract("Ambispective", "Advarra") if section.title == "WHAT WILL HAPPEN DURING THE STUDY")
        self.assertIn("existing-records", procedure.placement.casefold())

    def test_sterling_contracts_are_branch_specific(self) -> None:
        prospective = icf_contract("Prospective", "Sterling")
        ambispective = icf_contract("Ambispective", "Sterling")
        self.assertEqual([item.title for item in prospective], [item.title for item in ambispective])
        self.assertNotEqual(
            [item.section_id for item in prospective],
            [item.section_id for item in ambispective],
        )
        procedures = next(item for item in ambispective if item.title == "PROCEDURES")
        self.assertIn("existing-records", procedures.placement.casefold())
        self.assertFalse(next(item for item in prospective if item.title == "PROCEDURES").placement)

    def test_sanitized_sterling_template_passes_contract_audit_for_both_branches(self) -> None:
        from icf import sanitize_icf_document

        reference = {"study": {"title": "Approved study"}, "meta": {"protocol_number": "P-25"}}
        for study_type in ("Prospective", "Ambispective"):
            with self.subTest(study_type=study_type), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "icf.docx"
                source = REPO_ROOT / "assets/client-templates/docx/sterling-icf.template.docx"
                path.write_bytes(source.read_bytes())
                contract = icf_contract(study_type, "Sterling")
                sanitize_icf_document(path, contract, reference)
                self.assertEqual(audit_icf_document(path, contract, reference), [])

    def test_ambispective_sanitizer_inserts_records_disclosure_after_procedures_heading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "icf.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>INTRODUCTION</w:t></w:r></w:p><w:p><w:r><w:t>WHAT WILL HAPPEN DURING THE STUDY</w:t></w:r></w:p><w:p><w:r><w:t>Visit details.</w:t></w:r></w:p></w:body></w:document>',
                )
            from icf import sanitize_icf_document

            sanitize_icf_document(path, icf_contract("Ambispective", "Advarra"), {"study": {"title": "Approved study"}})
            with zipfile.ZipFile(path) as archive:
                document = archive.read("word/document.xml").decode()
            self.assertIn("existing medical records", document)
            self.assertLess(document.index("WHAT WILL HAPPEN"), document.index("existing medical records"))

    def test_icf_audit_rejects_review_residue_stale_facts_and_unstyled_headings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "icf.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", """<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body><w:p><w:r><w:t>LEGAL RIGHTS</w:t></w:r></w:p><w:p><w:r><w:t>cataract surgery</w:t></w:r></w:p><w:ins><w:r><w:t>review comment</w:t></w:r></w:ins></w:body></w:document>""")
            errors = audit_icf_document(path, icf_contract("Prospective", "Advarra"), {"study": {"title": "Approved study"}})
            fields = {item["field"] for item in errors}
            self.assertIn("word/document.xml", fields)
            self.assertIn("LEGAL RIGHTS", fields)


if __name__ == "__main__":
    unittest.main()
