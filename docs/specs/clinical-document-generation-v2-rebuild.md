# Clinical Document Generation v2 Rebuild

## Problem Statement

The clinical document generation skill has grown into a difficult-to-maintain collection of more than fifteen production scripts with overlapping responsibilities and multiple internal entrypoints. The apparent workflow is simple—classify a study, produce a reviewer-editable Source-of-Truth Markdown file, wait for approval, and generate the required documents—but the implementation obscures that lifecycle and makes failures hard to diagnose or repair.

The current test suite can pass while required document sections remain empty or weak. Protocol sections and tables can be omitted, ICF output can escape equivalent rendering and visual review, formatting defects can survive delivery, and a renderer failure can be reported too optimistically. The generated DOCX may contain malformed hierarchy, stale or inaccurate TOC content, clipped headers, orphaned headings, split table rows, placeholders, inconsistent styles, or internal drafting language. These are delivery failures even when the package is syntactically valid.

Clinical content generation is also too coarse. Giving one agent an entire document makes targeted retries difficult, but assigning the same arbitrary number of agents to every document fragments tone and creates unnecessary contradiction boundaries. Protocol, ICF, and PRS XML have different narrative shapes and must not receive identical agent topologies.

The client requires Microsoft Word-compatible DOCX output. Candidate construction remains independent of office software, while installation requires a verified host Microsoft Word or LibreOffice capability for DOCX-to-PDF Render Assurance. The skill must state honestly which Active Renderer produced Visual QA evidence and must not claim Word validation when Word was not used.

The PRS XML path requires special protection. The client-confirmed manual XML is the PRS XML Structural Reference. A separate generated example is defective: it omits much of the required XML shape, changes element ordering and repeated-block taxonomy, and collapses interventions, arms, and other outcomes. The replacement must preserve the existing client-approved XML structure and mapping rather than redesigning a path that already has a correct reference.

The user needs a clean, manageable replacement that reliably produces complete Branch Document Sets, keeps all required leaf sections substantive when Required Source Inputs are complete, prevents unsupported study-specific claims, renders cleanly, retries only failed work, and releases either the complete passing package or a precise Repair Report.

## Solution

Rebuild the skill around one public workflow and six focused Python production modules. The public lifecycle will be `prepare`, `approve`, `validate`, and `generate`; every client run will pass through that lifecycle instead of invoking internal scripts independently.

The workflow will preserve the Source Intake Packet, classify the study branch, apply the appropriate Branch Input Contract, and collect all blocking Required Source Inputs together. Prospective and Ambispective studies will share one semantic input contract; Retrospective studies will use a distinct contract. Existing obligatory n8n field meanings will remain supported even if internal canonical names change.

The workflow will generate a reviewer-editable Source-of-Truth Markdown file containing all study facts, regulatory values, and structured repeated data needed by the active branch. The client will edit or approve that exact file once. Any later source change will invalidate the approval and begin a new immutable Run Revision.

After approval, Hermes will launch versioned Drafting Batches rather than one agent per document. Prospective and Ambispective runs will launch three Protocol batches and one unified ICF batch in parallel. After Protocol Foundations passes, one narrow PRS narrative batch will draft only the brief and detailed descriptions. Retrospective runs will launch only the three Protocol batches. Python will own deterministic merging, templates, DOCX construction, PRS XML mapping, validation, retries, evidence, and release.

Every generated DOCX context will use one Document Section Contract as the authority for hierarchy, section roles, minimum evidence, allowed content modes, Fixed Clinical Boilerplate, drafting instructions, and completeness checks. Every required leaf section must be substantive; a Container Section may group complete children without duplicating their prose.

After deterministic assembly, one package-wide read-only verifier will check content and Cross-Document Consistency, and another will inspect every rendered Protocol and ICF page. Failed section IDs or layout stages will receive targeted retries, with three total attempts per target. Accepted Section Drafts will be reused when their inputs and governing resources have not changed.

The workflow will deliver the Branch Document Set atomically. Prospective and Ambispective require Protocol DOCX, ICF DOCX, and PRS XML. Retrospective requires Protocol DOCX. If any required artifact or Delivery Gate fails after retries, no partial package will be released and the workflow will produce a classified Repair Report.

## User Stories

