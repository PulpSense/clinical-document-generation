# Bounded review scheduler validation — 2026-10-13

Issue: [#113](https://github.com/PulpSense/clinical-document-generation/issues/113).
Review baseline: `4b10e1a552582dcf9ecba45d65212d694f6fb4c3`.

## Failure and change

The blocked operation preserved partial content judgments but repeatedly assigned almost the entire unfinished package to replacement reviewers. A fixed package-wide replacement cap ended the operation before the missing review scope could complete. A substantive XML finding saved in partial progress never reached native repair.

Desktop now schedules at most three sections or two cross-document checks per unit, with at most three units in a wave. Productive completed judgments survive failed workers; only unfinished scope is assigned again. Consecutive no-progress work is bounded, and stalled section groups shrink to single-section assignments. The original persisted operation deadline applies throughout, including parent-process resume. Each wave receives a bounded budget with remaining time reserved for completion/delivery.

Readable native text includes paragraph/table locations, headers, footers, textboxes, and XML values. Full native inspection and the canonical approved source remain available as read-only fallback. No approved clinical fact is truncated. Unit request/response identities, evidence hashes, reviewer identities and aggregate judgments are authenticated before package approval.

Authenticated partial substantive findings reach existing source-preserving native repair before unrelated review completes. Changed native bytes require fresh review. Harmless independently classified editorial findings do not stop the queue or add client warnings. Prior localized, cross-document and unknown-location concerns receive a responsible reviewer and require explicit independent reassessment.

## Evidence

Public verification-request and Desktop lifecycle tests cover Prospective/Advarra, Prospective/Sterling, Ambispective/Advarra, Ambispective/Sterling, and Retrospective/Protocol-only. They exercise one-section-per-invocation capacity, partial defect → native repair → fresh complete review, checkpoint-only worker loss, missing/malformed responses, no-progress termination, slow workers under the original deadline, concurrent visual fallback, and interrupted-parent resume. Negative cases invalidate approval after unit response, parent assessment, native bytes or readable evidence changes.

The final review found and fixed two general defects: harmless findings prematurely stopped scheduling, and cross-document/unlocalized prior concerns could disappear from child scope. Regressions first reproduced these failures, then passed after the fixes. The existing unresolved-package test adapter also assumed every request included the introduction; it now injects its unchanged substantive finding only into assigned introduction units, retaining all five-family review-only assertions. Parent interruption also exposed premature interpretation of a partial parent response; queue resume now occurs before that interpretation.

The blocked archive was replayed for payload construction only. Its 62 sections and six cross-document checks became 24 initial bounded units. Readable native evidence was 93,807 bytes versus 617,002 bytes of raw native inspection (about 85% smaller). Individual unit request JSON ranged from 35,498 to 208,133 bytes; source and template evidence remain available rather than truncated. This replay does not establish clinical correctness or live completion speed.

Final validation on the frozen production implementation:

- `python tests/offline_reliability_gate.py --timeout 900 --report /tmp/review-scheduler-final-gate-rerun.json`: **150 passed, 1 skipped** in 507.50 seconds. The skip is the Hermes Linux profile office-runtime test on macOS. This is the exact focused command now wired into CI.
- `pytest -q tests/test_desktop_delivery.py tests/test_runtime_efficiency.py tests/test_verification_request_ledger.py`: **174 passed** in 96.23 seconds.
- The five previously failing unresolved-package adapter cases passed independently after the test-only scope correction, then passed again inside the clean focused gate.
- Python compilation and `git diff --check`: passed.

Total across the two disjoint final focused selections: **324 passed, 1 skipped**. No incomplete or failed run is counted as passing. Four suggested Hermes installation files collect 73 tests: scheduler, content-review recovery, general document repair and reviewer transport.

Independent Standards and Spec re-review: no remaining material findings.

## Limits

These are controlled local engineering checks, not live Hermes model certification. No full suite, acceptance corpus, paid certification or live study generation was run. Linux runtime dependencies were unchanged. A provider outage, unresolved substantive defect or exhausted operation deadline can still require a complete review-only package; incomplete review never becomes client-ready approval.
