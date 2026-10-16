# Generation-only experiment

Use this checkout as a complete skill folder on the Hermes host, with its
existing compatible Python 3.10+ runtime and requirements. Keep the installed
reviewed skill separate. This path uses native DOCX/XML builders and the existing
host LibreOffice for one Protocol TOC pagination pass. It requires no page-image
runtime provisioning, independent review workers, parent visual callback or
promoted release. Set `CLINICAL_SOFFICE` to the existing executable's absolute
path if `libreoffice` or `soffice` is not on PATH; preserve Linux dependencies.

## Generate with Hermes

Preserve the ordinary run-directory policy, intake, editable Source-of-Truth,
and explicit user approval. Use a new run folder; earlier runs remain intact.
From this skill's folder, after approval:

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage generate --generation-only
```

When the result is `awaiting_hermes`, `workspace` is the absolute base directory
for every returned `requests` and `handoffs` path. For each request:

1. Read the complete JSON. In `generation_only_prompts`, follow
   `adapter_instructions`, ICF `consent_template_comments`, and target-specific `editorial_corrections`, then the
   `messages` for each mapped target. These
   preserve the original n8n system prompts, task instructions and examples,
   substituting approved values for n8n expressions. `original_messages`
   retains the unmodified source for comparison.
2. Draft only the assigned sections. Approved study facts and Brad's later
   corrections in `section_contracts` take precedence over legacy defaults or
   demonstration facts. For `current_instruction_targets`, use the current
   section instructions and applicable fixed language. Additional study-specific
   sections need real source-grounded content, not generic template filler.
3. Save a JSON response at the handoff's `response_path`, relative to
   `workspace`. Use `hermes-response/v2` and copy `request_id`,
   `request_sha256`, `revision_id`, `task`, and `batch_id` exactly. Record the
   actual model as `producer.model_id`.
4. For DOCX requests return `section_results`, each with `section_id`,
   `outcome: drafted` (or `fixed_boilerplate`), `paragraphs: [{"text": "..."}]`,
   and `lists: [{"items": ["..."]}]`. Use empty arrays where appropriate, with
   at least one paragraph or list per section. Retain evidence/boilerplate refs
   when useful for manual inspection. Interpretation bookkeeping is optional.
   A list group may include `label`, rendered as an unbulleted paragraph before
   its items. Use separate labeled groups for secondary and exploratory endpoints.
   In `evaluation-procedures`, compare each supplied assessment note with the
   structured table. Move non-activity qualifications into nonempty adjacent
   notes using `assessment_presentation.qualifiers` (exact `source_text`,
   participant-readable `display_text`, and factual `rationale`). Retain the
   assessment name, conditions and timing. Keep actual assessments and staff
   tasks in their assigned columns. Use `assessment_presentation.notes` edits to omit a wholly
   redundant note (`display_text: ""`) or shorten it to its unique instructions.
   Each edit cites exact `source_text` and explains its `rationale`. Preserve
   every additional condition, measurement, timing rule and safety fact.
   Compare safety notes with the supplied `related_source` context too: general
   risks belong in the safety/risks sections; retain unique assessment instructions.
   For `icf.withdrawal`, draft additional study-specific policies; assembly owns
   the fixed voluntary-participation paragraph and retains it once.
   For PRS return `narrative.brief_summary` and `narrative.detailed_description`,
   each as an object with `text`. Return only the requested targets.
5. Run the same command again. It schedules remaining drafting prerequisites,
   then builds the complete native files and refreshes Protocol TOC fields once
   all drafts exist. A malformed
   response returns `drafting_response` with specific format feedback; correct
   the same response file and rerun. There is no automatic repair loop.

`drafting.response_template(request, model_id=...)` can scaffold the response
envelope. Fill it with actual model-written content; recorded acceptance helpers
are test fixtures and must never supply real study prose.

## Inspect the result

The terminal result is `status: unreviewed`, with exact paths in
`experimental_outputs`. Files are named `protocol.docx`,
`icf.docx`, and `study.xml` as applicable. They live in
`<run-dir>/output/`. Completed native files are moved out of the assembly
workspace, leaving one document set. The experiment notice stays in the internal
workspace with the drafting and assembly records.
`client_outputs` stays empty. Local host paths establish saved files only;
use the channel's actual transfer mechanism when available.

Deliver with “Here are the documents:”, a clickable link for each generated
file, and the recorded generation time in minutes and seconds. Use `delivery_message` when its links are accessible to the user; otherwise
upload/attach the files through the channel's supported transfer mechanism and use
the resulting links in that same short message. Keep filenames free of the
`UNREVIEWED-` prefix. Keep run paths, revision IDs, hashes, drafting records,
assessment status and experiment notices in the run records rather than the delivery
message. Internal `status: unreviewed` records the workflow's actual assessment state.

Source approval, request/response identity, section presence and basic native
readability are checked. Content judgments, XML contract validation, DOCX audits,
visual QA, publication gates and repair loops are skipped. The approved office
field-refresh step runs once after Protocol assembly, reads exact heading page
positions from an internal PDF outline, and inserts their caches into native
Word fields. It discards the PDF and does not round-trip the clinical DOCX body
through LibreOffice. A reserved page-number column keeps TOC labels from
reflowing when numbers are inserted. No content or visual judgment runs.
An office failure returns `stage: office_field_refresh` with construction feedback,
without starting a retry loop or publishing files with invented page numbers.
The recorded renderer, before/after hashes and pagination-PDF hash stay internal
in `office-field-refresh.json`. Completed results reuse their saved files.
The current source-driven table and XML builders still preserve their structure;
legacy workflow constants and external Google Docs/Gmail actions are excluded.
Prompts, responses, merged drafts and assembly records remain in `workspace`.
Changing the generation authority starts a separate attempt; use a new run folder
for its document set. A nonempty output folder is preserved and returns
`stage: output_conflict`. Repeating a completed
command returns the saved result and verifies its file hashes.

The owner generates the study files with Hermes, then the owner and Codex
inspect them against the approved source and
[Brad's comment register](brad-review-coverage.md). Check short running titles,
supported clinical claims, section purpose, endpoint ownership, concise methods,
useful measurements, nonrepetitive schedules, supplied privacy details, distinct
completion/withdrawal wording, and the selected ICF's fixed language. Inspect
DOCX appearance in Word during that manual review. Record concrete defects before
tuning prompts. Completion of generation alone establishes no review result.
