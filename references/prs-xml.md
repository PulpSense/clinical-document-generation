# ClinicalTrials.gov PRS XML

Use this reference for prospective and ambispective XML generation.

## Contract

Use `assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml` as the canonical PRS XML skeleton when the client has not supplied a newer PRS template. Copy it to:

```text
templates/study.template.xml
```

Do not create XML from scratch. Preserve the PRS element names, major order, required legacy fields, empty optional fields, `overall_contact`, `overall_contact_backup`, camelCase and snake_case duplicate PRS fields, and the corrected outcome taxonomy.

Retrospective studies do not generate XML in the n8n workflow unless the user/client explicitly overrides the branch and supplies a retrospective XML template.

## Required Source Fields

Before creating the named source Markdown, prospective and ambispective references must include these reviewer-controlled PRS fields:

- `regulatory.prs.provider_study_id`
- `regulatory.prs.org_name`
- `regulatory.prs.overall_status`
- `regulatory.prs.irb_approval_status`
- `regulatory.prs.study_uid`
- `parties.overall_contact`

Do not guess these fields. If they are absent, keep them missing or add `needs_review`; `scripts/check_required_inputs.py` must block source Markdown creation until they are provided.

Use `regulatory.prs.last_follow_up_date_type` whenever `procedures.last_follow_up_date` or `regulatory.prs.last_follow_up_date` is present.

## Mapper And Renderer

After the branch n8n mapper, run:

```bash
python scripts/build_prs_xml_fields.py --run-dir <run-dir>
```

This script:

- writes every PRS placeholder into `template_fields`, using empty strings for optional unknown values
- sets `regulatory.xml_profile` to `clinicaltrials-prs`
- sets `template_fields.__prs_counts` for `intervention`, `arm_group`, `primary_outcome`, `secondary_outcome`, and `other_outcome`
- adds `needs_review` items for missing required PRS fields instead of inventing values

Then validate and render:

```bash
python scripts/validate_reference.py --run-dir <run-dir> --require-approval
node scripts/render_templates.mjs --run-dir <run-dir> --require-approval
python scripts/validate_prs_xml.py --run-dir <run-dir>
```

The renderer uses `__prs_counts` to remove unused repeated blocks or clone the last exemplar block when the real study has more repeated items than the template contains.

## Corrected-Pattern Rules

The client-corrected XML showed these rules:

- `orgName` maps to `/clinical_study/id_info/org_name`.
- `leadSponsorAgency` maps to `/clinical_study/sponsors/lead_sponsor/agency`.
- Leave `collaboratorAgency` blank unless the source has a collaborator.
- `responsiblePartyType` defaults to `Sponsor` unless the source explicitly says otherwise.
- Include `overall_contact` and `overall_contact_backup`.
- Use the client PRS study-design structure for this template family, but preserve the reviewed PRS study type. Interventional studies must render `studyType` as `Interventional` with an `interventional_design` block; observational studies must render `studyType` as `Observational` with an `observational_design` block.
- Normalize client-facing controlled fields before rendering XML: `Submitted, pending approval.` and `Submitted` become `Pending`; `Non-Probability Simple` becomes `Non-Probability Sample`; enrollment and `number_of_groups` are numeric only; age limits use PRS format such as `50 Years`; PRS date fields use `YYYY-MM-DD`.
- Use the shared study/outcome UID across primary, secondary, and other outcome blocks when the client PRS export follows that pattern.
- Multi-arm studies must have separate `intervention` and `arm_group` blocks. Do not combine arms into one label or description.
- Keep primary, secondary, and other outcomes separate. Do not downgrade `other_outcome` records into secondary outcomes.
- Every outcome block must include `outcome_measure`, `outcome_time_frame`, `uid`, and `outcome_description/textblock`.
- Use country `United States`, not `USA`.
- Do not emit placeholder URLs such as `http://`.
- Do not emit unresolved placeholders, markdown, comments, or exact literal values `None` or `N/A`; use empty strings for optional unknown values.

## Defaults

Use these defaults only when the source does not explicitly provide a value:

- `providerName`: `NLM_DES`
- `responsiblePartyType`: `Sponsor`
- `fdaRegulatedDrug`: `Yes`
- `fdaRegulatedDevice`: `No`
- For clearly device-regulated studies, set `fdaRegulatedDevice` to `Yes` and `fdaRegulatedDrug` to `No`.
- `postPriorToApproval`: `No`
- `exportedFromUs` and `exportFromUs`: `Yes`
- `pediatricPostmarketSurveillance`: `No`
- `hasDmc`: `No`
- `isINDStudy` and `isIndStudy`: `No`
- `delayedPosting`: `No`
- `sharingIPD` and `sharingIpd`: `No`

`irbApprovalStatus` has no default. It must come from the source/client correction.
