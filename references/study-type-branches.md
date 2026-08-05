# Study Type Branches

Use this guide before structuring `reference/study.reference.json` and before choosing templates.

## Branch Selection

Normalize `meta.study_type` to one of:

- `Prospective`
- `Ambispective`
- `Retrospective`

Treat `ambipective` as a typo for `Ambispective`.

If the study type is missing or unclear, set `meta.study_type` to `null`, set `meta.document_set` to `[]`, and add a `needs_review` item.

## Document Sets

Use these defaults from the existing workflow:

```json
{
  "Prospective": ["protocol_docx", "icf_docx", "xml"],
  "Ambispective": ["protocol_docx", "icf_docx", "xml"],
  "Retrospective": ["protocol_docx"]
}
```

`short_docx` is optional for all branches when a shorter summary is requested or when a `short.template.docx` is intentionally provided.

## Template Expectations

- `protocol_docx` -> `templates/protocol.template.docx` -> `output/protocol.docx`
- `icf_docx` -> `templates/icf.template.docx` -> `output/icf.docx`
- `short_docx` -> `templates/short.template.docx` -> `output/short.docx`
- `xml` -> `templates/study.template.xml` -> `output/study.xml`

The renderer uses `meta.document_set`. Templates that are present but not listed in `meta.document_set` are not rendered.

## Required Reference Focus

### Prospective

Prospective studies require enough detail for protocol, participant-facing ICF, and XML:

- Sponsor, investigator affiliation, sites, objectives, endpoints, procedures, inclusion/exclusion criteria.
- Visit schedule, interventions/test articles, risks, benefits, privacy, compensation/reimbursement when applicable.
- PRS XML-specific regulatory values under `regulatory.prs`, including provider study ID, org name, overall status, IRB approval status, study UID/outcome UID, and overall contact.

### Ambispective

Ambispective studies follow the prospective document set, but the reference must separate retrospective and prospective data collection:

- Existing/historical data sources.
- Prospective visits, procedures, or follow-up.
- Which endpoints come from historical review versus prospective collection.
- ICF language appropriate to the prospective portion.
- PRS XML-specific regulatory values under `regulatory.prs`, using the same source-controlled fields as prospective studies.

### Retrospective

Retrospective studies follow the protocol-only branch from the current workflow:

- Existing records/data/video sources.
- Privacy/de-identification protocol.
- Waiver or consent rationale if supplied by the source material.
- No ICF or XML unless the user/client explicitly requests them and provides templates. The inspected n8n workflow has no retrospective XML generation/upload path.

## Validation

Run:

```bash
python3 scripts/validate_reference.py --run-dir <run-dir>
```

Validation checks `meta.study_type`, `meta.document_set`, required branch fields, required templates for that branch, and placeholders in active templates.
