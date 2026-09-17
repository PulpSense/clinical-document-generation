# Clinical Document Generation v2

## Summary

The new version will replace the current chain of overlapping scripts with one clear workflow and six focused Python modules.

The skill will identify the study type, collect the required information, and generate a reviewer-editable Source of Truth. The client can correct and approve that file before any final documents are generated.

After approval, specialized subagents will draft the clinical narrative. Python will assemble the approved content into the client templates, generate the required files, validate them, and release the complete package only when everything passes.

## Complete Loop

```text
Client provides study information and source documents
-> preserve the original input
-> select Prospective, Ambispective, or Retrospective
-> check the required fields for that branch
-> generate the Source of Truth Markdown
-> client edits and approves the Source of Truth
-> launch only the subagents required for that branch
-> subagents draft their assigned sections in parallel
-> after Protocol Foundations passes, draft the two PRS narrative descriptions
-> Python merges accepted sections in the correct order
-> Python renders the documents using the contracted templates
-> one read-only verifier checks content and cross-document consistency
-> another read-only verifier checks every rendered Protocol and ICF page
-> Python checks completeness, XML structure, evidence, and release readiness

PASS
-> release the complete document package

FAIL
-> retry only the failed section or formatting stage
-> continue targeted, progress-sensitive repair inside the original 45-minute deadline
-> if the deadline or a non-repairable safety/integrity condition stops the run, release nothing and produce a Repair Report

APPROVED SOURCE CHANGES
-> invalidate the previous approval
-> return to the Source of Truth step
```

## Structure

The production implementation will contain six Python scripts:

- `workflow.py`: the only public entrypoint; controls preparation, approval, validation, generation, retries, and delivery.
- `contracts.py`: defines required inputs, study branches, section contracts, and Source-of-Truth parsing.
- `drafting.py`: assigns sections to subagents, manages targeted retries, and merges accepted drafts by stable section ID.
- `rendering.py`: creates the Protocol and ICF DOCX files using the bundled client templates.
- `quality.py`: checks content, shared facts, document structure, visual rendering, and release readiness.
- `prs_xml.py`: preserves the existing PRS XML mapping and validation behavior.

Templates, approved clinical boilerplate, prompts, and contracts will be resource files, not additional workflow scripts.

### Skill Folder

```text
clinical-document-generation/
|-- SKILL.md                    # Instructions used by Hermes
|-- README.md                   # Installation and usage guide
|-- scripts/
|   |-- workflow.py             # Public workflow and delivery loop
|   |-- contracts.py         # Branch, source, and section contracts
|   |-- drafting.py             # Subagent assignments and retries
|   |-- rendering.py            # Protocol and ICF DOCX generation
|   |-- quality.py              # Content, formatting, and release checks
|   `-- prs_xml.py              # Existing PRS XML generation
|-- resources/
|   |-- templates/              # Contracted Protocol and ICF templates
|   |-- contracts/              # Section definitions for each document
|   |-- boilerplate/            # Approved reusable clinical language
|   `-- prompts/                # Scoped instructions for subagents
|-- tests/                      # Branch and document acceptance tests
`-- runs/                       # Source, approvals, drafts, reports, and outputs
```

Only the six files inside `scripts/` are production workflow scripts. Adding or updating a template, contract, prompt, or approved boilerplate entry will not create another workflow script.

## Subagents

Subagents run only after the client approves the Source of Truth. Each receives only the approved fields needed for its assigned sections, together with controlled clinical boilerplate.

The available drafting groups are:

1. Protocol foundations: rationale, objectives, population, and study design.
2. Protocol operations: procedures, visits, measurements, and schedules.
3. Protocol analysis and oversight: endpoints, statistics, safety, ethics, and risks.
4. ICF narrative.
5. PRS brief and detailed descriptions.

Prospective and Ambispective studies use all five groups. Retrospective studies use only the three Protocol groups.

The ICF stays as one unified drafting batch to preserve a consistent participant-facing voice. The PRS batch runs only after Protocol Foundations passes and drafts only the brief and detailed descriptions; Python retains the client-approved XML structure and mapping.

Subagents are used for context-sensitive clinical writing. They are not used for input validation, approval state, section ordering, Word formatting, XML mapping, pass/fail decisions, or delivery. Those responsibilities stay in deterministic Python so the result remains stable and auditable.

Subagents may adapt approved boilerplate, but they may not invent study-specific procedures, risks, benefits, safety obligations, or regulatory claims.

After assembly, two additional read-only subagents review the complete package: one checks content and cross-document consistency, and one checks every rendered Protocol and ICF page. They report exact retry targets but cannot rewrite or release files.

## Outputs and Release

- Prospective: Protocol DOCX, ICF DOCX, and PRS XML.
- Ambispective: Protocol DOCX, ICF DOCX, and PRS XML.
- Retrospective: Protocol DOCX.

The skill will reuse sections that already passed and retry only failed parts inside the one persisted 45-minute Desktop operation deadline. It will not stop repairable work because of a fixed attempt count. The full branch package will be released together; partial document packages will never be delivered.

The DOCX files will be built for Microsoft Word. Visual checks will use the best compatible renderer available on the computer and record which renderer was used.
