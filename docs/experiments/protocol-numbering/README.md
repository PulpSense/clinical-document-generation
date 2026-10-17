# Consecutive protocol subsections — 17 October 2026

Issue #120 fixes the jump from 18.2 to 18.5 when the approved source supplies
neither optional termination section. Native assembly resolves included
subsections consecutively after source applicability and layout processing.
Stable section IDs and canonical template numbers remain unchanged internally.
Drafting plans list only applicable sections; cross-references use heading
titles or canonical numbers, which the assembler resolves once to display
numbers. This avoids two competing numbering decisions in drafting and assembly.

The same resolution applies to other numbered subsections and nested headings.
Explicit Section/Sections references, including lists and ranges, resolve from
the original map simultaneously. Ordinary clinical numbers remain untouched.
Visible XML spans retain run styling, hyperlinks and bookmarks. Merged-cell
paragraphs are processed only once. Section snapshots identify headings by
title within the original major section, so changing a subsection number does
not lose its stable section identity.

The linked native TOC is rebuilt from the final headings and then uses the
existing single office pagination pass. No new content/visual review stage,
repair loop, dependency or production script is added. Contract version is
`clinical-documents-v2.53-consecutive-subsections`; drafting version is
`section-drafting-v34-canonical-section-references`.

## Focused verification

33 tests passed in 34.50 seconds:

- All four optional termination combinations for prospective and ambispective
  protocols in both Advarra and Sterling families (16 combinations).
- Heading, body cross-reference, source-text presence, TOC label/bookmark and
  stable section snapshot checks; no optional clinical rule is invented.
- Split-run styling, hyperlinks, bookmarks, merged table cells and idempotence.
- Other section numbers, nested subsections and unchanged clinical values.
- Unchanged retrospective numbering and native linked TOCs for all branches.
- Prior citation/form prompt handoffs and original n8n transport regression.

Command:
`.venv/bin/python -m pytest -q tests/test_protocol_subsection_numbering.py tests/test_generation_only_toc.py tests/test_citation_and_form_prompt_trials.py tests/test_source_owned_drafting.py::test_historical_trial_response_uses_the_production_transport`

The full suite was not run. Initial new-test failures exposed trailing template
whitespace in comparisons and formatting loss when replacing an entire number
across styled runs. Comparisons now normalize outer whitespace; production
replacement edits only the changed number component, preserving the original
formatting.

## Real saved-run replay

Rebuilt only the PureSee protocol from the latest uploaded Hermes run's unchanged
approved source and actual merged drafts. This isolates numbering; it does not
represent new AI writing or rerun the preceding citation/form prompt trials.
One actual bundled LibreOffice field refresh passed. The protocol remains
12 pages, with all 44 linked TOC entries populated from actual pagination.
Study Completion is 18.3 on page 11 and in the TOC. Only rendered pages 5 (TOC)
and 11 (body heading) differ from the previously inspected Hermes protocol;
both changed pages were visually inspected. The other ten page images are
pixel-identical to the previously reviewed output. `puresee-receipt.json`
records hashes and pagination results. Local regression artifacts remain under
`.scratch/protocol-numbering/`; no new delivery package or client approval is
claimed.
