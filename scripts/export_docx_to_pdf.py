#!/usr/bin/env python3
"""Export DOCX to PDF with the best renderer available on the host system."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


PAGES_SCRIPT = r'''
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


WORD_POWERSHELL = r'''
$ErrorActionPreference = "Stop"
$word = $null
$document = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $document = $word.Documents.Open($env:CLINICAL_DOCX_INPUT)
    $document.ExportAsFixedFormat($env:CLINICAL_PDF_OUTPUT, 17)
} finally {
    if ($null -ne $document) { $document.Close(0) }
    if ($null -ne $word) { $word.Quit() }
}
'''


def renderer_order(system: str | None = None) -> list[str]:
    """Return renderer priority.

    Automatic delivery uses one deterministic authority order everywhere.  The
    optional platform argument remains available for callers that need the
    legacy platform capability list (and for diagnostics), but is not used by
    the active renderer selection.
    """
    if system is None:
        return ["word", "libreoffice", "pages"]
    current = (system or platform.system()).strip().lower()
    if current == "darwin":
        return ["pages", "libreoffice"]
    if current == "windows":
        return ["word", "libreoffice"]
    return ["libreoffice"]


def pages_available() -> bool:
    if platform.system() != "Darwin" or shutil.which("osascript") is None:
        return False
    return any(
        path.exists()
        for path in (
            Path("/Applications/Pages.app"),
            Path.home() / "Applications" / "Pages.app",
        )
    )


def powershell_command() -> str | None:
    for command in ("powershell.exe", "powershell", "pwsh.exe", "pwsh"):
        found = shutil.which(command)
        if found:
            return found
    return None


def libreoffice_command() -> str | None:
    for command in ("libreoffice", "soffice"):
        found = shutil.which(command)
        if found:
            return found
    if platform.system() == "Darwin":
        candidate = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        if candidate.exists():
            return str(candidate)
    if platform.system() == "Windows":
        for root_name in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            root = os.environ.get(root_name)
            if not root:
                continue
            candidate = Path(root) / "LibreOffice" / "program" / "soffice.exe"
            if candidate.exists():
                return str(candidate)
    return None


def renderer_available(renderer: str) -> bool:
    if renderer == "pages":
        return pages_available()
    if renderer == "word":
        return platform.system() == "Windows" and powershell_command() is not None
    if renderer == "libreoffice":
        return libreoffice_command() is not None
    return False


def run_pages(input_path: Path, output_path: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["osascript", "-", str(input_path), str(output_path)],
            input=PAGES_SCRIPT,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return False, "Pages did not finish rendering within 60 seconds."
    message = (result.stderr or result.stdout).strip()
    return result.returncode == 0 and output_path.is_file(), message


def run_word(input_path: Path, output_path: Path) -> tuple[bool, str]:
    command = powershell_command()
    if not command:
        return False, "PowerShell is unavailable."
    environment = os.environ.copy()
    environment["CLINICAL_DOCX_INPUT"] = str(input_path)
    environment["CLINICAL_PDF_OUTPUT"] = str(output_path)
    try:
        result = subprocess.run(
            [command, "-NoProfile", "-NonInteractive", "-Command", WORD_POWERSHELL],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return False, "Microsoft Word did not finish rendering within 60 seconds."
    message = (result.stderr or result.stdout).strip()
    return result.returncode == 0 and output_path.is_file(), message


def run_libreoffice(input_path: Path, output_path: Path) -> tuple[bool, str]:
    command = libreoffice_command()
    if not command:
        return False, "LibreOffice is unavailable."
    with tempfile.TemporaryDirectory() as temporary:
        temporary_path = Path(temporary)
        profile_path = temporary_path / "profile"
        profile_path.mkdir()
        # LibreOffice recalculates TOC fields during headless conversion and
        # can emit a PDF with an unusable text map.  Preserve the real field in
        # the client DOCX, but use its cached/static display for this render.
        render_input = temporary_path / input_path.name
        with zipfile.ZipFile(input_path) as source, zipfile.ZipFile(render_input, "w", zipfile.ZIP_DEFLATED) as destination:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename.startswith("word/") and item.filename.endswith(".xml"):
                    text = data.decode("utf-8", errors="ignore")
                    paragraphs = re.compile(r"<w:p\b.*?</w:p>", re.IGNORECASE | re.DOTALL)
                    text = paragraphs.sub(
                        lambda match: "" if re.search(r"\bTOC\b", match.group(0), re.IGNORECASE) else match.group(0),
                        text,
                    )
                    data = text.encode("utf-8")
                destination.writestr(item, data)
        try:
            result = subprocess.run(
                [
                    command,
                    f"-env:UserInstallation={profile_path.as_uri()}",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(temporary_path),
                    str(render_input),
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return False, "LibreOffice did not finish rendering within 60 seconds."
        converted = temporary_path / f"{input_path.stem}.pdf"
        message = (result.stderr or result.stdout).strip()
        if result.returncode != 0 or not converted.is_file():
            return False, message
        shutil.move(str(converted), str(output_path))
        return output_path.is_file(), message


def export_with_renderer(renderer: str, input_path: Path, output_path: Path) -> tuple[bool, str]:
    if renderer == "pages":
        return run_pages(input_path, output_path)
    if renderer == "word":
        return run_word(input_path, output_path)
    if renderer == "libreoffice":
        return run_libreoffice(input_path, output_path)
    return False, f"Unknown renderer: {renderer}"


def export_docx(
    input_path: Path,
    output_path: Path,
    renderer: str = "auto",
    require_renderer: bool = False,
) -> tuple[dict[str, Any], int]:
    input_path = input_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    result: dict[str, Any] = {
        "input": str(input_path),
        "output": str(output_path),
        "platform": platform.system(),
        "requested_renderer": renderer,
        "renderer": None,
        "status": "error",
        "attempts": [],
    }
    if not input_path.is_file():
        result["message"] = f"Input DOCX does not exist: {input_path}"
        return result, 1
    try:
        with zipfile.ZipFile(input_path) as archive:
            names = set(archive.namelist())
            content_types = archive.read("[Content_Types].xml").decode("utf-8", errors="ignore") if "[Content_Types].xml" in names else ""
            if (
                "word/document.xml" not in names
                or "word/_rels/document.xml.rels" not in names
                or "wordprocessingml.document.main+xml" not in content_types
            ):
                result["status"] = "unavailable"
                result["message"] = "Input is not a valid DOCX package."
                return result, 1 if (require_renderer or renderer != "auto") else 0
    except (OSError, zipfile.BadZipFile):
        result["status"] = "unavailable"
        result["message"] = "Input is not a valid DOCX package."
        return result, 1 if (require_renderer or renderer != "auto") else 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    candidates = renderer_order() if renderer == "auto" else [renderer]
    for candidate in candidates:
        available = renderer_available(candidate)
        attempt: dict[str, Any] = {"renderer": candidate, "available": available}
        result["attempts"].append(attempt)
        if not available:
            continue
        if output_path.exists():
            output_path.unlink()
        success, message = export_with_renderer(candidate, input_path, output_path)
        attempt["success"] = success
        if message:
            attempt["message"] = message
        if success:
            result["renderer"] = candidate
            result["status"] = "exported"
            result["message"] = f"Exported with {candidate}."
            return result, 0

    result["status"] = "unavailable"
    result["message"] = (
        "No usable DOCX-to-PDF renderer was found. The DOCX remains valid; "
        "PDF-based visual and TOC QA was skipped."
    )
    strict = require_renderer or renderer != "auto"
    return result, 1 if strict else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_docx", help="DOCX file to export.")
    parser.add_argument("output_pdf", help="PDF path to create when a renderer is available.")
    parser.add_argument(
        "--renderer",
        choices=("auto", "pages", "word", "libreoffice"),
        default="auto",
        help="Renderer to use. Defaults to platform-aware automatic selection.",
    )
    parser.add_argument(
        "--require-renderer",
        action="store_true",
        help="Return a failure when no renderer succeeds. Auto mode is nonblocking by default.",
    )
    parser.add_argument("--report", help="Optional JSON report path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result, return_code = export_docx(
        Path(args.input_docx),
        Path(args.output_pdf),
        renderer=args.renderer,
        require_renderer=args.require_renderer,
    )
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.report:
        report_path = Path(args.report).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
