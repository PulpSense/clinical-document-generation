# Clinical Document Generation Skill

This repository is the Hermes skill source for clinical document generation.

Setup target:

- GitHub repo: `https://github.com/PulpSense/clinical-document-generation`
- Branch: `main`
- Skill name: `clinical-document-generation`
- Skill root: the repository root, the directory that contains `SKILL.md`
- Required Hermes model: `gpt-5.5`

Do not install only `SKILL.md`. The skill requires the bundled `assets/`, `references/`, and `scripts/` directories.

## What Is Included

- `SKILL.md`: the Hermes skill instructions and routing description.
- `assets/client-templates/`: bundled DOCX and PRS XML templates.
- `references/`: branch, schema, approval, source-of-truth, and template-contract instructions.
- `scripts/`: deterministic Python scripts used by the skill.

Quality and delivery entry points:

- `scripts/workflow.py` is the only public workflow seam. It
  owns prepare, approval, readiness, generation, and delivery for a complete
  conversational run.
- `scripts/quality_contract.py` validates branch-aware source completeness,
  explicit approval, legacy normalization, and Data-Driven Table schemas.
- `scripts/delivery_pipeline.py` runs the read-only content, structure,
  package, visual, and Static TOC reviews, applies only controlled repairs, and
  exposes client outputs only after the complete rerun passes.

The remaining scripts are internal adapters used by the public workflow. They
are not separate user workflows and should not be invoked directly during a
client run.

The scripts do not call OpenAI directly. Hermes should use `gpt-5.5` for the agent reasoning and narrative-generation steps, then run the local scripts for validation, mapping, rendering, and QA.

## Public Workflow Seam

Client integrations should import `scripts/workflow.py` and use only its four
Run Lifecycle operations: `prepare`, `approve`, `validate`, and `generate`.
The six replacement ownership modules are `contracts`, `drafting`, `rendering`,
`quality`, and `prs_xml`, alongside `workflow`. The former
`clinical_document_workflow.py` compatibility entrypoint has been removed;
callers must use the public seam.

## Access Check

The repository is private. Before cloning, confirm the GitHub account used by Hermes or by the setup agent has access to `PulpSense/clinical-document-generation`.

With GitHub CLI:

```bash
gh auth status
gh repo view PulpSense/clinical-document-generation --json nameWithOwner,visibility,defaultBranchRef
```

Expected result:

```text
nameWithOwner: PulpSense/clinical-document-generation
visibility: PRIVATE
defaultBranchRef.name: main
```

If GitHub returns `Repository not found`, the account is not authenticated correctly or has not been invited to the private repo.

## Clone Into Hermes

Set the Hermes skill directory to the actual skill directory used by that Hermes installation:

```bash
export HERMES_SKILLS_DIR="/absolute/path/to/hermes/skills"
test -d "$HERMES_SKILLS_DIR"
```

Clone the repository as a direct child of that directory:

```bash
git clone https://github.com/PulpSense/clinical-document-generation.git \
  "$HERMES_SKILLS_DIR/clinical-document-generation"

cd "$HERMES_SKILLS_DIR/clinical-document-generation"
git checkout main
```

Verify the clone:

```bash
test -f SKILL.md
test -d assets/client-templates/docx
test -d references
test -d scripts
```

If the repo is already cloned, update it with:

```bash
cd "$HERMES_SKILLS_DIR/clinical-document-generation"
git pull --ff-only origin main
```

## Runtime Requirements

The core workflow has one runtime requirement in the environment where Hermes runs skill commands:

- Python 3.9 or newer.

All Python scripts use the standard library. Do not run `pip install`, `npm install`, or any package bootstrap command for this skill. Node.js is not used.

DOCX generation does not require Microsoft Word, Apple Pages, or LibreOffice. Optional PDF-based visual/TOC QA automatically uses Pages on macOS, Word on Windows, or LibreOffice on Linux when available. If none is installed, the DOCX is still generated and the exporter records that visual QA was skipped.

Check versions:

```bash
python3 --version
```

The Python version check must report 3.9 or newer. No additional runtime installation is needed.

## Verify Local Setup

Run these commands from the skill root:

```bash
cd "$HERMES_SKILLS_DIR/clinical-document-generation"

python3 - <<'PY'
import sys
assert sys.version_info >= (3, 9), sys.version
print("Python version OK")
PY

python3 -m py_compile scripts/*.py
python3 -m unittest discover -s tests -v
```

Run a smoke test that creates and then removes a temporary run outside the repo:

```bash
printf '%s\n' "Hermes setup smoke test only." > /tmp/hermes-clinical-source.md

python3 scripts/create_run.py \
  --root /tmp/hermes-clinical-runs \
  --slug setup-smoke \
  --study-type retrospective \
  --raw-context /tmp/hermes-clinical-source.md

test -f /tmp/hermes-clinical-runs/setup-smoke/reference/study.reference.json
test -f /tmp/hermes-clinical-runs/setup-smoke/templates/protocol.template.docx

rm -rf /tmp/hermes-clinical-runs /tmp/hermes-clinical-source.md
```

## Register In Hermes

Register the cloned repository root as a Hermes skill source.

Use these values in the Hermes UI or config fields that correspond to skill registration:

