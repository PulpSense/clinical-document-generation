# Clinical Document Generation

This context describes the document-generation workflow for clinical study artifacts. It names the review, rendering, and template concepts that must stay precise because small wording drift can create real delivery risk.

## Language

**Reference Protocol**:
A known-good protocol document used as the visual and structural authority for generated protocol output.
_Avoid_: good protocol, actual protocol, sample protocol

**Embedded Client Reference**:
A retained client protocol example bundled with the skill so each run can follow the established client document shape without requiring the client to upload an example again.
_Avoid_: uploaded example, temporary reference, sample file

**Source Intake Packet**:
One or more client-provided source files, notes, references, emails, PDFs, DOCX files, or Markdown files used to produce the reviewed source-of-truth Markdown.
_Avoid_: messy input, client dump, source blob

**Evidence File**:
A preserved item inside a Source Intake Packet that carries client-provided study evidence, such as a Markdown note, extracted PDF text, DOCX text, spreadsheet content, email, or attachment.
_Avoid_: attachment, raw file, loose source

**Extraction Pass**:
The model-owned interpretation step that converts a Source Intake Packet into draft structured study facts for reviewer approval.
_Avoid_: deterministic parser, field scraper, intake conversion

**Draft Reference**:
The internal study reference before reviewer source approval.
_Avoid_: final JSON, approved reference, generated reference

**Source-of-Truth Markdown**:
The reviewer-editable Markdown representation of client-provided study facts and regulatory values before source approval.
_Avoid_: form output, editable JSON, generated summary

**Approved Source-of-Truth Markdown**:
The Source-of-Truth Markdown after the client has confirmed that its study facts and regulatory values are correct; this approval releases the run for final document generation.
_Avoid_: approved JSON, final input, reviewer notes

**Run Lifecycle**:
The single user-facing progression from a Source Intake Packet through required-input collection, one approval of the final client-provided or client-edited Source-of-Truth Markdown, and final Branch Document Set delivery. A changed approved source creates a new immutable Run Revision.
_Avoid_: workflow scripts, command sequence, generation path

**Run Revision**:
An immutable attempt tied to one exact approved source and its generation inputs, drafts, evidence, and outputs. Only the newest passing revision is client-facing; earlier revisions remain internal audit history until explicitly removed.
_Avoid_: overwritten run, latest folder, regenerated copy

**Field Candidate**:
An extracted possible value for a structured study field, kept with enough source evidence for review when confidence or conflicts matter.
_Avoid_: guess, inferred value, temporary field

**Required Source Input**:
A client-provided study fact or regulatory value required by the active Branch Input Contract before the workflow can request approval or generate active document outputs.
_Avoid_: obligatory field, starred field, must-have

**Branch Input Contract**:
The versioned set of Required Source Inputs for a study branch. Prospective and Ambispective studies share one contract; Retrospective studies use a distinct contract, and the meaning of each input is preserved independently of legacy n8n field names.
_Avoid_: n8n field list, intake form schema, template fields

**Required Source Input Conflict**:
A conflict among extracted Field Candidates for a Required Source Input that must be resolved before approval can continue.
_Avoid_: mismatch, duplicate answer, candidate disagreement

**Generated Protocol**:
The protocol document produced by the clinical document generation workflow from reviewed study inputs.
_Avoid_: output doc, bad protocol, AI protocol

**Generated ICF**:
The informed consent document produced by the clinical document generation workflow from reviewed study inputs and branch-specific consent generation.
_Avoid_: consent output, AI consent, ICF blob

**Generated PRS XML**:
The ClinicalTrials.gov PRS XML document produced from reviewed study inputs, PRS-specific regulatory values, and structured repeated XML rows.
_Avoid_: XML blob, registry dump, generated XML text

**PRS XML Structural Reference**:
The client-approved manual PRS XML whose element names, order, optional empty nodes, and repeated-block taxonomy define the required XML shape; its study-specific values are reference data, not source facts for another study.
_Avoid_: sample XML, generated XML, XML content source

**Branch Document Set**:
The documents required for a study branch: Prospective and Ambispective studies require a Protocol, ICF, and PRS XML, while Retrospective studies require a Protocol.
_Avoid_: output bundle, artifact list, case documents

The Branch Document Set is decided from the approved source and released atomically: every required document passes or no client-facing document is released.

**Canonical Approved Source**:
The final client-provided or client-edited Source-of-Truth Markdown is the authoritative study fact record after one explicit approval; structured references and format-specific fields are derived from that exact version for generation and validation. Any later source change invalidates approval and all generated material.
_Avoid_: final JSON, generated reference, template fields

**ICF Template Choice**:
The client’s Advarra or Sterling selection for the ICF in a Prospective or Ambispective Branch Document Set; Retrospective studies have no ICF template choice.
_Avoid_: protocol template choice, IRB guess, consent format

