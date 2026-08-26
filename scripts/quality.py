"""Fail-closed content, XML, renderer, and page-visual quality gates."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader
from lxml import etree as ET

from contracts import BOILERPLATE_VERSION, ICF_RETAINED_SHELL_SECTIONS, canonical_study_type, get_path, icf_contract, icf_retained_sections, protocol_contract
from rendering import audit_docx, refresh_toc_from_pdf, template_paths


VERIFY_SCHEMA = "hermes-verification/v1"
RESPONSE_SCHEMA = "hermes-verification-response/v1"
CONTENT_CHECKS = ("substantive", "source_supported", "no_invention", "no_internal_language", "cross_document_consistent")
CROSS_DOCUMENT_CHECKS = ("protocol_number", "study_title", "study_type", "population", "procedures", "risks_benefits")
VISUAL_CHECKS = (
    "clipping", "overlap", "overflow", "orphan_heading", "bad_table_split",
    "blank_page", "footer_collision", "unreadable_text", "duplicate_section",
    "inconsistent_style", "missing_header_footer", "toc_mismatch",
)
TRANSIENT_REVIEW_STATUSES = {"retryable_error", "transient_error", "unavailable", "temporarily_unavailable"}
_MAC_FONT_NAMES: set[str] | None = None
def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict): raise ValueError(f"Expected JSON object: {path}")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()


def renderer(*, environment: Mapping[str, str] | None = None) -> dict[str, Any] | None:
    """Discover an installed renderer and report its honest identity."""
    search_path = (environment or {}).get("PATH") if environment is not None else None
    system = platform.system()
    if system == "Windows":
        try:
            import win32com.client
            word = win32com.client.DispatchEx("Word.Application")
            version = str(word.Version); word.Quit()
            return {"kind": "Microsoft Word", "path": "COM:Word.Application", "version": version, "platform": "Windows"}
        except Exception:
            pass
    if system == "Darwin" and Path("/Applications/Microsoft Word.app").exists():
        return {"kind": "Microsoft Word", "path": "/Applications/Microsoft Word.app", "version": "installed macOS application"}
    for executable in ("libreoffice", "soffice"):
        if path := shutil.which(executable, path=search_path):
            try:
                result = subprocess.run([path, "--version"], text=True, capture_output=True, timeout=20, env=dict(environment) if environment else None)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0:
                return {"kind": "LibreOffice", "path": path, "version": result.stdout.strip(), "platform": system}
    if system == "Darwin" and Path("/Applications/Pages.app").exists():
        return {"kind": "Pages", "path": "/Applications/Pages.app", "version": "installed macOS application"}
    return None


def _template_fonts(path: Path) -> set[str]:
    """Read declared font families without changing the client template."""
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    fonts: set[str] = set()
    with zipfile.ZipFile(path) as package:
        for name in ("word/document.xml", "word/styles.xml", "word/header1.xml", "word/footer1.xml"):
            if name not in package.namelist():
                continue
            root = ET.fromstring(package.read(name))
            for element in root.iter(f"{{{namespace}}}rFonts"):
                for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
                    value = element.get(f"{{{namespace}}}{attribute}")
                    if value:
                        fonts.add(value.strip())
    return fonts


def _font_probe(font: str, *, environment: Mapping[str, str] | None = None) -> tuple[bool, str]:
    global _MAC_FONT_NAMES
    executable = shutil.which("fc-match", path=(environment or {}).get("PATH"))
    if not executable and platform.system() == "Darwin":
        try:
            if _MAC_FONT_NAMES is None:
                result = subprocess.run(["/usr/sbin/system_profiler", "SPFontsDataType", "-json"], text=True, capture_output=True, timeout=10)
                if result.returncode != 0:
                    raise RuntimeError(result.stderr.strip() or "system_profiler failed")
                entries = json.loads(result.stdout).get("SPFontsDataType", [])
                _MAC_FONT_NAMES = {str(item.get("_name", "")).casefold() for item in entries if isinstance(item, Mapping)}
            normalized_font = font.casefold()
            available = any(
                name.removesuffix(".ttf").removesuffix(".otf").removesuffix(".ttc").removesuffix(" bold").removesuffix(" italic").strip() == normalized_font
                for name in _MAC_FONT_NAMES
            )
            return available, "macOS system font inventory"
        except (OSError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
            pass
    if not executable:
        return False, "fontconfig fc-match is not installed; required font availability cannot be verified."
    try:
        result = subprocess.run(
            [executable, "-f", "%{family}", font],
            text=True,
            capture_output=True,
            timeout=5,
            env=dict(environment) if environment else None,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"font probe failed: {exc}"
    families = {part.strip().casefold() for part in result.stdout.split(",") if part.strip()}
    return result.returncode == 0 and font.casefold() in families, result.stdout.strip()


def preflight(
    repo_root: Path,
    reference: Mapping[str, Any],
    *,
    deadline_seconds: float = 30.0,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Verify renderer, fonts, PDF export, and page-image tooling before drafting."""
    started = time.monotonic()
    identity = renderer(environment=environment)
    findings: list[dict[str, Any]] = []
    if identity is None:
        findings.append({"category": "renderer", "field": "renderer", "issue": "No supported Word, LibreOffice, or Pages renderer is installed."})
    protocol_template, icf_template = template_paths(repo_root, reference)
    templates = [path for path in (protocol_template, icf_template) if path is not None]
    required_fonts = sorted({font for path in templates for font in _template_fonts(path)})
    font_results: dict[str, Any] = {}
    if identity is not None:
        for font in required_fonts:
            available, detail = _font_probe(font, environment=environment)
            font_results[font] = {"available": available, "match": detail}
            if not available:
                findings.append({"category": "renderer", "field": f"font:{font}", "issue": f"Required font {font!r} is unavailable or could not be verified: {detail}"})
    smoke: dict[str, Any] = {"status": "not_run"}
    if identity is not None and not findings and time.monotonic() - started < deadline_seconds:
        try:
            with tempfile.TemporaryDirectory(prefix="hermes-renderer-preflight-") as directory:
                root = Path(directory)
                source = root / "preflight.docx"
                document = Document()
                document.add_paragraph("Hermes renderer preflight")
                document.save(source)
                pdf = _render_pdf(source, root, identity, environment=environment, timeout_seconds=max(1.0, deadline_seconds - (time.monotonic() - started)))
                page_dir = root / "pages"
                page_dir.mkdir()
                result = subprocess.run(
                    [shutil.which("pdftoppm", path=(environment or {}).get("PATH")) or "pdftoppm", "-png", "-f", "1", "-singlefile", str(pdf), str(page_dir / "page")],
                    text=True,
                    capture_output=True,
                    timeout=max(1.0, deadline_seconds - (time.monotonic() - started)),
                    env=dict(environment) if environment else None,
                )
                page = page_dir / "page.png"
                if result.returncode or not page.is_file():
                    raise RuntimeError(f"Page-image export failed: {result.stderr or result.stdout}")
                smoke = {"status": "passed", "pdf": "disposable/preflight.pdf", "page_image": "disposable/preflight.png", "pages": len(PdfReader(pdf).pages)}
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            findings.append({"category": "renderer", "field": "preflight", "issue": str(exc)})
            smoke = {"status": "blocked", "issue": str(exc)}
    elif identity is not None and not findings:
        findings.append({"category": "renderer", "field": "preflight", "issue": f"Renderer preflight exceeded its {deadline_seconds:.1f}s deadline."})
    elapsed = time.monotonic() - started
    if elapsed > deadline_seconds:
        findings.append({"category": "renderer", "field": "preflight", "issue": f"Renderer preflight exceeded its {deadline_seconds:.1f}s deadline ({elapsed:.3f}s)."})
    return {"status": "passed" if not findings else "blocked", "renderer": identity, "required_fonts": required_fonts, "fonts": font_results, "smoke": smoke, "deadline_seconds": deadline_seconds, "elapsed_seconds": round(elapsed, 3), "findings": findings}