1. As a clinical document requester, I want Hermes to recognize a clinical study document request, so that I do not need to know internal script names.
2. As a clinical document requester, I want one conversational Run Lifecycle, so that the skill feels like one coherent capability rather than a collection of commands.
3. As a clinical document requester, I want the workflow to classify Prospective, Ambispective, and Retrospective studies, so that the correct branch requirements are selected.
4. As a clinical document requester, I want Prospective and Ambispective studies to produce a Protocol, ICF, and PRS XML, so that I receive the complete required package.
5. As a clinical document requester, I want Retrospective studies to produce only a Protocol, so that irrelevant ICF and XML work is not performed.
6. As a reviewer, I want every supplied source preserved as part of the Source Intake Packet, so that the run remains auditable.
7. As a reviewer, I want each Evidence File retained without silent rewriting, so that I can trace the origin of extracted facts.
8. As a reviewer, I want the Extraction Pass to preserve conflicting Field Candidates, so that ambiguity is resolved before approval.
9. As a reviewer, I want all missing or conflicting Required Source Inputs requested together, so that I am not questioned one field at a time.
10. As a reviewer, I want a focused supplemental source question only when minimum evidence is genuinely absent, so that sparse but sufficient studies can proceed without unnecessary interrogation.
11. As a reviewer, I want Prospective and Ambispective studies to share one Branch Input Contract, so that equivalent branch inputs behave consistently.
12. As a reviewer, I want Retrospective studies to use a distinct Branch Input Contract, so that retrospective-specific requirements remain focused.
13. As a maintainer, I want the semantic obligations of existing obligatory n8n fields preserved, so that current client intake integrations remain compatible.
14. As a maintainer, I want canonical field names to be independent from legacy n8n spelling, so that internal design can improve without breaking compatibility.
15. As a reviewer, I want visits, schedules, endpoints, arms, interventions, sites, and contacts represented structurally before approval, so that repeated document content is governed by the approved source.
16. As a reviewer, I want the Source-of-Truth Markdown to be readable and editable, so that I can correct study facts without editing JSON or code.
17. As a reviewer, I want the Source-of-Truth Markdown to include every branch-required fact, so that final generation does not depend on hidden prompt context.
18. As a reviewer, I want the Source-of-Truth Markdown to distinguish source facts from generated narrative, so that approval remains meaningful.
19. As a reviewer, I want to approve one exact Source-of-Truth Markdown version, so that the generation boundary is unambiguous.
20. As a reviewer, I want silence or the original generation request not to count as approval, so that final documents cannot be generated accidentally.
21. As a reviewer, I want an edited Source-of-Truth Markdown file parsed exactly as supplied, so that my corrections become authoritative.
22. As a reviewer, I want a change to approved source information to invalidate approval, so that stale drafts cannot be delivered.
23. As a reviewer, I want every source change to create a new immutable Run Revision, so that earlier evidence and outputs remain auditable.
24. As a reviewer, I want only the newest passing Run Revision presented as client-facing, so that superseded artifacts are not confused with the current package.
25. As a Protocol reviewer, I want Prospective and Ambispective Protocols to follow the corrected 1–19 hierarchy, so that all expected sections are present.
26. As a Protocol reviewer, I want Retrospective Protocols to follow the corrected bundled 1–13 hierarchy, so that retrospective output matches its established template family.
27. As a Protocol reviewer, I want obvious numbering defects corrected rather than copied, so that the generated hierarchy remains internally coherent.
28. As a Protocol reviewer, I want every required leaf section to contain substantive content, so that heading-only sections cannot pass.
29. As a Protocol reviewer, I want Container Sections allowed to group complete child sections without duplicate prose, so that the document is complete without unnecessary repetition.
30. As a Protocol reviewer, I want a section to fail when it is merely nonempty but unsupported, so that filler cannot satisfy completeness.
31. As a Protocol reviewer, I want each section checked against its declared minimum evidence, so that required concepts are present.
32. As a Protocol reviewer, I want sufficient but sparse evidence to produce concise text, so that the system does not pad the document.
33. As a Protocol reviewer, I want missing minimum evidence to return the run to source review, so that agents do not invent study-specific details.
34. As a Protocol reviewer, I want approved Fixed Clinical Boilerplate available for stable cross-study language, so that common clinical sections do not require reinvention.
35. As a Protocol reviewer, I want Fixed Clinical Boilerplate changes versioned, so that later runs and regressions remain reproducible.
36. As a Protocol reviewer, I want operational procedures, visits, measurements, and schedules drafted as a focused batch, so that those connected sections remain coherent.
37. As a Protocol reviewer, I want rationale, objectives, population, eligibility, and design drafted as a focused batch, so that scientific foundations remain consistent.
38. As a Protocol reviewer, I want endpoints, statistics, safety, ethics, risks, and oversight drafted as a focused batch, so that analysis and safeguards remain aligned.
39. As a Protocol reviewer, I want Data-Driven Tables generated from approved structured rows, so that tables are not fabricated from free-form prose.
40. As a Protocol reviewer, I want a table caption without its required table to fail delivery, so that references cannot conceal missing structures.
41. As a Protocol reviewer, I want schedules and other repeated structures rendered as Real Word Constructs, so that the document remains editable and stable.
42. As a Protocol reviewer, I want headings, lists, fields, tables, headers, and footers represented with Word semantics, so that formatting survives editing and repagination.
43. As a Protocol reviewer, I want natural content-driven pagination, so that correct content is not distorted to match exact reference page breaks.
44. As a Protocol reviewer, I want branding and visual character preserved from the Contracted Template, so that the output remains recognizable to the client.
45. As an ICF reviewer, I want the skill to support the existing Advarra Prospective, Advarra Ambispective, and shared Sterling template families, so that branch and IRB choices remain available.
46. As an ICF reviewer, I want one unified ICF Drafting Batch, so that participant-facing language maintains one voice.
47. As an ICF reviewer, I want the selected template's hierarchy and legal boilerplate preserved, so that the ICF remains recognizable to the client.
48. As an ICF reviewer, I want only study-specific facts replaced, so that established Client ICF Language is not generically rewritten.
49. As an ICF reviewer, I want the Prospective template's invalid Legal Rights reference repaired without inventing an injury section, so that the template defect is corrected conservatively.
50. As an ICF reviewer, I want the Ambispective existing-records disclosure placed inside the study-procedures section, so that participants encounter it in the correct context.
51. As an ICF reviewer, I want one Sterling template with distinct Prospective and Ambispective contracts, so that shared presentation does not erase branch behavior.
52. As an ICF reviewer, I want every visible ICF leaf section covered and substantive, so that legal or participant-facing sections are not empty.
53. As an ICF reviewer, I want all visible headings to use real Word heading styles, so that the document remains navigable and consistent.
54. As an ICF reviewer, I want signature structures preserved, so that execution-ready consent pages are not damaged.
55. As an ICF reviewer, I want comments, tracked changes, and hidden review content removed before delivery, so that internal review material does not reach participants.
56. As an ICF reviewer, I want arbitrary eye, device, cataract, or other stale study details rejected, so that one template's prior facts cannot contaminate another study.
57. As a registry specialist, I want the client-approved manual XML treated as the PRS XML Structural Reference, so that the accepted shape governs generation.
58. As a registry specialist, I want the defective generated XML retained only as a negative regression example, so that its omissions are never normalized as expected behavior.
59. As a registry specialist, I want the manual reference's study-specific values excluded from new studies, so that structural reference data cannot leak into generated content.
60. As a registry specialist, I want Python to preserve XML element names and major ordering, so that PRS import compatibility remains stable.
61. As a registry specialist, I want optional empty nodes preserved where required by the reference contract, so that the shape is not simplified incorrectly.
62. As a registry specialist, I want interventions and arm groups kept as separate repeated blocks, so that multi-arm studies are represented accurately.
63. As a registry specialist, I want primary, secondary, and other outcomes to remain distinct, so that outcome taxonomy is not collapsed.
64. As a registry specialist, I want every outcome block to carry the required measure, timeframe, UID, and description structure, so that repeated outcomes remain valid.
65. As a registry specialist, I want the existing PRS XML mapper and validation behavior preserved behind a dedicated module, so that unrelated document changes cannot destabilize it.
66. As a registry specialist, I want one narrow PRS narrative batch to draft only brief and detailed descriptions, so that narrative quality improves without granting agents authority over XML.
67. As a registry specialist, I want the PRS narrative batch to run after Protocol Foundations passes, so that registry descriptions align with accepted Protocol language.
68. As a registry specialist, I want XML generation to fail on a structural difference from the approved contract, so that a syntactically valid but incomplete XML cannot pass.
69. As a reviewer, I want subagents to receive only the approved fields relevant to their Drafting Batch, so that unrelated context cannot introduce contradictions.
70. As a reviewer, I want subagents to receive controlled boilerplate and section contracts, so that their authority is explicit.
71. As a reviewer, I want subagents blocked from inventing procedures, risks, benefits, safety obligations, or regulatory claims, so that study-specific content remains source-grounded.
72. As a reviewer, I want Section Drafts keyed by stable section IDs, so that deterministic merging and targeted retries are possible.
73. As a reviewer, I want Drafting Batches to run concurrently when their prerequisites are satisfied, so that quality does not require unnecessary serial latency.
74. As a reviewer, I want the Drafting Batch topology versioned and stable during a run, so that cost and ownership remain reproducible.
75. As a reviewer, I want a failed section retried within its existing Drafting Batch, so that the system does not unpredictably create new agent boundaries.
76. As a reviewer, I want accepted Section Drafts reused when their source and governing resources are unchanged, so that retries do not rewrite good content.
77. As a reviewer, I want an explicit redraft operation separate from ordinary generation, so that accepted content is not refreshed accidentally.
78. As a reviewer, I want a package-wide read-only content verifier, so that weak narrative and Cross-Document Consistency problems are found independently.
79. As a reviewer, I want a package-wide read-only visual verifier, so that every rendered Protocol and ICF page receives independent inspection.
80. As a reviewer, I want verifier agents to return findings and retry targets without rewriting, so that repair remains controlled.
81. As a reviewer, I want shared facts compared across the Canonical Approved Source, Protocol, ICF, and PRS XML, so that document contradictions block release.
82. As a reviewer, I want each failed target limited to three total attempts, so that retries are bounded and understandable.
83. As a reviewer, I want a failure after the retry limit classified in a Repair Report, so that the next required action is clear.
84. As a reviewer, I want Repair Report findings classified as source evidence, drafting, contradiction, structure, renderer, or visual failures, so that remediation is routed correctly.
85. As a client, I want standards-compliant DOCX output, so that files can be opened and edited in Microsoft Word.
86. As a client, I want Microsoft Word treated as the compatibility target, so that local fallback rendering is not mistaken for the client's environment.
87. As a QA reviewer, I want the Active Renderer selected from verified host Microsoft Word and LibreOffice, so that DOCX-to-PDF evidence uses an explicit supported prerequisite.
88. As a QA reviewer, I want the Active Renderer identity recorded, so that every visual claim names the environment that produced it.
89. As a QA reviewer, I want the workflow forbidden from claiming Word validation unless Word produced the evidence, so that validation statements remain truthful.
90. As a QA reviewer, I want a missing renderer to prevent a visual-pass claim, so that structural validation is not confused with rendered validation.
91. As a QA reviewer, I want every Protocol and ICF page inspected, so that defects cannot hide on unreviewed pages.
92. As a QA reviewer, I want clipping, overlap, unexpected blank pages, orphan headings, split rows, table overflow, duplicate sections, and style drift treated as failures, so that delivery quality is strict.
93. As a QA reviewer, I want a real Word TOC field configured to update on open, so that page references remain maintainable in Word.
94. As a QA reviewer, I want cached TOC display values validated after final pagination, so that local render evidence is internally consistent.
95. As a QA reviewer, I want visual evidence bound to the exact artifact hash, so that later file mutation invalidates certification.
96. As a client, I want all required branch outputs released together, so that I never receive a partially passing package.
97. As a client, I want only the Source-of-Truth Markdown, final Branch Document Set, or Repair Report exposed by default, so that internal artifacts do not clutter delivery.
98. As a maintainer, I want a Generation Manifest recording source, contracts, boilerplate, templates, model, renderer, evidence, and artifact hashes, so that every result is reproducible.
99. As a maintainer, I want six focused production modules behind one public workflow, so that the codebase remains manageable.
100. As a maintainer, I want the old script collection removed only after the Branch Acceptance Corpus passes, so that simplification does not sacrifice proven behavior.
101. As a QA reviewer, I want office tool failure to advance only between verified host Word and LibreOffice while PDFium failure stops exactly, so that mandatory Visual QA is neither skipped nor falsely passed through an alternate backend.
102. As an administrator, I want installation activation to be conditional on an end-to-end Render Assurance smoke and to retain the previous verified release, so that updates are atomic.

