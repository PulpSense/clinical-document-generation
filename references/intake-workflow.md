# Intake workflow

1. Preserve supplied files under the run's `input/` directory when available.
2. Translate source aliases into `reference/study.reference.json` using the
   canonical schema.
3. Run `workflow.py --stage prepare` once. If mandatory fields are missing,
   return the generated repair report in one batch.
4. Deliver the generated editable Source-of-Truth Markdown file. Do not replace
   it with chat text.
5. The reviewer edits that file and approves it once.
6. Run `workflow.py --stage generate`. Do not ask new source questions after
   approval. Missing optional detail stays blank or uses authorized standard
   clinical boilerplate where the section contract permits it.
7. Satisfy Hermes drafting requests until `status: unreviewed`; then deliver the
   complete `experimental_outputs` using the links and recorded generation time
   in `delivery_message`. Follow [generation-only.md](generation-only.md).

The canonical approved reference never stores model prose or a legacy flat
placeholder layer. Rendering maps canonical facts and accepted section drafts
directly into the client templates.

## Represent facts before approval

For participant registry disclosures, interpret the supplied consent instructions
and record the explicit decision as a boolean at
`regulatory.prs.participant_registry_disclosure`. A request for the standard
ClinicalTrials.gov consent disclosure means Yes; an explicit decision to omit it
means No. Leave an unspecified decision blank. Registration plans, interventional
classification and requests for XML do not establish consent-disclosure
applicability. Reconcile conflicting narrative and structured decisions with the
owner before approval. Preserve the distinction between a sponsor's request and
a statement about legal necessity; do not invent an NCT identifier or approval.
The structured aliases `regulatory.clinicaltrials_consent_disclosure_applies`
and `regulatory.clinicaltrials_gov_disclosure_required` are supported for existing
sources. Their values must agree with the canonical field; when correcting the
decision, update all supplied declarations before regenerating the review file.

Apply these rules to every study branch during the Extraction Pass. Preserve the
raw evidence and show the resulting facts in the editable Source-of-Truth.

- Classify observational versus interventional design from explicit evidence in
  `regulatory.prs.study_type`. Observational studies need no assigned test article.
  Preserve a named routine product when supplied; otherwise a descriptive activity
  name/type may be derived from explicit facts or left not applicable. Show these
  normalizations for approval. Do not invent a treatment assignment. Ask about real
  contradictions, such as a payment trigger inconsistent with the schedule.
  Compare the declared study type with source descriptions of treatment assignment.
  If one says observational while another explicitly says the study randomly assigns
  treatments, quote both statements and ask which design is correct in the consolidated
  source question, before requesting Source-of-Truth approval. Masking alone does not
  establish treatment assignment. Record the clarified study type and consistent design
  wording in the editable Source-of-Truth, preserving the original evidence. Generation
  uses that approved classification; Brad's XML supplies structure, not a default study
  type for other studies. This is AI intake guidance, not a post-generation check.
- Represent supplied visits as rows with `visit`, supplied `timing`, and
  `procedures` assigned to that visit. Convert explicit narrative relationships
  into rows: “Screening: history. Week 8: questionnaire” already supplies those
  relationships. Keep quantities, units, timing anchors, windows, conditions,
  negations, and historical versus prospective phases with their activities.
  Keep genuinely unassigned requirements as separate assessment notes. A missing
  optional window stays blank; a visit label is not a reason to invent one.
  Keep occurrence counts (such as one operative visit per eye) in the visit
  description rather than repeating them as a timing window. A name such as
  "Screening" alone supplies no screening window.
  Use one visit-label convention across all documents. Preserve explicit source
  visit numbers. When the source lists phases with repeated occurrences, such as
  one operative visit per eye, retain those phase names in the ICF rather than
  inventing expanded visit numbers. Occurrence counts and schedule-row numbers
  describe different things; show any derived convention in the Source-of-Truth.
  Put explicit activity/visit relationships in the structured schedule. Keep
  one row per actual assessment or action. Keep questionnaire response choices
  and score ranges in that questionnaire's description, not as extra activities.
  Use short activity names in schedule rows, such as "Study-eye pressure".
  Keep the complete instrument, units, reading count, selection rules, score
  anchors and exceptions in `procedures.assessment_details` or `procedures.methods`;
  the narrative explains these methods while the matrix shows when each activity
  occurs. Preserve distinctions needed to identify different activities in their
  row labels, such as both-eye selection versus fixed-eye follow-up. Show both
  the concise row and its full method for Source-of-Truth approval. Existing
  approved rows remain unchanged during generation.
  Put statements such as "no separate exit form" in supplemental notes rather
  than making them checked procedures. In ambispective studies, distinguish
  staff abstraction of historical records from future participant contacts;
  preserve each contact's in-person or telephone mode and its own assessments.
  Store appointment length separately from `timing`: "Day 84 +/- 7 days after
  enrollment" is a window; "approximately 35 minutes" is a visit length.
  Use `study.participation_duration` for explicit participant-duration facts.
  Keep `procedures.assessments` and `procedures.evaluation` for additional unallocated
  facts or qualifications, rather than copying a second assessment inventory.
  Reconcile abbreviated matrix column labels with explicit narrative timing
  anchors. For example, preserve "postoperative" when the narrative identifies
  the Month 3 assessment as 3 months after surgery; a shorter matrix label must
  not erase that relationship.
- Preserve the approved population, cohorts, and comparisons separately from
  prose labels. Populate `design.arms` when the source identifies groups,
  including a single observational cohort when explicitly supported. A missing
  group inventory is unknown, not zero; “no control” alone does not prove that
  there is only one active cohort. Preserve sample counts and their group/total
  relationships. The renderer converts supported legacy count records into
  readable display text.
