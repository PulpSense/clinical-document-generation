# Clinical Document Generation Quality and Reliability

## Problem Statement

The clinical document generation skill can currently produce a Generated Protocol that is shorter than the Reference Protocol, omits required operational content, contains internal drafting language, renders tables incorrectly, references tables that were never inserted, produces an inaccurate Static TOC, uses inconsistent document geometry, and embeds unnecessary fonts that make the DOCX substantially larger than the reference.

The current failure is not only visual. A Generated Protocol may be syntactically valid while being clinically incomplete or operationally different from the reviewed source. For example, a document can contain the caption “Table 15.1. Proposed Visits and Study Assessments” without containing the Schedule of Assessments itself. A table can also exist but have malformed row/column structure or incorrect visit data. These must be treated as delivery failures.

The user needs one reliable clinical study document-generation skill that is automatically invoked for clinical study document requests, classifies the study branch, gathers and validates required inputs, produces a reviewer-editable Source-of-Truth Markdown file, waits for explicit approval, and then generates complete, visually stable, reasonably sized document artifacts.

The workflow must support prospective, ambispective, and retrospective studies. It must preserve the existing approval boundary: source material is evidence, the Source-of-Truth Markdown is reviewable input, and final documents are not generated until the reviewer explicitly approves the current Markdown or uploads an edited approved version.

The end-to-end workflow should be optimized to complete in 10–20 minutes in normal conditions, but that target is not a correctness timeout. The workflow must continue making progress until the output is correct, up to the 30-minute operation ceiling. It must not deliver a known-incomplete or known-invalid document merely to meet a time target.

## Solution

Improve the skill as a fail-closed, source-grounded, reference-aligned document-generation pipeline.

The workflow will:

1. Automatically invoke for clinical study document-generation requests.
2. Classify the study as Prospective, Ambispective, or Retrospective.
3. Preserve all source material as a Source Intake Packet and Evidence Files.
4. Run the Extraction Pass into a Draft Reference.
5. Identify missing or conflicting Required Source Inputs.
6. Stop and ask for all blocking inputs together when required information is missing or conflicting.
7. Generate the Source-of-Truth Markdown only after required inputs and any required ICF template choice are resolved.
8. Present the Source-of-Truth Markdown to the reviewer and wait for explicit approval.
9. Parse the currently approved Markdown exactly as written.
10. Generate branch-specific narrative and structured operational fields.
11. Render documents through a rebuilt, reference-aligned Protocol Template and branch-specific templates.
12. Insert sections, lists, captions, and tables as Real Word Constructs rather than newline-packed text.
13. Validate content completeness, placeholder compatibility, table structure, DOCX structure, file size, rendering, and Static TOC pagination.
14. Run parallel read-only review passes for content, structure, visual layout, and package hygiene.
15. Apply repairs through one controlled implementation/repair path and rerun the complete validation cycle.
16. Deliver only artifacts that pass all applicable Delivery Gates.

The Reference Protocol is the visual and structural authority. The generated document should be similar in length and structure to the Reference Protocol, but expansion must remain grounded in source evidence and approved Fixed Clinical Boilerplate. The workflow must not invent study-specific clinical or operational details to meet a word count.

## User Stories

