# Source-derived construction and localized recovery

Review baseline: `cd1b48e3429b0ab455cdf3c407d498607d42384e`.
This implements the owner's approved construction/recovery fixes following the
Input 01 pilot, under the varied-input reliability work in #89 and #90.

## Approved behavior

- A supported complete input must not depend on extraction producing a
  Word-ready sentence fragment. Bare integer enrollment counts and explicit
  noun phrases must both render coherently. Explicit record units, meaningful
  negatives and group breakdowns remain intact. Scalar display normalization
  must never substitute that number into unrelated measurements.
- Keep renderer provenance for generated display prose, separate from accepted
  narrative drafts, retained template clauses and structured tables/XML.
  A precise independent editorial finding on that prose can request a scoped
  correction from the current model within the same operation and approval.
- Bind corrections to the exact archived candidate, approved source, passage
  and reviewer finding. Persist accepted corrections as authenticated drafting
  evidence; rebuilding must retain them. Preserve structure and protected
  template language. The editor cannot change quantities or satisfy its own
  independent review.
- Measure repair progress at the implicated passage. A privacy edit or package
  churn cannot count as progress on an enrollment sentence. An unresolved
  finding always prevents client-ready delivery.
- Reject ineffective, malformed or quantity-changing corrections; bound the
  display editor to three proposals per stable passage under the original
  Desktop deadline. A syntactically valid proposal that changes clinical meaning
  must fail fresh independent review. Preserve unsuccessful attempts.
  Multiple findings on the same passage share one proposal containing all
  eligible findings; count proposals rather than findings. Corrupt archived
  provenance returns an integrity failure instead of interrupting ingestion.
- After correction, rerender and complete fresh package-wide content and
  every-document, every-page reviews. Preserve atomic exact-byte delivery.
- Cover all three branches and both ICF families using public generation,
  rendering and recovery boundaries, varied source representations, and injected
  construction/reviewer defects. Controlled reviewers and office adapters prove
  mechanics, not clinical correctness, visual quality or release reliability.

## Implementation boundaries

The display editor covers positively identified source-derived template prose
and the computed study descriptor. Existing section drafting still owns clinical
narrative corrections; deterministic reconstruction owns tables and PRS XML.
Arbitrary shell text, legal clauses, signatures and headings are outside the
display editor's authority. Unknown or stale provenance fails closed rather than
granting broad document editing rights. Additional computed display destinations
must register source paths and retain the same constraints.

No client input or diagnostics are committed. Linux dependencies, installation
smokes, source approval, the 45-minute deadline and final review requirements
are preserved. Full-suite, live paid generation, installation and certification
are outside this implementation request. The next evidence is the varied Linux
pilot; local passes alone cannot establish reliability for every possible input.

## Verification record

Python 3.11 focused selections completed with 105 passes and one Linux-only
skip. They comprise:

- `test_construction_reliability.py`: all 29 cases covered by the completed
  `bare_approved`, `generated_display`, and
  `native_template or localized_repair or unrelated` selections. Coverage
  includes integer/text counts, explicit units and groups, all five document
  families, persistent corrections, multiple findings on one passage, rejected
  proposals, changed meaning, authenticated records and damaged archives.
- `test_shared_output_projection.py`, `test_owner_aware_recovery.py`,
  `test_reviewer_transport.py`, and `test_general_delivery_reliability.py`:
  66 passes with the latter's `independent_clinical_inputs`, `real_omission`,
  `independent_review_recovery_tracks`, and `ineffective_or_cycling` selections
  excluded. Those longer selections were not run for this change.
- `test_offline_reliability_gate.py`: 10 passes, one Linux-only skip. The
  changed and newly inventoried authority helpers have paired behavioral
  evidence. The gate's broader release-check command was not run.

One earlier consolidated construction-file invocation was interrupted when
review findings required changes; it is not counted as a passing invocation.
The completed selections above cover the final cases. Python compilation and
`git diff --check` passed. No full suite, installation smoke, acceptance corpus,
paid certification or live Hermes generation was run.

## Code review

The Standards review found an archive-indexing exception; the Spec review found
competing edits when several findings named one paragraph. Both were reproduced
through failing regressions and corrected. Follow-up reviews found no remaining
actionable defects. The Spec reviewer independently replayed its original
two-finding generation reproduction successfully after the correction.

Standards retains one advisory judgment: the provenance dictionaries could
become a validated record type if more display destinations are added. Current
dictionaries follow repository conventions, so no refactor is required here.
Spec has no outstanding findings within the approved implementation scope.
