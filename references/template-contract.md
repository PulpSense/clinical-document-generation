# Client Template Contract

This skill has one template path and one public lifecycle. Do not invoke
`rendering.py`, `quality.py`, or `prs_xml.py` directly.

## Bundled authorities

Protocol and ICF Word assets live under `assets/client-templates/docx/`:

- `prospective-protocol.template.docx`
- `ambispective-protocol.template.docx`
- `retrospective-protocol.template.docx`
- `prospective-icf.template.docx` (Advarra)
- `ambispective-icf.template.docx` (Advarra)
- `sterling-icf.template.docx`

The PRS structural authority is:

- `assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml`

The retained client references used to audit those families are:

- `assets/client-templates/reference/protocol-reference.docx`
- `assets/client-templates/reference/advarra-icf-reference.docx`
- `assets/client-templates/reference/sterling-icf-reference.docx`
- `assets/client-templates/reference/prs-manual-reference.xml`

The PRS template preserves the element names, ordering, optional nodes, and
repeated-block taxonomy of the client-approved manual XML. Python may populate
or repeat those nodes, but a drafting subagent may return only the two PRS
narrative values.

## Selection

- Prospective selects the prospective Protocol template.
- Ambispective selects the ambispective Protocol template.
- Retrospective selects the retrospective Protocol template and produces no
  ICF or PRS XML.
- Prospective and Ambispective require `meta.icf_template` to be exactly
  `Advarra` or `Sterling`. The workflow never guesses between them.

Templates are bundled authorities, not mutable per-run inputs. When a client
supplies a replacement, update the appropriate bundled asset and rerun the
complete release gate. Template hashes bind drafting requests, the candidate
cache, verification evidence, and the delivery manifest; stale output cannot
be published after a template change.

## Word output and visual QA

The renderer starts from the selected DOCX asset and preserves its Word package,
section geometry, headers/footers, tables, and signature design. On every run it
reapplies the matching retained client reference's document defaults, named styles,
heading design, generated-body design, and section spacer rhythm; formatting must
not be approximated with generic font or spacing values. Protocol leaf bodies come
only from accepted Section Drafts. ICF regulatory language stays
in the selected client family, every accepted ICF draft is visible, and
study-specific prose from the authority example is removed unless the approved
source supports it. Client outputs remain standard `.docx` files.

Protocol formatting is also source-bound to the retained client reference:

- Bullets use the authority's thin marker, hanging indent, typeface, and spacing.
- The investigator completion lines remain blank and retain the authority order.
- The general-information summary retains `Test Article(s)` and does not add a
  separate hypothesis row.
- The running header uses the approved short title; when none is supplied, it
  removes the canonical study-type prefix and a leading `Evaluation of the`
  phrase from the full title. The page control stays on one line.
- The visible TOC is populated from rendered-page evidence and inherits the
  authority's `TOC 1` and `TOC 2` indents and dot leaders.
- The visit-schedule table inherits the authority's widths, borders, typography,
  `E6E6E6` header fill, and open-row border rhythm.
- `REFERENCES` is never omitted. Supplied references are preserved; otherwise
  the document states that none were supplied in the approved Source of Truth.
  The workflow never invents a citation.

The Protocol document-control date defaults during Source-of-Truth preparation
to `dd MMM yyyy` when absent. Version is reviewer-controlled and remains blank
when absent; it is never inherited from an authority document.

For QA, the workflow uses a verified host renderer in this order:

1. Microsoft Word
2. Installed LibreOffice

The renderer produces a PDF and a PNG for every page. Delivery remains blocked
unless an independent visual response assesses every page hash for clipping,
overlap, overflow, blank pages, table splits, footer collisions, readability,
duplicate sections, style consistency, headers/footers, and TOC accuracy.
Office tool failure may advance between Word and LibreOffice. PDF-to-image rendering always uses the one packaged `pypdfium2` runtime and stops if it fails. A successfully rendered
defect triggers repair on that renderer, while an unassessed page remains a
blocker—not a warning.
The deterministic gate also rejects blank and near-blank continuation pages even
when they contain a running header, footer, or page number.

## Public lifecycle

Run templates only through:

```bash
python3 scripts/workflow.py --run-dir <run-dir> --stage prepare
python3 scripts/workflow.py --run-dir <run-dir> --stage approve --approved-by "<reviewer>"
python3 scripts/workflow.py --run-dir <run-dir> --stage validate
python3 scripts/workflow.py --run-dir <run-dir> --stage generate
```

Continue `generate` whenever it returns `awaiting_hermes`, placing each exact
JSON response at the request's declared `response_path`. Publish only the paths
returned in `client_outputs` after `status: passed`.