**Client ICF Language**:
The selected ICF template’s recognizable hierarchy, tone, sentence patterns, legal boilerplate, and signature language. Study-specific terms are populated from the Canonical Approved Source, and obvious cross-reference, review-comment, or formatting defects are corrected rather than copied.
_Avoid_: generic consent rewrite, verbatim study leakage, improvised legal language

**Protocol Template**:
The DOCX document package that receives approved study facts and generated narrative during final protocol generation.
_Avoid_: Word file, format file, shell document

**Contracted Template**:
A bundled template with an explicit Document Section Contract and acceptance coverage. A newly supplied template is not eligible for guaranteed generation until it is onboarded as a Contracted Template.
_Avoid_: arbitrary DOCX, drop-in template, compatible file

**Renderer**:
An available document application or converter used to open a DOCX and produce a visual PDF or page image for quality review.
_Avoid_: exporter, converter, editor

**Client Rendering Authority**:
The office application used by the client to open the delivered DOCX; Microsoft Word desktop is the current client’s renderer. It is the compatibility target, even when a different Active Renderer performs local Visual QA.
_Avoid_: active renderer, local renderer, whatever opens it

**Active Renderer**:
The best supported document renderer available on the generation host—preferred in the order Microsoft Word, LibreOffice, then Pages—and recorded with its Visual QA evidence. Passing evidence proves the artifact under that renderer only and must not be described as Microsoft Word validation unless Word produced it.
_Avoid_: Client Rendering Authority, generic renderer, invisible converter

**Visual QA**:
The deterministic and visual-agent review of rendered evidence that rejects unresolved placeholders, clipped content, unexpected blank pages, orphaned headings, split table rows, overflowing tables, duplicate sections, inconsistent styles, missing headers or footers, and TOC/page mismatches. Natural content-driven pagination is allowed.
_Avoid_: format check, PDF check, eyeballing

**Prospective Protocol Path**:
The branch of the workflow that produces prospective-study protocol documents from reviewed source inputs.
_Avoid_: protocol path, prospective generation, GP path

**Layout Contract**:
The Reference Protocol’s branding, heading hierarchy, headers, footers, tables, and general visual character as rendered by the Client Rendering Authority. Study-specific content may paginate naturally; exact reference page breaks and page numbers are not required.
_Avoid_: exact page clone, formatting preference, style goal, desired look

**Word TOC**:
A real Microsoft Word table-of-contents field configured to refresh when opened, with locally validated cached display values produced after final content insertion and repagination by the Active Renderer.
_Avoid_: static TOC, manual page numbers, dotted-text index

**Real Word Construct**:
A DOCX structure represented by WordprocessingML semantics, such as real tab stops, list paragraphs, section properties, and table grids.
_Avoid_: plain-text imitation, visual hack, manual formatting

**Data-Driven Table**:
A table rendered from structured row and column data approved in the Source-of-Truth Markdown, with explicit Word geometry and repeatable rules for width, wrapping, and pagination.
_Avoid_: prose table, pasted table text, table blob

**Delivery Gate**:
A required validation condition that must pass before a Branch Document Set is ready for delivery. DOCX delivery requires renderer-identified Visual QA evidence bound to the exact artifact.
_Avoid_: warning, optional check, nice-to-have QA

**Template Rebuild**:
The act of deriving a clean Word-native template from the Reference Protocol’s design system rather than repairing or mutating an existing DOCX package in place.
_Avoid_: patching the template, cleaning the old template, XML package mutation

**Placeholder Compatibility**:
The requirement that a rebuilt template continue accepting the currently supported n8n-style placeholder names.
_Avoid_: renaming everything, schema-only placeholders

**Structural Insertion**:
Renderer behavior that creates or repeats DOCX paragraphs, list items, or table rows as Real Word Constructs instead of replacing placeholder text with blobs.
_Avoid_: text replacement, blob insertion, newline stuffing

**Content Completeness Gate**:
A Delivery Gate that verifies every required leaf section and major table uses an allowed content mode, covers its declared evidence, contains no unresolved placeholder, makes no unsupported study-specific claim, and does not contradict the Canonical Approved Source or another section.
_Avoid_: word-count check, rough completeness review

**Operational Detail**:
Source-provided protocol content that controls study conduct, safety, visit execution, endpoint hierarchy, retention, compensation, or research-related injury handling.
_Avoid_: background prose, optional detail, filler

**Repair Report**:
The reviewer-facing output produced when a Delivery Gate fails, classifying each blocker as a source-evidence gap, drafting failure, cross-document contradiction, document-structure failure, renderer failure, or visual defect and naming the exact next action.
_Avoid_: warning note, partial delivery, caveat

