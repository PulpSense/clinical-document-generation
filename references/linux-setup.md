# Explicit Linux setup

Use only when the owner explicitly requests a new host or a fresh extracted unsigned candidate. Ordinary operations use the already provisioned runtime.

Provision a new Hermes host once before generation by creating a dedicated
Python environment in writable storage and installing the pinned runtime
dependencies. This explicit setup operation is separate from document
generation. On the client Linux host, use:

```bash
/usr/local/bin/uv venv /opt/data/clinical-document-runtime --python /usr/bin/python3.13
/usr/local/bin/uv pip install --python /opt/data/clinical-document-runtime/bin/python python-docx==1.2.0 lxml==6.1.1 pypdf==6.10.0
export CLINICAL_PYTHON=/opt/data/clinical-document-runtime/bin/python
cd /absolute/path/to/hermes/skills/clinical-document-generation
"$CLINICAL_PYTHON" scripts/workflow.py --provision-candidate
"$CLINICAL_PYTHON" scripts/workflow.py --verify-installation
```

Run the final two commands once after every fresh extraction of an unsigned
client ZIP and require both JSON results to report `"status": "passed"` before
generation. `--provision-candidate` installs only the archive's hash-bound
Linux x86_64 PDFium wheel into that extracted skill; it does not download a
renderer or modify the host Python environment. `--verify-installation` then
smoke-tests the exact DOCX-to-PDF-to-page-image path through the host's Word or
LibreOffice installation. Do not use `--install-release` for this unsigned
drop-in path. That command remains reserved for a signed, fully certified
archive.
`--verify-installation` returns a smoke report; do not write that report as
`INSTALLATION-ASSURANCE.json` or create `PROMOTION-RECORD.json` for an unsigned
candidate. Those files are governed promotion state. On the Hermes host, a
rootless office launcher under the profile's `clinical-office-runtime/bin`
is discoverable during manual review even when isolated workers use a restricted
`PATH`.

The release carries its pinned Linux x86_64 PDFium page renderer. Microsoft
Word or LibreOffice remains the host prerequisite for DOCX-to-PDF rendering.
Resolve one supported interpreter first and retain its absolute path; do not
delegate launch to an ambiguous `python3` command. The Desktop launcher uses
`workflow.resolve_python_runtime`, launches with the returned `executable`,
and passes the returned identity to `run_desktop_operation` so every resume is
recorded. In the examples below, `CLINICAL_PYTHON` is that validated absolute
Python 3.10+ path.


After both setup results pass, follow [ordinary generation](../SKILL.md). This setup does not authorize signed installation or activation; see [release workflow](release-workflow.md).
