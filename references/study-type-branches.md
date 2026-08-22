# Study Type Branches

Use this guide before structuring `reference/study.reference.json` and before choosing templates.

## Branch Selection

Normalize `meta.study_type` to one of:

- `Prospective`
- `Ambispective`
- `Retrospective`

Treat `ambipective` as a typo for `Ambispective`.

If the study type is missing or unclear, set `meta.study_type` to `null`, set `meta.document_set` to `[]`, and add a `needs_review` item.

## Document Sets

Use these defaults from the existing workflow:

```json
{
  "Prospective": ["protocol_docx", "icf_docx", "xml"],
  "Ambispective": ["protocol_docx", "icf_docx", "xml"],
  "Retrospective": ["protocol_docx"]
}
```

`short_docx` is optional for all branches when a shorter summary is requested or when a `short.template.docx` is intentionally provided.

## Template Expectations

- `protocol_docx` -> `templates/protocol.template.docx` -> `output/protocol.docx`
- `icf_docx` -> `templates/icf.template.docx` -> `output/icf.docx`
- `short_docx` -> `templates/short.template.docx` -> `output/short.docx`
- `xml` -> `templates/study.template.xml` -> `output/study.xml`

The renderer uses `meta.document_set`. Templates that are present but not listed in `meta.document_set` are not rendered.

### ICF Template Selection

Prospective and ambispective runs support two bundled ICF families:

- `Advarra`: branch-specific Advarra template.
- `Sterling`: one Sterling template shared by both branches.

Resolve the choice before the source-of-truth file is created. If exactly one supported name appears in the source, select it automatically. If no supported name appears, ask whether to use Advarra or Sterling. If an unsupported IRB appears, state that only those two templates are available and ask which to use. Record the result in `meta.icf_template`; the public workflow applies it internally. Retrospective runs do not require an ICF choice.

## Required Reference Focus

### Prospective

Read `references/starred-fillout-required-inputs.md`. The prospective source-input gate is defined only by the 35 fields/groups marked with `*` in Fillout. Stop when one is missing or has more than one distinct source candidate. Do not promote optional form fields, generated narrative, or PRS administration fields into prospective intake blockers.

### Ambispective

Read `references/starred-fillout-required-inputs.md`. The confirmed ambispective form has the same 35 starred fields and stop behavior as the prospective form. Protocol numbers, PI affiliation, PRS administration values, study UID, and overall contact are not intake blockers unless they are part of a conflict involving a starred field.

Ambispective studies follow the prospective document set, but generated content must separate retrospective and prospective data collection:

- Existing/historical data sources.
- Prospective visits, procedures, or follow-up.
- Which endpoints come from historical review versus prospective collection.
- ICF language appropriate to the prospective portion.
- PRS XML-specific regulatory values under `regulatory.prs` when supplied. Missing nonstar PRS administration values remain visible but do not trigger intake questions.

### Retrospective

Read `references/retrospective-required-inputs.md`. The retrospective source-input gate is defined only by its 21 confirmed starred fields. `meta.protocol_number`, funding-source details, facility city, sub-investigator, test articles, and references are not intake blockers.

Retrospective studies follow the protocol-only branch from the current workflow:

- Existing records/data/video sources.
- Privacy/de-identification protocol.
- Waiver or consent rationale if supplied by the source material.
- No ICF or XML unless the user/client explicitly requests them and provides templates. The inspected n8n workflow has no retrospective XML generation/upload path.

## Validation

Run:

```bash
python3 scripts/workflow.py --run-dir <run-dir> --stage validate
```

Validation checks `meta.study_type`, `meta.document_set`, required branch fields, required templates for that branch, and placeholders in active templates. Technical parser, approval, rendering, controlled-vocabulary, and XML failures may still stop a prospective or ambispective run after the source-input gate passes.
