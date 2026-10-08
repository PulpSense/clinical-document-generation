# Intake workflow

1. Preserve supplied files under the run's `input/` directory when available.
2. Translate source aliases into `reference/study.reference.json` using the
   canonical schema.
3. Run `workflow.py --stage prepare` once. If mandatory fields are missing,
   return the generated repair report in one batch.
4. Deliver the generated editable Source-of-Truth Markdown file. Do not replace
   it with chat text.
5. The reviewer edits that file and approves it once.
6. Run the production `workflow.py --desktop-operation --manual-review` adapter
   with the actual Desktop opener and parent visual reviewer as described in
   [ordinary generation](../SKILL.md#post-approval-desktop-operation). Preserve
   the original 2700-second deadline and approval across supported cause-specific
   repairs. Do not ask new source questions after approval; optional detail stays
   blank or uses listed applicable Fixed Clinical Boilerplate.
7. Require authentic independent content and every-page visual review of exact
   final bytes, then complete atomic branch delivery. Client-ready means
   `status: passed`, `stage: desktop_delivery` and `delivery.confirmed: true`,
   with every attachment hash and byte length confirmed by the actual opener.
   A passing inner generation result or review-only copy is not success.
   Cautions belong only in the Hermes Delivery Message.

The canonical approved reference never stores model prose or a legacy flat
placeholder layer. Rendering maps canonical facts and accepted section drafts
directly into the client templates.
