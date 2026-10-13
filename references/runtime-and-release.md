# Runtime setup and release maintenance

Read for a new host, fresh candidate extraction, runtime failure, or an explicitly requested release/installation operation. Ordinary study generation resumes in SKILL.md after verified provisioning. Certification timing criteria here are separate from the under-25-minute ordinary target.

## Restricted Hermes TUI compatibility

Owner-authorized unsigned manual candidates support `--host-mode hermes-tui`
with `--desktop-operation --manual-review`. Select this explicitly on existing
restricted Linux hosts; the default isolated mode still requires its full
installed lifecycle evidence. TUI mode does not require Bubblewrap, namespace
permission, a recipient opener, or a synthetic paid capability campaign.
Provisioning and installation rendering checks still apply after replacement.
Use the existing Linux interpreter, office runtime, fonts and configured model.

TUI preflight checks actual profile authentication and installed evidence reads.
Worker capabilities are observed during the real operation; a failed tool is
review feedback or an honest blocker, not a fabricated assurance-cache pass.
Workers retain private mutable Hermes state and controlled process cleanup.
Source/request/artifact hashes authenticate judgments, and every worker wave
checks installed package integrity before and after execution. These detect
changes; they do not establish OS-enforced write or network denial. Safe mode
and host permissions are the execution boundary. This mode is excluded from
certification and promoted execution.

Final local files are checked against the exact manifest bytes. Terminal state
records `recipient_delivery_verified: false`, local availability and no recipient
confirmation. The recipient-delivery gate remains pending. Resuming the same
operation rechecks those bytes and preserves the original deadline. Genuine
independent native and page-image review is still required for clinical approval;
missing parent visual fallback yields incomplete review, never an assumed pass.

## Public interface

Run commands from this skill folder. `scripts/workflow.py` is the only CLI entrypoint.
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

