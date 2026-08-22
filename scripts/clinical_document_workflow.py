"""Compatibility adapter for the pre-v2 workflow module.

The replacement implementation lives in :mod:`workflow`.  This module stays
available while callers migrate, but it deliberately contains no lifecycle
logic of its own: legacy imports and command-line calls delegate to the same
four public operations as the replacement seam.
"""

from __future__ import annotations

from workflow import (
    STANDARD_REFERENCE,
    approve,
    approve_source,
    branch_contract,
    generate,
    generate_approved_run,
    main,
    prepare,
    prepare_run,
    validate,
    validate_run,
    validated_client_outputs,
)


__all__ = ["prepare", "approve", "validate", "generate"]


if __name__ == "__main__":
    raise SystemExit(main())
