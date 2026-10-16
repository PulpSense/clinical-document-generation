# Document generation validation plan

Agreed with the owner on 16 October 2026.
Branch: `codex/generation-only-experiment`.
Current candidate: registry disclosure mapping fix (contract v2.50, prompt v30),
built on retrospective coverage commit `8d48c22`.
Record the installed commit from the next Hermes run receipt.

**Current step: Run 6 disclosure fix implemented and locally replayed; Hermes rerun pending.**
CHART, current-version NEAR/Advarra, COMFORT/Sterling, NEAR/Sterling and
COMFORT/Advarra pass Codex review. Both template-switch tests pass review.
The owner now operates Hermes and uploads complete run archives for review;
computer operation is no longer delegated. Fresh approved Source of Truth records
are present for Runs 2–3. Preserve those clinical facts during template switches.
Next: rerun BREAK with the disclosure fix before Run 7.

## Sequence

Complete these eight runs in order, excluding reruns needed for material fixes.
Keep the clinical input unchanged during the template-switch phase so that a
new input and a new template do not change at the same time.

| Run | Study | Clinical input | Consent family | Status |
| --- | --- | --- | --- | --- |
| 1 | Retrospective | CHART-26-04 | Not applicable | Codex review passes; owner delegated continuation |
| 2 | Prospective | NEAR input with freshly approved Source of Truth | Advarra | Current-version rerun passes Codex review; owner acceptance pending |
| 3 | Ambispective | COMFORT input with fresh Source of Truth | Sterling | Current-version run passes Codex review; owner acceptance pending |
| 4 | Prospective | Same NEAR clinical facts as Run 2 | Sterling | Passes Codex review; owner acceptance pending |
| 5 | Ambispective | Same COMFORT clinical facts as Run 3 | Advarra | Passes Codex review; owner acceptance pending |
| 6 | Prospective | BREAK-27-05, approved revision r-3a7da16f6dea | Sterling | Local disclosure fix passes; Hermes rerun pending |
| 7 | Ambispective | New clinical input, to be prepared | Advarra | Pending |
| 8 | Retrospective | New clinical input, to be prepared | Not applicable | Pending |

Runs 2–3 repeat the existing studies after the retrospective branch is settled.
Runs 4–5 change only the selected consent family, preserving the studies'
clinical facts. Record and approve that template-selection change through the
usual Source of Truth process. Runs 6–8 test fresh clinical inputs after the
template-switch results are accepted. Prepare and approve those inputs before
starting their runs. Run 6 input is retained below; Runs 7–8 inputs remain pending.

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

### Run 1 rerun review — 16 October 2026

Supplied archive: `/Users/juanpabloleoni/Downloads/CHART-26-04-8d48c22-outputs.zip`.
Contains only `protocol.docx`. Filename identifies candidate `8d48c22`, but no
installation receipt, approved-source revision/hash or generation time was
supplied; those identities remain unverified.

Protocol SHA-256: `7a0dae823282dc41b96fc59021e26f6abf371381d7bcf15dcd14661cd3aac0b4`.
Reviewed all 11 rendered pages and compared content against the original
CHART input. All 21 cached TOC references match the rendered heading pages.
Opening borders are visible; both facilities, investigators and coordinator
contacts are complete; Section 6.2 preserves eye-level exclusions, retention
of an eligible fellow eye, person exclusion only when both are ineligible,
and missing measurements affecting analysis rather than cohort eligibility.

Records-only procedures, requested rather than granted waivers, people/eyes
counts, historical windows and measurement-selection rules, outcome-specific
denominators, clustered statistics, privacy and retention policies remain
consistent with the input. No material content or layout finding identified.
Minor withdrawal/disposition repetition within Section 8.1 is recorded but is
not a progression gate under the owner's stated priorities. No supplied
document or production code changed during review.

Codex document review passes; owner acceptance remains pending. After that,
continue with Run 2: NEAR prospective / Advarra, using its existing approved
Source of Truth. Do not switch templates or introduce a new clinical input yet.