## Implementation Decisions

### Public workflow and lifecycle

- `workflow.py` is the only public production interface and exposes `prepare`, `approve`, `validate`, and `generate` operations.
- Internal modules are not independent user workflows and are not invoked directly during a client run.
- The Run Lifecycle is Source Intake Packet preservation, branch classification, Required Source Input collection, Source-of-Truth Markdown generation, explicit approval, Drafting Batch execution, deterministic assembly, Delivery Gates, and atomic handoff.
- The workflow fails closed. It never reports a Branch Document Set as passed when a required artifact or Delivery Gate is unresolved.
- A changed Canonical Approved Source invalidates approval, Section Drafts, generated artifacts, and associated evidence and creates a new immutable Run Revision.

### Branch and source contracts

- Prospective and Ambispective share one Branch Input Contract because their obligatory input semantics are the same.
- Retrospective uses a distinct Branch Input Contract because its obligatory inputs and Branch Document Set differ.
- Legacy n8n field names remain accepted through a compatibility projection, but canonical names and domain meanings govern the replacement.
- Required Source Inputs are asked for in one consolidated batch. Optional or ordinary review notes do not become intake blockers.
- A focused supplemental source request is made only when a Required Generated Section lacks minimum evidence and neither approved facts nor Fixed Clinical Boilerplate can support it safely.
- Structured repeated data that feeds lists, tables, visits, endpoints, arms, interventions, sites, contacts, or XML blocks must be represented in Source-of-Truth Markdown before approval.
- Sparse but sufficient inputs generate concise text; the system does not expand content merely to reach a target length.

