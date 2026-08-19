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

## Branch Smoke And Packaging

A skill version is releasable only after every supported branch has generated its complete default document set and passed every applicable Delivery Gate.

Run the branch smoke:

```bash
python3 scripts/run_branch_smoke.py --root /tmp/clinical-smoke
```

It generates the prospective, ambispective, and retrospective document sets from approved reference fixtures, runs each branch's Delivery Gates, and writes `skill-smoke.json` recording the branch, active document set, generated artifacts, gate outcomes, and any QA limitation. It exits non-zero when a branch fails or was never smoked.

Build the package:

```bash
python3 scripts/package_skill.py --output /tmp/clinical-document-generation.zip --smoke-root /tmp/clinical-smoke
```

Packaging runs the smoke first and refuses to write an archive unless every branch passed. Invalid PRS XML, unresolved placeholders, missing branch-required body content, an absent Data-Driven visit table, or detected stale template content all block the release. Renderer unavailability does not: it is recorded as a QA limitation, matching the exporter contract. An available renderer that fails, or a static-TOC audit that finds page, alignment, or missing-heading mismatches, does block.

The archive contains `SKILL.md`, `README.md`, `agents/`, `assets/`, `references/`, `scripts/`, and the `smoke-evidence.json` that authorised the release.

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

1. Preserve raw source material under the run's `input/` directory.
2. Classify the study as `Prospective`, `Ambispective`, or `Retrospective`.
3. Draft `reference/study.reference.json`.
4. For prospective or ambispective studies, resolve Advarra vs Sterling before source-of-truth generation. Auto-select an explicitly named supported template; otherwise ask. Apply a later answer with `python3 scripts/select_icf_template.py --run-dir <run-dir> --choice <advarra|sterling>`. Retrospective studies skip this step.
5. Run `python3 scripts/check_required_inputs.py --run-dir <run-dir>`.
6. If blocking inputs remain, ask for them together and stop. Clinical input blockers are limited to missing or conflicting starred Fillout fields; prospective and ambispective runs also require the separate ICF template choice.
7. Create the reviewer-facing source Markdown with `python3 scripts/create_source_truth_md.py --run-dir <run-dir> --require-complete`.
8. Send or attach only the generated source Markdown for review.
9. Wait for explicit reviewer approval or an edited source Markdown upload.
10. Parse the approved Markdown back into `study.reference.json`.
11. Generate branch-specific narrative fields with `gpt-5.5` and save them under `generated`.
12. Run the branch mapper and validation scripts.
13. Render final DOCX/XML outputs only with `python3 scripts/render_templates.py --run-dir <run-dir> --require-approval`.
14. Run PRS XML validation for prospective and ambispective XML outputs.
15. Run `python3 scripts/export_docx_to_pdf.py <input.docx> <output.pdf> --report <report.json>` for optional platform-aware visual QA. If a renderer is available and the DOCX has a static TOC/index, refresh, re-render, and audit it. If no renderer is available, keep the DOCX and disclose that visual/TOC QA was skipped.

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
