# General native document repair


A failed substantive AI assessment creates one `document_repair` request for the complete native document set. The repair author receives approved source/template evidence, stable concern IDs, current native files and retained reviewer evidence. `workspace_path` contains editable deliverable files; `tools_path` holds arbitrary run-local scripts. AI can use DOCX/XML libraries directly for paragraphs, table associations, headers/footers, metadata and arbitrary XML nodes. No edit DSL, rule registry or pre-registered location is required. XML structural diagnostics also use this general workspace rather than the old scalar editor.

The bound `hermes-response/v2` reports `completed`, `disputed` or `needs_review`, actual author/model identity and a summary. Disputes include source-grounded explanations. The workflow verifies request/source/base identities, exact native inventory, file readability and XML structure before adopting a new immutable whole-file checkpoint. Later assembly and renderer font substitution preserve accepted native content. Only objective font replacement operates on those bytes during renderer fallback. Stale render/review evidence is invalidated. Final package-wide content and cross-document review are fresh after each repair. Changed DOCX are rerendered and every page independently reassessed. A passing visual assessment can be reused only for identical native/PDF/page bytes under unchanged current renderer identities, approved source and generation authority, with no new applicable visual concern and independent reviewer identity. Reuse retains the original request/response bytes and review-set identity; it does not create a fictional fresh assessment. Prior substantive findings and all repair-author IDs stay bound to the independent review requests, including exact-envelope transport retries.

Malformed tool/response results receive actionable feedback without clinical findings or adoption. An identical ineffective technical response/workspace after feedback returns `document_repair_no_progress`; an author reporting no productive safe correction returns `document_repair_unresolved`. Both preserve the original candidate for #107's usability/trust assessment and complete review-only delivery. Source/base/integrity mutation remains unavailable. Repeated unchanged substantive actions carry reassessment feedback into the next AI pass; there is no universal repair-count limit. Every pass retains the original operation deadline and asks the author to reserve final verification/delivery time.

Default isolated production repair workers can write only declared native/script work areas and
private dispatch runtime state. Linux uses the same ordinary Bubblewrap boundary
as review workers, with a private network namespace and governed provider bridge;
Darwin uses its native sandbox profile. Installed integrity and source/base hashes
are also verified before adoption. Actual installed enforcement and capabilities
require bound installation probe evidence before admission; local controlled tests
alone do not establish Linux readiness. Installed code is never a repair surface.
Restricted Hermes TUI mode instead uses the host-managed boundary documented in
[runtime-and-release.md](runtime-and-release.md#restricted-hermes-tui-compatibility);
OS write/network denial is not claimed in that mode.

Run native Python tools with `-B`, including alongside `-I`. Managed worker and
parent environments suppress bytecode writes, and the PDFium worker uses `-B`.
Imports must leave the installed runtime inventory unchanged across inspection,
repair and rerendering. Do not delete or ignore unexpected runtime files during
generation; a contaminated installation requires a fresh verified replacement.


Focused public lifecycle tests use actual python-docx/ElementTree editing with controlled reviewers/renderers. They demonstrate native edits, dispute reassessment, newly introduced XML defects, reconstruction preservation, malformed edits, stale responses, source/base mutation and reviewer independence. These adapters establish control flow and byte preservation, not live AI quality or latency.
