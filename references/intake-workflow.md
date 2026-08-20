# Intake and Extraction Workflow

Use this guide when the source material is unstructured: Telegram or Slack messages, email text, meeting notes, audio transcripts, pasted synopsis text, PDFs, DOCX files, images with extracted text, spreadsheets, or mixed attachments.

## The Source Intake Packet

A client submission is one **Source Intake Packet**, whether it is a single Markdown file or nine mixed attachments. The packet holds one or more **Evidence Files** and is represented by `input/source-intake-manifest.json`, which records each file's identity, submission order, provenance, media type, processing status, and any extraction error.

Build the packet with every file the client sent:

```bash
python3 scripts/create_run.py \
  --root <runs-root> --slug <slug> --study-type <branch> \
  --evidence <file-1> --evidence <file-2> --evidence <file-3>
```

`--raw-context <file>` remains supported and simply creates a one-file packet.

Supported Evidence File types are Markdown, plain text, JSON, CSV, PDF, and DOCX. A file of any other type is still copied into the run and listed in the manifest with status `unsupported`; a file that cannot be read is listed as `unreadable` with the error naming the file. Never treat either as if it had not arrived — report it to the reviewer.

## Intake Rules

1. Preserve the original material before extracting anything. Every Evidence File belongs in the packet.
2. Read the whole packet, not only the first file. Template selection and every other source inspection use the combined evidence text, because a study can name its IRB only in the third attachment.
3. Save audio transcripts as Evidence Files. If an audio file is provided but no transcription tool is available, ask for a transcript.
4. Record the intake channel in `source.channel`, for example `telegram`, `slack`, `email`, `audio_transcript`, `uploaded_file`, or `manual_context`.
5. If new material arrives during review, add it to the packet before applying corrections to the reference file.
6. Tell the reviewer about any Evidence File the workflow could not read, and which one it was.

## Source-Of-Truth Stop Rule

For newly supplied source material, the first deliverable is always the named source-of-truth Markdown file generated under `reference/`. A request to create or generate clinical documents means create the run, extract the draft reference, pass the missing-input gate, and return the generated source-of-truth Markdown for review. It does not authorize final protocol, ICF, XML, or short-document generation. Stop after presenting the source-of-truth Markdown until the reviewer explicitly approves it or uploads an edited approved version.

Only the generated source Markdown recorded in `approval.review_file` should be shown as the review-stage output. Raw source copies, draft JSON, manifests, templates, logs, run inventories, and successful preflight reports are internal run state unless the reviewer explicitly asks for them.

## Extraction Pass

Create or update `reference/study.reference.json` in this order:

1. Fill factual fields copied from source material: title, study type, sponsor, investigator, sites, sample size, endpoints, criteria, procedures, timelines, and regulatory facts.
2. Normalize the study type branch using `references/study-type-branches.md`.
3. Set `meta.document_set` from the branch before selecting templates.
4. For prospective or ambispective studies, resolve `meta.icf_template` before the source-of-truth step. Auto-select when exactly one of Advarra or Sterling is stated in the input. Otherwise ask the reviewer to choose. If another IRB is named, explain that only Advarra and Sterling are available and ask which to use. Apply a later answer with `scripts/select_icf_template.py`. Retrospective studies skip this selection.
5. Add `null` for expected fields that are not present.
6. Add every missing, ambiguous, or conflicting item to `needs_review`. Record all starred-field candidates under `source.field_candidates`. Follow `references/starred-fillout-required-inputs.md` for prospective/ambispective and `references/retrospective-required-inputs.md` for retrospective.
7. Draft generated narrative fields only after the factual fields are filled.
8. Keep generated narrative under `generated`, not mixed into factual fields.
9. Run `scripts/check_required_inputs.py` before creating the reviewer-facing source Markdown. Clinical inputs stop only for a missing starred field or conflicting distinct candidates for a starred field. Prospective and ambispective runs also stop when the operational Advarra/Sterling ICF template choice has not been resolved. If blocking inputs remain, ask for them together and do not create the source Markdown yet.
10. Set `approval.status` to `pending_review` after creating or parsing a review-ready source Markdown. If corrections arrive, use `changes_requested` until the revised source Markdown is ready.

## Generated Text Rules

- Use formal clinical protocol style.
- Do not invent inclusion criteria, endpoints, sample sizes, dates, study arms, or regulatory values.
- If the source is unclear, write a review item instead of filling a confident-looking value.
- For ICF content, use participant-facing plain language and keep risks, benefits, compensation, reimbursement, privacy, contact, and withdrawal wording under `risks_benefits` or `generated.icf`.
- Generate the ICF and short document fields from the same reference file as the protocol document.
- Generate XML fields from `regulatory` and factual fields, not from copied defaults.
- Never reuse stale defaults from another study. In particular, verify investigator affiliation, organization name, site name, endpoint/outcome text, and XML organization fields against the current source material.

## Minimum Reference Before Rendering

Before running templates, the reference should usually include:

- `meta.protocol_number`, if known
- `meta.version`, if known
- `meta.date`
- `meta.study_type`
- `study.title`
- `study.short_title`
- `parties.sponsor`
- `parties.principal_investigator`
- `sites`
- `population.sample_size`
- `population.inclusion_criteria`
- `population.exclusion_criteria`
- `design.study_design`
- `objectives`
- `endpoints`
- `generated.protocol`
- `generated.icf`, when an ICF template is present
- `generated.short`
- `regulatory.xml_profile`, or a `needs_review` item stating that the XML profile is pending

The exact required fields are ultimately determined by template placeholders. Run `scripts/validate_reference.py` to enforce that contract.

## Source Markdown Before Generation

After the extraction pass, run:

```bash
python3 scripts/check_required_inputs.py --run-dir <run-dir>
```

If the preflight passes, create and present the named source Markdown:

```bash
python3 scripts/create_source_truth_md.py --run-dir <run-dir> --require-complete
```

After presenting the generated source Markdown, stop and wait for reviewer approval. If the reviewer uploads an edited source Markdown, parse it with `scripts/parse_source_truth_md.py`. Continue to final generation only after the source Markdown is approved and approval is recorded.
