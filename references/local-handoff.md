# Local Handoff

Use the repository root as the Hermes skill directory and follow `SKILL.md`.

## Requirements

- Python 3.10+
- `python3 -m pip install -r requirements.txt`
- A release activated through `workflow.py --install-release`
- Preferred host applications are optional; the verified local fallback stack is mandatory

No Node.js or TypeScript is used.

## Lifecycle

Create `runs/<study>/reference/study.reference.json`, then run:

```bash
python3 scripts/workflow.py --run-dir runs/<study> --stage prepare
python3 scripts/workflow.py --run-dir runs/<study> --stage approve --approved-by "<reviewer>"
python3 scripts/workflow.py --run-dir runs/<study> --stage validate
python3 scripts/workflow.py --run-dir runs/<study> --stage generate
```

When `prepare` returns `awaiting_approval`, attach or upload the exact file at
`review_delivery.absolute_path`. Never paste the Source-of-Truth into chat; its
field markers must remain in an editable `.md` file.

When `generate` returns `awaiting_hermes`, read all returned request JSON files,
run one subagent per request, save each exact response to its `response_path`,
and rerun `generate`. Drafting batches and content/visual verification requests
may run concurrently when returned together.

If a delegated visual reviewer fails or times out, the parent inspects every
page PNG bound by that exact request and writes the response. Deterministic
checks alone never satisfy the visual request.

Only return paths in `client_outputs` after `status: passed`. Keep revision
state, requests, responses, PDFs, page images, and reports internal.

## Release check

```bash
python3 -m pytest -q
python3 scripts/workflow.py --release-gate
```

If the gate returns `awaiting_hermes`, complete every returned content and
rendered-page verification request using real content/image inspection, then
resume it with `python3 scripts/workflow.py --release-gate --release-gate-root
<evidence_root>`. The gate never fabricates visual approval and must ultimately
pass all six branch/richness cases. A missing renderer, unassessed page, invalid
response binding, missing section, unresolved token, XML mismatch, or
approval/source-hash mismatch blocks all client outputs. Renderer and tool
failures first exhaust the verified fallback stack; a complete candidate is
retained internally when the Delivery Gate remains unresolved.
