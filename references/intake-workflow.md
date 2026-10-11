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
7. Satisfy Hermes drafting and verification requests until the workflow returns
   `status: passed`; then return only `client_outputs`.

The canonical approved reference never stores model prose or a legacy flat
placeholder layer. Rendering maps canonical facts and accepted section drafts
directly into the client templates.

## Represent facts before approval

Apply these rules to every study branch during the Extraction Pass. Preserve the
raw evidence and show the resulting facts in the editable Source-of-Truth.

- Classify observational versus interventional design from explicit evidence in
  `regulatory.prs.study_type`. Observational studies need no assigned test article.
  Preserve a named routine product when supplied; otherwise a descriptive activity
  name/type may be derived from explicit facts or left not applicable. Show these
  normalizations for approval. Do not invent a treatment assignment. Ask about real
  contradictions, such as a payment trigger inconsistent with the schedule.
- Represent supplied visits as rows with `visit`, supplied `timing`, and
  `procedures` assigned to that visit. Convert explicit narrative relationships
  into rows: “Screening: history. Week 8: questionnaire” already supplies those
  relationships. Keep quantities, units, timing anchors, windows, conditions,
  negations, and historical versus prospective phases with their activities.
  Keep genuinely unassigned requirements as separate assessment notes. A missing
  optional window stays blank; a visit label is not a reason to invent one.
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
  The renderer's shared short-title fallback remains available for older sources.
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