Before starting a study Desktop operation, verify the selected provider login in
the same isolated `HERMES_HOME` used by its workers. A login in the dashboard's
profile does not establish a login in another profile. The shipped adapter
records `logs/worker-readiness.json` before creating the study deadline; resolve
a failed login there and start a fresh operation. An authentication rejection
during generation stops immediately with `worker_authentication`.

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage prepare
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage approve
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage validate
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage generate --manual-review
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --desktop-operation --manual-review --desktop-opener-command <opener> --parent-visual-review-command <reviewer>
"$CLINICAL_PYTHON" scripts/workflow.py --format-conformance --format-conformance-root <evidence-root>
"$CLINICAL_PYTHON" scripts/workflow.py --release-gate
"$CLINICAL_PYTHON" scripts/workflow.py --package-release /absolute/path/clinical-document-generation-release.zip
"$CLINICAL_PYTHON" scripts/workflow.py --bind-certification /absolute/path/release-certification-corpus.json --release-archive /absolute/path/clinical-document-generation-release.zip
"$CLINICAL_PYTHON" scripts/workflow.py --install-release /absolute/path/clinical-document-generation-release.zip --skills-dir /absolute/path/to/hermes/skills --hermes-config /absolute/path/to/hermes/config.yaml
"$CLINICAL_PYTHON" scripts/workflow.py --verify-installation
"$CLINICAL_PYTHON" scripts/workflow.py --rollback-release --skills-dir /absolute/path/to/hermes/skills
```

`--package-release` creates the immutable candidate from the current clean
commit. Provision the extracted certification candidate with
`--provision-candidate`, run the full real corpus, and set
`CLINICAL_DOCUMENT_CERTIFICATION_PRIVATE_KEY` to the authorized external RSA
private-key JSON before embedding its passing report with `--bind-certification`.
The private key must never be copied into the repository, archive, evidence
bundle, logs, or installation. Only that one certified archive may be activated
with `--install-release`; direct extraction is not a
supported update path. Installation verifies host Word or LibreOffice, installs
the one manifest-bound `pypdfium2` wheel offline, verifies every extracted file
against the immutable wheel-derived inventory, and runs page rendering in a
killable worker with governed time, page, pixel, dimension, output, and process
resource limits. Before staging or archive access, installation requires the
current resolved Python 3.10+ interpreter and records its implementation,
version, resolved executable path, and executable SHA-256 in installation
assurance. It runs an end-to-end render/page-image smoke, reruns manifest,
certification, and runtime-integrity verification immediately after each
provisioner/verifier hook and before invoking the next hook, rejecting a symbolic
link at the skill root or any manifest-owned path
component, and only then writes installation records. Before the first namespace
mutation, installation durably commits an inode-bound activation journal with an
atomic JSON replacement and parent-directory sync. The atomic candidate-to-active
rename is the activation commit point. Every ordinary failure before it restores
the exact prior active and previous releases and removes only transient history
created by that attempt; an interrupted process is reconciled from the journal
before any later staging. Inode identity distinguishes a committed candidate from
the prior active release even when their package fingerprints match. Failures
cleaning deterministic fingerprint-named displaced state or the transaction
journal after that commit point are reported as successful activation with
deferred-cleanup findings; they never become false installation failures. The
newly activated release remains selected. A failed smoke leaves the previous
verified release active. One rollback operation completely revalidates the
immutable previous release's manifest, certification/evidence, and PDFium runtime,
copies it to an isolated system-temporary directory outside the live release
namespace, completely verifies that copy, runs executable
integration smoke only against the copy, and completely revalidates the copy after
smoke. The retained previous release is also completely revalidated after the
callback and immediately before the swap. Rollback then
commits an atomic previous-to-active swap. A durable inode-bound rollback journal restores a failed
pre-commit swap on retry or recognizes an already committed rollback. The suspect
release is quarantined under its fingerprint without rewriting retained run
revisions. The archive contains
`RELEASE-MANIFEST.json` and the bound `RELEASE-CERTIFICATION.json`. Installation
also requires Hermes `skills.external_dirs` to name only the promoted active
path, validates recorded model provenance plus the certified reasoning/safe-mode/turn settings declared
under `skills.clinical_document_generation`, and records the activation in
`PROMOTION-RECORD.json`.

The bound certification report contains a deterministic
`release-certification-evidence/v1` bundle. Its canonical inventory retains the
exact release manifest, preflight report and logs, deterministic/layout evidence,
Python/renderer/production-module/configuration identities, synthetic fixture sources
and approvals, all three raw case/state/manifest records, output bytes, drafting
and verification exchanges, parent-process completion records, PDFs, and every
reviewed page image. The complete canonical report is signed with the external
private key; binding and installation verify that detached signature against
`references/release-certification-public-key.json`, whose exact bytes are bound
by the immutable release manifest. Signer and verifier derive its key identity
through one shared canonical hash of algorithm, exponent, and modulus. They then
independently decode and rehash every item, cross-check all semantic links, and
reject unsigned, missing, substituted,
ambiguous, stale, or unrelated evidence. The bundle is limited to 512 files,
32 MiB per file, and 128 MiB total. It rejects symlinks and path aliases and
must not retain credentials, private session logs, editable-checkout debris, or
client/patient data; fixture provenance must explicitly be synthetic and
non-private.

Before either binding or installation extracts an archive, the archive is limited
to 1,024 members, 64 MiB per ordinary member, 195,734,187 bytes for the encoded
certification report, 329,951,915 uncompressed bytes in total, and a 100:1 maximum
compression ratio. Any excess fails before extraction.

The manifest
hashes every packaged file and records implementation, template, contract,
font, renderer, harness, and model provenance. It excludes development
environments, credentials, source/patient data, old runs, and tests.

Run certification in the fixed order Retrospective, Ambispective–Sterling,
Prospective–Advarra. Retrospective must remain below 15 minutes. The approved
Ambispective and Prospective exception permits completion through 18 minutes
only when rendering, every-page Visual QA, formatting preservation, content,
delivery, and every other certification gate pass unchanged.

The release gate never fabricates verifier approval. If it returns
`awaiting_hermes`, run the returned content and every-page visual verification
requests, save their exact responses, then resume the same corpus with:

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --release-gate --release-gate-root <evidence_root>
```

