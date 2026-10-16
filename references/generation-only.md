# Generation-only experiment

Use this checkout as a complete skill folder on the Hermes host, with its
existing compatible Python 3.10+ runtime and requirements. Keep the installed
reviewed skill separate. This path uses native DOCX/XML builders and requires no
office renderer, PDF conversion, page-image runtime provisioning, independent
review workers, parent visual callback or promoted release.

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
   `adapter_instructions`, then the `messages` for each mapped target. These
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
   For PRS return `narrative.brief_summary` and `narrative.detailed_description`,
   each as an object with `text`. Return only the requested targets.
5. Run the same command again. It schedules remaining drafting prerequisites,
   then builds the complete native files once all drafts exist. A malformed
   response returns `drafting_response` with specific format feedback; correct
   the same response file and rerun. There is no automatic repair loop.

`drafting.response_template(request, model_id=...)` can scaffold the response
envelope. Fill it with actual model-written content; recorded acceptance helpers
are test fixtures and must never supply real study prose.

## Inspect the result

The terminal result is `status: unreviewed`, with exact paths in
`experimental_outputs`. Files are named `UNREVIEWED-protocol.docx`,
`UNREVIEWED-icf.docx`, and `UNREVIEWED-study.xml` as applicable. They live in
`<run-dir>/generation-only-output/<revision>/<attempt>/`, with a separate notice.
`client_outputs` stays empty. Local host paths establish saved files only;
use the channel's actual transfer mechanism when available.

Source approval, request/response identity, section presence and basic native
readability are checked. Content judgments, XML contract validation, DOCX audits,
visual QA, PDF conversion, publication gates and repair loops are skipped.
The current source-driven table and XML builders still preserve their structure;
legacy workflow constants and external Google Docs/Gmail actions are excluded.
Prompts, responses, merged drafts and assembly records remain in `workspace`.
Changing the generation authority starts a separate attempt. Repeating a completed
command returns the saved result and verifies its file hashes.

The owner generates the study files with Hermes, then the owner and Codex
inspect them against the approved source and
[Brad's comment register](brad-review-coverage.md). Check short running titles,
supported clinical claims, section purpose, endpoint ownership, concise methods,
useful measurements, nonrepetitive schedules, supplied privacy details, distinct
completion/withdrawal wording, and the selected ICF's fixed language. Inspect
DOCX appearance in Word during that manual review. Record concrete defects before
tuning prompts. Completion of generation alone establishes no review result.
