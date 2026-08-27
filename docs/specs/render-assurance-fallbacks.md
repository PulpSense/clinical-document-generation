# Self-sufficient Render Assurance

Future Hermes clinical-document runs target 10–12 minutes and have one persisted 30-minute ceiling. Environment and tooling failures must not prevent construction of a complete branch candidate, but client delivery remains atomic and requires mandatory Visual QA.

## Confirmed requirements

- Protocol body sections use natural content-driven pagination, preserve the Client Template Authority's heading rhythm, and keep headings with their first substantive paragraph, list, or table. Intentional title-page and table-of-contents boundaries remain.
- Construct the complete Protocol/ICF/PRS candidate before terminal Render Assurance capability resolution.
- Keep Visual QA mandatory. At least one reviewer inspects every exact bound page image; deterministic checks alone cannot pass it. Evidence records the exact DOCX, PDF, and page-image hashes and becomes stale if any of those bytes change.
- Keep all rendering and review local. A delegated visual-review timeout routes the same request to the parent reviewer.
- Try Microsoft Word, installed LibreOffice, Pages, then a release-local verified LibreOffice fallback. Tool failure advances; a genuine visual defect triggers repair on the renderer that exposed it.
- Treat font evidence as available, missing, or unknown. Unknown inventory is decided through an actual render. Proven missing fonts use an approved compatible packaged fallback and record the substitution.
- Package/provision a renderer, page renderer, and compatible fonts. A release activates only after an end-to-end smoke test; failed activation leaves the previous verified release active.
- Record renderer, page-renderer, reviewer, font, substitution, attempt, and exact-artifact evidence in internal manifests without adding technical notices to clinical documents.
- Preserve the complete branch package atomically. Invalid source, corrupt templates, unsupported content, structural invalidity, or a genuine visual defect may block delivery.
- At the 30-minute ceiling, retain a complete unresolved candidate internally and publish no client outputs.
- The Desktop launcher calls `resolve_python_runtime`, selects a supported Python 3.10+ executable by absolute path, and records its identity instead of relying on an ambiguous `python3` command.
- Persist one cross-process UTC deadline and derive elapsed time from that anchor across resumes. A runtime or monotonic-clock epoch change cannot reset the budget; monotonic time is used only for measurements within one producer/consumer clock epoch.