```yaml
skill_id: clinical-document-generation
name: clinical-document-generation
source_type: local_directory
path: /absolute/path/to/hermes/skills/clinical-document-generation
entrypoint: SKILL.md
model: gpt-5.5
enabled: true
```

If Hermes imports skills directly from Git instead of a local directory, use:

```yaml
skill_id: clinical-document-generation
name: clinical-document-generation
source_type: git
repository: https://github.com/PulpSense/clinical-document-generation.git
branch: main
subdirectory: .
entrypoint: SKILL.md
model: gpt-5.5
enabled: true
```

Important registration details:

- Point Hermes at the repo root, not `scripts/`, `references/`, or the parent skills directory.
- Keep the skill name as `clinical-document-generation`; it matches the `name` field in `SKILL.md`.
- Route this skill to `gpt-5.5`. Do not route the generation workflow to a smaller or summarization-only model.
- Allow the skill runtime to execute `python3`.
- Allow the skill runtime to read and write local run directories.
- No office-application permission is required for DOCX generation. Optional renderer-based QA may invoke Pages/`osascript` on macOS, Word/PowerShell on Windows, or LibreOffice where installed.

## Hermes Smoke Prompt

After registration, ask Hermes:

```text
Use the clinical-document-generation skill to start a retrospective clinical document generation run from these setup-test notes: This is only a setup test. Principal investigator, sponsor, site, study title, endpoints, and IRB details are intentionally omitted.
```

Expected behavior:

- Hermes selects the `clinical-document-generation` skill.
- Hermes does not produce final DOCX/XML outputs from incomplete information.
- Hermes preserves the setup-test source input in a run directory or reports the missing required inputs.
- Hermes stops before final generation until a reviewer-facing source-of-truth Markdown file is complete and explicitly approved.

## Normal Generation Contract

For real studies, the Hermes agent must follow this sequence:

1. Preserve raw source material under the run's `input/` directory. The
   embedded client protocol reference is used automatically as an internal
   layout/reference contract; the client does not need to provide it again.
2. Classify the study as `Prospective`, `Ambispective`, or `Retrospective`.
3. Draft `reference/study.reference.json`.
4. For prospective or ambispective studies, resolve Advarra vs Sterling before source-of-truth generation. The workflow asks when the choice is ambiguous and records the selection internally. Retrospective studies skip this step.
5. Run the single public workflow in `prepare` mode. It performs the required-input check, consolidates all blockers into `reference/missing-inputs.md`, or creates the reviewer-facing Source-of-Truth Markdown.
6. Send or attach only that Source-of-Truth Markdown for review. The client may edit that file; the final client-provided or client-edited file is authoritative.
7. After one explicit client approval, run the same workflow in `approve` mode. It parses the current Markdown exactly as approved and records the approval.
   If the client uploaded an edited copy, pass it with `--source-md`; that copy becomes the run's approved source.
8. Generate branch-specific narrative fields with `gpt-5.5` and save them under `generated`; the workflow owns all deterministic mapping, rendering, validation, and delivery gates.
9. Optionally run the public `validate` mode to receive one consolidated readiness report before generation.
10. Generate the complete branch document set through the public seam:

    ```bash
    python3 scripts/workflow.py --run-dir <run-dir> --stage prepare
    python3 scripts/workflow.py --run-dir <run-dir> --stage approve --approved-by "<client>"
    python3 scripts/workflow.py --run-dir <run-dir> --stage generate
    ```

    The final command maps the approved source, generates the required branch
    documents, validates PRS XML for prospective/ambispective runs, and exposes
    client outputs only after all delivery gates pass. Add `--require-renderer`
    when rendered evidence is mandatory.
11. The workflow validates PRS XML for prospective/ambispective runs, renders
    DOCX/XML through the internal renderer adapters, performs controlled TOC
    repair and audit when available, and exposes client outputs only after all
    delivery gates pass. Add `--require-renderer` when rendered evidence is
    mandatory.

Read `SKILL.md` and the referenced files in `references/` for the full workflow before generating real client documents.

## Do Not Ship If

Do not mark a run complete if any of these are true:

- Branch-required inputs are still missing or conflicting.
- `approval.status` is not `approved`.
- The approved source Markdown was not parsed after approval.
- `needs_review` contains unresolved branch-blocking starred-field conflicts; optional and generic review notes do not block.
- Template placeholders remain unresolved.
- Prospective or ambispective PRS XML validation has not passed.
- An available DOCX renderer reports static TOC/index page mismatches, missing headings, or alignment mismatches.

## Troubleshooting

`Repository not found`

The GitHub account used by Hermes does not have access to the private repo. Authenticate as an invited GitHub user or request repo access.

`Unsupported or encrypted PDF`

The built-in PDF text extractor accepts the unencrypted PDFs generated by Apple Pages and ordinary office renderers. Re-export the DOCX as an unencrypted PDF with the same renderer the reviewer will use, then rerun TOC refresh/audit.

`status: unavailable` from `export_docx_to_pdf.py`

The host has no supported PDF renderer. This does not block DOCX generation or delivery. The report must remain with the run logs and the delivery note must state that PDF-based visual/TOC QA was skipped. Install or provide Pages, Word, or LibreOffice only when the client requires strict visual verification.

Final output was not generated

This is usually correct when source inputs are incomplete or approval is missing. Complete the source-of-truth Markdown review and approval loop before rendering final outputs.
