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

The scripts do not call OpenAI directly. Hermes should use `gpt-5.5` for the agent reasoning and narrative-generation steps, then run the local scripts for validation, mapping, rendering, and QA.

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
- macOS Pages plus the built-in `osascript` command is optional and required only when the final DOCX must be rendered and audited with Apple Pages.

All Python scripts use the standard library. Do not run `pip install`, `npm install`, or any package bootstrap command for this skill. Node.js is not used.

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
- Allow `osascript` only if the Hermes host uses Apple Pages for final DOCX rendering and TOC audit.

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

1. Preserve raw source material under the run's `input/` directory.
2. Classify the study as `Prospective`, `Ambispective`, or `Retrospective`.
3. Draft `reference/study.reference.json`.
4. Run `python3 scripts/check_required_inputs.py --run-dir <run-dir>`.
5. If required inputs are missing, ask for them and stop.
6. Create the reviewer-facing source Markdown with `python3 scripts/create_source_truth_md.py --run-dir <run-dir> --require-complete`.
7. Send or attach only the generated source Markdown for review.
8. Wait for explicit reviewer approval or an edited source Markdown upload.
9. Parse the approved Markdown back into `study.reference.json`.
10. Generate branch-specific narrative fields with `gpt-5.5` and save them under `generated`.
11. Run the branch mapper and validation scripts.
12. Render final DOCX/XML outputs only with `python3 scripts/render_templates.py --run-dir <run-dir> --require-approval`.
13. Run PRS XML validation for prospective and ambispective XML outputs.
14. For DOCX files with a static TOC/index, render to PDF with the reviewer-facing engine, refresh static TOC/index values, re-render, and audit before delivery. On macOS, use `python3 scripts/export_docx_with_pages.py <input.docx> <output.pdf>` for Pages export.

Read `SKILL.md` and the referenced files in `references/` for the full workflow before generating real client documents.

## Do Not Ship If

Do not mark a run complete if any of these are true:

- Required inputs are still missing.
- `approval.status` is not `approved`.
- The approved source Markdown was not parsed after approval.
- `needs_review` contains unresolved critical items.
- Template placeholders remain unresolved.
- Prospective or ambispective PRS XML validation has not passed.
- A DOCX static TOC/index has page mismatches, missing headings, or alignment mismatches.

## Troubleshooting

`Repository not found`

The GitHub account used by Hermes does not have access to the private repo. Authenticate as an invited GitHub user or request repo access.

`Unsupported or encrypted PDF`

The built-in PDF text extractor accepts the unencrypted PDFs generated by Apple Pages and ordinary office renderers. Re-export the DOCX as an unencrypted PDF with the same renderer the reviewer will use, then rerun TOC refresh/audit.

`osascript: command not found` or Apple Pages export fails

Run Pages-based final rendering only on a macOS Hermes host with Apple Pages installed. If the reviewer will inspect the DOCX in another renderer, use that renderer's PDF output as the audit source instead.

Final output was not generated

This is usually correct when source inputs are incomplete or approval is missing. Complete the source-of-truth Markdown review and approval loop before rendering final outputs.