- Use `study.references` for supplied bibliographic entries in their cited
  order. Keep citation identifiers and qualification on prior findings. The
  Protocol carries the bibliography; the ICF explains the clinical evidence in
  participant-facing language without unexplained reference numbers.
- Preserve full person display names. Supply `first_name`, `middle_name`,
  `last_name`, and `degrees` when their components are clear; keep honorifics and
  role titles distinct from given names and degrees. Prefer supplied components
  for compound or culturally variable names. Keep site investigators in the
  corresponding site record rather than only naming the overall investigator.
- Preserve an explicit `study.short_title`. When absent, derive a concise phrase
  from the full title and show it for approval. Retain the unchanged full title.
  Aim for a short running-header label, often 6–10 words and around 60 characters
  or fewer, naming the distinguishing intervention/topic and outcome. These are
  writing guides, not input gates. Avoid carrying the full design preamble or
  long introductory phrase from the official title into the running title.
  The renderer's shared short-title fallback remains available for older sources.
- Keep `design.study_design_summary` to a short description of the actual
  design, assignment and comparison. Retain complete design evidence separately
  in `design.study_design`; a synopsis is not a copy of the intake field labels.
- Separate `procedures.study_termination` (supplied grounds/authority for early
  stopping) from `study.completion` (the supplied planned completion trigger and
  administrative closeout). Keep dates in `study.timeline`. Leave termination
  absent when no early-stopping policy is supplied; a planned end date is not
  an early-termination rule. Treat embedded writing directions as instructions,
  preserving their underlying policy as facts rather than patient-facing prose.
- Carry every explicit eligibility restriction into the appropriate canonical
  inclusion or exclusion list, including restrictions supplied separately from
  those lists. Preserve any dedicated structured field as well. For example, a
  supplied interval without participation in another interventional study belongs
  in the eligibility criteria as well as the screening-interval field, so the
  same approved restriction reaches Protocol, ICF and XML. Show the placement
  for source approval; never derive a new restriction from an example.
  Phrase inclusion criteria as requirements for eligibility and exclusion
  criteria as disqualifying conditions. For example, "must not have participated
  in another interventional study during the previous 30 days" is an inclusion
  requirement; its equivalent exclusion is "Participation in another
  interventional study during the 30 days before screening." Preserve scope,
  timing, exceptions and negation, and choose one consistent placement before
  approval. Do not copy a negative eligibility requirement unchanged under an
  Exclusion Criteria heading or duplicate it under both headings.
- Preserve the unit of eligibility and criterion-specific conditions/exceptions
  inside the relevant inclusion/exclusion entries. Retain cross-criterion rules
  in `population.eligibility_notes`, including supplied rules distinguishing
  a person from eligible eyes, records or other subunits. Preserve separately
  whether missing data limits an analysis rather than cohort membership.
  These notes are optional; add no rule absent from the input.
- Populate format-specific structured fields from facts explicitly stated in
  the intake, not just from identically named form questions. Keep coded
  type/status values separate from narrative descriptions: observational design
  belongs in the study-design fields, rather than in an intervention-type value.
  Preserve an explicitly supplied condition and IRB submission status in their
  supported fields; leave genuinely absent regulatory facts absent.
  Keep narrative IRB submission/review status distinct from a PRS approval-status
  value. Store an explicitly supplied PRS value in `parties.irb.approval_status`;
  keep the source's submission statement in `ethics.approval_status`. "Not
  submitted" alone does not authorize assigning "Pending" or "Approved" in XML.
  Show the distinction for source approval; a missing optional PRS value remains
  blank rather than triggering an extra question.
- Preserve supplied privacy, costs, injury, and closeout procedures in their
  own fields. Missing optional procedures remain absent and use only authorized
  Fixed Clinical Boilerplate where permitted; they are not additional obligatory
  inputs or permission to invent operational policy.
- Inspect background and rationale for study-specific qualified potential
  benefits. Preserve applicable statements and their uncertainty in
  `risks_benefits.benefits` as well as the original background; keep historical
  findings distinct from expected study benefit and never promise personal
  treatment benefit from retrospective record review. Absence of a dedicated
  benefits label does not mean the source supplies no benefit. If none applies,
  leave the field absent; do not invent one or request extra optional input.

Before requesting approval, consume `prepare.intake_review`: inspect its obligatory-input checklist, supplied representations and raw field candidates. AI determines actual missing facts and conflicts, including disagreement among candidate sources. Compare the proposed Source-of-Truth with the raw
evidence for lost facts and changed relationships, and inspect its computed
assessment table. Correct extraction omissions at this point. Ask one consolidated question for Required Source Inputs or actual unresolved conflicts in supplied material facts;
representation work and optional omissions do not justify extra questions.

For reused, byte-identical approvals with explicit relationships still in prose,
the drafting request may authorize a source-quoted display interpretation. This
does not revise approval or reinterpret ambiguous evidence: unresolved assignments
remain notes. The independent reviewer must reconcile raw source with the actual
tables and intended narrative sections, including any qualified benefit clauses.

## Source review handoff

For `awaiting_approval`, attach/upload `review_delivery.absolute_path` and use `source_review_reply.message`, which contains `review_delivery.link`. Keep the clickable link in the chat reply when the client can access that file. If local attachments are unsupported, use the supported accessible-file upload/link mechanism. Ask the client to review/edit and approve that exact file once; preserve its markers and actual bytes. Source facts stay in the editable artifact, rather than a chat transcription.
