"""E2 - fleet selection: heuristic fleet planner vs. LP/IP with engine-generated patterns.

(a) Integer lower bound: cheapest container mix whose total volume AND weight
    cover the cargo (tiny IP, CP-SAT). Tighter than the fractional bound.
(b) Column generation: master LP over patterns (feasible container loads,
    counted per SKU), the engine prices new patterns (objective VALUE with the
    LP duals as item values), a final IP (CP-SAT) picks the patterns. The
    chosen containers are then really packed with the engine; anything that
    does not fit is handed to the fleet planner (extra cost is reported).
"""
from __future__ import annotations

import math
import random
import sys
from collections import Counter

from common import bp, save, timer


TYPES = [("40ft HC", (2350, 2690, 12030), 26500, 3000), ("20ft", (2350, 2390, 5900), 21700, 1800),
         ("Truck 7.2m", (2450, 2600, 7200), 12000, 1400), ("Tempo", (1700, 1700, 3000), 1500, 350)]


def instance(n, seed):
    """n items drawn from 10 SKUs (8 cartons, 2 pallet kinds): SKU list + demand."""
    r = random.Random(seed)
    skus = [(r.randint(300, 800), r.randint(200, 600), r.randint(300, 800), round(r.uniform(5, 40), 1), False)
            for _ in range(8)]
    skus += [(1200, r.choice([800, 1000, 1400]), 800, round(r.uniform(150, 600), 1), True),
             (1200, r.choice([900, 1200]), 1000, round(r.uniform(200, 800), 1), True)]
    demand = Counter(r.randrange(len(skus)) for _ in range(n))
    return skus, [demand.get(s, 0) for s in range(len(skus))]


def items_for(skus, demand, values=None):
    out = []
    for s, (w, h, d, kg, up) in enumerate(skus):
        for k in range(demand[s]):
            out.append(bp.Item(f"{s}:{k}", w, h, d, weight=kg, upright=up,
                               value=(values[s] if values else 0.0)))
    return out


def baseline(skus, demand, avail, optimize=True):
    p = bp.Packer(optimize=optimize)
    for name, dims, mw, cost in TYPES:
        p.add_bin_type(bp.Bin(name, *dims, max_weight=mw, cost=cost), avail.get(name))
    for it in items_for(skus, demand):
        p.add_item(it)
    with timer() as t:
        p.pack()
    return p.get_total_cost(), len(p.get_unfit_items()), t["s"]


