# Local Handoff

Use this guide when handing the workflow to the study team or when running it without changing the skill code.

## Setup

Install DOCX rendering dependencies once from the skill folder:

```bash
cd clinical-document-generation/scripts
npm install
```

## Run a Generation

1. Create a run directory:

```bash
python scripts/create_run.py \
  --root runs \
  --slug <study-slug> \
  --study-type <prospective|ambispective|retrospective> \
  --raw-context <source-notes.md>
```

The command copies the bundled client templates for the selected study type. Retrospective copies only the protocol template. Prospective and ambispective copy protocol, ICF, and PRS XML templates. Pass explicit `--protocol-template`, `--icf-template`, or `--xml-template` only when replacing a bundled template.

2. Draft the internal reference from the source material, then run the missing-input preflight:

```bash
python scripts/check_required_inputs.py --run-dir runs/<study-slug>
```

If `reference/missing-inputs.md` lists missing inputs, ask the reviewer for those inputs before creating the structured source Markdown.

3. Create the reviewer-facing Markdown source document:

```bash
python scripts/create_source_truth_md.py --run-dir runs/<study-slug> --require-complete
```

Send or attach the generated file shown by the command output, normally `reference/source-of-truth--<protocol>--<study-slug>.md`. The reviewer edits values between field marker comments or approves it as-is. If an edited Markdown file is uploaded, save it under `input/attachments/` and parse it:

```bash
python scripts/parse_source_truth_md.py \
  --run-dir runs/<study-slug> \
  --source-md runs/<study-slug>/input/attachments/<edited-source-md> \
  --approval-status pending_review
```

If the upload message clearly says it is approved for generation, use `--approval-status approved --approved-by "<reviewer>"`.

Confirm `meta.study_type` and `meta.document_set` before rendering:

- Prospective: `["protocol_docx", "icf_docx", "xml"]`
- Ambispective: `["protocol_docx", "icf_docx", "xml"]`
- Retrospective: `["protocol_docx"]`

4. For templates copied from the existing workflow, populate the legacy n8n placeholders after the source Markdown has been approved or parsed:

```bash
# Prospective protocol + ICF + XML branch
python scripts/build_n8n_prospective_fields.py --run-dir runs/<study-slug>

# Ambispective protocol + ICF + XML branch
python scripts/build_n8n_ambispective_fields.py --run-dir runs/<study-slug>

# Retrospective protocol branch
python scripts/build_n8n_retrospective_protocol_fields.py --run-dir runs/<study-slug>
```

For prospective and ambispective XML runs, then populate PRS XML placeholders:

```bash
python scripts/build_prs_xml_fields.py --run-dir runs/<study-slug>
```

If this reports missing PRS inputs, resolve them with the reviewer before final generation.

5. Record approval when the reviewer approves the source Markdown, unless approval was already recorded by the parser:

```bash
python scripts/set_approval.py --run-dir runs/<study-slug> --status approved --approved-by "<reviewer>"
```

6. Validate fields:

```bash
python scripts/validate_reference.py --run-dir runs/<study-slug>
python scripts/validate_reference.py --run-dir runs/<study-slug> --require-approval
```

7. Generate outputs:

```bash
node scripts/render_templates.mjs --run-dir runs/<study-slug> --require-approval
```

8. Validate PRS XML for prospective and ambispective XML runs:

```bash
python scripts/validate_prs_xml.py --run-dir runs/<study-slug>
```

9. For any DOCX output with a static index or table of contents, render the DOCX to PDF, refresh the static TOC/index page values and alignment, then audit both page values and right-aligned dot-leader formatting:

```bash
python scripts/refresh_static_toc.py --docx runs/<study-slug>/output/<document>.docx --pdf runs/<study-slug>/logs/pages-render/<document>.pdf --report runs/<study-slug>/logs/toc-refresh.json
python scripts/audit_static_toc.py --docx runs/<study-slug>/output/<document>.docx --pdf runs/<study-slug>/logs/pages-render/<document>.pdf --output runs/<study-slug>/logs/toc-audit.json
```

Use the same PDF renderer the reviewer will inspect. For Apple Pages review, export the final DOCX from Pages, refresh the TOC/index from that Pages-generated PDF, export from Pages again, and audit the final Pages-generated PDF. If the refresh report updates page values or alignment, re-render/re-export before the final audit. Do not ship while `toc-audit.json` has page mismatches, missing headings, or alignment mismatches.

When auditing a static TOC/index, do not accept matches found on the TOC/index pages for entries that come after the TOC/index entry. The audit must verify the real heading location after the rendered TOC/index ends, otherwise the index can accidentally validate itself.

10. Review outputs:

```text
runs/<study-slug>/output/protocol.docx
runs/<study-slug>/output/icf.docx
runs/<study-slug>/output/study.xml
runs/<study-slug>/logs/generation-report.json
runs/<study-slug>/logs/toc-refresh.json
runs/<study-slug>/logs/toc-audit.json
```

## Regenerate

After the source Markdown exists, make durable study-content changes in the generated source Markdown recorded in `approval.review_file` or in an uploaded edited copy, then parse it again. Do not edit generated protocol/ICF/XML outputs if the change should persist across regenerations.

If the change comes from the reviewer by text/audio instead of an edited Markdown file, set approval to `changes_requested`, update the internal reference, regenerate the named source Markdown, then wait for approval again.

## Template Updates

Bundled templates live under `assets/client-templates/`. Use Docxtemplater-style placeholders that map to `reference/study.reference.json`, such as `{study.title}` or `{parties.principal_investigator.name}`. Run `scripts/scan_placeholders.py` and `scripts/validate_reference.py` after changing templates.

## QA Gate

Do not mark a run complete when:

- `missing_count` is greater than `0`.
- `unresolved_output_placeholders` contains any values.
- `approval_status` is not `approved`.
- Critical study-specific values remain in `needs_review`.
- Required inputs still appear in `reference/missing-inputs.md`.
- The approved source Markdown was not parsed or confirmed.
- PRS XML validation has not passed for a prospective or ambispective XML run.