1. As a clinical document requester, I want the skill to invoke automatically when I ask to generate clinical study documents, so that I do not need to know the internal skill name.
2. As a clinical document requester, I want the skill to recognize prospective, ambispective, and retrospective studies, so that the correct document branch is selected automatically.
3. As a clinical document requester, I want the skill to preserve every supplied Evidence File, so that the extraction process remains auditable.
4. As a reviewer, I want the Extraction Pass to identify Field Candidates with source evidence, so that ambiguous or conflicting facts can be resolved before generation.
5. As a reviewer, I want the workflow to ask for all missing Required Source Inputs together, so that I do not have to answer a long sequence of one-field questions.
6. As a reviewer, I want the workflow to stop when a Required Source Input conflicts across Evidence Files, so that the final document does not silently choose an unsupported value.
7. As a reviewer, I want prospective and ambispective runs to resolve the required ICF template choice before Source-of-Truth Markdown generation, so that the review reflects the actual document branch.
8. As a reviewer, I want retrospective runs to avoid unnecessary ICF-template questions, so that branch-specific requirements remain focused.
9. As a reviewer, I want a Source-of-Truth Markdown file containing structured study facts and regulatory values, so that I can correct the facts before final generation.
10. As a reviewer, I want the Source-of-Truth Markdown to exclude unapproved AI-written protocol prose, so that I can review source facts separately from generated narrative.
11. As a reviewer, I want to edit any mapped value in the Source-of-Truth Markdown, so that my edited wording becomes authoritative for final generation.
12. As a reviewer, I want the workflow to require explicit approval, so that a request to generate documents cannot accidentally bypass review.
13. As a reviewer, I want an uploaded edited Source-of-Truth Markdown file to be parsed exactly as written, so that the workflow does not silently normalize or overwrite my corrections.
14. As a reviewer, I want the final Generated Protocol to include all required sections from the Reference Protocol, so that the output is operationally complete.
15. As a reviewer, I want the Generated Protocol to preserve Operational Detail such as endpoint hierarchy, visit windows, dosing schedules, supply management, safety reporting, retention, compensation, and injury handling, so that the protocol remains usable in study conduct.
16. As a reviewer, I want narrative sections to be expanded when the source supports additional detail, so that the output is not an overly compressed summary.
17. As a reviewer, I want expansion to remain grounded in Evidence Files or approved Fixed Clinical Boilerplate, so that the system does not fabricate clinical details.
18. As a reviewer, I want required concepts and operational qualifications to determine completeness rather than raw word count, so that longer output does not contain filler.
19. As a reviewer, I want a missing required clinical detail to produce a precise Repair Report, so that the missing input can be supplied instead of being invented.
20. As a reviewer, I want the Generated Protocol to use the approved protocol number, version, date, investigator information, sub-investigator information, sponsor information, and study identifiers consistently, so that document control is reliable.
21. As a reviewer, I want the Generated Protocol to preserve the Reference Protocol’s section numbering and hierarchy, so that reviewers can compare the documents efficiently.
22. As a reviewer, I want every source-referenced table to be represented as a required Data-Driven Table contract, so that a table caption cannot exist without its table.
23. As a reviewer, I want Table 15.1 and other required tables to contain the expected columns and rows, so that operational schedules are not reduced to a paragraph or omitted.
24. As a reviewer, I want visit schedules to preserve visit names, windows, arm qualifications, CRF information when supported, and all required assessment cells, so that the study team can use the table operationally.
25. As a reviewer, I want sample-size evidence tables to preserve their study, time point, mean change, standard error, and estimated standard deviation data, so that the sample-size rationale remains auditable.
26. As a reviewer, I want tables to wrap text without clipping, overlap, or pinned content, so that the DOCX remains readable in Word and rendered PDF form.
27. As a reviewer, I want table headers to repeat across page breaks when tables span pages, so that continuation pages remain understandable.
28. As a reviewer, I want table widths, indents, grids, and cell widths to be explicit, so that rendering does not depend on Word defaults or renderer-specific autofit behavior.
29. As a reviewer, I want lists to use real Word numbering and indentation, so that wrapped list lines align beneath the item text.
30. As a reviewer, I want headings, captions, lists, and tables to be inserted as Real Word Constructs, so that the document is structurally editable and visually stable.
31. As a reviewer, I want the rebuilt Protocol Template to follow the Reference Protocol’s page size, margins, section structure, headers, footers, typography, and table treatment, so that the output has no avoidable formatting drift.
32. As a reviewer, I want known Reference Protocol presentation defects to be distinguished from the Layout Contract, so that typos or one-off reference anomalies are not reproduced blindly.
33. As a reviewer, I want conflicting reference metadata, such as inconsistent header dates, to be surfaced during implementation or QA, so that the intended document-control value can be confirmed.
34. As a reviewer, I want unnecessary embedded fonts removed from generated DOCX packages, so that text-and-table documents remain reasonably small.
35. As a reviewer, I want the generated DOCX package to avoid duplicated or unnecessary assets, so that file size remains proportional to document content.
36. As a reviewer, I want the normal generated protocol to remain within an agreed reasonable size target, approximately 100–250 KB unless required assets justify more, so that files are easy to store and transmit.
37. As a reviewer, I want the Static TOC to include every required section and table entry, so that navigation is complete.
38. As a reviewer, I want Static TOC page numbers to be calculated after final rendering, so that pagination reflects the actual document.
39. As a reviewer, I want Static TOC entries to use real right-aligned dot-leader tab stops, so that alignment remains stable and editable.
40. As a reviewer, I want the workflow to rerender after TOC refresh, so that TOC changes cannot invalidate the page numbers.
41. As a reviewer, I want the workflow to fail the Content Completeness Gate when a caption exists without its required table, so that the Section 15 defect cannot reach delivery.
42. As a reviewer, I want the workflow to fail when required generated sections contain internal drafting language, so that phrases such as “The approved source identifies” do not appear in client documents.
43. As a reviewer, I want the workflow to fail when placeholders remain unresolved, so that incomplete template substitution cannot be mistaken for a finished document.
44. As a reviewer, I want visual QA to inspect rendered page images or PDF output, so that clipping, overflow, blank sections, malformed tables, and header/footer defects are detected.
45. As a reviewer, I want the workflow to support a client-like renderer as stronger External Render Evidence when available, so that local-only rendering differences do not hide defects.
46. As a reviewer, I want content, DOCX structure, and document-scoped visual layout checks to run concurrently, so that quality review does not unnecessarily exceed the 10–20 minute performance target.
47. As a reviewer, I want review sub-agents to report findings rather than independently rewrite the document, so that competing edits do not create inconsistent output.
48. As a reviewer, I want one controlled repair path to apply fixes and rerun every relevant gate, so that repairs are reproducible and auditable.
49. As a reviewer, I want the workflow to continue working toward a correct output when a run takes longer than twenty minutes, up to the 30-minute correctness ceiling, so that correctness is not sacrificed for the performance target.
50. As a reviewer, I want repeated or irreducible failures to produce a precise Repair Report, so that the workflow never silently delivers a known-incomplete document.
51. As a study team member, I want only validated final artifacts delivered by default, so that internal renders, audit JSON, PDFs, and reports do not clutter the client handoff.
52. As a study team member, I want internal QA artifacts retained in the run directory, so that failures and output decisions remain auditable.
53. As a maintainer, I want the workflow to retain Placeholder Compatibility with supported legacy n8n-style fields, so that existing branch mappings and templates do not break unnecessarily.
54. As a maintainer, I want new templates to prefer structured table loops and explicit fields, so that future documents do not regress to newline-separated table blobs.
55. As a maintainer, I want the end-to-end approved-run path to be the primary test seam, so that tests verify externally meaningful output behavior rather than implementation details.
56. As a reviewer, I want document construction to complete before Render Assurance capability failures are reported, so that an environment fault never destroys the complete internal candidate.
57. As a reviewer, I want unavailable capabilities to fail closed or use only their explicitly governed owner—host Word/LibreOffice, the release-owned PDFium runtime, packaged fonts, or Desktop-parent visual review—so that mandatory Visual QA remains mandatory without an alternate renderer backend.
58. As a reviewer, I want unknown font inventory decided by actual render evidence rather than treated as a missing font, so that an inspection limitation cannot block valid documents.
59. As an administrator, I want release activation to smoke-test the host office prerequisite and manifest-bound PDFium runtime and retain the previous verified release atomically, so that a broken update cannot break future runs.
60. As a reviewer, I want a genuine defect to remain bound to the renderer that exposed it, so that switching renderers cannot manufacture a pass.

