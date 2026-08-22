#!/usr/bin/env python3
"""Extract page text from common PDF files using only the Python standard library."""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


OBJECT_HEADER_RE = re.compile(rb"(?m)^(?P<number>\d+)\s+(?P<generation>\d+)\s+obj\b")
REFERENCE_RE = re.compile(rb"(?P<number>\d+)\s+\d+\s+R")


@dataclass(frozen=True)
class PdfName:
    value: str


@dataclass
class FontDecoder:
    encoding: str = "latin-1"
    cmap: dict[bytes, str] | None = None

    def decode(self, value: bytes) -> str:
        if self.cmap:
            lengths = sorted({len(key) for key in self.cmap}, reverse=True)
            output: list[str] = []
            offset = 0
            while offset < len(value):
                matched = False
                for length in lengths:
                    chunk = value[offset : offset + length]
                    if chunk in self.cmap:
                        output.append(self.cmap[chunk])
                        offset += length
                        matched = True
                        break
                if not matched:
                    output.append(bytes((value[offset],)).decode(self.encoding, errors="replace"))
                    offset += 1
            return "".join(output)
        return value.decode(self.encoding, errors="replace")


def _extract_objects(content: bytes) -> dict[int, bytes]:
    headers = list(OBJECT_HEADER_RE.finditer(content))
    objects: dict[int, bytes] = {}
    for index, header in enumerate(headers):
        boundary = headers[index + 1].start() if index + 1 < len(headers) else len(content)
        candidate = content[header.end() : boundary]
        end = candidate.rfind(b"endobj")
        if end >= 0:
            candidate = candidate[:end]
        objects[int(header.group("number"))] = candidate.strip()
    if not objects:
        raise ValueError("The PDF does not contain readable indirect objects.")
    return objects


def _stream_data(pdf_object: bytes) -> bytes:
    marker = re.search(rb"stream(?:\r\n|\n|\r)", pdf_object)
    if not marker:
        return b""
    end = pdf_object.rfind(b"endstream")
    if end < marker.end():
        raise ValueError("Malformed PDF stream.")
    data = pdf_object[marker.end() : end]
    if b"/FlateDecode" in pdf_object[: marker.start()]:
        candidates = [data]
        if data.endswith(b"\r\n"):
            candidates.append(data[:-2])
        elif data.endswith((b"\r", b"\n")):
            candidates.append(data[:-1])
        last_error: zlib.error | None = None
        for candidate in candidates:
            try:
                return zlib.decompress(candidate)
            except zlib.error as exc:
                last_error = exc
        raise ValueError("Unable to decompress a PDF text stream.") from last_error
    if data.endswith(b"\r\n"):
        data = data[:-2]
    elif data.endswith((b"\r", b"\n")):
        data = data[:-1]
    return data


def _decode_cmap_destination(value: bytes) -> str:
    if len(value) >= 2 and len(value) % 2 == 0:
        try:
            return value.decode("utf-16-be")
        except UnicodeDecodeError:
            pass
    return value.decode("latin-1", errors="replace")