### Six-module production architecture

- `workflow.py` owns public orchestration, branch selection, approval state, Run Revisions, and atomic delivery.
- `contracts.py` owns Branch Input Contracts and Document Section Contracts, including stable section IDs, hierarchy, roles, minimum evidence, content modes, and retry ownership.
- `drafting.py` owns Drafting Batch planning, Hermes subagent request and response contracts, structured Section Draft validation, accepted-draft reuse, targeted retries, and deterministic contract-order merging.
- `rendering.py` owns Protocol and ICF DOCX construction from Contracted Templates and structured content.
- `quality.py` owns Source Completeness, Content Completeness, Cross-Document Consistency, DOCX structure, package, renderer, visual, evidence, and release gates.
- `prs_xml.py` owns the preserved PRS XML mapping, repeated-block handling, structural comparison, escaping, and validation behavior.
- The six-module target expresses clear ownership and a manageable interface, not a prohibition against small private helpers inside those modules.
- Templates, Document Section Contracts, Fixed Clinical Boilerplate, prompts, schemas, and acceptance fixtures are data resources rather than additional production workflows.
- The replacement is Python-only. No TypeScript or additional implementation language is introduced.
- Python dependencies required for robust DOCX and XML handling are pinned and reproducible.
- Deterministic production scripts do not call a model API directly. Hermes owns subagent orchestration; scripts exchange explicit structured requests and responses with that orchestration layer.

