# Background evidence scope fix

## Cause

The blocked bilateral-study run supplied a background containing clinical evidence,
rationale, a study objective, design details, and references. ICF Background was
instructed to avoid repeating the endpoint, but its source-coverage check required
the objective's six-month number. All three archived drafts failed that check.
Adding a dangling `6` made the old check pass, demonstrating inconsistent section
ownership rather than missing clinical input.

## Change

Protocol Introduction and ICF Background now share a deterministic projection of
background evidence between drafting requests and validation. Explicit objective
and planned-design sentences are excluded from their coverage requirements.
Clinical context, prior-study numbers, qualifications, and rationale are retained,
including facts in the same paragraph as an objective. The approved source is
unchanged and remains available to Purpose and Design.

The source phrase “two cohorts/groups” can be covered by “both groups/cohorts.”
This equivalence cannot supply another quantity, such as a two-week duration, or
cover a three-group design. Existing delivery, clinical review, template, and
deadline protections remain in place.

## Verification

All three archived Background drafts pass with the current section contract.
Negative regressions retain required prior-trial numbers and reject omitted
durations or changed cohort counts. Spec and Standards reviews found no remaining
material issues after two initial review findings were corrected.

The focused regression selection covers section scope, successful-run polish,
earlier Background failures, run reliability, contracts, handoff quality, Sterling
template comments, Brad editorial feedback, duration/reference preservation, and
architecture. No full suite, paid live corpus, or study generation was run locally.
The final stable selection passed all 276 tests; Python compilation and
`git diff --check` also passed.

## Remaining verification

Hermes must perform a fresh run with the approved bilateral-study input to verify
end-to-end generation. Passing archived drafting checks does not establish that
every later stage will pass. The broader section-ownership and input-variation
reliability audit is separate follow-up work.
