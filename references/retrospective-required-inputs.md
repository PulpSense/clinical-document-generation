# Retrospective Required Inputs

Use this contract only when `meta.study_type` is `Retrospective`. It mirrors the 21 fields marked with `*` in the confirmed client Fillout form.

## Stop Rule

Before creating the source-of-truth Markdown, stop only when one of the starred fields below has no meaningful value. Whitespace-only text is missing.

If multiple sources provide distinct values for one starred field, leave that field unresolved and stop until one value is selected. Repeated identical values are agreement. Multiple items intentionally supplied inside one list answer are one field value, not conflicting candidates.

Do not block retrospective intake for an optional field, an ordinary `needs_review` item, a protocol number, missing AI-generated prose, or XML/PRS data. Parser, approval, template-rendering, and unresolved-placeholder failures remain technical blockers.

## Starred Fields

### Study Overview

- `study.title`: full study title.
- `study.background`: combined background and significance.
- `objectives.primary`: key study objectives; multiple objectives in one answer are allowed.
- `study.unmet_need`: unmet medical need. `study.unmet_medical_need` is an accepted compatibility key.
- `study.hypothesis`: study hypothesis.

### Study Methodology

- `design.study_design`: study design.
- `design.number_of_sites`: number of investigational sites that participated.
- `endpoints.primary`: combined key-endpoints answer.
- `procedures.assessments`: assessments conducted and their schedules. `procedures.visit_schedule` is an accepted compatibility key.

The site count and facility name are independently required form answers. The retrospective form requests one facility name rather than a facilities table, so do not compare `design.number_of_sites` with the number of `sites` rows.

### Participant Details And Analysis

- `population.inclusion_criteria`
- `population.exclusion_criteria`
- `population.sample_size`
- `population.sample_justification`; `statistics.sample_size_justification` is an accepted compatibility key.
- `statistics.analysis_plan`

### Operations And Resources

- `parties.irb.name`
- `parties.irb.address`
- `parties.sponsor.name`
- `parties.sponsor.address`
- `sites.0.facility.name`
- `parties.principal_investigator.name`
- `parties.principal_investigator.title`; `degree` is an accepted compatibility key.

## Optional Fields

These Retrospective Fillout fields do not block when absent:

- funding-source name and address
- facility city
- sub-investigator
- test articles
- references

`meta.protocol_number` is not a starred Fillout field and does not block intake. A deterministic compatibility value may still be generated later when a client template requires one.

## Candidate Tracking

Preserve candidates for retrospective starred fields under `source.field_candidates`, using the canonical field key. Each candidate may include `value` and `source`. For a list supplied as one candidate, wrap the entire list in a `value` object.

If candidate values conflict, keep the canonical field unresolved and add a field-specific `needs_review` item with `"kind": "conflict"`. After review, retain only the selected value or identical agreeing candidates. Generic review notes remain visible but nonblocking.
