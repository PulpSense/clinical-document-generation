"""The single public seam for the clinical document Run Lifecycle.

The implementation modules remain available to the workflow, but callers use
only these four operations.  ``clinical_document_workflow`` is retained as a
compatibility adapter for existing Hermes and n8n integrations during the
expand step tracked by issue #17.
"""

from clinical_document_workflow import (
    approve_source as _approve_source,
    generate_approved_run as _generate_approved_run,
    prepare_run as _prepare_run,
    validate_run as _validate_run,
)

prepare = _prepare_run
approve = _approve_source
validate = _validate_run
generate = _generate_approved_run

__all__ = ["prepare", "approve", "validate", "generate"]
