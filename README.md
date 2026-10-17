# Clinical Document Generation

Experimental Hermes skill: retained n8n prompts, Brad's corrections and current
client DOCX/XML formatting. Read [SKILL.md](SKILL.md) and
[the generation instructions](references/generation-only.md).

Install the entire folder with its existing compatible Python runtime and
`requirements.txt`. Linux runtime dependencies remain unchanged.

The workflow prepares an editable Source-of-Truth, records explicit approval,
requests a shared AI content plan and section drafts from Hermes and builds the complete native document set.
One office pagination pass fills Protocol TOC page numbers using the existing
host LibreOffice (`CLINICAL_SOFFICE` can specify its absolute path). Its temporary
PDF stays internal and is deleted. There is no independent review or automatic repair.

Seven Python scripts are retained:

| Script | Role |
| --- | --- |
| `workflow.py` | Source preparation, approval, native generation and delivery records |
| `contracts.py` | Study, section and template contracts |
| `drafting.py` | Hermes requests, response ingestion and merging |
| `rendering.py` | Native Protocol and ICF DOCX assembly |
| `prs_xml.py` | Literal planned PRS values in the governed XML structure |
| `content_plan.py` | Full-source AI content-plan handoff, shape and identity checks |
| `output_recovery.py` | Shared field mappings and compatibility helpers still imported by drafting/rendering |

`--stage generate` always uses the experimental generation path; the existing
`--generation-only` flag remains accepted. Deliver clean filenames with clickable
links and the recorded generation time. The original reviewed implementation
remains available in the primary checkout and Git history.

Historical tests and design references for the reviewed workflow remain in the
repository, but its removed worker/release commands are not supported by this
experimental checkout. Run focused tests for the active generation path.
