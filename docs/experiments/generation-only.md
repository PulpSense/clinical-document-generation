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

## Table-note follow-up — 16 October 2026

The owner authorized a general assembly correction for the repeated table note.
Supplemental notes now omit exact activity/visit statements when the same
relationship is already marked in the assessment matrix. The comparison applies
to any activity and to both typed schedules and source matrices; no study or
product names are special-cased. Case, whitespace and sentence punctuation may
differ. Paraphrases and uncertain relationships are retained rather than guessed.

Different timing, unmarked visits, nonunique timing aliases, quantities, actors,
conditions and ongoing monitoring instructions remain visible. An independent
additional sentence is retained when its preceding duplicate is omitted;
cross-sentence qualifications retain their original activity context. Approved
source data and table marks are unchanged, and no new generation gate runs.

The native-output regression also exposed a section-inspection ambiguity after
the TOC fix: linked TOC entries could be mistaken for actual body headings.
Section snapshots now select real heading paragraphs, preserving inspection of
the document body rather than returning TOC entries.

Focused table-note, assessment-matrix, existing note-preservation and native-TOC
checks passed: 49 tests. One unrelated lexical-review-caution test fails unchanged
in the original checkout and was excluded from that passing selection. The full
suite was not run. The original TOC fix remains included: earlier downloaded
files require regeneration to acquire the visible linked entries, with page
numbers populated when Word updates its fields.

## Consent-template follow-up — 16 October 2026

The supplied Sterling consent template matches the retained reference exactly.
Its 14 comments include 12 resolved comments and two open IRB comments: leave
IRB-owned merge fields for the IRB, and retain the exact registry statement when
applicable. Historical comments guide drafting but do not supply study facts.
The approved family selection remains authoritative: Advarra front metadata is
populated; Sterling IRB-owned front merge fields remain reserved.

Advarra metadata labels and values now have explicit left alignment, avoiding
inherited body justification. Cosmetic trailing empty cell paragraphs are
removed while native fields and multiline labels remain intact. Other tables,
body formatting and family layouts are unchanged. A copy of the uploaded ICF
was rendered with bundled LibreOffice and all six pages inspected; metadata
values remained unchanged. The desktop LibreOffice window could not be opened,
so comments were inspected from their anchored DOCX XML instead.

Generation-only prompt guidance now covers the selected family's key information,
conditional pregnancy testing and reproductive risks, results disclosure and
blinding, withdrawal follow-up, privacy terms and registry/GINA applicability.
Supplied conditional evidence is routed to the relevant existing ICF section;
absent details do not create new requirements or invented study content. Original
n8n messages remain unchanged, and no new generation gate is introduced.

Focused front-matter, template-comment, generation-only and Brad-feedback checks
passed: 43 tests. One existing reviewer-instruction literal-string test fails
unchanged in the original checkout and was excluded. The full suite was not run.
Prompt behavior still needs a fresh Hermes generation for manual comparison.

## Experimental script cleanup — 16 October 2026

The owner requested removal of scripts outside the active generation path.
This checkout now retains six Python files: workflow, contracts, drafting,
rendering, PRS XML and output_recovery. The last still supplies field mappings
and compatibility helpers imported by drafting/rendering; it is not an active
post-generation repair stage. Nine review, worker, callback and storage files
were removed. The workflow retains source preparation, approval, source-readiness
validation and generation-only assembly; obsolete Desktop, release and review
operations were removed rather than left calling deleted modules.

Plain `--stage generate` now uses the same experimental lifecycle as the retained
`--generation-only` compatibility flag. Skill instructions and README describe
only the supported lifecycle. Existing Linux dependency declarations are unchanged.
Historical reviewed-workflow tests/references remain as repository history and
are outside this checkout's supported execution path. The original reviewed
implementation remains in the primary checkout and Git history.

Delivery includes clean document links followed by generation time from recorded
elapsed seconds. Focused native-generation, obligatory-intake, TOC and front-table
checks passed (45 tests), plus two fresh-process CLI cases for generation with
and without the compatibility flag. The full suite was not run.

## Latest output follow-up — 16 October 2026

Manual inspection covered all 12 Protocol pages and all six Advarra ICF pages
from the latest uploaded output, plus the XML. The short header, visible linked
TOC, left-aligned populated Advarra metadata, complete endpoint inventory and
Brad's XML structure were present. Remaining findings included duplicate timing
prose inserted by the ICF assembler, a redundant source assessment note below
the Protocol matrix, inconsistent derived visit numbering, and negative
eligibility wording under the XML Exclusion Criteria heading.

The ICF assembler no longer appends a timing inventory based on exact-string
matching; accepted source-bound drafts own the wording. Regression tests cover
plain-language timing in both families. Prompt guidance now uses the existing
assessment_presentation edits to omit wholly redundant notes while retaining
unique conditions, timing and safety details. A handoff-to-native-output test
checks that a redundant-note edit survives and a unique instruction stays visible.

Intake guidance now keeps phase labels distinct from occurrence counts and asks
for consistent source-approved numbering. It also places eligibility requirements
and disqualifying conditions with the correct polarity before source approval.
Approved facts are not silently reclassified during XML assembly. Narrative IRB
submission status is distinct from an explicitly supplied PRS approval status;
"not submitted" does not authorize an inferred "Pending" value. Missing optional
PRS values remain blank.

Original n8n node messages remain unchanged. These changes add no review or
repair stage and retain six scripts. Prompt effects need a fresh Hermes run with
source preparation for manual verification. TOC page-number caches still require
office pagination; adding a field-refresh step awaits the owner's choice.
Focused generation, repetition, metadata and obligatory-intake checks passed:
73 tests. No full suite or new live Hermes study generation was run.
