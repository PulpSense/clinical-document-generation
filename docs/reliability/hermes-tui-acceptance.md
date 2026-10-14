# Hermes TUI host checks and acceptance

## Current owner-authorized scope

For the TUI visual correction campaign, execute exactly the independently audited
five-case pilot below, fast focused regressions, unpaid host/render checks and
the mandatory bounded genuine callback/fallback admission probe on the matching
candidate. **Do not execute any other fixed cases, even if the pilot passes.**
Freeze the manifest with `--pilot-scope owner-five-only`; the runner rejects
`--phase remaining` for that hash-bound scope before admission or spending.
Retain all first outcomes and failed evidence. Report five-case pilot-only
acceptance and other fixed cases as not run by owner direction, never full
28-case acceptance. The default full-campaign criteria and remaining-case
reference below are unchanged, but they are not execution authorization.
No client-study restart is authorized.

Exact owner pilot IDs, in execution order:

1. `retrospective-sparse-complete.r1`
2. `prospective-advarra-sparse-complete.r1`
3. `prospective-sterling-sparse-complete.r1`
4. `ambispective-sterling-sparse-complete.r1`
5. `ambispective-advarra-sparse-complete.r1`

These are existing fixed clean baseline cases, not additional or duplicated runs.

Run this procedure on the actual Linux Hermes host before another client study.
Use a development checkout at the same commit as the freshly replaced installed
candidate. Helpers under `tests/` are developer commands, not additional skill
CLI entrypoints. Preserve the existing Linux Python, LibreOffice, fonts, Hermes
profile/provider/model and installation instructions. Do not require sudo,
Bubblewrap namespaces or an attachment opener. Do not use the older
`installed_capability_campaign.py` for this TUI campaign.

Use the existing validated `CLINICAL_PYTHON`, absolute installed `RELEASE_ROOT`,
matching development `CHECKOUT`, fresh `CAMPAIGN_ROOT` outside installed code,
and a genuine executable `PARENT_VISUAL_REVIEW_COMMAND`. The parent command must
follow the existing `--parent-visual-review-command` contract: inspect actual
images and produce authenticated visual responses. The bundled executable is
`$RELEASE_ROOT/scripts/tui_visual_callback`; production TUI selects it by default
unless an explicit callback override is supplied. File presence is not image
capability. Never return constant passes or impersonate a parent observer.
If it is unavailable, stop with `parent_visual_callback_unavailable`.

## Unpaid host checks

From the matching checkout, after candidate provisioning and installation
verification pass:

```bash
"$CLINICAL_PYTHON" -B tests/hermes_tui_host_checks.py \
  --release-root "$RELEASE_ROOT" --evidence-root "$CAMPAIGN_ROOT/host"
```

Require `host/host-checks.json` status `passed`. The command exercises actual
installed Hermes file tools over 2,048 lines in bounded chunks, safe checkpoint
creation/readback, general Python DOCX/XML tools, descendant cleanup, real
rendering before and after native repair, unchanged dependency identity, and
exact local output bytes. Retain stdout/stderr and render evidence on failure.
It makes no model API calls. Login-status availability is checked; provider
inference and real model image inspection are tested by the paid cases.

The report records the installed commit, package fingerprint, manifest hash and
actual worker/model/dependency identity. Extra runtime bytecode files remain an
integrity failure. Do not remove files or weaken inventories to force a pass;
replace/provision the candidate cleanly and rerun under a new evidence root.

## Freeze and run the pilot

Before any pilot, run one explicitly authorized synthetic callback probe on
this exact installed candidate. It injects a short delegated timeout (not a
change to the production 240-second ceiling), then exercises one genuine
callback with the remaining budget. The fixture is not a clinical generation
entrypoint or a rendering certificate. Retain first failures; do not loop paid
probes on an unchanged implementation. The report binds actual session/model,
image tool evidence, authenticated responses and implementation hashes.

```bash
"$CLINICAL_PYTHON" -B tests/run_tui_visual_probe.py \
  --release-root "$RELEASE_ROOT" \
  --candidate-identity "$CAMPAIGN_ROOT/host/candidate-identity.json" \
  --run-dir "$CAMPAIGN_ROOT/callback-probe" --authorize-paid-probe
```

Require complete accepted image judgments and successful fallback. The runner
revalidates actual returned read-line coverage and correlated successful image
results from retained session databases, not EOF/full-read claims. It binds the
intact installed manifest, source hashes and command at launch into the parent
request, persisted operation, invocation snapshot and observer provenance;
accepted response/ledger hashes bind that provenance. Mutable report labels or
flags cannot establish matching-candidate admission. Development evidence and
older probes lacking those durable installed bindings must not be relabelled.

