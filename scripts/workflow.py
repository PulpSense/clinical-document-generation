"""The single public seam for the clinical document Run Lifecycle.

The implementation modules remain available to the workflow, but callers use
only these four operations.  ``clinical_document_workflow`` is retained as a
compatibility adapter for existing Hermes and n8n integrations during the
expand step tracked by issue #17.
"""

from __future__ import annotations

from clinical_document_workflow import (
    approve_source,
    generate_approved_run,
    prepare_run,
    validate_run,
)

prepare = prepare_run
approve = approve_source
validate = validate_run
generate = generate_approved_run

__all__ = ["prepare", "approve", "validate", "generate"]
