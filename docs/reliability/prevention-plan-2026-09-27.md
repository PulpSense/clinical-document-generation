# Reliability work and release policy

## Goal and scope

Given complete, approved study inputs, produce template-faithful Protocol/ICF DOCX and applicable PRS XML, with clinically faithful content and Brad's section ownership. Prevent avoidable false rejections and catch regressions before asking Hermes to spend a study run. Keep independent content and every-page review, legal/template text, source approval, immutable deadlines and exact-byte delivery.

This change does not claim every possible input or model response will succeed. Incorrect clinical claims, missing material facts, unverifiable reviewers and genuine environment failures must still stop publication. No paid live corpus, full suite or Mac runtime dependency is introduced.

## Acceptance criteria for this maintenance pass

- Inventory direct finding/block producers and shared evidence/normalization helpers across all six production modules. Record authority, false-rejection risk, duplicate-check policy and representative verification by family.
- Protect that inventory from silent changes with a developer-only source fingerprint check. Describe its limitations; it is not proof of every conditional or model judgement.
- Keep one source interpretation for supported visit matrices and typed visits; preserve the approved original, units, labels, quantities and visit assignments. Test markers, key ordering, omitted assessments and wrong quantities.
- Preserve material zero values. They must not disappear through truthiness, and spelled numeric equivalents must remain valid.
- Have the same evidence evaluator return both its verdict and actionable source diagnostics; use it in drafting and rendered ICF findings. Semantic hypothesis checks must remain provisional until full independent review.
- Provide one explicit local release command covering historical failures, earlier successful fixtures, Brad/template rules, PRS relationships, approval/reviewer safeguards and worker readiness. It must not run a live study/corpus, sign a release or become a client activation preflight.
- Review the diff, run only the focused selection, commit and push.

## Audit findings

The source-normalization boundary already exists: `source_contract` canonicalizes declared aliases before Source-of-Truth approval. `assessment_matrix` and `normalized_visit_records` interpret supported schedules; `protocol_table_contracts` supplies table relationships. `section_evidence_value` projects section-owned clinical evidence from that source, and both drafting and Sterling rendering now consume it. Adding another normalized source store would create a second authority and additional approval/hash migration risk. This pass preserves those boundaries and tests their equivalence across variations.

The remaining general overlap checker is a heuristic. It requires source numbers and a proportion of source words; it does not prove dose-to-visit relationships, distinguish all negations, or understand every participant-facing paraphrase. Hypothesis meaning is already assigned explicitly to independent review. Other source omissions and meaning remain subject to the complete source inventory and mandatory source-supported/no-invention review. This pass does not waive those checks or broaden semantic deferral without evidence.

Two concrete issues addressed:

1. `_leaf_texts` discarded numeric `0`/`0.0` through `value or ''`, so unsupported prose could pass an ostensibly numeric evidence check. Only `None` is now absent; explicit booleans retain yes/no polarity rather than requiring technical Boolean spelling in prose. Numeric word aliases participate in the existing anchor screen too, allowing a scalar zero to be expressed as “zero.”
2. A generic “material facts are not observable” rejection hid the actual reason and encouraged repeat drafts with unchanged evidence. The shared evaluator now retains the failed source excerpt, missing numbers and observed/required anchor counts. Generic drafting coverage failures and Sterling rendered failures carry these diagnostics into the existing retry request. Phase-bound timelines retain their own validation mode, and semantic hypotheses are labelled independent-review obligations, never release acceptance.

The audit inventory covers 101 functions: direct producers plus shared evidence and normalization helpers, including nested conditions in each function fingerprint. Its family policies are in `blocking-checks.json`. It catches changed/new/deleted indexed checks before release. It does not enumerate every possible execution path, parse dynamically generated external errors, certify the environment, or substitute for reading a changed check. Whole-package implementation/resource fingerprints remain the runtime integrity authority.

## Local variation bank

The new bank exercises 72 combinations of positive/negative schedule encodings and forward/reversed mapping key order. Each checks both narrative projections and normalized activity assignments, preserves original source bytes in memory, rejects a wrong quantity and rejects an omitted assessment. Five numeric-word variants additionally cover correct and wrong quantities. Existing matrix-versus-typed tests, custom headers, unknown cells and structural-ID tests cover representation boundaries.

Historical fixtures remain in the focused command: earlier successful complete candidates, real blocked drafts, background qualification, purpose/hypothesis fidelity, duration references, template comments, Brad editorial rules and PRS enrollment/cohort mapping. Independent review authentication/scope and worker-profile tests are retained. No model drafts are generated by this check.

## Developer release command

From the repository, using its development Python with test dependencies:

```sh
python3.11 tests/offline_reliability_gate.py --report .scratch/reliability-audit/offline-check.json
```

`--list` shows the explicit selection. The command runs 21 selected test files and checks the audit inventory; it is not the full suite. It records its exact command, output, elapsed time and result. The developer timeout is separate from generation deadlines. A failed check blocks this developer's release decision, not an installed client's generation.

For each change to an indexed check: read the changed protection, determine whether its authority and owner changed, add a valid variation and an incorrect-output counterexample at the public seam, then update its reviewed fingerprint. Never refresh hashes merely to make a failure disappear. The two-axis code review checks that judgement.

Ordinary Hermes activation continues to verify package/runtime integrity and render smoke only. Do not run this bank, the structural layout corpus, live certification corpus or signing as an extra client installation requirement. Do not increase generation timeouts or retry counts to mask repeated conditions.

## What remains to validate on Hermes

A fresh run on Brad's actual worker verifies installed authentication, runtime/font/render capability and real model drafting/reviewer behaviour. Local recorded fixtures cannot prove those. After that run, inspect final document content and page images plus any retry diagnostics. Further source forms need a boundary case and negative counterexample before declaring them supported; the approved source must never be rewritten silently.

## Verification record

The final focused command passed 493 tests in 57.97 seconds; audit findings were empty. The initial run passed 491 tests before the two scalar-polarity follow-up cases were added. Standards review found no material violations. Spec review requested refreshing the final reviewed helper fingerprint and clarifying that PRS mapping and deterministic validation share helpers; both are addressed before release. No full suite, paid model call, live study or certification corpus was run.