def _parse_cmap(data: bytes) -> dict[bytes, str]:
    mapping: dict[bytes, str] = {}
    for section in re.finditer(rb"beginbfchar(?P<body>.*?)endbfchar", data, re.DOTALL):
        for source, destination in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", section.group("body")
        ):
            mapping[bytes.fromhex(source.decode())] = _decode_cmap_destination(
                bytes.fromhex(destination.decode())
            )
    for section in re.finditer(rb"beginbfrange(?P<body>.*?)endbfrange", data, re.DOTALL):
        body = section.group("body")
        array_re = re.compile(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]",
            re.DOTALL,
        )
        consumed: list[tuple[int, int]] = []
        for match in array_re.finditer(body):
            consumed.append(match.span())
            start = int(match.group(1), 16)
            end = int(match.group(2), 16)
            width = len(match.group(1)) // 2
            destinations = re.findall(rb"<([0-9A-Fa-f]+)>", match.group(3))
            for code, destination in zip(range(start, end + 1), destinations):
                mapping[code.to_bytes(width, "big")] = _decode_cmap_destination(
                    bytes.fromhex(destination.decode())
                )
        scalar_body = bytearray(body)
        for start, end in consumed:
            scalar_body[start:end] = b" " * (end - start)
        scalar_re = re.compile(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>"
        )
        for source_start, source_end, destination_start in scalar_re.findall(bytes(scalar_body)):
            start = int(source_start, 16)
            end = int(source_end, 16)
            width = len(source_start) // 2
            destination = int(destination_start, 16)
            destination_width = len(destination_start) // 2
            for offset, code in enumerate(range(start, end + 1)):
                mapping[code.to_bytes(width, "big")] = _decode_cmap_destination(
                    (destination + offset).to_bytes(destination_width, "big")
                )
    return mapping


def _encoding_name(font_object: bytes) -> str:
    match = re.search(rb"/Encoding\s*/(?P<name>[A-Za-z0-9_-]+)", font_object)
    if not match:
        return "latin-1"
    name = match.group("name")
    if name == b"MacRomanEncoding":
        return "mac_roman"
    if name == b"WinAnsiEncoding":
        return "cp1252"
    return "latin-1"


def _font_decoder(font_object: bytes, objects: dict[int, bytes]) -> FontDecoder:
    cmap = None
    match = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", font_object)
    if match:
        cmap_object = objects.get(int(match.group(1)), b"")
        cmap = _parse_cmap(_stream_data(cmap_object))
    return FontDecoder(encoding=_encoding_name(font_object), cmap=cmap or None)


def _page_resources(page_object: bytes, objects: dict[int, bytes]) -> bytes:
    current = page_object
    visited: set[int] = set()
    while True:
        reference = re.search(rb"/Resources\s+(\d+)\s+\d+\s+R", current)
        if reference:
            return objects.get(int(reference.group(1)), b"")
        direct = re.search(rb"/Resources\s*<<(.*?)>>", current, re.DOTALL)
        if direct:
            return direct.group(0)
        parent = re.search(rb"/Parent\s+(\d+)\s+\d+\s+R", current)
        if not parent:
            return b""
        parent_number = int(parent.group(1))
        if parent_number in visited:
            return b""
        visited.add(parent_number)
        current = objects.get(parent_number, b"")


def _page_fonts(page_object: bytes, objects: dict[int, bytes]) -> dict[str, FontDecoder]:
    resources = _page_resources(page_object, objects)
    font_dictionary = re.search(rb"/Font\s*<<(.*?)>>", resources, re.DOTALL)
    if not font_dictionary:
        return {}
    fonts: dict[str, FontDecoder] = {}
    for name, number in re.findall(
        rb"/([A-Za-z0-9_.-]+)\s+(\d+)\s+\d+\s+R", font_dictionary.group(1)
    ):
        fonts[name.decode("latin-1")] = _font_decoder(
            objects.get(int(number), b""), objects
        )
    return fonts


def _ordered_page_numbers(objects: dict[int, bytes]) -> list[int]:
    catalog = next(
        (value for value in objects.values() if re.search(rb"/Type\s*/Catalog\b", value)),
        None,
    )
    pages_reference = (
        re.search(rb"/Pages\s+(\d+)\s+\d+\s+R", catalog) if catalog else None
    )
    root_number = int(pages_reference.group(1)) if pages_reference else None
    if root_number is None:
        roots = [
            number
            for number, value in objects.items()
            if re.search(rb"/Type\s*/Pages\b", value)
        ]
        root_number = roots[0] if roots else None
    if root_number is None:
        return [
            number
            for number, value in objects.items()
            if re.search(rb"/Type\s*/Page\b", value)
            and not re.search(rb"/Type\s*/Pages\b", value)
        ]

    ordered: list[int] = []
    visited: set[int] = set()

    def visit(number: int) -> None:
        if number in visited:
            return
        visited.add(number)
        value = objects.get(number, b"")
        if re.search(rb"/Type\s*/Page\b", value) and not re.search(
            rb"/Type\s*/Pages\b", value
        ):
            ordered.append(number)
            return
        kids = re.search(rb"/Kids\s*\[(.*?)\]", value, re.DOTALL)
        if kids:
            for reference in REFERENCE_RE.finditer(kids.group(1)):
                visit(int(reference.group("number")))

    visit(root_number)
    return ordered


