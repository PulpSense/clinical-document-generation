#!/usr/bin/env python3
"""Scan DOCX and XML templates for brace-style placeholders."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


TOKEN_RE = re.compile(r"\{([#\^/]?)([A-Za-z0-9_.\-\[\]\(\)&]+)\}")
WORD_XML_PREFIXES = ("word/",)
WORD_XML_SUFFIX = ".xml"


def visible_text_from_word_xml(xml_bytes: bytes) -> str:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return xml_bytes.decode("utf-8", errors="ignore")
    chunks = []
    for elem in root.iter():
        if elem.tag.endswith("}t") and elem.text:
            chunks.append(elem.text)
        elif elem.tag.endswith("}tab"):
            chunks.append("\t")
        elif elem.tag.endswith("}br"):
            chunks.append("\n")
    return "".join(chunks)


def read_template_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        texts = []
        with zipfile.ZipFile(path) as docx:
            for name in docx.namelist():
                if name.startswith(WORD_XML_PREFIXES) and name.endswith(WORD_XML_SUFFIX):
                    texts.append(visible_text_from_word_xml(docx.read(name)))
        return "\n".join(texts)
    return path.read_text(encoding="utf-8")


def scan_path(path: Path) -> list[dict]:
    text = read_template_text(path)
    tokens = []
    for match in TOKEN_RE.finditer(text):
        prefix, name = match.groups()
        kind = "variable"
        if prefix == "#":
            kind = "block_start"
        elif prefix == "^":
            kind = "inverted_block_start"
        elif prefix == "/":
            kind = "block_end"
        tokens.append(
            {
                "template": str(path),
                "kind": kind,
                "name": name,
                "raw": match.group(0),
            }
        )
    return tokens


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("templates", nargs="+", help="Template files to scan.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    all_tokens = []
    for item in args.templates:
        path = Path(item)
        if not path.exists():
            all_tokens.append(
                {
                    "template": str(path),
                    "kind": "error",
                    "name": "",
                    "raw": "missing template",
                }
            )
            continue
        all_tokens.extend(scan_path(path))

    if args.json:
        print(json.dumps(all_tokens, indent=2))
    else:
        for token in all_tokens:
            print(f"{token['template']}\t{token['kind']}\t{token['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
