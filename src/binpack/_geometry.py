"""Vectorised geometry helpers shared by the report, validation and rendering code."""
from __future__ import annotations

import numpy as np


def boxes_array(items) -> tuple[np.ndarray, np.ndarray]:
    """(lo, hi) arrays of shape (n, 3): back-bottom-left and front-top-right corners."""
    items = list(items)
    if not items:
        empty = np.zeros((0, 3), dtype=np.int64)
        return empty, empty.copy()
    lo = np.array([tuple(it.get_position()) for it in items])
    dims = np.array([tuple(it.get_dimension()) for it in items])
    # Packer results are whole numbers; bulk loads (binpack.bulk) place shapes at fractions.
    dtype = np.int64 if np.issubdtype(lo.dtype, np.integer) and np.issubdtype(dims.dtype, np.integer) else float
    lo = lo.astype(dtype)
    return lo, lo + dims.astype(dtype)


def interval_overlap(a0, a1, b0, b1) -> np.ndarray:
    """Length of the overlap of [a0, a1) and [b0, b1) (broadcasting), 0 if disjoint."""
    return np.maximum(0, np.minimum(a1, b1) - np.maximum(a0, b0))


def row_blocks(n: int, block: int = 1024):
    """Row ranges for chunked all-pairs computations (bounded memory)."""
    for start in range(0, n, block):
        yield start, min(n, start + block)