### Document Section Contracts

- Each Protocol and ICF context has one versioned Document Section Contract consumed by drafting, rendering, and validation.
- A contract declares complete hierarchy, stable section IDs, section roles, minimum evidence, allowed content modes, Fixed Clinical Boilerplate, drafting expectations, repeated structures, and completeness rules.
- Allowed content modes are approved source, Fixed Clinical Boilerplate, agent-drafted content, structured rows, or a controlled combination.
- Every required leaf section must be substantive and source-compatible. Nonempty text alone does not pass.
- A Container Section may contain no separate prose when all required descendants are substantive.
- A contract rejects unresolved placeholders, unsupported study-specific claims, internal drafting language, and contradictions.
- Contract and Fixed Clinical Boilerplate changes invalidate affected accepted drafts and rerun the full Branch Acceptance Corpus.

### Drafting Batch topology

- Drafting topology is versioned and contract-defined rather than inferred dynamically during a run.
- Prospective and Ambispective first launch four parallel batches: Protocol Foundations, Protocol Operations, Protocol Analysis and Oversight, and one unified ICF Narrative batch.
- Protocol Foundations covers rationale, objectives, population, eligibility, and study design.
- Protocol Operations covers procedures, visits, assessments, schedules, measurements, and completion rules.
- Protocol Analysis and Oversight covers endpoints, statistics, sample size, safety, ethics, risks, benefits, and oversight.
- The unified ICF batch covers participant-facing study-specific narrative while preserving Client ICF Language and controlled legal text.
- After Protocol Foundations passes, one PRS narrative batch drafts only the brief and detailed study descriptions using relevant approved source fields and accepted Protocol Foundations content.
- Retrospective launches only the three Protocol batches.
- Drafting subagents receive only relevant approved fields, the applicable section contracts, selected Fixed Clinical Boilerplate, and explicitly relevant accepted Section Drafts. They do not receive the raw Source Intake Packet or unrelated drafts.
- Section Draft responses are structured and keyed by stable section ID; free-form whole-document responses are rejected.
- One package-wide read-only content verifier checks source fidelity, section substance, and Cross-Document Consistency after assembly.
- One package-wide read-only visual verifier inspects every rendered Protocol and ICF page after deterministic checks produce render evidence.
- Verifiers return findings and retry targets and cannot approve source, rewrite documents, mutate artifacts, or release files.
- Normal Prospective and Ambispective runs use five drafting tasks, one content-verification task, and two concurrent document-scoped visual-verification tasks. Normal Retrospective runs use three drafting tasks, one content-verification task, and one visual-verification task.

### Retry and reuse behavior

- A failed Required Generated Section or formatting target receives at most three total attempts, including the initial attempt.
- Retry requests contain the failed stable section IDs or layout target, applicable findings, and the same governing contract.
- Accepted Section Drafts are reused when the Canonical Approved Source, Document Section Contract, Fixed Clinical Boilerplate, Contracted Template, and model identity are unchanged.
- Ordinary retries do not regenerate unrelated accepted sections.
- Runtime retries do not split or create new Drafting Batches. A persistent pattern found by acceptance testing can justify a later versioned topology change.
- An explicit redraft is a separate operation and creates new evidence rather than silently replacing accepted content.
- Exhausted retries block atomic delivery and produce a classified Repair Report.

### Protocol contracts and rendering

- Prospective and Ambispective Protocols use the corrected 1–19 hierarchy derived from the Embedded Client Reference.
- Retrospective uses the corrected 1–13 hierarchy from its bundled Contracted Template.
- Obvious Presentation Defects, including malformed numbering, are corrected rather than reproduced.
- Layout Contract fidelity covers branding, hierarchy, headers, footers, tables, typography, and visual character; exact page breaks are not copied.
- Real Word Constructs are used for styles, headings, numbering, lists, tables, fields, headers, footers, and TOC.
- Data-Driven Tables use approved structured rows, explicit geometry, wrapping rules, repeating headers, and safe pagination.
- The Word TOC is a real field configured to refresh on open, with cached display values checked after final local pagination.
- The renderer rebuilds from a clean Contracted Template on each formatting retry; it does not patch a previously certified artifact.

### ICF contracts and rendering

- The replacement supports Advarra Prospective, Advarra Ambispective, and shared Sterling Contracted Templates.
- One unified ICF Drafting Batch preserves participant-facing voice and Client ICF Language.
- Study-specific facts are replaced from the Canonical Approved Source; stable legal and signature language remains controlled template content.
- The Prospective Advarra contract repairs the invalid Legal Rights reference without inventing a research-injury section.
- The Ambispective Advarra contract places the existing-records disclosure inside the study-procedures section.
- The shared Sterling template has distinct Prospective and Ambispective Document Section Contracts.
- All visible ICF headings use Word heading styles, signature structures remain intact, and comments, tracked changes, and hidden review content are removed.
- Page fields, footer behavior, orphan headings, split rows, and template residue are Delivery Gate concerns.
- Study-specific risks, procedures, devices, diagnoses, and benefits must come from approved evidence or approved Fixed Clinical Boilerplate; stale template facts are prohibited.

