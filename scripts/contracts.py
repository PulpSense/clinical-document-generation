"""Contract seam for branch and document-generation validation.

This module gives the replacement architecture a stable home for contracts
while the existing contract implementation remains available as a proven
compatibility implementation.
"""

from __future__ import annotations

from typing import Any

from clinical_document_workflow import branch_contract as get_branch_contract
from retrospective import RETROSPECTIVE_SECTIONS, retrospective_contract
from quality_contract import validate_source_contract

branch_contract = get_branch_contract

__all__ = ["branch_contract", "validate_source_contract", "RETROSPECTIVE_SECTIONS", "retrospective_contract"]
