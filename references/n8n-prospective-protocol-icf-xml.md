# Prospective n8n/Hermes handoff

Treat n8n field names as intake aliases only. Translate them into the canonical
reference described in `reference-schema.md`, then use the public workflow:

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage prepare
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage approve
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --desktop-operation --manual-review --desktop-opener-command <opener> --parent-visual-review-command <reviewer>
```

The editable Source-of-Truth Markdown is the only reviewer-facing generation
authority. Do not persist a second flat placeholder map and do not call an
internal mapper directly. After approval, Hermes handles the requested drafting
batches and independent verification requests. Python owns deterministic Word
rendering, the manual client PRS XML structure, retries, and atomic publication.

Follow [ordinary generation](../SKILL.md). Reviewer metadata is optional when
already supplied. Client-ready requires `status: passed`,
`stage: desktop_delivery`, `delivery.confirmed: true` and actual opener byte/hash
confirmation of all reviewed attachments. A passing inner generation result is
insufficient. A complete prospective delivery contains exactly:

- `output/protocol.docx`
- `output/icf.docx`
- `output/study.xml`

The Protocol and selected Advarra or Sterling ICF retain their client Word
layout contracts. PRS values come from approved canonical source fields;
unsupplied optional values remain empty, while code-owned stable UIDs are
deterministically derived when the source does not supply one.
