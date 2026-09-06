# Source Fidelity and Layout Corrections

These narrowly scoped rules were authorized for the clinical-output quality
correction. They apply to all applicable study branches and both ICF families;
they are not permission to redesign the client documents during a run.

## Source and population

- Sponsor identity and address form one role-specific block. Funding-source
  identity must not be concatenated into it, whether the organizations match or
  differ. Preserve funding information separately where applicable.
- Include every supplied site-address component. Accept structured or complete
  string addresses without duplication; never invent a postal code.
- Both visit tables use the same visit identities. Preserve explicit identifiers;
  consistent display ordinals may identify an explicit ordered visit schedule.
  An assessments-only list is not a source of invented numbered visits.
- Reconcile structured visit associations with supplied assessment and safety
  requirements. Every-contact safety assessment must retain that relationship,
  subject to consent-before-procedures requirements. Unallocated assessment
  timing must not become guessed visit marks or an assertion of nonperformance.
- Successful completion, early discontinuation, and administrative closeout are
  distinct. Specific completion criteria and decision-making authorities constrain
  general boilerplate. Source citation or boilerplate membership alone does not
  establish semantic fidelity.
- Compare timeline statements only after identifying their reference points.
  Enrollment duration must not mask contradictory participant follow-up. Report
  genuine source conflicts for clarification; do not silently rewrite them.
  An unspecified timing origin is not a demonstrated contradiction or a missing
  obligatory input. Do not request extra anchors or reject unchanged source on
  the basis of a conditional subtraction. Preserve the supplied timing verbatim;
  never invent a shared origin or rewrite a duration to make it agree. Conflicts
  established by explicit comparable anchors remain findings.

## Authorized layout scope

- Preserve client font families, sizes, emphasis, page geometry, legal language,
  headers/footers, and usable signature fields. A generic compact-table override
  must not replace the authority's typography with smaller type.
- Keep table width, column grid, and cell widths coherent. Header construction and
  column allocation must support readable wrapping, not merely absence of clipping.
- Equivalent ICF section headings have one family-consistent left alignment,
  retaining bold/underline and typography. This never requires every heading to
  start a new page.
- The legacy hard break before Protocol Section 15 may be normalized to natural
  flow. Preserve required TOC and first-body boundaries; do not remove arbitrary
  breaks or join entire large sections merely to force a page-count target.
- Protect a heading with the beginning of its table and avoid stranding a short
  trailing paragraph before a forced boundary. Natural sentence continuation
  across pages is not a content error.
- Preserve the physician-notification prompt and both unmarked choices. Remove
  only redundant non-signature spacers where governed, keeping the consent block
  coherent. Do not reduce usable signing space or delete content to save a page.
- Maintain live heading-linked TOC fields with populated current-render caches;
  verify destinations against the final render, not fixed expected page numbers.
  Different viewers may paginate differently. A correct generating render is not
  a guarantee of identical pagination in every viewer.

## Review and PRS readiness

Every-page visual review and exact-artifact delivery remain mandatory. A sparse
page may be justified by its function, but a claimed approved layout exception
must identify an actual rule or originating approval record. Another reviewer's
unsupported assertion is not approval provenance.

Keep source fidelity, PRS transport vocabulary, and conditional registration
readiness distinct. The PRS upload schema documents sex tokens `All`, `Female`,
and `Male` (with `Both` equivalent to `All`), although its `gender` declaration
uses `xs:string`, not an XSD enumeration. Map source display wording explicitly;
do not change the approved source to match transport spelling.

Unknown calendar dates cannot be derived from a document-control date or relative
visit durations. Optional empty fields remain optional; deprecated `end_date`
is not a separate required value. Registration completeness must not be inferred
from XML structural validity, and no report may claim successful PRS submission
without actual submission evidence. No new obligatory source-intake fields are
introduced by these rules.

Official upload schema:
https://cdn.clinicaltrials.gov/documents/xsd/prs/ProtocolRecordSchema.xsd

## Maintenance and evidence

Keep failed runs immutable. Debug ZIPs are produced only on explicit request;
GitHub-connected maintenance is the ordinary debugging path. Installation-only
packaging is distinct from a debug ZIP and does not authorize distribution of
study data.

Test Retrospective Protocol and Prospective/Ambispective with Advarra/Sterling,
including long/short narratives, differing visit structures, optional absences,
and deliberately introduced defects. Preserve the six production modules and
model flexibility. A structural formatting test is not clinical or visual
certification.
