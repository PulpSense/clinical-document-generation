# Intake workflow

1. Preserve supplied files under the run's `input/` directory when available.
2. Translate source aliases into `reference/study.reference.json` using the
   canonical schema.
3. Run `workflow.py --stage prepare` once. If mandatory fields are missing,
   return the generated repair report in one batch.
4. Deliver the generated editable Source-of-Truth Markdown file. Do not replace
   it with chat text.
5. The reviewer edits that file and approves it once.
6. Run `workflow.py --stage generate`. Do not ask new source questions after
   approval. Missing optional detail stays blank or uses authorized standard
   clinical boilerplate where the section contract permits it.
7. Satisfy Hermes drafting and verification requests until the workflow returns
   `status: passed`; then return only `client_outputs`.

The canonical approved reference never stores model prose or a legacy flat
placeholder layer. Rendering maps canonical facts and accepted section drafts
directly into the client templates.
