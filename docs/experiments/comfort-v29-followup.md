# COMFORT v28 follow-up fixes

The user supplied `COMFORT-26-03-2fe14bb-entire-run.zip` and requested general
corrections, local testing, a GitHub push and a COMFORT rerun using the same
approved Source of Truth. The run used v28 and the same approved reference as
the retained COMFORT fixture.

## Changes

- The shared section contract assigns `procedures.specimens` and
  `procedures.return_of_results` to Protocol measurements (prospective and
  ambispective), Protocol enrollment/record-review procedures (retrospective),
  and ICF procedures. Instructions preserve supplied handling, coding,
  recipients, destruction timing/deadlines, future-use restrictions, data versus
  specimen retention, individual/research/incidental/aggregate results and
  routine-care referrals. Absent optional policies remain absent.
- Sterling generated list text now uses family body typography. Paragraph-mark
  formatting is normalized too, removing yellow marker highlighting while
  preserving native numbering and indentation. Template headings remain styled.
- Triggered controlled Sterling clauses keep their heading and authorized
  paragraphs together. The last paragraph ends the keep-with-next chain.
- XML site-investigator roles use the approved title when an explicit role is
  absent. Explicit roles retain precedence; neither value is invented.

Prompt v29 and contract v2.48 identify this change. The original n8n prompt
library is byte-identical to the starting commit. No production scripts,
dependencies, content/visual gates or repair loops were added.

## Verification

Focused tests exercise real drafting handoffs, DOCX rendering and XML generation,
including all three Protocol branches, both ICF families, explicit-role
precedence, missing optional policies, unchanged source data, actual saved v28
risk paragraphs/lists and the controlled GINA block. Existing focused replay,
source-owned drafting, editorial, spacing, contact pagination, office-refresh
and generation-only workflow tests passed. Syntax and whitespace checks passed.
The full suite was not run.

Local visual replay: the actual v28 ICF prose renders in eight pages with clean
risk bullets and the complete GINA clause on page 7. A separate Protocol preview
adds three manually drafted, source-grounded development paragraphs to the saved
v28 response to exercise the newly owned policies; it renders in 19 pages. One
native TOC refresh passed and all 43 entries match the pagination PDF. These are
development previews, not newly generated Hermes outputs or client deliverables.
Fresh model compliance with the new instructions remains for the requested
COMFORT rerun. The approved source was not edited.

## Standards

Independent review found no documented-standard violations or actionable smells.

## Spec

Independent review found no missing requirements, scope creep or incorrect
implementation. Saved-response replay and manual development prose are
explicitly distinguished from fresh Hermes drafting.
