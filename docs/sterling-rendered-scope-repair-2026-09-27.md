# September 27 Sterling rendered validation repair

## Evidence and cause

The bilateral study's `__03` evidence archive records a 995.81-second blocked operation with three candidate renders. BACKGROUND and PROCEDURES passed drafting validation but failed the later Sterling clause checker repeatedly. The earlier repair changed drafting's evidence projection; the rendered checker still flattened raw source. It therefore required background objective details and structured visit row identifiers that drafting correctly assigned elsewhere. The earlier repair was incomplete across the two validation paths.

Replaying the actual candidate documents also exposed a PURPOSE maximum-word failure. The final clause exceeded the existing 140 normalized-word maximum, including the template's source-filled enrollment sentence. Drafting neither communicated nor checked this budget, allowing an overlong draft to reach rendering.

## Repair

- Both drafting and the rendered Sterling checker call the same section evidence projection. Approved-source bytes, full structured schedules, clinical quantities, fixed template clauses and conditional safeguards remain governed by their existing checks.
- Sterling PURPOSE requests expose and validate the existing rendered word budget before rendering. The available draft budget subtracts the literal enrollment paragraph from the packaged template after filling the approved sample size. The rendered maximum remains unchanged.
- No study-specific exemption, template edit, deadline extension, retry increase or delivery-rule change was introduced.

## Verification

Seven new regression tests replay all three archived ICF candidates through the real Sterling clause checker; BACKGROUND and PROCEDURES clear. A missing 66 cm measurement remains blocking. Tests also cover template-reserved word budget, early overlength rejection and a controlled in-memory candidate whose entire Sterling clause check passes after a concise, source-grounded PURPOSE replacement. This controlled replacement is a test fixture operation, not a modification of client outputs or a substitute for generation.

The focused selection covering these checks, visit identifiers, bilateral content, background scope, Sterling fidelity and comments, duration, Brad's editorial feedback, contracts and handoff quality passed: **265 tests**. Standards and spec reviews reported no material findings. No full suite or live study generation ran.

A fresh Hermes run is still needed to verify generation, rendering and independent review together. These replays verify the diagnosed failures; they do not establish that every future input will complete successfully.
