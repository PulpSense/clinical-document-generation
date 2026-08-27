# Clinical Document Generation

Hermes skill for generating reviewed clinical Protocol DOCX, ICF DOCX, and ClinicalTrials.gov PRS XML packages.

The repository root is the skill root. Install the whole repository—not only `SKILL.md`—because the skill requires its templates, contracts, boilerplate, and Python modules.

## Architecture

`scripts/workflow.py` is the only public entrypoint. Production code is limited to six Python files:

```text
scripts/
├── workflow.py
├── contracts.py
├── drafting.py
├── rendering.py
├── quality.py
└── prs_xml.py
```

There is no hidden runtime package and no alternative lifecycle.

The workflow is:

```text
study inputs
  → mandatory-input check
  → editable Source-of-Truth Markdown
  → explicit client approval
  → parallel section-level Hermes drafting batches
  → deterministic DOCX/XML assembly
  → independent content and every-page visual verification
  → atomic publication of the complete branch package
```

See [SKILL.md](SKILL.md) for the exact Hermes orchestration and retry loop.

## Runtime

- Python 3.10+
- Dependencies in `requirements.txt`
- Preferred host renderers: Microsoft Word, LibreOffice, then Apple Pages
- A version-local LibreOffice fallback provisioned during activation
- Page-image fallbacks ending in required PyMuPDF
- No Node.js or TypeScript

Activation provisions and smoke-tests a release-owned LibreOffice renderer, a release-owned PyMuPDF page renderer, and packaged compatible fonts. Preferred host tools remain first in the runtime ladder, but their absence cannot make the active release incapable of Visual QA. Normal generation never installs packages, fonts, or changes machine configuration. It builds the complete candidate before resolving Render Assurance, treats unknown font inventory as a render test rather than a missing font, maps proven-missing fonts only to explicit packaged Liberation substitutes, and records every fallback in the manifest.

The client outputs are standard `.docx` and `.xml` files. Microsoft Word is not required on the authoring computer; the workflow uses the best installed renderer for local QA and keeps the output Word-compatible.

Protocol and ICF rendering begins from the bundled client Word families. The renderer preserves their visual design, replaces study-specific Protocol bodies with accepted drafts, keeps applicable ICF regulatory language, removes example-study leakage, and blocks empty or near-empty rendered pages.

Install Python dependencies in the Hermes environment:

```bash
"$CLINICAL_PYTHON" -m pip install -r requirements.txt
```

`CLINICAL_PYTHON` must be the absolute Python 3.10+ path returned by
`workflow.resolve_python_runtime`; do not rely on the host's unqualified
`python3`. The Desktop operation records that identity and every later runtime
used to resume it.

## Public commands

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage prepare
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage approve --approved-by "<reviewer>"
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage validate
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage generate
```

`generate` may return `awaiting_hermes`. It is the deterministic inner lifecycle
step. Normal post-approval Desktop delivery uses
`workflow.run_desktop_operation`, which owns one cross-process UTC deadline, routes
those handoffs, and confirms every final attachment through the Desktop opener.
The standalone CLI loop is for development and controlled diagnostics; it is
not sufficient evidence of Desktop delivery.

The normal approval-to-accessible-files target is 10–12 minutes. The target is
not a cutoff. The complete operation, including retries, verification,
attachment retrieval, and owned-process cleanup, has a 30-minute ceiling.
Normal generation runs with the installed skill read-only and may write only to
the run workspace and isolated runtime caches. It never patches code or
templates, installs packages, runs the development suite, or starts a recovery
operation to obtain a new deadline.

## Verification

```bash
"$CLINICAL_PYTHON" -m py_compile scripts/*.py
"$CLINICAL_PYTHON" -m pytest -q
"$CLINICAL_PYTHON" scripts/workflow.py --release-gate
# Build a clean release archive outside the checkout
"$CLINICAL_PYTHON" scripts/workflow.py --package-release /absolute/path/clinical-document-generation-release.zip
"$CLINICAL_PYTHON" scripts/workflow.py --install-release /absolute/path/clinical-document-generation-release.zip --skills-dir /absolute/path/to/hermes/skills
"$CLINICAL_PYTHON" scripts/workflow.py --verify-installation
```

The first release-gate command may return `awaiting_hermes` with independent
content and rendered-page verification requests. Complete those requests using
real content/image inspection, then resume without rebuilding the corpus:

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --release-gate --release-gate-root <evidence_root>
```

The gate never creates synthetic visual approvals.

The release gate exercises six distinct public lifecycle cases:

- Prospective sparse/rich
- Ambispective sparse/rich
- Retrospective sparse/rich

Prospective and Ambispective publish Protocol + ICF + PRS XML. Retrospective publishes Protocol only.

## Hermes installation

For a release, build the archive with `--package-release` and activate it with
`--install-release`. The installer stages the candidate, provisions its local
fallback runtime, verifies package hashes, renders a DOCX, rasterizes a page,
checks the packaged fonts, and atomically swaps it into the Hermes skills
directory. A failed update retains the previous verified release. The archive
includes the templates, contracts,
boilerplate, and requirements, plus `RELEASE-MANIFEST.json` with hashes and
packaging-time provenance. It excludes development environments, credentials,
source/patient data, old runs, and tests. Register the extracted root as
`clinical-document-generation` with `SKILL.md` as the entrypoint.

```bash
"$CLINICAL_PYTHON" scripts/workflow.py \
  --install-release /absolute/path/clinical-document-generation-release.zip \
  --skills-dir /absolute/path/to/hermes/skills
```

The installed `INSTALLATION-ASSURANCE.json` records the verified renderer,
page renderer, fonts, and smoke result. Installation is setup; the post-approval
Desktop operation remains governed by the single 30-minute budget. A passing
Generation Manifest is not delivery: the Desktop parent must expose exactly its
client outputs as attachments, retrieve each file through the actual opener,
and confirm byte length and SHA-256 before reporting success.

The Hermes runtime needs permission to execute Python, spawn drafting/verification subagents, and read/write run directories. Do not expose internal drafts, rendered PDFs, page PNGs, or logs to clients; return only the workflow’s `client_outputs` after `status: passed`.
