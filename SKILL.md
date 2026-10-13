---
name: clinical-document-generation
description: Generate reviewed clinical Protocol DOCX, ICF DOCX, and ClinicalTrials.gov PRS XML packages for prospective, ambispective, or retrospective studies. Use when a user asks to create, revise, validate, or deliver clinical study documents from study inputs.
---

# Clinical Document Generation

Generate source-grounded clinical documents through one approval, independent AI review, general-tool repair and complete file delivery. AI owns meaning and visual usability. Code owns input/schema presence, approval and source identity, native-file integrity, required inventory, supported XML structure, rendering and exact-byte delivery.

## Before generation

Run commands from this skill folder using the validated absolute Python 3.10+ interpreter in `CLINICAL_PYTHON`. Read [runtime-and-release.md](references/runtime-and-release.md) for first-host setup, a fresh unsigned candidate, renderer/runtime failure, or explicitly requested packaging, certification or installation. Preserve its Linux dependencies, font/renderer contracts and manual-candidate provisioning checks. Ordinary client generation uses `--manual-review`; installation and certification are separate owner-authorized operations.

The installed skill, templates and runtime implementation stay read-only during generation. AI repairs actual document files and scripts inside the run's declared workspace. Preserve approved facts, applicable client legal language, typography and template hierarchy. Clinical guidance and authorized layout corrections are in [quality-corrections.md](references/quality-corrections.md); consult it when drafting or repairing affected content. Review applicability against the source rather than treating a phrase matcher as clinical authority.

## Branch outputs

| Study type | Complete required set |
| --- | --- |
| Prospective | `protocol.docx`, `icf.docx`, `study.xml` |
| Ambispective | `protocol.docx`, `icf.docx`, `study.xml` |
| Retrospective | `protocol.docx` |

Prospective/Ambispective use the selected Advarra or Sterling ICF template and [starred-fillout-required-inputs.md](references/starred-fillout-required-inputs.md). Retrospective uses [retrospective-required-inputs.md](references/retrospective-required-inputs.md). These lists define obligatory inputs; optional fields stay optional. If both optional Provider Study ID and protocol number are absent, preparation assigns a stable visible `ADM-...` administrative identifier, not a clinical fact.

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
8. Keep verified deliverables in `<run-folder>/output/` and labeled review copies in `<run-folder>/review-output/`. A terminal failed Desktop operation writes only the diagnostic ZIP to `output/`; report its path and terminal findings without presenting it as a deliverable. `client_outputs` lists only passed deliverables; `review_outputs` lists only review copies.
9. Never generate files directly in `/opt/data`, inside this installed skill, or inside another study's run folder.
10. Never delete or alter an earlier study-run folder.
11. At completion, report the approved study title, study type, creation date, complete run-folder path, `output` path, final deliverable filenames, and total generation time in minutes and seconds. Use the operation result's recorded `elapsed_seconds` (also persisted in the Desktop operation state); do not estimate it from chat timestamps.

Folder selection is complete only after confirming the proposed path does not
already exist and the chosen path is the first available collision-safe name.

## Ordinary workflow

### 1. Interpret the source

Preserve supplied files in the run's `input/` directory. Extract source-grounded values to `reference/study.reference.json` using [reference-schema.md](references/reference-schema.md). Read [intake-workflow.md](references/intake-workflow.md) when interpreting source files. Set `meta.study_type` to the actual supported branch; resolve the Advarra/Sterling choice before source review when an ICF is required.

Compare the branch's obligatory checklist with preserved evidence. Resolve extraction omissions yourself; ask one consolidated question for genuinely missing obligatory facts or material source conflicts. Preserve coherent timelines, units, addresses and paraphrases even when a parser cannot interpret them. Complete inputs can be concise. For an explicitly observational study, record `regulatory.prs.study_type` as `Observational`; no assigned test article is required. Derive harmless activity names/types from explicit facts or record not applicable, and show normalizations for approval. Never invent a study fact to satisfy construction.

### 2. Present the editable Source-of-Truth

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage prepare
```

Read `intake_review` and assess its raw conflict/candidate evidence against source. `awaiting_approval` means the file was prepared, not that AI completed intake assessment. For actual missing obligatory inputs, present the single consolidated checklist; technical schema failures receive separate tool feedback.

Attach/upload `review_delivery.absolute_path` as the editable Markdown file and expose `review_delivery.link` in chat when the recipient can access it. A remote host-local path needs the channel upload mechanism. Use `source_review_reply.message` and its attachment payload; report a delivery blocker if neither attachment nor accessible link is possible. Do not paste the Source-of-Truth contents into chat. Preserve every field marker and stop for separate explicit approval.

Example reply: “Please review the attached editable Source-of-Truth: {review_delivery.link}. You can edit its marked values or approve this exact file.”

### 3. Bind approval

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage approve
```

For an uploaded edited file, append `--source-md <path>`. Use `--approved-by` only if the user supplied reviewer identity; otherwise the default is `client`. Approval binds exact saved bytes and creates an immutable revision. Approval closes intake; preserve the approved source throughout generation and repair.

