from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from delivery_pipeline import (  # noqa: E402
    AMBISPECTIVE_DOCUMENT_SET,
    PROSPECTIVE_ADVARRA_DOCUMENT_SET,
    bind_generation_manifest,
    verify_branch_document_set,
)
from revisions import publish_revision  # noqa: E402


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def write_docx(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = f'<w:document xmlns:w="{WORD_NS}"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p><w:sectPr/></w:body></w:document>'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", "<Relationships/>")


class BranchDeliveryTests(unittest.TestCase):
    def reference(self) -> dict:
        return {
            "meta": {"study_type": "Prospective", "icf_template": "Advarra", "protocol_number": "P-23"},
            "study": {"title": "A prospective study"},
        }

    def test_prospective_advarra_package_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "reference").mkdir()
            (run_dir / "reference/study.reference.json").write_text(json.dumps(self.reference()), encoding="utf-8")
            write_docx(run_dir / "output/protocol.docx", "A prospective study P-23")
            report = verify_branch_document_set(run_dir, ["output/protocol.docx"])

            self.assertEqual(report["status"], "failed")
            findings = report["review_passes"]["consistency"]["findings"]
            self.assertEqual({item["field"] for item in findings}, set(PROSPECTIVE_ADVARRA_DOCUMENT_SET) - {"output/protocol.docx"})

    def test_manifest_binds_artifact_hashes_and_verification_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "reference").mkdir()
            (run_dir / "reference/study.reference.json").write_text(json.dumps(self.reference()), encoding="utf-8")
            (run_dir / "revision").mkdir()
            manifest_path = run_dir / "revision/generation-manifest.json"
            manifest_path.write_text(json.dumps({"revision_id": "0001"}), encoding="utf-8")
            write_docx(run_dir / "output/protocol.docx", "A prospective study P-23")
            manifest = bind_generation_manifest(
                run_dir,
                manifest_path,
                ["output/protocol.docx"],
                {"review_passes": {"visual": {"evidence": {"output/protocol.docx": {"pages": [1]}}}}},
            )

            self.assertEqual(manifest["artifacts"][0]["path"], "output/protocol.docx")
            self.assertEqual(len(manifest["artifacts"][0]["sha256"]), 64)
            self.assertEqual(manifest["renderer_evidence"]["output/protocol.docx"]["pages"], [1])
            self.assertEqual(manifest["contracts"]["branch"], "prospective-advarra-package-v1")

    def test_ambispective_package_requires_the_complete_branch_document_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "reference").mkdir()
            reference = self.reference()
            reference["meta"]["study_type"] = "Ambispective"
            (run_dir / "reference/study.reference.json").write_text(json.dumps(reference), encoding="utf-8")
            write_docx(run_dir / "output/protocol.docx", "A prospective study P-23")
            report = verify_branch_document_set(run_dir, ["output/protocol.docx"])

            self.assertEqual(report["status"], "failed")
            self.assertEqual(
                {item["field"] for item in report["review_passes"]["consistency"]["findings"]},
                set(AMBISPECTIVE_DOCUMENT_SET) - {"output/protocol.docx"},
            )

    def test_only_the_newest_passing_revision_is_published(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            for revision_id, status in (("0001", "passed"), ("0002", "passed")):
                revision_dir = run_dir / "revisions" / revision_id
                revision_dir.mkdir(parents=True)
                (revision_dir / "generation-manifest.json").write_text(
                    json.dumps({"revision_id": revision_id, "status": status}), encoding="utf-8"
                )

            release = publish_revision(run_dir, "0001", ["output/protocol.docx"])

            self.assertEqual(release["status"], "not_published")
            self.assertEqual(release["reason"], "superseded_by_newer_passing_revision")
            self.assertFalse((run_dir / "state/client-facing-revision.json").exists())


if __name__ == "__main__":
    unittest.main()
