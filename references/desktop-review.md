# Desktop workers, review and recovery

Read when assigned a drafting or verification request, or explicitly integrating or diagnosing Desktop handoffs. Ordinary generation uses the production adapter in [SKILL.md](../SKILL.md); it already owns scheduling and recovery. Workers read their exact request completely and follow its contract.

`generate` is the deterministic inner step used by that operation. Do not run
an independent open-ended `generate` loop as the normal delivery path. Only for explicitly requested adapter diagnosis, the inner CLI form is:

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage generate --manual-review
```

The workflow advances deterministically until it passes, blocks, or returns `status: awaiting_hermes` with one or more request paths.

For every `awaiting_hermes` response:

1. Use the returned `handoffs` as routing metadata. Resolve each `request_path` and `response_path` relative to `revisions/<revision_id>/`.
2. Keep request contents out of the parent orchestration context. The parent must route paths without reading request JSON; each assigned subagent reads its own request completely.
3. Send one request path to each subagent and dispatch all returned handoffs concurrently. Never combine multiple request files in one subagent. If the delegation limit is lower than the handoff count, start one isolated `hermes chat -q` background process per handoff in the same turn instead of shrinking the wave.
4. Give each subagent the absolute request path, revision directory, exact response path, and task. Require exact response JSON with no Markdown commentary and validation with the repository validator before completion. For `task: prs_narrative_drafting`, the response must use a `narrative` object containing exactly `brief_summary` and `detailed_description`; do not return `section_results` for PRS requests.
5. Keep the parent turn alive with one bounded wait for every exact `response_path`. A handoff is complete when its exact response file contains parseable JSON bound to the request ID, hash, task, and revision. At that point, terminate and reap only that owned worker within the cleanup reserve, then advance without waiting for its final chat self-report. If a delegated visual reviewer fails or times out, the Desktop parent must inspect every page image bound by that same unchanged request and return the complete outer verification-response object. The external parent-review launcher must stream the reviewer's raw stdout unchanged; it must not choose the last decoded JSON object or save a nested `finding` object. The installed workflow selects and atomically saves only the unique object accepted by the existing response validator and binding checks. A parent callback is complete only after every declared response path passes those checks. If a callback returns or raises without accepted responses, retry the parent once with the exact original request; if any response remains absent or invalid, stop immediately with `missing_parent_visual_review_response` rather than waiting for the operation deadline. Deterministic checks alone never count as Visual QA. A missing drafting response at the operation deadline is one consolidated technical blocker and does not consume a drafting retry.
6. Rerun `--stage generate`. The next `generate` call is the authoritative response validator; it accepts valid drafts, schedules targeted retries for rejected drafts, and returns the next handoff wave.

Repeat until the workflow passes or blocks. A missing drafting or delegated-worker response remains pending and does not consume a drafting retry; the bounded Desktop-parent rule above governs a missing parent visual response.

`awaiting_hermes` is internal orchestration state. Do not expose its requests, findings, drafting decisions, or progress questions to the reviewer.

During normal generation, use the provisioned `CLINICAL_PYTHON`; do not patch
code or templates, install packages,
run the repository development test suite, create a recovery operation, or
start a new deadline. An implementation defect becomes one technical blocker
for separate maintenance. Emit concise stage changes and a brief update at
least once per minute during a healthy wait.

## Why the work is split this way

For Prospective and Ambispective studies, the first drafting wave uses four parallel subagents:

1. `protocol-foundations`
2. `protocol-operations`
3. `protocol-analysis-and-oversight`
4. `icf-narrative`

After Foundations is accepted, a fifth subagent handles only the two PRS narrative values. Retrospective studies use the three Protocol batches and skip ICF/PRS.

This is the cost/quality balance approved for the skill:

- A single Protocol agent carries too much context and makes section omissions harder to isolate.
- One agent per tiny section adds avoidable cost and inconsistency.
- Three coherent Protocol batches let agents specialize while Python assembles one ordered contract.
- One ICF batch keeps participant language consistent across the consent form.
- The PRS narrative agent cannot alter XML; Python preserves the client-approved taxonomy and structure.

Subagents return section-level structured content, never a whole document. The workflow validates section IDs, request hashes, evidence references, boilerplate references, completeness, and forbidden placeholders before accepting a response.

For source-rich protocol sections, each drafting contract includes an
`approved_source_word_count` and a conservative `reference_detail_target_words`
soft compression signal. Semantic source coverage, not word count, governs
acceptance: retain the supplied clinical, statistical, visit, eligibility,
safety, retention, injury, and intervention detail without padding, repetition,
invention, or source-gap commentary. The Document Section Contract owns the
optional source-mode Section 8.3 and renders supplied treatment assignment
verbatim. Its typed table contracts render structured visit/procedure
relationships as the complete Schedule of Assessments and structured
sample-size evidence as its own Section 11 table. Both tables must preserve the
contracted headers, row and column order, cell associations, allowed blanks,
timing, and values before release.

## Retry behavior

- Repairable post-approval drafting, deterministic construction, layout, and
  reviewer-response failures retry within the one persisted 45-minute Desktop
  operation deadline. There is no fixed per-target, reviewer, or complete-review-set cap,
  except the Desktop-parent visual callback: after its initial callback, exactly one
  unchanged-request parent retry is permitted, with callback consumption persisted per exact request across process resume, before missing or invalid response evidence
  becomes `missing_parent_visual_review_response`.
- Invalid draft: retry only failed section IDs in their existing batch.
- Post-approval source-shortfall response: reject it as an invalid draft and retry only the affected section using approved evidence and its listed Fixed Clinical Boilerplate. Never reopen reviewer intake.
- Content contradiction: retry only implicated sections unless the approved source conflicts.
- Visual defect: localize the exact document, page, element, check, and layout
  target; apply the narrowest untried safe Word-native strategy; rebuild the
  affected artifact; and rerun rendered-page verification.
- Reuse unaffected accepted drafts.
- Every attempted repair records the actual strategy. A repeated finding must
  select a stronger untried governed strategy; identical raw DOCX ZIP bytes or
  ZIP-metadata churn never establish meaningful progress. Valid DOCX progress is
  measured from normalized member names and content hashes.
- When all safe deterministic strategies for one exact localized target are
  already present, re-prompt only the exact visual reviewer to reinspect and
  localize the unchanged artifact. Do not mutate the document blindly or consume
  a new complete review set.
- If any content or visual reviewer finds a governed repairable defect, preserve
  the failed evidence, repair only the implicated draft/layout target, then rerun
  the package-wide content review and every document-scoped visual review against
  the repaired candidate. Never reuse a pass from an earlier set.
- A transient API or structurally incomplete verification response retries only
  that reviewer within the current set and does not consume a new complete review
  set. A governed finding whose effective recovery target is missing, empty,
  wrong-category, or unsupported instead fails explicitly before any recovery
  attempt or journal is created. The bounded Desktop-parent exception above
  applies after delegated visual review has already fallen back to the parent.
- Only the persisted 45-minute deadline or a non-repairable integrity, source,
  renderer, safety, unsupported-template, unsupported-recovery-route,
  atomic-delivery, or exhausted bounded parent-response validation failure
  terminates the post-approval operation without client outputs.

## Independent verification

After rendering, `generate` returns one package-wide content request plus one
document-scoped visual request for each rendered DOCX. Run all requests
concurrently so every-page image inspection stays off the serial critical path:

- `clinical_content_verification`: checks source fidelity, every required section, unsupported claims, cross-document consistency, and participant-facing ICF language.
- `rendered_page_visual_verification`: each request inspects every supplied page PNG for one Protocol or ICF document and every listed check.

The visual verifier must use image inspection. File existence, DOCX text extraction, or PDF page count alone is not visual review. Visual QA is bound to the exact DOCX, PDF, and page-image hashes, and its response must include every page number and exact PNG hash with every requested check. Any changed document, PDF, or page image invalidates earlier evidence; missing or stale assessments block delivery. Before any content or visual response can become terminal, complete, recovery, or publication evidence, the workflow authenticates the exact request bytes and canonical payload hash against its workflow-owned request ledger; request or response self-declarations never establish authority.

Every independent verification response records both `producer.model_id` for the actual selected model and `producer.reviewer_id` for the independent reviewer role. These identities are mandatory, distinct bindings in Final Exact-Artifact Review; neither field selects or restricts which model the client may use.

Each request records its one-based `review_set`. A genuine finding invalidates
the entire prior verification set after its evidence is archived; all reviewers
then run concurrently on the repaired candidate. A structurally incomplete
verification response is retried as reviewer-transient. Once a finding declares
a governed Recovery Class, however, its effective target is normalized and
validated before archival; a missing, empty, wrong-category, or unsupported
route returns an explicit blocker without creating an attempt or journal, while
valid companion findings remain unchanged and unclaimed as repaired. Every
verifier-originated or verification-routed finding must carry its nonempty
`verification_request_id`; before archival the workflow resolves that identity
exactly once in the current authenticated request inventory and verifies its
request hash, task, review-set identity, and Run Revision binding. Pure
deterministic and drafting findings remain governed by their own route contracts
and do not fabricate a verification identity. Invalid routing is never silently
ignored or guessed by the workflow.

The Generation Manifest contains one hash-bound monotonic gate ledger in this
fixed order: clinical fidelity; content completeness and consistency; DOCX/PRS
structure; exact-artifact rendering; every-page Visual QA; exact-byte atomic
delivery. Each gate records its evidence hash, retry owner, terminal status, and
stable machine-readable findings. A later gate cannot pass while an earlier gate
is pending or blocked. A blocked record is terminal and immutable; a governed
retry starts a new retained attempt rather than replacing or erasing that failed
evidence. Each archived attempt stores its blocked ledger, and every later ledger
binds the ordered predecessor ledger hashes and blocked findings under the same
Run Revision attempt identity. The working reference also binds every retained
attempt directory to its manifest and ledger identities; missing, mutated,
duplicated, or forked attempt history blocks retry, resume, and publication.
Publication reconciles the complete candidate
inventory with exactly one passed render row and nonempty page evidence for each
DOCX, then rehashes every candidate DOCX/XML, PDF, and
page image against the accepted build immediately before staging, then rehashes
the staged client bytes before the atomic swap. Desktop confirmation advances
only the final pending gate and is persisted in the Desktop operation result.
Terminal replay revalidates both prepared and final ledgers and permits only that
one delivery-gate transition.

The deterministic render gate rejects pages with no meaningful body content, even when running headers or page numbers are present. Visual review must evaluate sparse continuation, signature, and consent pages according to their actual content and function. A sentence continuing across pages is not a content error; preserve meaningful choices and usable signature space rather than treating every sparse page as blank.

Candidate construction does not depend on the render environment. Build the complete Protocol/ICF/XML candidate first, then resolve DOCX rendering through host Microsoft Word or LibreOffice. Tool failure may advance between those office renderers; a successfully rendered visual defect stays bound to that renderer and enters repair instead of switching to obtain an easier pass. Page rendering always uses the release-owned `pypdfium2` 5.13.0 runtime. If PDFium fails, stop with the governed diagnostic; never discover or use another PDF backend.

Font evidence is tri-state. `available` preserves the declared font; `missing` selects the explicit release-owned compatible Liberation mapping and writes that substitution into the candidate; `unknown` preserves the declared font and decides capability through the disposable render smoke. Heuristic host substitutions are not accepted, and “cannot inspect” is never treated as “missing.” The manifest records renderer attempts, the one PDFium identity, font evidence, substitutions, exact artifact hashes, and page-image review. Installation owns offline PDFium provisioning and verifies the host office prerequisite; normal generation remains read-only.

