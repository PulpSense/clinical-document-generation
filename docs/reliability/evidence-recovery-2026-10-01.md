# Evidence review and table recovery maintenance

## Reproduced causes

The preserved a51c892 Prospective Sterling run contained two representations of
the same schedule: activity-matrix headers and qualified narrative visit records.
Exact-name matching produced five stages instead of screening, surgery per eye,
and Month 3 follow-up. That widened both generated tables and contributed to an
unreadable header. The layout blocker also concealed a companion table finding.

Prose evidence matching used inconsistent lexical dispositions across drafting,
rendered Protocol content, and Sterling clause checks. A code-owned table finding
could also schedule a prose rewrite because the table shares its section ID.

## Maintenance scope

- Reconcile only uniquely matching matrix headers and narrative visits. Preserve
  clinical order, quantities, units, signs, timepoints, and approved source bytes.
  Ambiguous contacts and conflicting timings remain separate.
- Treat nonnumeric word-overlap failures as unresolved lexical cautions and expose
  them to the existing independent content review. Missing citations, quantities,
  polarity requirements, explicit contradictions, and exact clause safeguards keep
  their existing blocking treatment.
- Resolve only the exact cautions presented to a passing, authenticated section
  assessment for the current artifact. Retain the decision in quality evidence and
  revalidate it before delivery. This adds no model call and does not turn lexical
  matching into clinical approval.
- Bind table findings to canonical table IDs and owner sections. Reconstruct tables
  from the approved source without invalidating accepted prose. Measure the actual
  rendered section, including tables, when recording progress.
- When a supported content reconstruction affects the same artifact as an
  unsupported visual repair, preserve the visual finding and reconstruct first.
  A fresh full content and every-page review is still mandatory. Unsupported visual
  findings alone, malformed reviewer authority, and unknown repair rules still stop.
- Include companion findings in terminal reports instead of displaying only the
  first layout blocker.

Client templates, PRS XML shape, source approval, final byte binding, deadlines,
and review-copy delivery policy are unchanged. This maintenance does not guarantee
that all future clinical inputs or model outputs will pass review.

## Regression evidence

`test_mixed_visit_representations.py` replays the actual synthetic approved source,
asserts independent expected stages and activity assignments, and rejects ambiguous
contacts, conflicting timepoints, and numeric-symbol collisions.

`test_semantic_evidence_recovery.py` checks all five study/template families,
faithful paraphrases, material omissions, missing citations, stale responses,
and clearance limited to the presented caution.

`test_owner_aware_recovery.py` exercises real DOCX table reconstruction with bound
synthetic reviewer responses. Its placeholder PDF/page bytes exercise authority
and routing only; they are not evidence of visual quality. The separate deterministic
format-conformance check and failed-source rendered replay cover rendering.

Release acceptance requires the focused offline gate and five-family deterministic
format conformance. Hermes must additionally verify its installation renderer and
run one fresh study against the failed run's approved source. Local replay and
synthetic reviewer responses are not live clinical certification.