def _parse_literal_string(data: bytes, offset: int) -> tuple[bytes, int]:
    output = bytearray()
    depth = 1
    offset += 1
    while offset < len(data) and depth:
        value = data[offset]
        offset += 1
        if value == 0x5C:
            if offset >= len(data):
                break
            escaped = data[offset]
            offset += 1
            escapes = {
                ord("n"): b"\n",
                ord("r"): b"\r",
                ord("t"): b"\t",
                ord("b"): b"\b",
                ord("f"): b"\f",
                ord("("): b"(",
                ord(")"): b")",
                ord("\\"): b"\\",
            }
            if escaped in escapes:
                output.extend(escapes[escaped])
            elif escaped in b"\r\n":
                if escaped == 0x0D and offset < len(data) and data[offset] == 0x0A:
                    offset += 1
            elif ord("0") <= escaped <= ord("7"):
                digits = bytearray((escaped,))
                while (
                    len(digits) < 3
                    and offset < len(data)
                    and ord("0") <= data[offset] <= ord("7")
                ):
                    digits.append(data[offset])
                    offset += 1
                output.append(int(digits.decode(), 8) & 0xFF)
            else:
                output.append(escaped)
        elif value == 0x28:
            depth += 1
            output.append(value)
        elif value == 0x29:
            depth -= 1
            if depth:
                output.append(value)
        else:
            output.append(value)
    return bytes(output), offset


def _tokenize(data: bytes, offset: int = 0, stop_at_array_end: bool = False) -> Iterator[Any]:
    delimiters = b"()<>[]{}/%"
    whitespace = b"\x00\x09\x0a\x0c\x0d\x20"
    while offset < len(data):
        value = data[offset]
        if value in whitespace:
            offset += 1
            continue
        if value == ord("%"):
            newline = data.find(b"\n", offset)
            offset = len(data) if newline < 0 else newline + 1
            continue
        if value == ord("]") and stop_at_array_end:
            return
        if value == ord("["):
            end = _find_array_end(data, offset + 1)
            yield list(_tokenize(data[offset + 1 : end], 0, False))
            offset = end + 1
            continue
        if value == ord("("):
            literal, offset = _parse_literal_string(data, offset)
            yield literal
            continue
        if value == ord("<") and offset + 1 < len(data) and data[offset + 1] != ord("<"):
            end = data.find(b">", offset + 1)
            if end < 0:
                return
            compact = re.sub(rb"\s+", b"", data[offset + 1 : end])
            if len(compact) % 2:
                compact += b"0"
            try:
                yield bytes.fromhex(compact.decode())
            except ValueError:
                yield b""
            offset = end + 1
            continue
        if value == ord("/"):
            end = offset + 1
            while end < len(data) and data[end] not in whitespace + delimiters:
                end += 1
            yield PdfName(data[offset + 1 : end].decode("latin-1"))
            offset = end
            continue
        end = offset
        while end < len(data) and data[end] not in whitespace + delimiters:
            end += 1
        if end == offset:
            offset += 1
            continue
        raw = data[offset:end].decode("latin-1")
        try:
            yield float(raw)
        except ValueError:
            yield raw
        offset = end