### Run 1 Source of Truth follow-up — 16 October 2026

Owner subsequently supplied `/Users/juanpabloleoni/Downloads/source-of-truth.md`.
File SHA-256: `2a3553af26a3a969fdbdeae7f14854b2a71dc3d88efbf136ab4809bb0ec4b5a4`.
Compared its marked fields against the already reviewed CHART rerun. Both sites
and their contact details, eye/person eligibility qualifications, historical
selection windows and tie rules, outcome definitions/denominators, clustered
analysis, dates, waiver status, privacy and retention policies are consistent.
No material discrepancy found; Codex document-review pass stands. This supplied
source closes the earlier source-content comparison gap; it does not provide
a machine approval receipt or installed-code attestation. Those records were
not supplied. Source facts and document have not been modified. Owner acceptance
and the planned NEAR prospective/Advarra repeat remain the next steps.

### Delegated continuation — 16 October 2026

The owner authorized Codex to operate Hermes, continue the plan, make general
fixes and test until completion. They clarified that old runs were deleted and
the Source of Truth will be newly prepared, and requested an entire-run ZIP
after every study generation. Preserve each run's input, Source of Truth,
approval record, draft requests/responses, logs, outputs and installed version
evidence in that ZIP; download through Hermes Files.

Hermes was already completing NEAR with owner source approval visible in its
chat. It reports generation time 2 minutes 49 seconds and a 91-file, 7.86 MiB
archive at `/opt/data/clinical-document-runs/NEAR-27-02-entire-run.zip`. These
reported details await archive inspection. Chrome blocked its Files download
as insecure; the owner was asked to click Keep themselves. No security setting
was changed or warning bypassed by Codex.

### Run 2 archive review — 16 October 2026

Owner supplied `/Users/juanpabloleoni/Downloads/NEAR-27-02-entire-run.zip`
after taking over manual Hermes operation and downloads. Continue through
owner-uploaded archives; earlier autonomous browser operation was withdrawn.
Archive SHA-256: `980a0a45c472ed459b8ae1c3ad9515da34025e6e1979cd765d3cfd89ed8ca4c1`.
Revision `r-889398fb1465`; recorded approved source digest
`60094cc2b38af7bf7982e1158d2a964642c630130cf4e027afa22bb5fe9a805b`.
Recorded generation time: 169.213664 seconds. All three delivered output hashes
match the manifest.

This is not validation of current candidate `8d48c22`: all five drafting requests
record `section-drafting-v25-live-run-reliability` and section contract
`clinical-documents-v2.44-applicable-intake-and-native-review`; five production
script hashes differ from the local candidate. Renderer bytes match the
historical `576ad49` version, drafting bytes match `957d663`, and contract
bytes match `c08a6a9`. These identify matching file histories, not a proven
single installed Git commit. Current candidate uses prompt v30/contract v2.49.

Rendered Protocol: 15 pages; ICF: 8. All 43 native TOC references match the
render. ICF pages were visually reviewed, Protocol overview and affected
table/contact pages inspected. Study design, visits/outcomes, payments and
authorization/retention distinctions are substantially preserved.

Findings in these superseded outputs:
- ICF p6 copies the authoring direction “Do not promise free treatment or
  automatic payment” from approved injury source into participant text. The
  old request has no dedicated injury draft; current contracts/renderer do.
- Both sites are in approved source, but ICF identifies only the first site's
  contact/address. Its instruction to write to the participant's own site
  coordinator lacks the second site's details. The second investigator and
  coordinator also do not appear in the Protocol contact block.
- XML location investigator roles are empty despite supplied titles.
- Protocol assessment table gives the reading-glasses response choices their
  own activity row; repeat rescheduling/enrollment prose remains.
- Opening Protocol table lacks visible lines, and legacy duplicate
  `generation-only-output` artifacts remain.

