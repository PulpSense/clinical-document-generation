# Previous-input regression — 17 October 2026

The implementation tested is `dbe4228659abe4f34b394b52f5b6a07fa185cdb1`
(contract v2.52, drafting v32). No production code or prompt was changed during
this regression. Machine-readable receipts are in `results.json`.

## Results and exact scope

| Study | Local coverage | Result |
| --- | --- | --- |
| NEAR | Saved approved source/drafts, both Advarra and Sterling; current drafting requests; protocol, ICF and XML reassembly | No transport or DOCX content/format regression |
| COMFORT | Same replay for both families; additionally rebuilt Advarra protocol with the three reviewed concise section drafts | No regression; concise protocol 18 pages versus 19 |
| BREAK | Saved approved source/drafts, Sterling; current requests; DOCX/XML replay; concise protocol rebuild | No regression; 17-page concise protocol retains allocation, masking, diary and contact rules |
| GLIDE | Saved approved source/drafts, Advarra; current requests; DOCX/XML replay; concise protocol rebuild | Exactly the five intended XML leaf changes; concise protocol 19 pages versus 21 |
| RECORD | Original source/drafts replay isolates format stability; four local section revisions assemble a corrected full protocol | Nine-page corrected protocol retains detailed abstraction, selection, counting and access rules; references use active headings |
| CHART | Current requests and reviewed operations draft using the scoped extraction from its original input | Section-only coverage passes; complete approved source was not retained, so no full current-run replay is claimed |
| CAPS | Previously completed fresh full controlled run on the tested implementation, with all 14 Codex-authored sections | Seven pages reviewed; 21/21 TOC entries match; protocol only |

The seven saved-run/family combinations replayed 13 DOCX files and six XML
files. Every comparison baseline was verified byte-for-byte against the output
inside its original uploaded ZIP. DOCX comparison covers all Word XML parts,
excluding TOC cache contents, after one actual office pagination pass. The
unchanged drafts produce identical body content, styles, tables, headers and
footers. This establishes assembly stability; it does not newly approve the
original incomplete RECORD content.

The five GLIDE XML changes are the three explicit false flags rendered as
`No`, plus two observational arm types left empty. Element order, all other
leaf values and the retained narratives remain unchanged. The other five XML
replays preserve every leaf value and its order. Source snapshots remain
unchanged throughout.

All 63 pages of the four rebuilt protocols (RECORD, GLIDE, BREAK and COMFORT)
were visually inspected. All 150 TOC entries point to the expected heading on
the indicated page. Opening tables, contact tables, assessment matrices,
headers/footers and page flow have no new material layout findings. Minor
pre-existing repetition is outside the user's requested acceptance threshold.

## Writing and provenance

These are controlled local tests, not seven fresh Hermes generations. They use
retained sources and drafts, current public drafting requests and reviewed
Codex writing trials. GLIDE/BREAK/COMFORT reuse their saved three-section concise
trials after checking current contracts. RECORD revises design, bias,
operations and the statistical-methodology cross-reference; its four revisions
are retained in `record.revised-sections.json`. The existing withdrawal template
passage supplies that statement, avoiding a second drafted copy. No original
approved source or uploaded output was edited.

The reviewed concise sections preserve unique instruments, directions, windows,
contacts, sample handling, masking/allocation, missingness and denominator
rules. Retrospective methods stay in actual section 8.1. Prospective and
ambispective methods stay in Study Methods and Measurements. No production
semantic checker, extra generation gate or repair loop was introduced. The
six production scripts, original n8n prompt payload and templates are unchanged
by this regression work.

The local run artifacts, requests, PDFs and page images are retained under
`.scratch/latest-version-regression/`; these development artifacts are not part
of the installed skill or client delivery. The earlier fresh CAPS evidence is
in `../retrospective-method-trials/`.

## Focused checks and final confirmation

57 focused tests passed in 51.22 seconds across retrospective handoff,
retrospective assembly, generation-only workflow, PRS transport and registry
disclosure mapping. The full suite was not run, following repository policy.

Local results show no new material regression in the exercised paths. A fresh
Hermes inference run remains the external-runtime/model check; local replay
cannot guarantee future model behavior. GLIDE is the preferred final full
package check because it exercises both XML corrections and concise drafting.
If the final check is intended specifically to confirm the new retrospective
method instructions in Hermes, use CAPS instead; that run produces only DOCX
and cannot confirm XML. Retain the entire run ZIP for the final review. Do not
mark the old incomplete RECORD run or unavailable CHART replay newly accepted.