## Implementation Decisions

### Workflow and invocation

- The skill’s trigger description will cover clinical study document-generation requests without requiring the requester to name the skill explicitly.
- The supported scope is clinical study document sets: Generated Protocol, Generated ICF, short summary where applicable, and Generated PRS XML where applicable.
- Unrelated clinical artifacts such as clinical notes, case reports, and medical letters are out of scope for this skill.
- Study classification remains Prospective, Ambispective, or Retrospective and determines the branch-specific document set and requirements.
- The workflow remains local and auditable through run directories containing preserved inputs, references, templates, generated outputs, and QA logs.

### Approval and source-of-truth boundary

- The Extraction Pass remains model-owned because Source Intake Packets can contain mixed, unstructured Evidence Files.
- Local scripts remain responsible for source preservation, Required Source Input checks, Source-of-Truth Markdown creation and parsing, template rendering, structural validation, rendering, and delivery gates.
- The Source-of-Truth Markdown remains the reviewer-editable representation of client-provided study facts and regulatory values.
- Final document generation requires explicit approval. Silence, an original generation request, or an unapproved draft does not count as approval.
- On approval, the current Source-of-Truth Markdown is parsed exactly as written. Mapped reviewer edits are authoritative unless a technical parsing failure makes continuation impossible.

### Template strategy

