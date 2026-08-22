# n8n Retrospective Protocol Branch

Use this reference when `meta.study_type` is `Retrospective`, especially for studies like MB-25-01.

Read `references/retrospective-required-inputs.md` first. Its 21 starred fields are the only retrospective source-input blockers.

## Document Classification

MB-25-01 is a retrospective clinical study protocol. More specifically, it is a retrospective, single-surgeon surgical video and medical-record review comparing two vitrectomy platforms:

- Unity VCS 27G with HyperVit 30k
- Constellation 27G with HyperVit 20k

It is protocol-only in the existing workflow. Do not generate ICF or XML for this branch unless the reviewer explicitly requests those outputs and provides templates.

## n8n Branch Shape

The existing workflow routes `selectYourTypeOfStudy = Retrospective` through this sequence:

```text
Protocol Type
  -> Introduction & Objectives2
  -> Population Variables2
  -> Study Design & Methods2
  -> Statistics & Sample Size2
  -> Set Protocol Fields2
  -> Create Protocol Folder2
  -> Duplicate Protocol Template2
  -> Batch:update Protocol Variables2
```

The skill must mimic the same logical sequence locally:

1. Structure source facts into `reference/study.reference.json`.
2. Run the four retrospective generation modules below using the reviewed source facts.
3. Save module outputs under `generated.protocol`.
4. Let the public workflow populate `template_fields` through its internal
   retrospective adapter during `generate`.
5. Generate the named source Markdown, complete the source Markdown approval loop, then render final outputs.
6. Render the protocol DOCX after approval.

## Module 1: Introduction & Objectives2

Use formal clinical protocol style. Return JSON only.

Inputs:

- Study Title: `study.title`
- Study Design: `design.study_design`
- Background: `study.background`
- Unmet Medical Need: `study.unmet_need`
- Hypothesis: `study.hypothesis`
- Key Objectives: `objectives`
- Key Endpoints: `endpoints`
- Assessments: `procedures.visit_schedule`, `procedures.assessments`, or `procedures.data_sources`

Output keys to save under `generated.protocol`:

```json
{
  "shortTitle": "",
  "introduction": "",
  "objectivesIntro": "",
  "primaryOutcomes": "",
  "secondaryOutcomes": "",
  "exploratoryOutcomes": ""
}
```

Rules from n8n:

- `shortTitle`: write a concise short title derived from the full title.
- `introduction`: write two short paragraphs using Background and Unmet Medical Need. The final sentence must start with "The purpose of this study is to".
- `objectivesIntro`: start with "The objective of the study is to" and restate the main objective using objectives and hypothesis.
- `primaryOutcomes`: use only primary endpoints, one bullet per endpoint.
- `secondaryOutcomes`: use only secondary endpoints, one bullet per endpoint, or empty string.
- `exploratoryOutcomes`: use only exploratory endpoints, one bullet per endpoint, or empty string.
- Do not invent data, endpoints, citations, or numbers.
- Do not use em dashes.
- Use the bullet prefix `• ` in the raw module output. The n8n field mapper converts bullets to the template spacing style.

## Module 2: Population Variables2

Use formal clinical protocol style. Return JSON only.

Inputs:

- Study Design: `design.study_design`
- Sample Size: `population.sample_size`
- Sample Justification: `population.sample_justification` or `statistics.sample_size_justification`
- Inclusion Criteria: `population.inclusion_criteria`
- Exclusion Criteria: `population.exclusion_criteria`

Output keys to save under `generated.protocol`:

```json
{
  "populationLong": "",
  "inclusionCriteria": "",
  "exclusionCriteria": ""
}
```

Rules from n8n:

- `populationLong`: write one paragraph incorporating planned sample size, inclusion/exclusion filtering, and analysis population. For retrospective records/video review, do not force prospective consent language if it is not applicable.
- `inclusionCriteria`: preserve the full inclusion section, including notes and bullets.
- `exclusionCriteria`: preserve the full exclusion section, including notes and bullets.
- Do not invent criteria or numbers.

## Module 3: Study Design & Methods2

Use formal clinical protocol style. Return JSON only.

Inputs:

