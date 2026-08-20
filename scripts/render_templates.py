#!/usr/bin/env python3
"""Render clinical DOCX and XML templates using only the Python standard library."""

from __future__ import annotations

import argparse
import copy
import html
import json
import re
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from data_driven_tables import read_matrix


STANDARD = {
    "reference": "reference/study.reference.json",
    "xml_template": "templates/study.template.xml",
    "xml_output": "output/study.xml",
    "report": "logs/generation-report.json",
}

DOCX_OUTPUTS = (
    ("protocol_docx", "templates/protocol.template.docx", "output/protocol.docx"),
    ("icf_docx", "templates/icf.template.docx", "output/icf.docx"),
    ("short_docx", "templates/short.template.docx", "output/short.docx"),
    ("main_docx", "templates/main.template.docx", "output/main.docx"),
)

XML_OUTPUT = ("xml", STANDARD["xml_template"], STANDARD["xml_output"])
PATH_CHARS = r"A-Za-z0-9_.\-\[\]\(\)&"
TOKEN_RE = re.compile(r"\{(?P<prefix>[#\^/]?)(?P<path>[" + PATH_CHARS + r"]+)\}")
BLOCK_RE = re.compile(
    r"\{#(?P<path>[" + PATH_CHARS + r"]+)\}(?P<body>.*?)\{/(?P=path)\}",
    re.DOTALL,
)
INVERTED_BLOCK_RE = re.compile(
    r"\{\^(?P<path>[" + PATH_CHARS + r"]+)\}(?P<body>.*?)\{/(?P=path)\}",
    re.DOTALL,
)
UNRESOLVED_RE = re.compile(r"\{[#/^]?[A-Za-z_][" + PATH_CHARS + r"]*\}")
GUID_RE = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)
TEXT_NODE_RE = re.compile(
    r"(?P<open><w:t\b[^>]*>)(?P<text>.*?)(?P<close></w:t>)",
    re.DOTALL,
)
PARAGRAPH_RE = re.compile(r"<w:p\b[^>]*>.*?</w:p>", re.DOTALL)
ROW_RE = re.compile(r"<w:tr\b[^>]*>.*?</w:tr>", re.DOTALL)
MISSING = object()

#: Table width copied from the bundled protocol templates' own visit table, so
#: an inserted table lines up with the tables already in the document.
MATRIX_TABLE_WIDTH_DXA = 8730
MATRIX_TABLE_BORDERS = ("top", "left", "bottom", "right", "insideH", "insideV")
#: A cell may not end with a table, and two adjacent tables merge into one, so
#: an inserted table is always followed by a paragraph.
EMPTY_PARAGRAPH = "<w:p/>"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default=".", help="Run directory. Defaults to the current directory.")
    parser.add_argument("--reference", help="Reference JSON path. Defaults inside --run-dir.")
    parser.add_argument(
        "--require-approval",
        action="store_true",
        help="Require approval.status to equal approved before rendering.",
    )
    return parser.parse_args(argv)


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return value


def get_path(data: Any, dotted_path: str) -> Any:
    if not dotted_path:
        return MISSING
    current = data
    for part in dotted_path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return MISSING
            current = current[part]
        elif isinstance(current, (list, tuple)) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return MISSING
            current = current[index]
        else:
            return MISSING
    return current


def resolve_value(local_data: Any, root_data: Any, dotted_path: str) -> Any:
    value = get_path(local_data, dotted_path)
    if value is not MISSING and value is not None:
        return value
    return get_path(root_data, dotted_path)


def stringify(value: Any) -> str:
    if value is MISSING or value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def xml_escape(value: Any) -> str:
    escaped = html.escape(stringify(value), quote=True)
    return escaped.replace("&#x27;", "&apos;")


def block_scopes(value: Any, local_data: Any) -> list[Any]:
    if value is MISSING or value is None or value is False or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        return [value]
    return [local_data] if bool(value) else []


