---
status: accepted
---

# Own the capabilities required for mandatory Render Assurance

Document construction is independent from Render Assurance, while client delivery still requires exact-artifact rendering and page-image review. The client host must provide Microsoft Word or LibreOffice for DOCX-to-PDF rendering. The release owns exactly one PDF-to-image capability: a pinned, manifest-hashed `pypdfium2` wheel installed offline into the release runtime. It never discovers alternate PDF backends. A release becomes active only after its host office renderer, PDFium runtime, and compatible fonts pass an end-to-end smoke test, and activation retains the previous verified release atomically.

This supersedes ADR-0009's PDF-backend discovery ladder and revises this ADR's earlier release-owned office-suite decision. We rejected direct GUI screenshot traversal because it is slower and cannot prove deterministic every-page coverage, and rejected downloading a renderer during installation because network and upstream changes weaken reproducibility. The smaller packaged PDFium runtime preserves mandatory Visual QA without redistributing a complete office suite. An incompatible host stops during installation before the first clinical run.
