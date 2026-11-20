"""Shaped goods (spheres, cones, cylinders, pyramids) loaded with cartons.

Run from the repository root:  python examples/shaped_goods.py [output folder]
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

packer = bp.Packer(fill_order=bp.FillOrder.BACK_BOTTOM_LEFT, loading_access=bp.LoadingAccess.DOOR)
packer.add_bin(bp.Bin("20ft", 2350, 2390, 5900, max_weight=28000))
for i in range(16):
    packer.add_item(bp.Item(f"carton {i}", 600, 400, 500, weight=12))
for i in range(12):
    packer.add_item(bp.Item(f"drum {i}", 600, 900, 600, weight=60, shape="cylinder", upright=True))
for i in range(6):
    packer.add_item(bp.Item(f"pipe {i}", 300, 1800, 300, weight=25, shape="cylinder"))   # may lie down
for i in range(12):
    packer.add_item(bp.Item(f"ball {i}", 450, 450, 450, weight=3, shape="sphere"))
for i in range(10):   # nothing is stacked on a tip
    packer.add_item(bp.Item(f"traffic cone {i}", 400, 700, 400, weight=2, shape="cone", upright=True,
                            disable_stacking=True))
for i in range(6):
    packer.add_item(bp.Item(f"display {i}", 700, 600, 700, weight=8, shape="pyramid", upright=True,
                            disable_stacking=True))
packer.pack()

assert bp.validate(packer) == []                  # every loading rule holds
print(bp.format_plan(packer, max_rows_per_bin=10))
bin_ = packer.get_bins()[0]
bp.render_loading_steps(bin_, panels=6).savefig(os.path.join(out, "loading.png"), dpi=80)
bp.animate_loading(bin_, os.path.join(out, "loading.gif"), frames=30, fps=5, dpi=60)
