# Duration and supplied-reference fixes

Baseline: `0c00c1cc7d1c8188bc56aa2796998b1bd3b7a14c`.

## Confirmed defects

The successful Sep26 run 03 rejected its correct second ICF Duration draft because lexical coverage treated 6M/3M/1M and enrollment/analysis as literal anchors. Its final draft added unnecessary shorthand to pass. The Protocol also omitted three bibliography entries embedded in the approved background because rendering only read the separate top-level references field.

## Implementation

Duration coverage now compares recognized enrollment/recruitment, follow-up, and analysis phrases with their numbers and units. It accepts spelled-out month units, shorthand, number words, and coordinated phase lists. Wrong values, units, phase assignments, missing phases, and conflicting repeated phase values remain rejected. This handling is confined to ICF Duration and study.timeline; unknown timeline shapes retain the existing grounding fallback. It is not a universal natural-language timeline interpreter.

Protocol rendering preserves explicit references and recognizable bibliography embedded in approved background, using the existing References section and template authority. It handles reference headings, numbered DOI/PMID entries, journal references with author/year/volume/pages but no identifier, and indented or identifier-led wrapped continuation lines. Duplicate lines are omitted. Numbered clinical facts and unindented prose after a citation are not treated as references. No citations are generated or fetched, and no source approval facts are mutated.

No new gate, deadline, dependency, workflow topology, template resource, or source-limited content change was introduced.

## Verification

Archived request/response replay reproduces the false rejection before the fix. Focused tests cover the replay, alternate wording/units, negative phase/value/unit cases, bibliography preservation, and assembled DOCX structure. A broader focused selection passed 256 tests in 62.84 seconds. After the final bibliography-boundary and contradictory-phase regressions, the new module passed 24 tests. Python compilation and diff whitespace checks passed.

Standards review: no remaining findings; bibliography continuation concern corrected.
Specification review: coordinated wording and identifier-free citations findings corrected; no remaining findings.

As requested, the full suite, live study generation, and local Office rendering were not run. A fresh Hermes run remains necessary to confirm the restored References section's rendered pagination and end-to-end behavior. Existing final content and every-page visual review remain in place; no new release gate is added.
