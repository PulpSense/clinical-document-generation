# Clinical document generation: reliability plan from the 24 September blocked run

## Desired result

For an approved, complete source on a supported study branch and contracted templates, the workflow produces the complete Protocol, ICF, and PRS XML set with source-grounded clinical prose, Brad's editorial rules, and usable Word layout. It resolves routine construction and pagination defects inside the same run. It asks for source clarification only before approval when an obligatory fact is genuinely missing or ambiguous. It continues to withhold a package if a material clinical error or unresolved visual defect remains.

The captured run used commit `90fce28ef318aeffffe08f5c984cb18a2fec701d` and revision `r-43538315b81e`. This plan records the diagnosis and release criteria; code changes are tracked separately in the repository.

## Implementation status

The first release candidate corrects the Sterling merge-field audit, projects and validates complete US site addresses in PRS XML, adds a governed Section 15 opening repair, accepts plain-language Sterling PURPOSE wording, and lets Statistical Methodology summarize methods by outcome group without repeating the endpoint inventory. Focused regressions cover these paths. A local LibreOffice render of the captured Protocol opening showed the heading and table on the same page without a new blank final page.

The release criteria below remain open until a fresh Linux Hermes run with the approved source completes all three artifacts and the final bytes pass content and every-page visual review. The broader editorial corpus, failure injection, and timing work are follow-up release-hardening tasks rather than claims established by the local replay.

## What this run proves

- The approved reference contains `sites[0].facility.address` as one full string: `300 Test Clinic Road, Test City, New York 10003, USA`. The candidate files were built and rendered. Structural reports passed, but independent review found missing PRS location components.
- The Sterling ICF deliberately retains the IRB's first-page merge fields (`«Address»`, `«City_State_ZIP»`, and related fields), following the template instruction and `SKILL.md`. `quality.audit_source_surfaces` nevertheless requires the literal supplied address at that destination. It reported a construction defect which the layout router treated as an unknown visual check. This is a false positive caused by conflicting authorities, not missing source data.
- The PRS builder projects structured city/state/ZIP/country fields. With only a full address string, those fields were empty. Its validator compared the XML only against structured source components, so the candidate passed deterministic XML validation and the independent reviewer found the omission later. This is a real mapping and validation gap.
- Protocol Section 15's heading and introduction are on page 10; the caption and Schedule of Assessments table start on page 11. The visual finding is valid. `artificial_pagination` is configured to fail closed and has no targeted repair for this heading-introduction-caption-table pattern.
- The first review also retained two content findings: repeated endpoint inventory in the statistical methodology section and a Sterling PURPOSE section lacking an explicit hypothesis and primary-endpoint statement. They were not resolved because classification stopped first.
- The operation stopped after about 563 seconds (9.4 minutes), with about 35.7 minutes left of its 45-minute ceiling. Drafting and retries consumed about 348 seconds; independent verification about 186 seconds. This run was blocked by repair coverage, not by timeout or API limits.

## Implementation sequence

### 1. Make one source-to-artifact contract for each field

Add a versioned mapping for approved source facts that states where each fact must appear, where it must *not* appear, and whether a template owns the destination. Sterling first-page merge fields must have a `preserve_irb_merge_field` disposition; the ICF audit should check the exact expected tags and their placement, rather than require substituted study values. Protocol and Advarra destinations continue to require actual source values. The independent content-review request must receive the same family-specific policy so its instructions do not contradict construction.

**Proof:** replay the captured ICF and assert that its intentional merge fields pass, while a deleted, altered, misplaced, or leaked study value fails. Compare this against the supplied Sterling template comment and the rendered first page.

### 2. Normalize address evidence before artifact generation

Store a full display address plus explicit city, state, postal code, and country components in the approved reference when the source supplies them. Preserve the original full string and provenance. Parse clearly delimited addresses conservatively; mark uncertain components for resolution *before* source approval. Do not silently infer an uncertain locality from a plausible-looking string. For already approved runs with an unambiguous source string, allow a deterministic, source-preserving projection without changing approval identity. If a required PRS component cannot be justified from approved evidence, report that exact gap at readiness rather than after rendering.

Make PRS validation compare generated fields against the normalized projection, including values derived from an approved full address, and add a cross-artifact source-coverage check. Do not require a street field in PRS XML if that schema does not provide one; ensure every supported component is mapped.