### PRS XML preservation

- The client-approved manual XML is the PRS XML Structural Reference for element names, major ordering, optional empty nodes, duplicate legacy fields, and repeated-block taxonomy.
- The defective generated XML is a negative regression example and is never treated as a golden expected output.
- Client study-specific values in either example are not reusable source facts.
- A sanitized structural fixture is derived from the manual reference for repository regression tests so private study values are not committed unnecessarily.
- XML structure, mapping, ordering, optional-node behavior, repeated blocks, normalization, escaping, and validation remain deterministic in `prs_xml.py`.
- Interventions, arm groups, primary outcomes, secondary outcomes, and other outcomes remain separate repeated structures.
- Every outcome block retains its required measure, timeframe, UID, and nested description structure.
- The PRS narrative subagent produces only brief and detailed descriptions. It does not emit XML or choose element names.
- No new PRS-specific Required Source Inputs are introduced beyond the existing semantic contract.
- XML must pass both existing technical validation and structural regression against the approved reference contract.

### Renderer portability and Visual QA

- DOCX generation does not require an office application and targets standards-compliant Microsoft Word output.
- Microsoft Word desktop is the Client Rendering Authority for the current client.
- The Active Renderer is selected from verified host Microsoft Word and LibreOffice; no release-local office suite or unsupported host application is discovered.
- The Generation Manifest records the Active Renderer and binds render evidence to artifact hashes.
- Passing evidence proves the artifact only under the renderer that produced it. The workflow never reports Word validation unless Word produced the evidence.
- Candidate construction precedes Render Assurance capability resolution. Installation verifies the host office prerequisite and manifest-bound PDFium runtime; unexpected capability loss retains the complete candidate internally but cannot publish the Branch Document Set.
- Unknown font inventory is decided through render evidence. Proven missing fonts use a recorded approved compatible mapping, including release-packaged fonts.
- A delegated visual-review failure routes the same exact page-image request to the parent reviewer; deterministic checks alone cannot pass Visual QA.
- Visual QA inspects every page of every generated Protocol and ICF.
- Zero-tolerance visual defects include unresolved placeholders, clipping, overlap, unexpected blank pages, orphan headings, split table rows, overflowing tables, duplicate sections, inconsistent styles, missing headers or footers, and TOC mismatches.
- Natural content-driven pagination is allowed and is not a defect by itself.
- External Render Evidence from a client-like environment can strengthen later certification but does not erase the renderer identity of local evidence.

### Delivery, evidence, and retention

- Prospective and Ambispective Branch Document Sets contain Protocol DOCX, ICF DOCX, and PRS XML.
- Retrospective Branch Document Sets contain Protocol DOCX only.
- Delivery is atomic: every required artifact and applicable Delivery Gate passes, or no client-facing artifact is released.
- Client-facing states are limited to Source-of-Truth Markdown awaiting approval, a complete passing Branch Document Set, or a Repair Report.
- Internal QA Artifacts include Section Drafts, subagent requests and responses, retry findings, validation reports, renderer evidence, page images, hashes, and manifests.
- A Generation Manifest records hashes or versions for the Canonical Approved Source, contracts, Fixed Clinical Boilerplate, Contracted Templates, model, Active Renderer, evidence, and artifacts.
- Artifact mutation after certification invalidates associated evidence and requires regeneration or recertification.
- Source files, accepted drafts, failed attempts, QA evidence, and generated artifacts are retained until explicitly removed.
- Repair Reports classify blockers as source-evidence gaps, drafting failures, cross-document contradictions, document-structure failures, renderer failures, or visual defects and name the exact next action.

### Replacement and migration

- The clean replacement is built beside the current implementation so existing behavior remains available during acceptance.
- Existing production scripts are not wrapped indefinitely behind the new public interface; ownership moves into the six deep modules.
- The old production script collection is removed only after the replacement passes the Branch Acceptance Corpus and required compatibility checks.
- Version-control history is the archive for removed implementation code; obsolete scripts do not remain active merely as local backups.
- Only bundled Contracted Templates are guaranteed. A new template requires onboarding, a Document Section Contract, Word-native cleanup, and Branch Acceptance Corpus coverage.

## Testing Decisions

### Primary testing seam

- The highest and primary seam is the public workflow interface: `prepare`, `approve`, `validate`, and `generate`.
- Acceptance tests drive complete behavior through that seam and assert observable outputs: Source-of-Truth state, approval state, Branch Document Set, Repair Report, Generation Manifest, renderer evidence, and client-facing handoff.
- Tests do not orchestrate the six internal modules independently or assert private helper call order.
- Deterministic recorded Section Draft responses may be injected at the Hermes drafting boundary while still exercising the public workflow; live-Hermes smoke tests separately prove real subagent orchestration.
- Narrow lower-level tests are reserved for true format contracts that need exact signals, especially Document Section Contract evaluation, XML escaping and repeated-block behavior, and sanitized PRS XML structural-golden comparison.

