"""Test-facing alias for the smoke fixtures shipped with the skill.

The fixtures live in `scripts/` because the packaging smoke command runs them,
and tests must exercise exactly what ships.
"""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from smoke_fixtures import (  # noqa: E402,F401
    BRANCH_TEMPLATES,
    BUNDLED_DOCX,
    BUNDLED_PRS,
    approved_reference,
    build_run,
    generated_modules,
    write_reference,
)