**Proof:** the captured input yields the supplied city, state, postal code, and country in PRS XML; flat and nested address fixtures pass; ambiguous strings are flagged before approval; dropped XML components fail deterministic validation.

### 3. Add a safe Section 15 pagination repair

Treat the Section 15 heading, short introduction, caption, and first table row as one opening block. Add a narrowly scoped Word-native `keep-with-next` repair or move that opening block to the next page. Keep the table contents, section text, styles, and template geometry intact. Classify this exact visual pattern separately from generic `artificial_pagination`, which can still fail closed when it lacks a safe target. Repair only after a reviewer identifies the exact section and page, then re-render and inspect the affected pages and final document.

**Proof:** on the captured candidate, page 10 no longer ends with the Section 15 introduction separated from its table. Check that the table still fits, no new blank or clipped page appears, and unrelated headings/tables are unchanged.

### 4. Finish all repairable findings in one governed cycle

Route construction, drafting, and layout findings independently so an unsupported or misclassified item does not hide other repairable findings. Repair the PRS mapping and targeted Protocol/ICF drafts in the same revision, then rebuild only affected artifacts. Record each finding's owner, action, before/after artifact hashes, and outcome. A truly unresolved material defect still blocks atomic delivery, but the report should enumerate every remaining blocker after available safe repairs have run.

**Proof:** inject the four captured findings together. The system performs the available repairs and reports only any genuinely unresolved items; it does not stop at the first repair-classification error or request another clinical approval for unchanged input.

### 5. Turn Brad's corrections into editorial acceptance cases

Use the corrected Protocol, his comments, the ICF template comments, and this run's content findings as a versioned rubric. For each rule, record a source example, acceptable output, unacceptable output, section owner, and severity. Include short title placement/fallback, unsupported claims, concise section purpose, endpoint ownership, repetition, study roles, ICF template-owned language, and source-grounded risk/benefit wording. Keep deterministic checks for exact facts, numbers, dates, roles, and section placement; use independent model review for semantic claims and usefulness. Redraft only implicated sections with the exact failed evidence, then review the assembled documents across sections.

**Proof:** the Brad-corrected example is accepted, his identified defects are detected, and sparse-complete inputs produce concise usable prose without filler. A reviewer checks a small blinded set of outputs for clinical sense and editorial fit before release.

### 6. Certify the complete behavior, then measure run time

Build a replayable acceptance corpus from this blocked run and the prior Brad cases, with sparse and rich inputs across all supported branch/template combinations. Pin expected *properties* rather than whole AI text: source coverage, no unsupported claims, protected template fields, required clauses, valid XML, complete section inventory, and layout checks. Add failure injection for missing field, ambiguous address, missing/extra merge tag, table split, malformed reviewer response, and transient API failure. Run fast deterministic tests locally on each change, then one real end-to-end candidate on the Linux Hermes environment for each document family before replacing the active skill. Keep the previous verified release available for rollback.

Measure wall time by drafting, candidate build, rendering, verification, and repair. Aim for a routine complete run inside 20 minutes and keep the 45-minute ceiling as a limit, not a normal duration. Optimize only stages shown by traces to dominate after reliability passes; reuse exact-byte evidence where safe, but require a final review of the exact released artifacts.

## Release criteria

1. The captured run completes the full Protocol, Sterling ICF, and PRS XML set with no manual source edits and no unaddressed blocking findings.
2. The complete branch/template corpus passes, including adversarial sparse inputs and the Brad editorial cases.
3. The final exact DOCX and XML bytes pass source, clinical-content, structural, and every-page visual review; Word compatibility is checked on a client-like renderer when available. LibreOffice evidence is labeled as LibreOffice evidence.
4. Every failure after admission has a precise stage, owner, source evidence, repair attempt, and remaining blocker. Missing input is never blamed for a post-approval construction defect.
5. A production run does not invoke the full test suite; release certification occurs before installing a new skill version on Hermes.

## Important decision boundary

The Sterling template comment means the IRB merge tags remain in the generated ICF. If the intended deliverable changes to a fully filled participant copy, that is a separate output mode and needs an explicit template-authority decision; it must not happen as an automatic response to the false-positive address audit.
