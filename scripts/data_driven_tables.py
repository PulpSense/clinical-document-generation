#!/usr/bin/env python3
"""The Structural Table contract.

A Structural Table is a table whose shape comes from the data rather than from
the template, because its column count is not known when the template is
written. It travels as a row-major cell matrix that declares its own shape.

Three places have to agree on that shape: the mapper that builds the matrix,
the renderer that inserts the table, and the Delivery Gate that refuses to ship
an empty one. They agree here, so the shape cannot drift between them.
"""

from __future__ import annotations

from typing import Any


#: Every key a matrix must carry to be recognised as one.
MATRIX_KEYS = ("cells", "totalColumns", "totalRows")


def read_matrix(value: Any) -> tuple[list[Any], int, int] | None:
    """Read a matrix's cells and shape, or None when the value is not one.

    An empty matrix is still a matrix. The renderer has to remove its
    placeholder rather than leave a mapping behind for a scalar pass to
    stringify into the document; whether empty is deliverable is a separate
    question, answered by the gates.

    A declared `totalRows` is honoured, so a matrix carrying more cells than it
    declares rows for renders the shape it asked for. A missing or non-positive
    `totalRows` is computed from the cell count instead.
    """
    if not isinstance(value, dict) or not all(key in value for key in MATRIX_KEYS):
        return None
    cells = value.get("cells")
    if not isinstance(cells, list):
        return None
    try:
        columns = max(int(value.get("totalColumns") or 0), 0)
        rows = max(int(value.get("totalRows") or 0), 0)
    except (TypeError, ValueError):
        return None
    if columns and not rows:
        rows = -(-len(cells) // columns)
    return list(cells), columns, rows


def matrix_is_empty(value: Any) -> bool:
    """True when a matrix would render as a table with nothing in it.

    A value that is not a matrix at all counts as empty: the section it was
    meant to fill is just as blank either way.
    """
    matrix = read_matrix(value)
    if matrix is None:
        return True
    cells, columns, rows = matrix
    if columns <= 0 or rows <= 0:
        return True
    return not any(str(cell).strip() for cell in cells[: columns * rows])


def build_matrix(cells: list[Any], columns: int) -> dict:
    """Build a matrix in the shape the reference contract defines."""
    columns = max(int(columns), 0)
    return {
        "cells": list(cells),
        "totalColumns": columns,
        "totalRows": -(-len(cells) // columns) if columns else 0,
    }
