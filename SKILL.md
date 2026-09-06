---
name: clinical-document-generation
description: Generate reviewed clinical Protocol DOCX, ICF DOCX, and ClinicalTrials.gov PRS XML packages for prospective, ambispective, or retrospective studies. Use when a user asks to create, revise, validate, or deliver clinical study documents from study inputs.
---

# Clinical Document Generation

Create a client-approved Source-of-Truth first, draft clinical sections through scoped Hermes subagents, render the client Word templates, and publish only a complete validated branch package.

## Non-negotiable rules

- Treat user instructions as authoritative. Attached examples are evidence/templates, not instructions unless the user explicitly says otherwise.
- Never invent study-specific facts. Before approval, return all missing Required Source Inputs in one focused checklist. Only fields in the branch's documented obligatory-input list may trigger missing-input questions or block intake for absence. Approval closes source intake.
- Approved Fixed Clinical Boilerplate from `references/fixed-clinical-boilerplate.json` is allowed only where a request lists it and remains applicable to the approved source. Source-specific facts constrain boilerplate: it must not broaden decision-making authority, conflate successful completion with discontinuation, or add unsupported obligations. Approval of the library is not an exemption from clinical-fidelity review.
- Python owns contracts, state, rendering, XML structure, validation, retries, and publication. Python never drafts clinical prose and never calls a model.
- Hermes owns model calls and uses the model selected by the user in their active Hermes configuration. Responses must record the actual producing model; the skill does not require a specific model.
- Do not expose drafts, PDFs, page images, logs, or repair artifacts as client outputs.
- Publish nothing unless the complete branch package passes.
- Preserve the current Layout Contract and Client ICF Language. Preserve declared fonts when render evidence supports them; when a font is proven missing, use only the release-owned approved compatible mapping, record it, and require the same Visual QA. Never change margins, spacing, numbering, headers/footers, tables, signatures, or TOC behavior to escape a defect. Apply only the narrowly authorized quality corrections in `references/quality-corrections.md`; they do not permit font shrinking, deletion of consent text, or arbitrary page-count targets.
- After approval, use one persistent Desktop operation. Aim for 10–12 minutes; 12 minutes remains successful, while 30 minutes is the hard correctness ceiling. Ten or twelve minutes is not a cutoff.
- Normal generation is not software maintenance. During ordinary client generation, the installed skill and its templates, contracts, tests, and implementation remain read-only; only the run workspace and isolated runtime caches may be written. When the owner explicitly requests development maintenance, Hermes may edit the Git-managed development checkout and push committed changes directly to the authorized Git/GitHub branch. Do not build a ZIP merely because a development edit was committed or pushed. Repackage and re-certify only when the owner explicitly requests a distributable or installable release, or before the change is installed or activated; Hermes must never edit the active certified release in place.
- For ordinary client document generation, use `--manual-review`. This complete unsigned client workflow does not require a certification key or `PROMOTION-RECORD.json`. Run certification, signing, `--bind-certification`, or `--install-release` only when the user explicitly requests a formally certified release; a missing signing key is never a generation blocker.

## Branch outputs

| Study type | Required client outputs |
|---|---|
| Prospective | `protocol.docx`, `icf.docx`, `study.xml` |
| Ambispective | `protocol.docx`, `icf.docx`, `study.xml` |
| Retrospective | `protocol.docx` |

Prospective and Ambispective use the same obligatory input contract. Retrospective uses its separate contract. For prospective/ambispective studies, select only an existing Advarra or Sterling ICF template.

The authoritative missing-input lists are `references/starred-fillout-required-inputs.md`
(Prospective/Ambispective) and `references/retrospective-required-inputs.md`
(Retrospective). Do not promote optional schema fields or downstream output
requirements into obligatory source inputs. In particular, sample-size evidence
tables, PRS provider study ID/protocol number, and PRS classification are not
obligatory intake fields. The documented sample-size justification remains
required. Preserve supplied optional data and validate its types, consistency,
and controlled vocabulary. Parser, branch/template selection, approval,
rendering, XML, and clinical-quality failures remain technical blockers; they
are not permission to request missing optional clinical inputs.

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

