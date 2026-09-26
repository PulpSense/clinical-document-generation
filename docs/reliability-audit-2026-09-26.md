# September 26 reliability audit

## Scope and observed failure

The synthetic Sep26 archived run used candidate `dafff9d`. It expired during drafting before candidate DOCX construction or rendering. The background reached attempt 22 and statistical methodology attempt 6. Logs recorded 112 worker exits without a bound response; a manual interruption identified the isolated Hermes profile as logged out. The first successful worker started approximately 663 seconds after the initial worker. The immutable 2,700-second operation deadline included this interruption.

This audit examines the drafting validator, recovery scheduling, production worker startup and delegated visual-review exception paths. It does not certify an unseen input or constitute a complete Linux study run.

## Confirmed defects and changes

| Route | Defect | Correction and protection |
| --- | --- | --- |
| Background grounding | Numbered bibliography and inline reference labels were required in patient prose. | Identify author/year/DOI or PMID bibliography lines and exclude their reference labels from clinical coverage. Preserve full approved source. Negative tests retain real clinical numbers and numbered procedure values. |
| Statistical methods | A combined analysis-plan field made methods repeat population eligibility and Month 3. | Separate explicit population-definition sentences into dataset coverage; retain methods in methodology coverage. Sentences containing statistical methods remain in full scope. |
| Citation metadata | Exact bare approved paths triggered model retries. | Canonicalize only exact approved aliases to `source:` references; keep unknown and wrong-section references rejected. Narrative text is unchanged. |
| Deterministic drafting retry | No-progress guard covered independent reviews only. | Track distinct completed drafting attempts, stop after three consecutive identical conditions, retain the unsatisfied condition. Re-reading one response does not count; changed conditions or an intervening success reset the streak. |
| Worker startup | Dashboard authentication did not establish login in the isolated worker profile. | Read authentication status using the worker interpreter and identical environment before creating the study deadline. No model call or authentication mutation. Record only filtered status, provider and profile. |
| Runtime authentication | Deterministic authentication rejection could be redispatched, including through visual fallback. | Recognize authentication failure after unsuccessful worker exit; stop immediately with an environment diagnosis. Delegated visual catches propagate this failure. |

## Retry and gate audit

- Deterministic drafting failures now have an attempt-based no-progress bound. Independent content reviews retain their separate review-set bound.
- Visual-parent callbacks retain the initial callback and one bounded retry. Authentication failures bypass that retry.
- Other transport failures remain subject to the immutable operation deadline. A missing response alone does not prove authentication failure.
- Rendering, document structure, review authenticity, exact artifact hashes and atomic delivery remain mandatory. This patch does not publish rejected documents, reset expired deadlines or convert substantive findings into passes.
- The historical regression inventory now requires the Sep26 replay alongside prior blocked-run regressions. Replays use the actual synthetic source wording and archived prose; no model generation is needed.
- Integration test fixtures were updated to supply the canonical request ledger, revision binding and governed finding identity already required by production verification. Production authentication was not relaxed.

## Evidence and practical limits

Exact background and methodology response replays pass after these corrections without rewriting their prose. Negative tests reject omitted clinical numbers, stronger trial claims, unknown citations and omitted method numbers. Tests exercise the real retry scheduler and production startup seams, including credential-output filtering and authentication failure during visual delegation.

Verification completed: 223 focused drafting/delivery/blocked-run tests, 75 integration/architecture tests, 8 selected runtime recovery tests, and 9 worker-readiness tests passed (worker tests overlap the focused group). Static Python compilation and whitespace checks passed.

One additional existing runtime test, `test_verifier_transient_remains_retryable_after_three_attempts`, remains failing: its generated visual companion has no rendered artifacts, so canonical recovery inventory rejects it before retry. This is outside the changed drafting path and is retained as an unresolved fixture issue.

The broader local test run also found two document-render acceptance failures: sparse-page expectations and a blocked render. These results are unresolved local rendering evidence, not established Linux failures; no Mac dependency or production layout change is included. The test artifacts from that earlier invocation were no longer available for retrospective diagnosis.

The read-only Hermes authentication probe depends on `hermes_cli.auth.get_auth_status` and `get_active_provider`. Local tests verify routing and filtering; the actual server implementation must be checked in the next ordinary candidate trial. Readiness status does not prove a remote token remains valid; runtime authentication detection handles subsequent rejection.

## Next trial

Keep the active skill unchanged while provisioning this candidate. Use one fresh ordinary manual-review operation with the approved input. Do not run the costly live certification corpus, require production signing, reuse prior drafts/reviews, or reset an expired deadline. Inspect worker readiness before the operation and retain final documents plus stage timings. A successful trial is evidence of this environment and input, not a guarantee of every future study.
