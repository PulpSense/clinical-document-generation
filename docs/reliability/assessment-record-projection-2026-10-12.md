# Assessment record projection

Issue: #109. Baseline: `4f734cf`.

The uploaded prospective Protocol rendered Table 15.1 as serialized visit records in a one-column supplemental-details table. The reported final AI reviews passed. Their responses and exact approved reference were not supplied, so the remote reviewer's rationale is unknown.

## Reproduction and cause

An approved `procedures.assessments` list containing explicit `visit`, `timing` and `procedures` records produced no matrix rows. `normalized_visit_records` read only the two schedule fields, while `protocol_table_contracts` serialized assessment records into supplemental notes. The same facts in `visit_schedule` rendered correctly. The new regression file initially failed 12 cases, including actual Word assembly for all four prospective/ambispective template combinations.

## Correction

Explicit visit records and activity matrices in assessments and evaluation now share the schedule projection. Single assessment records are also supported. Unassigned prose remains unassigned; different timings and ambiguous contacts stay distinct. Additional record metadata retains its visit label, and represented records are no longer repeated as serialized schedule notes. Approved source objects remain unchanged.

Both independent review requests now explicitly assess readable visit/activity relationships, including code-generated tables. Fact presence alone does not establish table usability. This adds reviewer guidance, not a semantic code veto or a new specialized recovery route.

## Local evidence

- 26 new regression cases cover the shared projection across three study branches, four actual prospective/ambispective Protocol constructions, immutability, unassigned narrative, metadata, alternate fields, matrices, single records and review instructions.
- Main focused selection: 114 passed, 8 deselected. The 8 existing failures were reproduced on the unchanged baseline; they require superseded lexical/timeline code findings.
- Source-routing selection: 50 passed, 12 deselected. Separately, the 12 deselected cases produced the identical six passing/six failing result on baseline and patched code. Failing cases expect superseded specialized semantic/recovery behavior.
- Additional public assembly/schedule selection: 10 passed, 12 failed. The same 12 failures were reproduced on the unchanged baseline. They assert deterministic semantic rejection of removed table notes, contrary to current AI-owned review.
- The real DOCX from the new public assembly test was converted with the bundled office renderer. Its Table 15.1 page visibly contains separate activity and visit columns with correct marks and readable headers.
- `git diff --check` passed. No full suite, live Hermes generation or paid certification ran. Local evidence does not prove future live reviewers will always catch a defect.

The user's existing generated documents and approved inputs were not edited. The next Hermes operation must install the corrected version and perform fresh exact-artifact content and page reviews.