The release carries its pinned Linux x86_64 PDFium page renderer. Microsoft
Word or LibreOffice remains the host prerequisite for DOCX-to-PDF rendering.
Resolve one supported interpreter first and retain its absolute path; do not
delegate launch to an ambiguous `python3` command. The Desktop launcher uses
`workflow.resolve_python_runtime`, launches with the returned `executable`,
and passes the returned identity to `run_desktop_operation` so every resume is
recorded. In the examples below, `CLINICAL_PYTHON` is that validated absolute
Python 3.10+ path.

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage prepare
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage approve --approved-by "<reviewer>"
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
Python/renderer/six-module/configuration identities, synthetic fixture sources
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

The six production modules are:

```text
scripts/
├── workflow.py   # lifecycle, approval, immutable revisions, publication
├── contracts.py  # inputs, branches, sections, Source-of-Truth Markdown
├── drafting.py   # scoped Hermes requests, response validation, retries
├── rendering.py  # Protocol and ICF Word rendering
├── quality.py    # renderer, page images, content/visual verification
└── prs_xml.py    # PRS mapping, structure, repeated blocks, validation
```

Do not add a second workflow entrypoint. The installation-owned `runtime/`
directory contains only the manifest-bound PDFium runtime and packaged fonts
used by Render Assurance; host Word or LibreOffice remains the DOCX renderer.

## Run directory policy

Keep every study run under `/opt/data/clinical-document-runs/`, with exactly one
dedicated top-level folder per run. Before starting generation, derive and show
the proposed folder name, then use it unless the user requests a different
approved study title:

```text
<filesystem-safe-approved-study-title>__<study-type>__<YYYY-MM-DD>
```

Apply these rules:

1. Use the approved study title from the study input.
2. Use exactly `Prospective`, `Ambispective`, or `Retrospective` for the study-type label.
3. Use the Hermes host's current local date when the folder is first created, formatted `YYYY-MM-DD`.
4. Convert the title to a readable filesystem-safe name: replace spaces with hyphens; remove slashes, colons, and unsupported characters; and retain enough text to identify the study clearly.
5. Never reuse or overwrite a run folder. If the base name exists, append `__02`, `__03`, and so on, choosing the first unused suffix.
6. Create the selected folder directly under `/opt/data/clinical-document-runs/` and pass its exact absolute path as every workflow command's `--run-dir`.
7. Keep all source inputs, the approved Source-of-Truth, revisions, drafts, logs, QA evidence, render evidence, and final documents inside that run folder.
8. Keep final deliverables only in `<run-folder>/output/`; `client_outputs` is the workflow result field that lists those published files, not a separate directory.
9. Never generate files directly in `/opt/data`, inside this installed skill, or inside another study's run folder.
10. Never delete or alter an earlier study-run folder.
11. At completion, report the approved study title, study type, creation date, complete run-folder path, `output` path, and final deliverable filenames.

Folder selection is complete only after confirming the proposed path does not
already exist and the chosen path is the first available collision-safe name.

## Full loop

### 1. Preserve and normalize inputs

Create `<run-dir>/reference/study.reference.json` from the user’s supplied facts. Preserve raw material under `<run-dir>/input/` when available. Use the field names documented in `references/reference-schema.md`; do not add generated prose under the source fields.

Set `meta.study_type` to exactly `Prospective`, `Ambispective`, or `Retrospective`. For prospective/ambispective studies, set `meta.icf_template` to `Advarra` or `Sterling` based on the user’s choice or clear evidence. Do not guess between templates.

For prospective/ambispective studies, preserve `regulatory.prs.study_type` as `Observational` or `Interventional` when explicit source evidence supplies it; during preparation, an unambiguous classification in `design.study_design` populates the review field. If neither classification is explicit, leave it unresolved without a missing-input question or intake blocker. Never infer it from uncertain or negated design text, and never restore a reviewer-cleared value. A supplied unsupported classification still fails controlled-vocabulary validation, and missing or invalid required PRS output values still fail downstream XML validation. `meta.study_type` describes the workflow branch and is not a PRS classification.

