# Hypothesis fidelity repair after bilateral run __04

## Reproduction

The September 27 __04 run used commit 4d40df2 and stopped after 1,028.447 seconds. Six PURPOSE drafts and one candidate render were preserved. The final three drafting responses were rejected with the same study.hypothesis source-evidence finding.

Local replay reproduced every rejection. The source's incidental phrase 'the two cohorts' introduced a numeric requirement into a generic word-overlap check. Accurate participant-facing drafts named the two lens groups and said 'between groups'; inserting 'two' made the same content pass. Earlier rendered checks also rejected accurate prose that explained the study aim without the literal purpose/objective words. A further regression demonstrated that 'Researchers anticipate' failed where 'Researchers expect' passed.

The same generic grounding function accepted isolated changes from 'may differ' to 'will differ' and removal of the superiority negation. These probes assess that component only, not the full workflow. They show why word overlap is not proof of narrative fidelity.

## Implementation

A shared semantic evidence contract declares the exact approved study.hypothesis excerpt and mandatory requirements: material expectations, outcome-to-group relationships, uncertainty, negation and study limitations. Draft requests carry these obligations, respecting section concept ownership. Introduction does not receive hypothesis-owner obligations; concise summaries remain concise.

Drafting and rendered Sterling validation use the same provisional source-path policy. Hypothesis meaning is assessed by the existing independent package content reviewer under source_supported and no_invention. This adds no model call or response-format requirement. Review requests and persisted evidence bind the shared obligations to their existing authenticated scope. Reported missing material hypothesis facts remain blocking and cannot be treated as ordinary substantive warnings.

Conservative early guards reject recognizable direct stronger-than-source outcome comparisons and reversal of the supplied superiority limitation. Repair feedback supplies the exact approved excerpt. These guards do not claim complete semantic understanding: unrelated, uncertain and methodological comparisons defer to independent review. The uncertainty guard requires a direct group/cohort comparison and source outcome anchors, and excludes methodological subjects.

Sterling PURPOSE no longer requires literal purpose/objective or hypothesis/expectation vocabulary. Its aim and hypothesis meaning are mandatory reviewer obligations. The main-outcome label and existing 140-word rendered limit remain enforced. Mandatory template language and other Sterling clauses remain governed by their previous rules.

Concrete endpoint, population, procedures, PRS enrollment and cohort-association paths retain their deterministic checks. Required citations, source approval, implementation/resource hashes, deadlines, retry limits, visual review and exact-byte delivery are unchanged.

## Verification and limits

The tests replay all six archived PURPOSE drafts; verify fresh draft and existing review request obligations; reject a changed 66 cm endpoint distance; reject definite differences and superiority-limit reversal; accept equivalent expectation wording; preserve rejection of reported missing facts during review ingestion; and cover unrelated or uncertain comparisons. A controlled in-memory ICF exercises the complete Sterling clause checker without modifying archived candidate files or producing client outputs.

- Final hypothesis-fidelity module: 16 tests passed.
- Focused regression selection including prior background, visit, bilateral, Sterling, duration, Brad editorial, contracts and handoff checks: 280 passed before the final expectation-keyword contract change.
- After that isolated resource change, affected hypothesis, Sterling, editorial and contract checks: 128 passed.
- Standards and spec reviews cleared; both review findings about the early uncertainty guard were reproduced and resolved before commit.

No full suite, paid live corpus or live study generation ran. A fresh Hermes run must still verify generation, rendering and independent review together. This repair establishes a shared narrative validation policy for study.hypothesis; it does not replace all remaining narrative checks or guarantee completion for every future input.
