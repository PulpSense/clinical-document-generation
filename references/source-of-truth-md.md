# Source Of Truth Markdown

Use this reference for the reviewer-facing structured source workflow.

## Contract

The reviewer-facing source document is one named Markdown intake map under `reference/`, using the default pattern `source-of-truth--<protocol>--<study-slug>.md`. It mirrors the old n8n form role and is designed for a non-technical reviewer to edit normal text while preserving hidden machine mapping markers.

The document must make the editing boundary obvious for non-technical reviewers. The top study title line is only a preview and must be labeled as not editable. Before the first mapped field, include a visible heading such as:

```md
## Editable Study Inputs Start Here
```

Tell reviewers that edits start at that heading and that they should edit only the text inside field blocks.

Each editable field uses this shape:

```md
### Human Field Label
<!-- field: study.title -->
Reviewer edits this value.
<!-- /field -->
```

The reviewer should edit only the value between `<!-- field: ... -->` and `<!-- /field -->`. The parser uses the field marker to rebuild `reference/study.reference.json`. Do not rely on reviewers editing a preview/header line correctly.

Keep this Markdown file input-only. Include client-provided study facts, form-equivalent values, regulatory/PRS values, contacts, sites, criteria, objectives, endpoints, dates, interventions, and reviewer-provided references. Do not include `generated.*`, `template_fields`, `source`, `approval`, `needs_review`, or AI-written protocol/ICF/XML/summary prose.

Mapped field values in the source-of-truth Markdown are reviewer-controlled string content. After this Markdown is generated, uploaded, edited, or approved, do not manually correct, normalize, reconcile, or "fix" those values for spelling, branding, style, grammar, consistency with raw source material, consistency with the preview line, or consistency with other fields. Raw source material is evidence only. Reviewer-edited mapped values override raw source material unless the reviewer gives another correction.

Only intervene when a mapped value technically breaks the workflow, such as parser failure, malformed markers, missing required source fields, schema/type errors, unresolved template output, required controlled-vocabulary rejection, XML validation failure, or another hard validation issue that prevents final generation. In that case, make the smallest technical fix required to continue, prefer fixing the machine reference or template adapter over editing the approved Markdown, document the correction, and ask the reviewer if the needed change affects string content or semantics.

The source-of-truth Markdown is always the first reviewer-facing deliverable for newly supplied study input. A user request to create, generate, prepare, make, or build clinical documents from new source material does not approve the source data. Present the generated source Markdown path from the command output and stop; final outputs may be generated only after the reviewer explicitly approves that Markdown file or an edited uploaded version of it.

At this stage, the generated source Markdown recorded in `approval.review_file` is the only user-facing output. Keep `input/raw_context.md`, `reference/study.reference.json`, `input/source_manifest.json`, templates, logs, preflight reports, and other run artifacts internal unless the reviewer explicitly asks to inspect them.

## Required Input Gate

Read `references/starred-fillout-required-inputs.md` for prospective/ambispective or `references/retrospective-required-inputs.md` for retrospective. Only missing or conflicting starred Fillout fields block the clinical-input gate; optional and generic review notes do not. Prospective and ambispective runs must also resolve the operational ICF template choice (`Advarra` or `Sterling`). Retrospective runs do not require an ICF choice.

The ICF template choice must remain internal in `meta.icf_template` and must not appear as an editable source-of-truth field. If the input names exactly one supported template, select it automatically. If it names neither, both, or an unsupported IRB, ask the reviewer which supported template to use before running this command.

Before creating the named source-of-truth Markdown, run:

```bash
python3 scripts/clinical_document_workflow.py --run-dir <run-dir> --stage prepare
```

If the command reports missing inputs, do not create the structured Markdown. Send `reference/missing-inputs.md` or summarize the missing source fields to the reviewer, then update the draft reference after the reviewer provides the missing information. Do not ask the reviewer to provide AI-generated introductions, methods, ICF language, summary prose, or XML narrative fields.

Only create the structured Markdown when the preflight passes:

```bash
python3 scripts/clinical_document_workflow.py --run-dir <run-dir> --stage prepare
```