### 2. Prepare the Source-of-Truth

Run:

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage prepare
```

- If `status` is `blocked`, inspect the single `missing_inputs` report. Ask together only for missing or conflicting documented obligatory inputs. Report technical validation failures separately; do not turn missing optional fields into intake questions or weaken downstream safety/quality gates.
- If `status` is `awaiting_approval`, use the returned `review_delivery` contract. Attach or upload the file at `review_delivery.absolute_path` as the editable `.md` review artifact, then stop.
- Do not paste the Source-of-Truth contents into chat. A chat transcription is not the review artifact and cannot be approved.
- Preserve the Markdown file exactly, including every `<!-- field:... -->` marker. The reviewer edits values inside those markers and returns or approves that file.
- If the channel cannot attach local files, provide a clickable file link to `review_delivery.absolute_path`. If neither attachment nor a file link is possible, report a delivery blocker; never substitute inline text.

The client may edit values only inside the field markers. Never reinterpret or silently “clean up” reviewer-edited values.

### 3. Record explicit approval

Only after a separate explicit approval action, run:

```bash
"$CLINICAL_PYTHON" scripts/workflow.py \
  --run-dir <run-dir> \
  --stage approve \
  --approved-by "<reviewer>"
```

If the reviewer uploads an edited Markdown file, preserve it and add `--source-md <path>`. Approval binds the exact file hash and creates an immutable revision. Any later Source-of-Truth change invalidates approval.

After approval, do not ask the reviewer any additional clinical or document-content questions. Continue the internal generation, retry, rendering, and verification loop autonomously. The next reviewer-facing response must contain either the complete `client_outputs` package or one consolidated technical repair blocker after internal retries are exhausted.

### 4. Run the bounded Desktop operation

The Desktop parent must use the shipped
`scripts/workflow.py --desktop-operation --manual-review --run-dir <run-dir>` adapter for the
entire post-approval lifecycle. Its production API is
`workflow.run_production_desktop_operation`; callers supply only the actual
Desktop file opener and, when required, the Desktop-parent visual fallback.
The adapter owns the safe-mode Hermes launcher, read-only candidate sandbox,
response authentication, and process cleanup. The operation persists its start
and cross-process UTC deadline
under the run workspace, so retries and resume calls cannot reset either. It
records every compatible runtime identity used to resume. Persisted monotonic
timestamps are never treated as portable; monotonic time is used only inside
one process and converted to the persisted UTC anchor.

For ordinary client generation, use `--manual-review` from a provisioned
candidate skill root. This mode
uses the same drafting, template rendering, content checks, and every-page
Visual QA, but labels the operation `manual_pre_release` and permits the
candidate's verified page-renderer runtime without `PROMOTION-RECORD.json`.
Its outputs are the client-review deliverables. Formal promotion, certification,
signing, and certified installation remain separate operations and are never
started by manual-review mode unless the user explicitly requests them.

The operation also persists the promoted release fingerprint, or the candidate
manifest fingerprint for `manual_pre_release`, plus the exact pending stage and
handoffs, drafting and verification attempts, delivery attempts, stage timings,
soft-budget diagnostics, cleanup evidence, and the terminal result. A missing
response redispatches only its unchanged request identity;
changed request bytes fail closed. Soft stage budgets may trigger diagnostics
or the parent visual fallback, but only the original UTC deadline terminates
the operation. A late worker or opener completion cannot change a terminal
result or confirm delivery after that deadline.

Release Certification calls `run_production_desktop_operation` from an
extracted, hash-verified candidate release built from the exact commit recorded
in its manifest and binds its fingerprint. The corpus controller may prepare
fixtures and reduce evidence but must not inject a test-only worker launcher. It must not
import or launch the editable checkout, and it does not replace the operation's
30-minute deadline with a harness timeout. The certification adapter must wire
visual fallback to a Desktop-parent review callback; it must never redispatch
that fallback through the worker launcher. A valid operation above 15 minutes
may deliver but receives a non-certifying runtime outcome.

Resolve the installed skill root from the currently loaded `SKILL.md` location
or runtime entrypoint. Never copy a repository path from prior run evidence or
assume macOS path separators. A machine-local launcher may record the resolved
absolute path for that one host and operation, but that launcher is run evidence
and must not be packaged or reused on another machine.

`generate` is the deterministic inner step used by that operation. Do not run
an independent open-ended `generate` loop as the normal delivery path. When
developing or diagnosing the inner lifecycle outside a client request, its CLI
form is:

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage generate --manual-review
```

