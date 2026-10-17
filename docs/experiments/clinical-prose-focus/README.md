# Clinical prose focus — 17 October 2026

Issue #122 addresses the PureSee `__03` run reviewed on commit `73d071c`.
The owner confirms that preparing its new Source of Truth was intentional.
The run correctly preserved all 69 authored text blocks, but its AI responses
included an internal test-input notice in Ethics, unresolved form-marker
commentary in a table note, and a literature-heavy benefits summary with
source citation punctuation such as `context.1,2`.

## Changes

Shared drafting instructions keep internal provenance, preparation/approval
workflow notes and marker-interpretation explanations in run records or
structured rationales. Actual ethics submission/approval/exemption/waiver status
and material clinical uncertainties remain in the documents. Ambiguous form
identifiers remain as supplied; this change does not infer or remove a number.

The assessment-presentation contract and supplemental n8n table correction now
allow an empty display note when it contains only internal commentary. Unique
safety instructions, timing, conditions and genuine explained footnotes remain.
Protocol and ICF benefits sections request one concise paragraph preserving
distinct benefits, uncertainty and no-direct-benefit statements. Prior studies
and lens-design explanations remain with background literature. Background
quotation pairs can still support the internal benefit interpretation.
Protocol citation numbers use square brackets before sentence punctuation.

These are prompt instructions only. Assembly, XML mapping, source files,
formatting, numbering and TOC code are unchanged. No content gate or repair loop
was introduced. All 22 original n8n nodes/messages are unchanged. Versions:
`clinical-documents-v2.55-clinical-prose-focus` and
`section-drafting-v36-clinical-prose-focus`.

## Verification and limits

The public handoff regression failed before the prompt changes and passed
afterward across Prospective and Ambispective with both consent families and
Retrospective. All 41 focused tests passed, covering the handoffs, AI prose
ownership, existing editorial regressions and historical prompt transport.
The eight prompt tests also passed again after aligning the supplemental table
correction. Python compilation and diff whitespace checks pass. The full suite
was not run under the owner's focused-test constraint.

`trials.json` retains 34 section responses accepted through current public
request bindings across 46 full-batch handoffs for 10 saved source/family cases:
NEAR and COMFORT in both families, BREAK, GLIDE, RECORD, CAPS, earlier PureSee
and the new PureSee `__03` source. Sources remain unchanged. Already concise
benefit sections and prior ethics/assessment drafts were reused. Codex locally
redrafted the two PureSee benefit sections for each source, the new PureSee
ethics paragraph and its unresolved-marker table-note edit. The table projection
retains Form1 and removes only the explanatory note. No DOCX/XML study outputs
were generated for these trials.

These are controlled local section trials and public transport checks, not
fresh Hermes model runs or a guarantee of identical future prose. Manual
inspection confirms the local revisions preserve the supplied qualifications,
current IRB status and form identifier while removing the observed repetition
and internal commentary. The next Hermes run checks model compliance.