- Rebuild the Protocol Template from the Reference Protocol rather than incrementally repairing the current template package.
- Preserve Placeholder Compatibility for currently supported legacy field names while making new template structures use explicit structured fields.
- Keep the Reference Protocol as the visual and structural authority for page geometry, section organization, headers, footers, typography, table treatment, and pagination behavior.
- Treat one-off Reference Protocol presentation defects as Presentation Defects unless explicitly adopted into the Layout Contract.
- Surface unresolved Reference Protocol metadata conflicts during QA instead of silently selecting a value.

### Structured content generation

- Generate protocol content as section-level structured objects containing headings, paragraphs, lists, captions, tables, and expected elements.
- Avoid replacing placeholders with large blocks of newline-separated prose.
- Preserve Operational Detail from reviewed sources and expand narrative only using Evidence Files and approved Fixed Clinical Boilerplate.
- Use semantic completeness requirements as the primary content-quality signal. Soft length comparisons against the Reference Protocol may detect suspicious compression but cannot justify filler or invented facts.
- Reject internal process language from client-facing outputs, including unresolved drafting notes and statements that content should be finalized later.
- Keep terminology consistent with the domain glossary: Reference Protocol, Source Intake Packet, Generated Protocol, Data-Driven Table, Delivery Gate, Repair Report, and related terms.

### Structured tables

- Represent every substantive table as a typed Data-Driven Table with explicit columns, rows, and validation rules.
- Define branch and template contracts for expected tables, including the Schedule of Assessments and sample-size evidence table.
- Treat table captions and references as required-element declarations. A caption such as Table 15.1 without its table is a hard Content Completeness Gate failure.
- Require table schemas to validate row count, column count, header labels, required values, visit order, and allowed blank cells before DOCX insertion.
- Insert tables as Real Word Constructs with explicit table width, table indent, table grid, cell widths, cell margins, wrapping, vertical alignment, header-row repetition, and page-break behavior.
- Do not rely on autofit, fixed row heights, percentage widths, centered default tables, or prose-table hacks.
- Preserve legacy string fields only through an explicit Legacy String Fallback that normalizes them into structured rows and records the normalization.

### DOCX package and layout

- Use the Reference Protocol’s page size and section structure as the default layout contract for rebuilt protocol templates.
- Preserve headers and footers as structured document parts with correct version, date, title, and page fields.
- Use real Word headings, numbering definitions, tab stops, table grids, section properties, and fields.
- Ensure wrapped lists align under their text rather than under markers.
- Ensure captions remain paired with their tables and headings remain paired with their following content where practical.
- Remove embedded fonts from generated text-and-table DOCX packages unless a specific client requirement justifies them.
- Avoid unnecessary package parts, duplicated assets, and renderer-specific metadata that inflate file size.
- Add a package-size and embedded-asset audit to the delivery process, with an expected normal target of approximately 100–250 KB for a text-and-table protocol.

### Static TOC and pagination