Do not count Run 2 as passed or introduce speculative new prompt changes from
this old implementation. Fetch AND activate candidate `8d48c22`, verify the
installed skill's version and implementation identity, then regenerate fresh
drafts/outputs from this same approved source. Retain a complete run ZIP plus
installed commit/version evidence. Review remaining findings on that candidate
before deciding whether further fixes are necessary. Run 3 remains pending.

### Run 2 current-candidate rerun — 16 October 2026

Archive: `/Users/juanpabloleoni/Downloads/NEAR-27-02-8d48c22-entire-run.zip`.
Archive SHA-256: `892596f2d57c31f18c5908caf03ebf55d0c0a8541a28a868af6e9d7282a931de`.
Candidate `8d48c220c69d4b824cb465b3feafd77ac7e47f49` is supported by
installed-version evidence, all six archived scripts matching local candidate
bytes, and all five drafting requests identifying matching implementations,
prompt v30 and contract v2.49. Approved-reference bytes are unchanged from the
previous run, revision `r-889398fb1465`, source digest
`60094cc2b38af7bf7982e1158d2a964642c630130cf4e027afa22bb5fe9a805b`.
Generation time: 2 minutes 44.30 seconds. All three final file hashes match
the manifest; delivery is directly under `output/`, with no duplicate legacy
`generation-only-output` folder.

Reviewed all 15 Protocol pages, all 7 ICF pages and XML against approved facts.
All 43 TOC references match the rendered pages. Opening Protocol borders are
visible, the assessment matrix no longer treats questionnaire response choices
as a separate activity, and the ICF injury text is participant-facing without
the source's authoring instruction. ICF identifies both clinic addresses and
both coordinators with business/office phones, emails and mailing addresses.
XML preserves both investigators' roles, two exposure groups, all five outcomes,
observational/prospective design, enrollment, ages and completion dates.

No material finding preventing progression identified. Main clinical facts,
visit windows/durations, payments, results return, withdrawal, authorization
end and retention policies are preserved. Minor notes retained without new
fixes: repeated ICF enrollment target; Protocol AE contact block still lists
the overall coordinator rather than every local contact (both local contact
records are in ICF/XML, both facilities are in Protocol); short final Protocol
benefits page. These are not treated as progression gates under the agreed
focus on material issues. No production or supplied output files were changed.

Run 2 passes Codex review; owner acceptance pending. Next after acceptance:
Run 3, COMFORT ambispective / Sterling, from
`/opt/data/COMFORT-26-03-study-input.txt`. Old runs were deleted, so prepare
and approve a fresh Source of Truth rather than claim reuse of a missing
approved revision. Keep candidate `8d48c22`, and ZIP the entire completed run
with its approved source, drafts, logs, final files and version evidence.


### Run 3 current-candidate COMFORT review — 16 October 2026

Archive: `/Users/juanpabloleoni/Downloads/COMFORT-26-03-entire-run (1).zip`.
Archive SHA-256: `46aacc5be198bab79f35b52cc507114069457ced09e2eabc256724a0bf610105`.
All five drafting requests identify prompt v30 / contract v2.49, with all six
implementation hashes matching local candidate `8d48c22`. This ZIP does not
contain a separate installed Git commit attestation; implementation identity
is established by the request hashes. Approved revision: `r-7325669e7b3f`;
approved-source digest:
`c7259b3ef969d088bc89a3b5e3dc00b283aeafed1f51df48e0adb1f4b1ecbf5d`.
Generation time: 3 minutes 15.98 seconds. All three output hashes independently
match the manifest. Production content/visual assessments were not run, as agreed.

Reviewed all 19 Protocol pages, all 7 ICF pages and XML against the approved
source. All 43 native Protocol TOC references match the rendered headings.
Opening table borders are visible, the AE contact table stays on one page,
the assessment matrix repeats its headers, and ICF signatures fit cleanly.
Sterling merge fields are deliberately retained; all three site coordinator
contacts and the complete applicable GINA section are present in the ICF.

