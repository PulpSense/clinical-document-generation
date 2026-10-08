# Retrospective n8n/Hermes handoff

Translate upstream n8n aliases into the canonical reference described in
`reference-schema.md`, then run only `scripts/workflow.py`. Do not persist a
parallel placeholder-oriented model.

Retrospective intake uses its own mandatory field contract. It may describe a
multisite study while providing the one required facility record used by the
client template; the workflow therefore does not compare the declared site
count with that single required facility row.

After the reviewer approves the editable Source-of-Truth Markdown, Hermes runs
the applicable Protocol section batches with targeted retries. Retrospective
runs do not create an ICF or PRS XML. A passing run atomically publishes exactly
`output/protocol.docx` after deterministic and independent rendered-page/content
verification.

Follow [ordinary generation](../SKILL.md) through the production Desktop
adapter after approval. Client-ready requires `status: passed`,
`stage: desktop_delivery`, `delivery.confirmed: true` and actual opener byte/hash
confirmation of the exact reviewed Protocol. A passing inner generate result
is insufficient.