**Fixed Clinical Boilerplate**:
Version-controlled, approved clinical language that is stable across studies within a branch and does not depend on reviewer-provided study facts. A generation agent may select, adapt, and connect it, but may not invent new clinical obligations, safety procedures, benefits, or regulatory claims.
_Avoid_: free-form boilerplate, improvised clinical language, static filler

**Study-Specific Body**:
Protocol content whose wording or structure depends on reviewed source inputs for a particular study.
_Avoid_: generated section, AI section, custom prose

**Required Generated Section**:
A branch-required portion of the Study-Specific Body that declares minimum evidence fields and must contain source-grounded, substantive content before its document can pass delivery. Missing minimum evidence returns the run to source review; sufficient but sparse evidence permits concise drafting.
_Avoid_: AI field, optional prose, populated placeholder

**Document Section Contract**:
The versioned authority for a generated DOCX document’s complete heading hierarchy, section roles, minimum evidence, allowed content modes, Fixed Clinical Boilerplate, drafting expectations, and completeness checks. Protocol and ICF generation and validation consume the same contract; Generated PRS XML retains its separate existing contract.
_Avoid_: template checklist, AI field list, heading audit

**Container Section**:
A heading whose purpose is to group required child sections. It is complete when its required descendants are substantive and need not repeat their content in separate body prose.
_Avoid_: empty section, duplicate introduction, missing content

**Section Draft**:
Structured candidate content for one Required Generated Section, identified by its stable section ID and carrying its approved evidence, selected Fixed Clinical Boilerplate, prose, lists, and tables as applicable.
_Avoid_: AI response, document fragment, generated blob

**Drafting Batch**:
A contract-defined set of related Required Generated Sections assigned to one drafting subagent so narrative work can run concurrently and failed sections can be retried without regenerating accepted work. Batch size follows document complexity rather than a fixed number of agents per document.
_Avoid_: one agent per document, three agents per document, arbitrary section split

**Cross-Document Consistency Gate**:
A Delivery Gate that checks shared study facts across the Canonical Approved Source, Generated Protocol, Generated ICF, and Generated PRS XML without rewriting them.
_Avoid_: final rewrite, consistency cleanup, output merge

**Branch Acceptance Corpus**:
The versioned set of sparse-complete and rich-complete studies for every branch, plus the real inputs that previously produced known content and presentation defects, used to certify a replacement workflow without treating defective outputs as expected results.
_Avoid_: sample inputs, smoke fixtures, happy-path tests

**Presentation Defect**:
An obvious non-substantive error in the Reference Protocol or template surface, such as a typo or malformed label, that should not become part of the Layout Contract.
_Avoid_: reference mismatch, template preference

**Structured Operational Field**:
A machine-readable representation of Operational Detail, such as criteria items, visit rows, endpoint hierarchy, safety roles, or schedule cells.
_Avoid_: preformatted prose, Word-ready blob, paragraph string

**Legacy String Fallback**:
Compatibility behavior that converts older preformatted string fields into Real Word Constructs while reporting that normalization occurred.
_Avoid_: silent cleanup, old field support

**Branch Completeness Checklist**:
The explicit, versioned list of required sections, tables, and document elements for a document-generation branch.
_Avoid_: inferred completeness, template scan, word-count proxy

**Internal QA Artifact**:
A Section Draft, verifier finding, retry record, renderer-identified PDF, page image, audit file, artifact hash, or page-level result saved as workflow evidence but not delivered to the client by default. Any document change invalidates its associated render evidence.
_Avoid_: client deliverable, attachment, proof packet

**Generation Manifest**:
The internal record binding a Run Revision to the versions or hashes of its Canonical Approved Source, contracts, Fixed Clinical Boilerplate, Contracted Templates, model, Active Renderer, evidence, and generated artifacts.
_Avoid_: log summary, latest configuration, output list

**External Render Evidence**:
A human- or system-supplied render from a client-like environment that can be used as stronger Visual QA evidence than weaker fallback renderers.
_Avoid_: screenshot, client PDF, manual proof

**Source Completeness Gate**:
The branch-aware pre-generation contract that validates document-control values, operational source facts, explicit approval, candidate conflicts, and Data-Driven Table schemas before final rendering.
_Avoid_: metadata check, input cleanup, best-effort validation

**Controlled Delivery Pipeline**:
The auditable workflow that runs independent read-only content, structure, package, visual, and Word TOC review passes, regenerates failed documents through one controlled path, reruns affected gates, and filters client-facing outputs from Internal QA Artifacts.
_Avoid_: post-processing, output cleanup, manual QA script

**Readiness Contract**:
The agreed evidence and scope boundary that determines when all three study branches are ready and whether a later report is a contract bug, a reference defect, or a new requirement.
_Avoid_: done checklist, issue list, bug pile

**Document Renderer**:
The generation capability that turns an approved Branch Document Set into rendered client documents and produces package, visual, Word TOC, and format-specific quality evidence for verification.
_Avoid_: exporter, rendering script, document cleanup
