# Assessment presentation polish (#111)

Baseline: 75f008b4a8d9e6a21c5fe815b216446bce00c89d. This changes shared construction and authoring guidance, not a particular study or its approved source.

The assessment matrix now contains only visit/activity rows. Unique unallocated assessment, safety, timing and footnote detail is rendered as adjacent prose; narrative-only input keeps its facts without a caption or introduction pointing to an absent table. Source text is preserved by default.

The evaluation-procedures drafting request offers optional assessment_presentation edits for exact existing activity labels and notes, each with source_text, display_text and rationale. Existing schedule interpretation still owns source-to-visit mapping. Display edits change labels and notes without changing source values or X assignments. AI may omit a redundant note, clean internal source references, or remove a contextually confirmed orphan marker. Genuine numbered forms/instruments, citations, explained footnotes, units and qualifications must be preserved; uncertain numbers remain. There is no automatic number stripping or lexical publication gate. Missing optional polish does not fail drafting or publication.

The optional edits pass through authenticated ingestion and model assembly. Unique edited notes survive section-body replacement. Source-binding/shape checks remain code-owned; semantic correctness remains with final independent AI review and the existing native repair route. A substantive mistaken qualifier can be repaired in the DOCX and independently reviewed without reconstructing the same defective draft. Retrospective Protocols have no Section 15 matrix; shared standalone drafting guidance applies to all three study types.

## Validation

The main focused sweep passed 185 tests across assessment presentation, runtime efficiency, drafting examples, reviewer transport, general document repair and Desktop delivery. An additional four public lifecycle cases passed for presentation-authored substantive defects, native DOCX-only repair, fresh content review and delivery across both templates for Prospective and Ambispective. Another 23 selected schedule/assembly cases passed. These are controlled local adapters, not live Hermes quality certification.

The final installation-sized rerun passed all 50 tests in 194.35 seconds across tests/test_assessment_presentation.py, tests/test_drafting_examples.py and tests/test_general_document_repair.py. This reruns a subset of the coverage above.

Two synthetic Protocols were rendered with the bundled office renderer; affected Section 15 page images were inspected for matrix-with-prose and narrative-only layout. User documents were not modified. Compilation and whitespace checks passed. Standards and Spec reviews reported zero material findings; an initially suspected recovery-hash gap was traced to an older path rather than the active native repair route, which the added lifecycle tests exercise.

An exploratory probe of older shared-projection, contextual-output and source-routing files exposed obsolete semantic-validator expectations. On the unchanged baseline, 31 checks in those files failed and 115 passed. Twelve of those baseline failures belonged to the schedule-detail tests updated for the new prose presentation; the other 19 pre-existing failures are not counted as passing. No production check was disabled or removed to hide them.

No full suite, acceptance corpus, paid certification or live Hermes run was performed. Linux runtime dependencies were unchanged. Hermes must run staged and active installation rendering smokes on its Linux host.