### 4. Generate, independently review and repair

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --desktop-operation --manual-review --run-dir <run-dir>
```

Use this bounded Desktop adapter for the entire ordinary post-approval lifecycle. It owns provider readiness, authenticated worker requests, supported runtime identity, rendering and cleanup. The same persisted UTC start/deadline and pending request identity survive resume; record the promoted release fingerprint, or the candidate manifest fingerprint for `manual_pre_release`.

For returned work, read the exact request and write its response at the declared path. Hermes uses the user's configured model and records actual author/model identity. Section authors receive scoped evidence, purpose, relationships and applicable fixed boilerplate. Source facts constrain boilerplate. Independent content and every-page visual reviews run concurrently when their evidence is available; the content reviewer inspects actual native files including tables, headers/footers and XML values. Visual reviewers inspect actual bound page images. Use the bounded parent fallback described by the adapter as soon as delegated visual work fails or times out, while content work continues. Delegated visual waves normally have four minutes; each parent callback has at most eight minutes for complete page inspection, and scheduled content units have at most three minutes per wave within the original operation deadline, with time reserved for delivery. Missing images or responses are incomplete review. Correct malformed tool arguments or switch supported equivalent tools within task access boundaries. Paginate large reads and batch independent inspections; preserve the exact request and source bindings.

The content scheduler assigns at most three sections or two cross-document checks per immutable unit, with at most three workers in a wave. Read the unit's `readable_native_evidence` and scoped approved facts first. These are hash-bound native passages, structured tables, headers/footers/text boxes and XML values with locations, not drafting summaries. Full native inspection and the canonical parent source remain available for ambiguity; formatting XML is a fallback rather than routine clinical reading. Use `review_transport.index_path` and its bounded packets if any ordinary read truncates.

Save completed judgments to the unit's declared `progress_path` with exact response bindings and actual reviewer/model identity. That audit checkpoint is the only writable review file; candidates and source remain read-only. Return completed partial judgments if interrupted. The scheduler retains them, assigns only missing scope, and shrinks stalled groups to single sections. Productive work is not subject to a package-wide two-replacement cap; repeated no-progress waves stop within the same operation deadline. Explicit validator feedback accompanies retries. A substantive partial finding goes to normal native document repair before unrelated review completes; it remains in the audit/report rather than being replaced by a generic tooling error. Fresh required content/cross-document and applicable visual reviews still precede client-ready delivery after repair. Older revisions without a review plan retain their original bounded transport fallback.


Drafting requests include only relevant [worked writing examples](references/drafting-examples.json). They demonstrate concise prose using synthetic facts; the current approved source and section instructions govern the actual document.

A substantive AI concern triggers `document_repair`. Read [general-document-repair.md](references/general-document-repair.md) for its workspace, response and concern-continuity contract. Use general DOCX/XML libraries or run-local scripts to correct actual paragraphs, tables, headers/footers or XML nodes. Batch real findings, explain source-grounded disputes, and return `needs_review` if no productive safe correction remains. Keep native-file inventory and source identity intact. A separate reviewer reassesses disputes; a generic pass cannot erase an explicit unresolved concern. Ordinary stylistic preferences need no repair cycle or client warning.

The workflow adopts corrected bytes, checks native files/XML and obtains fresh independent package-wide content and cross-document review after each repair. Changed DOCX receive fresh rendering and every-page visual review. Passing visual evidence may be retained only when native/PDF/page bytes, renderer identities, source and generation authority are unchanged and no new applicable visual concern exists. Retain the original reviewer, request, response and review-set identity; report reused assessments accurately. Accepted corrections must survive later construction. Attempting a correction is not evidence of success.

### 5. Deliver the complete package

- **Client-ready:** `status: passed`, `stage: desktop_delivery`, `delivery.confirmed: true`; complete usable branch set, objective checks, fresh final content review and exact-byte independent visual assessments passed, substantive concerns resolved, exact reviewed bytes retrieved. Expose every `desktop_reply.attachments` file as a clickable accessible link or uploaded attachment. Keep fixed defects, dismissed concerns and style preferences internal.
- **Review-only:** `status: review_required`; expose every `review_outputs` file plus `review_notice` and `review_findings`. State “Review copy — not client-ready,” list unresolved concerns with supplied locations, and identify incomplete assessments. Exact-byte `review_delivery.confirmed` establishes transfer only, never clinical approval. Notices remain outside clinical documents.
- **Unavailable:** no complete trustworthy usable set; report one consolidated technical blocker and retained diagnostic evidence. Partial, corrupted or source-untrustworthy files are not a delivered package.

Keep previews, PDFs, page images, draft/review requests and logs internal. Repeated terminal handoff validates the saved exact files; it never regenerates or resets the operation. Preserve prior successful outputs and prior operations.

Aim for **under 25 minutes** from generation start through confirmed complete delivery, excluding the human approval wait. Use recorded `elapsed_seconds`, stage timings and repair history; report clean and repaired runs separately. This target is not a demonstrated promise or approval waiver. The original **45-minute** ceiling remains fixed across processes. At the ceiling stop generation/repair and return a complete usable trustworthy review-only set when available, with honest unresolved/incomplete notices. Otherwise return unavailable with diagnostics. A later retry is a separate owner decision and must not be reported as success in the terminated operation.
