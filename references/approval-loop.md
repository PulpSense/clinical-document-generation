# Reviewer Approval Loop

Use this guide after `reference/study.reference.json` has been drafted and before final document generation.

## Boundary

Hermes handles the channel layer: Slack, Telegram, email, pasted text, file uploads, and audio transcription when available. The skill handles the local workflow state:

- preserved input files under `input/`
- draft/cache data under `reference/study.reference.json`
- reviewer-facing source document under `reference/source-of-truth--<protocol>--<study-slug>.md`
- approval metadata under `approval`
- final outputs under `output/`

During the source-review stage, only the generated source Markdown recorded in `approval.review_file` is user-facing. The preserved inputs, draft/cache JSON, manifests, copied templates, logs, run inventories, and successful preflight reports stay internal unless the reviewer asks for them.

After a source Markdown file has been generated, uploaded, edited, or approved, mapped field values in that Markdown are reviewer-controlled source content. Do not manually correct, normalize, reconcile, or "fix" those values for spelling, branding, grammar, style, consistency with the raw inputs, consistency with preview text, or consistency with other fields. Raw source material is evidence only and must not silently override reviewer-edited mapped values.

Only intervene when a mapped source value technically breaks the workflow, such as parser failure, malformed field markers, missing required source fields, schema/type errors, unresolved template output, required controlled-vocabulary rejection, XML validation failure, or another hard validation issue that prevents final generation. In those cases, make the smallest technical correction required to continue, prefer fixing machine/generated/template-adapter values instead of editing approved Markdown, document the correction, and ask the reviewer if the correction would change string content or meaning.

## State Machine

Use these approval states:

- `pending_review`: the structured source Markdown is ready for reviewer review, or an uploaded edit has been parsed and needs confirmation.
- `changes_requested`: the reviewer asked for corrections and the reference is not approved.
- `approved`: the reviewer approved the structured source Markdown for final generation.

New runs start as `pending_review`. Use `approved` only after an explicit reviewer approval such as "approved", "looks good, generate", "go ahead", or equivalent context.

An initial request that provides study source material and asks to "create", "generate", "prepare", "make", or "build" clinical documents is not approval. It is an intake instruction. In that situation, generate and present the named source Markdown, then stop for reviewer approval. The reviewer may approve immediately in the next message, but the approval must be an explicit response to the generated or edited source Markdown.

## Source Markdown

Before generating the reviewer-facing source Markdown, run:

```bash
python3 scripts/workflow.py --run-dir <run-dir> --stage prepare
```

If blocking inputs are reported, ask for those inputs before creating the structured document. Ask for the missing or conflicting starred fields, using `references/starred-fillout-required-inputs.md` for prospective/ambispective or `references/retrospective-required-inputs.md` for retrospective. When the preflight passes, generate the source Markdown:

```bash
python3 scripts/workflow.py --run-dir <run-dir> --stage prepare
```

Present the generated source Markdown path recorded in `approval.review_file` in the active channel or attach it if the channel supports files. The Markdown includes stable hidden `field` markers so the parser can map reviewer edits back into JSON. It must contain source inputs only, equivalent to the old n8n form fields; generated protocol, ICF, short-document, and XML prose should not appear in it.

After presenting the source Markdown, stop. Do not list raw inputs, draft JSON, manifests, templates, logs, run inventories, or successful preflight reports as outputs. Do not run final validation, rendering, PRS XML generation, TOC refresh, or render QA until approval has been explicitly recorded for that source Markdown.

## Corrections

If the reviewer uploads an edited source Markdown:

1. Save the new material under `input/` or `input/attachments/`.
2. Let the public workflow parse it during its `approve` stage with
   `--source-md input/attachments/<uploaded-source-md>`.
3. Treat the parsed Markdown as authoritative over prior raw inputs and prior JSON. Do not repair apparent typos or content inconsistencies in mapped values unless they technically block parsing or final generation.
4. The public workflow reruns required-input validation during approval.
5. Present a short parse summary or ask for approval if the accompanying message is ambiguous.

If the reviewer sends corrections as text or audio instead of editing the Markdown, preserve the correction, update `study.reference.json`, rerun the missing-input preflight, and regenerate the named source Markdown.

## Approval

When the reviewer approves the source Markdown:

```bash
python3 scripts/workflow.py \
  --run-dir <run-dir> \
  --stage approve \
  --approved-by "<reviewer>"
python3 scripts/workflow.py --run-dir <run-dir> --stage validate
```

This parse step is mandatory even when the reviewer did not upload a separate edited file. The reviewer may have edited the saved source Markdown in place after it was presented, and `reference/study.reference.json` must be regenerated from the current Markdown before final narrative generation, mapper checks, validation, or rendering. Review `reference/review-parse-report.md`; if parser warnings or missing required inputs remain, stop and resolve them before continuing.

Do not edit the approved source Markdown before parsing it. If a mapped value looks suspicious but does not break parsing, required-input checks, template rendering, XML validation, or another hard workflow gate, preserve it exactly.

If approval must be recorded after a separate parsed correction pass, use:

```bash
python3 scripts/workflow.py --run-dir <run-dir> --stage approve --approved-by "<reviewer>"
```

Then final validation and rendering must use approval gating:

```bash
python3 scripts/build_n8n_<branch>_fields.py --run-dir <run-dir> --check
python3 scripts/workflow.py --run-dir <run-dir> --stage generate
```

Before running the mapper check, generate the branch-specific n8n/OpenAI narrative fields from the approved input reference and save them under `generated`. Do not mark final outputs complete if validation fails, unresolved placeholders remain, required generated fields remain blank, or branch-blocking review items remain. Optional and generic review notes do not block in any branch.
