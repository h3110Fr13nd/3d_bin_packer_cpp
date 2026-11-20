"""E3 - which consignments to ship (VALUE objective, weight limit, all-or-nothing groups).

Heuristic: the packer's own VALUE objective (select-then-pack strategies).
IP variant: CP-SAT selects consignments maximising value with volume <= alpha * V
and weight <= W, the engine then packs the selection; the best alpha wins.
The IP with alpha = 1 is also an upper bound (it ignores geometry).
"""
from __future__ import annotations

import random

from common import bp, save, timer


from binpack import pricing

BIN = ("40ft HC", (2350, 2690, 12030), 26500.0)


def consignments(seed, n=60):
    r = random.Random(seed)
    items = []
    for g in range(n):
        kind = r.choice(["dense", "normal", "light"])
        dims = (r.randint(300, 1200), r.randint(200, 1000), r.randint(300, 1200))
        kg_m3 = {"dense": r.uniform(600, 1400), "normal": r.uniform(150, 400), "light": r.uniform(30, 120)}[kind]
        vol = dims[0] * dims[1] * dims[2] / 1e9
        for k in range(r.randint(1, 20)):
            items.append(bp.Item(f"G{g}-{k}", *dims, weight=round(vol * kg_m3, 1), group=f"G{g}",
                                 upright=r.random() < 0.3))
    pricing.price_items(items, pricing.minimum(pricing.weight_or_measure(55.0), 80.0))
    rm = random.Random(seed * 7)
    mult = {}
    for it in items:  # customer-specific rates
        it.value *= mult.setdefault(it.group, rm.choice([0.5, 0.8, 1.0, 1.0, 1.5, 3.0]))
    return items


def pack(items, chosen=None):
    p = bp.Packer(objective=bp.Objective.VALUE)
    name, dims, mw = BIN
    p.add_bin(bp.Bin(name, *dims, max_weight=mw))
    for it in items:
        if chosen is None or it.group in chosen:
            p.add_item(it)
    with timer() as t:
        p.pack()
    return sum(i.value for i in p.get_bins()[0].get_items()), t["s"]


def select(items, alpha):
    from ortools.sat.python import cp_model
    groups = {}
    for it in items:
        g = groups.setdefault(it.group, [0.0, 0, 0.0])
        g[0] += it.value
        g[1] += it.get_volume()
        g[2] += it.weight
    names = list(groups)
    V = BIN[1][0] * BIN[1][1] * BIN[1][2]
    m = cp_model.CpModel()
    x = {g: m.NewBoolVar(g) for g in names}
    m.Add(sum(groups[g][1] // 10**6 * x[g] for g in names) <= int(alpha * V // 10**6))   # dm3
    m.Add(sum(int(groups[g][2] * 10) * x[g] for g in names) <= int(BIN[2] * 10))
    m.Maximize(sum(int(groups[g][0] * 100) * x[g] for g in names))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = 5
    s.parameters.num_workers = 4
    s.Solve(m)
    return {g for g in names if s.Value(x[g])}, s.ObjectiveValue() / 100


def main():
    rows = []
    for seed in range(6):
        items = consignments(seed)
        offered = sum(i.value for i in items)
        row = {"seed": seed, "offered": round(offered)}
        row["heuristic"], t = pack(items)
        row["heuristic_s"] = round(t, 2)
        best, total_s = 0.0, 0.0
        for alpha in (1.0, 0.95, 0.9, 0.85, 0.8):
            with timer() as ts:
                chosen, ip_value = select(items, alpha)
            value, t = pack(items, chosen)
            total_s += ts["s"] + t
            if alpha == 1.0:
                row["ip_upper_bound"] = round(ip_value)
            best = max(best, value)
        row["ip_then_pack"] = best
        row["ip_then_pack_s"] = round(total_s, 2)
        row["heuristic"] = round(row["heuristic"])
        row["ip_then_pack"] = round(row["ip_then_pack"])
        print(row, flush=True)
        rows.append(row)
    save("e3_selection.json", rows)


if __name__ == "__main__":
    main()
