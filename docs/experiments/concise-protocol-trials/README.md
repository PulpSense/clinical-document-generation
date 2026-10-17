# Protocol section writing trials — 17 October 2026

These controlled trials exercise the revised drafting instructions before DOCX
assembly. Each request retains the study's approved facts, the three target
section contracts, the effective n8n messages and the current adapter instructions.
Each response contains actual section drafts generated manually by Codex in this
conversation. The same agent reviewed them against the saved sources. No separate
model API, Hermes generation, independent reviewer, document render or automated
clinical-quality benchmark was used. These trial drafts do not replace approved
run outputs or establish performance across future model calls.

The three sections are Methods Used to Minimize Bias, Visits and Examinations,
and Study Methods and Measurements. Bias explains why controls matter and refers
to their methods. Visits retains the activity schedule, mode, windows and duration.
Methods owns detailed definitions and exceptions. Essential quantities and timing
may recur so each section remains usable. No word-count gate or prose-trimming
code was added. All 22 retained n8n nodes remain unchanged.

| Case | Manual comparison with approved facts |
| --- | --- |
| GLIDE | Ingredient counting, stable groups, both-eye selection versus fixed-eye follow-up, two-reading average, 0–100 function with positive change as improvement, irregular historical records/tie rules, encounter deduplication, unknown changes distinct from zero, two clinic contacts and one phone contact preserved. |
| BREAK | Stratified block randomization and allocation release, assessor masking versus unmasked symptoms, contact windows/durations, no telephone acuity/satisfaction, Day 1–56 diary without symptoms, interval denominator and not-estimable adherence preserved. |
| COMFORT | Historical abstraction after consent, 70/15/40-minute contacts with Day 30 and Day 90 windows, per-eye acuity, positive comfort change, mandatory single saliva sample, targeted genotyping, destruction deadline versus retained data, genetic nonreturn versus offered vision results preserved. |

The review found no material omission within these three-section trials. Repeated
step-by-step rules now sit in Methods; brief references elsewhere replace those
repetitions. Contact timing, assessment names, analysis distinctions and necessary
scientific limitations still recur. Payment, authorization and other consent
sections were outside this writing trial and remain governed by their existing
source and template contracts. Actual response variation still needs the next
Hermes confirmation run.

`xml-replay.json` records a separate deterministic XML-only replay from GLIDE's
saved approved reference and unchanged brief/detailed narratives. Exactly five
leaf values change: three explicit False values become No and two observational
arm types become blank. Other values, element names/order, group labels and
narratives remain identical; no DOCX was generated or approved source modified.
The local replay XML is retained under `.scratch/glide-fix/GLIDE-study.xml`.

Focused XML transport and generation-only workflow tests pass (33 cases).
The older `test_prs_xml.py` and `test_prs_quality_corrections.py` files have
35 pre-existing failures that expect removed reviewed-workflow checks. Running
the same files with the `cf810a8` PRS module reproduces the identical 35 failing
test IDs. Their 44 remaining tests pass after updating the four lowercase
healthy-volunteer expectations to the client’s Yes/No vocabulary. No removed
review gates were restored and no full test suite was run.
