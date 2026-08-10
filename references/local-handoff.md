# Local Handoff

Use this guide when handing the workflow to the study team or when running it without changing the skill code.

## Setup

Confirm Python 3.9 or newer is available:

```bash
python3 --version
```

All scripts use the Python standard library. Do not install Python or Node packages.

## Run a Generation

1. Create a run directory:

```bash
python3 scripts/create_run.py \
  --root runs \
  --slug <study-slug> \
  --study-type <prospective|ambispective|retrospective> \
  --raw-context <source-notes.md>
```

The command copies the bundled client templates for the selected study type. Retrospective copies only the protocol template. Prospective and ambispective copy protocol and PRS XML templates, then copy the ICF automatically when the raw input names exactly one supported choice: Advarra or Sterling.

Before the source-of-truth step, confirm `meta.icf_template` for every prospective or ambispective run. If the input names neither supported template, ask which to use. If it names another IRB, explain that only Advarra and Sterling are available and ask which one to use. Apply the answer with:

```bash
python3 scripts/select_icf_template.py --run-dir runs/<study-slug> --choice <advarra|sterling>
```

Retrospective runs skip this step. Pass explicit `--protocol-template`, `--icf-template`, or `--xml-template` only when replacing a bundled template.

2. Draft the internal reference from the source material, then run the missing-input preflight:

```bash
python3 scripts/check_required_inputs.py --run-dir runs/<study-slug>
```

If `reference/missing-inputs.md` lists blocking inputs, ask the reviewer for them before creating the structured source Markdown. Clinical input blockers are limited to missing or conflicting starred Fillout fields; a prospective or ambispective report can also contain the separate unresolved ICF template choice.

3. Create the reviewer-facing Markdown source document:

```bash
python3 scripts/create_source_truth_md.py --run-dir runs/<study-slug> --require-complete
```

Send or attach the generated file shown by the command output, normally `reference/source-of-truth--<protocol>--<study-slug>.md`. The reviewer edits values between field marker comments or approves it as-is. If an edited Markdown file is uploaded, save it under `input/attachments/` and parse it:

```bash
python3 scripts/parse_source_truth_md.py \
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
python3 scripts/build_n8n_prospective_fields.py --run-dir runs/<study-slug>

# Ambispective protocol + ICF + XML branch
python3 scripts/build_n8n_ambispective_fields.py --run-dir runs/<study-slug>

# Retrospective protocol branch
python3 scripts/build_n8n_retrospective_protocol_fields.py --run-dir runs/<study-slug>
```

For prospective and ambispective XML runs, then populate PRS XML placeholders:

```bash
python3 scripts/build_prs_xml_fields.py --run-dir runs/<study-slug>
```

For prospective and ambispective studies, stop only when this reports `blocking_missing_count` greater than zero. Other PRS gaps remain visible as nonblocking review notes.

5. Record approval when the reviewer approves the source Markdown, unless approval was already recorded by the parser:

```bash
python3 scripts/set_approval.py --run-dir runs/<study-slug> --status approved --approved-by "<reviewer>"
```

6. Validate fields:

```bash
python3 scripts/validate_reference.py --run-dir runs/<study-slug>
python3 scripts/validate_reference.py --run-dir runs/<study-slug> --require-approval
```

7. Generate outputs:

```bash
python3 scripts/render_templates.py --run-dir runs/<study-slug> --require-approval
```

8. Validate PRS XML for prospective and ambispective XML runs:

```bash
python3 scripts/validate_prs_xml.py --run-dir runs/<study-slug>
```

9. After DOCX generation, try the platform-aware PDF exporter:

```bash
python3 scripts/export_docx_to_pdf.py runs/<study-slug>/output/<document>.docx runs/<study-slug>/logs/docx-render/<document>.pdf --report runs/<study-slug>/logs/docx-render/<document>.json
```

Automatic mode tries Pages on macOS, Word on Windows, and LibreOffice on Linux. If the report status is `unavailable`, retain the generated DOCX, skip PDF/TOC commands, and disclose the QA limitation. If the report status is `exported` and the DOCX has a static index or table of contents, refresh and audit it:

```bash
python3 scripts/refresh_static_toc.py --docx runs/<study-slug>/output/<document>.docx --pdf runs/<study-slug>/logs/docx-render/<document>.pdf --report runs/<study-slug>/logs/toc-refresh.json
python3 scripts/export_docx_to_pdf.py runs/<study-slug>/output/<document>.docx runs/<study-slug>/logs/docx-render/<document>.pdf --report runs/<study-slug>/logs/docx-render/<document>.json
python3 scripts/audit_static_toc.py --docx runs/<study-slug>/output/<document>.docx --pdf runs/<study-slug>/logs/docx-render/<document>.pdf --output runs/<study-slug>/logs/toc-audit.json
```

If the refresh report updates page values or alignment, re-render before the final audit. When a renderer is available, do not ship while `toc-audit.json` has page mismatches, missing headings, or alignment mismatches.

When auditing a static TOC/index, do not accept matches found on the TOC/index pages for entries that come after the TOC/index entry. The audit must verify the real heading location after the rendered TOC/index ends, otherwise the index can accidentally validate itself.

10. Review outputs:

```text
runs/<study-slug>/output/protocol.docx
runs/<study-slug>/output/icf.docx
runs/<study-slug>/output/study.xml
runs/<study-slug>/logs/generation-report.json
runs/<study-slug>/logs/docx-render/<document>.json
runs/<study-slug>/logs/toc-refresh.json
runs/<study-slug>/logs/toc-audit.json
```

## Regenerate

After the source Markdown exists, make durable study-content changes in the generated source Markdown recorded in `approval.review_file` or in an uploaded edited copy, then parse it again. Do not edit generated protocol/ICF/XML outputs if the change should persist across regenerations.

If the change comes from the reviewer by text/audio instead of an edited Markdown file, set approval to `changes_requested`, update the internal reference, regenerate the named source Markdown, then wait for approval again.

## Template Updates

Bundled templates live under `assets/client-templates/`. Use brace placeholders that map to `reference/study.reference.json`, such as `{study.title}` or `{parties.principal_investigator.name}`. Run `scripts/scan_placeholders.py` and `scripts/validate_reference.py` after changing templates.

## QA Gate

Do not mark a run complete when:

- `missing_count` is greater than `0`.
- `unresolved_output_placeholders` contains any values.
- `approval_status` is not `approved`.
- Branch-blocking starred-field conflicts remain in `needs_review`; optional and generic notes do not block.
- Required inputs still appear in `reference/missing-inputs.md`.
- The approved source Markdown was not parsed or confirmed.
- PRS XML validation has not passed for a prospective or ambispective XML run.