def render_text_template(
    template: str,
    root_data: Any,
    local_data: Any | None = None,
    *,
    escape_values: bool = True,
) -> str:
    local_data = root_data if local_data is None else local_data

    def render_block(match: re.Match[str]) -> str:
        value = resolve_value(local_data, root_data, match.group("path"))
        return "".join(
            render_text_template(
                match.group("body"),
                root_data,
                scope,
                escape_values=escape_values,
            )
            for scope in block_scopes(value, local_data)
        )

    def render_inverted(match: re.Match[str]) -> str:
        value = resolve_value(local_data, root_data, match.group("path"))
        if block_scopes(value, local_data):
            return ""
        return render_text_template(
            match.group("body"), root_data, local_data, escape_values=escape_values
        )

    previous = None
    rendered = template
    while rendered != previous:
        previous = rendered
        rendered = BLOCK_RE.sub(render_block, rendered)
        rendered = INVERTED_BLOCK_RE.sub(render_inverted, rendered)

    def render_variable(match: re.Match[str]) -> str:
        if match.group("prefix"):
            return match.group(0)
        value = resolve_value(local_data, root_data, match.group("path"))
        return xml_escape(value) if escape_values else stringify(value)

    return TOKEN_RE.sub(render_variable, rendered)


def prs_counts(data: dict[str, Any]) -> dict[str, Any] | None:
    profile = data.get("__xml_profile")
    regulatory = data.get("regulatory")
    if not profile and isinstance(regulatory, dict):
        profile = regulatory.get("xml_profile")
    if str(profile or "") != "clinicaltrials-prs":
        return None
    counts = data.get("__prs_counts")
    return counts if isinstance(counts, dict) else None


def renumber_prs_block(block: str, tag_name: str, from_index: int, to_index: int) -> str:
    if tag_name == "primary_outcome":
        return block.replace("primaryOutcome", f"primaryOutcome{to_index}")
    bases = {
        "intervention": "intervention",
        "arm_group": "armGroup",
        "secondary_outcome": "secondaryOutcome",
        "other_outcome": "otherOutcome",
    }
    base = bases.get(tag_name)
    if not base:
        return block
    return block.replace(f"{base}{from_index}", f"{base}{to_index}")


def adjust_prs_repeated_blocks(template: str, data: dict[str, Any]) -> str:
    counts = prs_counts(data)
    if not counts:
        return template
    adjusted = template
    for tag_name in (
        "intervention",
        "arm_group",
        "primary_outcome",
        "secondary_outcome",
        "other_outcome",
    ):
        raw_count = counts.get(tag_name)
        try:
            count = max(0, int(raw_count))
        except (TypeError, ValueError):
            continue
        block_re = re.compile(
            rf"\n?\s*<{tag_name}>.*?</{tag_name}>", re.DOTALL
        )
        matches = list(block_re.finditer(adjusted))
        if not matches:
            continue
        if count <= len(matches):
            seen = 0

            def keep_required(match: re.Match[str]) -> str:
                nonlocal seen
                seen += 1
                return match.group(0) if seen <= count else ""

            adjusted = block_re.sub(keep_required, adjusted)
            continue
        last = matches[-1]
        last_block = last.group(0)
        extra = "".join(
            renumber_prs_block(last_block, tag_name, len(matches), index)
            for index in range(len(matches) + 1, count + 1)
        )
        adjusted = adjusted[: last.end()] + extra + adjusted[last.end() :]
    return adjusted


def unresolved_in_text(text: str) -> list[str]:
    return sorted({match for match in UNRESOLVED_RE.findall(text) if not GUID_RE.match(match)})


def visible_text_from_word_xml(xml: str) -> str:
    pieces: list[str] = []
    token_re = re.compile(
        r"<w:t\b[^>]*>(?P<text>.*?)</w:t>|<w:tab\b[^>]*/>|<w:br\b[^>]*/>",
        re.DOTALL,
    )
    for match in token_re.finditer(xml):
        raw = match.group("text")
        if raw is not None:
            pieces.append(html.unescape(re.sub(r"<[^>]+>", "", raw)))
        elif match.group(0).startswith("<w:tab"):
            pieces.append("\t")
        else:
            pieces.append("\n")
    return "".join(pieces)


