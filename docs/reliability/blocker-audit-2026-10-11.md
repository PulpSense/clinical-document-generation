# Blocker and recovery audit — 2026-10-11

Status: read-only code audit; redesign confirmed by the owner and specified in GitHub issue #91. Baseline: `a536a2a` on `codex/review-contract-root-causes`. This report is a gap analysis, not a replacement runtime registry or a claim of exhaustive behavioral certification. No implementation or full-suite run was performed for this audit.

## Goal and scope

Complete approved inputs should produce the required document package through verified repair of real defects or evidence-backed resolution of false positives. Scope covers Prospective/Advarra, Prospective/Sterling, Ambispective/Advarra, Ambispective/Sterling, and Retrospective Protocol-only. Source approval, artifact integrity, fresh review, and exact-byte delivery remain authoritative.

## Findings

### 1. Semantic adjudication is available only to selected producers

`scripts/quality.py:75` declares 11 eligible uncertainty codes. `_lexical_review_cautions` at line 5974 accepts warnings with those codes. `quality_report` at line 7175 retains other deterministic findings as blockers. A generic passing independent review does not resolve such a blocker.

This creates a routing failure: a fallible prose matcher can retain publication authority even after the source and final passage have been reviewed as faithful. Changing the prose repeatedly does not address that authority mismatch.

| Producer family | Current limitation | Evidence in `scripts/quality.py` |
| --- | --- | --- |
| Retrospective timeline | Bespoke phrase/ordering matcher blocks without adjudication | 3895, 4906 |
| Unsupported template/example claims | Phrase presence and absence from serialized source do not consider context or negation | 4741, 4964 |
| Observational ICF “clinical trial” | Phrase alone can trigger, including a denial | 4982 |
| Consent instructions | Only three accepted substrings establish instruction | 5032 |
| Substantive body | Token threshold can mistake a valid short answer for missing content | 4793 |
| Source-mode sections | Normalized literal containment; exact-copy authority needs explicit classification | 4807 |
| Sterling clauses | Exact legal text, source-value checks, block counts and semantic proxies share a blocking route | 4175–4372 |
| Advarra site address | Token/alias checks depend on address representation and detected block | 3977–4059 |
| Bibliography, sponsor concatenation, computed duration | Literal/projection checks need separation of exact data obligations from presentation assumptions | 3955, 4061, 4075 |
| Required headings, tables, signature markers | Structure obligations and phrase-based proxies need separate rule identities | 4699, 4943 |
| Screening interval | DOCX evidence route differs from PRS construction/disagreement route | 4984–5030 |

Existing review decisions do bind approved source, exact current passage, artifact and rule evidence, with explicit faithful/confirmed-defect/source-clarification dispositions (`quality.py:6066–6191`). That mechanism is useful but does not cover every semantic producer.

Missing-content findings also need a different evidence shape: a missing passage cannot quote itself. Current caution/decision validation expects an existing passage (`quality.py:6021`, `6083`). The section inventory and allegedly missing approved fact need to provide the anchor.

Intake also contains fallible semantic inference: timeline/design and site-count contradictions use parsing heuristics (`scripts/contracts.py:2240–2316`, `2536`). Distinguish actual missing/conflicting input from inability of a parser to compare complete representations.

### 2. A recovery owner does not establish an executable repair

| Recovery surface | Capability gap | Evidence |
| --- | --- | --- |
| Localization | Missing native-shell/XML locations receive clarification; present but ambiguous, unregistered or unusable locations can fail later | `quality.py:6126`, `output_recovery.py:35`, `drafting.py:647` |
| Generated DOCX | Registered scalar spans or unique body paragraphs are editable; arbitrary tables, headers, footers and protected clauses are not generally covered | `drafting.py:609–685` |
| XML | Existing scalar leaves are editable using scoped approved scalar values; missing nodes, structural shape, attributes and derived transformations are not general capabilities | `output_recovery.py:35–136` |
| Deterministic reconstruction | Rebuilding with the same mapper can reproduce the same defect; unchanged reconstruction can terminate as capability gap | `workflow.py:8610–8677`, `8893` |
| Repeated drafting | Three completed attempts/review sets can terminate despite a persistent semantic false positive | `workflow.py:8021–8106`, `8536` |
| Native editor | Proposal caps and invalid post-overlay XML can stop rather than choose another strategy | `workflow.py:8633`, `9222` |
| Visual repair | Registered layout ladder and reinspection exist; unknown surfaces lack a general alternate repair | `workflow.py:8269`, `8405`, `8680` |
| Reviewer transport | Repeated schema/response failures can stop review of otherwise correct artifacts | `workflow.py:4690–4860` |
| Pre-review checks | Some deterministic failures prevent review requests from being created, so adjudication cannot inspect them | `workflow.py:8974–8998` |

