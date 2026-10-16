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

## First PureSee/Odyssey output review — 15 October 2026

Reviewed the owner's `UNREVIEWED-protocol.docx`, `UNREVIEWED-icf.docx`,
`UNREVIEWED-study.xml` and `SYNOPSIS_PureSee Odyssey_23Jun2026-2.txt`, together
with the operational supplement supplied in this chat. All original input files
remain untouched. No Hermes approved-source file or drafting responses accompanied
these outputs, so this comparison establishes what reached the documents rather
than proving exactly which intake/drafting step caused every omission.

The original Protocol rendered to 11 pages and the Advarra ICF to 6 pages using
the bundled LibreOffice renderer. Page images and native text were inspected;
this is LibreOffice evidence, not Microsoft Word validation. The documents are
generally readable, with usable tables, repeated matrix headers and signatures.
The significant formatting defect is the empty Protocol TOC on page 4.

### Brad's comments against this run

| Comment | Observed result | Action |
| --- | --- | --- |
| 0, short running title | The derived title wraps over two header lines and retains a long introductory phrase. | Tighten the intake prompt for concise derived running titles; preserve explicit client titles. |
| 1, Variables | All eight supplied primary/secondary outcomes appear with the 3-month timing. | Preserve. |
| 2, postoperative follow-up | The synopsis cell says `3 months`; body sections identify the postoperative visit. The summary cell itself does not retain the postoperative qualifier. | Strengthen intake preservation of narrative timing anchors. Deterministic summary projection is unchanged. |
| 3–4, Introduction | One supported background paragraph distinguishes evidence for individual lenses from the combination's evidence gap. | Preserve. |
| 5, Objectives | Concise purpose statement, separate from the endpoint inventory. | Preserve. |
| 6, Bias | Brief bias statement and limitation rather than another full design account. No study-specific bias procedures were supplied. | Preserve; do not invent more procedures. |
| 7, Measurements | Names the visual-acuity distances, correction conditions, defocus curve and AIOLIS assessment rather than restating the hypothesis. | Preserve. |
| 8, Visit wording | The unscheduled-visit section uses generic `contact` wording. | Add a conditional writing correction for in-person visits, without authorizing new visits or procedures. |
| 9–10, Statistics | Shared methods are grouped; descriptive interpretation is meaningful and agrees with the operational supplement. | Preserve. |
| 11, Matrix formatting | Activity capitalization, repeated headers, marks and row flow are readable. | Preserve the design. |
| 12, Schedule repetition | Main Section 15 introduction is concise, but a repeated adverse-event sentence is emitted below the matrix. | Record the remaining assembly issue; no semantic rendering rewrite under this task's scope. |
| 13, Confidentiality | Brief confidentiality text; detailed access, retention and disclosure operations were not supplied. | No prompt expansion. Test with a future source containing those details. |
| 14, Completion | Participant completion, discontinuation and the study-wide enrollment/follow-up/analysis timeline remain distinct. | Preserve. |

### General prompt changes

The original n8n messages and demonstrations are unchanged. Target-specific
editorial additions now ask for a compact Advarra purpose section, one account
of the visit itinerary, participation duration without repeating that itinerary
or sponsor administration phases, expected enrollment once in the approved
count/unit, and a compact grouped endpoint list with shared timing stated once.
They preserve material facts and applicable fixed consent language; word counts
are guidance, not gates. No extra detail is demanded for sparse privacy, injury,
cost, risk, bias or completion inputs.

Intake prompts now distinguish visit labels/occurrence counts from actual timing
windows. This addresses the awkward `Screening / Screening` and repeated
`Operative; one visit per eye` displays without inventing numerical windows.
It also improves future plain-language ICF visit displays. The existing ICF
renderer appends a timing list when its exact-string check does not recognize
the authored wording; that semantic assembly mechanism was not changed.

The XML retains the sample size, observational classification and all eight
outcomes, but omits the supplemental 30-day eligibility restriction that appears
in Protocol and ICF. Its condition and IRB-submission fields are empty despite
corresponding information in the synopsis, and intervention type contains a
narrative qualifier. Intake instructions now explicitly carry separately supplied
eligibility restrictions into canonical criteria and distinguish supported coded
fields from narrative descriptions. These are future intake corrections, not a
claim that the uploaded XML is repaired or registry-ready. Fields whose values
were genuinely absent from the source remain absent.

### Formatting fix and verification

Initial native assembly now builds the same linked Word TOC cache used by the
existing rendered workflow. Entries and heading bookmarks are immediately
visible; live PAGEREF fields remain available for Word to calculate. Page-number
caches stay empty until an office application supplies actual pagination. No
PDF stage, reviewer, quality gate, heuristic veto or repair loop was added.

A replay on a copy of the uploaded Protocol replaces the blank field with the
linked TOC. The replay rendered to 12 pages with the TOC on pages 4–5; clinical
body paragraphs and every table value remained unchanged. Source files were
not overwritten. Regression cases reproduced the empty TOC before the fix and
passed afterward across Prospective, Ambispective and Retrospective assembly.
The focused experiment, Brad feedback, drafting examples, native TOC and existing
PDF-cache-refresh checks passed (40 tests). The full suite was not run.

Prompt improvements still need a fresh Hermes run for evidence of actual model
behavior. Current uploaded documents remain the baseline for that comparison.
