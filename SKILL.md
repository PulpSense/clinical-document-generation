---
name: clinical-document-generation
description: Create local clinical study document-generation runs from unstructured study information. Use in Hermes only when a client asks to generate, create, prepare, build, or update a prospective, ambispective, or retrospective clinical study document set, including protocol, ICF, short summary, or ClinicalTrials.gov/PRS XML outputs. Also use when the client mentions prospective generation, propesctive generation, retrospective generation, ambispective generation, or asks for prospective, propesctive, retrospective, or ambispective study generation. Do not use for generic clinical document requests unless the request names or clearly implies one of these three study branches. The skill preserves raw inputs, blocks on missing required inputs, creates or parses an editable Markdown source-of-truth input map, waits for reviewer approval, populates branch-specific DOCX templates, and renders XML from local templates using local scripts.
---

# Clinical Document Generation

## Overview

Use this skill to turn unstructured clinical study context into a local, repeatable document-generation run. The skill must preserve the raw source material, draft an internal reference file, create a reviewer-editable Markdown source-of-truth input map only after required inputs are complete, then run deterministic scripts that populate DOCX and XML templates.

## Source-Of-Truth First Invariant

When the user provides study inputs and asks to "create", "generate", "make", "prepare", or "build" clinical documents, treat that request as an instruction to create the run and return the reviewer-facing source Markdown first. By default this file is named `reference/source-of-truth--<protocol>--<study-slug>.md`. The source material supplied in the same request is input, not approval.

Always stop after creating and presenting the generated source Markdown unless the user is approving a previously generated source-of-truth Markdown file or uploads an edited source-of-truth Markdown file with an explicit approval message. Do not infer approval from a request to create final protocol, ICF, XML, or other clinical documents. The reviewer may approve the source-of-truth Markdown immediately in the next message; only then record approval and run final generation.

At this source-of-truth review stage, the only user-facing output is the generated source Markdown recorded in `approval.review_file`. Keep `input/raw_context.md`, `reference/study.reference.json`, manifests, copied templates, preflight reports, logs, and other run artifacts as internal state unless the user explicitly asks to inspect them or asks for debugging details.

Reviewer-edited mapped values in a source-of-truth Markdown file are authoritative string content. After the Markdown has been generated, uploaded, edited, or approved, do not manually correct, normalize, reconcile, or "fix" mapped field values for spelling, branding, consistency with raw inputs, grammar, style, or agreement with other fields. On approval, parse the current Markdown exactly as written. Raw source material and preview text are evidence only; they must not silently override reviewer-edited field values.

Only intervene when a source-of-truth value creates a technical, flow-breaking problem, such as parser failure, missing required field markers, schema/type errors, unresolved template rendering, controlled-vocabulary rejection, XML validation failure, or another hard validation failure that prevents final generation. In that case, make the smallest technical correction required to continue, prefer fixing generated/template-adapter values rather than changing approved source Markdown, document the correction, and ask the reviewer if the needed change affects string content or semantics.

The core contract is source agnostic and template agnostic:

```text
any unstructured input
  -> create local run directory
  -> save raw source material
  -> classify Prospective, Ambispective, or Retrospective branch
  -> draft internal reference/study.reference.json
  -> for Prospective/Ambispective, resolve Advarra vs Sterling ICF template
  -> stop and ask for missing source inputs if preflight fails
  -> create one input-only reference/source-of-truth--<protocol>--<study-slug>.md for reviewer correction/approval
  -> parse the saved source-of-truth Markdown back into study.reference.json after every approval
  -> iterate until the source-of-truth Markdown is approved
  -> generate branch-specific n8n/OpenAI narrative variables from the approved source inputs
  -> validate parsed reference file and generated variables against templates
  -> populate branch-specific DOCX/XML outputs
  -> save outputs and generation report
```

## Workflow

Run script commands from this skill folder, or use absolute paths to the skill's `scripts/` files.

