from __future__ import annotations

import sys
import hashlib
import json
import shutil
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
    source_wheel = ROOT / "tests/fixtures/runtime-wheels/pypdfium2-5.13.0-py3-none-macosx_13_0_arm64.whl"
    wheel = tmp_path / "assets/runtime-wheels" / source_wheel.name
    wheel.parent.mkdir(parents=True)
    shutil.copy2(source_wheel, wheel)
    runtime_python = tmp_path / "runtime/python"
    runtime_python.mkdir(parents=True)
    with zipfile.ZipFile(wheel) as package:
        package.extractall(runtime_python)
    runtime_inventory = sorted([
        {
            "path": path.relative_to(runtime_python).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in runtime_python.rglob("*")
        if path.is_file()
    ], key=lambda item: item["path"])
    manifest_identity = {
        "kind": "pypdfium2",
        "version": "5.13.0",
        "wheel": f"assets/runtime-wheels/{wheel.name}",
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "platform": "macosx_13_0_arm64",
        "runtime_inventory": runtime_inventory,
    }
    shutil.copytree(ROOT / "scripts", tmp_path / "scripts")
    manifest_payload = {
        "inventory": {"pdf_page_renderer": manifest_identity}
    }
    package_fingerprint = hashlib.sha256(
        json.dumps(
            manifest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    manifest = {**manifest_payload, "package_fingerprint": package_fingerprint}
    (tmp_path / "RELEASE-MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    assurance_path = tmp_path / "INSTALLATION-ASSURANCE.json"
    assurance_path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    (tmp_path / "PROMOTION-RECORD.json").write_text(json.dumps({
        "schema_version": "promoted-release/v1",
        "status": "active",
        "package_fingerprint": package_fingerprint,
        "runtime_assurance_sha256": hashlib.sha256(
            assurance_path.read_bytes()
        ).hexdigest(),
    }), encoding="utf-8")
    (tmp_path / "runtime/PDF-RENDERER.json").write_text(json.dumps({
        "kind": "pypdfium2",
        "version": "5.13.0",
        "wheel": manifest_identity["wheel"],
        "wheel_sha256": manifest_identity["wheel_sha256"],
        "platform": manifest_identity["platform"],
        "status": "provisioned",
        "inventory_source": "RELEASE-MANIFEST.json",
    }), encoding="utf-8")
    identity = quality.page_renderers(skill_root=tmp_path)[0]
    monkeypatch.setattr(quality, "page_renderers", lambda **_kwargs: [identity])
    monkeypatch.setattr(
        quality,
        "_one_pdfium_renderer",
        lambda identities, **_kwargs: [identity] if identities else [],
    )
    monkeypatch.setattr(
        quality,
        "_pdfium_worker_command",
        lambda request: [
            sys.executable,
            str(tmp_path / "scripts/workflow.py"),
            "--internal-pdfium-worker",
            str(request),
        ],
    )
    return identity
