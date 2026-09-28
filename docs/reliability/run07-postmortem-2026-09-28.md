# Run 07: Sterling heading repair and two source-ownership omissions

## Evidence and cause

The fresh Hermes run used commit `fd0f90ccabcf3e5dd7dce0098cef56b4e60ba53b` and the same approved source hash `b481bd8b1cbccd1924aa3a842ea0f948f4e526f42cfdd825f55d60e5f404c441`. It blocked at `layout_repair_classification` after 2,094.503 seconds. The final ICF visual reviewer found the risk heading orphaned on page 3 while its opening paragraph began on page 4. The PDF visibly says `POTENTIAL RISKS, SIDE EFFECTS, DISCOMFORTS, INCONVENIENCES`.

The preserved DOCX holds `SIDE` inside a `w:smartTag` child of that heading. LibreOffice renders the child, but `python-docx` omits it from `Paragraph.text`, yielding `POTENTIAL RISKS,  EFFECTS, DISCOMFORTS, INCONVENIENCES`. The layout planner correctly kept the exact visible reviewer label; the Word-native repair matcher searched the incomplete parser text and raised `LayoutRepairTargetError: ... found 0`. This is an input-representation mismatch across the PDF reviewer and DOCX repair tool, not a missing clinical input. The prior focused 518-test gate did not include this layout test file or a smart-tagged heading fixture.

A minimized smart-tag regression failed with the exact exception before repair and passed afterward. The matcher now reconstructs visible heading text from OOXML `w:t` nodes and still requires exactly one matching heading; it does not guess aliases or apply a repair to an ambiguous heading. Applying the selected heading-cohesion repair to the preserved DOCX and rendering locally with LibreOffice placed both heading and first risk paragraph on page 4. This local render is diagnostic evidence, not an accepted client artifact or substitute for Hermes every-page review.

## Findings that would remain after the heading repair

The same second review set had two substantive content findings. Protocol Section 8.2 omitted approved `statistics.bias_minimization` detail about common testing conditions, predefinition of outcomes/methods, and limits on interpreting nonrandomized cohort differences. The `protocol-foundations` drafting request did not include that statistics field in its approved input or section checklist. The ICF PROCEDURES omitted the approved continuous adverse-event and device-deficiency collection period and reporting between scheduled visits. The ICF request had the procedure source family, but the `icf.procedures` section checklist did not name `procedures.adverse_events`. These are real omissions and remain blocking until fresh drafts and independent reviews pass.

The section contracts now assign these optional approved facts to their owning sections, with explicit content expectations. The foundations batch includes the statistics source family so `statistics.bias_minimization` appears in both approved input and its checklist. When either optional fact is absent, drafting does not invent it or demand evidence that was not supplied. A local request-construction test checks both supplied paths and values. The ICF evidence projection retains the continuous reporting obligation while removing a redundant list of scheduled review months from a narrow "not the only time" clause; the visit schedule still owns those month values. This avoids a lexical drafting rejection when a clear participant-facing sentence describes reporting between visits without repeating the same visit numbers. No source approval or clinical source data was changed.

## Prevention and limits

The focused developer gate now includes layout correction and run 07 source-ownership regressions. The code-owned layout matcher is fingerprinted in the blocking-check audit. This closes the precise Word/PDF heading mismatch and routes the two observed omissions into the draft contracts. It does not prove that a model will express those facts well, that all other templates lack hidden Word markup, or that a fresh Hermes run will pass. Keep substantive content findings blocking and perform a fresh full content and every-page visual review of any new candidate.

## Verification

- The packaged Sterling template contains the nested `SIDE` token. A minimized `w:smartTag` test reproduced the exact zero-heading exception before the matcher change and passed afterward. An extra-label negative case still fails closed.
- On the preserved candidate, the selected heading-cohesion repair resolved the target and a local LibreOffice PDF placed the risk heading and first body paragraph together on page 4. The original PDF placed them on pages 3 and 4.
- Fresh request-construction tests show `statistics.bias_minimization` and `procedures.adverse_events` in their owning section checklists and approved input, and exclude both when not supplied. A scoped evidence test confirms that patient-facing continuous reporting can pass drafting validation without repeating scheduled visit numbers.
- The explicit focused offline gate passed **564 tests in 116.82 seconds** across 24 selected test files, with no stale blocking-check audit fingerprints. No full suite, live model calls, certification corpus or client generation was run locally.
