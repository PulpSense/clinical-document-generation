# Clinical Document Generation

This context describes the document-generation workflow for clinical study artifacts. It names the review, rendering, and template concepts that must stay precise because small wording drift can create real delivery risk.

## Language

**Reference Protocol**:
A known-good protocol document used as the visual and structural authority for generated protocol output.
_Avoid_: good protocol, actual protocol, sample protocol

**Embedded Client Reference**:
A retained client protocol example bundled with the skill so each run can follow the established client document shape without requiring the client to upload an example again.
_Avoid_: uploaded example, temporary reference, sample file

**Client Template Authority**:
A retained client DOCX that defines the Layout Contract and, for an ICF family, the Client ICF Language. Its study-specific values are reference data and never evidence for another study.
_Avoid_: sample document, content source, generic template

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

**Compatible Python Runtime**:
An explicitly resolved Python 3.10+ executable, recorded by absolute path, implementation, and version for each Desktop operation process. An unqualified system `python3` command is not a runtime identity.
_Avoid_: system Python, default Python, current interpreter

**Desktop Operation Deadline**:
The single 30-minute post-approval correctness ceiling persisted as a cross-process UTC deadline. Each process may use its own monotonic clock only to measure time inside that process; a resume never interprets a prior process's monotonic epoch or creates a new budget.
_Avoid_: process timeout, monotonic deadline, retry timeout

**Run Revision**:
An immutable source-approval identity tied to one exact approved source. Each changed generation authority starts a new immutable, hash-inventoried Generation Authority Attempt beneath that revision; it never overwrites prior drafts, evidence, or outputs. Only the newest passing attempt is client-facing; earlier attempts remain internal audit history until explicitly removed.
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
An identified office application used to open a DOCX and produce the PDF used for quality review.
_Avoid_: exporter, converter, editor

**Client Rendering Authority**:
The office application used by the client to open the delivered DOCX; Microsoft Word desktop is the current client’s renderer. It is the compatibility target, even when a different Active Renderer performs local Visual QA.
_Avoid_: active renderer, local renderer, whatever opens it

**Host Office Renderer**:
Microsoft Word or LibreOffice on the generation host, verified during installation and used only for DOCX-to-PDF conversion. It is a declared host prerequisite and is never copied into or discovered from the release runtime.
_Avoid_: packaged office fallback, release-owned renderer, Pages

**Active Renderer**:
The Host Office Renderer selected for one render attempt and recorded with its Visual QA evidence. Passing evidence proves the artifact under that renderer only and must not be described as Microsoft Word validation unless Word produced it.
_Avoid_: Client Rendering Authority, generic renderer, invisible converter

**Release-Owned Page Renderer**:
The single manifest-bound `pypdfium2` runtime that converts the Host Office Renderer’s exact PDF bytes into every page image used by Visual QA. Packaging derives its normalized extraction inventory from the pinned wheel; provisioning and every later use rehash that inventory from the immutable manifest rather than trusting writable runtime metadata. Formal installation smoke verifies a pre-promotion candidate only inside the lifecycle-owned installation staging root. An explicitly requested `manual_pre_release` operation may instead provision and smoke-test a directly extracted, hash-valid unsigned candidate with promotion checks disabled; that mode is recorded in run evidence and does not confer promotion or certification. Every certified ordinary or active-root assurance requires and verifies the independent promotion record, including its hash binding to the exact installation-assurance bytes, so deleting or mutating writable assurance metadata cannot downgrade or alter active-release trust. Native rendering runs only in a killable worker with time, page, pixel, dimension, output, and supported process-resource limits; its complete process group is terminated and reaped after timeout, crash, malformed protocol, or successful exit. It never falls through to another PDF backend.
_Avoid_: host page renderer, PDF fallback ladder, mutable runtime marker

**Release-Owned Render Assurance Assets**:
The Release-Owned Page Renderer and approved compatible fonts whose immutable identities belong to the active skill release. These assets supplement but do not replace the Host Office Renderer prerequisite.
_Avoid_: packaged office suite, optional dependency, best-effort tooling