- Study Title: `study.title`
- Study Design: `design.study_design`
- Background: `study.background`
- Key Objectives: `objectives`
- Hypothesis: `study.hypothesis`
- Endpoints: `endpoints`
- Assessments Schedule: `procedures.visit_schedule`, `procedures.assessments`, or `procedures.data_sources`
- Number of Sites: `sites`
- Inclusion Criteria: `population.inclusion_criteria`
- Exclusion Criteria: `population.exclusion_criteria`
- Facility Name: `sites.0.facility.name`
- Sample Size: `population.sample_size`
- Sample Justification: `population.sample_justification`

Output keys to save under `generated.protocol`:

```json
{
  "studyDesignLong": "",
  "methods": "",
  "studyProcedure": "",
  "studyProcedureBullets": ""
}
```

Rules from n8n:

- `studyDesignLong`: expand the design, number of sites, endpoints, and assessment schedule. Mention timepoints only if provided.
- `methods`: describe bias-minimization procedures.
- `studyProcedure`: describe case identification at the facility. Include privacy handling: data are de-identified with a numbering system, PHI does not leave the facility, and an internal cross-reference sheet is maintained when applicable.
- `studyProcedureBullets`: generate only for comparative platform/group studies or specific selection logic. Include simple bullets for Study Groups and Case Selection. If generated, end `studyProcedure` with a bullet header and start this field directly with bullets.
- Do not invent outcomes, procedures, masking, timepoints, or measurements.

## Module 4: Statistics & Sample Size2

Use formal clinical retrospective protocol style. Return JSON only.

Inputs:

- Study Title: `study.title`
- Study Design: `design.study_design`
- Primary Objective: `objectives.primary`
- Key Endpoints: `endpoints`
- Inclusion Criteria: generated `inclusionCriteria` from Module 2
- Sample Size: `population.sample_size` plus `population.sample_justification`
- Statistical Analysis Plan: `statistics.analysis_plan` or `statistics.methodology`

Output keys to save under `generated.protocol`:

```json
{
  "sampleSizeJustification": "",
  "analysisDataSets": "",
  "analysisDataSetsBullets": "",
  "statisticalMethodology": "",
  "statisticalConsiderations": ""
}
```

Rules from n8n:

- `sampleSizeJustification`: formal paragraph using the provided rationale.
- `analysisDataSets`: short introductory paragraph for section 9.1. Do not include bullets in this field.
- `analysisDataSetsBullets`: bullet list of key variables/endpoints analyzed, with variable name and measurement/derivation. Include Yes/No definitions where applicable.
- `statisticalMethodology`: structured description of statistical methods for primary and secondary endpoints.
- `statisticalConsiderations`: software, significance level, missing data, multiplicity, and related considerations.
- Do not invent tests, software versions, alpha values, or missing-data rules.

## n8n Template Fields

After the four modules are complete, populate legacy template fields:

```bash
python3 scripts/workflow.py --run-dir <run-dir> --stage generate
```

This writes `template_fields` in `study.reference.json`. The renderer overlays those fields at the template root, so n8n-style placeholders such as `{AI_shortTitle}` and `{protocolNumber}` resolve without changing the client template.

Expected n8n retrospective protocol placeholders:

```text
{AI_shortTitle}
{date}
{title}
{protocolNumber}
{irbName}
{irbAdress}
{sponsortName}
{sponsortAdress}
{fundingSourceName}
{fundingSourceAdress}
{fundingSourceClarification}
{testArticle(s)}
{investigatorName}
{subInvestigatorHas}
{subInvestigatorName}
{investigatorTitle}
{facilityName}
{facilityCity}
{AI_introduction}
{AI_objectivesIntro}
{AI_primaryOutcome}
{AI_secondaryOutcomes}
{AI_exploratoryOutcomes}
{AI_populationLong}
{AI_inclusionCriteria}
{AI_exclusionCriteria}
{AI_studyDesignLong}
{AI_methods}
{AI_analysisDataSets}
{AI_analysisDataSetsBullets}
{AI_statisticalMethodology}
{AI_statisticalConsiderations}
{sampleSizeJustification}
{referencesExists}
{references}
{AI_studyProcedure}
{AI_studyProcedureBullets}
```

Notes:

- Keep the n8n typo `irbAdress` and `sponsortName` because the template may contain those exact placeholders.
- The n8n workflow derives `protocolNumber` from investigator initials and the current year when no explicit number exists. Prefer a reviewed `meta.protocol_number` if provided, but never ask for it solely to pass retrospective intake.
- Preserve `template_fields` for rendering, but keep clinical facts and generated prose in the structured reference sections.