The workflow advances deterministically until it passes, blocks, or returns `status: awaiting_hermes` with one or more request paths.

For every `awaiting_hermes` response:

1. Use the returned `handoffs` as routing metadata. Resolve each `request_path` and `response_path` relative to `revisions/<revision_id>/`.
2. Keep request contents out of the parent orchestration context. The parent must route paths without reading request JSON; each assigned subagent reads its own request completely.
3. Send one request path to each subagent and dispatch all returned handoffs concurrently. Never combine multiple request files in one subagent. If the delegation limit is lower than the handoff count, start one isolated `hermes chat -q` background process per handoff in the same turn instead of shrinking the wave.
4. Give each subagent the absolute request path, revision directory, exact response path, and task. Require exact response JSON with no Markdown commentary and validation with the repository validator before completion. For `task: prs_narrative_drafting`, the response must use a `narrative` object containing exactly `brief_summary` and `detailed_description`; do not return `section_results` for PRS requests.
5. Keep the parent turn alive with one bounded wait for every exact `response_path`. A handoff is complete when its exact response file contains parseable JSON bound to the request ID and hash. At that point, terminate and reap only that owned worker within the cleanup reserve, then advance without waiting for its final chat self-report. If a delegated visual reviewer fails or times out, the Desktop parent must inspect every page image bound by that same request and return the complete outer verification-response object. The external parent-review launcher must stream the reviewer's raw stdout unchanged; it must not choose the last decoded JSON object or save a nested `finding` object. The installed workflow selects and atomically saves only the unique object bound to the request schema, ID, hash, and task. Deterministic checks alone never count as Visual QA. Completion means every response path satisfies this condition; a missing drafting response at the operation deadline is one consolidated technical blocker and does not consume a drafting retry.
6. Rerun `--stage generate`. The next `generate` call is the authoritative response validator; it accepts valid drafts, schedules targeted retries for rejected drafts, and returns the next handoff wave.

Repeat until the workflow passes or blocks. A missing response remains pending and does not consume a retry.

`awaiting_hermes` is internal orchestration state. Do not expose its requests, findings, drafting decisions, or progress questions to the reviewer.

During normal generation, use the provisioned `CLINICAL_PYTHON`; do not patch
code or templates, install packages,
run the repository development test suite, create a recovery operation, or
start a new deadline. An implementation defect becomes one technical blocker
for separate maintenance. Emit concise stage changes and a brief update at
least once per minute during a healthy wait.

## Why the work is split this way

For Prospective and Ambispective studies, the first drafting wave uses four parallel subagents:

1. `protocol-foundations`
2. `protocol-operations`
3. `protocol-analysis-and-oversight`
4. `icf-narrative`

After Foundations is accepted, a fifth subagent handles only the two PRS narrative values. Retrospective studies use the three Protocol batches and skip ICF/PRS.

This is the cost/quality balance approved for the skill:

- A single Protocol agent carries too much context and makes section omissions harder to isolate.
- One agent per tiny section adds avoidable cost and inconsistency.
- Three coherent Protocol batches let agents specialize while Python assembles one ordered contract.
- One ICF batch keeps participant language consistent across the consent form.
- The PRS narrative agent cannot alter XML; Python preserves the client-approved taxonomy and structure.

Subagents return section-level structured content, never a whole document. The workflow validates section IDs, request hashes, evidence references, boilerplate references, completeness, and forbidden placeholders before accepting a response.