**Render Assurance**:
The mandatory evidence-backed result showing that the exact Generated Protocol and Generated ICF bytes were rendered and visually reviewed under an identified Active Renderer. An environment or tooling fault leaves assurance unresolved rather than failed; a genuine visual defect must be repaired and reassessed.
_Avoid_: render status, preflight pass, renderer availability

**Visual QA**:
The deterministic and visual-agent review of rendered evidence that rejects unresolved placeholders, clipped content, unexpected blank pages, orphaned headings, split table rows, overflowing tables, duplicate sections, inconsistent styles, missing headers or footers, and TOC/page mismatches. Natural content-driven pagination is allowed.
_Avoid_: format check, PDF check, eyeballing

**Prospective Protocol Path**:
The branch of the workflow that produces prospective-study protocol documents from reviewed source inputs.
_Avoid_: protocol path, prospective generation, GP path

**Layout Contract**:
The client reference’s page geometry, branding, fonts, typography, styles, spacing, margins, heading hierarchy, numbering, headers, footers, tables, signature structures, document-control layout, and general visual character as rendered by the Client Rendering Authority. Study-specific content may paginate naturally; exact reference page breaks and page numbers are not required, and known Presentation Defects are not preserved. Layout repair may change only pagination controls or the smallest necessary Word-native structure and must preserve this authority and the clinical content.
_Avoid_: exact page clone, formatting preference, style goal, desired look

**Template-Family Layout Repair**:
A bounded, composable correction for a verified visual defect class in one Contracted Template family. It targets the smallest identified element, preserves the Layout Contract and clinical meaning, and requires a fresh exact-artifact render and review.
_Avoid_: study-specific workaround, global reformat, content rewrite

**Document Control Date**:
The reviewer-editable date displayed in generated Protocol document-control surfaces using the client format `dd MMM yyyy`. When absent from the Source Intake Packet, it defaults to the Source-of-Truth preparation date and remains stable across approval, retries, and later rendering.
_Avoid_: generation date, current render date, automatic timestamp

**Document Control Version**:
The reviewer-controlled Protocol version displayed consistently in applicable document-control surfaces. It remains blank when absent from the Canonical Approved Source and is never defaulted from a Client Template Authority.
_Avoid_: template version, automatic version, default 1.0

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
A Delivery Gate that verifies every required leaf section and major table satisfies its section-specific drafting expectations, covers all material declared evidence and Operational Detail, contains no unresolved placeholder, makes no unsupported study-specific claim, and does not contradict the Canonical Approved Source or another section. Reference-calibrated content density may identify suspiciously compressed drafting, but raw word count alone never establishes completeness.
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

**Source Evidence Coverage Map**:
The machine-readable mapping from each required approved source fact to the generated sections and artifacts that must preserve it. It catches missing required evidence before rendering while leaving semantic fidelity, contradiction, and invention judgments to independent review.
_Avoid_: substring match, reviewer memory, word-count coverage

**Source-Grounded Elaboration**:
Drafting that reorganizes or paraphrases approved facts, states only conclusions that directly follow from them, and uses versioned Fixed Clinical Boilerplate only where the Document Section Contract permits it. It may improve clarity and flow but may not introduce a new number, date, procedure, risk, benefit, eligibility rule, role, commitment, or causal claim merely because that addition would be clinically plausible.
_Avoid_: reasonable invention, creative completion, assumed standard practice

**Evidence-Scaled Section Depth**:
The rule that a generated section follows the Reference Protocol's relative emphasis while its actual length is supported by the richness of approved evidence. A concise complete section passes; filler, repetition, or invented detail used to reach a fixed word count fails.
_Avoid_: minimum word count, length padding, verbosity target

**Drafting Batch**:
A contract-defined set of related Required Generated Sections assigned to one drafting subagent so narrative work can run concurrently and failed sections can be retried without regenerating accepted work. Batch size follows document complexity rather than a fixed number of agents per document.
_Avoid_: one agent per document, three agents per document, arbitrary section split

**Cross-Document Consistency Gate**:
A Delivery Gate that checks shared study facts across the Canonical Approved Source, Generated Protocol, Generated ICF, and Generated PRS XML without rewriting them.
_Avoid_: final rewrite, consistency cleanup, output merge

