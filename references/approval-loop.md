# Reviewer Approval Loop

Use only the public lifecycle in `scripts/workflow.py`.

## 1. Prepare

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage prepare
```

If the result is `blocked`, present the returned missing-input checklist and
ask the missing questions together. If it is `awaiting_approval`, attach the
actual Markdown file at `review_delivery.absolute_path`. Do not paste its
contents into chat. Preserve all `<!-- field:... -->` markers so the reviewer
can edit and return the file. Raw inputs, JSON, templates, drafts, and reports
remain internal.

Preparing documents is not approval. Stop until the reviewer explicitly
approves the generated or edited Source-of-Truth file.

## 2. Corrections

When the reviewer edits the Markdown, preserve the uploaded file and pass it to
the approval stage:

```bash
"$CLINICAL_PYTHON" scripts/workflow.py \
  --run-dir <run-dir> \
  --stage approve \
  --source-md <edited-source.md>
```

Reviewer-edited marked values are authoritative. Do not silently correct or
reinterpret them. Parser errors, missing obligatory inputs, conflicting source
candidates, and cross-field inconsistencies block approval and are returned as
one repair report.

## 3. Approval

For an unchanged Source-of-Truth file:

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage approve
```

Approval binds the exact Markdown hash and creates a write-once revision with
an immutable source copy and reference snapshot. Any later reviewer-controlled
input change requires a new prepare/approve cycle.

Approval closes source intake. Do not ask the reviewer additional clinical or
document-content questions after this point. Sparse-but-complete approved input
uses only its approved evidence and the section's listed Fixed Clinical
Boilerplate.

Reviewer identity is optional audit metadata: use `--approved-by` only when
already supplied; otherwise the workflow uses `client` without a new question.

## 4. Complete the Desktop operation

Follow [the ordinary production route](../SKILL.md#post-approval-desktop-operation):

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --desktop-operation --manual-review --desktop-opener-command <opener> --parent-visual-review-command <reviewer>
```

The adapter owns drafting, supported cause-specific repair, independent content
and every-page visual review, and atomic complete branch delivery under the
original 2700-second deadline. Ordinary generation keeps the installed release
read-only and launches no maintenance, developer suite or certification.
Return client-ready attachments only at `status: passed`,
`stage: desktop_delivery`, `delivery.confirmed: true`, after the actual opener
confirms every final byte length and hash. A passing inner generate result is
insufficient. Retained cautions belong only in the Hermes Delivery Message.
If an exceptional result provides complete review-only copies, expose them and
its findings honestly as not client-ready; this is not successful completion.
Never deliver partial documents or internal PDFs, page PNGs, drafts or logs.