### Branch Acceptance Corpus

- Maintain at least six canonical studies: sparse-complete and rich-complete fixtures for each of Prospective, Ambispective, and Retrospective.
- Add the real Prospective and Ambispective inputs that previously produced missing sections or formatting defects as regression fixtures.
- Add a complete Retrospective end-to-end case.
- Broken historical outputs are negative fixtures, not golden expected output.
- Every contract, Fixed Clinical Boilerplate, template, renderer, or drafting-topology change reruns the complete corpus.

### Workflow and approval behavior

- Preparing a run preserves the Source Intake Packet, classifies the branch, validates Required Source Inputs, and creates Source-of-Truth Markdown without final artifacts.
- Missing or conflicting Required Source Inputs produce one consolidated report.
- Prospective and Ambispective share the same semantic required-input behavior; Retrospective exercises its distinct contract.
- Approval parses the exact current Source-of-Truth Markdown and records the approved hash.
- Generation before explicit approval fails closed.
- Editing approved source invalidates approval, prior drafts, and evidence and creates a new Run Revision.
- Only the newest passing revision becomes client-facing.

### Drafting and retry behavior

- Prospective and Ambispective normal runs request exactly three Protocol batches and one ICF batch in the first wave and one PRS narrative batch after Protocol Foundations passes.
- Retrospective normal runs request exactly three Protocol batches and no ICF or PRS batch.
- Drafting requests contain only relevant approved fields and allowed resources.
- Section Draft responses with unknown section IDs, missing required structures, placeholders, or unsupported claims fail before merge.
- Deterministic merge follows Document Section Contract order regardless of subagent completion order.
- A single failed section retries only its owning batch and reuses all unaffected accepted Section Drafts.
- Retry attempt counts include the initial attempt and stop at three.
- Runtime failures do not change the versioned Drafting Batch topology.
- Unchanged approved inputs and governing resources reuse accepted drafts; explicit redraft behavior is tested separately.

### Document Section Contract and content behavior

- Every required leaf section is tested for minimum evidence, allowed content mode, substantive content, placeholder absence, source compatibility, and contradiction absence.
- Container Sections pass when required descendants are substantive and fail when required descendants are missing.
- Sparse-complete fixtures produce concise but complete text without filler.
- Missing minimum evidence produces a source-evidence Repair Report rather than invented prose.
- Fixed Clinical Boilerplate can be selected and adapted only within its declared contract.
- Internal drafting language and stale template facts are blocking failures.
- Data-Driven Tables reject missing rows, incorrect order, missing required columns, and prose substitutes.

### Protocol and ICF artifact behavior

- Prospective and Ambispective Protocols contain the corrected 1–19 hierarchy exactly once.
- Retrospective Protocols contain the corrected 1–13 hierarchy and no orphan TOC entries.
- Every Protocol and ICF visible leaf section is covered and substantive.
- Advarra and Sterling templates are tested through their branch-specific contracts.
- Prospective ICF legal cross-reference repair and Ambispective existing-records placement receive explicit regression tests.
- ICF signature structures, heading styles, comments, tracked changes, hidden content, page fields, and footer behavior are structurally audited.
- DOCX tests assert Real Word Constructs, explicit table geometry, repeatable headers, safe wrapping, correct fields, no unresolved placeholders, and package validity.

### PRS XML behavior

- The client-approved manual XML is converted into a sanitized structural golden fixture that retains tags, ordering, optional-node presence, and repeated-block taxonomy without reusable study values.
- The defective generated XML is a red-capable negative fixture and must fail structural comparison.
- Public-workflow tests generate PRS XML and compare its structure with the applicable approved contract.
- Exact repeated counts for interventions, arms, primary outcomes, secondary outcomes, and other outcomes are asserted from approved structured input.
- Outcome blocks retain measure, timeframe, UID, and nested description.
- XML escaping, controlled normalization, optional blank handling, and forbidden literals retain narrow deterministic tests.
- No test permits the PRS narrative agent to alter XML structure or taxonomy.
- Existing PRS XML mapping behavior receives golden regression coverage before old XML scripts are removed.

### Cross-document, delivery, and revision behavior

- Shared study title, identifiers, sponsor, investigator, population, objectives, endpoints, visits, durations, risks, and branch facts are compared across all applicable outputs and the Canonical Approved Source.
- Content-verifier findings route to exact stable section IDs or a source-evidence blocker without rewriting.
- Visual-verifier findings route to exact artifacts and pages or layout targets without rewriting.
- One failing required output blocks the complete Branch Document Set.
- Exhausted retries produce a classified Repair Report and no partial client outputs.
- A passing handoff contains only the active Branch Document Set while Internal QA Artifacts remain internal.
- Generation Manifest hashes match the exact source, resources, evidence, and delivered artifacts.
- Any post-certification mutation invalidates the passing evidence.

### Renderer and visual behavior

