# Study Reference Schema

`<run-dir>/reference/study.reference.json` is the machine-readable input used to
prepare the reviewer-facing Source-of-Truth Markdown. The approved Markdown and
its immutable JSON snapshot become the generation authority.

Do not place generated prose, legacy template placeholders, or model output in
this file.

## Canonical top-level shape

```json
{
  "meta": {},
  "source": {},
  "approval": {},
  "study": {},
  "parties": {},
  "sites": [],
  "population": {},
  "design": {},
  "objectives": {},
  "endpoints": {},
  "procedures": {},
  "statistics": {},
  "safety": {},
  "ethics": {},
  "confidentiality": {},
  "risks_benefits": {},
  "regulatory": {}
}
```

## Field families

- `meta`: `study_type`, protocol number, version, date, document set, and ICF
  template. `study_type` must normalize to `Prospective`, `Ambispective`, or
  `Retrospective`. Prospective/Ambispective require `icf_template` of `Advarra`
  or `Sterling`.
- `source`: preserved intake provenance and `field_candidates`. Put competing
  values for an obligatory field in `field_candidates`; conflicting values
  block approval until the reviewer selects one.
- `study`: title, short title, background/rationale, unmet need, hypothesis, and
  timeline.
- `parties`: sponsor, principal investigator, sub-investigators, coordinator,
  IRB/ethics committee, funding source, and their contact details.
- `sites`: one row per site with facility, contact, backup contact, and
  investigator details.
- `population`: study population, planned sample size, sample justification,
  age/sex eligibility, inclusion criteria, exclusion criteria, and supporting
  sample-size evidence.
- `design`: design description, site count, masking, arms/groups,
  interventions/test articles, controls, and data sources.
- `objectives`: primary and secondary objectives.
- `endpoints`: structured `primary`, `secondary`, and optional `other`
  outcome rows. Every row requires a measure (`label`, `measure`, or
  `outcome_measure`) and time frame (`time_point`, `time_frame`, or
  `outcome_time_frame`).
- `procedures`: consent/enrollment, assessments, methods/measurements, visit
  schedule rows, discontinuation, completion, termination, and related
  operational facts.
- `statistics`: analysis plan, methodology, statistical considerations, and
  supporting sample-size evidence.
- `safety`, `ethics`, and `confidentiality`: study-specific oversight facts.
- `risks_benefits`: risks, benefits, privacy, costs, alternatives, payment or
  reimbursement, and research-injury handling.
- `regulatory.prs`: ClinicalTrials.gov values, including
  `provider_study_id` (or `meta.protocol_number`), `study_type`
  (`Observational` or `Interventional`), and the stable study UID used for
  repeated PRS records. This registry classification is distinct from
  `meta.study_type`; during preparation, an unambiguous classification stated
  in `design.study_design` populates the PRS field before review.

When both `provider_study_id` and `meta.protocol_number` are absent for a
Prospective or Ambispective study, preparation assigns one stable `ADM-...`
workflow-owned administrative identifier derived only from the approved study
type, title, sponsor, and principal-investigator identity. The generated value,
its authority, and its source fields appear in the editable Source-of-Truth
before approval. It is control-plane identity, not an inferred clinical fact.

Schema support does not make a field obligatory for source intake. Sample-size
evidence tables and PRS administration/classification values are optional at
intake; their absence must not prompt missing-input questions. Supplied evidence
still requires the approved typed table schema and consistency checks, and a
supplied PRS classification must use the supported controlled vocabulary.
Required PRS output values remain governed by downstream XML validation.

## Consistency rules

- The planned sample count must agree with every populated sample-size evidence
  row.
- `design.number_of_sites`, the `sites` row count, and single-/multicenter
  wording must agree.
- Outcome text may not be supplied as one free-text blob; it must use structured
  rows with measure and time frame.
- A visit or outcome time point may not extend beyond the approved study
  timeline.
- Required branch inputs must be populated before Source-of-Truth approval.
- No section-specific fact may be inferred from a template or generated draft.

## Approval state

`prepare` writes the Source-of-Truth Markdown and sets the JSON to
`awaiting_approval`. `approve` parses the exact reviewer file, validates the
contract, binds its SHA-256, and creates a write-once revision containing:

- `approved-reference.json`
- `approved-source.md`

Changing reviewer-controlled study inputs after approval blocks generation and
requires a new prepare/approve cycle. Runtime `generation` attempt state is not
part of the clinical approval payload, but exhausted targets remain blocked
until a new approved revision is created.

## Generation boundary

After approval, use only:

```bash
python3 scripts/workflow.py --run-dir <run-dir> --stage generate
```

Hermes returns section drafting and independent verification JSON when the
workflow requests it. Python maps accepted content into Word and PRS XML. Never
edit `template_fields`, call an internal module directly, or run a separate n8n
mapper.