Hash/approval-lineage validation and exact-byte delivery are different: they establish which source, artifact and review are being used. They should not be waived by semantic judgment (`workflow.py:8320`, `9050`, `4045–4115`, `4970–5038`).

### 3. The inventory and tests provide narrower evidence than the reliability goal

The inventory audit passes for 186 function records. Its scanner selects top-level functions in `scripts/*.py` using literal markers, named helpers, and the output-recovery module. It fingerprints functions and validates metadata and named paired tests (`tests/offline_reliability_gate.py:42–150`). It does not enumerate every emitted condition or prove each condition reaches an implemented repair/adjudication route.

The lexical-veto guard recognizes constant code names containing lexical/repetition/word-goal. A semantic matcher with another name, a dynamic finding or a nested rule can escape that guard. Family-level paired tests can satisfy metadata without exercising every condition.

Local lifecycle tests exercise real workflow and DOCX/XML construction, but use controlled reviewer/model adapters and simulated rendering (`tests/test_clean_delivery.py:18–42`, `83–106`). These demonstrate control flow and binding, not live model judgment or page quality. CI selects focused files rather than the complete offline selection (`.github/workflows/presentation-delivery.yml:21–34`). Live campaign collection verifies reported bytes but cannot alone establish semantic correctness or complete failure history.

## Proposed acceptance requirements — not yet implementation decisions

1. Give every emitted condition a stable rule identity, authority class, applicable document families, evidence contract, and executable resolution route. Separate objective invariants from semantic evidence proxies within mixed functions.
2. Route semantic findings through source-grounded adjudication before unnecessary repair and after repair. A specific faithful decision may resolve an unchanged artifact; a generic pass cannot.
3. Validate usable localization and repair capability before spending a reconstruction attempt. Treat unusable locations as clarification, not proof of an unrepairable document.
4. Cover source-preserving transformations and required structural repairs explicitly. Do not assume scalar replacement is a universal editor.
5. Escalate stalled recovery by cause: real unresolved defect, likely matcher false positive, ambiguous source, unusable location, unsupported edit, or reviewer transport failure. Repeated rewriting alone does not establish a clinical defect.
6. Test each semantic rule with faithful variation and real corruption: paraphrase, omission, swapped values/relations, negation, ambiguous location, stale decisions, failed repair and new defects introduced by repair. Apply across each applicable family.
7. Demonstrate repairs on changed final bytes with relevant rechecks and fresh independent review. Demonstrate false-positive resolution against unchanged bytes with exact evidence binding. Verify package delivery in both cases.
8. Add negative audit tests for innocuously named, dynamic and nested semantic blockers. New rules must not silently acquire publication authority without a tested route.
9. Report controlled local evidence separately from live model/render evidence. Exercise both repair and false-positive resolution live across the five families and varied inputs before broad reliability claims.

## Open decisions

The owner confirmed the first grilling round:

- Stalled repair switches strategy to independent adjudication within the existing operation deadline. The adjudicator receives the approved source, exact passage, failed check and prior attempts.
- Readiness requires local audit coverage plus live repair/false-positive exercises across all five branch/template families and varied inputs.

The owner confirmed the second round:

- Recovery may repair generated paragraphs, tables, headers and XML structure beyond registered scalar fields, preserving approved facts and required template/legal text. Changed documents require rerendering, relevant checks and fresh independent review.
- A confirmed substantive defect that remains unresolved at the operation deadline results in a complete, clearly distinguished review-only package, with explanation outside the clinical documents. Proven false positives and harmless editorial differences do not cause that status.

This resolves ADR 0021's pending review-only delivery choice for this redesign. Source-identity or corrupted/unusable-file failures are not converted into verified review copies by this decision. The owner confirmed the consolidated design on 2026-10-11. The implementation specification is `docs/plans/verified-recovery-and-adjudication-spec.md`, published as https://github.com/PulpSense/clinical-document-generation/issues/91; its delivery-policy integration includes reconciling ADR 0021 and CONTEXT.md.
