#!/usr/bin/env python3
"""Export a DOCX to PDF with Apple Pages using a Python entry point."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


APPLE_SCRIPT = r'''
on run argv
    if (count of argv) is not 2 then
        error "Expected input DOCX and output PDF paths."
    end if
    set inputFile to POSIX file (item 1 of argv)
    set outputFile to POSIX file (item 2 of argv)

    tell application "Pages"
        activate
        set theDoc to open inputFile
        if theDoc is missing value then
            delay 1
            set theDoc to front document
        end if
        export theDoc to outputFile as PDF
        close theDoc saving no
    end tell
end run
'''


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_docx", help="DOCX file to open in Pages.")
    parser.add_argument("output_pdf", help="PDF path to create.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input_docx).expanduser().resolve()
    output_path = Path(args.output_pdf).expanduser().resolve()
    if not input_path.is_file():
        print(f"Input DOCX does not exist: {input_path}", file=sys.stderr)
        return 1
    if shutil.which("osascript") is None:
        print("Apple Pages export requires macOS with osascript and Pages installed.", file=sys.stderr)
        return 1
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["osascript", "-", str(input_path), str(output_path)],
        input=APPLE_SCRIPT,
        text=True,
        check=False,
    )
    if result.returncode:
        return result.returncode
    if not output_path.is_file():
        print(f"Pages did not create the expected PDF: {output_path}", file=sys.stderr)
        return 1
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
