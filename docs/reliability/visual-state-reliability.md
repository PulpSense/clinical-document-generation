# Bounded Desktop visual/state reliability repair

## Implemented

The concurrent independent content/visual branch now exits its wave `finally`
before calling `finish`. Wave timings and the running checkpoint are recorded
before terminal state and its diagnostic archive. Serial parent failure, concurrent
parent failure, worker authentication/launch failure and hard-deadline expiry are
covered through public Desktop operation paths. Resumption still uses the original
persisted UTC deadline; neither worker cap nor the operation ceiling is changed.

The production adapter explicitly tells the scheduler whether a parent visual
callback is configured. When delegated review is incomplete and none is configured,
the terminal finding is `parent_visual_callback_unavailable`, with zero parent
callback attempts. Ordinary generation can still use authenticated delegated review
without a parent. The lower-level Desktop interface retains its existing default
for caller-owned parent dispatch. `parent_visual_callback_available` describes
callback presence only, not successful invocation or image capability. The production
report distinguishes configuration from image-capability validation (`not_attested`
for a configured callback, `unavailable` for an omitted callback).

The executable callback regression launches real sleeping callback subprocesses
and detached descendants, times out delegated dispatch, invokes actual fallback,
and verifies timeout evidence, reaping and absent responses. It never creates an
image judgment. Existing callback integrity/binding/cleanup checks remain intact.

The independent integrity probe is promoted to
`tests/test_scheduler_interrupted_dispatch.py`. It stops the parent immediately
following production dispatch rejection, before scheduler rejection persistence.
Both checkpoint-only and final-only evidence, under candidate and promoted dispatch
policies, retain durable unit rejection; restoring runtime bytes does not restore
credit. Earlier unaffected assessments survive, stale parent aggregates are rejected,
and resume uses fresh remaining-scope requests and the original approval/deadline.
No scheduler integrity implementation is changed.

## Visual chunking blocker: no speculative transport change

Current `quality.py` visual request validation requires exactly one complete
request per document, its canonical review-set request ID, all mandatory checks,
and artifact inventory equal to the full current render. Native DOCX, PDF and every
page SHA-256 are authenticated. The response validator requires exactly one row for
every bound page, including every mandatory visual check. Request creation supplies
one whole document to one independent reviewer. Unlike content review, visual
review has no authenticated unit-ledger, partial-progress, scope-resume or aggregate
recombination contract.

Splitting the existing request or removing page bindings would therefore fail
`verification_request_incomplete_scope` or weaken the gate. Safe bounded visual
units need a new transport contract: parent-request hash and revision/source/
generation-authority/native/PDF/page identities on every fresh unit; exact page/check
ownership and durable accepted-unit provenance; independent review of cross-page
table continuation, heading flow and TOC destinations; non-overlapping complete
coverage validation and an authenticated terminal recombination route. They also
need bounded concurrent dispatch and an explicit finalization reserve within the
existing 240-second delegated wave, while retaining the 480-second parent cap and
honest incomplete coverage when the reserve/deadline is reached.

That is a multi-layer request/response and review-provenance redesign, not a safe
minimal change to the current document request. No chunk implementation, page-count
tuning, timeout extension, partial approval, manufactured aggregate or speculative
prompt-only latency fix is included here. The preserved four-sequential-image-wave
Protocol timeout remains an open workload limitation; tool success is not an
accepted visual response. A later separately specified authenticated visual transport
is required to address it safely.

## Evidence limits and acceptance

The production operation-level cleanup booleans remain historical adapter constants,
not an observed PID census. This patch does not reinterpret them as cleanup evidence.
Actual subprocess cleanup is tested and recorded by the command callback supervisor;
that evidence must not be generalized to every historical delegated descendant.
A production-wide cleanup observation contract is outside this bounded seam.

A configured executable is not proof of genuine image capability. The acceptance
procedure still requires discovering and validating an existing genuine request-bound
image-capable parent callback before paid cases; without it, complete unpaid checks
and stop with `parent_visual_callback_unavailable`. No callbacks were manufactured
for acceptance. Test fixture bindings are structural evidence, not clinical or visual
approval. No paid calls, client reruns, installs, activation, commits or pushes were
performed for this repair.