**Branch Acceptance Corpus**:
The versioned set of sparse-complete and rich-complete studies for all five supported document families, plus every real input that previously produced a known content or presentation defect, used to certify the workflow without treating defective outputs as expected results.
_Avoid_: sample inputs, smoke fixtures, happy-path tests

**Release Reliability Evidence**:
The passing evidence bound to exact packaged bytes: the complete Branch Acceptance Corpus, one real Hermes generation for each supported document family, and installation, activation, delivery, and rollback smoke tests. A package without this complete evidence is a candidate, not a reliable release.
_Avoid_: one successful run, local test pass, unbound certification

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
The branch-aware pre-generation contract that confirms every obligatory input for the selected branch was submitted, resolves conflicts, validates Data-Driven Table schemas, and binds explicit approval. It establishes completeness rather than prose quality: a modest but complete source passes, while an absent required fact does not.
_Avoid_: quality score, metadata check, input cleanup, best-effort validation

**Controlled Delivery Pipeline**:
The auditable workflow that runs independent read-only content, structure, package, visual, and Word TOC review passes, regenerates failed documents through one controlled path, reruns affected gates, and filters client-facing outputs from Internal QA Artifacts.
_Avoid_: post-processing, output cleanup, manual QA script

**Deterministic Workflow Authority**:
The code-owned boundary for mechanically enforceable values and structures, including section identifiers, required-fact checklists, tables, XML shape, verification envelopes, hashes, template placement, and repair routing. Models supply Source-Grounded Elaboration and independent review judgments, not protocol identity or control-plane data.
_Avoid_: model-generated envelope, AI-owned XML structure, inferred repair target

**Client Model Choice**:
The model selected by the client at operation time for drafting and review. The skill does not require or pin a vendor, model family, or version, and records the model actually used so newer GPT, Anthropic, or other client-selected models do not require a skill change.
_Avoid_: required model, pinned GPT version, model allowlist

**Progress-Based Recovery Ladder**:
The ordered set of governed recovery strategies for an Internal Reliability Defect. Each retry must be tied to a specific finding and make a material semantic change in evidence, strategy, or normalized candidate content. Raw package churn is not progress. When all safe deterministic strategies are present, the exact reviewer is re-prompted for reinspection and finer localization; repairable work continues within the original 30-minute ceiling.
_Avoid_: three blind retries, identical rerun, global attempt exhaustion

**Final Exact-Artifact Review**:
The mandatory package-wide content and cross-document review plus every-page visual review of every exact document proposed for delivery. Intermediate repair checks may be limited to changed sections or artifacts, but no earlier or partial review can replace this final complete pass.
_Avoid_: sampled pages, reused final pass, unchanged-file assumption

**Readiness Contract**:
The agreed evidence and scope boundary that determines when all three study branches are ready and whether a later report is an Internal Reliability Defect, a reference defect, or a new requirement. Once an approved source passes the Source Completeness Gate for a supported branch and Contracted Template, unchanged clinical input may not be blamed for a later internal workflow failure.
_Avoid_: done checklist, issue list, bug pile

**Internal Reliability Defect**:
A post-admission failure in drafting, document or XML construction, reviewer-response binding, repair routing, or repeatable Contracted Template layout behavior. The workflow must recover from it within the same Run Revision when possible; it never justifies requesting new source approval when the Canonical Approved Source is unchanged.
_Avoid_: source deficiency, client blocker, reapproval trigger

**Permitted Terminal Blocker**:
A fail-closed condition outside the admitted generation contract: corrupt or changed integrity evidence, unavailable required host software, a persistent model/API/network outage, inaccessible delivery storage, a pre-generation unsupported branch or template, the fixed 30-minute ceiling, or a genuine unresolved visual defect. An unresolved visual defect remains unpublished and becomes regression evidence for a product fix.
_Avoid_: drafting exhaustion, malformed reviewer response, unknown internal routing, known pagination defect

**Document Renderer**:
The generation capability that turns an approved Branch Document Set into rendered client documents and produces package, visual, Word TOC, and format-specific quality evidence for verification.
_Avoid_: exporter, rendering script, document cleanup
