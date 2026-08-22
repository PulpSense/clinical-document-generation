"""Dedicated seam for the preserved PRS XML structural contract."""

from __future__ import annotations

from build_prs_xml_fields import build_fields
from validate_prs_xml import validate
from prs_xml_contract import compare_structure, repeated_counts, structural_signature


def merge_narrative(reference: dict, narrative: dict[str, str]) -> dict:
    """Merge the PRS batch's two prose fields without granting XML authority."""
    from prospective import validate_prs_narrative

    values = validate_prs_narrative(narrative)
    generated = reference.setdefault("generated", {})
    if not isinstance(generated, dict):
        raise ValueError("reference.generated must be a mapping")
    xml_values = generated.setdefault("xml", {})
    if not isinstance(xml_values, dict):
        raise ValueError("reference.generated.xml must be a mapping")
    xml_values.update(values)
    return reference

__all__ = ["build_fields", "validate", "merge_narrative", "compare_structure", "repeated_counts", "structural_signature"]
