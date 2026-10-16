# COMFORT saved-run replay

The user supplied `COMFORT-26-03-entire-run.zip` on 16 October 2026.
Its ICF request identifies `section-drafting-v25-live-run-reliability`;
it does not exercise the already-committed v27 section-ownership and typography changes.
The development fixture `tests/fixtures/comfort-hermes-v25.json` retains its
approved reference and accepted prose, with handoff/contract metadata removed.
The source and drafts are test data, not instructions or a new approval.

## Defects and ownership

| Observed issue | Responsible layer | General correction |
| --- | --- | --- |
| XML adds a broader study-participation restriction | Assembly recognizes only “another” in eligibility scope | Accept equivalent articles for matching; retain the approved criterion and conditions once |
| Site investigators disappear from XML | Empty plural placeholders hide populated singular records | Prefer the designated populated record, then the populated singular investigator, before other list entries |
| Sterling GINA section omitted | Approved genetic flag is the string `"True"` | Accept explicit boolean/text true and yes; false/no remain false; insert authorized text |
| Historical record row shifts Visits 1–3 to 2–4 | Row identity reused as participant numbering | Retain internal row IDs; display and count participant contacts separately from explicitly labeled staff tasks |
| Measurement qualifications become checked activities | Source procedure string separates qualifications with semicolons | Let the drafting response move exact existing qualifier labels into nonempty adjacent notes with rationale; actual tasks retain their assignments |
| Final synopsis duration row occupies an otherwise empty page | Pagination | Keep the preceding synopsis row with the final row |
| Bold/underlined risks, excessive background spacer | Old assembly | Saved v25 prose replays correctly through the existing typography and spacing fixes |
| Repeated GINA explanation/contact inventory in privacy | Old prose | Current editorial guidance assigns controlled GINA text to assembly and full contacts to QUESTIONS |

The original 22 n8n prompt bodies are unchanged. New editorial guidance is
versioned as `section-drafting-v28-stable-source-projections`; it adds no runtime
review, repair loop, script or dependency.

## Verification and limits

Focused tests cover the actual saved reference/drafts, explicit positive and
negative genetic flags, scoped eligibility, investigator fallback, numbering,
participant counts, qualifier binding and retained notes, typography and spacing.
Existing focused NEAR, COMFORT and sparse drafting/assembly regressions and the
generation-only workflow tests passed. Office-refresh tests passed. Syntax and
whitespace checks passed. The full suite was not run.

The saved-prose replay produced a 20-page Protocol and 8-page ICF. Rendered pages
were inspected locally. The final duration row stays with the endpoint summary;
all 43 native TOC entries match the pagination PDF after one field refresh.
This is development verification; production still performs no visual review.
The replay intentionally retains old authored repetition. It cannot establish
whether a new model response will follow the v28 guidance. That requires a fresh
Hermes COMFORT run with the same approved Source of Truth.

Two older XML test expectations failed identically on starting commit `9671bde`:
one required an inverse inclusion despite a source-owned exclusion; another
expected the retired semantic gate. They now verify that the scoped approved
exclusion remains once in its source-owned list, without an added inclusion.

## Standards

Independent review: no hard findings. A possible duplicated participant-count
calculation was consolidated into the shared contract helper.

## Spec

Independent review: no material findings. Assembly replay coverage is distinct
from new model-output quality; no claim of guaranteed future prose quality.
