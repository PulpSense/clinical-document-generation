# Local Handoff

Use the verified candidate or activated Hermes skill root and follow `SKILL.md`. The development checkout is a separate maintenance surface.

## Requirements

- Python 3.10+
- `python3 -m pip install -r requirements.txt`
- A release activated through `workflow.py --install-release`
- Host Microsoft Word or LibreOffice is mandatory; the release-owned PDFium runtime is installed offline

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

For ordinary generation, use the bounded adapter instead of a separate open-ended loop:

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --desktop-operation --manual-review --run-dir <run-dir>
```

Independent content and every-page visual review use actual final files/evidence. AI repairs native files using [general-document-repair.md](general-document-repair.md). Preserve source approval and the original 45-minute deadline. Under 25 minutes is the measured normal target, excluding approval wait.

Deliver every client-ready attachment only after confirmed exact-byte delivery. For `review_required`, deliver every complete labeled review-only file plus its findings and notice; transfer confirmation does not establish clinical approval. Corrupt, incomplete or source-untrustworthy files remain unavailable. Keep previews, draft/review requests and logs internal.

## Owner-requested release maintenance

The full development suite requires explicit owner approval; ordinary generation runs no test suite.

```bash
# Only with explicit full-suite approval:
python3 -m pytest -q
python3 scripts/workflow.py --release-gate
```

If the gate returns `awaiting_hermes`, complete every returned content and
rendered-page verification request using real content/image inspection, then
resume it with `python3 scripts/workflow.py --release-gate --release-gate-root
<evidence_root>`. The gate never fabricates visual approval and must ultimately
pass all ten branch/family/richness cases. A missing renderer, unassessed page or incomplete AI review cannot establish client-ready status. Corrupt files, invalid response/source bindings, incomplete inventory and unsupported XML structure remain objective technical failures. Semantic and presentation judgments belong to independent AI review. Renderer and tool
office failures may advance between Word and LibreOffice, but PDFium failure stops with one diagnostic; a complete candidate is
retained internally when the Delivery Gate remains unresolved.