def _text_node_text(xml: str) -> str:
    return "".join(html.unescape(match.group("text")) for match in TEXT_NODE_RE.finditer(xml))


def _serialize_text_content(value: str) -> str:
    escaped = html.escape(value, quote=False)
    escaped = escaped.replace("\r\n", "\n").replace("\r", "\n")
    escaped = escaped.replace("\t", '</w:t><w:tab/><w:t xml:space="preserve">')
    return escaped.replace("\n", '</w:t><w:br/><w:t xml:space="preserve">')


def _ensure_preserve(opening_tag: str, value: str) -> str:
    if not value or (not value[0].isspace() and not value[-1].isspace()):
        return opening_tag
    if "xml:space=" in opening_tag:
        return re.sub(r'xml:space="[^"]*"', 'xml:space="preserve"', opening_tag)
    return opening_tag[:-1] + ' xml:space="preserve">'


def _replace_text_matches(
    fragment: str,
    replacements: Iterable[tuple[int, int, str]],
) -> str:
    nodes = list(TEXT_NODE_RE.finditer(fragment))
    if not nodes:
        return fragment
    texts = [html.unescape(match.group("text")) for match in nodes]
    starts: list[int] = []
    position = 0
    for value in texts:
        starts.append(position)
        position += len(value)

    def locate_start(offset: int) -> tuple[int, int]:
        for index, (start, value) in enumerate(zip(starts, texts)):
            if start <= offset < start + len(value):
                return index, offset - start
        if offset == position:
            return len(texts) - 1, len(texts[-1])
        raise ValueError("Template token starts outside DOCX text nodes.")

    def locate_end(offset: int) -> tuple[int, int]:
        for index, (start, value) in enumerate(zip(starts, texts)):
            if start < offset <= start + len(value):
                return index, offset - start
        if offset == 0:
            return 0, 0
        raise ValueError("Template token ends outside DOCX text nodes.")

    for start, end, replacement in sorted(replacements, reverse=True):
        start_index, start_offset = locate_start(start)
        end_index, end_offset = locate_end(end)
        if start_index == end_index:
            texts[start_index] = (
                texts[start_index][:start_offset]
                + replacement
                + texts[start_index][end_offset:]
            )
            continue
        texts[start_index] = texts[start_index][:start_offset] + replacement
        for index in range(start_index + 1, end_index):
            texts[index] = ""
        texts[end_index] = texts[end_index][end_offset:]

    rebuilt: list[str] = []
    cursor = 0
    for match, value in zip(nodes, texts):
        rebuilt.append(fragment[cursor : match.start()])
        opening = _ensure_preserve(match.group("open"), value)
        rebuilt.append(opening + _serialize_text_content(value) + match.group("close"))
        cursor = match.end()
    rebuilt.append(fragment[cursor:])
    return "".join(rebuilt)


def _replace_literal_tokens(fragment: str, literals: dict[str, str]) -> str:
    visible = _text_node_text(fragment)
    replacements: list[tuple[int, int, str]] = []
    for literal, replacement in literals.items():
        replacements.extend(
            (match.start(), match.end(), replacement)
            for match in re.finditer(re.escape(literal), visible)
        )
    return _replace_text_matches(fragment, replacements)


def _render_docx_scalars(fragment: str, root_data: Any, local_data: Any) -> str:
    def replace_paragraph(paragraph_match: re.Match[str]) -> str:
        paragraph = paragraph_match.group(0)
        visible = _text_node_text(paragraph)
        replacements = []
        for match in TOKEN_RE.finditer(visible):
            if match.group("prefix"):
                continue
            value = resolve_value(local_data, root_data, match.group("path"))
            replacements.append((match.start(), match.end(), stringify(value)))
        return _replace_text_matches(paragraph, replacements)

    return PARAGRAPH_RE.sub(replace_paragraph, fragment)


