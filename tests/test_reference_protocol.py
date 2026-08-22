from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from create_run import main as create_run_main  # noqa: E402
from reference_protocol import (  # noqa: E402
    EMBEDDED_PROTOCOL_REFERENCE,
    embedded_protocol_reference,
)


class EmbeddedProtocolReferenceTests(unittest.TestCase):
    def test_embedded_reference_is_a_valid_registered_client_asset(self) -> None:
        metadata = embedded_protocol_reference()

        self.assertEqual(metadata["path"], "assets/client-templates/reference/protocol-reference.docx")
        self.assertEqual(metadata["source"], "embedded_client_reference")
        self.assertEqual(metadata["page_system"]["page_size"], "Letter")
        self.assertEqual(metadata["page_system"]["margins_inches"], {"left": 1.25, "right": 1.25, "top": 1.0, "bottom": 1.0})
        self.assertTrue(metadata["sha256"])
        self.assertTrue(EMBEDDED_PROTOCOL_REFERENCE.is_file())

    def test_create_run_records_reference_without_exposing_it_as_a_client_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "request.md"
            raw.write_text("A retrospective study request.", encoding="utf-8")
            old_argv = sys.argv
            sys.argv = [
                "create_run.py",
                "--root",
                str(root),
                "--slug",
                "reference-manifest",
                "--study-type",
                "retrospective",
                "--raw-context",
                str(raw),
            ]
            try:
                self.assertEqual(create_run_main(), 0)
            finally:
                sys.argv = old_argv

            run_dir = root / "reference-manifest"
            manifest = json.loads((run_dir / "input/source_manifest.json").read_text(encoding="utf-8"))
            reference = manifest["references"]["protocol"]
            self.assertEqual(reference["path"], "assets/client-templates/reference/protocol-reference.docx")
            self.assertEqual(reference["source"], "embedded_client_reference")
            self.assertNotIn("protocol-reference.docx", manifest["templates"])


if __name__ == "__main__":
    unittest.main()