1. Create a run directory with `scripts/create_run.py`, passing every file the client sent as `--evidence <path>`. The files become one Source Intake Packet recorded in `input/source-intake-manifest.json`, and the whole packet — not just the first file — is read for template selection and source inspection. Markdown, plain text, JSON, CSV, PDF, and DOCX evidence is extracted to text; anything else is preserved and reported as `unsupported` or `unreadable`, and you must tell the reviewer which file that was rather than proceeding as if it had not arrived. `--raw-context` still works and simply creates a one-file packet. If no templates are supplied, `create_run.py` copies the bundled client templates for the selected study type.
2. If the input is audio and a transcription tool is available, transcribe it and save the transcript under `input/transcript.md`. If transcription is not available, ask for a transcript before continuing.
3. If the source material is unstructured, read `references/intake-workflow.md`, then normalize the source into `input/` and draft `reference/study.reference.json`.
4. Read `references/study-type-branches.md`. Normalize `meta.study_type` to `Prospective`, `Ambispective`, or `Retrospective`, then set `meta.document_set` for that branch.
5. Read `references/reference-schema.md`, then create or update the internal draft reference. Keep uncertain values as `null` and record questions in `needs_review`; do not hide gaps by inventing data. For a prospective or ambispective study, read `references/starred-fillout-required-inputs.md`. For a retrospective study, read `references/retrospective-required-inputs.md`. Record starred-field candidates under `source.field_candidates`, and distinguish repeated identical evidence from conflicting distinct values.
6. For `Prospective` and `Ambispective`, resolve the ICF template before creating the source-of-truth file. Inspect the user's current message, preserved raw context, and IRB name:
   - If exactly one of `Advarra` or `Sterling` is mentioned, select it automatically. `create_run.py` performs this detection and records the result in `meta.icf_template`.
   - If neither is mentioned, ask: `Which ICF template should I use: Advarra or Sterling?` Stop until the reviewer answers.
   - If both are mentioned without a clear single choice, ask which one to use and stop.
   - If another IRB is named, say that only the Advarra and Sterling ICF templates are available, ask which one to use, and stop.
   - After a reviewer answers, apply the choice deterministically:

```bash
python3 scripts/select_icf_template.py --run-dir <run-dir> --choice <advarra|sterling>
```

This copies the selected asset to `templates/icf.template.docx` and records the choice internally. The Sterling asset is shared by the prospective and ambispective branches. Retrospective runs skip this step because their standard document set has no ICF. Do not put `meta.icf_template` in the reviewer-facing source-of-truth Markdown; it is an operational template choice, not a clinical study input.

7. Read `references/source-of-truth-md.md`, then run the client/source-input preflight before creating any structured source document:

```bash
python3 scripts/check_required_inputs.py --run-dir <run-dir>
```

For clinical study inputs, stop only when a starred Fillout field is missing or has multiple distinct source inputs. The only separate operational blocker is the unresolved ICF template choice for a prospective or ambispective run. Ignore optional and generic `needs_review` items at this gate. If blocking inputs remain, stop before structured Markdown generation and send `reference/missing-inputs.md` or one concise consolidated checklist to the reviewer. Do not ask the reviewer to supply AI-written protocol, ICF, summary, or XML prose.

8. When required source inputs are complete and any required ICF template choice is recorded, create the reviewer-facing structured Markdown document:

```bash
python3 scripts/create_source_truth_md.py --run-dir <run-dir> --require-complete
```

Present the generated Markdown file reported by `scripts/create_source_truth_md.py` and recorded in `approval.review_file`, then stop. This Markdown file is the editable equivalent of the old n8n intake form: it should contain client-provided study facts and regulatory inputs only. It must not include AI-generated introductions, methods, goals, ICF language, summary prose, XML narrative text, or `template_fields`.

Make the editing boundary obvious for reviewers. The top study title line is a preview only and must be labeled as not editable. The Markdown must include a visible heading such as `## Editable Study Inputs Start Here` immediately before the first field block, and the instructions must tell reviewers to edit only values between `<!-- field: ... -->` and `<!-- /field -->` marker lines.

When presenting this file, return or attach only the generated source Markdown. Do not list `input/raw_context.md`, `reference/study.reference.json`, `input/source_manifest.json`, templates, logs, or preflight reports as outputs unless the reviewer specifically asks for those internal artifacts.

Do not continue to final protocol, ICF, XML, short-document, TOC, or render-QA generation in the same turn merely because the user originally asked to create or generate clinical documents. The reviewer may approve it as-is or upload an edited copy. If an edited Markdown file is uploaded, preserve it under `input/attachments/`, then parse it:

