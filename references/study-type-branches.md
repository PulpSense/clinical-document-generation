# Study-Type Branches

The branch contract is deterministic:

| Study type | Required outputs | Drafting batches |
|---|---|---|
| Prospective | `protocol.docx`, `icf.docx`, `study.xml` | three Protocol batches + one ICF batch, then PRS narrative |
| Ambispective | `protocol.docx`, `icf.docx`, `study.xml` | three Protocol batches + one ICF batch, then PRS narrative |
| Retrospective | `protocol.docx` | three Protocol batches |

There is no optional short-document branch.

Prospective and Ambispective share the same obligatory input contract.
Ambispective output additionally discloses the historical-plus-prospective data
collection model. Retrospective uses its separate input and Protocol section
contract and never renders ICF or PRS XML.

For Prospective/Ambispective, `meta.icf_template` must be `Advarra` or
`Sterling`. Only bundled templates may be selected.

Branch resolution, output names, section order, drafting batches, and
publication are owned by `scripts/contracts.py` and `scripts/workflow.py`.
Do not override `meta.document_set` to add or remove outputs.

Validate a prepared and approved run with:

```bash
python3 scripts/workflow.py --run-dir <run-dir> --stage validate
```
