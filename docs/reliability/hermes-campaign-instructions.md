# Synthetic Hermes reliability campaign

This is a bounded development campaign, separate from release certification.
The three `pilot: true` cases in `campaign.json` cover the three study types.
Expansion covers the remaining two consent families and equivalent input forms.
Every case is fictional. Retrospective output is Protocol only.

The ten files are five different fictional studies, each supplied twice with the
same facts. Inputs 01–05 describe assessment assignments in prose; 06–10 use
matrices or record-field tables. Both use a Brad-style question-and-answer
synopsis, longer clinical rationale, citation markers, fictional bibliography,
measurement units, multiple outcomes and enrollment-versus-evaluable sample
reasoning. Supplemental administrative answers keep obligatory inputs complete.
The fictional references are formatting test data, not medical evidence.

| Input pair | Study | Study type | ICF template |
| --- | --- | --- | --- |
| 01 / 06 | Home BP diaries | Prospective | Sterling |
| 02 / 07 | Hand therapy | Ambispective | Advarra |
| 03 / 08 | Radiology records | Retrospective | None; Protocol only |
| 04 / 09 | Skin comfort diaries | Prospective | Advarra |
| 05 / 10 | Hearing follow-up | Ambispective | Sterling |

Numbers 01–03 are the initial pilot. See `INPUT-ORDER.txt` for exact filenames.

Build the pack from the repository with:

```sh
python3 tests/reliability_campaign.py build --output /path/to/new-pack
```

Start with `01-home-diary-narrative.md`, `02-hand-function-narrative.md`,
and `03-radiology-records-narrative.md`. Run each as a separate study.

## Run one case

Copy only `inputs/` to Hermes. Keep `reviewer-only/` separate for the independent
audit after delivery. The input is raw source material, not an approved
Source-of-Truth. Use the ordinary extraction, required-input check and explicit
Source-of-Truth approval. The fixture labels never grant approval.

Use this message with the chosen input path substituted:

> Run the installed clinical-document-generation skill using this synthetic input:
> `<input path>`. This is one reliability test. Preserve the exact raw input under
> the run's input/ directory. Prepare the editable Source-of-Truth and obtain its
> approval through the normal workflow. Then run one governed Desktop operation,
> including independent final content review and every-page visual review. Keep
> all recovery within that operation and its original deadline. On a terminal
> result, stop and preserve the entire run; report the result and diagnostic ZIP.
> A terminal failure does not authorize another generation. Report the active
> commit, run directory, operation ID, total elapsed time, findings and exact
> delivered files. Retain every attempt, including failed ones, under one
> dedicated campaign run root. Do not run the full suite or certification corpus.

Run the three pilot cases first. Return their full run evidence and delivered
files for independent audit before expanding. No model, specialty, or particular
wording is an acceptance rule.

## Independent audit

For each `required_facts` item in the separate oracle, inspect each listed
artifact. Assess equivalent meaning and source-to-destination relationships,
not word matching. Record exact artifact hashes and quoted evidence or a
localized omission/contradiction. Confirm none of the forbidden claims appear
in affirmative form. Inspect every final page and preserve the audit separately
from the workflow's own review. Include confidentiality detail only when supplied.

Equivalent narrative/structured inputs must preserve the same clinical facts,
timing, compensation and schedule assignments. Exact prose and page counts may
differ. Missing optional information must not become a new intake obligation.

## Evidence and decision

Keep all run directories, including failures. A second successful operation is
another attempt, not successful recovery. Count elapsed time from every attempt.
Local controlled tests establish routing and integrity behavior only. A live
workflow pass and an independent artifact audit are separate observations.
This pack does not confer release certification or prove universal reliability.

Collect the retained operation states from the dedicated campaign directory:

```sh
python3 tests/reliability_campaign.py report --pack /path/to/pack \
  --runs-root /path/to/campaign-runs --evidence-kind live_hermes > campaign-report.json
```

The collector verifies the pack hashes, matches each run's retained raw input,
and checks the exact delivered file set and hashes against the publication
manifest. It reports first-operation delivery, eventual delivery, terminal
failures, recovery within an operation, and elapsed time across every attempt.
Unreadable or unmatched operations remain visible as evidence errors; missing
durations remain explicitly unmeasured. Identical or missing start times cannot
establish first-operation success. A report's successful exit means collection
completed, not that the campaign passed.

Independent audits are separate records; this CLI does not ingest or verify
them. Its external-audit count stays zero pending that work. Assess all pilot
oracles and final pages before deciding to expand. Keep successful and failed
runs together; provide the entire dedicated run directory, not just the latest
success. A smaller selected set is not evidence of a complete campaign.