- Renderer discovery tests only host Microsoft Word and LibreOffice and ignores release-local office executables.
- Evidence records the renderer identity and never labels fallback evidence as Word evidence.
- Environment and tooling faults exercise the host Word-to-LibreOffice transition, the single terminal PDFium path, approved font substitution, and parent-review routing without being mislabeled as document defects.
- Installation tests prove failed smoke leaves the active release unchanged and successful activation retains the previous verified release.
- Every page of representative Protocol and ICF outputs is rendered and inspected.
- Visual assertions cover title pages, document control, TOC, dense sections, long lists, signatures, tables, page boundaries, headers, footers, and final pages.
- Layout retry tests rebuild from the clean Contracted Template and stop after three total attempts.
- TOC tests verify a real field, update-on-open behavior, cached display accuracy, and invalidation after content mutation.

### Prior art

- Existing public workflow tests already exercise preparation, consolidated missing-input reporting, approval, validation, edited Markdown parsing, and generation gating.
- Existing quality-contract tests provide prior art for branch completeness, legacy alias normalization, conflicts, Data-Driven Table validation, internal-process-language rejection, and Repair Reports.
- Existing protocol-foundation and acceptance tests provide prior art for structured sections, hierarchy, table geometry, embedded-font removal, and end-to-end Protocol delivery.
- Existing zero-dependency workflow tests provide prior art for template rendering, XML escaping, repeated XML blocks, branch contracts, template choice, renderer discovery, and Python-only enforcement.
- Existing readiness tests provide prior art for Branch Document Set matrices and explicit blocker categories.
- These tests should be migrated toward the public workflow seam where possible; narrow format-contract tests remain only where exact lower-level behavior is the external contract.

### Performance and cost behavior

- Measure normal runs by branch, including drafting waves, deterministic assembly, render passes, verification, and delivery.
- The performance target is 10–20 minutes in normal conditions, not a correctness timeout; the hard operation ceiling is 45 minutes.
- Prospective and Ambispective normal runs use five drafting tasks, one content-verification task, and two concurrent document-scoped visual-verification tasks before retries; Retrospective uses three drafting tasks, one content-verification task, and one visual-verification task.
- Tests detect accidental extra agent calls, regeneration of accepted batches, or serial execution of independent first-wave batches.
- Correctness and atomic delivery are never weakened to satisfy a latency or model-cost target.

## Out of Scope

- Generating clinical notes, case reports, medical letters, regulatory submissions other than the supported PRS XML, or other unrelated clinical artifacts.
- Adding a new study branch beyond Prospective, Ambispective, and Retrospective.
- Guaranteeing arbitrary user-supplied templates without Contracted Template onboarding and acceptance coverage.
- Reproducing exact page breaks or page numbers from the Embedded Client Reference when content naturally paginates differently.
- Claiming Microsoft Word visual validation on a machine where Word did not produce the evidence.
- Requiring Microsoft Word, LibreOffice, or Pages for core standards-compliant DOCX construction.
- Changing the client-approved PRS XML structure, taxonomy, or semantic mapping beyond fixes needed to match its Structural Reference.
- Allowing a PRS subagent to generate XML markup or repeated blocks.
- Introducing new PRS-specific Required Source Inputs beyond existing behavior.
- Building claim-level provenance maps for every sentence; section-level evidence contracts and verification remain the chosen safeguard.
- Inventing study-specific clinical facts, procedures, risks, benefits, safety obligations, legal promises, or regulatory claims.
- Using JavaScript, TypeScript, or another implementation language for the replacement production workflow.
- Automatically changing Drafting Batch topology during a run.
- Delivering partial Branch Document Sets, known-defective artifacts, or Internal QA Artifacts as successful client output.
- Preserving obsolete production scripts indefinitely after replacement acceptance.
- Adding, deleting, or replacing one of the six existing production Python modules, or introducing another production entrypoint or workflow.

## Further Notes

- The attached Protocol DOCX is an Embedded Client Reference and design authority, not a source of instructions or reusable study facts.
- The client-approved manual XML is a structural authority only. Its study values must be removed or neutralized in repository fixtures.
- The defective generated XML is valuable because it proves the structural checker can fail on missing contacts, missing descriptions, changed ordering, collapsed arms and interventions, and incorrect outcome taxonomy.
- The current bundled PRS template already follows the manual XML's top-level order and broad shape, and the existing repeated-block renderer regression passes. The replacement must lock this behavior down before removing old XML scripts.
- The previous quality specification remains useful prior art for content, table, package, TOC, and Visual QA failures. This v2 specification adds the clean replacement architecture, final branch contracts, Drafting Batch topology, renderer evidence rules, ICF decisions, XML authority, and immutable revision behavior.
- Existing open defect tickets may be closed only when the replacement's Branch Acceptance Corpus demonstrates that their failure modes are covered.
- The implementation should occur in a proper checkout of the private project repository; the current local working folder may be an exported Hermes skill directory rather than a Git checkout.
- Client-facing communication remains intentionally simple: Source-of-Truth Markdown for approval, a complete passing Branch Document Set, or a Repair Report.