- Generate or refresh the Static TOC only after all content and tables have been inserted.
- Use real right-aligned dot-leader tab stops for page numbers.
- Render the final DOCX, determine actual heading and table pages, update the Static TOC, rerender, and audit again.
- Require zero missing headings, zero page mismatches, and zero alignment mismatches when a renderer is available.

### Quality review and repair

- Use parallel read-only reviewers for:
  - Content Completeness and source fidelity.
  - DOCX structural correctness and table geometry.
  - Visual QA of rendered pages.
  - Package size and OOXML hygiene.
- Use one controlled implementation/repair path to apply consolidated findings.
- After any repair, rerun all affected structural, rendering, TOC, and package audits rather than trusting the previous result.
- Continue processing beyond the ten-minute performance target while meaningful progress is being made.
- Never deliver a known-incomplete document.
- If an irreducible issue remains after safe repair attempts, write a Repair Report that identifies the exact gate, artifact, section, table, or input blocking delivery.

### Primary seams

- The primary test seam is the end-to-end approved-run renderer, because it exercises the user-visible behavior from approved Source-of-Truth Markdown to final artifacts.
- Existing seams should be reused for Required Source Input checks, approval parsing, template validation, DOCX rendering, Static TOC refresh, Static TOC auditing, and PRS XML validation.
- New seams should be introduced only where current scripts cannot express the Content Completeness Checklist, Data-Driven Table contracts, package-size audit, or multi-reviewer result aggregation.
- Reviewers should consume rendered outputs and audit reports, not reach into implementation details or independently mutate documents.

### Performance

- Parallelize independent reviewer and audit passes.
- Use deterministic local scripts for mapping, validation, DOCX structure checks, rendering orchestration, and package inspection.
- Avoid unnecessary model calls after the Source-of-Truth Markdown is approved.
- Reuse structured extraction and table data across protocol, ICF, summary, and XML generation where branch contracts permit.
- Treat 10–20 minutes as the optimization objective and 30 minutes as the hard correctness ceiling, never as permission to ship a deficient artifact.

## Testing Decisions

Tests should verify externally observable behavior of the workflow and produced artifacts. They should prefer the highest available seam and avoid asserting private helper implementation details.

### End-to-end approved-run tests

- Start from an approved Source-of-Truth Markdown fixture and run the final generation path.
- Assert that only the configured branch document set is rendered.
- Assert that final outputs exist only after approval is recorded and the approved Markdown has been parsed.
- Assert that output artifacts pass the applicable Delivery Gates.
- Assert that a successful run does not contain a Repair Report with unresolved blocking failures.

### Required-input and approval tests

- Missing Required Source Inputs produce one consolidated blocking report.
- Conflicting Field Candidates for a Required Source Input block source-of-truth generation.
- A missing or ambiguous prospective/ambispective ICF template choice blocks appropriately.
- Retrospective runs do not require an ICF template choice.
- Unapproved Source-of-Truth Markdown cannot produce final documents.
- An edited approved Markdown file is parsed exactly as supplied.

### Content completeness tests

- A required section missing from Generated Protocol fails the Content Completeness Gate.
- A required subsection missing from the generated heading hierarchy fails.
- A source-referenced table caption without an inserted table fails.
- Table 15.1 without the expected Schedule of Assessments rows and columns fails.
- The sample-size table without its required evidence columns fails.
- Internal drafting language in final client-facing content fails.
- Required Operational Detail omissions fail even when the document’s total word count looks plausible.
- A source-grounded expansion passes when it adds supported detail without inventing unsupported study facts.

### Data-Driven Table tests

- Structured visit rows render in the correct visit order.
- Table schemas reject missing required columns and unexpected structural changes.
- Tables with long cell content wrap without clipping.
- Header rows repeat when a table spans pages.
- Explicit table widths, grids, indents, and cell widths remain internally consistent.
- Legacy String Fallback produces equivalent structured rows and records that normalization occurred.
- The rendered Schedule of Assessments contains the expected assessment matrix rather than a placeholder caption or prose summary.

