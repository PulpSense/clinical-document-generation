# Citation ownership and form actions — 17 October 2026

Issue #119 addresses two editorial findings in the final PureSee/Odyssey Hermes
run at 08fc8ba: a bibliography inside the Introduction in addition to the
assembler-owned final REFERENCES section, and the narrative wording
“complete Complete Exit Form1”.

The shared drafting constraints now assign the single bibliography to the
assembler while preserving supporting citation numbers in section prose. A
second constraint distinguishes imperative form instructions from explicitly
identified official form titles. It preserves form identifiers and ambiguous
numerals and leaves source-owned table labels untouched. Drafting version is
`section-drafting-v33-citations-and-form-actions`; contracts, templates, assembly,
the six-script inventory and the original 22 n8n prompt nodes are unchanged.
There are no new runtime content gates, reviews, text filters or repair stages.

## Local section trials

`trials.json` retains 12 public-request-bound responses covering 13 sections or
PRS narratives. Codex authored these responses locally in this conversation
using the current prompt constraints and saved input facts. These are controlled
writing trials, not independent Hermes calls or repeated model sampling.
No DOCX, PDF or XML documents were generated.

- Seven introductions: PureSee and NEAR (prospective), COMFORT and GLIDE
  (ambispective), BREAK (prospective), RECORD and CAPS (retrospective).
- PureSee retains the supplied supporting citations [1,2] and [3], with no full
  bibliography in the Introduction. Its source bibliography is not edited.
  Inputs without references receive no invented citations or bibliography.
- PureSee visits, participant procedures and both PRS narratives use natural
  form-action wording. The Exit Form1 numeral remains because the source does
  not establish that it is a footnote. Visual test distances, defocus bounds,
  questionnaire and timing remain in the relevant procedure narratives.
- Two scoped development form-action excerpts distinguish the imperative
  “Complete Exit Form” from the explicit official title “Complete Exit Form”,
  identifier EF-12. These excerpts test wording only, not complete study methods;
  they do not alter any approved source or represent a newly approved study.

Manual comparison found no material loss in the targeted content. All 12
responses pass the public drafting-response transport. This supports the local
prompt change, not a guarantee of every future model response.

## Focused verification

The prompt-handoff checks cover every active batch for prospective and
ambispective studies in both consent families, plus retrospective studies.
They verify authenticated current requests, both editorial instructions, source
immutability and the retained n8n adapter. Writing-receipt checks cover the seven
introductions, citation retention, form wording across artifacts, and explicit
official titles/identifiers. The three historical prompt-trial transport tests
also confirm that the retained original n8n messages have not changed.

Command:
`.venv/bin/python -m pytest -q tests/test_citation_and_form_prompt_trials.py tests/test_source_owned_drafting.py::test_historical_trial_response_uses_the_production_transport`

Result: **11 passed in 2.28 seconds**. No documents were generated.

The full suite was not run. An initial attempt to include the older
`test_drafting_examples.py` stopped at collection because that test imports the
removed `quality` module; no test in that module ran and it was left unchanged.
