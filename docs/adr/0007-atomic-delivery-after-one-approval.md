# Deliver the branch document set atomically after one approval

The client explicitly approves the Source-of-Truth Markdown once; generation may then release the Branch Document Set without a second human approval only when every required document passes content, structure, package, and renderer-identified Visual QA gates. Any failure blocks the entire set and produces one consolidated Repair Report. If no supported renderer is installed, structurally validated DOCX files may be produced as internal artifacts, but the Branch Document Set is not reported as visually passed.
