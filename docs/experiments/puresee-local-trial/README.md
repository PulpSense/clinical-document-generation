# Brad PureSee/Odyssey local trial — 17 October 2026

The owner requested a complete local run of the supplied
`SYNOPSIS_PureSee Odyssey_23Jun2026-2 (1).txt` before Hermes. The synopsis lacks
operational required fields. The owner explicitly authorized reuse of the earlier
PureSee/Odyssey test site, sponsor/IRB, contacts, compensation, screening interval
and descriptive analysis supplement. These values are identified separately from
Brad's clinical facts; no real study approval or actual client source approval
is claimed. The local workflow approver is explicitly controlled-test-only.

Using the current public source preparation, approval, drafting handoffs,
response ingestion and generation workflow, Codex authored 43 Protocol/Advarra
ICF sections and two PRS narratives. The original n8n prompt adapter and current
section instructions were used. This is actual local Codex writing, not the
deterministic acceptance fixture or a separate Hermes inference run.

## Result

- Protocol: 12 pages inspected; all 44 TOC references match the actual pages.
- Advarra ICF: four content pages inspected; no trailing blank fifth page.
- XML: parses, matches the retained Brad manual structure and selected observational
  branch; 40 participants, one group, one primary and seven secondary outcomes,
  all at 3 months postoperative. Observational arm type remains empty.
- Clinical review preserves the bilateral lens/eye relationship, photopic binocular
  measurements, 66 cm and 40 cm distances, +1.0 D through -2.50 D defocus range,
  per-question AIOLIS summaries, Month 3 safety/exit activities, 35-to-40 sample
  rationale and all three supplied references. Expectations remain hypotheses.
- No unsupported chart, acuity unit, defocus step, age bound, operative interval,
  postoperative anchor relative to the two eye operations, visit window, calendar
  date, risk inventory or regulatory decision was invented. Unprovided optional
  PRS fields remain blank. Source-limited sections use applicable existing boilerplate.

The study has three schedule phases and four encounters because the operative
phase occurs once per eye. The grouped source phase labels remain consistent
across the Protocol and ICF; no expanded visit numbering is invented.

## Corrections during the local trial

An initial draft used empty optional list labels; the response was corrected to
omit those labels. Source extraction added the explicitly supplied age-related
cataract condition and removed internal missing-detail commentary from the
participant-duration display. The existing assessment_presentation response
controls remove repeated matrix notes while preserving the unique defocus bounds.
These are run-local source/draft corrections, not production prompt changes.
Earlier attempts remain preserved under `.scratch/puresee-local-test/`.

One clear general formatting defect was found: an unused final Advarra template
paragraph overflowed onto a header-only fifth page. Issue #118 and commit
`d5df8f0` remove only ordinary terminal ICF spacers while preserving fields,
objects, breaks, signature room and the paragraph immediately after a table.
The native family regression failed for Advarra before the fix and passed after.
20 focused ICF-spacing/generation-only tests pass in 45.75 seconds; no full suite
was run. Standards and Spec reviews each reported zero findings.

The final public run uses the corrected implementation. Its Protocol page PNGs
are byte-identical to the 12 fully inspected earlier pages. All four final ICF
pages were inspected; its document XML differs by exactly one removed empty
terminal paragraph, preserving all text and signing lines. The final source,
request implementation hashes, XML structure and delivered artifact hashes were
checked. `results.json` contains the receipt; `source.json`, `sections.json` and
`prs-response.json` retain the source and local drafting provenance.

Final workflow time is 13.42 seconds for reassembly of retained local drafts,
not fresh end-to-end inference or total manual review time. No Hermes performance
claim is made. No independent clinical certification or PRS registration acceptance
is implied by the structural check.

Owner copies:
`/Users/juanpabloleoni/Downloads/PureSee-Odyssey-local-test/output/`.
Complete final local run ZIP:
`/Users/juanpabloleoni/Downloads/PureSee-Odyssey-local-test-entire-run.zip`.
The final local run is `.scratch/puresee-local-test/run-checked`.
Fresh Hermes generation and its final run ZIP review remain the confirmation.