This writes `reference/source-of-truth--<protocol>--<study-slug>.md` by default and records the exact path in `source.source_of_truth_file`, `source.source_of_truth_md`, and `approval.review_file` in `reference/study.reference.json`.

After this command succeeds, return the Markdown file to the reviewer and wait. Do not set `approval.status` to `approved`, run final rendering, or create final protocol/ICF/XML outputs in the same turn unless the current user message is explicitly approving a previously generated or uploaded source-of-truth Markdown file.

Do not list preserved raw inputs, source manifests, draft JSON, copied templates, logs, run inventories, or successful preflight reports as outputs when returning the source Markdown. A concise note that the source Markdown is ready is acceptable, but the only artifact to expose is the generated source Markdown.

## Reviewer Upload Behavior

When the reviewer uploads an edited source Markdown:

1. Preserve the uploaded file under `input/attachments/`.
2. Parse the uploaded Markdown:

```bash
python3 scripts/parse_source_truth_md.py \
  --run-dir <run-dir> \
  --source-md input/attachments/<uploaded-source-md> \
  --approval-status pending_review
```

3. Treat the parsed Markdown as authoritative over prior raw inputs and prior JSON. Do not repair apparent typos or string inconsistencies in mapped values unless they technically block the workflow.
4. Review `reference/review-parse-report.md`.
5. The public workflow reruns required-input validation during approval.
6. If the upload message clearly approved final generation, the public workflow's `approve` stage records approval after parsing the current Markdown.
7. Generate branch-specific n8n/OpenAI narrative, run the mapper, then run final validation/rendering.

If the reviewer says the generated source Markdown is good without uploading edits, do not assume the current JSON still matches the Markdown. Parse the saved run file anyway, because the reviewer may have edited the generated file in place. Do not edit the Markdown before parsing:

```bash
python3 scripts/parse_source_truth_md.py \
  --run-dir <run-dir> \
  --source-md <run-dir>/<approval.review_file> \
  --approval-status approved \
  --approved-by "<reviewer>"
python3 scripts/check_required_inputs.py --run-dir <run-dir>
```

Review `reference/review-parse-report.md` and stop if parser warnings or missing inputs remain.

Do not treat the original source-material submission as "the reviewer says the generated source Markdown is good." Approval must refer to the generated source-of-truth Markdown or an uploaded edited source-of-truth Markdown.

## Parsing Rules

- The parser reads every `<!-- field: path -->...<!-- /field -->` block.
- Mapped field blocks are the authoritative source for document content. Do not manually reconcile mapped fields against raw source material, filenames, preview/header text, or other fields.
- The parser rebuilds the study sections in `study.reference.json` from those field IDs.
- Scalar lists are shown as normal Markdown bullet lists and parse back to arrays.
- `generated` and `template_fields` are cleared during parsing. After approval, regenerate generated narrative from the approved source inputs, then run the branch-specific n8n mapper.
- Empty values parse as `null`; do not use blanks for intentionally unknown required values.
- Reviewer notes should be added outside field blocks or in the active conversation; notes are not mapped into final documents.

## Final Generation Order

After approval:

```bash
python3 scripts/parse_source_truth_md.py --run-dir <run-dir> --source-md <run-dir>/<approval.review_file> --approval-status approved --approved-by "<reviewer>"
python3 scripts/check_required_inputs.py --run-dir <run-dir>
python3 scripts/build_n8n_<branch>_fields.py --run-dir <run-dir> --check  # after generated narrative has been saved
python3 scripts/build_n8n_<branch>_fields.py --run-dir <run-dir>
python3 scripts/build_prs_xml_fields.py --run-dir <run-dir>  # prospective/ambispective XML only
python3 scripts/validate_reference.py --run-dir <run-dir> --require-approval
python3 scripts/render_templates.py --run-dir <run-dir> --require-approval
python3 scripts/validate_prs_xml.py --run-dir <run-dir>  # prospective/ambispective XML only
```

Use the branch-specific mapper names:

- `build_n8n_prospective_fields.py`
- the internal ambispective branch adapter
- `build_n8n_retrospective_protocol_fields.py`
