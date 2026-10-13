# Independent content review transport recovery (#112)

Baseline: da86a65676ce535b1e67b8615cbed701b23a43d7.

The supplied blocked-run diagnostic captured a content reviewer losing inspection evidence during context compaction and a read_file instruction value truncated even when requesting its single line. The archived value was complete (4,520 characters); the worker had no remaining nested delegation budget. Visual review had passed. This work changes shared review transport/orchestration, not the study facts or a particular passage.

## Behavior

Canonical content requests now bind a reading index and lossless packets for the entire request evidence and native XML inspection views. Strings are split into short chunks, with byte-counted packets of at most approximately 10 KB. Concatenating text_chunks in order recovers the original JSON. The ordinary request/ledger authentication also checks packet/index hashes and original native bytes. The worker prompt supplies exact response identity directly and directs the reviewer to the bounded reading route before a large request read.

Independent reviewers may save completed section and cross-document judgments in the declared audit checkpoint file, while source and candidate documents remain read-only. The workflow snapshots independently bound progress with producer identity and preserves original response evidence. Foreign/malformed progress is not reusable. Complete progress is assembled only from explicit judgments; all existing final completeness, independence, prior-concern and publication checks remain. Substantive blocked assessments and findings survive a replacement's generic pass and continue to ordinary native document repair. A tooling error is never a clinical pass.

Missing, partial or tooling-blocked content review triggers up to two fresh replacement attempts, each within the original persisted operation deadline. Initial content work has at most six minutes and half the remaining operation time; replacement waves likewise reserve half remaining time. Production replacement uses fresh worker processes, avoiding the failed reviewer's exhausted nested delegation budget. Content recovery starts as soon as that worker ends, concurrently with slow visual fallback. Shared operation-state saves and callback counters are serialized; visual completion evidence is preserved. Authentication failures do not receive blind replacement attempts. Exhausted recovery retains a complete review-only package when available, without restarting the operation or regenerating sound documents.

## Validation

Public verification-request and Desktop operation tests cover all five study/template families, long Unicode/quoted/multiline source values, saved progress after context loss, missing/partial/foreign/malformed worker responses, one alternate replacement attempt, exhausted attempts, unchanged source, changed native/index/packet/checkpoint evidence, preserved substantive findings, ambiguous bare blocked responses, expired deadlines and concurrent visual fallback. Controlled local adapters are not live clinical or runtime certification.

The concurrency test failed before recovery was moved into the content worker wave and passed afterward. A second negative regression caught a generic complete replacement pass erasing a previously saved substantive finding; it failed before the merge correction and passed afterward. Review-request ledger checks passed separately (45 tests). Standards and Spec re-reviews reported zero remaining material findings after correcting the concurrency gap.

A read-transport replay using the supplied blocked run’s actual approved reference and three native review copies recovered the complete source, all native inspection JSON and the 4,520-character instruction losslessly: 97 packets across four views, maximum 9,994 bytes per packet and 90 characters per line. This verifies transport reconstruction, not clinical approval.

Final focused sweep: **225 passed in 292.69 seconds**, covering:

- tests/test_content_review_recovery.py (25 cases)
- tests/test_runtime_efficiency.py
- tests/test_reviewer_transport.py
- tests/test_general_document_repair.py
- tests/test_desktop_delivery.py
- tests/test_verification_request_ledger.py

The installation-sized subset (the first four files) contains 85 of these passing tests. Python compilation and git diff whitespace checks passed. Initial exploratory focused execution had three failures: an obsolete 12-minute content-budget expectation was updated to six minutes, the final-response publication guard was restored, and a repair lifecycle case passed when rerun with production authority files held stable. The complete final sweep ran with those production files unchanged and passed.

No full suite, acceptance corpus, paid certification or live Hermes run was performed. Linux dependencies and runtime wheels were unchanged. Staged and active rendering smokes must run on the installation host. No document-generation or rendering changes require a separate visual layout claim for this patch.
