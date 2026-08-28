# Editable Source-of-Truth Markdown

`prepare` creates the reviewer-facing Markdown file under `<run-dir>/reference/`.
Every editable value is enclosed by a stable marker pair:

```markdown
<!-- field: study.title -->
Approved study title
<!-- /field -->
```

Lists use Markdown bullets and repeated structured records use Markdown tables.
The reviewer may change values, but must preserve every generated marker exactly.
`meta.icf_template`, Protocol date, and blank optional Protocol version are
visible controls. The date defaults to the preparation date; an unknown version
stays blank.

The Markdown is input-only. It contains approved clinical, administrative,
contact, facility, endpoint, procedure, analysis, safety, privacy, and PRS facts.
It never contains generated narrative, operational approval state, or a second
placeholder-shaped model.

Approval binds the exact Markdown hash, canonical parsed reference, selected
client templates, contracts, boilerplate, and implementation hashes into a new
write-once revision. Editing the Markdown or changing generation resources
requires a new approval/revision. After approval, no additional source questions
are allowed; section drafting and verification proceed through Hermes request
and response JSON files.
