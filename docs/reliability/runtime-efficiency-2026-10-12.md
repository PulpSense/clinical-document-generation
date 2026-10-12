# Runtime efficiency (#110)

Baseline: e524b3f6aa372feeca5c96225d508c6919c65abe. Scope: runtime improvements approved in the conversation and GitHub issue #110, across all three branches and five branch/template families.

The observed 40m11s run spent 8m49s drafting (including three citation-contract retries), 11m11s in first reviews, 3m19s repairing XML and 16m45s in final review/fallback. These observations motivate the changes; they are not a prediction of the new runtime.

## Changes

- Declared object evidence and existing approved child paths are consistently citable. Draft requests include source families actually required by their sections, even when a legacy batch omitted one. Request authentication reconstructs the same scope from the immutable approval. Unrelated or invented evidence paths remain invalid.
- Parent visual fallback starts while content review continues instead of waiting for the content future. Content waves have a 12-minute budget; each parent callback is capped by the visual stage budget (normally four minutes) and remaining operation time. The original 45-minute deadline is unchanged.
- After native repair, package-wide content/cross-document review is always fresh. An original independently passing visual response is retained only with identical native/PDF/page bytes, current renderer identities, approved source, generation authority and checks; new applicable visual concerns or repair-author identity conflicts invalidate reuse. Original request/response/reviewer/review-set identities are preserved. Final exact-artifact validation permits these older visual identities only with the required source/authority bindings.
- Rendering reuses complete hash-verified evidence under currently available office/page renderer identities and unchanged font evidence/substitutions. Changed or incomplete evidence is rerendered. Installation, runtime, structural and exact-byte delivery checks remain active.
- Worker instructions permit correcting tool arguments, equivalent supported tools, pagination and independent inspection batches within existing task access boundaries. They confer no authority to edit installed skill/runtime code or waive review.

## Validation

Focused tests only. New public-boundary tests cover object/leaf citations in all branches, legacy missing-family routing, unauthorized citations, concurrent fallback, actual native repair/review cycles in all five families, source/renderer/response/page/concern/author invalidations, and rendering cache invalidations. Controlled author/reviewer/renderer adapters are test doubles, not live quality or speed evidence.

No full suite, acceptance corpus, paid certification or live Hermes campaign is authorized by this change. Linux runtime dependencies remain unchanged. Hermes installation must run staged and active DOCX-to-PDF-to-page-image smokes before declaring activation complete; its report should distinguish newly performed reviews from retained exact-byte visual assessments.
