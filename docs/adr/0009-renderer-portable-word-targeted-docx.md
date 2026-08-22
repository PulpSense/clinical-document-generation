# Validate with the available renderer and target Microsoft Word

The workflow produces standards-compliant, Microsoft Word-targeted DOCX files and performs Visual QA with the best supported renderer installed on the generation host, preferring Word, then LibreOffice, then Pages. Evidence records the renderer identity and exact artifact hash, and the workflow never claims Microsoft Word validation unless Word produced that evidence. If no supported renderer exists, generation may complete structural validation but emits a Repair Report for missing Visual QA evidence.