For source-rich protocol sections, each drafting contract includes an
`approved_source_word_count` and a conservative `reference_detail_target_words`
soft compression signal. Semantic source coverage, not word count, governs
acceptance: retain the supplied clinical, statistical, visit, eligibility,
safety, retention, injury, and intervention detail without padding, repetition,
invention, or source-gap commentary. The Document Section Contract owns the
optional source-mode Section 8.3 and renders supplied treatment assignment
verbatim. Its typed table contracts render structured visit/procedure
relationships as the complete Schedule of Assessments and structured
sample-size evidence as its own Section 11 table. Both tables must preserve the
contracted headers, row and column order, cell associations, allowed blanks,
timing, and values before release.

## Retry behavior

- Maximum: three attempts per stable section target.
- Invalid draft: retry only failed section IDs in their existing batch.
- Post-approval source-shortfall response: reject it as an invalid draft and retry only the affected section using approved evidence and its listed Fixed Clinical Boilerplate. Never reopen reviewer intake.
- Content contradiction: retry only implicated sections unless the approved source conflicts.
- Visual defect: repair/rebuild the affected layout artifact and rerun rendered-page verification.
- Reuse unaffected accepted drafts.
- A fourth attempt is never created. After three failed attempts, block with `reference/repair-report.md` and no client outputs.
- Independent verification runs in at most three complete review sets. If any content or visual reviewer finds a governed repairable defect, preserve the failed evidence, repair only the implicated draft/layout target, then rerun the package-wide content review and every document-scoped visual review against the repaired candidate. Never reuse a pass from an earlier set.
- A transient API or malformed-routing response retries only that reviewer within the current set and does not consume a new complete review set. If the third complete set still finds a defect, preserve the candidate and block with `reference/repair-report.md`.

## Independent verification

After rendering, `generate` returns one package-wide content request plus one
document-scoped visual request for each rendered DOCX. Run all requests
concurrently so every-page image inspection stays off the serial critical path:

- `clinical_content_verification`: checks source fidelity, every required section, unsupported claims, cross-document consistency, and participant-facing ICF language.
- `rendered_page_visual_verification`: each request inspects every supplied page PNG for one Protocol or ICF document and every listed check.

The visual verifier must use image inspection. File existence, DOCX text extraction, or PDF page count alone is not visual review. Visual QA is bound to the exact DOCX, PDF, and page-image hashes, and its response must include every page number and exact PNG hash with every requested check. Any changed document, PDF, or page image invalidates earlier evidence; missing or stale assessments block delivery.

Every independent verification response records both `producer.model_id` for the actual selected model and `producer.reviewer_id` for the independent reviewer role. These identities are mandatory, distinct bindings in Final Exact-Artifact Review; neither field selects or restricts which model the client may use.

Each request records its one-based `review_set`. A genuine finding invalidates
the entire prior verification set after its evidence is archived; all reviewers
then run concurrently on the repaired candidate. Missing or invalid repair
routing is treated as an incomplete reviewer response and must be corrected by
that reviewer—it is never silently ignored or guessed by the workflow.

The Generation Manifest contains one hash-bound monotonic gate ledger in this
fixed order: clinical fidelity; content completeness and consistency; DOCX/PRS
structure; exact-artifact rendering; every-page Visual QA; exact-byte atomic
delivery. Each gate records its evidence hash, retry owner, terminal status, and
stable machine-readable findings. A later gate cannot pass while an earlier gate
is pending or blocked. A blocked record is terminal and immutable; a governed
retry starts a new retained attempt rather than replacing or erasing that failed
evidence. Each archived attempt stores its blocked ledger, and every later ledger
binds the ordered predecessor ledger hashes and blocked findings under the same
Run Revision attempt identity. The working reference also binds every retained
attempt directory to its manifest and ledger identities; missing, mutated,
duplicated, or forked attempt history blocks retry, resume, and publication.
Publication reconciles the complete candidate
inventory with exactly one passed render row and nonempty page evidence for each
DOCX, then rehashes every candidate DOCX/XML, PDF, and
page image against the accepted build immediately before staging, then rehashes
the staged client bytes before the atomic swap. Desktop confirmation advances
only the final pending gate and is persisted in the Desktop operation result.
Terminal replay revalidates both prepared and final ledgers and permits only that
one delivery-gate transition.

