# Spec #114 engineering and readiness preparation

Status: engineering implementation and offline preparation; installed readiness
remains unmeasured. This report does not certify or activate a release.

The implementation preserves authenticated checkpoint evidence independently of
final-response parsing, retains concern identities across units and repairs,
and rejects inconsistent assessment credit with scoped retry feedback. Native
review packets retain canonical source, Word XML locations, table associations,
headers and full native artifacts. Measured workload fields distinguish actual
serialized bytes and pages from unavailable token/read counts. Production logs
retain observed worker usage and stage/deadline measurements when available.

Ordinary Linux workers use the same Bubblewrap boundary exercised by the
installed probes: read-only package/source/evidence, role-specific writable
areas, private runtime state, a restricted provider bridge and process cleanup.
Reviewer and repair-author denial probes exercise both directions of the role
boundary. Installed admission requires evidence for all declared lifecycle
capabilities and exact package, tool, model configuration, renderer/font,
PDFium and callback identities. Missing dependency metadata blocks admission
with an actionable diagnostic. A small authenticated read alone cannot admit
clinical generation.

## Prepared campaign

`tests/ai_quality_campaign.py` freezes ten baseline cases repeated twice (20
planned operations) plus Q1–Q4, F1–F3 and D1 (eight supplemental operations).
The initial pilot is the Retrospective case and both consent-template families.
Long Q3/Q4 sources exercise both consent templates. Source-owned independent
fact ledgers and concrete mutations cover quantities, negation, schedule
association, safeguards, omissions, running headers, valid XML facts and
clipped populated schedule content. D1 records an explicit test-owned disputed
hypothesis; it does not impersonate a reviewer.

The run adapter invokes the actual installed production lifecycle. Faults use
real authenticated checkpoint/final bytes, constrained reads, genuine parent
visual fallback and recipient retries. F1 refuses to claim recovery without a
consumable checkpoint and resumes the same original operation/deadline. F3
retains an unresolved outcome rather than supplying a synthetic reviewer pass.
Every failure and retry remains evidence. The collector retains conflicting
observations, fixed planned denominators, exact outcome/artifact hashes and
independent audits. Missing observations yield unmeasured rates.

## Owner-run boundary

Separate owner authorization required by #114 still applies to installation,
Linux host changes, paid probes/campaign execution and activation. None of
those actions was performed during this implementation. Offline local tests
and a clean candidate package do not establish Linux isolation, model capacity,
recipient access, clinical quality or the under-25-minute readiness target.

After authorized installation of the exact archived candidate, run the probe
collector documented in `references/runtime-and-release.md`. Preserve its raw
evidence and assurance cache. Freeze the actual installed worker identity along
with the archive hash, manifest hash, package fingerprint and source commit in
an identity JSON before preparing the runnable campaign manifest:

```sh
"$CLINICAL_PYTHON" tests/ai_quality_campaign.py \
  --candidate-identity /absolute/candidate-identity.json \
  --output /absolute/readiness-manifest.json
```

Use `tests/run_readiness_case.py` for one explicitly authorized planned
operation, with the frozen manifest, exact installed root, real recipient and
parent callbacks, unique run directory, named fixture approver and
`--authorize-paid-operation`. F1 uses `--resume` with the same run directory;
retries use distinct directories and `--retry-of`, preserving the first attempt.
No runner installs or activates code or silently launches replacement attempts.
After independent audits, reconcile all retained run directories:

```sh
"$CLINICAL_PYTHON" tests/ai_quality_campaign.py \
  --readiness-manifest /absolute/readiness-manifest.json \
  --runs-root /absolute/campaign-runs \
  --output /absolute/readiness-observations.json
```

Actual readiness and any activation decision remain pending these observations.

## Offline verification

The selected offline reliability gate passed with 193 tests and three skips
(591.78 seconds). This selected gate makes no paid model calls and is not the
full test suite. Linux process-isolation tests skip on macOS; ordinary Linux
role-boundary behavior still requires the installed owner-run evidence above.
Architecture/production-adapter selection also passed (41 tests). Python
compilation and whitespace checks passed; no typechecker is configured here.

Independent standards and spec reviews found and prompted fixes for retained
concern identity, inconsistent judgment credit, real fault binding, source-owned
seeds, duplicate observations, installed metadata diagnostics and title context.
The final evidence-preservation regression reproduced substantive findings being
overwritten by presentation-only same-ID restatements at both unit and parent
aggregation. A shared merge now preserves the substantive support alongside
retained nonpassing judgments within that review set; subsequent independently
bound repair/review cycles can still resolve or dispute the concern.

Both new aggregation regressions failed before the correction and passed after
it (two tests). The independent spec review confirmed the correction at both
boundaries and found no remaining material issue in that diff. The independent
standards review found no concrete defect in the separate Linux role probes.

After the final merge correction, the two affected recovery test files passed
all 40 selected tests (125.74 seconds). No full-suite execution was performed.

The first GitHub Linux run reached its 900-second developer-check timeout after
183 completed cases with no reported test failures. CI now runs the ordinary
Linux role-boundary tests as an explicit early step and allows 1,200 seconds for
the selected offline gate. This is a developer test budget change; it does not
change the production operation deadline or establish readiness timing.
