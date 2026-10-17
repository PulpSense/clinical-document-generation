# Shared content ownership and TOC verification — issue #125

The shared planning prompt assigns one full explanation to each operational
concept and records its owner in AI decisions. Every drafting batch receives the
same accepted plan and is told to coordinate with its optional sections, shell
passages, tables and notes. Optional sections carry distinct source-grounded
policies; an optional Patient Termination that only repeats Patient
Discontinuation is omitted by AI. Genuine distinct termination policies remain
permitted. Required synopses, safety qualifications and self-contained consent
language remain complete. Code does not decide applicability or remove prose.
The original n8n messages remain unchanged.

The TOC discrepancy reported in COMFORT __03 could not be reproduced within
one office environment. Its Hermes-generated cache differs from local rendering,
but local refresh followed by local final-DOCX rendering agrees for every
heading. This supports environment-dependent reflow, not an established bug in
the cache writer. The existing native TOC/PAGEREF fields remain updateable. The
single generation pagination pass now retains its complete heading/page map in
office-field-refresh.json. No second generation pass, content gate, repair loop,
new dependency or Linux runtime change was introduced.

## Evidence

- Final focused regression run: 77 passed in 154.54 seconds across shared
  ownership, real office pagination, generation, immutable authority, native TOC,
  subsection numbering, AI content plans and citation/form handoffs.

- The new prompt handoff regression failed before the guidance change, then
  passed for Prospective/Advarra, Prospective/Sterling, Ambispective/Advarra,
  Ambispective/Sterling and Retrospective. It checks that the shared AI ownership
  decisions reach every batch and that source facts stay separate.
- Real-office tests compare the final DOCX cache against a second, test-only
  render for all three study types. The map records actual PDF outline pages,
  including nonconsecutive pages, rather than guessed heading indices.
- Twelve public-workflow local replays passed: BREAK/Sterling; CAPS;
  COMFORT/Advarra; COMFORT/Sterling; GLIDE/Advarra; NEAR/Advarra;
  NEAR/Sterling; PureSee; RECORD; final COMFORT; final PureSee; actual Hermes
  COMFORT __03. All 484 final TOC entries match their respective final renders.
  Approved local source files remain unchanged; generation is idempotent.
- Ten non-retrospective cases include locally authored AI writing trials for
  Discontinued Subjects, Patient Discontinuation and optional Patient
  Termination. GLIDE's distinct medication-change exception was moved with its
  policy rather than discarded. The actual COMFORT __03 trial places its full
  grounds/rights in Patient Discontinuation and omits the duplicate heading.
  Sections become 18.1 Completion, 18.2 Discontinuation, 18.3 Study Completion.
  Existing numbering/cross-reference and immutable-authority regressions pass.
- Native assembly preserves accepted ICF paragraphs, including repeated consent
  language needed for participant understanding. Applicable Sterling COMFORT
  GINA remains present. Every generated XML matches Brad's structural reference.
- All 20 pages of the updated COMFORT protocol were inspected locally. The
  overlapping termination section is absent and the TOC agrees. Previously
  noted minor layout issues are outside this repetition/TOC change.

These are focused locally authored writing trials and archived-response replays,
not fresh external-model inference or a claim that every future response will
follow the prompt. A fresh Hermes rerun remains the live behavior check. No full
suite or Microsoft Word validation was run. results.json retains corpus
receipts; writing-trials.json retains the before/after writing samples.

An older citation handoff assertion still claimed code owned the bibliography.
It now checks the already-established AI-plan ownership and single assembly
placement; citation formatting and source-evidence requirements are unchanged.
