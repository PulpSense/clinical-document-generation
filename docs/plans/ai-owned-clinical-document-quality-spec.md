# Spec: AI-owned clinical document quality and repair

Status: published as [GitHub issue #103](https://github.com/PulpSense/clinical-document-generation/issues/103), labeled `ready-for-agent`. Implementation tickets: #104–#108.

## Outcome and scope

Replace #91's per-rule adjudication and custom recovery architecture with a simple workflow: complete intake, one Source-of-Truth approval, generation, independent AI review, AI-directed repair with general tools, final review, complete delivery.

Supported families remain Prospective/Advarra, Prospective/Sterling, Ambispective/Advarra, Ambispective/Sterling, and Retrospective Protocol-only. Prospective and Ambispective require Protocol DOCX, selected ICF DOCX and PRS XML together; Retrospective requires Protocol DOCX only.

This spec supersedes #91 and its unimplemented tickets #93–#102. Completed #92 remains historical implementation; cleanup must inspect its actual changes before selectively retaining or removing them. This decision replaces conflicting semantic-gate/recovery requirements in earlier specifications for this work. Existing #89/#90 remain separate evidence work; reconcile their acceptance with this design rather than rebuilding retired gates to satisfy old criteria.

## Ownership boundary

| Responsibility | Owner |
| --- | --- |
| Installation, dependency/runtime identity, fonts and renderer capability | Code |
| Required-input checklist definition, intake data schema and approval state | Code |
| Interpretation of obligatory-input completeness and actual source ambiguity | AI using the existing checklist |
| File readability/package integrity, required document inventory, source identity, exact reviewed-byte delivery | Code |
| DOCX assembly, template insertion, styles, tables and rendering | Software tools operated by AI/workflow |
| XML syntax, supported structural contract, element order/cardinality and serialization | Code |
| Study meaning, factual fidelity, completeness of substantive content, consent applicability, quantities/relationships, visual usability | AI |
| Drafting, independent content/page review, deciding whether a concern is real, and correction | AI using general document tools |

Code may validate that obligatory fields have values and that the input schema is usable. It must not reject coherent input because a parser fails to interpret a timeline, unit, site representation or paraphrase. AI asks one consolidated question for actually missing obligatory facts or unresolved source conflicts; optional inputs stay optional. Preserve one explicit approval and the approved source unchanged throughout generation/repair.

## Normal workflow

1. AI interprets source using the branch's existing obligatory-input checklist, resolves actual missing/conflicting facts, and obtains one approval of the Source-of-Truth.
2. AI drafts source-grounded sections with concise section-specific instructions, evidence, section ownership, applicable consent/template language and cross-document relationships. Deterministic assembly remains useful; complete inputs need not be verbose inputs.
3. Build the complete candidate and render each DOCX with the supported office renderer and existing release-owned page renderer. Code establishes file usability, source identity and XML structure.
4. Run independent AI content review and every-page visual review concurrently once their evidence is available. Content review covers Protocol, ICF and XML values against approved source, substantive omissions, unsupported claims, quantities/units/relationships, consent and cross-document consistency. Visual review inspects actual page images for readability and template/layout defects.
5. Review findings include the substantive concern, approved/template evidence, actual location or missing-content anchor, and suggested correction. AI repair may reject a false concern with a source-grounded explanation; the independent reviewer reassesses disputed concerns. A generic pass cannot conceal an explicitly unresolved material finding. Stylistic preferences do not require repair cycles or client warnings.
6. AI repairs actual defects using available general DOCX/XML tools, libraries or run-local scripts. It may edit paragraphs, tables, headers/footers and XML as needed while preserving approved facts and applicable template/legal language. This requires no per-rule registry, pre-registered edit surface, typed proposal language, or custom repair engine. Keep installed skill/runtime code read-only; repair artifacts in a new candidate/work area.
7. Inspect the actual corrected files, rerun file/XML/integrity checks, rerender changed DOCX, and obtain final independent package-wide content review plus every-page visual review of the final DOCX files. Preserve accepted edits through later construction; a stale rebuild must not silently undo a correction. Reviewer independence means a separate review task from the repair author, not a required different model vendor.
8. Deliver every required file together with the correct status and exact-byte verification. Retain concise internal evidence of reviews, changes and unresolved concerns.

## Remove semantic code gates

Retire prose/content and presentation matchers as runtime blocking authorities throughout intake, draft acceptance, construction, pre-review, post-review and publication. This includes phrase matching, lexical source coverage, inferred unsupported claims or contradictions, numeral matching, word thresholds, repetition, consent phrase proxies and heuristic page-layout rules. Deterministic XML clinical-value/source-comparison heuristics are also semantic checks, even though they inspect XML.

Useful observations may remain internal advisory context if they do not add a mandatory per-finding adjudication response, hide a candidate, delay review, or cause repair/publication failure. Prefer deleting redundant matchers and their special recovery plumbing. Developer tests may inspect content and template construction; they do not become production semantic gates.

Code inserts required template-owned language deterministically. AI reviews its applicability and preservation in context. Keep template/release asset integrity checks; do not preserve generated-output exact-text/placement gates as a hidden replacement content checker. XML structural validation remains required, while AI owns the meaning and source fidelity of XML values. Do not invent an XSD requirement where the repository uses a client-derived structural contract.

Retain objective file/package, installation and trust safeguards: valid readable files, complete document inventory, supported XML structure, approval lineage, artifact/review identity, real render evidence and delivery of the reviewed bytes. Code may check review-response structure and that required reviews/pages were supplied; AI supplies the quality judgment. Technical failures receive direct tool/response feedback, not fabricated clinical findings.

## Time and delivery

Under 25 minutes is the normal end-to-end completion target, not a demonstrated promise or an approval waiver. Measure post-approval generation start through confirmed complete Desktop delivery, excluding the human wait for source approval; report clean runs and repaired runs separately. Preserve the original cross-process 45-minute operation ceiling and resume identity.

Batch findings into a repair pass, run independent reviews concurrently, and avoid cosmetic repair cycles. Use observed timings to reserve time for final rendering/review/delivery. Do not impose a universal fixed repair count, reset the deadline, or silently launch a second operation. Repeated unchanged ineffective actions require AI reassessment or an honest unresolved outcome.

- Client-ready: complete usable files, objective checks passed, final AI content and page reviews complete, substantive concerns resolved, reviewed bytes delivered. No routine warning for fixed defects, dismissed concerns or stylistic alternatives.
- Review-only: at the deadline or when no productive safe repair remains, provide the complete usable, source-trustworthy package with external notice of unresolved concerns and incomplete assessments. Never claim it passed final review. Verify its actual file hashes without fabricating review evidence.
- Unavailable: incomplete, corrupted/unreadable or source-untrustworthy files. Preserve diagnostic evidence; do not expose a partial set as a successful package.

Notices stay outside clinical documents. Preserve prior operations and distinguish a later retry from success in the original operation.

## Cleanup and implementation constraints

Inspect completed #92 (reported implementation 846a22d, integration 937f630) and the current checkout. Remove or retire rule-authority registries, mandatory per-heuristic resolution payloads, inventory enforcement and specialized recovery machinery made unnecessary by this design. Retain source/artifact/reviewer/delivery bindings independently of rule IDs. Keep only existing editing helpers that genuinely simplify general tool use; do not expand them into #91's framework.

Reconcile SKILL.md, relevant references, CONTEXT.md and ADRs with this decision. Historical specs/audits remain clearly superseded evidence. Preserve unrelated user work. Preserve Linux runtime dependencies, renderer/font contracts and installation checks; do not adapt them for macOS.

## Acceptance evidence

Use focused tests at public intake, generation, review, correction and delivery boundaries. No full suite without explicit approval; ordinary generation runs no maintenance suite.

Demonstrate: faithful paraphrases/negations/concise sections reach AI review and delivery without semantic code vetoes; real prose, table, header/footer and XML-value defects can be repaired with general tools; corrections exist in final files and survive later construction; independent final review is fresh; missing obligatory facts still receive a consolidated question; optional facts stay optional; malformed XML, corrupt files, stale identities and incomplete sets remain detected. Cover all five supported families with sparse and detailed synthetic sources. Controlled reviewer/render adapters are local control-flow evidence, not proof of live model judgment or speed.

Provide the owner a small fixed Linux run plan spanning all five families, clean runs and deliberate substantive repair exercises. Record every operation, exact candidate identity, stage/total latency, repair cycles, final status and delivered hashes; report denominators and under-25-minute results separately for clean and repaired runs. The owner performs live Hermes runs separately. Creating/implementing these tickets does not authorize installation, activation, paid runs or certification. Production readiness and timing claims require fresh live evidence on the actual candidate.

## Implementation tickets

- [ ] #104 — Cleanup implemented #92 and retire semantic code gates
- [ ] #105 — Implement AI-owned intake, section drafting and independent review
- [ ] #106 — Enable AI-directed repair with general document tools
- [ ] #107 — Integrate complete delivery, review-only fallback and concise skill instructions
- [ ] #108 — Verify the simplified lifecycle locally and prepare owner-run Linux timing evidence
