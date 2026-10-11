# Spec 103 focused evidence and owner-run Linux campaign

The local checks establish lifecycle behavior with controlled drafting, reviewing and rendering adapters. They do not establish clinical judgment, real page quality, installed Linux compatibility or a sub-25-minute live runtime. Those remain unproven until the owner supplies fresh evidence. This ticket does not authorize live Hermes calls, paid execution, packaging, installation or activation.

## Reproducible inputs and local checks

Run the focused selection with Python 3.11:

```sh
python tests/offline_reliability_gate.py --report /tmp/clinical-focused-report.json
python tests/ai_quality_campaign.py --output /tmp/clinical-owner-plan.json
```

The same selection runs in CI. It covers concise/negated drafts across five sparse families, raw intake aliases, authentic review/source/render identity, actual native prose repairs across five rich families, native tables/headers/footer and XML corrections, structural/corrupted-file negatives, final review freshness, independent Protocol/ICF visual tasks, dispute-only review, installation worker discovery, complete and review-only delivery, unavailable packages and persistent deadlines. There is no producer-rule inventory or mandatory semantic adjudication registry. Ordinary generation does not run these development checks. Historical tests outside this selection are historical expectations; they are not release obligations. Full-suite execution requires separate approval.

The generated manifest fixes ten synthetic cases: clean sparse and deliberate substantive-repair rich cases for each Retrospective, Prospective/Advarra, Prospective/Sterling, Ambispective/Advarra and Ambispective/Sterling family. It embeds each complete source and its canonical JSON SHA-256. Preserve the manifest bytes and record its hash before observing outputs. Preserve the fixture revision and package fingerprint. Do not tune the source, prompts or defect after inspecting results. A changed candidate requires a new campaign and separate denominator.

## Owner execution protocol

1. Obtain separate authorization for the Linux run and any paid model usage. Use the existing installed candidate only after its exact package fingerprint, tracked revision, runtime executable/version, renderer/font paths and installation smoke identity are recorded. Installation/activation remains separate work.
2. Materialize each manifest source into a fresh isolated run directory. Record both the canonical manifest source hash and exact file-byte hash. Obtain normal source approval and preserve the exact approved-reference hash. No real client input participates.
3. For clean cases, run the ordinary Desktop lifecycle without a test defect. For repair cases, use a run-local harness that appends the manifest's unsupported experimental-drug sentence to the initial authenticated Protocol introduction drafting response **before that response is consumed and before candidate construction, hashing, render or review**. Preserve the response's real request bindings. The harness must copy and record the original response, injected response and hashes. Never modify the approved source, an already-reviewed candidate, shared skill scripts or the active release. The local example is `test_real_injected_prose_is_removed_and_freshly_reviewed_across_families` in `tests/test_general_document_repair.py`; its drafting callback is the injection boundary. A Linux live adapter for this callback must be reviewed before execution; this plan does not claim that adapter is installed.
4. Let the real independent content reviewer discover the defect from native files and the approved source. Do not supply a prewritten passing review or hide the injected sentence from review. The general native repair author removes unsupported content. Require fresh independent content and all native-page visual reviews, complete final-file delivery and actual open/readback confirmation. Preserve final document bytes, hashes and reviewer/render evidence. Manually verify the unsupported sentence is absent and no approved meaning disappeared.
5. Execute all ten fixed cases. Stop only for a recorded failure or owner cancellation, keeping unexecuted cases visible. A retry is another operation linked to its prior attempt, not a replacement. A resume of the same operation keeps its original ID, start time and persisted 45-minute deadline. Do not restart timing after repairs, disputes or handoff failures.

## Evidence ledger and timing report

Keep one JSON array row per operation, including aborted, failed, review-only and unavailable results. Record:

- `case_id`, `operation_id`, `retry_of` (null for the first attempt), run directory, start/end timestamps and final `status`/terminal cause; cancellation and unexecuted cases stay in the campaign ledger.
- Exact package fingerprint, tracked candidate revision, manifest hash, original source-file hash, approved-reference hash, initial candidate hashes, final candidate hashes, actual renderer/font/runtime identity and authenticated request/response evidence paths.
- `elapsed_seconds`, all `stage_timings`, drafting/review/repair attempt counters, `repair_cycles`, `changed_native_repairs` and `dispute_cycles`. Retain stages that failed and resumed time.
- Delivered file names, byte counts and SHA-256 hashes, final manifest identity, `delivery_confirmed`, actual confirmation evidence and final content/visual judgments. A quick review-only or unavailable result is not a successful under-target document.

Then run:

```sh
python tests/ai_quality_campaign.py --operations /path/all-operations.json --output /path/timing-summary.json
```

The summary retains every submitted row and reports three mutually exclusive groups: clean (no changed-native repair or dispute), changed-native repairs (including any disputes), and dispute-only (no changed native bytes). Each denominator includes all submitted operations in that group, including failures and retries. The numerator requires `status=passed`, actual `delivery_confirmed=true` and total elapsed below 1500 seconds. Report client-ready counts, under-target proportions, total elapsed and stages alongside the original ten-case completion table; zero-member groups have no proportion. Independently verify ledger completeness against operation directories and owner cancellation records. A summary cannot infer omitted operations or establish quality from timing fields alone.

## Reconciliation with #89 and #90

#89's useful evidence goals remain: five-family sparse/rich behavior, defects and false alarms visible to independent reviewers, actual final artifact bytes, complete delivery, and explicit operation/latency denominators. Spec 103 retires per-semantic-rule owners, registered repair surfaces, producer inventories and rule-specific adjudication/maintenance obligations. The ten fixed cases replace those obligations for this implementation's owner plan; they do not claim statistical coverage of every clinical defect.

#90 still owns fresh evidence against the **exact installed Linux candidate**: package identity, renderer/font smoke, real independent reviews, final delivery/readback and live latency. No local adapter result fulfills that work. #89 and #90 are not closed or claimed complete here. After the separately authorized campaign, the owner can attach the original manifest, all operation ledger rows, final bytes/hashes, smoke/reviewer evidence and timing report to those issues and assess readiness.
