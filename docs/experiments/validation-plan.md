# Document generation validation plan

Agreed with the owner on 16 October 2026.
Branch: `codex/generation-only-experiment`.
Current candidate: retrospective coverage fixes (prompt v30), replacing `2017039`.
Record the installed commit from the next Hermes run receipt.

**Current step: Run 1, retrospective CHART-26-04, follow-up required.** The
first supplied Protocol has been reviewed. General source-coverage and table-formatting
fixes are implemented and locally tested; the actual Hermes rerun remains pending
before accepting Run 1 and continuing with Run 2. This file records
the agreed sequence; it does not schedule or start Hermes runs.

## Sequence

Complete these eight runs in order, excluding reruns needed for material fixes.
Keep the clinical input unchanged during the template-switch phase so that a
new input and a new template do not change at the same time.

| Run | Study | Clinical input | Consent family | Status |
| --- | --- | --- | --- | --- |
| 1 | Retrospective | CHART-26-04 | Not applicable | Reviewed; source coverage and opening-table borders need correction |
| 2 | Prospective | Existing approved NEAR source | Advarra | Pending Run 1 |
| 3 | Ambispective | Existing approved COMFORT source | Sterling | Pending |
| 4 | Prospective | Same NEAR clinical facts as Run 2 | Sterling | Pending |
| 5 | Ambispective | Same COMFORT clinical facts as Run 3 | Advarra | Pending |
| 6 | Prospective | New clinical input, to be prepared | Sterling | Pending |
| 7 | Ambispective | New clinical input, to be prepared | Advarra | Pending |
| 8 | Retrospective | New clinical input, to be prepared | Not applicable | Pending |

Runs 2–3 repeat the existing studies after the retrospective branch is settled.
Runs 4–5 change only the selected consent family, preserving the studies'
clinical facts. Record and approve that template-selection change through the
usual Source of Truth process. Runs 6–8 test fresh clinical inputs after the
template-switch results are accepted. Prepare and approve those inputs before
starting their runs; they have not been created yet.

The current retrospective workflow produces **only protocol.docx**, with no ICF
or XML. Prospective and ambispective produce protocol.docx, icf.docx and study.xml.

## Run 1 input and review focus

Input: [CHART-26-04-study-input.txt](inputs/CHART-26-04-study-input.txt).
A matching copy is saved at
`/Users/juanpabloleoni/Downloads/CHART-26-04-study-input.txt`.
Expected Hermes-host location after the owner transfers it:
`/opt/data/CHART-26-04-study-input.txt`; transfer has not been verified here.

Review the retrospective Protocol against the approved source, especially:

- Records-only design: historical clinical windows and future staff work phases
  remain distinct; no invented participant appointments, tests or contact.
- Requested consent/privacy waivers remain requested until actually granted;
  Source of Truth approval is not IRB approval.
- People versus eyes: 240 anticipated unique people and about 360 eligible eyes,
  with duplicate reconciliation, paired-eye dependence and per-outcome denominators.
- Baseline, early postoperative and Day 30 selection windows/rules, including
  positive pressure change meaning an increase rather than improvement.
- Missing measurements or unknown diabetes status do not silently become normal
  findings, absent diagnoses or cohort exclusions.
- Supplied analysis, privacy, retention, original-record custody and aggregate
  results policies are preserved; no new specimens, genetic testing or treatment.
- Retrospective section hierarchy, concise running title, readable tables and
  native TOC page references follow the selected Protocol template.

## Acceptance and handling findings

The owner and Codex review actual Hermes outputs against the approved source
and Brad's applicable comments. A run passes this development phase when no
material source omissions, unsupported clinical facts, inappropriate template
clauses or significant readability/formatting defects remain. This is not a
claim of guaranteed future model quality or formal approval for client use.

The owner explicitly accepted leaving the two smaller COMFORT findings alone:
the wording difference about instrument validation and the short final benefits
page. Do not reopen those items or polish harmless wording/layout differences
as a condition of progressing through this plan.

When a section is thin because the source is thin, record that source limit;
use a richer input later instead of expanding prompts to invent information.
For a material defect, trace source -> drafting request/response -> assembly.
Apply a general fix at the responsible layer, preserve the original n8n prompts,
run focused tests and replay affected saved responses, then rerun the affected
study in Hermes. If a shared change could affect already accepted branches or
families, retest those affected cases before accepting the new candidate.
Record the commit and approved-source identity for every run so results from
older versions are not mistaken for evidence about a newer candidate.

