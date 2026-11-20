# Solver benchmarks: is an LP/MIP/CP solver worth adding?

Small, time-boxed experiments comparing the library's heuristics with free,
open-source solvers:
- OR-Tools 9.15: CP-SAT, plus SCIP / CBC / HiGHS through `pywraplp`
- PuLP 4.2 with HiGHS

They are **not part of the library**. Nothing here is imported by `src/`.

```bash
python setup.py build_ext --inplace          # from the repository root: builds the engine
pip install -r experiments/solver_benchmarks/requirements.txt
cd experiments/solver_benchmarks
python e1_exact_3d.py                        # ~3 min (10 s limit per solve)
python e1b_scaling_and_multistart.py a|b     # ~1 min each
python e2_fleet.py                           # ~3 min
python e3_selection.py                       # ~5 s
python e4_tools.py ortools && python e4_tools.py pulp
```

Results are written to `results/*.json`. Machine: 4 cores, 15 GB RAM. Every solver run has a
time limit of 5–10 s. A direction was dropped as soon as it timed out on every instance of a
size. The samples are small (3–6 instances per size): they show direction, not final numbers.

## Summary

| Part of the problem | Solver approach | Verdict |
|---|---|---|
| Placing boxes in one container (3D) | CP-SAT exact model | **Only for ~15 boxes or fewer.** Much better than the engine there, useless at realistic sizes |
| Same | MIP, big-M (SCIP, HiGHS) | **Not worth it**: already fails at 6–8 boxes |
| Which containers to book (fleet) | Integer lower bound (tiny IP) | **Worth it**: ~5 ms, gives a real quality certificate |
| Same | Column generation: LP/IP master + engine as pricing oracle | **Worth pursuing for limited fleets**: 4–9 % cheaper in 3 of the 4 larger limited-fleet cases |
| Which cargo to ship (value, weight limit, consignments) | Knapsack IP, then engine packs | **Worth it**: +6 % revenue on average, 0.2–0.3 s |
| Choice of solver for these small IPs | CP-SAT vs CBC vs SCIP vs PuLP+HiGHS | **Doesn't matter**: same optimum, 3–120 ms |

## E1 – exact 3D packing of one container (`e1_exact_3d.py`, `e1b_…`)

One container (100×100×100), random boxes summing to 1.2× its volume, all rotations allowed,
maximise packed volume. Neither side has a gravity/support rule (engine `min_support_ratio=0`),
so both solve the same problem. A per-pair "left/right/below/above/behind/front" disjunction
models non-overlap.

| boxes | engine (≈1 ms) | CP-SAT 10 s | CP-SAT proven optimal | SCIP / HiGHS big-M MIP |
|---|---|---|---|---|
| 6 | 54.0 % | 55.7 % | 3/3, 0.1 s | SCIP optimal 2/3 (3–5 s, 1 timeout); HiGHS optimal 2/3, no solution on the third |
| 8 | 51.8 % | **70.5 %** | 3/3, 0.4 s | SCIP 0/3 optimal; HiGHS finds **no** solution in 10 s |
| 10 | 69.2 % | **80.2 %** | 3/3, 0.8 s | dropped |
| 12 | 74.2 % | **89.3 %** | 1/3 | dropped |
| 15 | 81.0 % | **90.0 %** | 0/3 (timeouts) | dropped |

Warm-started from the engine's solution (10 s, one instance each):

| boxes | engine | CP-SAT | model memory |
|---|---|---|---|
| 20 | 79.1 % | 86.8 % | +63 MB |
| 40 | 82.6 % | 86.0 % | +40 MB |
| 80 | 78.4 % | 80.2 % | +134 MB |
| 160 | 80.1 % | **no solution** (not even the hint) | +166 MB (0.5 GB process) |

The pairwise model grows with n², so real loads (hundreds to thousands of boxes) are out of reach.

**Cheap alternative found on the way:** engine multi-start. Packing the same boxes in 1,000
random orders takes 0.05–0.13 s. It reached CP-SAT's result in 5 of 15 cases (within 1 point in
one more) and closes about half of the engine–CP-SAT gap overall, e.g. 12 boxes 67.8 % → 91.2 %
(optimum 91.9 %). With only 100 orders it was sometimes *worse* than the default engine, so it
would complement the default strategies, not replace them.

Verdict: the MIP is not worth it. CP-SAT is worth it only as an optional exact mode for small
loads of large items (machinery, project cargo). For the same case, a multi-start inside the
engine is a no-dependency improvement.

Caveat: the CP-SAT model has no gravity, so some of its solutions may have floating boxes.
With support rules the gap to the engine is likely smaller.

## E2 – which containers to book (`e2_fleet.py`)

Manifests of 150 / 600 / 2,000 items from 10 SKUs (cartons and upright pallets). Four types:
40ft HC, 20ft, truck, tempo, with costs and weight limits. Fleets are unlimited, or limited
to 1 × 40ft HC and 3 trucks.

