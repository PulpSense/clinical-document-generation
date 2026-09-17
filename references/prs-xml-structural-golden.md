# PRS XML structural golden

`assets/client-templates/reference/prs-manual-reference.xml` is the client-derived structural architecture authority for element names, direct-child order, optional-node presence, and repeated-block taxonomy.

`assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml` is the separate sanitized generation/format template. It contains placeholders only, and populated output from it must validate against the structural reference.

The checker deliberately ignores values and repeated counts. Counts are derived from approved structured source data and are checked by `validate_prs_xml.py`. The golden includes separate `intervention`, `arm_group`, `primary_outcome`, `secondary_outcome`, and `other_outcome` block shapes. The defective historical output is retained at `tests/fixtures/prs-xml-defective.xml` and must fail the checker.
