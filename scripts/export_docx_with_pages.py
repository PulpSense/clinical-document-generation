#!/usr/bin/env python3
"""Export a DOCX to PDF with Apple Pages through the portable exporter."""

from __future__ import annotations

import sys

from export_docx_to_pdf import main as portable_main


def main(argv: list[str] | None = None) -> int:
    return portable_main([*(argv or sys.argv[1:]), "--renderer", "pages", "--require-renderer"])


if __name__ == "__main__":
    raise SystemExit(main())
