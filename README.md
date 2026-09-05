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
- Required host renderer: Microsoft Word or LibreOffice
- One release-owned page renderer: pinned `pypdfium2` 5.13.0
- No Node.js or TypeScript

Activation verifies host Word or LibreOffice, installs the manifest-bound `pypdfium2` wheel offline into the release runtime, and smoke-tests that exact DOCX-to-PDF-to-PNG path with the packaged compatible fonts. No alternate PDF renderer is discovered or used. Normal generation never installs packages, fonts, or changes machine configuration. It builds the complete candidate before resolving Render Assurance, treats unknown font inventory as a render test rather than a missing font, and maps proven-missing fonts only to explicit packaged Liberation substitutes.

The client outputs are standard `.docx` and `.xml` files. The authoring host must provide Microsoft Word or LibreOffice for DOCX rendering; the workflow records which application produced the local QA evidence.

Protocol and ICF rendering begins from the bundled client Word families. The renderer preserves their visual design, replaces study-specific Protocol bodies with accepted drafts, keeps applicable ICF regulatory language, removes example-study leakage, and blocks empty or near-empty rendered pages.

For the normative Hermes setup—including the dedicated Python environment,
one-time unsigned-candidate provisioning, installation smoke, and the boundary
between `--manual-review` and formally certified activation—follow
[SKILL.md's Public interface](SKILL.md#public-interface). `CLINICAL_PYTHON` must
be the resolved absolute Python 3.10+ path; do not rely on the host's
unqualified `python3`. The Desktop operation records that identity and every
later runtime used to resume it.

## Public commands

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage prepare
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage approve --approved-by "<reviewer>"
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage validate
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage generate
```

`generate` may return `awaiting_hermes`. It is the deterministic inner lifecycle
step. Normal post-approval Desktop delivery uses
the shipped `scripts/workflow.py --desktop-operation` adapter, which owns one
cross-process UTC deadline, launches safe-mode Hermes workers behind a read-only
candidate boundary, routes bound responses, and confirms every final attachment
through the Desktop opener. The standalone `--stage generate` loop is for
development and controlled diagnostics; it is not sufficient evidence of
Desktop delivery.

Production Desktop operation also requires an absolute external parent-reviewer
command. When delegated Visual QA fails, the adapter passes that command one
JSON request path; the Desktop parent must inspect every referenced page and
write the bound verification responses. Worker redispatch is never relabelled
as parent review:

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --desktop-operation --run-dir <run-dir> \
  --desktop-opener-command /absolute/path/to/desktop-opener \
  --parent-visual-review-command /absolute/path/to/desktop-parent-reviewer
```

The same shipped adapter owns controlled real-Hermes certification execution.
`tests/hermes_e2e.py` prepares and audits the governed corpus but cannot replace
the candidate's launcher, sandbox, response authentication, generation loop, or
deadline. The persisted operation
state binds the release fingerprint and compatible runtimes to the original UTC
deadline, exact pending handoffs, attempt counters, stage timing and soft-budget
diagnostics, cleanup evidence, and immutable terminal result.

One real certification tracer requires an extracted, hash-valid candidate rather than the
editable checkout:

```bash
candidate_dir="$(mktemp -d /tmp/clinical-release-candidate.XXXXXX)"
mkdir -p "$candidate_dir/hermes-home/skills"
"$CLINICAL_PYTHON" scripts/workflow.py --package-release "$candidate_dir/release.zip"
unzip -q "$candidate_dir/release.zip" -d "$candidate_dir/hermes-home/skills"
"$CLINICAL_PYTHON" "$candidate_dir/hermes-home/skills/clinical-document-generation/scripts/workflow.py" \
  --provision-candidate
"$CLINICAL_PYTHON" tests/hermes_e2e.py \
  --fixture ambispective-sterling \
  --preflight-evidence /absolute/path/release-certification-preflight.json \
  --release-root "$candidate_dir/hermes-home/skills/clinical-document-generation" \
  --desktop-opener-command /absolute/path/to/desktop-opener \
  --parent-visual-review-command /absolute/path/to/desktop-parent-reviewer
```

The corpus controller loads `run_production_desktop_operation` from that
candidate; the candidate launches Hermes with its own files read-only and binds
the operation to its independently verified release-manifest fingerprint. Its
cleanup reserve remains inside the one 30-minute operation;
there is no shorter certification timeout. A successful single fixture is
case evidence only; it does not certify a release until the complete three-study
corpus has passed.

The complete live gate runs the declared cases sequentially against one package
fingerprint and stops at the first failed, blocked, or slow case while retaining
that attempt. It requires hash-bound evidence that static checks, the deterministic
ten-case Branch Acceptance Corpus with its executable historical regressions, and
the repository regression suite passed
before any real model call:

```bash
export CLINICAL_DOCUMENT_CERTIFICATION_PRIVATE_KEY=/absolute/path/to/production-signing-key.json
"$CLINICAL_PYTHON" tests/hermes_e2e.py \
  --run-preflight \
  --preflight-evidence /absolute/path/release-certification-preflight.json \
  --release-root /absolute/path/to/hermes-home/skills/clinical-document-generation

"$CLINICAL_PYTHON" tests/hermes_e2e.py \
  --corpus \
  --preflight-evidence /absolute/path/release-certification-preflight.json \
  --run-root /absolute/path/to/isolated-certification-runs \
  --release-root /absolute/path/to/hermes-home/skills/clinical-document-generation \
  --desktop-opener-command /absolute/path/to/desktop-opener \
  --parent-visual-review-command /absolute/path/to/desktop-parent-reviewer
```

The opener command is an external Desktop-host prerequisite, not a release
resource. It receives one attachment path and must emit exactly the bytes
retrieved through the actual Desktop opener on stdout; certification rejects a
missing, relative, non-executable, or symlinked command and never substitutes a
local filesystem read.

The harness creates the preflight evidence by checking a clean candidate commit,
compiling exactly the six production modules, running the identical-content
five-family Layout Preservation corpus, running the deterministic ten-case Branch
Acceptance Corpus and its historical regressions, and then running the complete repository suite. The resulting
`release-certification-corpus.json` is the only full-corpus pass signal. It binds
those governed command results and logs, the clean commit and package fingerprint, each
approved synthetic fixture, governed Hermes settings and observed model IDs,
Contracted Template Bundle and Layout Preservation identities, exact delivered
bytes, all quality gates, every rendered page and check, delivery confirmation,
Retrospective timing below 15 minutes, and the explicitly approved Ambispective
and Prospective ceiling of 18 minutes. Recorded drafting or synthetic verification remains
labelled structural-only in preflight evidence and cannot satisfy the live gate.

Certification fixtures live under `tests/fixtures/release-certification/`.
Each fixture manifest explicitly declares synthetic/non-private provenance,
hashes its source input, reviewed Source-of-Truth, and approved reference, fixes
the exact branch output set and governed Hermes configuration, and may declare
authority-derived Layout Preservation notes. A run is always prepared from
those repository bytes into a fresh directory; ignored runs, Downloads, and
prior Hermes sessions are not inputs. The durable report is written to
`<run>/logs/hermes-integration-report.json`. If the visual-review soft budget
expires, `<run>/logs/desktop-parent-visual-review.json` identifies the exact
page requests the Desktop parent must inspect and bind inside the unchanged
operation deadline.

The Desktop-parent visual-review command prints each complete outer verification
response to stdout and leaves response selection to the installed workflow. The
workflow ignores nested finding objects and persists only the unique response
bound to the request schema, ID, hash, and task.

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
"$CLINICAL_PYTHON" scripts/workflow.py --bind-certification /absolute/path/release-certification-corpus.json --release-archive /absolute/path/clinical-document-generation-release.zip
"$CLINICAL_PYTHON" scripts/workflow.py --install-release /absolute/path/clinical-document-generation-release.zip --skills-dir /absolute/path/to/hermes/skills --hermes-config /absolute/path/to/hermes/config.yaml
"$CLINICAL_PYTHON" scripts/workflow.py --verify-installation
"$CLINICAL_PYTHON" scripts/workflow.py --rollback-release --skills-dir /absolute/path/to/hermes/skills
```

The first release-gate command may return `awaiting_hermes` with independent
content and rendered-page verification requests. Complete those requests using
real content/image inspection, then resume without rebuilding the corpus:

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --release-gate --release-gate-root <evidence_root>
```

The gate never creates synthetic visual approvals.

The release gate exercises ten distinct public lifecycle cases:

- Prospective Advarra sparse/rich
- Prospective Sterling sparse/rich
- Ambispective Advarra sparse/rich
- Ambispective Sterling sparse/rich
- Retrospective sparse/rich

Prospective and Ambispective publish Protocol + ICF + PRS XML. Retrospective publishes Protocol only.

## Hermes installation

For a release, build the immutable candidate with `--package-release`, certify
its extracted and provisioned bytes, embed the passing full-corpus report with
`--bind-certification`, and activate it with `--install-release`. The installer stages the candidate, verifies host Word or
LibreOffice, installs its packaged PDFium runtime offline, verifies package hashes, renders a DOCX, rasterizes a page,
checks the packaged fonts, and atomically swaps it into the Hermes skills
directory. A failed update retains the previous verified release. The archive
includes the templates, contracts,
boilerplate, and requirements, plus `RELEASE-MANIFEST.json` with hashes and
packaging-time provenance. Packaging materializes the exact `HEAD` commit into
an isolated tree, records that commit, and never copies mutable checkout bytes.
It excludes development environments, credentials,
source/patient data, old runs, and tests. Register the extracted root as
`clinical-document-generation` with `SKILL.md` as the entrypoint.

```bash
"$CLINICAL_PYTHON" scripts/workflow.py \
  --install-release /absolute/path/clinical-document-generation-release.zip \
  --skills-dir /absolute/path/to/hermes/skills \
  --hermes-config /absolute/path/to/hermes/config.yaml
```

The installer refuses an unsigned archive, a mismatched fingerprint, unlisted
files, stale model/configuration evidence, or a Hermes configuration that points
at an editable copy. The installed `PROMOTION-RECORD.json` binds the commit,
fingerprint, embedded certification report, model/configuration hashes, runtime
assurance, activation time, and sole promoted discovery path.
`INSTALLATION-ASSURANCE.json` records the verified renderer,
page renderer, fonts, and smoke result. Installation is setup; the post-approval
Desktop operation remains governed by the single 30-minute budget. A passing
Generation Manifest is not delivery: the Desktop parent must expose exactly its
client outputs as attachments, retrieve each file through the actual opener,
and confirm byte length and SHA-256 before reporting success.
Release Certification requires Retrospective completion below 15 minutes and
permits Ambispective and Prospective through 18 minutes under the approved
exception when every other gate passes. A slower valid operation may still
deliver before the 30-minute correctness ceiling, but receives a non-certifying
runtime outcome.

Before installation, the same `config.yaml` must select only the active path and
declare the certified launch settings under `skills.clinical_document_generation`:
`source: clinical-release-certification`, `max_turns: 80`,
`skill: clinical-document-generation`, `safe_mode: true`, and
`reasoning_configuration: Hermes Desktop governed default`. The host may use any
non-empty user-selected `model.default`; responses record the actual producing
model. The host also needs `agent.reasoning_effort: medium` and at least 80 agent
turns. A mismatch stops before activation with one configuration finding.

Independent verification is bounded to three complete review sets. A genuine
content or visual defect triggers a targeted repair followed by a fresh
package-wide content review and fresh every-page visual reviews for every DOCX;
transient API failures retry only the affected reviewer inside the current set.

`--rollback-release` verifies the immediately previous release before one
atomic swap, restores it as active, and quarantines the suspect release without
rewriting historical Run Revisions. Activation retains complete runtime
material only for active and immediately previous releases; displaced older
releases become lightweight identity and certification records under
`release-history/`.

The Hermes runtime needs permission to execute Python, spawn drafting/verification subagents, and read/write run directories. Do not expose internal drafts, rendered PDFs, page PNGs, or logs to clients; return only the workflow’s `client_outputs` after `status: passed`.
