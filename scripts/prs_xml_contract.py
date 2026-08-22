"""Structural contract checks for the client-approved PRS XML shape.

Values are intentionally ignored here.  The mapper and technical validator
own values and semantic rules; this module owns element names, optional-node
presence, ordering, and repeated-block taxonomy.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


REPEATED_BLOCKS = {
    "intervention",
    "arm_group",
    "primary_outcome",
    "secondary_outcome",
    "other_outcome",
    "location",
}
OPTIONAL_ALTERNATIVES = {"interventional_design", "observational_design"}


def _study(root: ET.Element) -> ET.Element:
    if root.tag == "clinical_study":
        return root
    for element in root.iter("clinical_study"):
        return element
    raise ValueError("missing <clinical_study>")


def _ordered_children(element: ET.Element) -> list[str]:
    """Return order while treating repeated blocks as one contract slot."""
    result: list[str] = []
    seen: set[str] = set()
    for child in list(element):
        if child.tag in REPEATED_BLOCKS:
            if child.tag in seen:
                continue
            seen.add(child.tag)
        result.append(child.tag)
    return result


def _shape(element: ET.Element) -> dict[str, Any]:
    children = list(element)
    representative: dict[str, ET.Element] = {}
    for child in children:
        representative.setdefault(child.tag, child)
    return {
        "tag": element.tag,
        "children": _ordered_children(element),
        "child_shapes": {
            tag: _shape(child)
            for tag, child in representative.items()
            if tag not in REPEATED_BLOCKS
        },
        "repeated_shapes": {
            tag: _shape(child)
            for tag, child in representative.items()
            if tag in REPEATED_BLOCKS
        },
    }


def structural_signature(path: Path) -> dict[str, Any]:
    """Build a value-free, repeat-count-independent signature for an XML file."""
    root = ET.parse(path).getroot()
    return _shape(_study(root)) | {"root": root.tag}


def _compare_shape(expected: dict[str, Any], actual: dict[str, Any], path: str, findings: list[str]) -> None:
    if expected["tag"] != actual["tag"]:
        findings.append(f"{path}: expected <{expected['tag']}>, got <{actual['tag']}>")
        return
    expected_children = [
        tag
        for tag in expected["children"]
        if tag in actual["children"]
        or (tag not in REPEATED_BLOCKS and tag not in OPTIONAL_ALTERNATIVES)
    ]
    if expected_children != actual["children"]:
        findings.append(f"{path}: direct-child order or optional-node presence differs")
    for key, expected_child in expected["child_shapes"].items():
        actual_child = actual["child_shapes"].get(key)
        if actual_child is None and key in OPTIONAL_ALTERNATIVES:
            continue
        if actual_child is None:
            findings.append(f"{path}: missing <{key}>")
            continue
        _compare_shape(expected_child, actual_child, f"{path}/{key}", findings)
    for key, expected_child in expected["repeated_shapes"].items():
        actual_child = actual["repeated_shapes"].get(key)
        if actual_child is None:
            # Repeated blocks are optional by study design; their exact count
            # is checked separately from approved source data.
            continue
        _compare_shape(expected_child, actual_child, f"{path}/{key}[*]", findings)


def compare_structure(reference_path: Path, candidate_path: Path) -> list[str]:
    """Return structural differences; an empty list means the contract passes."""
    try:
        expected_root = ET.parse(reference_path).getroot()
        actual_root = ET.parse(candidate_path).getroot()
        expected = structural_signature(reference_path)
        actual = structural_signature(candidate_path)
    except (ET.ParseError, OSError, ValueError) as exc:
        return [f"PRS XML structural parse error: {exc}"]
    findings: list[str] = []
    if expected_root.tag != actual_root.tag:
        findings.append(f"root tag differs: expected {expected_root.tag}, got {actual_root.tag}")
    _compare_shape(expected, actual, "clinical_study", findings)
    return findings


def repeated_counts(path: Path) -> dict[str, int]:
    study = _study(ET.parse(path).getroot())
    return {tag: len([child for child in list(study) if child.tag == tag]) for tag in sorted(REPEATED_BLOCKS)}


__all__ = ["compare_structure", "repeated_counts", "structural_signature"]
