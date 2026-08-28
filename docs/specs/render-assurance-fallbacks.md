# Self-sufficient Render Assurance

Future Hermes clinical-document runs target 10–12 minutes and have one persisted 30-minute ceiling. Environment and tooling failures must not prevent construction of a complete branch candidate, but client delivery remains atomic and requires mandatory Visual QA.

## Confirmed requirements

- Protocol body sections use natural content-driven pagination, preserve the Client Template Authority's heading rhythm, and keep headings with their first substantive paragraph, list, or table. Intentional title-page and table-of-contents boundaries remain.
- Construct the complete Protocol/ICF/PRS candidate before terminal Render Assurance capability resolution.
- Keep Visual QA mandatory. At least one reviewer inspects every exact bound page image; deterministic checks alone cannot pass it. Evidence records the exact DOCX, PDF, and page-image hashes and becomes stale if any of those bytes change.
- Keep all rendering and review local. A delegated visual-review timeout routes the same request to the parent reviewer.
- Require host Microsoft Word or LibreOffice for DOCX-to-PDF rendering. Tool failure may advance between those office renderers; a genuine visual defect triggers repair on the renderer that exposed it.
- Treat font evidence as available, missing, or unknown. Unknown inventory is decided through an actual render. Proven missing fonts use an approved compatible packaged fallback and record the substitution.
- Package exactly one pinned `pypdfium2` page renderer and compatible fonts. Never discover an alternate PDF backend. A release activates only after an end-to-end host-office/PDFium smoke test; failed activation leaves the previous verified release active.
- Record renderer, page-renderer, reviewer, font, substitution, attempt, and exact-artifact evidence in internal manifests without adding technical notices to clinical documents.
- Preserve the complete branch package atomically. Invalid source, corrupt templates, unsupported content, structural invalidity, or a genuine visual defect may block delivery.
- At the 30-minute ceiling, retain a complete unresolved candidate internally and publish no client outputs.
- The Desktop launcher calls `resolve_python_runtime`, selects a supported Python 3.10+ executable by absolute path, and records its identity instead of relying on an ambiguous `python3` command.
- Persist one cross-process UTC deadline and derive elapsed time from that anchor across resumes. A runtime or monotonic-clock epoch change cannot reset the budget; monotonic time is used only for measurements within one producer/consumer clock epoch.
- Drive normal generation and controlled real-Hermes certification through the same persisted Desktop Operation interface. Environment-specific adapters own only Hermes process launch, read-only sandboxing, file opening, progress, and cleanup.
- Bind operation identity to the Promoted Release fingerprint, compatible runtime history, exact pending handoffs, attempt counters, stage timings, soft-budget diagnostics, cleanup evidence, and terminal result. A missing worker response may redispatch only the unchanged request.
- Treat stage budgets as soft early-fallback or diagnostic thresholds. Only the original 30-minute UTC deadline is terminal, and late worker or opener completion cannot publish or confirm after it.
