# Visit identifiers and clinical narrative evidence

## Reproduced cause

Run `r-5c57ca737eb2` used release `1b0a7d7` and stopped after 499.551 seconds
at `drafting_validation_stalled`, before construction or rendering. All three
ICF Procedures responses failed the same `procedures.visit_schedule` grounding
condition. Replaying the first response against each source leaf isolated only
`2`, `4`, and `5`: structural `visitNumber` row identifiers. They were not absent
clinical time points, testing distances, or missing clinical inputs.

The approved schedule contains named visits, timing, procedures, and ordinal
identifiers. The generic scalar-leaf validator incorrectly required every row
identifier in patient-facing prose. Changing the prose's organization did not
resolve that requirement, hence the three distinct failed attempts.

## Repair

The shared section-evidence projection excludes only `visitNumber` and
`visit_number` keys from typed `procedures.visit_schedule` and
`procedures.visit_schedule_table` records. Drafting payloads and validation use
the same projection. Names, timing, procedures, other fields, and their numeric
values remain clinical evidence. A number in the actual visit name, such as
`Visit 9`, remains required evidence.

The approved source is unchanged, and deterministic structured tables retain
the supplied visit numbering. The contract version is advanced. No input,
template, deadline, approval, recovery-stop, rendering, or delivery rules changed.

## Verification

The three archived request/response pairs replay successfully. Focused negative
checks still reject missing clinical distances and explicitly named visit numbers.
Changing only ordinal identifiers does not change the narrative verdict; the
source values and structured table numbering are preserved. Both Spec and
Standards reviews cleared. All 304 focused checks passed, including the 13 new
visit-identifier checks and earlier Background, PRS, completion, successful-run,
template, handoff, and architecture regressions. Python compilation and
`git diff --check` passed.

No full test suite or live study generation was run. This prevents the reproduced
metadata rejection across typed schedule inputs; it does not certify every future
input or eliminate the need for fresh complete content and visual review on Hermes.
The broader audit of evidence ownership and validation across input variations
remains separate work.
