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

## Visit Schedule Tables

Prospective and ambispective protocol visit schedules must be **Data-Driven Tables**: one real Word row per visit. Put the loop around the row that repeats, opening the block in the first cell and closing it in the last:

```text
| {#visits}{visitNumber} | {visitName} | {visitWindow} | {CRFnumber}{/visits} |
```

The branch mapper publishes those rows as `template_fields.visits`. The `AI_visitNumber`, `AI_visitName`, `AI_visitWindow`, and `AI_CRFnumber` fields remain available as newline-joined compatibility values for older external templates, but they are a **Legacy String Fallback**: they pack every visit into a single table cell. They may never carry the schedule in a bundled protocol template.

Two checks enforce this:

```bash
python3 scripts/validate_template_contract.py
```

fails when a bundled prospective or ambispective protocol visit table uses the legacy scalar placeholders or has no repeated row block. The `visit_table` Delivery Gate then fails a run whose rendered protocol packs multiple visits into one row, renders the wrong number of rows, or drops a visit.

Keep the repeating header row marked with `<w:tblHeader/>` and leave that flag off the data row. A data row carrying `tblHeader` repeats on every page once it is duplicated per visit.

## Structural Tables

A **Structural Table** is a table whose shape is decided by the data rather than by the template, because its column count is not known when the template is written. It cannot be expressed as a repeated Word row, so it is not written as a `{#block}`. Instead the template carries a lone scalar placeholder on its own paragraph, and the renderer removes that paragraph and inserts a real Word table in its place:

```text
Table 15.1. Proposed Visits and Study Assessments
{visitsTable}
```

The branch mapper publishes the matrix as `template_fields.visitsTable`, in the shape the original workflow defined:

```json
{"cells": ["Visit Number", "Visit Name", "…"], "totalColumns": 4, "totalRows": 8}
```

`cells` is read row-major, the first row renders as a repeating shaded header, and a short final row is padded so the table stays rectangular. A declared `totalRows` is honoured, so cells beyond `totalRows` x `totalColumns` are ignored rather than growing the table; a missing `totalRows` is computed from the cell count. An empty matrix is not tolerated.

The inserted table is always followed by a paragraph, because a table may not be the last thing in a table cell and two adjacent tables merge into one.

The matrix is used with the shape it declares when `generated.protocol.visitsTable` supplies a non-empty one; a blank generated matrix degrades to the derived table rather than blanking the section.

### What the derived table is, and is not

The caption reads "Proposed Visits and Study Assessments", but the derived table is **not** a schedule-of-assessments matrix marking which assessment happens at which visit. No Required Source Input carries assessment-per-visit detail, and the branch scripts may not add one, so the derived table repeats the study-level assessments text against each visit and shares three of its four columns with Table 9.2-1.

This is a deliberate, accepted fallback, not an oversight. The original workflow called `visitsTable` the "Protocol visit table equivalent", which is what this reproduces. A true assessments matrix would need per-visit assessment data, and collecting it is a source-contract change to be decided with the client rather than inferred by a mapper.

A model that supplies `generated.protocol.visitsTable` can render a real matrix of any width today: the renderer builds whatever shape the matrix declares. The fallback only covers studies where no such matrix was generated. Otherwise it is derived from the visit schedule the branch already holds, with the assessments column falling back to `procedures.assessments` and then `generated.protocol.measurements`. No Required Source Input carries an assessment-per-visit matrix, so a study with no assessment detail still renders a complete table.

Two checks enforce this, mirroring the visit table:

```bash
python3 scripts/validate_template_contract.py
```

fails when a bundled prospective or ambispective protocol template no longer carries the `{visitsTable}` placeholder. The `structural_tables` Delivery Gate then fails a run whose matrix is empty or entirely blank, naming the affected section in the Repair Report.

That gate exists because a Structural Table fails silently. An empty matrix still *resolves* the placeholder, so placeholder validation passes and the document ships the caption with nothing beneath it.

Retrospective protocols declare no structural tables and carry neither the placeholder nor the caption.

## Static Index And TOC Alignment

Any generated DOCX that contains a static index or table of contents must use real right-aligned dot-leader tab stops for page numbers. Manual dot strings are not acceptable, even when the page numbers are correct.

After generating the DOCX, run `scripts/export_docx_to_pdf.py` in automatic mode. If a renderer is available, run `scripts/refresh_static_toc.py`, re-export, and run `scripts/audit_static_toc.py`. The final audit must report zero page mismatches, zero missing headings, and zero alignment mismatches before the DOCX is considered visually verified. If no renderer is available, the DOCX remains a valid deliverable, but record and disclose that PDF-based visual/TOC QA was skipped.

The audit must treat TOC/index pages as front matter, not as the real location of later content. For any entry after the `TABLE OF CONTENTS` or `INDEX` entry, the heading search must start on the first page after the rendered TOC/index. This is required for all document sets and study branches so an index row cannot satisfy its own page lookup.

A static TOC must also describe the document it sits in. A bundled template may not list a section its own body does not contain:

```bash
python3 scripts/validate_template_contract.py
```

fails when a bundled protocol template's TOC carries an entry that no heading in that template answers. A heading may share its paragraph with the content after it, as `9.1. Analysis Data Sets {AI_analysisDataSets}` does, so an entry is answered by a paragraph that is its title or its title followed by a placeholder; a merely longer heading does not answer it.

This check reads both the entries and the body with `audit_static_toc`'s own parser. A `<w:t>`-only regex drops the `<w:tab/>` that separates a compliant entry from its page number, which stops the row being recognised as a TOC row at all and makes every entry match itself. One known limitation: a heading whose number comes from Word list numbering rather than its text will not be matched, and would be reported as an orphan.

An orphan entry is invisible until a renderer audits the TOC against a rendered PDF, and it then blocks packaging outright, so it is worth catching deterministically first.

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