The outputs preserve one consenting 90-person ambispective cohort, historical
record abstraction only after consent/authorization, the fixed historical
window, and 90-day prospective follow-up from enrollment. Day 30 remains a
telephone contact without vision testing or saliva. Required saliva occurs
only at Day 0; targeted research genotyping, no individual genetic/incidental
results return, specimen destruction deadlines, no banking/future use, coded
data retention, authorization end, withdrawal and payment rules are retained.
XML preserves observational classification, ambispective timing, enrollment,
ages, all three sites and lead investigator roles, and all six outcomes.

No material finding preventing progression identified. Minor notes, not gates:
Protocol AE table lists the overall coordinator; all local contacts appear in
ICF/XML. XML dedicated biospecimen fields are empty, while its detailed narrative
preserves specimen/genotyping/destruction facts; its date strings follow the
approved structured source. This was source/format review, not registry import
validation. No production code, source facts or supplied output files changed.

Run 3 passes Codex review; owner acceptance pending. Next is Run 4: retain the
accepted NEAR Run 2 clinical facts and change only consent selection to Sterling
through normal Source of Truth approval. Keep candidate `8d48c22` and retain an
entire-run ZIP including approved source, drafts, logs, output and version evidence.


### Run 4 NEAR Sterling template switch — 16 October 2026

Archive: `/Users/juanpabloleoni/Downloads/NEAR-27-02-Sterling-entire-run.zip`.
Archive SHA-256: `1afe8824856c6d4c320a124edeb901fb0cea9018214fade979f58eab181d0808`.
Installed-version receipt identifies `8d48c220c69d4b824cb465b3feafd77ac7e47f49`.
All five drafting requests identify prompt v30 / contract v2.49 and all six
implementation hashes match local candidate bytes. Approved revision:
`r-50da9678f2f7`; approved-source digest:
`369d4e63678713c0949c652228785988fb954e5d914d6f50b34ebc80022df615`.
Independent recursive comparison with accepted Run 2 approved-reference JSON
finds only `meta.icf_template` (Advarra to Sterling) and approval identity/time/hash
metadata changed. Clinical facts are unchanged. Generation: 3 minutes 54.51
seconds; all three delivered file hashes independently match the receipt.

Reviewed all 14 Protocol pages, all 7 ICF pages and XML against approved facts.
All 43 native Protocol TOC references match rendered headings. Opening borders
are visible; AE contact table stays on one page; the assessment matrix and ICF
signature page are readable without clipping or overlap. Sterling opening merge
fields remain deliberately unpopulated; actual contacts for both clinics appear
in the Questions section. Genetic, future-specimen-use, LAR/witness and mandatory
registry disclosure clauses are appropriately absent for this source. The
supplied study-specific IRB contact remains, without claiming Sterling approval.

Main study facts hold: 80 people, two prior-lens exposure cohorts, no assigned
treatment, 12-week prospective follow-up, Day 0/Week 6/Week 12 windows and
durations, binocular uncorrected testing, all five outcomes, supplied adjusted
analysis, no invented power assumptions, no specimens, payments/reimbursement,
return of vision results, optional withdrawal discussion, finite authorization
and seven-year retention after closeout. XML retains both site investigators'
roles, locations, outcomes and source dates. Registry import was not tested.

No material finding preventing progression. Minor repetition and the previously
noted overall-coordinator-only Protocol AE table remain outside progression
gates. Two unchanged source prose fields still refer to the original Advarra
family, while the governing template selector is Sterling; that stale source
wording did not leak into the output or alter the selected family. No source
facts, production code or supplied outputs were changed by this review.

Run 4 passes Codex review; owner acceptance pending. Next: Run 5, COMFORT using
the accepted Run 3 clinical facts, changing only the governing consent-template
selection from Sterling to Advarra through normal Source of Truth approval.
Keep candidate `8d48c22` and package the entire completed run with source,
drafts, logs, outputs and installed-version evidence.


### Run 5 COMFORT Advarra template switch — 16 October 2026