Before live certification, `--format-conformance` runs the immutable matrix in
`references/format-conformance-matrix.json`. It covers Retrospective Protocol,
Prospective–Advarra, Prospective–Sterling, Ambispective–Advarra, and
Ambispective–Sterling using exact hash-addressed fixtures, templates, and client
authorities. It also compares every generated DOCX with an approved normalized
OOXML baseline under `references/format-baselines/`, covering section geometry,
styles, numbering, headers/footers, fields/TOC, page furniture, table geometry,
signature/legal placement, paragraph rhythm, and relational pagination controls
without relying on whole-DOCX equality. Every governed heading is bound to its
actual first substantive paragraph, table, or child heading on the same rendered
page; missing successors and unrelated page text fail. Its `structural_passed` result is
deterministic structural evidence only: it cannot substitute for clinical
verification, genuine every-page image inspection, production certification, or
exact-byte Desktop confirmation.

The production modules are:

```text
scripts/
├── workflow.py   # lifecycle, approval, immutable revisions, publication
├── contracts.py  # inputs, branches, sections, Source-of-Truth Markdown
├── drafting.py   # scoped Hermes requests, response validation, retries
├── rendering.py  # Protocol and ICF Word rendering
├── quality.py    # renderer, page images, content/visual verification
├── prs_xml.py    # PRS mapping, structure, repeated blocks, validation
└── output_recovery.py # general native document workspaces and checkpoints
```

Do not add a second workflow entrypoint. The installation-owned `runtime/`
directory contains only the manifest-bound PDFium runtime and packaged fonts
used by Render Assurance; host Word or LibreOffice remains the DOCX renderer.


## Installed worker capability evidence

Spec #114 requires owner-authorized probes before clinical admission. Ordinary
generation neither provisions dependencies nor runs a maintenance/model suite.
The tiny authentication/read probe is diagnostic only. Admission additionally
requires `clinical-capabilities/<package-manifest-sha256>/assurance.json` under
the isolated Hermes profile, outside the immutable skill package.

The `worker-capabilities/v1` report records `identity` (package manifest hash,
Hermes launcher/interpreter hashes, configuration hash and actual selected model,
compatible Python hash, office renderer hash, host font hashes and installed
Hermes tool hashes) and `capabilities`. Use the exact identity returned by the
installed probe collector; never hand-author passing observations. Each capability
has `status: passed` and nonempty `evidence_files` with report-relative paths and
SHA-256 hashes. Retain requests, raw results, actual observer identity and outcomes;
never credentials. Changing any bound dependency or evidence invalidates admission.

Exercise every capability listed in `scripts/worker_capabilities.py` through the
actual installed ordinary adapter: worker launch, realistic bounded reads,
checkpoint write/readback, actual page-image inspection, DOCX/XML execution,
genuine parent fallback, actual recipient attachment retrieval, sentinel write
denials, permitted/denied network routes, and worker/child termination. Reviewer
writes are limited to its declared checkpoint; the parent publishes final JSON.
Repair authors can also edit declared native/script workspaces. Include source,
installed-code, sibling-review and earlier-run sentinel denials. Narrow runtime
state belongs to each dispatch. A local self-read cannot establish recipient
access, and serialized image bytes cannot establish actual image inspection.

The consolidated campaign and its exact host probe collector require independent
review before execution. Missing evidence is an accurate capability blocker,
not permission to fabricate a report or use certification-only isolation.


The repository supplies the installation probe collector (it is not shipped as
an ordinary generation command). After separate owner authorization, run it
with the validated compatible Python against the exact installed Linux root:

```sh
"$CLINICAL_PYTHON" tests/installed_capability_campaign.py \
  --release-root /absolute/installed/skills/clinical-document-generation \
  --desktop-opener-command /absolute/recipient-opener \
  --parent-visual-review-command /absolute/desktop-parent-reviewer \
  --approved-by "<owner approving synthetic fixture>" --authorize-paid-probes
```

This collector executes real ordinary sandbox launches, installed bounded
read/write tools, harmless sentinel denial/network probes, native DOCX/XML
execution and child termination. It then runs two independent synthetic
Retrospective Desktop lifecycles using real Hermes: delegated image review and
genuine parent image review, both with real recipient retrieval. It preserves
all failed attempts and raw evidence, and writes the admission cache only after
complete coverage and unchanged dependency identity. The probes do not count
as baseline/supplemental readiness observations or release certification. It
never installs or activates anything. PDFium runtime integrity/metadata and
recipient/parent executable identities also invalidate the cache on change.