### DOCX structural tests

- Rebuilt templates contain the expected section properties, headers, footers, headings, numbering definitions, captions, and tables.
- Generated DOCX packages contain no unresolved placeholders.
- List paragraphs use numbering definitions rather than fake bullet characters or manually numbered text.
- TOC paragraphs use real tab stops rather than manual dot strings.
- Embedded-font audits detect and reject unnecessary font payloads.
- Package-size audits report component sizes and fail when the configured normal target is exceeded without justification.
- Document XML remains valid and can be opened by the supported renderer.

### Visual QA tests

- Render representative protocols to PDF and page images when a renderer is available.
- Inspect title page, document-control pages, TOC pages, dense eligibility sections, visit schedule pages, every required table, page-break boundaries, and final pages.
- Assert no clipping, overlap, malformed table, missing table, blank placeholder section, header/footer drift, or incorrect page number.
- Refresh the Static TOC from final pagination, rerender, and require zero audit mismatches.
- Record renderer-unavailable status as a QA limitation rather than falsely claiming visual verification.

### Branch regression tests

- Run prospective, ambispective, and retrospective fixtures through their respective document-set contracts.
- Preserve current Placeholder Compatibility tests for legacy n8n-style fields.
- Preserve existing PRS XML validation tests for prospective and ambispective branches.
- Ensure retrospective protocol-only runs do not accidentally emit ICF or XML outputs.

### Performance tests

- Measure a representative approved run from approval parse through final validation.
- Measure parallel reviewer execution separately from serial repair and rerender work.
- Assert that normal runs meet the ten-minute optimization target without weakening Delivery Gates.
- Include a larger protocol with multiple Data-Driven Tables to detect performance regressions.

## Out of Scope

- Generating unrelated clinical documents such as medical notes, case reports, or clinical letters.
- Replacing the model-owned Extraction Pass with a fully deterministic parser.
- Inventing study-specific clinical facts, operational procedures, endpoint values, safety roles, compensation rules, or regulatory language.
- Treating word count as a sufficient measure of content quality.
- Delivering a partial Generated Protocol as successful output.
- Making the client’s Reference Protocol perfect beyond identifying Presentation Defects and surfacing ambiguities that affect the Layout Contract.
- Requiring Microsoft Word, Apple Pages, or LibreOffice for core DOCX generation.
- Embedding fonts or adding visual assets solely to make a protocol look polished.
- Rewriting unrelated ICF or PRS XML behavior unless the shared structured data or delivery gates require coordinated changes.
- Publishing internal QA artifacts as client deliverables by default.
- Imposing a hard ten-minute timeout that can terminate a correct-but-slow repair cycle.

## Further Notes

- The supplied comparison identified concrete acceptance examples: the Generated Protocol should not substitute the protocol number, version, date, investigator details, or study-control language; it should preserve the full endpoint hierarchy, visit windows, detailed intervention procedures, safety roles, retention period, injury language, replacement rule, and participant compensation; and it should include both the sample-size evidence table and the complete Schedule of Assessments.
- The supplied reference contains at least one header-date inconsistency. The implementation should surface such conflicts rather than silently copying whichever page is encountered first. The intended official date must be resolved as part of the Reference Protocol’s Layout Contract.
- The current generated file’s excessive size is primarily explained by embedded Andika and NotoSansSymbols font files. The package audit should make this regression visible and prevent recurrence.
- The workflow should retain internal run evidence, including generation reports, render reports, TOC reports, package audits, reviewer findings, and repair reports, while keeping the user-facing handoff concise.
- The spec intentionally keeps implementation modules abstract. Existing scripts for run creation, required-input checks, source-of-truth parsing, template rendering, DOCX export, Static TOC refresh, Static TOC auditing, and PRS validation should be extended where possible before introducing new components.
- The implementation should preserve the existing domain distinction between a Reference Protocol, Source Intake Packet, Draft Reference, Source-of-Truth Markdown, Generated Protocol, Protocol Template, Renderer, Visual QA, Data-Driven Table, Delivery Gate, and Repair Report.