```bash
python3 scripts/parse_source_truth_md.py --run-dir <run-dir> --source-md input/attachments/<edited-source-md> --approval-status pending_review
```

After this point, the latest parsed source-of-truth Markdown is authoritative. Do not reinterpret the original messy inputs unless the reviewer provides additional corrections. Do not repair apparent typos or inconsistencies in mapped Markdown values unless they technically break the workflow as described in the source-of-truth authority rule above.

9. Read `references/approval-loop.md`. Only after the reviewer clearly approves the generated or edited source Markdown in a separate approval action, parse the saved Markdown file from disk before recording or relying on approval. This is required even when the reviewer did not upload a separate edited file, because the reviewer may have edited the generated source Markdown in place after it was presented:

```bash
python3 scripts/parse_source_truth_md.py \
  --run-dir <run-dir> \
  --source-md <run-dir>/<approval.review_file> \
  --approval-status approved \
  --approved-by "<reviewer>"
python3 scripts/check_required_inputs.py --run-dir <run-dir>
```

Review `reference/review-parse-report.md` and stop if parser warnings or missing required inputs remain. Do not assume `reference/study.reference.json` still matches the reviewer-facing Markdown just because the file was generated earlier.

Do not edit the approved source Markdown before this parse step. If a mapped value looks suspicious but does not break parsing, required-input checks, template rendering, or XML validation, preserve it exactly.

If approval is recorded separately after a parse or correction pass, use:

```bash
python3 scripts/set_approval.py --run-dir <run-dir> --status approved --approved-by "<reviewer>"
```

Use `--approval-status approved --approved-by "<reviewer>"` when parsing an uploaded Markdown file if the accompanying message clearly says it is approved or good to generate. Do not use `approved` for the initial message that supplied raw study input, even if that message asked to create final documents.

10. After source Markdown approval, generate the branch-specific n8n/OpenAI module outputs from the approved input fields and save them under `generated.protocol`, `generated.icf`, `generated.short`, or `generated.xml` as described by the branch reference. Then populate n8n-compatible template fields:

```bash
# Prospective protocol + ICF + XML branch
python3 scripts/build_n8n_prospective_fields.py --run-dir <run-dir>

# Ambispective protocol + ICF + XML branch
python3 scripts/build_n8n_ambispective_fields.py --run-dir <run-dir>

# Retrospective protocol branch
python3 scripts/build_n8n_retrospective_protocol_fields.py --run-dir <run-dir>
```

For prospective runs, read `references/n8n-prospective-protocol-icf-xml.md`. For ambispective runs, read `references/n8n-ambispective-protocol-icf-xml.md`. For retrospective protocol runs, read `references/n8n-retrospective-protocol.md`.

For prospective and ambispective runs with XML, also read `references/prs-xml.md` and build PRS XML fields after the n8n mapper:

```bash
python3 scripts/build_prs_xml_fields.py --run-dir <run-dir>
```

For prospective and ambispective studies, this command reports both all PRS gaps and the subset that corresponds to missing starred fields. Stop and ask the reviewer only when `blocking_missing_count` is nonzero. Nonstar PRS gaps remain visible but nonblocking.

11. Use the bundled templates unless the reviewer/client supplies replacements. `create_run.py` copies the bundled defaults into `templates/` using these standard names:
   - `protocol.template.docx`
   - `icf.template.docx`
   - `short.template.docx`
   - `study.template.xml`
12. Read `references/template-contract.md` before editing templates or mapping placeholders. Templates may vary, but placeholders must map to paths in `study.reference.json` or to n8n-compatible `template_fields`.
13. Validate the reference file and active branch templates. Use `--require-approval` for final output generation:

```bash
python3 scripts/validate_reference.py --run-dir <run-dir>
python3 scripts/validate_reference.py --run-dir <run-dir> --require-approval
```

14. Confirm Python 3.9 or newer is available. All scripts use the Python standard library; do not install Python or Node packages:

```bash
python3 --version
```

15. Generate outputs. Prefer the branch workflow, which maps the approved reference, renders every active template, runs all applicable Delivery Gates, and retains QA evidence in one step:

```bash
python3 scripts/generate_branch_documents.py --run-dir <run-dir>
```

