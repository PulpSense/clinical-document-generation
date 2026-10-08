# Explicit release workflow

Read only when the owner explicitly requests packaging, certification, signing, installation, activation or rollback. A study request, source edit, commit or push does not authorize these operations. Require explicit authorization for the selected release action; keep the active release immutable.

Resolve the compatible absolute Python runtime and preserve the Linux dependency contract in [Linux setup](linux-setup.md).

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --format-conformance --format-conformance-root <evidence-root>
"$CLINICAL_PYTHON" scripts/workflow.py --release-gate
"$CLINICAL_PYTHON" scripts/workflow.py --package-release /absolute/path/clinical-document-generation-release.zip
"$CLINICAL_PYTHON" scripts/workflow.py --bind-certification /absolute/path/release-certification-corpus.json --release-archive /absolute/path/clinical-document-generation-release.zip
"$CLINICAL_PYTHON" scripts/workflow.py --install-release /absolute/path/clinical-document-generation-release.zip --skills-dir /absolute/path/to/hermes/skills --hermes-config /absolute/path/to/hermes/config.yaml
"$CLINICAL_PYTHON" scripts/workflow.py --verify-installation
"$CLINICAL_PYTHON" scripts/workflow.py --rollback-release --skills-dir /absolute/path/to/hermes/skills
```

`--package-release` creates the immutable candidate from the current clean
commit. Provision the extracted certification candidate with
`--provision-candidate`, run the full real corpus, and set
`CLINICAL_DOCUMENT_CERTIFICATION_PRIVATE_KEY` to the authorized external RSA
private-key JSON before embedding its passing report with `--bind-certification`.
The private key must never be copied into the repository, archive, evidence
bundle, logs, or installation. Only that one certified archive may be activated
with `--install-release`; direct extraction is not a
supported update path. Installation verifies host Word or LibreOffice, installs
the one manifest-bound `pypdfium2` wheel offline, verifies every extracted file
against the immutable wheel-derived inventory, and runs page rendering in a
killable worker with governed time, page, pixel, dimension, output, and process
resource limits. Before staging or archive access, installation requires the
current resolved Python 3.10+ interpreter and records its implementation,
version, resolved executable path, and executable SHA-256 in installation
assurance. It runs an end-to-end render/page-image smoke, reruns manifest,
certification, and runtime-integrity verification immediately after each
provisioner/verifier hook and before invoking the next hook, rejecting a symbolic
link at the skill root or any manifest-owned path
component, and only then writes installation records. Before the first namespace
mutation, installation durably commits an inode-bound activation journal with an
atomic JSON replacement and parent-directory sync. The atomic candidate-to-active
rename is the activation commit point. Every ordinary failure before it restores
the exact prior active and previous releases and removes only transient history
created by that attempt; an interrupted process is reconciled from the journal
before any later staging. Inode identity distinguishes a committed candidate from
the prior active release even when their package fingerprints match. Failures
cleaning deterministic fingerprint-named displaced state or the transaction
journal after that commit point are reported as successful activation with
deferred-cleanup findings; they never become false installation failures. The
newly activated release remains selected. A failed smoke leaves the previous
verified release active. One rollback operation completely revalidates the
immutable previous release's manifest, certification/evidence, and PDFium runtime,
copies it to an isolated system-temporary directory outside the live release
namespace, completely verifies that copy, runs executable
integration smoke only against the copy, and completely revalidates the copy after
smoke. The retained previous release is also completely revalidated after the
callback and immediately before the swap. Rollback then
commits an atomic previous-to-active swap. A durable inode-bound rollback journal restores a failed
pre-commit swap on retry or recognizes an already committed rollback. The suspect
release is quarantined under its fingerprint without rewriting retained run
revisions. The archive contains
`RELEASE-MANIFEST.json` and the bound `RELEASE-CERTIFICATION.json`. Installation
also requires Hermes `skills.external_dirs` to name only the promoted active
path, validates recorded model provenance plus the certified reasoning/safe-mode/turn settings declared
under `skills.clinical_document_generation`, and records the activation in
`PROMOTION-RECORD.json`.

The bound certification report contains a deterministic
`release-certification-evidence/v1` bundle. Its canonical inventory retains the
exact release manifest, preflight report and logs, deterministic/layout evidence,
Python/renderer/production-module/configuration identities, synthetic fixture sources
and approvals, all three raw case/state/manifest records, output bytes, drafting
and verification exchanges, parent-process completion records, PDFs, and every
reviewed page image. The complete canonical report is signed with the external
private key; binding and installation verify that detached signature against
`references/release-certification-public-key.json`, whose exact bytes are bound
by the immutable release manifest. Signer and verifier derive its key identity
through one shared canonical hash of algorithm, exponent, and modulus. They then
independently decode and rehash every item, cross-check all semantic links, and
reject unsigned, missing, substituted,
ambiguous, stale, or unrelated evidence. The bundle is limited to 512 files,
32 MiB per file, and 128 MiB total. It rejects symlinks and path aliases and
must not retain credentials, private session logs, editable-checkout debris, or
client/patient data; fixture provenance must explicitly be synthetic and
non-private.

Before either binding or installation extracts an archive, the archive is limited
to 1,024 members, 64 MiB per ordinary member, 195,734,187 bytes for the encoded
certification report, 329,951,915 uncompressed bytes in total, and a 100:1 maximum
compression ratio. Any excess fails before extraction.

The manifest
hashes every packaged file and records implementation, template, contract,
font, renderer, harness, and model provenance. It excludes development
environments, credentials, source/patient data, old runs, and tests.

Run certification in the fixed order Retrospective, Ambispective–Sterling,
Prospective–Advarra. The existing certification runtime gate accepts otherwise
passing cases through the unchanged 45-minute correctness ceiling. Runtime
above 15 minutes and above the 18-minute diagnostic window is recorded for
optimization; it does not independently invalidate correct fully reviewed
output. Preserve every other certification gate and exact-byte confirmation.

The release gate never fabricates verifier approval. If it returns
`awaiting_hermes`, run the returned content and every-page visual verification
requests, save their exact responses, then resume the same corpus with:

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --release-gate --release-gate-root <evidence_root>
```