Archive: `/Users/juanpabloleoni/Downloads/COMFORT-26-03-Advarra-entire-run.zip`.
Archive SHA-256: `632a852b853d091d2c48bc3f0426f054586f8f3a9ff5402d4d7d16e18442260e`.
Installed receipt identifies `8d48c220c69d4b824cb465b3feafd77ac7e47f49`.
All five requests use prompt v30 / contract v2.49, and all six implementation
hashes match local candidate bytes. Approved revision: `r-b3f2e1829cad`; source
digest: `d257557cddeb4f78c54c0d0eeab16761bf4027225375d0efc8deae71468166a6`.
Independent comparison with Run 3 approved-reference JSON finds only the
Sterling-to-Advarra selector change and approval identity/time/hash metadata.
Clinical facts are unchanged. Generation: 3 minutes 1.27 seconds. All three
output hashes independently match the receipt. Production review assessments
remain not_run, as agreed.

Reviewed all 19 Protocol pages, all 6 ICF pages and XML against approved facts.
All 43 native TOC references match rendered headings. The Advarra opening table
is populated, retains field labels and lists all three site addresses. All
three coordinators and their business/office phones, emails and mailing
addresses appear in ICF contacts. Signature blocks fit; Protocol opening
borders, intact AE contact table and repeated assessment-matrix headers hold.

The same consenting 90-person ambispective cohort is preserved, with historical
records accessed only after consent/authorization and 90-day prospective
follow-up. The telephone visit has no vision test or saliva. Day 0 mandatory
saliva, targeted research genotyping, specimen destruction deadlines, no
individual genetic/incidental results return, no banking/future use, coded
data retention, finite authorization, withdrawal and payments remain accurate.
XML retains observational/Other timing, all three sites and lead investigator
roles, all six outcomes and source dates; dedicated specimen fields remain
empty while detailed narrative preserves their facts, as in Run 3. No registry
import or independent legal sufficiency validation was performed.

No material finding preventing progression under the agreed source/template
review criteria. Minor items retained without fixes: repeated enrollment target,
Protocol prose about template-managed fields, overall-coordinator-only AE table,
and sparse final pages. The Sterling-specific GINA boilerplate is not carried
into Advarra by the current family-scoped contract; the Advarra text retains
genetic privacy and biological-relative risks. Retained Sterling source prose
does not override the selected Advarra template. No production code, approved
source facts or supplied outputs were changed.

Run 5 passes Codex review; owner acceptance pending. Both template-switch rows
now pass review. Next: prepare and approve a new prospective clinical input for
Run 6 using Sterling, then generate at candidate `8d48c22` and retain an entire
run ZIP. Runs 6–8 inputs remain to be created; the eight-run plan is not complete.


### Run 6 fresh input prepared — 16 October 2026

Input: `inputs/BREAK-27-05-study-input.txt`; matching owner-transfer copy:
`/Users/juanpabloleoni/Downloads/BREAK-27-05-study-input.txt`.
Expected Hermes path after transfer: `/opt/data/BREAK-27-05-study-input.txt`.
Transfer, intake and Source of Truth approval have not been performed here.
Use candidate `8d48c22` and Sterling. This is a prospective randomized behavioral
study with two parallel groups, assessor-only masking, mixed clinic/telephone
contacts and daily home diaries. Review negative symptom change as improvement,
different scale directions, intervention-only adherence with missing/zero
denominators, group assignment regardless of adherence, reimbursement without
compensation, limited sponsor identification access, finite authorization,
and requested registry disclosure without invented registration or IRB approval.
This adds interventional coverage while remaining within the prospective
Protocol template. No production changes are required to prepare this input.
Runs 7–8 inputs remain to be created.


### Run 6 BREAK review — 16 October 2026

Archive: `/Users/juanpabloleoni/Downloads/BREAK-27-05-entire-run.zip`.
Archive SHA-256: `5c7c22106a59f0c4ab1abd44eb9ac1445e065d0b158805a4e751881005ff2660`. Input bytes match the retained Run 6 input.
All five drafting requests use prompt v30 / contract v2.49 and their six
implementation hashes match local `8d48c22`; no standalone installed-commit
receipt is included. Approved revision: `r-3a7da16f6dea`; source digest:
`55ad980ca1dd925a9c51d30c30667e55a2e771db1dfa792e6d1f50946b697bff`.
Recorded elapsed generation time: 2 minutes 50.55 seconds. All three output
hashes independently match the completion receipt. No production review ran.

