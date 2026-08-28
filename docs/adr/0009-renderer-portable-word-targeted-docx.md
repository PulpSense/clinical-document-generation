---
status: superseded
superseded_by: ADR-0018
---

# Produce renderer-portable, Word-targeted DOCX with identified evidence

The durable part of this decision remains: generated DOCX files target Microsoft Word, evidence names the office application that produced it, and the workflow never claims Microsoft Word validation unless Word produced that evidence.

ADR-0018 supersedes the former renderer-discovery ladders. The current governed contract requires a verified host Microsoft Word or LibreOffice installation for DOCX-to-PDF conversion and one pinned, manifest-bound `pypdfium2` runtime for PDF-to-page-image conversion. Installation fails before clinical generation when either capability cannot be verified. The release never bundles or discovers an office suite from its runtime and never discovers an alternate PDF backend.

This preserves mandatory exact-artifact Render Assurance and every-page Visual QA while making ownership explicit: the host owns the office prerequisite; the immutable release owns PDFium and approved compatible fonts.