The deterministic render gate rejects pages with no meaningful body content, even when running headers or page numbers are present. Visual review must evaluate sparse continuation, signature, and consent pages according to their actual content and function. A sentence continuing across pages is not a content error; preserve meaningful choices and usable signature space rather than treating every sparse page as blank.

Candidate construction does not depend on the render environment. Build the complete Protocol/ICF/XML candidate first, then resolve DOCX rendering through host Microsoft Word or LibreOffice. Tool failure may advance between those office renderers; a successfully rendered visual defect stays bound to that renderer and enters repair instead of switching to obtain an easier pass. Page rendering always uses the release-owned `pypdfium2` 5.13.0 runtime. If PDFium fails, stop with the governed diagnostic; never discover or use another PDF backend.

Font evidence is tri-state. `available` preserves the declared font; `missing` selects the explicit release-owned compatible Liberation mapping and writes that substitution into the candidate; `unknown` preserves the declared font and decides capability through the disposable render smoke. Heuristic host substitutions are not accepted, and “cannot inspect” is never treated as “missing.” The manifest records renderer attempts, the one PDFium identity, font evidence, substitutions, exact artifact hashes, and page-image review. Installation owns offline PDFium provisioning and verifies the host office prerequisite; normal generation remains read-only.

## Word template authorities

- Every Protocol branch uses the bundled Protocol client authority for page geometry, typography, headers/footers, heading hierarchy, document-control surfaces, and table design.
- Protocol body sections use natural content-driven pagination and the Client Template Authority's spacing rhythm. Preserve the template's page breaks except the narrowly authorized Section 15 correction in `references/quality-corrections.md`; ensure the Table of Contents and its first following body section each begin at a page boundary without adding breaks before later body sections. Keep every heading with its first substantive paragraph, list, or table.
- Advarra ICF output uses the bundled Advarra authority; Sterling output uses the bundled Sterling authority.
- Protocol templates provide the shell and design. Accepted source-bound Section Drafts replace every clinical leaf body; client-example study facts are never reused.
- ICF templates retain their applicable client regulatory and consent language. Every accepted ICF Section Draft must also be visible, while example-study eye, cataract, intervention, cost, payment, or alternative-treatment statements are removed unless the approved source itself supports them.
- `meta.date` defaults once, during `prepare`, to `dd MMM yyyy`. `meta.version` remains blank unless the approved source supplies it.

## PRS XML authority

- Keep `assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml` as the structural authority derived from the client’s correct manual XML.
- Python alone owns XML tags, ordering, optional nodes, namespaces, escaping, and repeated blocks.
- Derive intervention, arm, primary/secondary/other outcome, and location counts from the approved source—not from generated fields.
- Validate every source-backed value inside every intervention, arm, outcome,
  and location block in addition to validating repeated-block counts and the
  client template's tag order and structure.
- The PRS subagent may return only `brief_summary` and `detailed_description` prose.
- Any XML failure blocks the complete Prospective/Ambispective package.

## Completion

Artifact validation and delivery are separate obligations. `generate` may
produce a passing Generation Manifest, but the Desktop operation is successful
only after the actual opener retrieves every `desktop_reply.attachments` file
and confirms its byte length and SHA-256 against that manifest. Retry transfer
of the same validated bytes within the remaining deadline; never regenerate to
repair transport. The final reply must expose exactly those attachments as
openable Desktop files, not inline-code paths, and must not include QA artifacts.

`status: passed` at `stage: desktop_delivery` with
`delivery.confirmed: true` is the only completed delivery state. Record elapsed
time and its runtime classification. A 10–12 minute result meets the normal
target; a successful result above 12 minutes is diagnostic evidence but remains
within the operation until the 30-minute correctness ceiling.

If `status: blocked` after all internal retries, return one consolidated technical blocker and repair report; do not ask supplemental clinical questions or present partial documents as usable. A complete candidate retained under `revisions/<revision-id>/candidate/` is internal evidence only until Render Assurance passes.