Reviewed all 18 Protocol pages, all 8 ICF pages and XML. All 43 native TOC
references match. No significant clipping, overlap, table splitting or signature
layout defect found. Protocol AE contact table remains intact on page 14.
Sterling merge fields remain deliberately retained; both site contacts appear.

One material finding prevents Run 6 acceptance: the ICF omits the explicitly
requested ClinicalTrials.gov participant disclosure. Original input requests
it, approved source retains the requirement in `ethics.registry_disclosure`
and `regulatory.clinicaltrials_consent_disclosure_applies`, and Protocol page 14
states it will be included. The accepted privacy draft and final ICF omit it.
The current Sterling clause contract and renderer instead require boolean true
at `regulatory.prs.participant_registry_disclosure`; that path is absent from
this approved source. `_preserve_sterling_registry_statement` removes matching
registry statements and returns without restoring one when that flag is absent.
This is a source-normalization/conditional-clause integration defect, not a
missing-input issue or a reason to expand general clinical drafting prose.
A general fix should preserve explicit source authorization through intake
and clause assembly, respect explicit negative/conflicting facts, and avoid
inferring registration requirements solely from study type or XML requests.
Preserve the agreed template wording without inventing an NCT ID or approval;
review any legal-necessity assertion against the supplied sponsor requirement.

Other coverage holds: randomization after baseline/consent with concealed
allocation and site/block rules, assessor-only masking without automatic breach
exclusions, 72 people in two groups, four contacts with no phone acuity or
satisfaction, separate Days 1–56 diaries without invented daily symptoms,
negative symptom change as improvement, intervention-only adherence and correct
missing/zero-denominator handling, assigned-group analysis, reimbursement-only
limits, sponsor identifying reimbursement access versus coded analysis access,
finite authorization and seven-year retention. XML has interventional/randomized
parallel/supportive-care design, single outcomes-assessor masking, Experimental
and No Intervention arms, intervention link, one primary and three secondary
outcomes, both sites/roles and source dates. No registry import was tested.

Minor repetition, broad key-information wording and sparse continuation pages
are not additional progression gates. No production code, approved source or
supplied outputs changed in this review. Run 6 remains unaccepted until the
general disclosure fix is tested and BREAK rerun; Runs 7–8 remain pending.


### Run 6 general disclosure fix — 16 October 2026

Candidate contract: `clinical-documents-v2.50-registry-disclosure-mapping`.
Intake now records the explicit consent-disclosure decision in the canonical
review field and resolves disagreement before approval. The shared resolver
supports both existing structured aliases, including BREAK’s annotated Yes;
rendering reads those approved declarations without modifying the source.
Explicit No and unspecified decisions do not add a disclosure or infer one from
trial classification, registration plans or an XML request.

Local replay used BREAK’s saved approved source and drafting responses without
new model calls. The Sterling ICF now contains exactly one copy of the reviewed
disclosure. An empty chapter-sequence field carried by the authority paragraph
was removed from the inserted copy to prevent a stray visible number after
native office refresh. The ICF remains eight pages: pages 1–6 and 8 are pixel
identical to the supplied run’s render; page 7 was visually inspected and the
disclosure and contacts fit. Original n8n prompts and production generation
stages remain unchanged. Twenty focused tests passed across `test_registry_disclosure_mapping.py` and
`test_generation_only.py`; Python compilation and `git diff --check` also passed.
Tests cover source preparation, positive,
negative, absent, ambiguous and conflicting decisions, exact wording, clean
field formatting, and approved-source immutability.

This local replay does not accept a new Hermes run. Rerun BREAK using the same
approved Source of Truth, retain the entire run ZIP and review it before moving
to Runs 7–8.