def _find_array_end(data: bytes, offset: int) -> int:
    depth = 1
    while offset < len(data):
        value = data[offset]
        if value == ord("("):
            _, offset = _parse_literal_string(data, offset)
            continue
        if value == ord("["):
            depth += 1
        elif value == ord("]"):
            depth -= 1
            if depth == 0:
                return offset
        offset += 1
    return len(data)


def _decode_operand(value: Any, decoder: FontDecoder) -> str:
    if isinstance(value, bytes):
        return decoder.decode(value)
    if isinstance(value, list):
        return "".join(decoder.decode(item) for item in value if isinstance(item, bytes))
    return ""


def _extract_content_text(data: bytes, fonts: dict[str, FontDecoder]) -> str:
    output: list[str] = []
    operands: list[Any] = []
    decoder = FontDecoder()
    operators = {
        "BT",
        "ET",
        "Tf",
        "Tj",
        "TJ",
        "'",
        '"',
        "Td",
        "TD",
        "T*",
        "Tm",
        "BDC",
        "BMC",
        "EMC",
    }
    for token in _tokenize(data):
        if not isinstance(token, str) or token not in operators:
            operands.append(token)
            continue
        if token == "Tf" and len(operands) >= 2 and isinstance(operands[-2], PdfName):
            decoder = fonts.get(operands[-2].value, FontDecoder())
        elif token in {"Tj", "'", '"'} and operands:
            text = _decode_operand(operands[-1], decoder)
            if token in {"'", '"'} and output and not output[-1].endswith("\n"):
                output.append("\n")
            output.append(text)
        elif token == "TJ" and operands:
            output.append(_decode_operand(operands[-1], decoder))
        elif token == "ET" and output and not output[-1].endswith("\n"):
            output.append("\n")
        operands.clear()
    return "".join(output)


def _page_content(page_object: bytes, objects: dict[int, bytes]) -> bytes:
    array = re.search(rb"/Contents\s*\[(.*?)\]", page_object, re.DOTALL)
    if array:
        numbers = [int(match.group("number")) for match in REFERENCE_RE.finditer(array.group(1))]
    else:
        reference = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", page_object)
        numbers = [int(reference.group(1))] if reference else []
    return b"\n".join(_stream_data(objects.get(number, b"")) for number in numbers)


def extract_pdf_pages(path: Path) -> list[str]:
    """Return one extracted text string per PDF page.

    The extractor supports unencrypted PDFs with ordinary page content streams,
    Flate compression, Type1/TrueType encodings, and ToUnicode CMaps. These are
    the structures emitted by Apple Pages and the office renderers used by this
    skill. It intentionally rejects encrypted or object-stream-only PDFs.
    """

    content = path.read_bytes()
    if not content.startswith(b"%PDF-"):
        raise ValueError(f"Not a PDF file: {path}")
    if b"/Encrypt" in content:
        raise ValueError("Encrypted PDFs are not supported for TOC auditing.")
    objects = _extract_objects(content)
    pages = []
    for number in _ordered_page_numbers(objects):
        page_object = objects[number]
        fonts = _page_fonts(page_object, objects)
        pages.append(_extract_content_text(_page_content(page_object, objects), fonts))
    if pages and not any(any(ord(char) < 9 for char in page) for page in pages):
        return pages
    # LibreOffice may emit a valid PDF with a font encoding that cannot be
    # recovered from the standard-library parser.  Prefer an installed PDF
    # text engine as a compatibility fallback; the core workflow still has no
    # third-party runtime requirement.
    try:
        import fitz  # type: ignore

        with fitz.open(path) as document:
            fallback = [page.get_text() for page in document]
        if fallback:
            return fallback
    except (ImportError, OSError, RuntimeError):
        pass
    try:
        from pypdf import PdfReader  # type: ignore

        fallback = [(page.extract_text() or "") for page in PdfReader(str(path)).pages]
        if fallback:
            return fallback
    except (ImportError, OSError, ValueError):
        pass
    if not pages:
        raise ValueError("The PDF does not contain extractable pages.")
    return pages
