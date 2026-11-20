"""Shared helpers for the solver benchmarks (not part of the library).

Imports the engine from ../../src, so build it first:
    python setup.py build_ext --inplace        (from the repository root)
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))

import binpack as bp  # noqa: E402

RESULTS = os.path.join(HERE, "results")


@contextmanager
def timer():
    box = {}
    start = time.perf_counter()
    yield box
    box["s"] = time.perf_counter() - start


def save(name: str, data) -> None:
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, name), "w") as fh:
        json.dump(data, fh, indent=1, default=str)


def random_boxes(n: int, container=(100, 100, 100), fill=1.2, seed=0):
    """n random boxes whose total volume is about `fill` x the container volume."""
    rnd = random.Random(seed)
    W, H, D = container
    side = (fill * W * H * D / n) ** (1 / 3)
    boxes = []
    for _ in range(n):
        dims = [max(1, min(c, round(side * rnd.uniform(0.6, 1.4)))) for c in (W, H, D)]
        boxes.append(tuple(dims))
    return boxes


def engine_pack(boxes, container, support=0.0, optimize=True, values=None, weights=None, max_weight=0.0,
                objective=None):
    """Packs with the library engine; returns (packed volume, packed indices, seconds)."""
    p = bp.Packer(min_support_ratio=support, optimize=optimize, loading_access=bp.LoadingAccess.NONE,
                  objective=objective or bp.Objective.VOLUME)
    p.add_bin(bp.Bin("c", *container, max_weight=max_weight))
    for i, (w, h, d) in enumerate(boxes):
        p.add_item(bp.Item(str(i), w, h, d, value=(values[i] if values else 0.0),
                           weight=(weights[i] if weights else 0.0)))
    with timer() as t:
        p.pack()
    items = p.get_bins()[0].get_items()
    packed = sorted(int(it.name) for it in items)
    return sum(it.get_volume() for it in items), packed, t["s"], items