def integer_lower_bound(skus, demand, avail):
    from ortools.linear_solver import pywraplp
    from ortools.sat.python import cp_model
    volume = sum(w * h * d * q for (w, h, d, _, _), q in zip(skus, demand))
    weight = sum(kg * q for (_, _, _, kg, _), q in zip(skus, demand))
    m = cp_model.CpModel()
    y = []
    for name, (W, H, D), mw, cost in TYPES:
        ub = avail.get(name)
        y.append(m.NewIntVar(0, ub if ub is not None else 1000, name))
    scale = 10**6  # volumes in dm3 to keep coefficients small
    m.Add(sum(v * (W * H * D // scale) for v, (_, (W, H, D), _, _) in zip(y, TYPES)) >= math.ceil(volume / scale))
    m.Add(sum(v * int(mw) for v, (_, _, mw, _) in zip(y, TYPES)) >= math.ceil(weight))
    m.Minimize(sum(v * c for v, (_, _, _, c) in zip(y, TYPES)))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = 5
    s.Solve(m)
    return s.ObjectiveValue()


def price_pattern(t, skus, demand, duals):
    """Engine as pricing oracle: one container of type t maximising sum of duals."""
    name, dims, mw, cost = TYPES[t]
    p = bp.Packer(objective=bp.Objective.VALUE, optimize=False)
    p.add_bin(bp.Bin(name, *dims, max_weight=mw))
    for it in items_for(skus, demand, [max(d, 0.0) + 1e-6 for d in duals]):
        p.add_item(it)
    p.pack()
    counts = [0] * len(skus)
    for it in p.get_bins()[0].get_items():
        counts[int(it.name.split(":")[0])] += 1
    return tuple(counts)


def solve_master(patterns, skus, demand, avail, integer, time_limit=10):
    from ortools.linear_solver import pywraplp
    from ortools.sat.python import cp_model
    if integer:
        m = cp_model.CpModel()
        z = [m.NewIntVar(0, 200, "") for _ in patterns]
        for s in range(len(skus)):
            m.Add(sum(a[s] * v for (_, a), v in zip(patterns, z)) >= demand[s])
        for t, (name, _, _, _) in enumerate(TYPES):
            if avail.get(name) is not None:
                m.Add(sum(v for (tt, _), v in zip(patterns, z) if tt == t) <= avail[name])
        m.Minimize(sum(TYPES[t][3] * v for (t, _), v in zip(patterns, z)))
        s = cp_model.CpSolver()
        s.parameters.max_time_in_seconds = time_limit
        s.parameters.num_workers = 4
        st = s.Solve(m)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None, None, None
        return s.ObjectiveValue(), [s.Value(v) for v in z], st == cp_model.OPTIMAL
    lp = pywraplp.Solver.CreateSolver("GLOP")
    z = [lp.NumVar(0, lp.infinity(), "") for _ in patterns]
    cover = [lp.Add(sum(a[s] * v for (_, a), v in zip(patterns, z)) >= demand[s]) for s in range(len(skus))]
    cap = {}
    for t, (name, _, _, _) in enumerate(TYPES):
        if avail.get(name) is not None:
            cap[t] = lp.Add(sum(v for (tt, _), v in zip(patterns, z) if tt == t) <= avail[name])
    lp.Minimize(sum(TYPES[t][3] * v for (t, _), v in zip(patterns, z)))
    if lp.Solve() != lp.OPTIMAL:
        return None, None, None
    return lp.Objective().Value(), [c.dual_value() for c in cover], {t: c.dual_value() for t, c in cap.items()}


def column_generation(skus, demand, avail, max_iters=15):
    patterns = set()
    # Seed: per type, the engine's own load of all demand, and single-SKU loads.
    for t in range(len(TYPES)):
        patterns.add((t, price_pattern(t, skus, demand, [1.0] * len(skus))))
        for s in range(len(skus)):
            if demand[s]:
                only = [demand[k] if k == s else 0 for k in range(len(skus))]
                patterns.add((t, price_pattern(t, skus, only, [1.0] * len(skus))))
    patterns = [p for p in patterns if any(p[1])]
    lp_value = None
    for it in range(max_iters):
        lp_value, duals, cap_duals = solve_master(patterns, skus, demand, avail, integer=False)
        if lp_value is None:
            break
        added = 0
        for t in range(len(TYPES)):
            a = price_pattern(t, skus, demand, duals)
            reduced = TYPES[t][3] - sum(x * d for x, d in zip(a, duals)) - cap_duals.get(t, 0.0)
            if reduced < -1e-6 and (t, a) not in patterns:
                patterns.append((t, a))
                added += 1
        if not added:
            break
    ip_value, z, optimal = solve_master(patterns, skus, demand, avail, integer=True)
    return patterns, lp_value, ip_value, z, optimal, it + 1


def realise(skus, demand, patterns, z, avail):
    """Packs the real items into the chosen containers; leftovers go to the fleet planner."""
    remaining = list(demand)
    cost = 0.0
    used = Counter()
    for (t, a), count in zip(patterns, z):
        for _ in range(count):
            take = [min(x, r) for x, r in zip(a, remaining)]
            if not any(take):
                continue
            name, dims, mw, c = TYPES[t]
            p = bp.Packer(optimize=True)
            p.add_bin(bp.Bin(name, *dims, max_weight=mw))
            for item in items_for(skus, take):
                p.add_item(item)
            p.pack()
            for item in p.get_bins()[0].get_items():
                remaining[int(item.name.split(":")[0])] -= 1
            cost += c
            used[name] += 1
    leftover = sum(remaining)
    extra = 0.0
    if leftover:
        left_avail = {k: (None if v is None else max(0, v - used[k])) for k, v in avail.items()}
        for name, *_ in TYPES:
            left_avail.setdefault(name, None)
        extra, unfit, _ = baseline(skus, remaining, left_avail)
    return cost + extra, leftover


def main():
    rows = []
    cases = [(n, seed, avail) for n in (150, 600, 2000) for seed in (0, 1)
             for avail in ({}, {"40ft HC": 1, "Truck 7.2m": 3})]
    for n, seed, avail in cases:
        skus, demand = instance(n, seed)
        row = {"n": n, "seed": seed, "limited": bool(avail)}
        row["heuristic_cost"], row["heuristic_unfit"], row["heuristic_s"] = baseline(skus, demand, avail)
        row["quick_cost"], _, row["quick_s"] = baseline(skus, demand, avail, optimize=False)
        with timer() as t:
            row["int_lower_bound"] = integer_lower_bound(skus, demand, avail)
        row["lb_s"] = round(t["s"], 3)
        with timer() as t:
            patterns, lp_value, ip_value, z, optimal, iters = column_generation(skus, demand, avail)
        row.update(cg_patterns=len(patterns), cg_iters=iters, cg_lp=lp_value, cg_ip=ip_value, cg_ip_optimal=optimal,
                   cg_s=round(t["s"], 2))
        if z is not None:
            with timer() as t:
                row["cg_realised_cost"], row["cg_leftover_items"] = realise(skus, demand, patterns, z, avail)
            row["realise_s"] = round(t["s"], 2)
        row["heuristic_s"] = round(row["heuristic_s"], 2)
        row["quick_s"] = round(row["quick_s"], 2)
        print(row, flush=True)
        rows.append(row)
        if row["cg_s"] > 120:
            print("column generation too slow: stopping", flush=True)
            break
    save("e2_fleet.json", rows)


if __name__ == "__main__":
    main()
