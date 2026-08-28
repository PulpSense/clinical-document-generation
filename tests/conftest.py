from __future__ import annotations

import sys
import hashlib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import quality


@pytest.fixture
def governed_pdfium(tmp_path, monkeypatch):
    """Provide the exact shape of a release-owned PDFium test runtime."""
    wheel = ROOT / "assets/runtime-wheels/pypdfium2-5.13.0-py3-none-macosx_13_0_arm64.whl"
    runtime_python = tmp_path / "runtime/python"
    runtime_python.mkdir(parents=True)
    with zipfile.ZipFile(wheel) as package:
        package.extractall(runtime_python)
    identity = {
        "kind": "pypdfium2",
        "path": "python:pypdfium2",
        "module": "pypdfium2",
        "python_path": str(runtime_python),
        "version": "5.13.0",
        "source": "release-owned runtime",
        "wheel": f"assets/runtime-wheels/{wheel.name}",
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
    }
    monkeypatch.setattr(quality, "page_renderers", lambda **_kwargs: [identity])
    return identity
