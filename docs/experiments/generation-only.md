# Generation-only experiment

## Settled scope

The owner requested an isolated worktree to inspect the initial generated
documents before deciding whether to replace the existing workflow.

- Preserve source approval and basic checks for missing or corrupt files.
- Produce the branch's DOCX and XML files only.
- Skip post-generation content review, visual review, and automatic repair.
- Retain drafting prompts and responses for inspection.
- Identify the outputs as unreviewed.
- Use the prompts from the owner's supplied n8n workflow as the drafting
  baseline, with the current DOCX templates and formatting. "Current prompts"
  means these n8n prompts, not the checkout's section-drafting prompts.
- The owner will generate the documents through Hermes. The owner and Codex
  will then inspect the actual files manually against Brad's recorded comments,
  including concise running titles and substantive, relevant section content.

The supplied workflow is reference data for prompt migration. Its Google Docs,
Gmail, credentials, pinned execution data and embedded automation are outside
the experiment's execution scope.

This is an experiment, not a decision to change client-ready delivery policy.
ADRs 0019 and 0022 continue to describe the existing reviewed workflow.

## Prompt policy

Brad's later corrections and approved source facts take precedence over
conflicting n8n instructions. Keep the n8n prompts for matching sections.
Retain applicable fixed client template language. Generate additional
study-specific sections from the approved source using the current section
instructions.

The owner confirmed these choices in the design interview on 15 October 2026.
Hermes execution and manual output review follow
[the experiment instructions](../../references/generation-only.md).

## Verification

On 15 October 2026, 36 focused tests passed across the experiment, Brad feedback,
and drafting-example checks. Controlled fixture responses produced readable
native files for all five branch/template combinations while patched
post-generation gates raised if called. Two representative ordinary reviewed
delivery tests also passed. All 22 original n8n prompt-node message lists were
compared directly with the supplied export and matched exactly. Skill validation,
Python compilation and whitespace checks passed. Linux requirements are unchanged.

The XML regression file had 22 passing and 11 failing tests. Those same 11
failures reproduced in the original checkout; they were not changed here.
No full suite or live model generation ran. The owner will generate with Hermes;
actual prose quality and document appearance remain for the agreed manual review.