It refuses to render anything while approval is missing or a Required Source Input is unresolved, and it writes `logs/branch-generation.json` plus a `logs/repair-report.md` naming every failed gate. Deliver only when `delivery_ready` is true.

The lower-level renderer stays available for partial or diagnostic runs. Use `--require-approval` for anything that could be delivered:

```bash
python3 scripts/render_templates.py --run-dir <run-dir>
python3 scripts/render_templates.py --run-dir <run-dir> --require-approval
```

16. For prospective and ambispective PRS XML runs, validate the rendered XML:

```bash
python3 scripts/validate_prs_xml.py --run-dir <run-dir>
```

17. DOCX generation must never depend on a desktop office application. After the DOCX exists, use the portable exporter for optional PDF-based visual and static TOC/index QA. Treat these PDFs as internal QA artifacts: do not deliver or list them as user-facing outputs unless the reviewer explicitly asks for PDF files. Automatic mode tries Pages on macOS, Microsoft Word on Windows, and LibreOffice on Linux, with LibreOffice as a fallback where available:

```bash
python3 scripts/export_docx_to_pdf.py \
  <run-dir>/output/<document>.docx \
  <run-dir>/logs/docx-render/<document>.pdf \
  --report <run-dir>/logs/docx-render/<document>.json
```

Read the report. If `status` is `unavailable`, keep and deliver the generated DOCX, state that PDF-based visual/TOC QA was skipped because no compatible renderer was installed, and do not run the refresh or audit commands below. This is nonblocking by default. Use `--require-renderer` only when the client explicitly requires strict renderer-based QA.

If `status` is `exported` and the DOCX contains a static index or table of contents, refresh page values and normalize index rows to real right-aligned dot-leader tab stops, then export once more and audit:

```bash

python3 scripts/refresh_static_toc.py \
  --docx <run-dir>/output/<document>.docx \
  --pdf <run-dir>/logs/docx-render/<document>.pdf \
  --report <run-dir>/logs/toc-refresh.json

python3 scripts/export_docx_to_pdf.py \
  <run-dir>/output/<document>.docx \
  <run-dir>/logs/docx-render/<document>.pdf \
  --report <run-dir>/logs/docx-render/<document>.json

python3 scripts/audit_static_toc.py \
  --docx <run-dir>/output/<document>.docx \
  --pdf <run-dir>/logs/docx-render/<document>.pdf \
  --output <run-dir>/logs/toc-audit.json
```

If `toc-refresh.json` reports `updated_count` or `aligned_count` greater than zero, always re-render/re-export before running the final audit. Repeat refresh and audit if the updated TOC changes pagination. When a renderer is available, do not present a DOCX with a static index/TOC as visually verified unless `toc-audit.json` reports zero page mismatches, zero missing headings, and zero alignment mismatches.

The final audit must not count text on the TOC/index pages as evidence that a later heading is on that page. For every TOC/index entry after the TOC/index entry itself, actual-page lookup must begin after the rendered TOC/index ends. This prevents entries such as `4. INTRODUCTION` from being accepted on the index page merely because the index contains that title.

18. Extract or read the rendered DOCX text and inspect static template prose for stale study-specific content before delivery. Placeholder validation alone is insufficient because bundled or client templates may contain hard-coded language from a prior study. Check especially for unrelated procedures or conditions, sponsor/IRB role confusion, duplicate organization suffixes such as `IRB IRB`, incorrect intervention names, and payment, cost, alternative-treatment, privacy, or regulatory-authority language that does not fit the reviewed study. Make narrowly scoped template fixes, rerender, and repeat renderer/TOC QA.

19. Review `logs/generation-report.json`, `logs/prs-xml-validation.json`, `logs/docx-render/*.json`, `logs/toc-refresh.json`, `logs/toc-audit.json`, `reference/missing_fields.md`, and `reference/review-parse-report.md` when present. Also extract and inspect the complete rendered DOCX text for stale client-template prose before delivery. The bundled prospective templates may contain legacy study-specific language such as cataract surgery, handpieces, treatment assignment, prior-to-surgery replacement, duplicated `IRB IRB`, or unrelated sponsor/payment statements even when all placeholders resolve. Replace or remove such language using only the approved study facts and generated narrative, then re-export and repeat TOC/visual QA. Do not present the output as complete if required placeholders are unresolved, approval is missing, PRS XML validation fails, stale study-specific template content remains, an available renderer finds TOC/index mismatches, or blocking fields remain in `needs_review`. A renderer-unavailable report is a nonblocking QA limitation and must be disclosed. In every branch, only conflict-tagged review items mapped to starred inputs are blocking; optional and generic review notes remain visible.

