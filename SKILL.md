---
name: clinical-document-generation
description: Generate clinical Protocol DOCX, ICF DOCX, and ClinicalTrials.gov PRS XML from approved study inputs using retained n8n prompts and client formatting. Use for prospective, ambispective, or retrospective studies.
---

# Clinical Document Generation

This experimental checkout prepares an editable Source-of-Truth, records one
explicit source approval, obtains Hermes section drafts and assembles native
DOCX/XML. The owner and Codex inspect outputs afterward. Follow
[generation-only.md](references/generation-only.md) for drafting and delivery.
The reviewed workflow remains in Git history and the original checkout; this
checkout has no review workers, quality gates or repair lifecycle. One office
pagination pass populates Protocol TOC page numbers after native assembly.

## Runtime and source preparation

Use an existing absolute Python 3.10+ interpreter in `CLINICAL_PYTHON` with
`requirements.txt` installed. Preserve Linux runtime dependencies. Keep the
installed skill read-only during generation; write run data in its run folder.
Install this entire skill folder, including assets and references.
Use the existing host LibreOffice executable for TOC pagination. Set
`CLINICAL_SOFFICE` to its absolute path if `libreoffice` or `soffice` is not on
PATH. This formatting step creates a temporary internal PDF and discards it;
the native DOCX body is not round-tripped through the office application.

Preserve supplied files in `input/`. Read
[intake-workflow.md](references/intake-workflow.md) when interpreting them and
[reference-schema.md](references/reference-schema.md) for canonical fields in
`reference/study.reference.json`. Resolve material conflicts, including conflicting
study-design statements, before requesting approval. Missing optional details
stay absent. Use [quality-corrections.md](references/quality-corrections.md) as
content guidance when relevant; it does not add automated review steps.

## Branch outputs

| Study type | Required documents |
| --- | --- |
| Prospective | `protocol.docx`, `icf.docx`, `study.xml` |
| Ambispective | `protocol.docx`, `icf.docx`, `study.xml` |
| Retrospective | `protocol.docx` |

Prospective/Ambispective use the approved Advarra or Sterling selection and
[starred-fillout-required-inputs.md](references/starred-fillout-required-inputs.md).
Retrospective uses [retrospective-required-inputs.md](references/retrospective-required-inputs.md).
Keep source facts distinct from template examples. Use retained n8n prompts plus
Brad's corrections for matching sections; draft additional sections from supplied
study facts. AI owns each complete requested section, including applicable supplied
boilerplate; assembly preserves accepted prose and lists without completing or
rewriting them. Current templates own retained fixed clauses, source-field
mappings, headings and formatting.

## Run directory policy

Keep every study run under `/opt/data/clinical-document-runs/`, with exactly one
dedicated top-level folder per run. Before starting generation, derive and show
the proposed folder name, then use it unless the user requests a different
approved study title:

```text
<filesystem-safe-approved-study-title>__<study-type>__<YYYY-MM-DD>
```

Apply these rules:

1. Use the approved study title from the study input.
2. Use exactly `Prospective`, `Ambispective`, or `Retrospective` for the study-type label.
3. Use the Hermes host's current local date when the folder is first created, formatted `YYYY-MM-DD`.
4. Convert the title to a readable filesystem-safe name: replace spaces with hyphens; remove slashes, colons, and unsupported characters; and retain enough text to identify the study clearly.
5. Never reuse or overwrite a run folder. If the base name exists, append `__02`, `__03`, and so on, choosing the first unused suffix.
6. Create the selected folder directly under `/opt/data/clinical-document-runs/` and pass its exact absolute path as every workflow command's `--run-dir`.
7. Keep source inputs, the approved Source-of-Truth, revisions, drafts, logs and final documents inside that run folder.
8. Generation moves the complete branch set into the run's `output/` folder; use the exact paths returned in `experimental_outputs`.
9. Never generate files directly in `/opt/data`, inside this installed skill, or inside another study's run folder.
10. Never delete or alter an earlier study-run folder.
11. Deliver the document links and recorded generation time as described in [generation-only.md](references/generation-only.md).

Folder selection is complete only after confirming the proposed path does not
already exist and the chosen path is the first available collision-safe name.

## Source approval and generation

Run these commands from this skill folder, using the exact run directory:

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage prepare
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage approve --approved-by <reviewer>
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage generate --generation-only
```

After prepare, assess `intake_review` against the original evidence. Resolve
extraction omissions yourself and consolidate questions about actual missing
required facts or material conflicts. Attach the editable file using
`review_delivery` and `source_review_reply`. Run approve only after the user
explicitly approves that exact Source-of-Truth file. A changed source requires
new approval; a changed generation implementation starts a new attempt.

When generation returns `awaiting_hermes`, complete the drafting requests as
specified in [generation-only.md](references/generation-only.md), then rerun
that same generate command until native assembly is complete. Both plain
`--stage generate` and the compatibility flag `--generation-only` use this path.
`--stage validate` checks source readiness and approval only.

## Delivery

### Owner-required output presentation

- Present the documents as normal outputs, not as “generation-only” or experimental documents. Use the normal filenames `protocol.docx`, `icf.docx`, and, when applicable, `study.xml`.
- The user-facing `output/` folder must contain only the branch-appropriate DOCX/XML documents. Keep README files, notices, commit identifiers, hashes, prompt provenance, and other technical metadata in internal run records, outside this folder.
- Deliver the workflow's files directly from `output/`. Completed runs retain one document set, with hashes and actual assessment status in internal records.
- At startup, simply say that document generation has started. Do not narrate internal prompt sources or mention Brad's corrections in progress or delivery messages; continue following them internally.
- Finish with a short, neatly formatted message headed **Here are the documents**, one individually clickable link per document, and **Generation time: X minutes Y seconds**. Do not include commit IDs, revision IDs, experiment labels, audit details, or long technical explanations in that delivery message.
- Use genuine accessible file links or actual channel uploads when supported. Never invent upload links or claim recipient transfer from a host-local path alone. If the channel cannot deliver accessible files, state that limitation plainly.
- This presentation preference does not establish independent review or certification. Preserve the true assessment status internally and disclose it accurately if asked.

Use `delivery_message`: “Here are the documents:”, clickable links for the
complete branch set, then generation time in minutes and seconds. Transfer files
through the channel's actual attachment/upload mechanism when host-local paths
are not accessible, and substitute its real links. Keep technical details in run
records. Filenames are `protocol.docx`, `icf.docx` and `study.xml` as applicable.
Generation records assessment status internally; generation alone does not
establish an independent review result.