These are development reviews. Keep production generation as agreed: draft,
assemble, perform the single Protocol TOC refresh and deliver the native files.
No automatic content/visual review gate or repair loop is introduced by this
plan. Preserve Linux dependencies. Full-suite testing requires explicit approval.

## Evidence and completion

For each row above, record the commit, approved-source revision/hash, template,
run/output location or supplied archive, generation time, review findings and
owner/Codex acceptance. Update the status and next step here after review.
Retain compact approved inputs, accepted responses and representative outputs
for regression replay; avoid unnecessary duplicate installations or output sets.

Existing baseline evidence: the COMFORT archive
`COMFORT-26-03-2017039-entire-run.zip` used v29 and the unchanged approved source.
The major fixes held: specimen/results policy coverage, ICF typography, complete
GINA placement, XML investigator roles, visit numbering and all 43 TOC entries.
This earlier run is background evidence; Run 3 remains a planned repeat after
retrospective testing.

After all eight runs pass at the accepted candidate, freeze that version.
Subsequent material failures become focused regression cases; prompt, source
mapping or template changes receive affected-case replay and fresh Hermes tests.


### Run 1 first Protocol review — 16 October 2026

Supplied artifact: `/Users/juanpabloleoni/Downloads/protocol (9).docx`.
Reviewed against `inputs/CHART-26-04-study-input.txt`; the approved Source of Truth,
request/response archive, source revision/hash and generation time were not
supplied with this artifact. Requested candidate was `2017039`, but the DOCX
alone does not establish the installed code version or source-approval identity.

The Protocol renders in 10 pages, with all 21 native TOC entries matching.
Records-only design, ungranted waiver status, no new participant procedures,
historical versus staff-work dates, people/eyes distinction, measurement-selection
rules, missing-data denominators, clustered analyses and retention/results
policies are substantially preserved.

Three concerns remain before accepting this case:

1. The document states two sites but omits the supplied Severn Ophthalmology
   Center and its site investigator, Dr. Riley Chen. The coordinator contacts
   for the two sites are also absent. The study should identify its participating
   sites and supplied operational contacts.
2. Section 6.2 lists the surgical exclusions without explicitly identifying
   their eye-level scope. The supplied rule that an eligible fellow eye is
   retained when the other eye is excluded, and that the person is excluded
   only when both eyes are ineligible, is absent. Preserve that rule so readers
   cannot mistake an eye-level exclusion for exclusion of the whole person.

3. The opening retrospective table has white cell-border overrides, inherited
   from its template, so its lines disappear on the white page. The owner
   explicitly flagged this as a formatting concern. Make the opening table's
   borders visible and consistent with the agreed presentation of the other
   study types; this is a template/renderer issue, not a drafting-prompt issue.

The site and eligibility facts were supplied in the test input. A full run archive is needed to
trace whether they were lost during Source of Truth preparation or drafting/
assembly. No production code, approved source or supplied DOCX was changed in
this review. Minor repetition and layout preferences are not progression gates.
Run 2 remains pending acceptance of the corrected retrospective output.

### Run 1 general fixes — local validation

Prompt v30 / contract v2.49 preserves accepted eligibility prose and labeled
criteria instead of replacing them with a source-list-only fallback. Intake
and drafting retain supplied eligibility scope and exceptions. Retrospective
assembly now includes a source-derived site/investigator/contact directory
within the existing Study Design section. Opening Protocol tables use visible
cell borders across all three study types. The original n8n prompt library,
six production scripts, Linux dependencies and generation-only workflow remain.

Validation: 86 focused tests passed, followed by all seven retrospective cases
after the contract-owned placement refinement; Python compilation and diff
checks passed. A development layout preview using the supplied DOCX plus
explicit test-projected contacts and an input-grounded qualification paragraph
was rendered and visually checked at the affected pages. Its one native TOC
refresh passed at 10 pages. This is layout evidence, not a new Hermes generation
or evidence of the actual approved CHART source.

Spec review found no material issues. Standards review identified a hardcoded
section boundary; placement was changed to resolve the owner and boundary
from the shared section contract, then the focused retrospective tests passed.

Next: rerun from `/opt/data/CHART-26-04-study-input.txt` through normal Source
of Truth preparation and owner approval, then generate the retrospective
Protocol DOCX. Confirm both sites/contacts and eligibility qualifications are
in the approved source before generation. Run 1 remains pending that review.
