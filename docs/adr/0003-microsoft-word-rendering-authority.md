---
status: superseded by ADR-0009
---

# Use Microsoft Word as the rendering authority

Microsoft Word desktop is the Client Rendering Authority for generated DOCX documents. Visual QA and pagination acceptance use Word-rendered evidence because alternate office renderers can lay out the same DOCX differently; they may provide diagnostics, but they cannot certify delivery. Final DOCX delivery blocks when Word-rendered evidence cannot be produced.
