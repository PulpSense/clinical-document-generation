# Publish minor editorial findings and preserve accepted timeline repairs

## Cause and change

The archived PureSee/Odyssey run identified nonmaterial repetition in Protocol §18.5 and a duplicate exit-form row in Table 15.1. The repetition finding supplied valid section ownership and explicit false harm flags, but omitted optional `code` and `disposition` labels. Validation consequently routed it to drafting instead of retaining a warning. Separately, rendering always replaced the accepted §18.5 repair with the raw source timeline, restoring the visit narration that review had flagged.

Structured `concept_repetition` now uses the governed ownership pair, target, evidence, and five explicit harm flags. Previously valid four-flag structured warnings remain compatible when their optional safety flag is absent; an affirmative safety flag still requires correction. `editorial_relevance` likewise distinguishes harmless wording in a safety-related section from an actual missing safeguard or unsupported claim. Material, uncertain, source-fidelity, malformed, mistargeted, and stale findings retain their protected routes. Reviewer instructions request the same five flags that current validation consumes.

Rendering preserves accepted timeline-only prose when no separate study-completion criterion is supplied. The source timeline remains the fallback for absent prose or a study-completion/closeout assertion. Enrollment completion and the explicit statement that no separate completion criterion is specified do not erase a faithful repair. Supplied completion criteria remain source-bound and independently reviewed.

Normal publication adds document locations to delivery cautions separately from the immutable reviewed quality record. Minor findings do not cause review-only names or drafting retries. Unresolved material findings still use the existing review-copy and diagnostic paths.

## Scope

The shared review/publication policy applies to all five study/template families. §18.5 repair persistence applies to the four Prospective/Ambispective families that contain that section. No templates, approved format baselines, PRS mapping, clinical inputs, production dependencies, or runtime deadlines changed.

Neighboring renderer rules were audited. The neutral Section 15 table introduction is intentionally code-owned. Retrospective withdrawal, reminder-call, and ICF visit-window rules append source details rather than replace the accepted body. Their safeguards remain; harmless resulting repetition can be reported through the warning policy.

## Verification

- New seam regressions and unchanged repetition tests: 99 passed (62 new cases, 37 existing). Coverage includes authenticated minor findings, normal atomic publication and location notes for every family, legacy-response compatibility, material/stale/ownership guards, accurate timeline repairs, and unsupported closeout assertions.
- Final focused offline gate: 720 passed, one Linux-only test skipped on Darwin; zero audit findings.
- Actual archived failed-run replay: complete quality report passed with the two original editorial warnings and no blocking finding. This is an evidence replay, not a fabricated fresh review.
- Five-family deterministic format conformance: structural gate and every approved output baseline passed in the local test renderer fixture. This does not confer live clinical certification.
- Before/after DOCX scaffold construction: all nine normalized format signatures matched the previous commit.
- Static compilation and whitespace checks passed. Independent standards/spec review reported no remaining material finding after correcting both discovered overwrite edge cases.

The broader suite was stopped after 33m23s with 981 passed, nine failed, and one skipped; it is incomplete and is not a clean suite pass. Eight failures reproduced on unchanged commit `50a51433950f1c01fdf2020a6129d5254ce90a77`. They concern an existing run-directory instruction assertion, a Section 15 wording assertion, two drafting-policy expectations, and four layout/body-design expectations. The ninth comes from an older synthetic visual-repair responder: its preserved response is rejected identically by the previous and current validators for a missing revision binding, and its corpus retries report missing governed visual repair routing. These unrelated tests and protected production bindings were left unchanged. The final broader-suite result and parent comparisons remain in local implementation evidence.

Before activating on Hermes, verify the exact package and installation rendering, then perform the single final Prospective–Sterling study run against the unchanged previously approved PureSee/Odyssey source. Further live runs of the other families are not required for this bounded change; deterministic family coverage does not guarantee against every future input, provider, or host failure.