def _single_complete_block(text: str) -> re.Match[str] | None:
    matches = list(BLOCK_RE.finditer(text))
    if len(matches) != 1:
        return None
    return matches[0]


def _render_docx_row_blocks(xml: str, root_data: Any, local_data: Any) -> str:
    def replace_row(row_match: re.Match[str]) -> str:
        row = row_match.group(0)
        visible = _text_node_text(row)
        block = _single_complete_block(visible)
        if not block:
            return row
        value = resolve_value(local_data, root_data, block.group("path"))
        scopes = block_scopes(value, local_data)
        start_token = "{#" + block.group("path") + "}"
        end_token = "{/" + block.group("path") + "}"
        return "".join(
            _render_docx_xml(
                _replace_literal_tokens(row, {start_token: "", end_token: ""}),
                root_data,
                scope,
            )
            for scope in scopes
        )

    return ROW_RE.sub(replace_row, xml)


def _matrix_cell_xml(value: str, width: int, *, header: bool) -> str:
    run_properties = (
        '<w:rFonts w:ascii="Arial" w:cs="Arial" w:eastAsia="Arial" w:hAnsi="Arial"/>'
        + ('<w:b w:val="1"/><w:bCs w:val="1"/>' if header else "")
        + '<w:sz w:val="20"/><w:szCs w:val="20"/>'
    )
    shading = '<w:shd w:fill="cccccc" w:val="clear"/>' if header else ""
    alignment = '<w:jc w:val="center"/>' if header else ""
    return (
        f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shading}</w:tcPr>'
        '<w:p><w:pPr><w:widowControl w:val="0"/>'
        '<w:spacing w:before="0" w:line="240" w:lineRule="auto"/>'
        f'<w:ind w:left="0" w:firstLine="0"/>{alignment}'
        f'<w:rPr>{run_properties}</w:rPr></w:pPr>'
        f'<w:r><w:rPr>{run_properties}<w:rtl w:val="0"/></w:rPr>'
        f'<w:t xml:space="preserve">{xml_escape(value)}</w:t></w:r></w:p></w:tc>'
    )


def _matrix_row_xml(values: list[str], width: int, *, header: bool) -> str:
    # Only the header repeats across pages; marking body rows as headers is the
    # defect that made the visit schedule unreadable.
    properties = (
        '<w:trPr><w:cantSplit w:val="1"/>'
        + ('<w:tblHeader w:val="1"/>' if header else "")
        + "</w:trPr>"
    )
    cells = "".join(_matrix_cell_xml(value, width, header=header) for value in values)
    return f"<w:tr>{properties}{cells}</w:tr>"


def _matrix_table_xml(cells: list[Any], columns: int, rows: int) -> str:
    """Build a real Word table from a row-major cell matrix."""
    if columns <= 0 or rows <= 0 or not cells:
        return ""
    width = max(MATRIX_TABLE_WIDTH_DXA // columns, 1)
    borders = "".join(
        f'<w:{edge} w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
        for edge in MATRIX_TABLE_BORDERS
    )
    body = []
    for index in range(rows):
        chunk = [stringify(cell) for cell in cells[index * columns : (index + 1) * columns]]
        # A ragged matrix still has to render as a rectangle.
        chunk += [""] * (columns - len(chunk))
        body.append(_matrix_row_xml(chunk, width, header=index == 0))
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for _ in range(columns))
    return (
        f'<w:tbl><w:tblPr><w:tblW w:w="{width * columns}" w:type="dxa"/>'
        f"<w:tblBorders>{borders}</w:tblBorders>"
        '<w:jc w:val="left"/><w:tblLook w:val="0600"/>'
        "<w:tblLayout w:type=\"fixed\"/></w:tblPr>"
        f"<w:tblGrid>{grid}</w:tblGrid>{''.join(body)}</w:tbl>"
    )


