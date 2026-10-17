# AI-owned section prose — 17 October 2026

Issue #121 implements the owner's request to remove automatic narrative
completion and rewriting. The PureSee ICF correctly said “40 adults”; a lexical
assembly check failed to recognize that wording and appended “40 participants”.
The public native-assembly regression reproduced this exact defect before the
fix and passed afterward for both consent families.

## Ownership audit

Removed from native assembly:

- The ICF enrollment completeness check and automatic enrollment sentence.
- Withdrawal sentence splitting, exact-sentence removal and fixed-paragraph
  prepending. AI now returns the complete withdrawal section, including the
  applicable supplied authorized paragraph once and every supplied policy.
- The forced generic Protocol assessment-table introduction, which discarded
  the accepted introduction. AI writes the introduction; the table and its
  approved structured note edits remain source-driven.
- Retrospective eligibility fallback prose/age sentences and automatic raw
  withdrawal-text appending to an authored enrollment paragraph.
- Generated ICF citation stripping and legacy sample-size string replacement.
- Raw-source fallback text for drafted risk, inclusion and sample-justification
  targets, plus the invented no-exploratory-outcomes sentence.
- The five-block truncation of Sterling Key Information. All accepted summary
  blocks now use the same insertion path as the other authored ICF sections.
- Injury-section boilerplate fallback. Layout restoration places the authored
  injury section without supplying a missing narrative.

Template example cleanup, IRB-name substitution and fixed-shell terminology
adaptation now run before any authored prose is inserted. Registry example
cleanup also occurs only on that raw template. It cannot remove a matching AI
sentence after insertion. All mapped ICF clinical sections use a common authored
paragraph/list insertion path, including withdrawal, payment, duration and summary.

A past-input fidelity check also exposed an existing structural loss: replacing
Protocol section 14 removed its drafted 14.1 child. Replacement now stops at
another contracted heading, preserving both bodies. The public regression failed
before this fix and passed afterward. Section 14.1 may therefore reappear in
outputs where its accepted draft was previously discarded.

Still code/template-owned, as agreed: fixed retained family clauses and
investigator agreements, source-field mappings including front matter and contact
directories, verbatim optional source clauses, source-derived tables and approved
structured notes, final bibliography, styles/geometry/signatures, section numbers
and explicit reference resolution, TOC pagination, XML structure/source mappings,
source approval identity and file integrity. Contact text built from fixed
labels and source names/phones remains a direct field mapping. These are not
new AI-drafted sections. There is no new content gate, repair loop, runtime
review stage, dependency or production script.

Contract: `clinical-documents-v2.54-ai-owned-section-prose`.
Drafting: `section-drafting-v35-ai-owned-section-prose`.
All original 22 n8n nodes/messages are unchanged; only the supplemental
withdrawal correction changes. The skill and active generation instructions now
request complete sections, replacing the former instruction to leave the
voluntary-participation paragraph to assembly.

## Verification and limits

83 focused tests passed in 46.78 seconds, covering the public ownership
regressions, prior editorial cases, subsection numbering/TOC, source-authenticated
prompt handoffs, explicit registry disclosure, front-matter alignment, ICF body
spacing and original n8n transport. Python compilation and `git diff --check`
pass. No repository typechecker/configuration is present. The full suite was not
run, in accordance with the owner's development constraint. The legacy
`test_shared_output_projection.py` imports the previously removed `quality`
module; obsolete calls to the now-removed narrative cleanup were retired in
favor of public ownership tests, but that legacy module was not counted as a pass.

The nine saved source/family cases are NEAR (both), COMFORT (both), BREAK,
GLIDE, RECORD, PureSee and CAPS. Public current requests, native assembly and
existing Protocol field refresh produced 16 DOCX files and seven structurally
valid XML files. All approved sources remain unchanged. Checks confirm retention
of 879 authored paragraphs/list blocks in their owning sections, allowing only
the separately tested structural resolution of section references and exclusion
of template-owned caption echoes. XML structured mappings and AI narratives
retain their existing implementation.

These are saved-source/draft replays, not nine fresh Hermes inference runs.
Codex locally authored seven complete withdrawal responses and seven concise
table introductions under the current public handoffs, preserving the supplied
policies and applicable fixed paragraph. The responses are retained separately.
Other sections reuse their already reviewed drafts; RECORD uses the previously
corrected method drafts and CAPS uses its controlled local run. No client source
approval or new external model benchmark is claimed.

CHART passes current request transport and native preservation of its eight
operations paragraphs using the retained scoped source. Its complete earlier
approved source is unavailable, so this remains section-only coverage.

## Final review

Independent Standards and Spec reviews of implementation commit `a1477bf`
reported zero material/actionable findings. The Standards reviewer identified a
nonblocking duplicate `icf.duration` dictionary key that overrode the more
specific enrollment instruction. A public request assertion reproduced the
override; the duplicate was removed and the surviving instruction corrected.
All 24 focused follow-up tests passed in 10.52 seconds, including public handoff,
ownership, citation/form and historical transport coverage.

Six representative documents were rendered locally (46 pages); 25 pages were
visually inspected: all PureSee Advarra ICF pages (1–5), all NEAR Sterling ICF
pages (1–7), all COMFORT Advarra ICF pages (1–6), PureSee Protocol pages 5, 10
and 11, RECORD Protocol pages 8–9, and CAPS Protocol pages 6–7. This is visual
sampling, not an all-document visual certification. The inspected pages retain
the family layouts, source contacts and signatures, complete withdrawal text,
and the restored 14.1 heading with its matching TOC entry. RECORD retains a
sparse continuation page; no pagination optimization was attempted. Rendering
remains a local development check, not a new production workflow stage.
