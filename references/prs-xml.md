# ClinicalTrials.gov PRS XML

PRS XML is required for Prospective and Ambispective studies and omitted for
Retrospective studies.

## Structural authority

Use this client-derived structural architecture reference:

`assets/client-templates/reference/prs-manual-reference.xml`

Use this separate generation/format template:

`assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml`

Generated output from the template must validate against the structural
reference. Preserve its element names, major order, optional empty nodes,
duplicate compatibility fields, contact topology, and
primary/secondary/other outcome taxonomy.

Python owns XML structure, escaping, aliases, stable UIDs, and repeated blocks.
Repeated counts come from the approved source for interventions, arms, sites,
and structured outcomes. Every populated outcome requires a measure and time
frame.

The PRS subagent may draft only:

- `brief_summary`
- `detailed_description`

It cannot return XML markup or alter structural fields.

## Validation and delivery

Run only the public lifecycle:

```bash
python3 scripts/workflow.py --run-dir <run-dir> --stage validate
python3 scripts/workflow.py --run-dir <run-dir> --stage generate
```

The structural-reference and generation-template hashes bind drafting
governance, candidate caching, and the delivery manifest. Any authority change
invalidates stale drafts/output. XML
structure or content failure blocks the complete package; never deliver
Protocol/ICF without the required passing XML.
