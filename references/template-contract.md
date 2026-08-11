# Template Contract

Templates are allowed to change. The scripts stay generic by requiring every placeholder to resolve from `reference/study.reference.json`.

## Placeholder Syntax

Use the skill's brace placeholder syntax:

```text
{study.title}
{meta.protocol_number}
{parties.principal_investigator.name}
{generated.protocol.introduction}
```

Use array loops for repeatable content:

```text
{#sites}
{facility.name}
{facility.address.city}
{/sites}
```

Use the same syntax in XML templates:

```xml
<official_title>{study.title}</official_title>
<brief_title>{study.short_title}</brief_title>
{#endpoints.primary}
<primary_outcome>
  <measure>{measure}</measure>
  <time_frame>{time_frame}</time_frame>
  <description>{description}</description>
</primary_outcome>
{/endpoints.primary}
```

## Required Conventions

- Keep placeholders ASCII and path-like: letters, digits, `_`, `-`, and dots.
- Prefer fully qualified placeholders outside loops.
- Inside loops, use fields relative to the loop item.
- Do not use placeholders with spaces or prose labels.
- Do not rely on implicit defaults. Put defaults in `study.reference.json` or in `regulatory`.
- Keep generated narrative fields under `generated` so scripts do not call an LLM.

## Legacy n8n Placeholders

Client templates copied from the existing workflow may contain flat placeholders such as:

```text
{AI_shortTitle}
{protocolNumber}
{AI_introduction}
{AI_populationLong}
{AI_studyProcedureBullets}
{testArticle(s)}
```

These are supported through top-level `template_fields`. For retrospective protocol runs, generate them with:

```bash
python3 scripts/build_n8n_retrospective_protocol_fields.py --run-dir <run-dir>
```

For prospective protocol, ICF, and XML runs, generate them with:

```bash
python3 scripts/build_n8n_prospective_fields.py --run-dir <run-dir>
```

For ambispective protocol, ICF, and XML runs, generate them with:

```bash
python3 scripts/build_n8n_ambispective_fields.py --run-dir <run-dir>
```

Do not manually duplicate clinical facts into `template_fields`; derive them from the reviewed reference and generated module outputs.

## DOCX Templates

`scripts/create_run.py` copies the bundled client DOCX templates from `assets/client-templates/docx/` into the run `templates/` directory. Replace them only when the client supplies newer templates. Standard run template names are:

```text
templates/protocol.template.docx
templates/icf.template.docx
templates/short.template.docx
```

For prospective and ambispective ICF output, the run must record `meta.icf_template` before source-of-truth generation. `Advarra` selects the branch-specific Advarra asset; `Sterling` selects the shared `sterling-icf.template.docx` asset. Apply a reviewer choice with:

```bash
python3 scripts/select_icf_template.py --run-dir <run-dir> --choice <advarra|sterling>
```

The command always writes the selected template to the standard run path `templates/icf.template.docx`, so downstream validation and rendering remain branch-independent.

Recommended examples:

```text
{study.title}
Protocol Number: {meta.protocol_number}
Investigator: {parties.principal_investigator.name}

{generated.protocol.introduction}

{#population.inclusion_criteria}
• {text}
{/population.inclusion_criteria}
```

For tables, put the loop around the row that must repeat.

`templates/main.template.docx` is supported as a legacy alias for older runs, but new client templates should use `protocol.template.docx`.

## Static Index And TOC Alignment

Any generated DOCX that contains a static index or table of contents must use real right-aligned dot-leader tab stops for page numbers. Manual dot strings are not acceptable, even when the page numbers are correct.

After generating the DOCX, run `scripts/export_docx_to_pdf.py` in automatic mode. If a renderer is available, run `scripts/refresh_static_toc.py`, re-export, and run `scripts/audit_static_toc.py`. The final audit must report zero page mismatches, zero missing headings, and zero alignment mismatches before the DOCX is considered visually verified. If no renderer is available, the DOCX remains a valid deliverable, but record and disclose that PDF-based visual/TOC QA was skipped.

The audit must treat TOC/index pages as front matter, not as the real location of later content. For any entry after the `TABLE OF CONTENTS` or `INDEX` entry, the heading search must start on the first page after the rendered TOC/index. This is required for all document sets and study branches so an index row cannot satisfy its own page lookup.

## XML Templates

`scripts/create_run.py` copies the bundled PRS XML template into:

```text
templates/study.template.xml
```

The XML renderer supports scalar placeholders and simple array/object blocks using the same `{#path}...{/path}` syntax. Keep XML escaping in mind: values are XML-escaped by default.

For ClinicalTrials.gov PRS XML, copy the canonical template from:

```text
assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml
```

Then run:

```bash
python3 scripts/build_prs_xml_fields.py --run-dir <run-dir>
```

The PRS mapper writes flat PRS placeholders into `template_fields` and sets `template_fields.__prs_counts`. The renderer uses those counts to keep exactly one repeated XML block per real intervention, arm, primary outcome, secondary outcome, and other outcome.

Only templates listed by `meta.document_set` are rendered. For example, retrospective runs normally include `protocol_docx` only, so ICF and XML templates are ignored unless the document set explicitly includes them.

## Validation Expectations

Run:

```bash
python3 scripts/scan_placeholders.py templates/protocol.template.docx templates/icf.template.docx templates/short.template.docx templates/study.template.xml
python3 scripts/validate_reference.py --run-dir <run-dir>
```

Validation checks that:

- templates exist when expected
- placeholders can be mapped to `study.reference.json`
- unresolved paths are written to `reference/missing_fields.md`
- generation metadata is written to `logs/generation-report.json`

For PRS XML, also run:

```bash
python3 scripts/validate_prs_xml.py --run-dir <run-dir>
```

Validation does not prove the clinical correctness of generated language. Review the reference file before final output.
