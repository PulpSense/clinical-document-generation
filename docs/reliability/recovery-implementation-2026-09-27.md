# Repairable findings and code-owned content

## Accepted scope

Fix the bilateral run 06 and the general failure mechanisms it exposed. Use the existing independent AI content reviewer for meaning, shared code for computed facts and native templates, and explicit nonmaterial editorial warnings. Preserve all source approval, reviewer authenticity, exact-artifact review, deadline, legal/template and clinical safeguards. No full suite, paid study/certification corpus, extra reviewer calls or Mac dependencies.

## Acceptance criteria and seams

The agreed seams are source contracts/render fields, actual DOCX construction, authenticated review ingestion, measured recovery/reconstruction and final publication with recorded test reviews.

1. Matrix and typed visit sources feed the same canonical visit interpretation everywhere. Protocol synopsis follow-up excludes enrollment/analysis and preserves an explicit surgery-relative qualifier. Count visits rather than matrix activities. Clinical source remains unchanged.
2. Computed synopsis/table facts are available at source validation before drafting. Audit the actual rendered synopsis before dispatching independent review, and again in deterministic final content checks. No new client installation gate.
3. Explicitly nonmaterial editorial findings become retained warnings only with exact negative material/safety/contradiction/usability flags and passage/action evidence. Missing/true flags, factual/no-invention checks and safeguard targets remain blocking.
4. Code-owned Protocol and retained ICF sections are measured from rendered content when they have no accepted AI draft. A reconstructed target must actually change, and an unrelated later passage must not satisfy progress. Fresh full review is still required; a byte change is not clinical acceptance.
5. Local tests reproduce the actual run source and reviewer finding, reconstruct an incorrect synopsis through the recovery adapter, reject an unrelated change, and exercise complete recorded review and atomic publication with an editorial warning. Expand the focused release selection with these regressions; run two-axis review and push.

## Reproduction and findings

From the approved source in run 06, `render_fields(...)["AI_duration"]` returned `Enrollment: 8 months; follow-up: 6 months after second-eye surgery; data analysis: 2 months.` The actual activity matrix has ten activity rows and five canonical visits. `_protocol_followup_summary` selected raw rows as visits, found no timing/name, and returned the entire timeline. `totalVisits` independently counted activity rows.

A second failing integration test reconstructed the corrected synopsis through `_quality_retry`, but `_complete_pending_recovery_attempts` still reported no progress. Deterministic Protocol target measurements used accepted AI paragraph needles. General Information is code-owned and has no accepted AI draft, so its target identity stayed the hash of an empty list. Code-owned sections must instead be observed at their native document boundaries.

The run's reviewer finding explicitly marked four harm flags false but omitted `material`. The repair fixes the actual passage. The revised editorial-warning policy additionally requires `material: false`; the archived finding is not automatically downgraded from this incomplete severity record. This avoids a broad waiver based on category or wording alone.

## Implementation

`participant_followup_summary` owns participant duration: preserve an explicit follow-up phase, otherwise use canonical visits, never substitute a mixed enrollment/analysis timeline. Rendering and computed-field auditing consume that same policy. Snapshot helpers observe native rendered sections independently of the presence of draft records. Protocol snapshots stop at the next peer heading; retained ICF snapshots use the rendering authority's section headings. Existing progress comparisons still require both changed target and changed candidate; fresh review still assesses correctness.

The computed synopsis audit runs before independent review dispatch and in final deterministic content validation. It checks only an existing governed synopsis destination; missing/duplicated document topology remains the existing structure audit's responsibility. Template files and legal wording are unchanged.

Source validation now exposes computed synopsis/count/table previews before drafting without changing the normalized source or adding an approval/install gate. Unknown counts remain unknown.

A complete local publication replay exposed another ownership mismatch: Protocol rendered fidelity demanded endpoints.other in Statistical Methodology, despite its brief-reference ownership. The endpoint inventory check now belongs to Study Design, where omission still fails; rendered fidelity consumes the same section evidence projection used in drafting instead of raw source values. The source-supported independent review is unchanged.

Warnings retain passage/recommendation evidence and must survive final warning/evidence revalidation. Independent review instructions request explicit severity evidence rather than treating all editorial findings as terminal. Factual, missing required, safety, rights and fixed-template checks keep their existing authority.

## Verification limits

Recorded reviews exercise orchestration, reconstruction, warning retention and publication; they do not demonstrate real model quality or replace genuine every-page inspection. Brad's actual Hermes profile, renderer and fresh independent reviewers still need one fresh approved run. The developer regression selection remains separate from client installation and ordinary generation.

## Review and boundary regressions

Standards and specification reviews exposed two qualifier-loss boundaries: a typed postoperative visit could hide the supplied second-eye timing anchor, and a semicolon/newline inside the follow-up phase could truncate a visit-window qualification. Both public render-field cases failed before correction and passed afterward. Explicit relative timing now wins over a generic visit label; phase extraction stops at a recognized next enrollment/recruitment/analysis phase and retains intervening qualifications. Both final reviews cleared with no remaining material findings.

The earlier Brad synopsis regression expected the final visit label even when an explicit follow-up phase was supplied. Its expectation now follows the documented phase projection; the dedicated typed-visit fallback tests retain coverage of the alternative representation.

## Final validation

- Explicit offline reliability selection: **518 passed in 108.97 seconds** across 22 selected test files. The audit reported no stale/unreviewed blocking-check fingerprints. Command: `python3.11 tests/offline_reliability_gate.py --report .scratch/reliability-audit/recovery-check-final.json`.
- Includes actual failed-source reproduction, correct reconstruction, unrelated-change rejection, conservative warning boundaries, endpoint-owner omission, and one complete recorded-review publication replay.
- Static Python compilation and `git diff --check` passed.
- No full test suite, paid model calls, live certification corpus, production signing, Mac dependency changes or new client activation gate.
