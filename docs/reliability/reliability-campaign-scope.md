# Reliability campaign implementation

Review baseline: `edd9a42966272cdf6927b142bfe3a7ad90b2659a`.
This implements the user-approved next step toward general reliability under
issues #89 and #90. It supplements the existing offline branch conformance;
it does not replace live Linux delivery evidence or complete those issues.

## Approved scope and completion criteria

- Use the existing public intake, generation and recovery interfaces, plus a
  developer test-pack CLI. Preserve Linux dependencies and installation checks.
- Author varied synthetic inputs covering Retrospective and both consent
  families for Prospective and Ambispective. Include equivalent narrative and
  structured inputs, sparse optional details, and explicit assessment timing.
- Export raw inputs separately from independent expected facts. Intake requires
  normal editable Source-of-Truth approval; fixtures never approve themselves.
- Exercise admission and complete publication locally with explicitly controlled
  model/render adapters. These tests establish routing, review obligations and
  integrity, not clinical correctness or visual quality.
- Provide a three-study live pilot before expansion, with instructions to keep
  terminal failures visible and stop rather than automatically restart a study.
- Collect every retained operation, first-operation versus eventual delivery,
  recovery, elapsed time and output identity. Keep external artifact audits
  separate; neither a workflow pass nor collector exit certifies reliability.
- Reproduce the supplied blocked operation's reviewer transport failure, repair
  the general contract boundary, and preserve independent judgments and full
  response validation. Unknown schemas and foreign or incomplete evidence fail.
- Run focused tests and a Standards/Spec review, then commit on the current
  branch. Full-suite execution, installation and live paid runs are outside this
  implementation request.

## Diagnostic findings

The supplied October 10 archive's first operation stopped after 1,041.353 seconds.
Its protocol visual response used the request label `hermes-verification/v1`
instead of `hermes-verification-response/v1`. Both parent callbacks replayed
the same invalid label. The actual 12-page response reproduces rejection on the
baseline and is accepted by the corrected public adapter, with page judgments
unchanged. The adapter records the normalization and original semantic hash;
raw reviewer stdout remains preserved. Response prompts and parent request
metadata now state the response label explicitly. No study facts are involved.

The new varied sources exposed another lexical veto: record retention phrased
as “years after” matched an authorization-expiry marker despite an absent
authorization-duration input. Phrase-only matches now use the existing bound
independent uncertainty review. Confirmed unsupported claims require correction;
unresolved uncertainty still prevents publication. Objectively present prohibited
compensation or GINA sections, exact clauses and required safeguards retain
their checks. This applies to marker-based conditional-clause inference generally.

## Evidence boundaries

The five new fictional studies yield ten exported inputs and five independently
authored fact sets, shared by equivalent representations. They cover home diaries,
hand function, radiology records, skin diaries and hearing follow-up. The oracles
are semantic audit instructions, not word-matching validators or blinded trials.
The local generator adapter can preserve narrative evidence without making real
clinical interpretations. Only live independent reviews can establish whether
those relationships are drafted correctly in practice.

The collector measures supplied evidence; it cannot discover deleted or withheld
run directories. Missing elapsed times make totals partial. It verifies reported
delivery bytes, not all publication-ledger claims or clinical review judgments.
The external-audit count intentionally remains pending until a separate audit is
performed. Live evidence across varied inputs remains the next step before any
production reliability claim.