def _render_docx_matrix_tables(xml: str, root_data: Any, local_data: Any) -> str:
    """Replace a lone matrix placeholder paragraph with a real table."""

    def replace_paragraph(match: re.Match[str]) -> str:
        paragraph = match.group(0)
        token = TOKEN_RE.fullmatch(_text_node_text(paragraph).strip())
        if not token or token.group("prefix"):
            return paragraph
        matrix = read_matrix(resolve_value(local_data, root_data, token.group("path")))
        if matrix is None:
            return paragraph
        return _matrix_table_xml(*matrix) + EMPTY_PARAGRAPH

    return PARAGRAPH_RE.sub(replace_paragraph, xml)


def _standalone_marker(paragraph: str) -> tuple[str, str] | None:
    visible = _text_node_text(paragraph).strip()
    match = re.fullmatch(r"\{(?P<prefix>[#/])(?P<path>[" + PATH_CHARS + r"]+)\}", visible)
    if not match:
        return None
    return match.group("prefix"), match.group("path")


def _render_docx_paragraph_blocks(xml: str, root_data: Any, local_data: Any) -> str:
    while True:
        paragraphs = list(PARAGRAPH_RE.finditer(xml))
        stack: list[tuple[str, re.Match[str]]] = []
        pair: tuple[re.Match[str], re.Match[str], str] | None = None
        for paragraph in paragraphs:
            marker = _standalone_marker(paragraph.group(0))
            if not marker:
                continue
            prefix, path = marker
            if prefix == "#":
                stack.append((path, paragraph))
                continue
            for index in range(len(stack) - 1, -1, -1):
                start_path, start_paragraph = stack[index]
                if start_path == path:
                    pair = (start_paragraph, paragraph, path)
                    del stack[index:]
                    break
            if pair:
                break
        if not pair:
            return xml
        start, end, path = pair
        body = xml[start.end() : end.start()]
        value = resolve_value(local_data, root_data, path)
        replacement = "".join(
            _render_docx_xml(body, root_data, scope)
            for scope in block_scopes(value, local_data)
        )
        xml = xml[: start.start()] + replacement + xml[end.end() :]


def _render_docx_inline_blocks(xml: str, root_data: Any, local_data: Any) -> str:
    def replace_paragraph(paragraph_match: re.Match[str]) -> str:
        paragraph = paragraph_match.group(0)
        visible = _text_node_text(paragraph)
        if not BLOCK_RE.search(visible) and not INVERTED_BLOCK_RE.search(visible):
            return paragraph
        rendered = render_text_template(
            visible, root_data, local_data, escape_values=False
        )
        nodes = list(TEXT_NODE_RE.finditer(paragraph))
        if not nodes:
            return paragraph
        total = sum(len(html.unescape(node.group("text"))) for node in nodes)
        return _replace_text_matches(paragraph, [(0, total, rendered)])

    return PARAGRAPH_RE.sub(replace_paragraph, xml)


def _render_docx_xml(xml: str, root_data: Any, local_data: Any) -> str:
    rendered = _render_docx_matrix_tables(xml, root_data, local_data)
    rendered = _render_docx_row_blocks(rendered, root_data, local_data)
    rendered = _render_docx_paragraph_blocks(rendered, root_data, local_data)
    rendered = _render_docx_inline_blocks(rendered, root_data, local_data)
    return _render_docx_scalars(rendered, root_data, local_data)


def unresolved_in_docx(path: Path) -> list[str]:
    unresolved: set[str] = set()
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.startswith("word/") or not name.endswith(".xml"):
                continue
            visible = visible_text_from_word_xml(archive.read(name).decode("utf-8", errors="ignore"))
            unresolved.update(unresolved_in_text(visible))
    return sorted(unresolved)