## Run Directory Contract

Use this structure for every study:

```text
runs/<study-or-protocol-slug>/
  input/
    raw_context.md
    source-intake-manifest.json
    source_manifest.json
    evidence/
    extracted/
    transcript.md
    attachments/
  reference/
    study.reference.json
    source-of-truth--<protocol>--<study-slug>.md
    missing-inputs.md
    review-parse-report.md
    missing_fields.md
  templates/
    protocol.template.docx
    icf.template.docx
    short.template.docx
    study.template.xml
  output/
    protocol.docx
    icf.docx
    short.docx
    study.xml
  logs/
    generation-report.json
```

The run structure is a superset. The active outputs are controlled by `reference/study.reference.json` field `meta.document_set`.

The raw source material is evidence. Before client review, `study.reference.json` is an internal draft. After the generated source Markdown is approved or an edited source Markdown is parsed, the Markdown file is the source of truth and `study.reference.json` is the machine-readable cache regenerated from it.

## Structuring Rules

- Preserve source text and attachments before summarizing or extracting.
- Keep raw user wording in `source.raw_summary` or `source.notes` when it helps later review.
- Separate user-provided data from generated narrative text under `generated`.
- Use `null` for missing values, not empty invented filler.
- Add each uncertainty, conflict, or missing required field to `needs_review`. For every study type, also store candidate values for starred fields under `source.field_candidates`; only missing or conflicting starred fields block the input gate.
- Keep generated protocol, ICF, short-document, and XML values in the reference file after source approval so regenerating outputs is deterministic. The ICF and shorter document should be generated from the same reviewed reference file, not by reinterpreting the original messy input.
- Treat the generated source Markdown recorded in `approval.review_file` as the human review surface for source inputs only. On every approval, parse the current saved Markdown file and regenerate `study.reference.json` from it before generating narrative, running mappers, or rendering templates. If a reviewer uploads an edited source Markdown file, preserve it and parse that uploaded copy; otherwise parse the run's recorded source Markdown from disk in case the reviewer edited it in place.
- Preserve reviewer-edited mapped string values exactly, even when they appear to be typos, brand inconsistencies, grammar issues, or conflicts with the raw input. Do not change source Markdown values for content correctness. Only make a narrowly scoped technical fix when an approved value blocks the workflow, and document that fix.
- Do not create the source Markdown while `scripts/check_required_inputs.py` reports missing required inputs. Ask for the missing information first.
- Do not include `generated.*`, `template_fields`, `approval`, `source`, or `needs_review` fields in the generated source Markdown.
- Keep `approval.status` as `pending_review` or `changes_requested` until the reviewer explicitly approves the structured reference after seeing the generated source Markdown. A same-turn request to create or generate documents from newly provided study input is not approval. Final generation should use approval-gated validation and rendering.
- For protocol/ICF/XML templates copied from the existing workflow, keep n8n-style replacement variables under `template_fields` and regenerate them from the reviewed reference before rendering.
- For ClinicalTrials.gov PRS XML, copy the canonical PRS template from `assets/client-templates/prs/` to `templates/study.template.xml`, run `scripts/build_prs_xml_fields.py`, and validate the rendered XML with `scripts/validate_prs_xml.py`.
- Do not hardcode source-channel, form-provider, or editor-specific assumptions into the reference file. Channel-specific details belong in `source`.
- Do not carry copied defaults into study-specific outputs. Investigator affiliation, organization names, site names, endpoints, outcomes, and XML values must come from the reviewed reference file or remain in `needs_review`.

## Template Rules

- Use the brace placeholder syntax in DOCX templates, such as `{study.title}`.
- Use the same placeholder paths in XML templates.
- Use loops only for arrays, such as `{#sites}{facility.name}{/sites}`.
- Avoid placeholders that rely on hidden prompt context. Every placeholder must resolve from `study.reference.json`.
- For PRS XML, the renderer also honors `template_fields.__prs_counts` to remove unused repeated PRS blocks or clone exemplar blocks for real repeated interventions, arms, and outcomes.
- Scan templates before generation:

