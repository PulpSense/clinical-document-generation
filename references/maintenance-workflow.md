# Explicit maintenance

Read only when the owner explicitly requests development or technical diagnosis. Ordinary study generation retains evidence and reports the actual technical cause; it never self-patches.

- Normal generation is not software maintenance. During ordinary client generation, the installed skill and its templates, contracts, tests, and implementation remain read-only; only the run workspace and isolated runtime caches may be written. When the owner explicitly requests development maintenance, Hermes may edit the Git-managed development checkout and push committed changes directly to the authorized Git/GitHub branch. Do not build a ZIP merely because a development edit was committed or pushed. Repackage and re-certify only when the owner explicitly requests a distributable or installable release, or before the change is installed or activated; Hermes must never edit the active certified release in place.

Use the Git-managed development checkout. Its AGENTS.md, GLOSSARY.md, docs/agents/, ADRs and focused developer checks apply when present. These development files are excluded from the installable archive; a normal Git clone still contains tracked files. Do not direct installed clients to absent developer files.

The single production entrypoint remains scripts/workflow.py. For an explicitly authorized inner-lifecycle diagnosis only:

```bash
"$CLINICAL_PYTHON" scripts/workflow.py --run-dir <run-dir> --stage generate --manual-review
```

Read [Desktop review](desktop-review.md) before routing any returned handoffs. Passing inner generation is not confirmed Desktop delivery. Run only explicitly focused developer checks; a full suite or live certification corpus requires owner approval. Preserve the Linux dependencies, pinned runtimes, renderer and font plan. Follow [release workflow](release-workflow.md) only for a separately authorized release action.