- **Integer lower bound.** The cheapest container mix whose total volume *and* weight cover the
  cargo: 4 integer variables, ~5 ms. It proved the fleet planner optimal on every 150-item case.
- **Column generation.** A master LP picks "patterns" (container loads counted per SKU); the
  engine generates new ones using the LP duals as item values (objective VALUE). A final IP
  (CP-SAT) picks the patterns. The chosen containers are then really packed by the engine, and
  any leftovers go to the fleet planner (their cost is included).

| case | fleet planner | column generation (realised) | integer lower bound |
|---|---|---|---|
| 150 items (4 cases) | 2,800 | 2,800 | 2,800 (optimal) |
| 600, unlimited (2) | **8,400** / 9,800 | 8,750 (2 left over) / 9,800 | 7,050 / 8,800 |
| 600, limited (2) | 8,950 / **11,450** | **8,600** / 11,750 | 7,050 / 9,000 |
| 2,000, unlimited (2) | **26,250** / **32,200** | 27,350 / 32,300 | 21,150 / 27,500 |
| 2,000, limited (2) | 35,600 / 61,100 (14 s) | **34,100** / **55,550 (0.9 s)** | 25,300 / 33,400 |

Column generation took 0.1–7 s in total (LP + engine pricing + IP), comparable to the fleet planner.

Verdict: **worth pursuing**, mainly for limited fleets. Picking the best mix under availability
limits is where an IP beats greedy construction. On unlimited fleets the heuristic is as good or
better. Column generation loses there because its patterns don't always re-pack exactly
(2–43 leftover items) and because its pricing uses the fast single-strategy mode. Both are
fixable. Added as one more candidate, keeping the cheaper fleet, it could never make results
worse. The integer lower bound is cheap enough to report in every fleet summary.

## E3 – which cargo to ship (`e3_selection.py`)

LCL consolidation: 60 consignments (1–20 cartons each, all-or-nothing), weight-or-measure tariff
with customer-specific rates, one 40ft HC with a 26.5 t limit. The knapsack IP (CP-SAT) selects
consignments for volume ≤ α × container (α = 1.0 … 0.8) and weight ≤ limit. The engine packs
each selection, and the best result wins.

| seed | heuristic VALUE | IP → engine | gain | IP upper bound (no geometry) |
|---|---|---|---|---|
| 0 | 6,178 | 6,916 | +11.9 % | 7,857 |
| 1 | 7,552 | 8,252 | +9.3 % | 9,810 |
| 2 | 6,641 | 6,640 | 0 % | 7,975 |
| 3 | 7,641 | 7,790 | +2.0 % | 9,603 |
| 4 | 7,729 | 8,281 | +7.1 % | 9,553 |
| 5 | 6,695 | 7,119 | +6.3 % | 8,084 |

Times: 0.2–0.4 s (5 IPs + 5 packings) vs 0.1 s for the heuristic.

Verdict: **worth it.** An exact knapsack selects better than the greedy by value density. The
model is tiny (one binary per consignment, two constraints). A small exact knapsack (dynamic
programming / branch and bound) in C++ could give the same without any solver dependency.

## E4 – which free tool (`e4_tools.py`)

| problem | CP-SAT | CBC (OR-Tools) | SCIP (OR-Tools) | PuLP + HiGHS |
|---|---|---|---|---|
| consignment knapsack (60 groups) | 32–38 ms | 20–25 ms | 88–113 ms | 65–121 ms |
| fleet lower bound | – | 3–4 ms | 6–13 ms | ~9 ms |

Times are warm. The first call also pays a one-off load of up to ~0.65 s. All reach the same
optimum. Practical differences:
- **OR-Tools** has CP-SAT, CBC, SCIP and HiGHS in one wheel (Apache 2.0). But it's heavy: 80 MB,
  and it pulls in protobuf, absl and pandas.
- **PuLP 4.x** no longer bundles CBC. Here only its HiGHS backend (`highspy`, MIT) was available,
  and its API changed (`problem.add_variable(...)`).
- **OR-Tools and `highspy` can't be loaded in the same process**: whichever is imported second
  fails with an undefined HiGHS symbol. `e4_tools.py` therefore runs each tool in its own process.

## Recommended next steps (in order of value / effort)

1. Exact consignment selection for VALUE/PROFIT (E3): +6 % revenue. A small exact knapsack in C++
   avoids any new dependency.
2. Integer lower bound in fleet summaries (E2a): a cheap quality certificate. With ≤ 10 container
   types it can be solved by enumeration, no solver needed.
3. Column generation as an extra fleet-planning candidate (E2b): 4–9 % cheaper on limited fleets.
   This one needs an LP solver, i.e. an **optional** dependency (OR-Tools or HiGHS, not both in one
   process).
4. Engine multi-start for small loads (E1b): a no-dependency fix for the weakness E1 exposed.
   An optional CP-SAT exact mode only makes sense for ≤ ~15 boxes.
5. Not worth pursuing: MIP (big-M) 3D placement; CP-SAT 3D placement beyond ~80 boxes.