def _render_pdf(docx: Path, output_dir: Path, identity: Mapping[str, Any], *, environment: Mapping[str, str] | None = None, timeout_seconds: float = 180.0) -> Path:
    if identity["kind"] == "LibreOffice":
        result = subprocess.run([str(identity["path"]), "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(docx)], text=True, capture_output=True, timeout=timeout_seconds, env=dict(environment) if environment else None)
        path = output_dir / f"{docx.stem}.pdf"
        if result.returncode or not path.is_file():
            raise RuntimeError(f"LibreOffice PDF export failed: {result.stderr or result.stdout}")
        return path
    if identity.get("platform") == "Windows":
        return _windows_word_pdf(docx, output_dir)
    return _mac_pdf(docx, output_dir, identity)


def _libreoffice_pdf(docx: Path, output_dir: Path, identity: Mapping[str, Any]) -> Path:
    result = subprocess.run([str(identity["path"]), "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(docx)], text=True, capture_output=True, timeout=180)
    path = output_dir / f"{docx.stem}.pdf"
    if result.returncode or not path.is_file(): raise RuntimeError(f"LibreOffice PDF export failed: {result.stderr or result.stdout}")
    return path


def _mac_pdf(docx: Path, output_dir: Path, identity: Mapping[str, Any]) -> Path:
    app = "Microsoft Word" if identity["kind"] == "Microsoft Word" else "Pages"
    output = output_dir / f"{docx.stem}.pdf"
    if app == "Microsoft Word":
        script = 'on run argv\nset src to POSIX file (item 1 of argv)\nset dst to POSIX file (item 2 of argv)\ntell application "Microsoft Word"\nset d to open src\nsave as d file name dst file format format PDF\nclose d saving no\nend tell\nend run'
    else:
        script = 'on run argv\nset src to POSIX file (item 1 of argv)\nset dst to POSIX file (item 2 of argv)\ntell application "Pages"\nset d to open src\nexport d to dst as PDF\nclose d saving no\nend tell\nend run'
    result = subprocess.run(["osascript", "-e", script, str(docx), str(output)], text=True, capture_output=True, timeout=180)
    if result.returncode or not output.is_file(): raise RuntimeError(f"{app} PDF export failed: {result.stderr or result.stdout}")
    return output


def _windows_word_pdf(docx: Path, output_dir: Path) -> Path:
    import win32com.client
    output = output_dir / f"{docx.stem}.pdf"
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    document = None
    try:
        document = word.Documents.Open(str(docx.resolve()), ReadOnly=True)
        document.ExportAsFixedFormat(str(output.resolve()), 17)
    finally:
        if document is not None:
            document.Close(False)
        word.Quit()
    if not output.is_file(): raise RuntimeError("Microsoft Word PDF export did not produce a file.")
    return output


def _blank_pdf_pages(path: Path) -> list[int]:
    blank: list[int] = []
    for index, page in enumerate(PdfReader(path).pages, 1):
        lines = []
        for line in (page.extract_text() or "").splitlines():
            normalized = line.strip()
            if re.search(r"\bpage\s+\d+\s+of\s+\d+\b", normalized, flags=re.I):
                continue
            if re.fullmatch(r"(?:v(?:ersion)?\s*)?\S*\s*\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}", normalized, flags=re.I):
                continue
            lines.append(normalized)
        if len(re.findall(r"\b\w+\b", "\n".join(lines))) < 3:
            blank.append(index)
    return blank


def render_pages(revision_dir: Path, *, renderer_identity: Mapping[str, Any] | None = None) -> dict[str, Any]:
    identity = dict(renderer_identity) if renderer_identity is not None else renderer()
    if identity is None: return {"status": "blocked", "findings": [{"category": "renderer", "field": "renderer", "issue": "No supported Word, LibreOffice, or Pages renderer is installed."}]}
    render_root = revision_dir / "rendered"; render_root.mkdir(parents=True, exist_ok=True)
    artifacts = []; findings: list[dict[str, Any]] = []
    try:
        for docx in sorted((revision_dir / "candidate").glob("*.docx")):
            if identity["kind"] == "LibreOffice": pdf = _libreoffice_pdf(docx, render_root, identity)
            elif identity.get("platform") == "Windows": pdf = _windows_word_pdf(docx, render_root)
            else: pdf = _mac_pdf(docx, render_root, identity)
            for _ in range(3):
                if not refresh_toc_from_pdf(docx, pdf): break
                pdf.unlink(missing_ok=True)
                if identity["kind"] == "LibreOffice": pdf = _libreoffice_pdf(docx, render_root, identity)
                elif identity.get("platform") == "Windows": pdf = _windows_word_pdf(docx, render_root)
                else: pdf = _mac_pdf(docx, render_root, identity)
            page_dir = render_root / docx.stem; page_dir.mkdir(parents=True, exist_ok=True)
            for stale_page in page_dir.glob("page-*.png"):
                stale_page.unlink()
            prefix = page_dir / "page"
            command = [shutil.which("pdftoppm") or "pdftoppm", "-png", "-r", "130", str(pdf), str(prefix)]
            result = subprocess.run(command, text=True, capture_output=True, timeout=180)
            pages = sorted(page_dir.glob("page-*.png"))
            expected = len(PdfReader(pdf).pages)
            if result.returncode or len(pages) != expected or expected == 0: raise RuntimeError(f"Page rendering failed for {docx.name}: expected {expected}, got {len(pages)}. {result.stderr}")
            for page_number in _blank_pdf_pages(pdf):
                findings.append({
                    "category": "visual",
                    "field": docx.stem,
                    "artifact": docx.stem,
                    "page": page_number,
                    "target_ids": [f"layout:{docx.stem}"],
                    "issue": f"Rendered {docx.stem} contains a textless page at page {page_number}.",
                })
            artifacts.append({"artifact": docx.stem, "docx": docx.relative_to(revision_dir).as_posix(), "docx_sha256": sha256_file(docx), "pdf": pdf.relative_to(revision_dir).as_posix(), "pdf_sha256": sha256_file(pdf), "pages": [{"page": i, "path": page.relative_to(revision_dir).as_posix(), "sha256": sha256_file(page)} for i, page in enumerate(pages, 1)]})
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return {"status": "blocked", "renderer": identity, "findings": [{"category": "renderer", "field": "rendering", "issue": str(exc)}]}
    return {"status": "passed" if not findings else "blocked", "renderer": identity, "artifacts": artifacts, "findings": findings}


def deterministic_content_check(revision_dir: Path, reference: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    branch = canonical_study_type(get_path(reference, "meta.study_type")) or ""
    protocol = revision_dir / "candidate/protocol.docx"
    findings.extend(audit_docx(protocol, required_phrases=[str(get_path(reference, "study.title", ""))]))
    document = Document(protocol)
    visible = "\n".join(p.text for p in document.paragraphs)
    normalized_visible = re.sub(r"\s+", " ", visible).casefold()
    source_visible = json.dumps(reference, ensure_ascii=False).casefold()
    def heading_key(value: str) -> str:
        first_line = next((line for line in value.splitlines() if line.strip()), "")
        normalized = re.sub(r"(?<=\d)\.(?=\s|$)", "", first_line)
        return re.sub(r"\s+", " ", normalized).strip().casefold()

    headings = [heading_key(p.text) for p in document.paragraphs if p.style.name.casefold().startswith("heading") and p.text.strip()]
    sections = protocol_contract(branch)
    for section in sections:
        expected = heading_key(f"{section.number} {section.title}")
        count = headings.count(expected)
        if count != 1:
            findings.append({"category": "content", "field": section.section_id, "target_ids": [section.section_id], "issue": f"Protocol section heading must appear exactly once; found {count}: {section.number} {section.title}"})
    stale_protocol_claims = {
        "an investigator-initiated clinical trial": "title-page",
        "all subjects will be monitored for adverse events": "quality-safety",
        "included on each case report form": "quality-safety",
        "1996 version of the declaration of helsinki": "ethics",
        "approval prior to initiating the study": "ethics",
    }
    for phrase, target in stale_protocol_claims.items():
        if phrase in normalized_visible and phrase not in source_visible:
            findings.append({"category": "content", "field": target, "target_ids": [target], "issue": f"Protocol contains unsupported client-template study language: {phrase}"})

    blocks: list[Paragraph | Table] = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            blocks.append(Paragraph(child, document))
        elif child.tag == qn("w:tbl"):
            blocks.append(Table(child, document))

    def heading_level(paragraph: Paragraph) -> int | None:
        if not paragraph.style.name.casefold().startswith("heading"):
            return None
        match = re.search(r"(\d+)$", paragraph.style.name)
        return int(match.group(1)) if match else 1

    def has_section_content(section: Any) -> bool | None:
        expected = heading_key(f"{section.number} {section.title}")
        target_index = next((
            index for index, block in enumerate(blocks)
            if isinstance(block, Paragraph) and heading_level(block) is not None and heading_key(block.text) == expected
        ), None)
        if target_index is None:
            return None
        target = blocks[target_index]
        assert isinstance(target, Paragraph)
        target_level = heading_level(target) or 1
        for block in blocks[target_index + 1:]:
            if isinstance(block, Paragraph):
                level = heading_level(block)
                if level is not None:
                    if level <= target_level:
                        break
                    continue
                if len(re.findall(r"\b\w+\b", block.text)) >= 3:
                    return True
            elif any(cell.text.strip() for row in block.rows for cell in row.cells):
                return True
        return False

    for section in sections:
        if section.role == "container":
            continue
        populated = has_section_content(section)
        if populated is False:
            findings.append({
                "category": "content",
                "field": section.section_id,
                "target_ids": [section.section_id],
                "issue": f"Protocol section has no substantive content after its heading: {section.number} {section.title}",
            })
    seen: dict[str, str] = {}
    current_section = ""
    heading_to_id = {heading_key(f"{section.number} {section.title}"): section.section_id for section in sections}
    for paragraph in document.paragraphs:
        text = re.sub(r"\s+", " ", paragraph.text).strip()
        if paragraph.style.name.casefold().startswith("heading"):
            current_section = heading_to_id.get(heading_key(paragraph.text), current_section)
            continue
        key = text.casefold()
        if len(text.split()) >= 8 and key in seen and seen[key] != current_section:
            findings.append({"category": "content", "field": current_section or "protocol", "target_ids": sorted({seen[key], current_section}), "issue": f"Exact paragraph is duplicated across protocol sections {seen[key]} and {current_section}."})
        elif len(text.split()) >= 8:
            seen[key] = current_section
    if branch == "Retrospective":
        for field in ("population.inclusion_criteria", "population.exclusion_criteria"):
            value = get_path(reference, field, [])
            items = value if isinstance(value, list) else [value]
            for item in items:
                expected = re.sub(r"\s+", " ", _text(item)).strip().casefold().rstrip(".")
                if expected and expected not in normalized_visible:
                    findings.append({"category": "content", "field": "subjects.eligibility", "target_ids": ["subjects.eligibility"], "issue": f"Retrospective eligibility omits approved source content from {field}."})
        timeline = re.sub(r"\s+", " ", _text(get_path(reference, "study.timeline"))).strip().casefold().rstrip(".")
        if timeline and timeline not in normalized_visible:
            findings.append({"category": "content", "field": "study-procedure.enrollment", "target_ids": ["study-procedure.enrollment"], "issue": "Retrospective study procedure omits the approved study timeline."})
        schedule = get_path(reference, "procedures.visit_schedule_table", []) or []
        visit_names = [item.get("visitName") or item.get("visit") for item in schedule if isinstance(item, Mapping)]
        for visit_name in visit_names:
            expected = re.sub(r"\s+", " ", _text(visit_name)).strip().casefold()
            if expected and expected not in normalized_visible:
                findings.append({"category": "content", "field": "study-procedure.enrollment", "target_ids": ["study-procedure.enrollment"], "issue": f"Retrospective study procedure omits approved visit {visit_name}."})
    if branch != "Retrospective":
        icf = revision_dir / "candidate/icf.docx"
        findings.extend(audit_docx(icf, required_phrases=[str(get_path(reference, "study.title", ""))]))
        icf_document = Document(icf)
        icf_visible = re.sub(r"\s+", " ", " ".join(paragraph.text for paragraph in icf_document.paragraphs)).casefold()
        icf_template = str(get_path(reference, "meta.icf_template", "Advarra"))
        for section_id, title in icf_retained_sections(branch, icf_template):
            if title.casefold() not in icf_visible:
                findings.append({
                    "category": "content",
                    "field": section_id,
                    "target_ids": ["layout:icf"],
                    "issue": f"Required retained ICF section is missing from the client shell: {title}",
                })
        signature_marker = "signature of participant"
        if signature_marker not in icf_visible:
            findings.append({
                "category": "content",
                "field": "icf.signature-block",
                "target_ids": ["layout:icf"],
                "issue": "Required participant signature block is missing from the ICF.",
            })
        stale_icf_claims = {
            "eye tests and procedures": "icf",
            "routine cataract surgery": "icf",
            "company that makes the handpiece": "icf",
            "no additional side effects or risks expected": "icf",
            "not to be used for participant enrollment": "icf.study-purpose",
            "advarra institutional review board": "icf.privacy",
            "all charges for medical care": "icf.injury",
            "insurance company": "icf.injury",
        }
        for phrase, target in stale_icf_claims.items():
            if phrase in icf_visible and phrase not in source_visible:
                findings.append({
                    "category": "content",
                    "field": target,
                    "target_ids": [target],
                    "issue": f"ICF contains example-study prose that is not supported by the approved source: {phrase}",
                })
        if _text(get_path(reference, "regulatory.prs.study_type")).casefold() == "observational" and "clinical trial" in icf_visible and "clinical trial" not in source_visible:
            findings.append({"category": "content", "field": "icf.study-purpose", "target_ids": ["icf.study-purpose"], "issue": "Observational ICF retains interventional clinical-trial language."})
        minimum_days = _text(get_path(reference, "procedures.minimum_days_before_screening_without_participation"))
        if minimum_days:
            day_pattern = re.compile(rf"\b{re.escape(minimum_days)}\s*[- ]?\s*days?\b", re.I)
            if not day_pattern.search(visible):
                findings.append({"category": "content", "field": "subjects.inclusion", "target_ids": ["subjects.inclusion"], "issue": "Protocol omits the approved minimum interval without participation in another study before screening."})
            if not day_pattern.search(icf_visible):
                findings.append({"category": "content", "field": "icf.procedures", "target_ids": ["icf.procedures"], "issue": "ICF omits the approved minimum interval without participation in another study before screening."})
            xml_path = revision_dir / "candidate/study.xml"
            if xml_path.is_file() and not day_pattern.search(xml_path.read_text(encoding="utf-8")):
                findings.append({"category": "content", "field": "prs.eligibility", "target_ids": ["layout:xml"], "issue": "PRS XML omits the approved minimum interval without participation in another study before screening."})
        consent_to_sign = any(phrase in icf_visible for phrase in (
            "should not sign",
            "if you would like to participate, you will be asked to sign",
            "if you agree to participate, you will be asked to sign",
        ))
        if not consent_to_sign:
            findings.append({"category": "content", "field": "icf.consent", "target_ids": ["layout:icf"], "issue": "ICF lacks an explicit instruction not to sign when the participant does not agree."})
    return findings


def create_verification_requests(revision_dir: Path, reference: Mapping[str, Any], render_report: Mapping[str, Any]) -> list[Path]:
    requests = revision_dir / "hermes/verification-requests"; responses = revision_dir / "hermes/verification-responses"
    content_files = []
    for path in sorted((revision_dir / "candidate").glob("*")):
        if path.is_file(): content_files.append({"path": path.relative_to(revision_dir).as_posix(), "sha256": sha256_file(path)})
    branch = canonical_study_type(get_path(reference, "meta.study_type")) or ""
    sections = [{"artifact": "protocol", "section_id": section.section_id, "number": section.number, "title": section.title} for section in protocol_contract(branch)]
    if branch != "Retrospective":
        choice = str(get_path(reference, "meta.icf_template", "Advarra"))
        sections.extend({"artifact": "icf", "section_id": section.section_id, "number": section.number, "title": section.title} for section in icf_contract(branch, choice))
        sections.extend({"artifact": "icf", "section_id": section_id, "number": "", "title": title} for section_id, title in icf_retained_sections(branch, choice))
    boilerplate_path = Path(__file__).resolve().parents[1] / "references/fixed-clinical-boilerplate.json"
    authorized_boilerplate = _json(boilerplate_path)
    if authorized_boilerplate.get("version") != BOILERPLATE_VERSION:
        raise ValueError("Verification boilerplate does not match the content contract.")
    payloads = [
        {"schema_version": VERIFY_SCHEMA, "request_id": f"{revision_dir.name}.verify.content", "task": "clinical_content_verification", "revision_id": revision_dir.name, "artifacts": content_files, "approved_source": reference, "authorized_boilerplate": authorized_boilerplate, "sections": sections, "checks": list(CONTENT_CHECKS), "cross_document_checks": list(CROSS_DOCUMENT_CHECKS), "instructions": "Assess every listed section against every content check and assess every cross-document check. Findings must include target_ids for affected section IDs. Treat exact authorized Fixed Clinical Boilerplate as approved non-study-specific content, not invention. Do not fail optional fields, dates, instruments, scoring rules, denominators, or policies that are absent from the approved source; instead fail only an unsupported affirmative claim or an omission of supplied material evidence. A document-control date may default from approval, while an unknown version must remain blank and must not be failed merely for being unknown.", "response_path": f"hermes/verification-responses/{revision_dir.name}.verify.content.json"},
        {"schema_version": VERIFY_SCHEMA, "request_id": f"{revision_dir.name}.verify.visual", "task": "rendered_page_visual_verification", "revision_id": revision_dir.name, "renderer": render_report.get("renderer"), "artifacts": render_report.get("artifacts", []), "checks": list(VISUAL_CHECKS), "instructions": "Inspect every supplied page image. Do not infer pass from file existence or document text.", "response_path": f"hermes/verification-responses/{revision_dir.name}.verify.visual.json"},
    ]
    for payload in payloads:
        payload["request_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    expected = {payload["request_id"]: payload for payload in payloads}
    existing_paths = sorted(requests.glob("*.json"))
    existing = {}
    for path in existing_paths:
        try:
            item = _json(path); existing[item.get("request_id")] = (path, item)
        except (OSError, ValueError, json.JSONDecodeError):
            existing[path.name] = (path, {})
    current = set(existing) == set(expected) and all(existing[key][1].get("request_sha256") == value["request_sha256"] for key, value in expected.items())
    if not current:
        for path, request in existing.values():
            response_path = request.get("response_path")
            if response_path:
                (revision_dir / str(response_path)).unlink(missing_ok=True)
            path.unlink(missing_ok=True)
    result = []
    for payload in payloads:
        path = requests / f"{payload['request_id']}.json"; _write(path, payload); result.append(path)
    return result


def pending_verifications(revision_dir: Path) -> list[Path]:
    pending = []
    for path in sorted((revision_dir / "hermes/verification-requests").glob("*.json")):
        request = _json(path)
        if not (revision_dir / request["response_path"]).is_file(): pending.append(path)
    return pending


def validate_verifications(revision_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    findings: list[dict[str, Any]] = []; evidence: dict[str, Any] = {}
    for request_path in sorted((revision_dir / "hermes/verification-requests").glob("*.json")):
        request = _json(request_path); response_path = revision_dir / request["response_path"]
        if not response_path.is_file():
            findings.append({"category": "verification", "field": request["task"], "issue": "Independent Hermes verification response is missing."}); continue
        try: response = _json(response_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            findings.append({"category": "verification", "field": request["task"], "issue": f"Invalid verification response: {exc}"}); continue
        for key, expected in (("schema_version", RESPONSE_SCHEMA), ("request_id", request["request_id"]), ("request_sha256", request["request_sha256"]), ("task", request["task"])):
            if response.get(key) != expected: findings.append({"category": "verification", "field": key, "issue": f"Verification response binding mismatch for {key}."})
        producer = response.get("producer") if isinstance(response.get("producer"), Mapping) else {}
        if not _text(producer.get("model_id")): findings.append({"category": "verification", "field": "producer.model_id", "issue": "Verifier identity is missing."})
        error = response.get("error") if isinstance(response.get("error"), Mapping) else {}
        error_type = _text(error.get("type")).casefold()
        transient = str(response.get("status") or "").casefold() in TRANSIENT_REVIEW_STATUSES or error_type in {
            "api_unavailable", "connection_error", "rate_limit", "timeout", "service_unavailable"
        }
        if transient:
            target = "verification:visual" if request["task"] == "rendered_page_visual_verification" else "verification:content"
            findings.append({
                "category": "reviewer-transient",
                "field": request["task"],
                "target_ids": [target],
                "issue": _text(error.get("message")) or "Independent Hermes verifier reported a transient API failure.",
            })
            evidence[request["task"]] = {"request": request_path.relative_to(revision_dir).as_posix(), "request_sha256": sha256_file(request_path), "response": response_path.relative_to(revision_dir).as_posix(), "response_sha256": sha256_file(response_path), "producer": producer, "status": "transient"}
            continue
        issues = response.get("findings") if isinstance(response.get("findings"), list) else []
        if response.get("status") != "passed" or issues:
            for item in issues or [{"issue": "Verifier did not pass the artifact."}]:
                source = item if isinstance(item, Mapping) else {"issue": item}
                category = "visual" if request["task"] == "rendered_page_visual_verification" else "verification"
                finding = {"category": category, "field": request["task"], "issue": _text(source.get("issue"))}
                for key in ("target_ids", "artifact", "page", "check"):
                    if key in source: finding[key] = source[key]
                if category == "visual":
                    finding["target_ids"] = [f"layout:{source.get('artifact') or 'documents'}"]
                elif not finding.get("target_ids"):
                    finding["target_ids"] = ["verification:content"]
                findings.append(finding)
        for artifact in request.get("artifacts", []):
            if request["task"] == "clinical_content_verification":
                path = revision_dir / str(artifact.get("path"))
                if not path.is_file() or sha256_file(path) != artifact.get("sha256"):
                    findings.append({"category": "verification", "field": request["task"], "issue": f"Verification request is stale for {artifact.get('path')}."})
            else:
                for key in ("docx", "pdf"):
                    path = revision_dir / str(artifact.get(key))
                    if not path.is_file() or sha256_file(path) != artifact.get(f"{key}_sha256"):
                        findings.append({"category": "visual", "field": artifact.get("artifact", key), "target_ids": [f"layout:{artifact.get('artifact', key)}"], "issue": f"Visual verification request is stale for {artifact.get(key)}."})
                for page in artifact.get("pages", []):
                    path = revision_dir / str(page.get("path"))
                    if not path.is_file() or sha256_file(path) != page.get("sha256"):
                        findings.append({"category": "visual", "field": artifact.get("artifact", "page"), "target_ids": [f"layout:{artifact.get('artifact', 'page')}"], "issue": f"Visual verification request is stale for {page.get('path')}."})
        if request["task"] == "clinical_content_verification":
            expected_sections = {(item["artifact"], item["section_id"]) for item in request.get("sections", [])}
            valid_section_rows = [item for item in response.get("section_assessments", []) if isinstance(item, Mapping) and item.get("status") == "passed" and set(item.get("checks", [])) == set(CONTENT_CHECKS)]
            assessed_sections = {(item.get("artifact"), item.get("section_id")) for item in valid_section_rows}
            if expected_sections != assessed_sections or len(valid_section_rows) != len(expected_sections):
                findings.append({"category": "verification", "field": request["task"], "issue": f"Every contracted section and content check must be explicitly assessed; expected {len(expected_sections)}, accepted {len(assessed_sections)}."})
            expected_cross = set(request.get("cross_document_checks", []))
            valid_cross_rows = [item for item in response.get("cross_document_assessments", []) if isinstance(item, Mapping) and item.get("status") == "passed"]
            assessed_cross = {item.get("check") for item in valid_cross_rows}
            if expected_cross != assessed_cross or len(valid_cross_rows) != len(expected_cross):
                findings.append({"category": "verification", "field": request["task"], "issue": f"Every cross-document check must be explicitly assessed; expected {len(expected_cross)}, accepted {len(assessed_cross)}."})
        if request["task"] == "rendered_page_visual_verification":
            expected_pages = {(a["artifact"], p["page"], p["sha256"]) for a in request.get("artifacts", []) for p in a.get("pages", [])}
            valid_page_rows = [p for p in response.get("page_assessments", []) if isinstance(p, Mapping) and p.get("status") == "passed" and set(p.get("checks", [])) == set(VISUAL_CHECKS)]
            assessed = {(p.get("artifact"), p.get("page"), p.get("sha256")) for p in valid_page_rows}
            if expected_pages != assessed or len(valid_page_rows) != len(expected_pages): findings.append({"category": "visual", "field": "page_assessments", "target_ids": ["verification:visual"], "issue": f"Every rendered page and every visual check must be explicitly assessed; expected {len(expected_pages)}, accepted {len(assessed)}."})
        evidence[request["task"]] = {"request": request_path.relative_to(revision_dir).as_posix(), "request_sha256": sha256_file(request_path), "response": response_path.relative_to(revision_dir).as_posix(), "response_sha256": sha256_file(response_path), "producer": producer}
    return findings, evidence


def quality_report(revision_dir: Path, reference: Mapping[str, Any], render_report: Mapping[str, Any], xml_report: Mapping[str, Any] | None) -> dict[str, Any]:
    findings = deterministic_content_check(revision_dir, reference)
    findings.extend(render_report.get("findings", []))
    if xml_report: findings.extend(xml_report.get("findings", []))
    verification_findings, evidence = validate_verifications(revision_dir); findings.extend(verification_findings)
    return {"status": "passed" if not findings else "blocked", "findings": findings, "renderer": render_report.get("renderer"), "verification_evidence": evidence}


__all__ = ["CONTENT_CHECKS", "CROSS_DOCUMENT_CHECKS", "ICF_RETAINED_SHELL_SECTIONS", "RESPONSE_SCHEMA", "VISUAL_CHECKS", "create_verification_requests", "deterministic_content_check", "pending_verifications", "preflight", "quality_report", "render_pages", "renderer", "sha256_file", "validate_verifications"]
