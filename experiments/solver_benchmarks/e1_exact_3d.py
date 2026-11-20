"""E1 - exact 3D packing of one container: CP-SAT / MIP vs. the engine.

Question: can an exact solver place boxes better than the extreme-point
engine, and at what size does it stop being practical?

Model (no gravity/support, rotations allowed, maximise packed volume):
  per box  : packed flag, one of its distinct orientations, position x, y, z
  per pair : if both packed, one of the 6 relations left/right/below/above/behind/front
The engine is run with min_support_ratio=0 so both solve the same problem.

Scaling stops at the first size where every solver run hits the time limit.
"""
from __future__ import annotations

import itertools
import sys

from common import engine_pack, random_boxes, save, timer

from ortools.linear_solver import pywraplp
from ortools.sat.python import cp_model

CONTAINER = (100, 100, 100)
TIME_LIMIT = 10.0  # seconds per solve


def orientations(dims):
    return sorted(set(itertools.permutations(dims)))


def solve_cpsat(boxes, container, time_limit=TIME_LIMIT, hint=None, workers=4):
    W, H, D = container
    m = cp_model.CpModel()
    packed, pos, size = [], [], []
    for i, dims in enumerate(boxes):
        p = m.NewBoolVar(f"p{i}")
        ors = [o for o in orientations(dims) if o[0] <= W and o[1] <= H and o[2] <= D]
        o_vars = [m.NewBoolVar(f"o{i}_{k}") for k in range(len(ors))]
        m.Add(sum(o_vars) == p)
        s = [sum(o[a] * v for o, v in zip(ors, o_vars)) for a in range(3)]
        xyz = [m.NewIntVar(0, c, f"{'xyz'[a]}{i}") for a, c in enumerate(container)]
        for a, c in enumerate(container):
            m.Add(xyz[a] + s[a] <= c)
        packed.append(p)
        pos.append(xyz)
        size.append(s)
        if hint is not None:
            m.AddHint(p, i in hint)
            if i in hint:
                m.AddHint(xyz[0], hint[i][0][0]); m.AddHint(xyz[1], hint[i][0][1]); m.AddHint(xyz[2], hint[i][0][2])
                for o, v in zip(ors, o_vars):
                    m.AddHint(v, o == hint[i][1])
    for i, j in itertools.combinations(range(len(boxes)), 2):
        rel = []
        for a in range(3):
            before = m.NewBoolVar("")
            after = m.NewBoolVar("")
            m.Add(pos[i][a] + size[i][a] <= pos[j][a]).OnlyEnforceIf(before)
            m.Add(pos[j][a] + size[j][a] <= pos[i][a]).OnlyEnforceIf(after)
            rel += [before, after]
        m.AddBoolOr(rel + [packed[i].Not(), packed[j].Not()])
    # Symmetry: among identical boxes, pack the earlier ones first.
    for i, j in itertools.combinations(range(len(boxes)), 2):
        if sorted(boxes[i]) == sorted(boxes[j]):
            m.AddImplication(packed[j], packed[i])
    m.Maximize(sum((b[0] * b[1] * b[2]) * p for b, p in zip(boxes, packed)))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = workers
    with timer() as t:
        status = solver.Solve(m)
    volume = int(solver.ObjectiveValue()) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 0
    return volume, status == cp_model.OPTIMAL, t["s"], int(solver.BestObjectiveBound())


def solve_mip(boxes, container, backend, time_limit=TIME_LIMIT):
    """Classic big-M MIP (Chen, Lee & Shen 1995 style) with orientation binaries."""
    W, H, D = container
    M = max(container)
    s = pywraplp.Solver.CreateSolver(backend)
    s.SetTimeLimit(int(time_limit * 1000))
    packed, pos, size = [], [], []
    for i, dims in enumerate(boxes):
        p = s.BoolVar("")
        ors = [o for o in orientations(dims) if o[0] <= W and o[1] <= H and o[2] <= D]
        ov = [s.BoolVar("") for _ in ors]
        s.Add(sum(ov) == p)
        sz = [sum(o[a] * v for o, v in zip(ors, ov)) for a in range(3)]
        xyz = [s.NumVar(0, c, "") for c in container]
        for a, c in enumerate(container):
            s.Add(xyz[a] + sz[a] <= c)
        packed.append(p); pos.append(xyz); size.append(sz)
    for i, j in itertools.combinations(range(len(boxes)), 2):
        rel = [s.BoolVar("") for _ in range(6)]
        for a in range(3):
            s.Add(pos[i][a] + size[i][a] <= pos[j][a] + M * (1 - rel[2 * a]))
            s.Add(pos[j][a] + size[j][a] <= pos[i][a] + M * (1 - rel[2 * a + 1]))
        s.Add(sum(rel) >= packed[i] + packed[j] - 1)
    s.Maximize(sum((b[0] * b[1] * b[2]) * p for b, p in zip(boxes, packed)))
    with timer() as t:
        status = s.Solve()
    volume = int(round(s.Objective().Value())) if status in (s.OPTIMAL, s.FEASIBLE) else 0
    return volume, status == s.OPTIMAL, t["s"], int(s.Objective().BestBound()) if status in (s.OPTIMAL, s.FEASIBLE) else None


def main(sizes=(6, 8, 10, 12, 15, 20, 30, 40), seeds=(0, 1, 2)):
    rows = []
    mip_alive = {"SCIP": True, "HIGHS": True}
    cp_alive = True
    V = CONTAINER[0] * CONTAINER[1] * CONTAINER[2]
    for n in sizes:
        timeouts = {"cpsat": 0, "SCIP": 0, "HIGHS": 0}
        runs = 0
        for seed in seeds:
            boxes = random_boxes(n, CONTAINER, fill=1.2, seed=seed)
            ev, packed, et, items = engine_pack(boxes, CONTAINER, support=0.0)
            hint = {int(it.name): (tuple(it.get_position()), tuple(it.get_dimension())) for it in items}
            row = {"n": n, "seed": seed, "engine_util": ev / V, "engine_s": round(et, 4)}
            if cp_alive:
                v, opt, t, bound = solve_cpsat(boxes, CONTAINER)
                row.update(cpsat_util=v / V, cpsat_opt=opt, cpsat_s=round(t, 2), cpsat_bound=bound / V)
                timeouts["cpsat"] += not opt
                v, opt, t, _ = solve_cpsat(boxes, CONTAINER, hint=hint)
                row.update(cpsat_hint_util=v / V, cpsat_hint_opt=opt, cpsat_hint_s=round(t, 2))
            for backend in ("SCIP", "HIGHS"):
                if mip_alive[backend]:
                    v, opt, t, _ = solve_mip(boxes, CONTAINER, backend)
                    row.update({f"{backend}_util": v / V, f"{backend}_opt": opt, f"{backend}_s": round(t, 2)})
                    timeouts[backend] += not opt
            runs += 1
            rows.append(row)
            print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()}, flush=True)
        # Stop scaling a solver once it times out on every instance of a size.
        cp_alive = cp_alive and timeouts["cpsat"] < runs
        for backend in mip_alive:
            mip_alive[backend] = mip_alive[backend] and timeouts[backend] < runs
        if not cp_alive and not any(mip_alive.values()):
            print(f"all solvers time out at n={n}: stopping", flush=True)
            break
    save("e1_exact_3d.json", rows)
    return rows


if __name__ == "__main__":
    main()
