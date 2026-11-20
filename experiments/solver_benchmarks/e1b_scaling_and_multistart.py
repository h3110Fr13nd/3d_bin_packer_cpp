"""E1b - where does CP-SAT stop helping, and can a cheap engine multi-start close the gap?

(a) CP-SAT warm-started from the engine (10 s) on larger instances: model size,
    memory, and whether it still improves the engine's solution.
(b) Engine multi-start: pack the same boxes in K random orders (Packer.pack_to_bin
    keeps the given order) and keep the best - compared with CP-SAT's result.
"""
from __future__ import annotations

import random
import resource
import sys

from common import bp, engine_pack, random_boxes, save, timer
from e1_exact_3d import CONTAINER, solve_cpsat

V = CONTAINER[0] * CONTAINER[1] * CONTAINER[2]


def multistart(boxes, container, restarts, seed=0):
    """Best packed volume over random item orders (no support, like the CP-SAT model).
    Packer.pack_to_bin keeps the given order, unlike pack()."""
    rnd = random.Random(seed)
    best = 0
    order = list(range(len(boxes)))
    packer = bp.Packer(min_support_ratio=0.0, optimize=False, loading_access=bp.LoadingAccess.NONE)
    for r in range(restarts):
        if r:
            rnd.shuffle(order)
        items = [bp.Item(str(i), *boxes[i]) for i in order]
        b = bp.Bin("c", *container)
        packer.pack_to_bin(b, items)
        best = max(best, b.get_packed_volume())
    return best


def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


if __name__ == "__main__":
    part = sys.argv[1] if len(sys.argv) > 1 else "both"
    rows = []
    if part in ("a", "both"):
        for n in (20, 40, 80, 160):
            boxes = random_boxes(n, CONTAINER, fill=1.2, seed=0)
            ev, _, et, items = engine_pack(boxes, CONTAINER, support=0.0)
            hint = {int(it.name): (tuple(it.get_position()), tuple(it.get_dimension())) for it in items}
            before = rss_mb()
            with timer() as t:
                v, opt, st, bound = solve_cpsat(boxes, CONTAINER, hint=hint)
            row = {"part": "a", "n": n, "engine_util": round(ev / V, 3), "cpsat_hint_util": round(v / V, 3),
                   "cpsat_s": round(st, 1), "total_s_incl_model": round(t["s"], 1), "pairs": n * (n - 1) // 2,
                   "rss_mb": round(rss_mb(), 0), "rss_growth_mb": round(rss_mb() - before, 0)}
            print(row, flush=True)
            rows.append(row)
            if t["s"] > 30 or rss_mb() > 4000:
                print("model too slow / too big: stopping", flush=True)
                break
    if part in ("b", "both"):
        for n in (6, 8, 10, 12, 15):
            for seed in (0, 1, 2):
                boxes = random_boxes(n, CONTAINER, fill=1.2, seed=seed)
                ev, _, _, _ = engine_pack(boxes, CONTAINER, support=0.0)
                cv, opt, cs, _ = solve_cpsat(boxes, CONTAINER)
                row = {"part": "b", "n": n, "seed": seed, "engine": round(ev / V, 3), "cpsat": round(cv / V, 3),
                       "cpsat_optimal": opt, "cpsat_s": round(cs, 2)}
                for k in (100, 1000):
                    with timer() as t:
                        row[f"multistart_{k}"] = round(multistart(boxes, CONTAINER, k) / V, 3)
                    row[f"multistart_{k}_s"] = round(t["s"], 2)
                print(row, flush=True)
                rows.append(row)
    save(f"e1b_{part}.json", rows)
