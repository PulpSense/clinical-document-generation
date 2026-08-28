# Reviewer Approval Loop

Use only the public lifecycle in `scripts/workflow.py`.

## 1. Prepare

```bash
python3 scripts/workflow.py --run-dir <run-dir> --stage prepare
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
python3 scripts/workflow.py \
  --run-dir <run-dir> \
  --stage approve \
  --approved-by "<reviewer>" \
  --source-md <edited-source.md>
```

Reviewer-edited marked values are authoritative. Do not silently correct or
reinterpret them. Parser errors, missing obligatory inputs, conflicting source
candidates, and cross-field inconsistencies block approval and are returned as
one repair report.

## 3. Approval

For an unchanged Source-of-Truth file:

```bash
python3 scripts/workflow.py --run-dir <run-dir> --stage approve --approved-by "<reviewer>"
python3 scripts/workflow.py --run-dir <run-dir> --stage validate
```

Approval binds the exact Markdown hash and creates a write-once revision with
an immutable source copy and reference snapshot. Any later reviewer-controlled
input change requires a new prepare/approve cycle.

Approval closes source intake. Do not ask the reviewer additional clinical or
document-content questions after this point. Sparse-but-complete approved input
uses only its approved evidence and the section's listed Fixed Clinical
Boilerplate.

## 4. Generate

```bash
python3 scripts/workflow.py --run-dir <run-dir> --stage generate
```

When the result is `awaiting_hermes`, complete every returned JSON request at
its declared response path and rerun `generate`. Continue until `passed` or a
truthful blocker is returned.

This loop is internal. The next reviewer-facing response after approval must be
the complete `client_outputs` package, or one consolidated technical repair
blocker after all automatic retries are exhausted.

Return only `client_outputs` after `status: passed`. Never deliver partial
documents, PDFs, page PNGs, drafts, or logs.