Before live certification, `--format-conformance` runs the immutable matrix in
`references/format-conformance-matrix.json`. It covers Retrospective Protocol,
Prospective–Advarra, Prospective–Sterling, Ambispective–Advarra, and
Ambispective–Sterling using exact hash-addressed fixtures, templates, and client
authorities. It also compares every generated DOCX with an approved normalized
OOXML baseline under `references/format-baselines/`, covering section geometry,
styles, numbering, headers/footers, fields/TOC, page furniture, table geometry,
signature/legal placement, paragraph rhythm, and relational pagination controls
without relying on whole-DOCX equality. Every governed heading is bound to its
actual first substantive paragraph, table, or child heading on the same rendered
page; missing successors and unrelated page text fail. Its `structural_passed` result is
deterministic structural evidence only: it cannot substitute for clinical
verification, genuine every-page image inspection, production certification, or
exact-byte Desktop confirmation.

Release Certification calls `run_production_desktop_operation` from an
extracted, hash-verified candidate release built from the exact commit recorded
in its manifest and binds its fingerprint. The corpus controller may prepare
fixtures and reduce evidence but must not inject a test-only worker launcher. It must not
import or launch the editable checkout, and it does not replace the operation's
45-minute deadline with a harness timeout. The certification adapter must wire
visual fallback to a Desktop-parent review callback; it must never redispatch
that fallback through the worker launcher. Certification records its existing runtime classification separately from clinical correctness; the 15-minute diagnostic target does not replace the 45-minute correctness ceiling.


Code completion, packaging, host verification, installation and activation are separate statuses. Report only the states actually evidenced. Controlled responders and captured replays are not fresh clinical approval or live certification.
