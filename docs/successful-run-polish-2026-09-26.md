# Successful-run polish — 2026-09-26

## Scope and baseline

Baseline: `af1e4991a0fefcadca29fc615a199060c1b89c54`, the release that completed the Sep26 `__02` Hermes run in 27m 26s. The synthetic run's accepted responses and delivered ICF DOCX are retained as regression fixtures. Source-limited costs, confidentiality, and ambiguous source labels remain unchanged.

## Changes

- Accept the exact patient-language equivalent of the source's negative compensation/reimbursement statement. Missing reimbursement and reversed payment still fail.
- Allow the visit schedule citation to cover the assessments alias only when all its material facts remain observable in the prose.
- Give interpretation qualifications to Section 10.3; remove the exact archived qualification from methodology evidence when other methods remain. This is a conservative adjustment, not a general sentence classifier.
- Request shared endpoint methods without unnecessary Study Design cross-references; request timing without enrollment repetition in ICF Duration and payment without a duplicate formal sentence.
- Include the existing Sterling summary and Purpose expectations in the initial drafting request.
- Apply existing Sterling clause checks before requesting independent review. The same final checks remain authoritative.
- Keep separate dispatch logs and associate each worker event with its own files.

No template, renderer, dependency, deadline, certification requirement, or substantive validation criterion changed.

## Verification

**329 focused tests passed in 63.70 seconds.** Python compilation and `git diff --check` also passed.

The tests cover the archived accepted prose, former false rejections, negative clinical-fidelity cases, existing template clauses, early-review scheduling, delivery, worker readiness, architecture, and integration-runner behavior. Standards and specification reviews completed; the worker-event log association finding was corrected and its regression test passed.

The full suite and live study generation were deliberately excluded from this Mac implementation, as instructed. Replays establish compatibility and validator behavior; they do not guarantee the next AI draft's wording or runtime. A fresh ordinary Hermes run should confirm cleaner wording, preserved template layout, source fidelity, and completion without redundant clause-review cycles. No new release gate is introduced.
