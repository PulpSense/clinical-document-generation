"""Fail-closed content, XML, renderer, and page-visual quality gates."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
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

from contracts import APPROVED_PACKAGED_FONT_FALLBACKS, BOILERPLATE_VERSION, BUNDLED_FONT_FILES, ICF_RETAINED_SHELL_SECTIONS, RECOVERY_POLICIES, batch_plan, canonical_study_type, contracted_template_bundle, get_path, icf_contract, icf_retained_sections, protocol_contract, recovery_finding
from rendering import audit_docx, refresh_toc_from_pdf, template_paths


VERIFY_SCHEMA = "hermes-verification/v1"
RESPONSE_SCHEMA = "hermes-verification-response/v1"
CONTENT_CHECKS = ("substantive", "source_supported", "no_invention", "no_internal_language", "cross_document_consistent")
CROSS_DOCUMENT_CHECKS = ("protocol_number", "study_title", "study_type", "population", "procedures", "risks_benefits")
VISUAL_CHECKS = (
    "clipping", "overlap", "overflow", "orphan_heading", "bad_table_split",
    "blank_page", "footer_collision", "unreadable_text", "duplicate_section",
    "inconsistent_style", "missing_header_footer", "toc_mismatch",
    "excessive_whitespace", "artificial_pagination",
)
TRANSIENT_REVIEW_STATUSES = {"retryable_error", "transient_error", "unavailable", "temporarily_unavailable"}
_MAC_FONT_NAMES: set[str] | None = None
_WINDOWS_FONT_NAMES: set[str] | None = None

SYMBOL_FONT_FALLBACKS = (
    "Apple Symbols",
    "Segoe UI Symbol",
    "Arial Unicode MS",
    "Arial Unicode",
    "Symbol",
    "DejaVu Sans",
    "Noto Sans",
    "Arial",
    "Helvetica",
    "Liberation Sans",
)
SANS_FONT_FALLBACKS = (
    "Arial",
    "Helvetica",
    "Aptos",
    "Calibri",
    "Liberation Sans",
    "DejaVu Sans",
    "Noto Sans",
    "Verdana",
)
SERIF_FONT_FALLBACKS = (
    "Times New Roman",
    "Times",
    "Liberation Serif",
    "DejaVu Serif",
    "Georgia",
    "Cambria",
    "Noto Serif",
)
MONOSPACE_FONT_FALLBACKS = (
    "Courier New",
    "Menlo",
    "Consolas",
    "Liberation Mono",
    "DejaVu Sans Mono",
    "Noto Sans Mono",
)


def verification_request_sha256(request: Mapping[str, Any]) -> str:
    unsigned = dict(request)
    unsigned.pop("request_sha256", None)
    return hashlib.sha256(json.dumps(unsigned, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def verification_request_hash_valid(request: Mapping[str, Any]) -> bool:
    supplied = str(request.get("request_sha256") or "")
    return bool(supplied) and supplied == verification_request_sha256(request)

PAGE_RENDERER_BACKENDS = ("pypdfium2",)


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


def _content_sha256(path: Path) -> str:
    """Hash visible DOCX text independently from its presentation properties."""
    if path.suffix.casefold() != ".docx":
        return sha256_file(path)
    try:
        stories: list[tuple[str, list[str]]] = []
        with zipfile.ZipFile(path) as package:
            for name in sorted(package.namelist()):
                if not name.startswith("word/") or not name.endswith(".xml"):
                    continue
                root = ET.fromstring(package.read(name))
                values = [
                    str(element.text or "")
                    for element in root.iter()
                    if ET.QName(element).localname in {"t", "instrText"}
                ]
                if values:
                    stories.append((name, values))
        payload = json.dumps(stories, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
    except (OSError, ET.XMLSyntaxError, zipfile.BadZipFile):
        return sha256_file(path)


def _executable_candidates(
    names: Iterable[str],
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Iterable[tuple[Path, str]]:
    """Yield PATH and common installation candidates without changing the host."""
    search_path = (environment or {}).get("PATH") if environment is not None else None
    yielded: set[str] = set()
    for name in names:
        if path := shutil.which(name, path=search_path):
            resolved = str(Path(path).resolve())
            yielded.add(resolved.casefold())
            yield Path(resolved), "PATH"

    user_home = (home or Path.home()).expanduser()
    directories = [
        user_home / ".hermes/bin",
        Path(sys.executable).resolve().parent,
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
        Path("/usr/bin"),
        Path("/bin"),
    ]
    sources = {
        str(user_home / ".hermes/bin"): "Hermes bundled tools",
        str(Path(sys.executable).resolve().parent): "Python environment",
    }
    bundled_tools_root = user_home / ".cache/codex-runtimes"
    if bundled_tools_root.is_dir():
        for pattern in ("*/dependencies/bin/override", "*/dependencies/bin/fallback"):
            for directory in sorted(bundled_tools_root.glob(pattern)):
                directories.append(directory)
                sources[str(directory)] = "bundled workspace tools"
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        if value := (environment or os.environ).get(variable):
            base = Path(value)
            directories.extend((base / "LibreOffice/program", base / "ImageMagick", base / "chocolatey/bin"))
            directories.extend(sorted(base.glob("ImageMagick-*")))
            directories.extend(sorted(base.glob("gs/gs*/bin")))

    for directory in directories:
        for name in names:
            candidates = (directory / name, directory / f"{name}.exe")
            for candidate in candidates:
                if not candidate.is_file() or not os.access(candidate, os.X_OK):
                    continue
                resolved = str(candidate.resolve())
                key = resolved.casefold()
                if key in yielded:
                    continue
                yielded.add(key)
                yield Path(resolved), sources.get(str(directory), "common installation path")


def page_renderers(
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
    skill_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Return the one release-owned PDFium page renderer, if provisioned."""
    del environment, home
    if skill_root is None:
        return []
    runtime_root = Path(skill_root).resolve() / "runtime"
    runtime_python = runtime_root / "python"
    identity_path = runtime_root / "PDF-RENDERER.json"
    if not (
        identity_path.is_file()
        and (runtime_python / "pypdfium2/__init__.py").is_file()
        and (runtime_python / "pypdfium2_raw/__init__.py").is_file()
    ):
        return []
    try:
        recorded = _json(identity_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    if recorded.get("kind") != "pypdfium2":
        return []
    return [{
        "kind": "pypdfium2",
        "path": "python:pypdfium2",
        "module": "pypdfium2",
        "python_path": str(runtime_python),
        "version": str(recorded.get("version") or ""),
        "source": "release-owned runtime",
        "wheel": str(recorded.get("wheel") or ""),
        "wheel_sha256": str(recorded.get("wheel_sha256") or ""),
    }]


def page_renderer(
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
    skill_root: Path | None = None,
) -> dict[str, Any] | None:
    """Return the preferred installed PDF page renderer."""
    identities = page_renderers(environment=environment, home=home, skill_root=skill_root)
    return identities[0] if identities else None


def _ordered_page_images(output_dir: Path) -> list[Path]:
    def key(path: Path) -> tuple[int, str]:
        match = re.search(r"(\d+)(?=\.png$)", path.name)
        return (int(match.group(1)) if match else -1, path.name)
    return sorted(output_dir.glob("page*.png"), key=key)


def rasterize_pdf(
    pdf: Path,
    output_dir: Path,
    identity: Mapping[str, Any],
    *,
    first_page_only: bool = False,
    dpi: int = 130,
    timeout_seconds: float = 180.0,
    environment: Mapping[str, str] | None = None,
) -> list[Path]:
    """Render PDF pages and normalize every backend to deterministic page-N names."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("page*.png"):
        stale.unlink()
    kind = str(identity["kind"])
    path = str(identity["path"])
    prefix = output_dir / "page"
    command: list[str] | None = None
    if kind == "pypdfium2":
        module_name = str(identity.get("module") or "pypdfium2")
        python_path = str(identity.get("python_path") or "")
        inserted = False
        previous_modules: dict[str, Any] = {}
        if python_path and python_path not in sys.path:
            sys.path.insert(0, python_path)
            inserted = True
        module_roots = ("pypdfium2", "pypdfium2_raw", "pypdfium2_cfg")
        if python_path:
            for name in list(sys.modules):
                if any(name == root or name.startswith(root + ".") for root in module_roots):
                    previous_modules[name] = sys.modules.pop(name)
        document = None
        try:
            pdfium = importlib.import_module(module_name)
            if python_path:
                module_file = Path(str(getattr(pdfium, "__file__", ""))).resolve()
                try:
                    module_file.relative_to(Path(python_path).resolve())
                except ValueError as exc:
                    raise RuntimeError(f"pypdfium2 resolved outside the release-owned runtime: {module_file}") from exc
            document = pdfium.PdfDocument(str(pdf))
            count = min(len(document), 1) if first_page_only else len(document)
            for index in range(count):
                page = document[index]
                bitmap = page.render(scale=dpi / 72.0)
                try:
                    bitmap.to_pil().save(output_dir / f"page-{index + 1}.png")
                finally:
                    bitmap.close()
                    page.close()
        except ImportError as exc:
            raise RuntimeError(f"The release-owned pypdfium2 page renderer is unavailable: {exc}") from exc
        finally:
            if document is not None:
                document.close()
            if python_path:
                for name in list(sys.modules):
                    if any(name == root or name.startswith(root + ".") for root in module_roots):
                        sys.modules.pop(name, None)
                sys.modules.update(previous_modules)
            if inserted:
                sys.path.remove(python_path)
    else:
        raise RuntimeError(f"Unsupported page renderer: {kind}")

    if command is not None:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            env=dict(environment) if environment else None,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"{kind} page-image export failed: {detail}")

    pages = _ordered_page_images(output_dir)
    if not pages:
        raise RuntimeError(f"{kind} page-image export produced no PNG pages.")
    temporary = []
    for index, page in enumerate(pages, 1):
        target = output_dir / f".normalized-{index}.png"
        page.replace(target)
        temporary.append(target)
    normalized = []
    for index, page in enumerate(temporary, 1):
        target = output_dir / ("page.png" if first_page_only else f"page-{index}.png")
        page.replace(target)
        normalized.append(target)
    return normalized


def renderers(
    *,
    environment: Mapping[str, str] | None = None,
    skill_root: Path | None = None,
    deadline_monotonic: float | None = None,
    clock: Any = time.monotonic,
) -> list[dict[str, Any]]:
    """List usable DOCX renderers in governed fidelity/fallback order."""
    search_path = (environment or {}).get("PATH") if environment is not None else None
    system = platform.system()
    identities: list[dict[str, Any]] = []
    yielded: set[str] = set()

    def append(identity: dict[str, Any]) -> None:
        key = str(identity.get("path", "")).casefold()
        if key and key not in yielded:
            yielded.add(key)
            identities.append(identity)

    def probe_timeout(cap: float = 20.0) -> float | None:
        if deadline_monotonic is None:
            return cap
        remaining = deadline_monotonic - clock()
        return min(cap, remaining) if remaining > 0 else None

    if system == "Windows":
        try:
            if importlib.util.find_spec("win32com.client") is not None:
                append({"kind": "Microsoft Word", "path": "COM:Word.Application", "version": "installed COM application", "platform": "Windows", "source": "host application"})
        except (ImportError, ValueError):
            pass
    if system == "Darwin" and Path("/Applications/Microsoft Word.app").exists():
        append({"kind": "Microsoft Word", "path": "/Applications/Microsoft Word.app", "version": "installed macOS application", "platform": "Darwin", "source": "host application"})
    office_candidates = list(_executable_candidates(("libreoffice", "soffice"), environment=environment))
    if system == "Darwin":
        office_candidates.append((Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"), "macOS application"))
    for candidate, source in office_candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            path = str(candidate)
            timeout = probe_timeout()
            if timeout is None:
                break
            try:
                result = subprocess.run([path, "--version"], text=True, capture_output=True, timeout=timeout, env=dict(environment) if environment else None)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0:
                append({"kind": "LibreOffice", "path": path, "version": result.stdout.strip(), "platform": system, "source": source})
    if system == "Darwin" and Path("/Applications/Pages.app").exists():
        append({"kind": "Pages", "path": "/Applications/Pages.app", "version": "installed macOS application", "platform": "Darwin", "source": "host application"})

    root = (skill_root or Path(__file__).resolve().parents[1]).resolve()
    bundled_patterns = (
        "runtime/**/Contents/MacOS/soffice",
        "runtime/**/program/soffice.exe",
        "runtime/**/program/soffice",
        "runtime/**/soffice",
    )
    for pattern in bundled_patterns:
        for candidate in sorted(root.glob(pattern)):
            if not candidate.is_file() or not os.access(candidate, os.X_OK):
                continue
            timeout = probe_timeout()
            if timeout is None:
                return identities
            try:
                result = subprocess.run([str(candidate), "--version"], text=True, capture_output=True, timeout=timeout, env=dict(environment) if environment else None)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0:
                append({
                    "kind": "LibreOffice",
                    "path": str(candidate.resolve()),
                    "version": result.stdout.strip(),
                    "platform": system,
                    "source": "verified fallback stack",
                })
    return identities


def renderer(
    *,
    environment: Mapping[str, str] | None = None,
    skill_root: Path | None = None,
) -> dict[str, Any] | None:
    """Return the preferred renderer from the governed fallback ladder."""
    identities = renderers(environment=environment, skill_root=skill_root)
    return identities[0] if identities else None


def _template_fonts(path: Path) -> set[str]:
    """Return font families that can render visible text in the DOCX stories.

    Word stores fonts for dormant styles and alternate writing systems alongside
    the fonts used by visible runs.  Requiring every declaration makes renderer
    preflight depend on fonts that cannot affect an English document.  Resolve
    each visible run through its run, character-style, paragraph-style, and
    document-default hierarchy instead.
    """
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ns = {"w": namespace}
    attr = lambda name: f"{{{namespace}}}{name}"
    fonts: set[str] = set()

    def font_values(element: ET._Element | None) -> dict[str, str]:
        if element is None:
            return {}
        node = element.find("w:rPr/w:rFonts", ns) if element.tag != attr("rPr") else element.find("w:rFonts", ns)
        if node is None:
            return {}
        return {
            key: value.strip()
            for key in ("ascii", "hAnsi", "eastAsia", "cs")
            if (value := node.get(attr(key))) and value.strip()
        }

    def scripts(text: str) -> set[str]:
        required: set[str] = set()
        for character in text:
            codepoint = ord(character)
            if character.isspace() or character.isascii():
                required.add("ascii")
            elif (
                0x3040 <= codepoint <= 0x30FF
                or 0x3400 <= codepoint <= 0x9FFF
                or 0xAC00 <= codepoint <= 0xD7AF
                or 0xF900 <= codepoint <= 0xFAFF
            ):
                required.add("eastAsia")
            elif (
                0x0590 <= codepoint <= 0x08FF
                or 0x0900 <= codepoint <= 0x0DFF
                or 0xFB1D <= codepoint <= 0xFEFC
            ):
                required.add("cs")
            else:
                required.add("hAnsi")
        return required or {"ascii"}

    with zipfile.ZipFile(path) as package:
        styles: dict[str, tuple[str | None, dict[str, str]]] = {}
        defaults: dict[str, str] = {}
        if "word/styles.xml" in package.namelist():
            styles_root = ET.fromstring(package.read("word/styles.xml"))
            defaults = font_values(styles_root.find("w:docDefaults/w:rPrDefault/w:rPr", ns))
            for style in styles_root.findall("w:style", ns):
                style_id = style.get(attr("styleId"))
                if not style_id:
                    continue
                based_on = style.find("w:basedOn", ns)
                styles[style_id] = (
                    based_on.get(attr("val")) if based_on is not None else None,
                    font_values(style),
                )

        def style_fonts(style_id: str | None) -> dict[str, str]:
            resolved: dict[str, str] = {}
            seen: set[str] = set()
            while style_id and style_id not in seen:
                seen.add(style_id)
                based_on, declared = styles.get(style_id, (None, {}))
                for key, value in declared.items():
                    resolved.setdefault(key, value)
                style_id = based_on
            return resolved

        story_names = [
            name for name in package.namelist()
            if name == "word/document.xml"
            or re.fullmatch(r"word/(?:header|footer)\d+\.xml", name)
            or name in {"word/footnotes.xml", "word/endnotes.xml", "word/comments.xml"}
        ]
        for name in story_names:
            root = ET.fromstring(package.read(name))
            for run in root.iter(attr("r")):
                text = "".join(node.text or "" for node in run.findall("w:t", ns))
                symbols = run.findall("w:sym", ns)
                if not text.strip() and not symbols:
                    continue
                for symbol in symbols:
                    if value := symbol.get(attr("font")):
                        fonts.add(value.strip())

                direct = font_values(run.find("w:rPr", ns))
                run_style = run.find("w:rPr/w:rStyle", ns)
                character = style_fonts(run_style.get(attr("val")) if run_style is not None else None)
                paragraph = run.getparent()
                while paragraph is not None and paragraph.tag != attr("p"):
                    paragraph = paragraph.getparent()
                paragraph_style = paragraph.find("w:pPr/w:pStyle", ns) if paragraph is not None else None
                inherited = style_fonts(paragraph_style.get(attr("val")) if paragraph_style is not None else None)
                sources = (direct, character, inherited, defaults)
                for script in scripts(text):
                    fallbacks = {
                        "ascii": ("ascii", "hAnsi"),
                        "hAnsi": ("hAnsi", "ascii"),
                        "eastAsia": ("eastAsia", "hAnsi", "ascii"),
                        "cs": ("cs", "hAnsi", "ascii"),
                    }[script]
                    selected = next(
                        (source[key] for source in sources for key in fallbacks if key in source),
                        None,
                    )
                    if selected:
                        fonts.add(selected)
    return fonts


def _font_probe(
    font: str,
    *,
    environment: Mapping[str, str] | None = None,
    timeout_seconds: float = 10.0,
) -> tuple[bool | None, str]:
    global _MAC_FONT_NAMES, _WINDOWS_FONT_NAMES
    executable = shutil.which("fc-match", path=(environment or {}).get("PATH"))
    if not executable and platform.system() == "Darwin":
        try:
            if _MAC_FONT_NAMES is None:
                result = subprocess.run(["/usr/sbin/system_profiler", "SPFontsDataType", "-json"], text=True, capture_output=True, timeout=max(0.001, min(10.0, timeout_seconds)))
                if result.returncode != 0:
                    raise RuntimeError(result.stderr.strip() or "system_profiler failed")
                entries = json.loads(result.stdout).get("SPFontsDataType", [])
                _MAC_FONT_NAMES = set()
                for item in entries:
                    if not isinstance(item, Mapping):
                        continue
                    _MAC_FONT_NAMES.add(str(item.get("_name", "")).casefold())
                    for face in item.get("typefaces", []):
                        if not isinstance(face, Mapping):
                            continue
                        for key in ("_name", "family", "fullname"):
                            if value := str(face.get(key, "")).strip():
                                _MAC_FONT_NAMES.add(value.casefold())
            normalized_font = font.casefold()
            available = any(
                name.removesuffix(".ttf").removesuffix(".otf").removesuffix(".ttc").removesuffix(" bold").removesuffix(" italic").strip() == normalized_font
                for name in _MAC_FONT_NAMES
            )
            return available, "macOS system font inventory"
        except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
            pass
    if not executable and platform.system() == "Windows":
        try:
            if _WINDOWS_FONT_NAMES is None:
                import winreg
                _WINDOWS_FONT_NAMES = set()
                key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
                for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        with winreg.OpenKey(hive, key_path) as key:
                            for index in range(winreg.QueryInfoKey(key)[1]):
                                name, filename, _kind = winreg.EnumValue(key, index)
                                _WINDOWS_FONT_NAMES.add(re.sub(r"\s*\([^)]*\)\s*$", "", str(name)).casefold())
                                _WINDOWS_FONT_NAMES.add(Path(str(filename)).stem.casefold())
                    except OSError:
                        continue
            normalized_font = font.casefold()
            return normalized_font in _WINDOWS_FONT_NAMES, "Windows system font inventory"
        except (ImportError, OSError):
            pass
    if not executable:
        return None, "font inventory is unavailable; availability will be decided by render evidence."
    try:
        result = subprocess.run(
            [executable, "-f", "%{family}", font],
            text=True,
            capture_output=True,
            timeout=max(0.001, min(5.0, timeout_seconds)),
            env=dict(environment) if environment else None,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"font probe unavailable: {exc}"
    families = {part.strip().casefold() for part in result.stdout.split(",") if part.strip()}
    return result.returncode == 0 and font.casefold() in families, result.stdout.strip()


def _bundled_font_path(
    repo_root: Path,
    font: str,
    approved_font_plan: Mapping[str, Any] | None = None,
) -> Path | None:
    families = (
        approved_font_plan.get("packaged_families", {})
        if isinstance(approved_font_plan, Mapping)
        else BUNDLED_FONT_FILES
    )
    filename = families.get(font)
    if not filename:
        return None
    assets = (
        approved_font_plan.get("packaged_font_assets", {})
        if isinstance(approved_font_plan, Mapping)
        else {}
    )
    relative = next(
        (str(path) for path in assets if Path(str(path)).name == filename),
        f"assets/fallback-fonts/{filename}",
    )
    path = repo_root / relative
    return path if path.is_file() else None


def _runtime_environment(
    repo_root: Path,
    environment: Mapping[str, str] | None,
    contracted_bundle: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    runtime = dict(environment or os.environ)
    approved_font_plan = contracted_bundle.get("approved_font_plan", {}) if isinstance(contracted_bundle, Mapping) else {}
    asset_paths = approved_font_plan.get("packaged_font_assets", {}) if isinstance(approved_font_plan, Mapping) else {}
    font_dirs = sorted({(repo_root / str(relative)).parent for relative in asset_paths})
    if not font_dirs:
        font_dirs = [repo_root / "assets/fallback-fonts"]
    available_dirs = [path for path in font_dirs if path.is_dir()]
    if available_dirs:
        existing = runtime.get("SAL_FONTPATH", "")
        runtime["SAL_FONTPATH"] = os.pathsep.join([
            *(str(path) for path in available_dirs),
            *([existing] if existing else []),
        ])
    return runtime


def _font_fallback_candidates(font: str) -> tuple[str, ...]:
    """Return visually compatible cross-platform fallbacks in preference order."""
    normalized = font.casefold()
    if "symbol" in normalized or "dingbat" in normalized or "wingding" in normalized:
        candidates = SYMBOL_FONT_FALLBACKS
    elif any(marker in normalized for marker in ("mono", "courier", "consolas", "menlo", "code")):
        candidates = MONOSPACE_FONT_FALLBACKS
    elif any(marker in normalized for marker in ("serif", "times", "georgia", "cambria", "garamond", "minion")):
        candidates = SERIF_FONT_FALLBACKS
    else:
        candidates = SANS_FONT_FALLBACKS
    seen = {normalized}
    ordered = []
    for candidate in candidates:
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(candidate)
    return tuple(ordered)


def _approved_packaged_font_fallback(
    font: str,
    approved_font_plan: Mapping[str, Any] | None = None,
) -> str:
    """Map a missing template font to one audited release-owned substitute."""
    normalized = font.casefold().strip()
    approved = (
        approved_font_plan.get("approved_fallbacks", {})
        if isinstance(approved_font_plan, Mapping)
        else APPROVED_PACKAGED_FONT_FALLBACKS
    )
    families = (
        approved_font_plan.get("packaged_families", {})
        if isinstance(approved_font_plan, Mapping)
        else BUNDLED_FONT_FILES
    )
    if normalized in approved:
        return str(approved[normalized])
    if any(marker in normalized for marker in ("mono", "courier", "consolas", "menlo", "code")):
        return "Liberation Mono" if "Liberation Mono" in families else next(iter(families))
    if any(marker in normalized for marker in ("serif", "times", "georgia", "cambria", "garamond", "minion")):
        return "Liberation Serif" if "Liberation Serif" in families else next(iter(families))
    return "Liberation Sans" if "Liberation Sans" in families else next(iter(families))


def preflight(
    repo_root: Path,
    reference: Mapping[str, Any],
    *,
    contracted_bundle: Mapping[str, Any] | None = None,
    deadline_seconds: float = 30.0,
    environment: Mapping[str, str] | None = None,
    renderer_identities: Iterable[Mapping[str, Any]] | None = None,
    page_renderer_identities: Iterable[Mapping[str, Any]] | None = None,
    clock: Any = time.monotonic,
) -> dict[str, Any]:
    """Resolve and smoke-test Render Assurance capabilities.

    Inventory uncertainty is evidence to test, not evidence of absence. The
    function only blocks after every local renderer/page-renderer combination
    has failed its disposable render.
    """
    started = clock()
    deadline = started + max(0.0, deadline_seconds)

    def remaining() -> float:
        return max(0.0, deadline - clock())

    bundle = contracted_bundle or contracted_template_bundle(repo_root, reference)
    approved_font_plan = bundle["approved_font_plan"]
    runtime_environment = _runtime_environment(repo_root, environment, bundle)
    renderer_candidates = (
        [dict(item) for item in renderer_identities]
        if renderer_identities is not None
        else renderers(
            environment=runtime_environment,
            skill_root=repo_root,
            deadline_monotonic=deadline,
            clock=clock,
        )
    )
    page_candidates = (
        [dict(item) for item in page_renderer_identities]
        if page_renderer_identities is not None
        else page_renderers(environment=runtime_environment, skill_root=repo_root) if remaining() > 0 else []
    )
    identity = None
    page_identity = None
    renderer_attempts: list[dict[str, Any]] = []
    page_attempts: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    protocol_template, icf_template = template_paths(repo_root, reference, contracted_bundle=bundle)
    templates = [path for path in (protocol_template, icf_template) if path is not None]
    required_fonts = sorted({font for path in templates for font in _template_fonts(path)})
    font_results: dict[str, Any] = {}
    font_substitutions: dict[str, str] = {}
    bundled_substitution = False
    for font in required_fonts:
        probe_remaining = remaining()
        if probe_remaining <= 0:
            font_results[font] = {"available": None, "match": "Render Assurance deadline expired before font inventory."}
            continue
        available, detail = _font_probe(font, environment=runtime_environment, timeout_seconds=probe_remaining)
        font_results[font] = {"available": available, "match": detail}
        if available is not False:
            continue
        candidate = _approved_packaged_font_fallback(font, approved_font_plan)
        bundled = _bundled_font_path(repo_root, candidate, approved_font_plan)
        if bundled is not None:
            font_substitutions[font] = candidate
            font_results[font].update({
                "substitute": candidate,
                "substitute_match": f"bundled approved compatible font: {bundled.relative_to(repo_root)}",
            })
            bundled_substitution = True
        else:
            font_results[font]["attempted_fallbacks"] = [candidate]
    smoke: dict[str, Any] = {"status": "not_run"}
    if renderer_candidates and page_candidates and remaining() > 0:
        with tempfile.TemporaryDirectory(prefix="hermes-renderer-preflight-") as directory:
            root = Path(directory)
            source = root / "preflight.docx"
            document = Document()
            document.add_paragraph("Hermes renderer preflight")
            for font in required_fonts:
                selected = font_substitutions.get(font, font)
                run = document.add_paragraph().add_run(f"{selected}: Aa 123 •")
                run.font.name = selected
                fonts = run._element.get_or_add_rPr().get_or_add_rFonts()
                for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
                    fonts.set(qn(f"w:{attribute}"), selected)
            document.save(source)
            for candidate_renderer in renderer_candidates:
                attempt_remaining = remaining()
                if attempt_remaining <= 0:
                    break
                if bundled_substitution and candidate_renderer.get("kind") != "LibreOffice":
                    renderer_attempts.append({
                        "renderer": candidate_renderer,
                        "status": "skipped",
                        "issue": "Bundled fallback fonts are isolated to the verified LibreOffice runtime.",
                    })
                    continue
                try:
                    pdf = _render_pdf(
                        source,
                        root,
                        candidate_renderer,
                        environment=runtime_environment,
                        timeout_seconds=max(0.001, attempt_remaining),
                    )
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    renderer_attempts.append({"renderer": candidate_renderer, "status": "failed", "issue": str(exc)})
                    continue
                page_dir = root / "pages"
                for candidate_page_renderer in page_candidates:
                    attempt_remaining = remaining()
                    if attempt_remaining <= 0:
                        break
                    try:
                        rasterize_pdf(
                            pdf,
                            page_dir,
                            candidate_page_renderer,
                            first_page_only=True,
                            timeout_seconds=max(0.001, attempt_remaining),
                            environment=runtime_environment,
                        )
                    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                        page_attempts.append({"renderer": candidate_page_renderer, "status": "failed", "issue": str(exc)})
                        continue
                    identity = candidate_renderer
                    page_identity = candidate_page_renderer
                    renderer_attempts.append({"renderer": candidate_renderer, "status": "passed"})
                    page_attempts.append({"renderer": candidate_page_renderer, "status": "passed"})
                    smoke = {"status": "passed", "pdf": "disposable/preflight.pdf", "page_image": "disposable/preflight.png", "pages": len(PdfReader(pdf).pages)}
                    break
                if identity is not None:
                    break
                renderer_attempts.append({
                    "renderer": candidate_renderer,
                    "status": "failed",
                    "issue": "Every available page renderer failed for this renderer.",
                })
    if identity is None:
        if not renderer_candidates:
            issue = "No supported Word, LibreOffice, Pages, or verified fallback renderer is available."
            field = "renderer"
        elif not page_candidates:
            issue = "No supported PDF page renderer is available, including bundled PyMuPDF."
            field = "page_renderer"
        else:
            issue = "Every local renderer/page-renderer combination failed its smoke render."
            field = "preflight"
        findings.append({"category": "renderer", "field": field, "issue": issue})
        smoke = {"status": "blocked", "issue": issue}
    else:
        for font, result in font_results.items():
            if result.get("available") is None:
                result["resolution"] = "render_verified"
    elapsed = clock() - started
    if elapsed > deadline_seconds and identity is None:
        findings.append({"category": "renderer", "field": "preflight", "issue": f"Renderer preflight exceeded its {deadline_seconds:.1f}s deadline ({elapsed:.3f}s)."})
    ordered_renderers = ([identity] if identity else []) + [candidate for candidate in renderer_candidates if candidate != identity]
    ordered_page_renderers = ([page_identity] if page_identity else []) + [candidate for candidate in page_candidates if candidate != page_identity]
    return {
        "status": "passed" if not findings else "blocked",
        "contracted_template_bundle": dict(bundle),
        "renderer": identity,
        "renderer_candidates": ordered_renderers,
        "renderer_attempts": renderer_attempts,
        "page_renderer": page_identity,
        "page_renderer_candidates": ordered_page_renderers,
        "page_renderer_attempts": page_attempts,
        "required_fonts": required_fonts,
        "fonts": font_results,
        "font_substitutions": font_substitutions,
        "smoke": smoke,
        "deadline_seconds": deadline_seconds,
        "elapsed_seconds": round(elapsed, 3),
        "findings": findings,
    }


def _render_pdf(docx: Path, output_dir: Path, identity: Mapping[str, Any], *, environment: Mapping[str, str] | None = None, timeout_seconds: float = 180.0) -> Path:
    if identity["kind"] == "LibreOffice":
        result = subprocess.run([str(identity["path"]), "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(docx)], text=True, capture_output=True, timeout=timeout_seconds, env=dict(environment) if environment else None)
        path = output_dir / f"{docx.stem}.pdf"
        if result.returncode or not path.is_file():
            raise RuntimeError(f"LibreOffice PDF export failed: {result.stderr or result.stdout}")
        return path
    if identity.get("platform") == "Windows":
        return _windows_word_pdf(docx, output_dir, timeout_seconds=timeout_seconds)
    return _mac_pdf(docx, output_dir, identity, timeout_seconds=timeout_seconds)


def _mac_pdf(docx: Path, output_dir: Path, identity: Mapping[str, Any], *, timeout_seconds: float = 180.0) -> Path:
    app = "Microsoft Word" if identity["kind"] == "Microsoft Word" else "Pages"
    output = output_dir / f"{docx.stem}.pdf"
    if app == "Microsoft Word":
        script = 'on run argv\nset src to POSIX file (item 1 of argv)\nset dst to POSIX file (item 2 of argv)\ntell application "Microsoft Word"\nset d to open src\nsave as d file name dst file format format PDF\nclose d saving no\nend tell\nend run'
    else:
        script = 'on run argv\nset src to POSIX file (item 1 of argv)\nset dst to POSIX file (item 2 of argv)\ntell application "Pages"\nset d to open src\nexport d to dst as PDF\nclose d saving no\nend tell\nend run'
    result = subprocess.run(["osascript", "-e", script, str(docx), str(output)], text=True, capture_output=True, timeout=timeout_seconds)
    if result.returncode or not output.is_file(): raise RuntimeError(f"{app} PDF export failed: {result.stderr or result.stdout}")
    return output


def _windows_word_pdf(docx: Path, output_dir: Path, *, timeout_seconds: float = 180.0) -> Path:
    output = output_dir / f"{docx.stem}.pdf"
    script = (
        "import sys\nimport win32com.client\n"
        "word=win32com.client.DispatchEx('Word.Application'); word.Visible=False; document=None\n"
        "try:\n document=word.Documents.Open(sys.argv[1], ReadOnly=True); document.ExportAsFixedFormat(sys.argv[2], 17)\n"
        "finally:\n document.Close(False) if document is not None else None; word.Quit()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(docx.resolve()), str(output.resolve())],
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    if result.returncode:
        raise RuntimeError(f"Microsoft Word PDF export failed: {result.stderr or result.stdout}")
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


def render_pages(
    revision_dir: Path,
    *,
    artifact_names: Iterable[str] | None = None,
    contracted_bundle: Mapping[str, Any] | None = None,
    renderer_identity: Mapping[str, Any] | None = None,
    page_renderer_identity: Mapping[str, Any] | None = None,
    renderer_identities: Iterable[Mapping[str, Any]] | None = None,
    page_renderer_identities: Iterable[Mapping[str, Any]] | None = None,
    deadline_monotonic: float | None = None,
    clock: Any = time.monotonic,
    font_evidence: Mapping[str, Any] | None = None,
    font_substitutions: Mapping[str, str] | None = None,
    office_exporter: Any = None,
    page_exporter: Any = None,
    blank_page_detector: Any = None,
) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    runtime_environment = _runtime_environment(repo_root, None, contracted_bundle)
    export_docx = office_exporter or _render_pdf
    export_pages = page_exporter or rasterize_pdf
    find_blank_pages = blank_page_detector or _blank_pdf_pages
    render_root = revision_dir / "rendered"
    selected_artifacts = set(artifact_names or ())
    docx_paths = [
        path
        for path in sorted((revision_dir / "candidate").glob("*.docx"))
        if not selected_artifacts or path.stem in selected_artifacts
    ]
    if selected_artifacts:
        for docx in docx_paths:
            (render_root / f"{docx.stem}.pdf").unlink(missing_ok=True)
            shutil.rmtree(render_root / docx.stem, ignore_errors=True)
    elif render_root.exists():
        shutil.rmtree(render_root)
    renderer_candidates = [dict(item) for item in (renderer_identities or [])]
    if renderer_identity is not None:
        renderer_candidates = [dict(renderer_identity), *[item for item in renderer_candidates if dict(item) != dict(renderer_identity)]]
    if not renderer_candidates and renderer_identities is None and renderer_identity is None:
        renderer_candidates = renderers(environment=runtime_environment, skill_root=repo_root)
    page_candidates = [dict(item) for item in (page_renderer_identities or [])]
    if page_renderer_identity is not None:
        page_candidates = [dict(page_renderer_identity), *[item for item in page_candidates if dict(item) != dict(page_renderer_identity)]]
    if not page_candidates and page_renderer_identities is None and page_renderer_identity is None:
        page_candidates = page_renderers(environment=runtime_environment, skill_root=repo_root)
    if not renderer_candidates:
        return {"status": "blocked", "findings": [{"category": "renderer", "field": "renderer", "issue": "No supported Word, LibreOffice, Pages, or verified fallback renderer is available."}]}
    if not page_candidates:
        return {"status": "blocked", "renderer": renderer_candidates[0], "findings": [{"category": "renderer", "field": "page_renderer", "issue": "No supported PDF page renderer is available."}]}

    renderer_attempts: list[dict[str, Any]] = []
    page_attempts: list[dict[str, Any]] = []
    for renderer_index, identity in enumerate(renderer_candidates, 1):
        remaining = 180.0 if deadline_monotonic is None else deadline_monotonic - clock()
        if remaining <= 0:
            break
        attempt_root = revision_dir / ".render-attempts" / f"renderer-{renderer_index}"
        if attempt_root.exists():
            shutil.rmtree(attempt_root)
        attempt_root.mkdir(parents=True)
        pdfs: dict[Path, Path] = {}
        try:
            for docx in docx_paths:
                remaining = 180.0 if deadline_monotonic is None else deadline_monotonic - clock()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired("DOCX rendering", 0)
                pdf = export_docx(docx, attempt_root, identity, environment=runtime_environment, timeout_seconds=min(180.0, remaining))
                for _ in range(3):
                    if not refresh_toc_from_pdf(docx, pdf):
                        break
                    pdf.unlink(missing_ok=True)
                    remaining = 180.0 if deadline_monotonic is None else deadline_monotonic - clock()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired("DOCX rendering", 0)
                    pdf = export_docx(docx, attempt_root, identity, environment=runtime_environment, timeout_seconds=min(180.0, remaining))
                pdfs[docx] = pdf
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            renderer_attempts.append({"renderer": identity, "status": "failed", "issue": str(exc)})
            continue

        selected_page_renderer = None
        selected_pages: dict[Path, list[Path]] = {}
        for candidate in page_candidates:
            current_pages: dict[Path, list[Path]] = {}
            try:
                for docx, pdf in pdfs.items():
                    remaining = 180.0 if deadline_monotonic is None else deadline_monotonic - clock()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired("PDF page rendering", 0)
                    page_dir = attempt_root / docx.stem / str(candidate["kind"])
                    pages = export_pages(pdf, page_dir, candidate, dpi=130, timeout_seconds=min(180.0, remaining), environment=runtime_environment)
                    expected = len(PdfReader(pdf).pages)
                    if len(pages) != expected or expected == 0:
                        raise RuntimeError(f"Page rendering failed for {docx.name}: expected {expected}, got {len(pages)}.")
                    current_pages[docx] = pages
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                page_attempts.append({"renderer": candidate, "status": "failed", "issue": str(exc)})
                continue
            selected_page_renderer = candidate
            selected_pages = current_pages
            page_attempts.append({"renderer": candidate, "status": "passed"})
            break
        if selected_page_renderer is None:
            renderer_attempts.append({"renderer": identity, "status": "failed", "issue": "Every available page renderer failed for the exported PDFs."})
            continue

        findings: list[dict[str, Any]] = []
        artifacts = []
        if not selected_artifacts and render_root.exists():
            shutil.rmtree(render_root)
        render_root.mkdir(parents=True, exist_ok=True)
        for docx, source_pdf in pdfs.items():
            pdf = render_root / source_pdf.name
            pdf.unlink(missing_ok=True)
            shutil.copy2(source_pdf, pdf)
            page_dir = render_root / docx.stem
            shutil.rmtree(page_dir, ignore_errors=True)
            page_dir.mkdir()
            pages = []
            for index, source_page in enumerate(selected_pages[docx], 1):
                page = page_dir / f"page-{index}.png"
                shutil.copy2(source_page, page)
                pages.append(page)
            for page_number in find_blank_pages(pdf):
                findings.append({
                    "category": "visual",
                    "field": docx.stem,
                    "artifact": docx.stem,
                    "page": page_number,
                    "target_ids": [f"layout:{docx.stem}"],
                    "issue": f"Rendered {docx.stem} contains a textless page at page {page_number}.",
                })
            artifacts.append({
                "artifact": docx.stem,
                "renderer": identity,
                "page_renderer": selected_page_renderer,
                "font_evidence": dict(font_evidence or {}),
                "font_substitutions": dict(font_substitutions or {}),
                "docx": docx.relative_to(revision_dir).as_posix(),
                "docx_sha256": sha256_file(docx),
                "pdf": pdf.relative_to(revision_dir).as_posix(),
                "pdf_sha256": sha256_file(pdf),
                "pages": [{"page": i, "path": page.relative_to(revision_dir).as_posix(), "sha256": sha256_file(page)} for i, page in enumerate(pages, 1)],
            })
        renderer_attempts.append({"renderer": identity, "status": "passed"})
        return {
            "status": "passed" if not findings else "blocked",
            "renderer": identity,
            "renderer_attempts": renderer_attempts,
            "page_renderer": selected_page_renderer,
            "page_renderer_attempts": page_attempts,
            "artifacts": artifacts,
            "findings": findings,
        }
    return {
        "status": "blocked",
        "renderer_attempts": renderer_attempts,
        "page_renderer_attempts": page_attempts,
        "findings": [{"category": "renderer", "field": "rendering", "issue": "Every local renderer/page-renderer combination failed."}],
    }


def render_assurance(
    repo_root: Path,
    revision_dir: Path,
    reference: Mapping[str, Any],
    *,
    contracted_bundle: Mapping[str, Any] | None = None,
    structural_validation: Mapping[str, Any],
    candidate_font_substitutions: Mapping[str, str] | None = None,
    rebuild_candidate: Any = None,
    artifact_names: Iterable[str] | None = None,
    renderer_identities: Iterable[Mapping[str, Any]] | None = None,
    page_renderer_identities: Iterable[Mapping[str, Any]] | None = None,
    deadline_seconds: float = 180.0,
    deadline_monotonic: float | None = None,
    clock: Any = time.monotonic,
    font_probe: Any = None,
    office_exporter: Any = None,
    page_exporter: Any = None,
    blank_page_detector: Any = None,
) -> dict[str, Any]:
    """Resolve fonts and render one complete candidate through one assurance seam."""
    started = clock()
    deadline = deadline_monotonic if deadline_monotonic is not None else started + max(0.0, deadline_seconds)
    bundle = contracted_bundle or contracted_template_bundle(repo_root, reference)
    approved_font_plan = bundle["approved_font_plan"]
    runtime_environment = _runtime_environment(repo_root, None, bundle)
    selected_artifacts = set(artifact_names or ())
    all_candidate_paths = [path for path in sorted((revision_dir / "candidate").glob("*")) if path.is_file()]
    structural_evidence, structural_finding = _validated_candidate_structure(
        revision_dir,
        structural_validation,
        all_candidate_paths,
    )
    candidate_paths = [
        path
        for path in all_candidate_paths
        if path.suffix.casefold() == ".docx"
        if not selected_artifacts or path.stem in selected_artifacts
    ]
    if structural_finding is not None or not candidate_paths:
        finding = structural_finding or recovery_finding({
                "category": "document-structure",
                "field": "candidate",
                "issue": "Render Assurance requires a complete structurally validated DOCX candidate.",
            }, "document_structure_defect")
        return {
            "schema_version": "render-assurance/v1",
            "status": "blocked",
            "fonts": {},
            "font_substitutions": {},
            "candidate": {"files": []},
            "structural_validation": structural_evidence,
            "render": {"status": "not_run", "findings": [finding]},
            "findings": [finding],
        }

    required_fonts = sorted({font for path in candidate_paths for font in _template_fonts(path)})
    probe = font_probe or _font_probe
    fonts: dict[str, dict[str, Any]] = {}
    substitutions: dict[str, str] = {}
    for font in required_fonts:
        remaining = max(0.0, deadline - clock())
        if remaining <= 0:
            available, detail = None, "Render Assurance deadline expired before font inventory."
        else:
            available, detail = probe(font, environment=runtime_environment, timeout_seconds=remaining)
        state = "available" if available is True else "missing-or-unusable" if available is False else "unknown"
        evidence = {"state": state, "match": detail}
        if state == "unknown":
            evidence.update({
                "recovery_class": "font_capability_uncertainty",
                "action": RECOVERY_POLICIES["font_capability_uncertainty"],
            })
        if state == "missing-or-unusable":
            substitute = _approved_packaged_font_fallback(font, approved_font_plan)
            bundled = _bundled_font_path(repo_root, substitute, approved_font_plan)
            if bundled is not None:
                if substitute.casefold() != font.casefold():
                    substitutions[font] = substitute
                evidence.update({
                    "substitute": substitute,
                    "substitute_match": f"bundled approved compatible font: {bundled.relative_to(repo_root)}",
                })
            else:
                evidence["attempted_fallbacks"] = [substitute]
        fonts[font] = evidence

    prior_substitutions = dict(candidate_font_substitutions or {})
    for source, target in prior_substitutions.items():
        if source not in required_fonts and target in required_fonts:
            substitutions[source] = target
            fonts[source] = {
                "state": "missing-or-unusable",
                "match": "Persisted candidate substitution.",
                "substitute": target,
                "resolution": "candidate_substitution_preserved",
            }
    if substitutions != prior_substitutions:
        if rebuild_candidate is None:
            finding = recovery_finding({
                "category": "document-structure",
                "field": "font_substitutions",
                "issue": "The candidate must be rebuilt with the selected approved font substitutions before rendering.",
            }, "document_structure_defect")
            return {
                "schema_version": "render-assurance/v1",
                "status": "blocked",
                "fonts": fonts,
                "font_substitutions": substitutions,
                "candidate": {"files": _artifact_hashes(revision_dir, all_candidate_paths)},
                "render": {"status": "not_run", "findings": [finding]},
                "findings": [finding],
            }
        rebuild_report = rebuild_candidate(substitutions)
        if rebuild_report.get("status") != "passed":
            findings = [recovery_finding(finding, "document_structure_defect") for finding in (rebuild_report.get("findings") or [{
                "category": "document-structure",
                "field": "font_substitutions",
                "issue": "The candidate could not be rebuilt with approved font substitutions.",
            }])]
            return {
                "schema_version": "render-assurance/v1",
                "status": "blocked",
                "fonts": fonts,
                "font_substitutions": substitutions,
                "candidate": {"files": _artifact_hashes(revision_dir, all_candidate_paths)},
                "render": {"status": "not_run", "findings": findings},
                "findings": findings,
            }
        candidate_paths = [
            path
            for path in sorted((revision_dir / "candidate").glob("*.docx"))
            if not selected_artifacts or path.stem in selected_artifacts
        ]
        all_candidate_paths = [path for path in sorted((revision_dir / "candidate").glob("*")) if path.is_file()]
        post_rebuild_validation = {
            **dict(structural_validation),
            "candidate_files": _artifact_hashes(revision_dir, all_candidate_paths),
        }
        structural_evidence, structural_finding = _validated_candidate_structure(
            revision_dir,
            post_rebuild_validation,
            all_candidate_paths,
        )
        structural_evidence["revalidated_after_substitution"] = structural_finding is None
        if structural_finding is not None or not candidate_paths:
            finding = structural_finding or recovery_finding({
                "category": "document-structure",
                "field": "candidate",
                "issue": "The rebuilt candidate does not contain the selected DOCX artifacts.",
            }, "document_structure_defect")
            return {
                "schema_version": "render-assurance/v1",
                "status": "blocked",
                "fonts": fonts,
                "font_substitutions": substitutions,
                "candidate": {"files": _artifact_hashes(revision_dir, all_candidate_paths)},
                "structural_validation": structural_evidence,
                "render": {"status": "not_run", "findings": [finding]},
                "findings": [finding],
            }

    office_candidates = (
        [dict(item) for item in renderer_identities]
        if renderer_identities is not None
        else renderers(environment=runtime_environment, skill_root=repo_root, deadline_monotonic=deadline, clock=clock)
    )
    page_candidates = (
        [dict(item) for item in page_renderer_identities]
        if page_renderer_identities is not None
        else page_renderers(environment=runtime_environment, skill_root=repo_root)
    )
    render_report = render_pages(
        revision_dir,
        artifact_names=artifact_names,
        contracted_bundle=bundle,
        renderer_identities=office_candidates,
        page_renderer_identities=page_candidates,
        deadline_monotonic=deadline,
        clock=clock,
        font_evidence=fonts,
        font_substitutions=substitutions,
        office_exporter=office_exporter,
        page_exporter=page_exporter,
        blank_page_detector=blank_page_detector,
    )
    render_report["renderer_attempts"] = _governed_adapter_attempts(render_report.get("renderer_attempts", []))
    render_report["page_renderer_attempts"] = _governed_adapter_attempts(render_report.get("page_renderer_attempts", []))
    governed_findings = []
    for raw in render_report.get("findings", []):
        finding = dict(raw)
        if finding.get("category") == "visual":
            finding.update({
                "recovery_class": "visual_defect",
                "action": RECOVERY_POLICIES["visual_defect"],
            })
        elif finding.get("category") == "renderer":
            finding = recovery_finding(finding, "adapter_fault")
        governed_findings.append(finding)
    render_report["findings"] = governed_findings
    if render_report.get("status") == "passed":
        for evidence in fonts.values():
            if evidence["state"] == "unknown":
                evidence["resolution"] = "render_verified"
        for artifact in render_report.get("artifacts", []):
            artifact["font_evidence"] = fonts
    report = {
        "schema_version": "render-assurance/v1",
        "status": render_report.get("status", "blocked"),
        "fonts": fonts,
        "font_substitutions": substitutions,
        "candidate": {
            "files": _artifact_hashes(revision_dir, all_candidate_paths),
            "font_evidence": fonts,
            "font_substitutions": substitutions,
        },
        "structural_validation": structural_evidence,
        "render": render_report,
        "findings": governed_findings,
        "elapsed_seconds": round(clock() - started, 3),
    }
    if report["status"] != "passed" and governed_findings and all(
        finding.get("recovery_class") == "adapter_fault" for finding in governed_findings
    ):
        report["diagnostic"] = {
            "recovery_class": "adapter_fault",
            "action": RECOVERY_POLICIES["adapter_fault"],
            "outcome": "adapters_exhausted",
            "candidate_disposition": "preserved",
            "publication": "blocked",
            "office_attempts": render_report["renderer_attempts"],
            "page_attempts": render_report["page_renderer_attempts"],
            "font_evidence": fonts,
            "font_substitutions": substitutions,
            "candidate_files": report["candidate"]["files"],
        }
    return report


def _validated_candidate_structure(
    revision_dir: Path,
    validation: Mapping[str, Any],
    candidate_paths: Iterable[Path],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    paths = list(candidate_paths)
    current = _artifact_hashes(revision_dir, paths)
    expected = {str(name) for name in validation.get("expected_files", []) if str(name)}
    actual = {path.name for path in paths}
    recorded = {
        str(item.get("path")): item
        for item in validation.get("candidate_files", [])
        if isinstance(item, Mapping) and item.get("path")
    }
    evidence = {
        "status": validation.get("status"),
        "expected_files": sorted(expected),
        "candidate_files": current,
    }
    complete = (
        validation.get("status") == "structurally_valid"
        and bool(expected)
        and actual == expected
        and all(
            (row := recorded.get(item["path"])) is not None
            and row.get("sha256") == item["sha256"]
            and int(row.get("bytes") or 0) == item["bytes"]
            for item in current
        )
    )
    if complete:
        return evidence, None
    return evidence, recovery_finding({
        "category": "document-structure",
        "field": "candidate",
        "issue": "Render Assurance requires the complete structurally validated Branch Document Set with matching hashes.",
    }, "document_structure_defect")


def _governed_adapter_attempts(attempts: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    governed = []
    for raw in attempts:
        attempt = {"adapter": dict(raw.get("renderer") or raw.get("adapter") or {}), "status": raw.get("status")}
        if raw.get("status") in {"failed", "skipped"}:
            attempt.update({
                "recovery_class": "adapter_fault",
                "action": RECOVERY_POLICIES["adapter_fault"],
                "issue": str(raw.get("issue") or "Adapter did not complete."),
            })
        governed.append(attempt)
    return governed


def _artifact_hashes(revision_dir: Path, paths: Iterable[Path]) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(revision_dir).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in paths
    ]


def deterministic_content_check(revision_dir: Path, reference: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    branch = canonical_study_type(get_path(reference, "meta.study_type")) or ""
    icf_template = str(get_path(reference, "meta.icf_template", "Advarra"))
    draftable_sections = {
        section_id
        for batch in batch_plan(branch, icf_template)
        for section_id in batch.section_ids
    }
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
        if len(text.split()) >= 8 and key in seen:
            if seen[key] == current_section:
                findings.append({"category": "content", "field": current_section or "protocol", "target_ids": [current_section or "protocol"], "issue": f"Exact paragraph is duplicated in protocol section {current_section or 'protocol'}."})
            else:
                findings.append({"category": "content", "field": current_section or "protocol", "target_ids": sorted({seen[key], current_section}), "issue": f"Exact paragraph is duplicated across protocol sections {seen[key]} and {current_section}."})
        elif len(text.split()) >= 8:
            seen[key] = current_section
    if branch == "Retrospective":
        if "approved visit schedule table is" in normalized_visible:
            findings.append({
                "category": "content",
                "field": "study-procedure.enrollment",
                "target_ids": ["study-procedure.enrollment"],
                "issue": "Retrospective study procedure contains flattened visit-schedule serialization instead of readable client-facing content.",
            })
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
        for section_id, title in icf_retained_sections(branch, icf_template):
            if title.casefold() not in icf_visible:
                findings.append(recovery_finding({
                    "category": "content",
                    "field": section_id,
                    "target_ids": ["layout:icf"],
                    "issue": f"Required retained ICF section is missing from the client shell: {title}",
                }, "document_structure_defect"))
        signature_marker = "signature of participant"
        if signature_marker not in icf_visible:
            findings.append(recovery_finding({
                "category": "content",
                "field": "icf.signature-block",
                "target_ids": ["layout:icf"],
                "issue": "Required participant signature block is missing from the ICF.",
            }, "document_structure_defect"))
        injury_or_costs = (
            "icf.injury" if "icf.injury" in draftable_sections
            else "icf.costs" if "icf.costs" in draftable_sections
            else "icf"
        )
        stale_icf_claims = {
            "eye tests and procedures": "icf.procedures",
            "routine cataract surgery": "icf.study-purpose",
            "company that makes the handpiece": "icf.study-purpose",
            "no additional side effects or risks expected": "icf.risks",
            "not to be used for participant enrollment": "icf.study-purpose",
            "advarra institutional review board": "icf.privacy",
            "all charges for medical care": injury_or_costs,
            "insurance company": injury_or_costs,
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
                findings.append(recovery_finding({"category": "content", "field": "prs.eligibility", "target_ids": ["layout:xml"], "issue": "PRS XML omits the approved minimum interval without participation in another study before screening."}, "document_structure_defect"))
        consent_to_sign = any(phrase in icf_visible for phrase in (
            "should not sign",
            "if you would like to participate, you will be asked to sign",
            "if you agree to participate, you will be asked to sign",
        ))
        if not consent_to_sign:
            findings.append(recovery_finding({"category": "content", "field": "icf.consent", "target_ids": ["layout:icf"], "issue": "ICF lacks an explicit instruction not to sign when the participant does not agree."}, "document_structure_defect"))
    governed = []
    for item in findings:
        if item.get("recovery_class") in RECOVERY_POLICIES:
            governed.append(item)
            continue
        targets = item.get("target_ids") if isinstance(item.get("target_ids"), list) else []
        unlocalized = not targets or any(
            str(target).strip().casefold() in {"", "protocol", "icf"}
            or str(target) not in draftable_sections
            for target in targets
        )
        governed.append(recovery_finding(
            item,
            "document_structure_defect" if unlocalized else "drafting_defect",
        ))
    return governed


def create_verification_requests(
    revision_dir: Path,
    reference: Mapping[str, Any],
    render_report: Mapping[str, Any],
    *,
    contracted_bundle: Mapping[str, Any] | None = None,
) -> list[Path]:
    requests = revision_dir / "hermes/verification-requests"; responses = revision_dir / "hermes/verification-responses"
    content_files = []
    for path in sorted((revision_dir / "candidate").glob("*")):
        if not path.is_file():
            continue
        artifact = {"path": path.relative_to(revision_dir).as_posix()}
        if path.suffix.casefold() == ".docx":
            artifact["content_sha256"] = _content_sha256(path)
        else:
            artifact["sha256"] = sha256_file(path)
        content_files.append(artifact)
    branch = canonical_study_type(get_path(reference, "meta.study_type")) or ""
    sections = [{"artifact": "protocol", "section_id": section.section_id, "number": section.number, "title": section.title} for section in protocol_contract(branch)]
    if branch != "Retrospective":
        choice = str(get_path(reference, "meta.icf_template", "Advarra"))
        sections.extend({"artifact": "icf", "section_id": section.section_id, "number": section.number, "title": section.title} for section in icf_contract(branch, choice))
        sections.extend({"artifact": "icf", "section_id": section_id, "number": "", "title": title} for section_id, title in icf_retained_sections(branch, choice))
    repo_root = Path(__file__).resolve().parents[1]
    bundle = dict(contracted_bundle or contracted_template_bundle(repo_root, reference))
    boilerplate_path = repo_root / str(bundle["fixed_clinical_boilerplate"]["path"])
    authorized_boilerplate = _json(boilerplate_path)
    if authorized_boilerplate.get("version") != BOILERPLATE_VERSION:
        raise ValueError("Verification boilerplate does not match the content contract.")
    payloads = [
        {"schema_version": VERIFY_SCHEMA, "request_id": f"{revision_dir.name}.verify.content", "task": "clinical_content_verification", "revision_id": revision_dir.name, "artifacts": content_files, "approved_source": reference, "authorized_boilerplate": authorized_boilerplate, "sections": sections, "checks": list(CONTENT_CHECKS), "cross_document_checks": list(CROSS_DOCUMENT_CHECKS), "instructions": "Assess every listed section against every content check and assess every cross-document check. Findings must include target_ids for affected section IDs. Treat exact authorized Fixed Clinical Boilerplate as approved non-study-specific content, not invention. Do not fail optional fields, dates, instruments, scoring rules, denominators, or policies that are absent from the approved source; instead fail only an unsupported affirmative claim or an omission of supplied material evidence. A document-control date may default from approval, while an unknown version must remain blank and must not be failed merely for being unknown.", "response_path": f"hermes/verification-responses/{revision_dir.name}.verify.content.json"},
    ]
    visual_artifacts = list(render_report.get("artifacts", []))
    visual_batches = [[artifact] for artifact in visual_artifacts] or [[]]
    for index, artifacts in enumerate(visual_batches, start=1):
        artifact_name = str(artifacts[0].get("artifact", "documents")) if artifacts else "documents"
        artifact_id = re.sub(r"[^a-z0-9]+", "-", artifact_name.casefold()).strip("-") or f"document-{index}"
        request_id = f"{revision_dir.name}.verify.visual.{artifact_id}"
        request_artifacts = [
            {key: value for key, value in artifact.items() if key not in {"renderer", "page_renderer"}}
            for artifact in artifacts
        ]
        payloads.append({
            "schema_version": VERIFY_SCHEMA,
            "request_id": request_id,
            "task": "rendered_page_visual_verification",
            "revision_id": revision_dir.name,
            "renderer": artifacts[0].get("renderer", render_report.get("renderer")) if artifacts else render_report.get("renderer"),
            "page_renderer": artifacts[0].get("page_renderer", render_report.get("page_renderer")) if artifacts else render_report.get("page_renderer"),
            "artifacts": request_artifacts,
            "checks": list(VISUAL_CHECKS),
            "instructions": "Inspect every supplied page image for this document. Do not infer pass from file existence or document text. Every repairable failure must identify artifact, check, and the exact element text of the affected heading or table caption so the repair remains local.",
            "reviewer_policy": {
                "image_inspection_required": True,
                "delegated_failure_fallback": "parent_reviews_the_same_bound_page_images",
                "deterministic_checks_alone_can_pass": False,
            },
            "response_path": f"hermes/verification-responses/{request_id}.json",
        })
    for payload in payloads:
        payload["contracted_template_bundle"] = bundle
        payload["request_sha256"] = verification_request_sha256(payload)
    expected = {payload["request_id"]: payload for payload in payloads}
    existing_paths = sorted(requests.glob("*.json"))
    existing = {}
    for path in existing_paths:
        try:
            item = _json(path); existing[item.get("request_id")] = (path, item)
        except (OSError, ValueError, json.JSONDecodeError):
            existing[path.name] = (path, {})
    for request_id, (path, request) in existing.items():
        replacement = expected.get(request_id)
        if (
            replacement is not None
            and verification_request_hash_valid(request)
            and request.get("request_sha256") == replacement["request_sha256"]
        ):
            continue
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


def verification_response_is_complete(revision_dir: Path, request_path: Path) -> bool:
    """Return whether one current, bound verifier response satisfies its full pass contract."""
    try:
        request = _json(request_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if not verification_request_hash_valid(request):
        return False
    findings, _ = validate_verifications(revision_dir, request_paths=[request_path])
    return not findings


def validate_verifications(
    revision_dir: Path,
    *,
    request_paths: Iterable[Path] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    findings: list[dict[str, Any]] = []; evidence: dict[str, Any] = {}
    request_records = [
        (request_path, _json(request_path))
        for request_path in sorted(
            request_paths
            if request_paths is not None
            else (revision_dir / "hermes/verification-requests").glob("*.json")
        )
    ]
    task_counts: dict[str, int] = {}
    for _, request in request_records:
        task = str(request.get("task"))
        task_counts[task] = task_counts.get(task, 0) + 1
    for request_path, request in request_records:
        response_path = revision_dir / request["response_path"]
        evidence_key = request["task"] if task_counts[str(request.get("task"))] == 1 else request["request_id"]
        verification_target = "verification:visual" if request["task"] == "rendered_page_visual_verification" else "verification:content"
        if not verification_request_hash_valid(request):
            findings.append(recovery_finding({
                "category": "verification",
                "field": "request_sha256",
                "target_ids": [verification_target],
                "issue": "Verification request body does not match its declared request hash.",
            }, "document_structure_defect"))
            continue
        if not response_path.is_file():
            findings.append(recovery_finding({"category": "verification", "field": request["task"], "target_ids": [verification_target], "issue": "Independent Hermes verification response is missing."}, "verifier_transient")); continue
        try: response = _json(response_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            findings.append(recovery_finding({"category": "verification", "field": request["task"], "target_ids": [verification_target], "issue": f"Invalid verification response: {exc}"}, "verifier_transient")); continue
        for key, expected in (("schema_version", RESPONSE_SCHEMA), ("request_id", request["request_id"]), ("request_sha256", request["request_sha256"]), ("task", request["task"])):
            if response.get(key) != expected: findings.append(recovery_finding({"category": "verification", "field": key, "issue": f"Verification response binding mismatch for {key}."}, "document_structure_defect"))
        producer = response.get("producer") if isinstance(response.get("producer"), Mapping) else {}
        if not _text(producer.get("model_id")): findings.append(recovery_finding({"category": "verification", "field": "producer.model_id", "target_ids": [verification_target], "issue": "Verifier identity is missing."}, "verifier_transient"))
        error = response.get("error") if isinstance(response.get("error"), Mapping) else {}
        error_type = _text(error.get("type")).casefold()
        transient = str(response.get("status") or "").casefold() in TRANSIENT_REVIEW_STATUSES or error_type in {
            "api_unavailable", "connection_error", "rate_limit", "timeout", "service_unavailable"
        }
        if transient:
            findings.append(recovery_finding({
                "category": "reviewer-transient",
                "field": request["task"],
                "target_ids": [verification_target],
                "issue": _text(error.get("message")) or "Independent Hermes verifier reported a transient API failure.",
            }, "verifier_transient"))
            evidence[evidence_key] = {"request": request_path.relative_to(revision_dir).as_posix(), "request_sha256": sha256_file(request_path), "response": response_path.relative_to(revision_dir).as_posix(), "response_sha256": sha256_file(response_path), "producer": producer, "status": "transient", "contracted_template_bundle": request.get("contracted_template_bundle")}
            continue
        issues = response.get("findings") if isinstance(response.get("findings"), list) else []
        if response.get("status") != "passed" or issues:
            for item in issues or [{"issue": "Verifier did not pass the artifact."}]:
                source = item if isinstance(item, Mapping) else {"issue": item}
                category = "visual" if request["task"] == "rendered_page_visual_verification" else "verification"
                finding = {"category": category, "field": request["task"], "issue": _text(source.get("issue"))}
                for key in ("target_ids", "artifact", "page", "check", "element"):
                    if key in source: finding[key] = source[key]
                if category == "visual":
                    finding["target_ids"] = [f"layout:{source.get('artifact') or 'documents'}"]
                elif not finding.get("target_ids"):
                    finding["target_ids"] = ["verification:content"]
                findings.append(recovery_finding(
                    finding,
                    "visual_defect" if category == "visual" else "drafting_defect",
                ))
        for artifact in request.get("artifacts", []):
            if request["task"] == "clinical_content_verification":
                path = revision_dir / str(artifact.get("path"))
                expected = artifact.get("content_sha256") or artifact.get("sha256")
                actual = None
                if path.is_file():
                    actual = _content_sha256(path) if artifact.get("content_sha256") else sha256_file(path)
                if not path.is_file() or actual != expected:
                    findings.append(recovery_finding({"category": "verification", "field": request["task"], "issue": f"Verification request is stale for {artifact.get('path')}."}, "document_structure_defect"))
            else:
                for key in ("docx", "pdf"):
                    path = revision_dir / str(artifact.get(key))
                    if not path.is_file() or sha256_file(path) != artifact.get(f"{key}_sha256"):
                        findings.append(recovery_finding({"category": "verification", "field": artifact.get("artifact", key), "issue": f"Visual verification request is stale for {artifact.get(key)}."}, "document_structure_defect"))
                for page in artifact.get("pages", []):
                    path = revision_dir / str(page.get("path"))
                    if not path.is_file() or sha256_file(path) != page.get("sha256"):
                        findings.append(recovery_finding({"category": "verification", "field": artifact.get("artifact", "page"), "issue": f"Visual verification request is stale for {page.get('path')}."}, "document_structure_defect"))
        if request["task"] == "clinical_content_verification":
            expected_sections = {(item["artifact"], item["section_id"]) for item in request.get("sections", [])}
            valid_section_rows = [item for item in response.get("section_assessments", []) if isinstance(item, Mapping) and item.get("status") == "passed" and set(item.get("checks", [])) == set(CONTENT_CHECKS)]
            assessed_sections = {(item.get("artifact"), item.get("section_id")) for item in valid_section_rows}
            if expected_sections != assessed_sections or len(valid_section_rows) != len(expected_sections):
                findings.append(recovery_finding({"category": "verification", "field": request["task"], "target_ids": [verification_target], "issue": f"Every contracted section and content check must be explicitly assessed; expected {len(expected_sections)}, accepted {len(assessed_sections)}."}, "verifier_transient"))
            expected_cross = set(request.get("cross_document_checks", []))
            valid_cross_rows = [item for item in response.get("cross_document_assessments", []) if isinstance(item, Mapping) and item.get("status") == "passed"]
            assessed_cross = {item.get("check") for item in valid_cross_rows}
            if expected_cross != assessed_cross or len(valid_cross_rows) != len(expected_cross):
                findings.append(recovery_finding({"category": "verification", "field": request["task"], "target_ids": [verification_target], "issue": f"Every cross-document check must be explicitly assessed; expected {len(expected_cross)}, accepted {len(assessed_cross)}."}, "verifier_transient"))
        if request["task"] == "rendered_page_visual_verification":
            expected_pages = {(a["artifact"], p["page"], p["sha256"]) for a in request.get("artifacts", []) for p in a.get("pages", [])}
            valid_page_rows = [p for p in response.get("page_assessments", []) if isinstance(p, Mapping) and p.get("status") == "passed" and set(p.get("checks", [])) == set(VISUAL_CHECKS)]
            assessed = {(p.get("artifact"), p.get("page"), p.get("sha256")) for p in valid_page_rows}
            if expected_pages != assessed or len(valid_page_rows) != len(expected_pages): findings.append(recovery_finding({"category": "verification", "field": "page_assessments", "target_ids": [verification_target], "issue": f"Every rendered page and every visual check must be explicitly assessed; expected {len(expected_pages)}, accepted {len(assessed)}."}, "verifier_transient"))
        evidence[evidence_key] = {
            "request": request_path.relative_to(revision_dir).as_posix(),
            "request_sha256": sha256_file(request_path),
            "response": response_path.relative_to(revision_dir).as_posix(),
            "response_sha256": sha256_file(response_path),
            "producer": producer,
            "artifacts": request.get("artifacts", []),
            "contracted_template_bundle": request.get("contracted_template_bundle"),
        }
    return findings, evidence


def quality_report(revision_dir: Path, reference: Mapping[str, Any], render_report: Mapping[str, Any], xml_report: Mapping[str, Any] | None) -> dict[str, Any]:
    findings = deterministic_content_check(revision_dir, reference)
    findings.extend(dict(item) for item in render_report.get("findings", []))
    if xml_report:
        findings.extend(recovery_finding(item, "document_structure_defect") for item in xml_report.get("findings", []))
    verification_findings, evidence = validate_verifications(revision_dir)
    findings.extend(verification_findings)
    return {"status": "passed" if not findings else "blocked", "findings": findings, "renderer": render_report.get("renderer"), "verification_evidence": evidence}


__all__ = ["CONTENT_CHECKS", "CROSS_DOCUMENT_CHECKS", "ICF_RETAINED_SHELL_SECTIONS", "PAGE_RENDERER_BACKENDS", "RECOVERY_POLICIES", "RESPONSE_SCHEMA", "VISUAL_CHECKS", "create_verification_requests", "deterministic_content_check", "page_renderer", "page_renderers", "pending_verifications", "preflight", "quality_report", "rasterize_pdf", "recovery_finding", "render_assurance", "render_pages", "renderer", "renderers", "sha256_file", "validate_verifications", "verification_request_hash_valid", "verification_request_sha256", "verification_response_is_complete"]
