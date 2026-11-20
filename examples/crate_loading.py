"""Crates, trunks and wheeled loading crates, filled and loaded with loose goods.

Run from the repository root:  python examples/crate_loading.py [output folder]
Writes loading.png (loading steps) and loading.gif (animation) to the folder.
"""
import os
import sys

import matplotlib

matplotlib.use("Agg")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import binpack as bp  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(out, exist_ok=True)

packer = bp.Packer()
packer.add_bin_type(bp.Bin("20ft", 2350, 2390, 5900, max_weight=28000, cost=1800))
for i in range(60):   # must travel in a crate: one shape and size per crate, densest pattern
    packer.add_item(bp.Item(f"ball {i}", 300, 300, 300, shape="sphere", weight=2, crate_required=True))
for i in range(40):   # boxes of any sizes share a crate
    packer.add_item(bp.Item(f"tote {i}", 600, 400, 400, weight=6, crate_required=True))
for i in range(16):
    packer.add_item(bp.Item(f"glass {i}", 400, 300, 300, weight=8, crate_required=True))
for i in range(8):
    packer.add_item(bp.Item(f"vase {i}", 250, 450, 250, weight=4, crate_required=True, upright=True))
for i in range(30):   # optional: crated only if that takes less space than loose
    packer.add_item(bp.Item(f"cone {i}", 350, 500, 350, shape="cone", weight=1))
for i in range(12):   # loose
    packer.add_item(bp.Item(f"carton {i}", 600, 400, 500, weight=12))

crates = [
    bp.CrateType("Crate L", outer=(1250, 1100, 1250), inner=(1200, 1000, 1200), tare_weight=40, max_weight=800),
    bp.CrateType("Trunk", outer=(900, 700, 650), inner=(860, 640, 610), tare_weight=15, max_weight=300, count=4),
    bp.LoadingCrate("Dolly", outer=(1250, 850), inner=(1200, 800), base_height=180,   # wheels, no walls
                    tare_weight=35, max_weight=900, count=2),
]
plan = bp.pack_with_crates(packer, crates)

assert bp.validate(plan) == []                    # containers, crates and their contents
print(bp.format_plan(plan, max_rows_per_bin=10))
bin_ = plan.get_bins()[0]
bp.render_loading_steps(bin_, panels=6).savefig(os.path.join(out, "loading.png"), dpi=80)
bp.animate_loading(bin_, os.path.join(out, "loading.gif"), frames=30, fps=4, dpi=60)