```bash
"$CLINICAL_PYTHON" -B tests/ai_quality_campaign.py --host-mode hermes-tui \
  --pilot-scope owner-five-only \
  --candidate-identity "$CAMPAIGN_ROOT/host/candidate-identity.json" \
  --host-checks "$CAMPAIGN_ROOT/host/host-checks.json" \
  --output "$CAMPAIGN_ROOT/manifest.json"
"$CLINICAL_PYTHON" -B tests/run_tui_acceptance.py --phase pilot \
  --manifest "$CAMPAIGN_ROOT/manifest.json" \
  --host-checks "$CAMPAIGN_ROOT/host/host-checks.json" \
  --release-root "$RELEASE_ROOT" --runs-root "$CAMPAIGN_ROOT/runs" \
  --parent-visual-review-command "$PARENT_VISUAL_REVIEW_COMMAND" \
  --callback-probe "$CAMPAIGN_ROOT/callback-probe/probe-result.json" \
  --approved-by 'owner-authorized synthetic acceptance' --authorize-paid-campaign
```

The manifest freezes 20 baseline first operations (10 clean, 10 deliberate prose
repair) across retrospective, prospective/Advarra, prospective/Sterling,
ambispective/Advarra and ambispective/Sterling, plus eight supplemental cases.
The default full-campaign pilot has three operations (retrospective and both
prospective consent families). The explicit owner-five-only pilot adds the
fixed ambispective/Sterling and ambispective/Advarra IDs listed above, covering
all five families. No client source is used. Owner authorization for this
synthetic pilot permits fixture approval only, not any new client facts.

## Independent audit

Audit each pilot before expansion, then every remaining operation. Use an
independent reviewer identity that did not draft or repair that operation.
Compare every fact and relationship in the manifest's `expected_fact_ledgers`
against final native DOCX/XML. Inspect every final rendered page bound to the
publication/review output. The injected seed ledger is an audit checklist, never
a substitute for looking at files and images. Preserve localized findings,
page references and actual inspection evidence in the run directory.

Write `<run>/independent-artifact-audit.json` with this schema. Populate it only
from actual inspection; zero defects and `true` values are earned observations.

```json
{
  "schema_version": "readiness-artifact-audit/v1",
  "auditor_id": "actual-independent-reviewer-identity",
  "independent_of_drafting_and_repair": true,
  "all_source_facts_reviewed": true,
  "all_final_pages_inspected": true,
  "material_defects_remaining": 0,
  "collateral_loss": 0,
  "seed_results": {},
  "delivered_artifact_sha256": {}
}
```

Populate `seed_results` for every fixed operation seed ID, each containing
`expected_outcome_verified` plus observed evidence. Populate
`delivered_artifact_sha256` with every final native filename and actual SHA-256,
including `REVIEW-ONLY-` prefixes for F3. For F3, record
`all_unresolved_concerns_reported` and `no_unreported_material_defects`; it must
remain an honestly labeled complete Review-only Document Set. Other cases
require passing clinical status and no material defects. Missing/failed audits
remain failures or incomplete evidence, never inferred successes.

## Remaining cases and decision (reference only; not authorized)

**Do not run this phase under the current owner scope.** The following retained
procedure defines unchanged full-campaign criteria, not a pilot-only pass.

Run the same runner with `--phase remaining` after pilot audits. It refuses
expansion unless all three pilot outcomes have passing independent audits and
verified local bytes. Q1–Q4 exercise numerical/negation/table associations,
consent/valid XML values, long-source/header fidelity and table clipping. F1
limits evidence reads, truncates a real final after a consumable authenticated
checkpoint, then interrupts/resumes the same operation and deadline. F2 removes
delegated visual workers, requires genuine parent image review and injects one
transient local output read failure. F3 injects a substantive concern and an
actual repair-worker launch fault (TUI does not claim OS write denial). D1 tests
an independently resolved prior paraphrase hypothesis. The fault variants are
explicit in the frozen TUI manifest; none manufactures reviewer judgments.

Each ordinary operation keeps its 45-minute deadline, including F1 resume.
A terminal failure is retained and is never automatically retried. Do not
change candidate/model/settings midway, or omit failed cases. If a first
operation fails, repair the implementation separately and start a new frozen
campaign; retain this campaign in the evidence. A pilot failure stops expansion.

After all audits, collect:

```bash
"$CLINICAL_PYTHON" -B tests/ai_quality_campaign.py \
  --readiness-manifest "$CAMPAIGN_ROOT/manifest.json" \
  --host-checks "$CAMPAIGN_ROOT/host/host-checks.json" \
  --runs-root "$CAMPAIGN_ROOT/runs" --output "$CAMPAIGN_ROOT/report.json"
```

Require `tui_local_acceptance: passed`: all 28 fixed first outcomes independently
audited, correct expected statuses, exact local bytes, every operation within
45 minutes, at least 8/10 clean and 8/10 repair cases under 25 minutes, no
reconciliation errors or unmatched operations, and the exact bound host-check
report. Missing cases remain visible; retries cannot repair first-operation
rates. This supports local TUI generation acceptance. It does not prove universal
clinical reliability, isolated certification, or recipient transfer. Overall
`readiness` remains incomplete for those broader claims.

Stop after the report and return the commit/fingerprint, host-check status,
all 28 outcomes, audits, timing, failures and evidence paths. Do not start another
client study as part of this campaign.
