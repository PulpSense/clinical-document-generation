# Bilateral-study review and PRS repair

## Evidence and reproduction

Run revision `r-9218b5efbaa1` used release `549a554` and expired after
2,702.136 seconds. No client documents were released. Its Background drafts passed;
this failure occurred downstream of the preceding Background fix.

The approved sample-size field was `36 subjects per cohort; 72 subjects total`.
The PRS mapper selected its first number, 36, and the deterministic validator used
that same parser. The combined PureSee/Odyssey intervention was linked only to the
first cohort. Both defects reproduced directly from the archived approved source.

Participant Completion was drafted seven times because validation required exact
visit and timing labels despite its brief-reference ownership. The last draft
therefore repeated the full schedule. Study Completion never received the supplied
`study.completion` condition about scheduled follow-up and database checks. The
front-matter follow-up synopsis also fell back to the entire study timeline when
visit timing lacked the word `postoperative`. A schedule-only source summary was
rendered as a supplemental note below the already complete table.

Four full content-review answers reported these errors. None was consumed: a failed
cross-document population assessment cited its exact enrollment finding, but the
validator allowed such finding links only for a limited procedures warning. The
first answer is consumable in the repaired adapter with all six blocking findings
retained and no transient response-format findings. The fifth worker was stopped
by the operation deadline. Drafting and retries consumed approximately 15 minutes;
independent verification consumed approximately 25 minutes. These are archived
measurements, not forecasts for future runs.

## Repairs

- Prefer explicit study-wide enrollment totals regardless of text order. Keep
  established plain counts and leading totals with parenthetical breakdowns.
  Subgroup-only and conflicting-total descriptions remain unresolved rather than
  acquiring an invented total.
- Preserve all exact source cohort names in a combined intervention as repeated
  PRS arm labels. Longer overlapping names take precedence; explicit structured
  associations remain authoritative. Mapping and validation share this projection.
- Require the supplied participant-completion rule, not every visit label. Preserve
  independently supplied conjuncts such as the exit-form requirement.
- Supply `study.completion` to Study Completion and require its explicit closeout
  prerequisites as well as the study timeline.
- Use the final supplied visit timing in the follow-up synopsis even without the
  word `postoperative`.
- Omit only proven schedule restatements from table notes. Retain novel assessment
  relationships, qualified instructions, and continuous safety-collection duties.
- Consume a bound blocking review whose non-passing cross-document assessments
  cite exact, valid reported finding IDs. Findings remain blocking; passing reviews,
  orphan failures, stale bindings, duplicate IDs, and incomplete assessments retain
  their validation protections.

No deadlines, renderer dependencies, document templates, approval requirements,
drafting topology, or delivery gates were changed.

## Verification and limits

The regression fixture retains the archived approved source and initial Operations
request/response. Tests cover PRS generation and validation, omitted cohort links,
changed enrollment, partial product-name matches, subgroup-only sample sizes,
missing completion facts, ambiguous schedule notes, consumable blocked reviews,
and uncovered cross-document failures. The newly added negative checks failed
before their corresponding repairs. Spec and Standards reviews cleared after the
initial review findings were corrected.

Only focused regressions and static compilation ran locally. No full suite, live
certification corpus, or model-driven study generation was run. A fresh approved
Hermes run must verify end-to-end generation, complete review, and exact-byte
release. This patch addresses reproduced defects; the broader input-variation and
section-ownership reliability audit remains separate follow-up work.

Validation results: 423 focused checks passed across the mapping, contracts,
handoff, Desktop adapter, template, architecture, and successful-run regressions.
A final decimal-interval regression caught and corrected sentence splitting at
`1.5`; after that correction all 134 selected drafting/previous-run checks passed,
including all 26 bilateral failure regressions. Python compilation and
`git diff --check` passed. The archived first complete content review was replayed
successfully as a blocking response with six retained findings and zero transient
response-format findings.
