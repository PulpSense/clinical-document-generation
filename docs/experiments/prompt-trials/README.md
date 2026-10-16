# Prompt-only development trials — 16 October 2026

The owner requested prompt improvement and review of generated section text
before document construction. The same Codex agent drafted and manually
reviewed ten target sections for each of three scoped development inputs.
No Hermes run, separate model API, subagent or independent reviewer was used.
These are writing trials and construction fixtures, not an automated model
quality benchmark or approved study sources.

Read `section-drafts.txt` for the thirty drafts. Each `*.request.json` saves the
source projection, effective retained n8n messages, corrections and current
section contracts. Each `*.response.json` saves Codex's actual section drafts.
The NEAR and COMFORT projections contain selected facts from the linked study
inputs; they are deliberately scoped to the ten targets, not full extractions.
The sparse case is self-contained. `receipts.json` records file hashes and
execution provenance. All 22 original n8n nodes remain unchanged.

| Case | Branch and family | Targeted manual review |
| --- | --- | --- |
| NEAR | Prospective / Advarra | Screening interval remains only in exclusion; endpoint groups stay distinct; three visits and windows preserved; injury policy becomes participant prose; withdrawal includes optional follow-up and earned payments; shared-site privacy contact stays site-neutral. |
| COMFORT | Ambispective / Sterling | Existing records are separate from future contacts; telephone contact has no acuity or saliva test; saliva occurs once; genetic results are not returned while vision results are offered; finite authorization and specimen destruction remain distinct; no treatment assignment is invented. |
| Sparse survey | Prospective / Sterling | The supplied inclusion restriction stays in inclusion once; no extra contacts, results policy, retention term, payment or injury payer is invented; authorized fixed privacy, withdrawal and injury language remains available. |

The initial draft review exposed the response format's ordering constraint:
paragraphs render before lists. Exploratory endpoints now occupy their own
labeled final list group, rather than interrupting a secondary-list introduction.
The retained n8n prompts still supply the writing baseline. Target corrections
override unsupported example obligations, including extra safety visits.

## Construction findings

Prospective Advarra previously omitted injury drafting and later inserted raw
source injury text. Both families now request injury and withdrawal drafts.
Assembly retains their participant wording and the authorized voluntary-language
paragraph. It no longer replaces study-completion prose with the raw timeline,
or appends a rescheduling sentence when a draft already owns that policy.

Shared consents list each site's contacts; Advarra's address row lists all sites.
Explicit participant duration is separate from appointment length. Source intake
owns concise synopsis fields, correct eligibility placement, activity/qualifier
separation and planned completion versus early termination. Already approved
malformed source rows are not silently rewritten during document generation.
To retest those intake corrections, start from the original input and approve
the newly prepared Source of Truth.

The layout check additionally exposed Sterling annotation typography leaking
into generated risk/background prose and inconsistent genetic-clause typography.
Generated prose now uses the selected family's retained body exemplar; the
conditional genetic clause keeps its exact authorized wording and heading style.
Sterling IRB merge fields remain intact. Advarra's signature spacer padding is
compacted without deleting signature lines or consent wording. A formatting-only
copy of the uploaded NEAR ICF went from seven pages to six, with unchanged
nonblank text. The final family previews are local QA material, not deliverables.

## Repeating this workflow

1. Select affected sections and varied source cases, including a sparse case.
2. Build their payloads with `generation_only_prompt_payload` and current
   section contracts. Save the exact source and instructions before drafting.
3. Draft native paragraph/list responses directly from those requests; record
   the actual producer and whether execution was manual or through an API.
4. Review facts, qualifiers, section ownership and readability against each
   input. Adjust corrections and regenerate the affected text as needed.
5. Check the saved responses through the existing response-shape adapter. After
   prose review, test affected construction paths and inspect minimal rendered
   family fixtures. Tests establish transport and preservation, not model quality.
6. Run the complete study on Hermes as the final integration test.

This is a development workflow. It adds no runtime review worker, content gate,
visual review or repair loop. Linux dependencies and the six-script inventory
remain unchanged. Older reviewed-workflow test modules importing the removed
`quality` module cannot collect in this experiment; active generation and the
focused construction regressions are used instead. The full suite was not run.

The focused selection passed 50 tests; the 17 affected checks passed again after
the final signature pagination adjustment. Skill validation and whitespace
checks passed. Final local previews contained six Advarra pages and five
Sterling pages, all visually inspected. Complete generation on Hermes remains
pending.
