# Prospective And Ambispective Required Inputs

Use this contract when `meta.study_type` is `Prospective` or `Ambispective`. The confirmed forms use the same 35 fields/groups marked with `*`.

## Stop Rule

Before creating the source-of-truth Markdown, stop only when:

- one of the starred fields below has no meaningful value; or
- one starred field has more than one distinct, nonblank source candidate.

Whitespace-only text is missing. Repeated identical values from multiple sources are agreement, not conflict. Multiple items intentionally supplied inside one list, table, document, spreadsheet, email, or other uploaded source are one field value, not conflicting candidates when they describe the same required input.

Do not block prospective or ambispective intake for an optional field, an optional `needs_review` item, missing AI-generated prose, or missing PRS administration data that was not starred in Fillout. Parser, approval, template-rendering, controlled-vocabulary, and XML-structure failures remain technical blockers.

## Starred Fields

### Study Overview

- `study.title`: full title.
- `study.background`: combined background and significance.
- `objectives.primary`: primary objectives; multiple objectives in one answer are allowed.
- `study.hypothesis`: study hypothesis.

### Study Methodology

- `design.study_design`: study design.
- `design.intervention_name`: intervention name.
- `design.intervention_type`: intervention type.
- `design.number_of_sites`: number of investigational sites. This value must be supplied separately from the facility/site information. Stop if it conflicts with the number of meaningful facility entries extracted from the source material.
- `endpoints.primary`: the combined primary/secondary endpoint answer. Preserve secondary and exploratory items under their normal endpoint keys when supplied, but the Fillout gate is the combined answer.
- `procedures.assessments`: planned assessments and schedule. `procedures.visit_schedule` may satisfy the same form field when it contains the assessment schedule.

### Participants And Analysis

- `population.inclusion_criteria`
- `population.exclusion_criteria`
- `procedures.minimum_days_before_screening_without_participation`
- `population.sample_size`
- `population.sample_justification`; `statistics.sample_size_justification` is an accepted compatibility path.
- `risks_benefits.compensation_or_reimbursement`. An explicit `None` is meaningful. Compatibility values under `compensation`, `reimbursement`, or `payment` also satisfy the field.
- `statistics.analysis_plan`

### Operations And Resources

- `study.timeline`
- `parties.irb.name`
- `parties.irb.affiliation`
- `parties.irb.phone`
- `parties.irb.email`
- `parties.irb.address`
- `parties.sponsor.name`
- `parties.sponsor.address`
- `parties.principal_investigator.name`
- `parties.principal_investigator.title`; `degree` is an accepted compatibility key.
- `parties.study_coordinator.name`
- `parties.study_coordinator.title`; `degree` is an accepted compatibility key.
- `parties.study_coordinator.business_phone`
- `parties.study_coordinator.office_phone`
- `parties.study_coordinator.email`

The business and office phone fields are independently starred. Even when the same number applies to both, preserve it as the supplied value for each field.

### Participating Sites And Staff

- `sites.facilities`: at least one meaningful facility entry, normalized under `sites[].facility`.
- `sites.contacts`: at least one meaningful site-contact entry, normalized under `sites[].contact` or `sites[].contacts`.
- `sites.investigators`: at least one meaningful site-investigator entry, normalized under `sites[].investigator` or `sites[].investigators`.

These three starred site/staff information groups must each be supplied, but the client does not need to provide them as table inputs. If the information appears in another uploaded format, extract it and normalize it into the structured `sites[]` fields. Values from the separate study-coordinator and principal-investigator fields do not silently replace missing site/staff information. Facility IDs and facility-reference IDs may be generated deterministically. Multiple facilities, contacts, or investigators are valid and are not conflicts.

## Optional Fields

These Fillout fields do not block when absent in either branch:

- funding source name and address
- sub-investigator
- test articles
- control articles
- U.S. FDA-regulated drug switch
- U.S. FDA-regulated device switch

An unselected FDA switch follows the old Fillout/n8n behavior and maps to `No`. If an explicit switch value conflicts with the intervention type or another source, record a nonblocking review warning unless a starred field itself is conflicting.

## Candidate Tracking

During extraction, preserve prospective and ambispective starred-field candidates under `source.field_candidates`. Use the starred field key. Each candidate may include its source:

```json
{
  "source": {
    "field_candidates": {
      "study.title": [
        {"value": "Title from synopsis", "source": "synopsis.docx"},
        {"value": "Title from email", "source": "email.txt"}
      ]
    }
  }
}
```

For a list, table, document section, spreadsheet range, email, or other uploaded source supplied as one candidate, wrap the entire value in a `value` object. Do not flatten its entries into separate conflicting candidates.

If candidate values conflict, keep the canonical field unresolved, add a field-specific `needs_review` item with `"kind": "conflict"`, and run the public workflow's `prepare` or `validate` stage. After the reviewer resolves the conflict, retain only the selected value or identical agreeing candidates. Generic review notes on populated starred fields are nonblocking.