def render_docx(template_path: Path, output_path: Path, data: dict[str, Any]) -> list[str]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=output_path.parent, delete=False, suffix=".docx"
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(template_path, "r") as source, zipfile.ZipFile(
            temporary_path, "w"
        ) as destination:
            for item in source.infolist():
                content = source.read(item.filename)
                if item.filename.startswith("word/") and item.filename.endswith(".xml"):
                    xml = content.decode("utf-8")
                    content = _render_docx_xml(xml, data, data).encode("utf-8")
                destination.writestr(copy.copy(item), content)
        with zipfile.ZipFile(temporary_path) as rendered:
            bad_member = rendered.testzip()
            if bad_member:
                raise ValueError(f"Rendered DOCX contains a corrupt member: {bad_member}")
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return unresolved_in_docx(output_path)


def render_xml(template_path: Path, output_path: Path, data: dict[str, Any]) -> list[str]:
    template = template_path.read_text(encoding="utf-8")
    adjusted = adjust_prs_repeated_blocks(template, data)
    rendered = render_text_template(adjusted, data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return unresolved_in_text(rendered)


def relative_to_run(path: Path, run_dir: Path) -> str:
    try:
        return path.relative_to(run_dir).as_posix()
    except ValueError:
        return path.name


def normalized_approval_status(data: dict[str, Any]) -> str:
    approval = data.get("approval")
    if not isinstance(approval, dict):
        return ""
    return str(approval.get("status") or "").strip().lower()


def build_render_data(data: dict[str, Any]) -> dict[str, Any]:
    template_fields = data.get("template_fields")
    if not isinstance(template_fields, dict):
        template_fields = {}
    return {**data, **template_fields}


def should_render(key: str, document_set: set[str]) -> bool:
    return not document_set or key in document_set


def run_generation(
    run_dir: Path,
    reference_path: Path,
    *,
    require_approval: bool = False,
) -> dict[str, Any]:
    data = read_json(reference_path)
    approval_status = normalized_approval_status(data)
    if require_approval and approval_status != "approved":
        raise ValueError("Final generation requires approval.status to be approved.")
    render_data = build_render_data(data)
    meta = data.get("meta")
    raw_document_set = meta.get("document_set") if isinstance(meta, dict) else None
    document_set = set(raw_document_set) if isinstance(raw_document_set, list) else set()
    outputs: list[str] = []
    templates: list[str] = []
    unresolved: dict[str, list[str]] = {}

    for key, template_rel, output_rel in DOCX_OUTPUTS:
        if not should_render(key, document_set):
            continue
        template_path = run_dir / template_rel
        if not template_path.exists():
            continue
        output_path = run_dir / output_rel
        unresolved[output_rel] = render_docx(template_path, output_path, render_data)
        outputs.append(output_rel)
        templates.append(template_rel)

    key, template_rel, output_rel = XML_OUTPUT
    xml_template = run_dir / template_rel
    if should_render(key, document_set) and xml_template.exists():
        unresolved[output_rel] = render_xml(xml_template, run_dir / output_rel, render_data)
        outputs.append(output_rel)
        templates.append(template_rel)

    report_path = run_dir / STANDARD["report"]
    prior_report: dict[str, Any] = {}
    if report_path.exists():
        try:
            prior_report = read_json(report_path)
        except (OSError, ValueError, json.JSONDecodeError):
            prior_report = {}
    report = {
        **prior_report,
        "run_dir": ".",
        "run_id": run_dir.name,
        "reference": relative_to_run(reference_path, run_dir),
        "templates": templates,
        "outputs": outputs,
        "approval_status": approval_status or None,
        "approval_required": require_approval,
        "unresolved_output_placeholders": unresolved,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir = Path(args.run_dir).expanduser().resolve()
    reference_path = (
        Path(args.reference).expanduser().resolve()
        if args.reference
        else run_dir / STANDARD["reference"]
    )
    try:
        report = run_generation(
            run_dir, reference_path, require_approval=args.require_approval
        )
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
