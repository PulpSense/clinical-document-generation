# Renderer preflight

Renderer and font installation is a one-time administrator prerequisite. Install the governed Microsoft Word, LibreOffice, or Apple Pages renderer, the fonts declared by the selected client templates, and Poppler's `pdftoppm`. The document lifecycle does not install packages or change machine configuration.

Before the first drafting wave, `generate` runs a bounded disposable smoke export. It records the selected renderer and version, required-font results, PDF export, page-image probe, deadline, and elapsed time under `generation.renderer_preflight`. A missing renderer or page-image tool, failed conversion, unavailable required font, unresponsive process, or deadline overrun blocks drafting and publication. The selected renderer identity is reused for the document render in that governed attempt.

The preflight is a capability check, not client-ready evidence. Final delivery still requires the existing content, structural, package, and independent every-page visual verification gates. Visual equivalence against the frozen client baseline remains a separate manual acceptance check.
