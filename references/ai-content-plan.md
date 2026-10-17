# AI-owned content plan

Before section drafting, read the entire approved_source, selected templates,
consent comments, authorized clauses and fixed boilerplate in the planning
request. Produce one shared plan. Source facts take precedence over examples.
AI owns applicability, interpretation, clinical wording, omissions, duplication,
short titles, duration, tables and registry values. Code renders explicit values;
it supplies no clinical defaults and performs no semantic review or repair.
Preserve every material qualification. Missing optional facts stay absent.

Return JSON with schema_version `clinical-content-plan/v1`, the exact request_id
and request_sha256, producer.model_id identifying the actual model, and `plan`.
The plan contains exactly these keys:

- `docx_fields`: an object per artifact (`protocol`, and `icf` when requested),
  each mapping its complete docx_field_names inventory to final strings. Use
  explicit empty strings for unused fields. Draft body placeholders (`AI_...`)
  can be empty because the subsequent section responses replace their complete
  bodies. Populate front matter, short running title, participant counts,
  duration/follow-up, visit counts, summary variables/endpoints, contacts,
  institutions, test/control articles and signature identities where their tokens
  occur. Keep Sterling's reserved merge fields exactly as its comments require
  within ICF fields. Protocol fields retain actual study identities.
  `studySiteAddress` includes the complete site directory when multiple sites
  participate. Choose a short descriptive title and an accurately anchored
  participant duration. Distinguish staff tasks from participant contacts.
- `visits`: ordered objects with string fields `visit`, `timing`,
  `display_visit_number`, `CRFnumber`. AI resolves source representations and
  identifies staff tasks, historical abstraction and actual participant visits.
  Use empty identifiers where appropriate; builders never infer or renumber them.
- `tables`: exactly `study-sites`, `schedule-of-assessments`,
  `sample-size-evidence`. Each has `caption`, `header_rows` (1 or 2), `rows`
  (rectangular arrays of strings) and `supplemental_notes` (strings). An unused
  table has empty rows and notes. For a schedule matrix, the first column holds
  activities and the remaining columns hold approved contacts; a two-row header
  has an empty first cell in its second row. AI places every activity, safety
  obligation and timing qualification in the right column or adjacent note.
  Keep historical review and staff activities distinct from participant visits.
  Omit a note only after checking that all its meaning is already represented;
  identical words alone do not establish duplication. Place general risks in
  their owning prose section. The site directory uses three columns: site,
  investigator, contact. Keep supplied sample-size evidence and uncertainties.
- `source_sections`: an object addressing every protocol section whose catalog
  role is `source`. Each value has `include` (boolean) and `blocks`. Decide from
  the full source whether assignment, participant termination and study
  termination apply, regardless of which source field contains the facts. Draft
  the complete source-grounded text here when included. An excluded section has
  empty blocks. Code uses this explicit decision to place/remove its heading.
- `investigator_agreement`: complete blocks, using applicable authorized
  investigator-agreement language and principles from fixed_boilerplate.
- `container_introductions`: protocol container section IDs mapped to blocks,
  only where an introductory paragraph is useful. Complete body sections are
  written in later drafting requests.
- `shell_edits`: an object for each requested artifact (`protocol`, and `icf`
  when present), containing paragraph edits `{ "index": 123, "text": "..." }`.
  Indices identify the original template body paragraphs in the request. A null
  text removes that paragraph. Unlisted paragraphs retain their template text.
  Read every template paragraph and choose the retained clinical/legal language
  deliberately. Replace study examples, template instructions, legacy trial
  claims and retained contact prose with correct complete text. Keep the client
  headings, signature lines, authorization choices and merge-field labels.
  Use literal final text or the supplied field tokens. Preserve mandatory
  template safeguards and the distinctions between future use, specimen storage,
  genetic results, clinical results, authorization duration and record retention.
  The raw template tables and authority comments are supplied for context too.
- `extra_icf_sections`: ordered objects with `heading`, `before` (an existing
  selected-template heading) and `blocks`. AI explicitly includes applicable
  conditional clauses such as Sterling GINA and ClinicalTrials.gov disclosure.
  Read genetics/GINA facts anywhere in the source, including ethics fields and
  narrative instructions; a canonical trigger field is not the only evidence.
  Use authorized template wording and permitted substitutions. Place a GINA
  heading and safeguards before QUESTIONS when applicable. Place an authorized
  registry statement before QUESTIONS as a separate block; an empty heading
  means insert only its blocks. Respect an explicit registry-disclosure decision;
  a request for XML alone does not establish consent-disclosure applicability.
  Record each considered conditional clause's inclusion/omission in decisions.
- `bibliography`: the complete final protocol bibliography as one string, with
  stable citation numbers shared by every drafting batch. Empty when absent.
- `xml`: null for retrospective studies. Otherwise an object with `design_branch`
  (`observational_design` or `interventional_design`), `scalars` and `repeated`.
  Use xml_schema and the supplied governed XML template for paths and element
  order. scalars maps every non-repeated leaf path of the selected branch to its
  final string, including explicit blanks for unsupported optional fields.
  repeated contains arrays for intervention, arm_group, primary_outcome,
  secondary_outcome, other_outcome and location. Each record maps all its listed
  relative leaf paths to final strings. intervention.arm_group_label may instead
  be an array of strings when an intervention belongs to multiple groups.
  Decide enrollment, observational timing, cohort/exposure descriptions,
  interventions and group links, eligibility restrictions, biospecimen fields,
  contacts and enum representations from the full source. Preserve approved
  classifications and Brad's manual XML structure. Use explicit approved dates,
  statuses and identities; keep unknown optional fields empty. Supply the same
  study UID in outcome records. Later AI narrative drafts populate the fixed
  brief_summary/textblock and detailed_description/textblock paths.
- `decisions`: source-grounded rationale records for applicability, source
  relationships and meaningful omissions. These are internal run records,
  never clinical document prose. Account for the genetics/GINA decision,
  registry disclosure, optional protocol sections, schedule qualifications,
  participant duration and XML group/intervention relationships when relevant.

Every `blocks` array contains `{ "text": "...", "bullet": false }` objects
(use true for a bullet). Return the complete response, not a patch. Completion
means every token, optional-section decision, planned table and XML path is
explicit, every retained template passage has been considered, and all material
source facts have a clear owner in the plan or subsequent section drafts.

Section drafting retains the original n8n prompts and Brad's later corrections.
Read the full approved source and this shared plan in every batch. Follow the
planned inventory and bibliography consistently. AI drafts complete sections;
code inserts their text and lists without completing or deduplicating them.
