# Spec #103 cleanup boundary (#104)

This is the current runtime boundary; #91 and the prior rule-migration/fingerprint inventories are historical. #103 supersedes conflicting semantic authority in earlier ADRs (see ADR 0022).

| #92 implementation / existing behavior | Decision |
| --- | --- |
| `rule_authority.py` registered lexical source-coverage condition | Removed; there is no condition authority registry. |
| `quality.py` rule-bound mandatory uncertainty decisions | Removed; reviewers supply independent judgments without adjudicating every heuristic. Legacy empty evidence fields remain compatible. |
| `quality.py` deterministic clinical, consent and presentation output validation | Removed from runtime gates. Existing standalone legacy assessment helpers are developer-only diagnostics; ordinary generation/publication does not invoke them. |
| `drafting.py` implementation fingerprints and request/source bindings | Keep exact implementation, approved-source and request identity; remove registry from package identity. |
| Draft acceptance | Keep response shape, section inventory, nonempty values and evidence-reference/quote provenance. Remove lexical coverage, numerical inference, repetition, minimum-length and output boilerplate-text judgments. |
| Intake | Keep obligatory value presence, supported branch/template and usable typed schemas. AI handles timeline/site/sample-size/source-alias meaning and conflicts; parser inability does not veto present inputs. |
| `prs_xml.py` | Keep XML parse, client-derived element shape/order and source-driven repeated cardinality. Remove clinical scalar/source equality, vocabulary interpretation and screening-interval semantic gates. |
| `rendering.py`, `quality.render_pages` | Keep readable OOXML, actual renderer/page inventory and hash evidence. AI reviews generated text, consent applicability, TOC placement and blank/orphan/layout concerns. Template insertion remains deterministic. |
| #92 tests | Replace rule adjudication expectations with public generation/delivery boundary tests across all five families. Keep source/request/render/delivery integrity tests. |
| `tests/offline_reliability_gate.py` producer fingerprint enforcement | Removed; ordinary developer test command and Linux office discovery remain. Historical JSON audit is explicitly retired. |
| #92 inventory documentation | Superseded history, not an acceptance checklist for #103. |

## Implemented integration boundaries

#105 implements intake and drafting instructions, independent review and source handoff. #106 replaces the old recovery owner/edit-surface machinery with general tools. #107 integrates review-only delivery and skill guidance. #108 reconciles the selected offline test list and historical semantic-rule tests with the new lifecycle and prepares the owner-run Linux evidence plan. See [implementation results](spec-103-implementation-results.md). Tests that explicitly expect phrase/numeral/word-count/consent/layout code vetoes or rule resolutions are obsolete, not reasons to restore those gates.

Focused boundary tests use controlled rendering and reviewer adapters. They prove routing, file integrity and identity preservation; they do not establish live AI judgment, production readiness or elapsed-time claims. No installation, activation, paid run or full suite was performed.
