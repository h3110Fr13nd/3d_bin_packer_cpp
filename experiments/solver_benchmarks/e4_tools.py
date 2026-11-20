"""E4 - does the choice of free solver matter for the small IPs of E2/E3?

The E3 consignment knapsack and the E2 integer lower bound, solved with CP-SAT,
OR-Tools SCIP / CBC (pywraplp) and PuLP + HiGHS. Reports objective and time
(including model building).
"""
from __future__ import annotations

# OR-Tools and PuLP's HiGHS (highspy) cannot be loaded in the same process:
# whichever comes second fails with an undefined HiGHS symbol. Each tool is
# therefore benchmarked in its own process: `python e4_tools.py ortools|pulp`.
import sys

from common import save, timer
from e2_fleet import TYPES, instance
from e3_selection import BIN, consignments


def knapsack_data(seed):
    groups = {}
    for it in consignments(seed):
        g = groups.setdefault(it.group, [0.0, 0, 0.0])
        g[0] += it.value
        g[1] += it.get_volume() // 10**6   # dm3
        g[2] += it.weight
    V = BIN[1][0] * BIN[1][1] * BIN[1][2] // 10**6
    return list(groups.values()), V, BIN[2]


def knap_cpsat(data, V, W):
    from ortools.sat.python import cp_model
    m = cp_model.CpModel()
    x = [m.NewBoolVar("") for _ in data]
    m.Add(sum(int(v) * b for (_, v, _), b in zip(data, x)) <= V)
    m.Add(sum(int(w * 10) * b for (_, _, w), b in zip(data, x)) <= int(W * 10))
    m.Maximize(sum(int(val * 100) * b for (val, _, _), b in zip(data, x)))
    s = cp_model.CpSolver()
    s.parameters.num_workers = 4
    s.Solve(m)
    return s.ObjectiveValue() / 100


def knap_pywraplp(data, V, W, backend):
    from ortools.linear_solver import pywraplp
    s = pywraplp.Solver.CreateSolver(backend)
    x = [s.BoolVar("") for _ in data]
    s.Add(sum(v * b for (_, v, _), b in zip(data, x)) <= V)
    s.Add(sum(w * b for (_, _, w), b in zip(data, x)) <= W)
    s.Maximize(sum(val * b for (val, _, _), b in zip(data, x)))
    s.Solve()
    return s.Objective().Value()


def knap_pulp(data, V, W):
    import pulp
    m = pulp.LpProblem("k", pulp.LpMaximize)
    x = [m.add_variable(f"x{i}", cat="Binary") for i in range(len(data))]  # PuLP >= 4 API
    m += pulp.lpSum(val * b for (val, _, _), b in zip(data, x))
    m += pulp.lpSum(v * b for (_, v, _), b in zip(data, x)) <= V
    m += pulp.lpSum(w * b for (_, _, w), b in zip(data, x)) <= W
    m.solve(pulp.HiGHS(msg=False))
    return pulp.value(m.objective)


def lb_data(seed, n=2000):
    skus, demand = instance(n, seed)
    volume = sum(w * h * d * q for (w, h, d, _, _), q in zip(skus, demand)) / 10**6
    weight = sum(kg * q for (_, _, _, kg, _), q in zip(skus, demand))
    return volume, weight


def lb_pywraplp(volume, weight, backend):
    from ortools.linear_solver import pywraplp
    s = pywraplp.Solver.CreateSolver(backend)
    y = [s.IntVar(0, 1000, "") for _ in TYPES]
    s.Add(sum(v * (W * H * D / 10**6) for v, (_, (W, H, D), _, _) in zip(y, TYPES)) >= volume)
    s.Add(sum(v * mw for v, (_, _, mw, _) in zip(y, TYPES)) >= weight)
    s.Minimize(sum(v * c for v, (_, _, _, c) in zip(y, TYPES)))
    s.Solve()
    return s.Objective().Value()


def lb_pulp(volume, weight):
    import pulp
    m = pulp.LpProblem("lb", pulp.LpMinimize)
    y = [m.add_variable(f"y{i}", 0, 1000, cat="Integer") for i in range(len(TYPES))]
    m += pulp.lpSum(v * c for v, (_, _, _, c) in zip(y, TYPES))
    m += pulp.lpSum(v * (W * H * D / 10**6) for v, (_, (W, H, D), _, _) in zip(y, TYPES)) >= volume
    m += pulp.lpSum(v * mw for v, (_, _, mw, _) in zip(y, TYPES)) >= weight
    m.solve(pulp.HiGHS(msg=False))
    return pulp.value(m.objective)


def main(tool):
    rows = []
    for seed in range(3):
        data, V, W = knapsack_data(seed)
        knap = ([("cpsat", lambda: knap_cpsat(data, V, W)), ("scip", lambda: knap_pywraplp(data, V, W, "SCIP")),
                 ("cbc", lambda: knap_pywraplp(data, V, W, "CBC"))] if tool == "ortools"
                else [("pulp_highs", lambda: knap_pulp(data, V, W))])
        for name, fn in knap:
            with timer() as t:
                value = fn()
            rows.append({"problem": "knapsack", "seed": seed, "solver": name, "value": round(value, 1), "ms": round(t["s"] * 1000, 1)})
        volume, weight = lb_data(seed)
        lbs = ([("scip", lambda: lb_pywraplp(volume, weight, "SCIP")), ("cbc", lambda: lb_pywraplp(volume, weight, "CBC"))]
               if tool == "ortools" else [("pulp_highs", lambda: lb_pulp(volume, weight))])
        for name, fn in lbs:
            with timer() as t:
                value = fn()
            rows.append({"problem": "fleet_lb", "seed": seed, "solver": name, "value": round(value, 1), "ms": round(t["s"] * 1000, 1)})
    for r in rows:
        print(r)
    save(f"e4_tools_{tool}.json", rows)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ortools")