```bash
python3 scripts/scan_placeholders.py templates/protocol.template.docx templates/icf.template.docx templates/study.template.xml
```

## Output Rules

For newly supplied study inputs that have not yet been approved, the output is only the generated source Markdown recorded in `approval.review_file`. Mention missing inputs instead when the required-input gate fails. Do not expose preserved raw inputs, internal JSON caches, source manifests, copied templates, validation logs, or run-folder inventories as user-facing outputs at this stage unless explicitly requested.

Generate whichever templates are present. A complete run usually produces:

- Prospective: `output/protocol.docx`, `output/icf.docx`, `output/study.xml`
- Ambispective: `output/protocol.docx`, `output/icf.docx`, `output/study.xml`
- Retrospective: `output/protocol.docx`
- Optional short summary: `output/short.docx`
- `logs/generation-report.json`

If exact replacement templates or XML structures are not available yet, use the bundled client templates already packaged under `assets/client-templates/`.

## Reviewer Loop

Hermes owns the channel mechanics: reading Slack/Telegram/email text, receiving uploads, and transcribing audio when a transcription tool is available. This skill owns the local state and approval gate:

1. Preserve each message, transcript, and attachment under `input/`.
2. Update `reference/study.reference.json` from all available source material.
3. For prospective or ambispective runs, resolve Advarra vs Sterling and apply the choice before source-of-truth generation. Retrospective runs skip this step.
4. Run `scripts/check_required_inputs.py`. Ask only for missing or conflicting starred clinical fields plus any unresolved prospective/ambispective ICF template choice. If blocking inputs remain, ask for all of them together and stop before creating the source Markdown.
5. Run `scripts/create_source_truth_md.py --require-complete`, send or attach the generated source Markdown path from the command output, and stop for reviewer approval.
6. If the reviewer uploads an edited source Markdown file, preserve it under `input/attachments/` and run `scripts/parse_source_truth_md.py`.
7. If the reviewer replies with corrections in text or audio instead of editing the Markdown file, update the internal reference, rerun the preflight, and regenerate the named source Markdown.
8. When the reviewer clearly approves the generated or edited source-of-truth Markdown file, first parse the current saved Markdown with `scripts/parse_source_truth_md.py --source-md <run-dir>/<approval.review_file> --approval-status approved --approved-by "<reviewer>"`, rerun the required-input preflight, review the parse report, then validate and render with `--require-approval`. Do not alter mapped Markdown values before parsing unless a technical issue prevents parsing or final generation.

## References

- Read `references/intake-workflow.md` when converting messages, notes, transcripts, or attachments into a reference file.
- Read `references/source-of-truth-md.md` before generating, sending, parsing, or approving the structured Markdown source-of-truth document.
- Read `references/approval-loop.md` before presenting structured study data for review or deciding whether final generation may proceed.
- Read `references/study-type-branches.md` before setting `meta.study_type`, `meta.document_set`, or choosing templates.
- Read `references/starred-fillout-required-inputs.md` for prospective and ambispective starred-field extraction, candidate tracking, and stop behavior.
- Read `references/retrospective-required-inputs.md` for retrospective starred-field extraction, candidate tracking, and stop behavior.
- Read `references/n8n-prospective-protocol-icf-xml.md` for prospective studies before generating protocol, ICF, XML, visit-table, and template fields.
- Read `references/n8n-ambispective-protocol-icf-xml.md` for ambispective studies before generating protocol, ICF, XML, visit-table, and template fields.
- Read `references/n8n-retrospective-protocol.md` for retrospective protocol studies, including MB-25-01-style video/chart review protocols.
- Read `references/prs-xml.md` for prospective or ambispective ClinicalTrials.gov PRS XML generation.
- Read `references/reference-schema.md` before creating or modifying `study.reference.json`.
- Read `references/template-contract.md` before scanning, editing, or rendering templates.
- Read `references/local-handoff.md` when handing the workflow to the study team or explaining how to run, review, regenerate, and update outputs locally.
