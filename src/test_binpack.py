"""Tests for the Python tooling: reports, validation, pricing and rendering."""
import csv
import os
import random
import re
import tempfile
import unittest

import numpy as np

import binpack as bp
from binpack import pricing
from binpack._geometry import boxes_array
from binpack.render import camera, draw_order


def mixed_packer(seed=0, n=80, access=bp.LoadingAccess.DOOR, **kwargs):
    rnd = random.Random(seed)
    packer = bp.Packer(loading_access=access, **kwargs)
    packer.add_bin(bp.Bin("20ft", 2350, 2390, 5900, max_weight=20000))
    types = [(rnd.randint(200, 900), rnd.randint(150, 800), rnd.randint(200, 900)) for _ in range(6)]
    for i in range(n):
        packer.add_item(bp.Item(f"carton {i}", *rnd.choice(types), weight=rnd.randint(5, 60)))
    packer.pack()
    return packer


class TestReport(unittest.TestCase):
    def test_loading_plan_rows(self):
        packer = mixed_packer()
        plan = bp.loading_plan(packer)
        items = packer.get_bins()[0].get_items()
        self.assertEqual(len(plan), len(items))
        self.assertEqual([r["step"] for r in plan], list(range(1, len(items) + 1)))
        for row, item in zip(plan, items):
            self.assertEqual(row["item"], item.name)
            self.assertEqual((row["x"], row["y"], row["z"]), tuple(item.get_position()))
            # rests_on refers to earlier steps only, whose top is this item's bottom
            for s in row["rests_on"]:
                self.assertLess(s, row["step"])
                below = plan[s - 1]
                self.assertEqual(below["y"] + below["height_y"], row["y"])
            self.assertEqual(row["rests_on"] == [], row["y"] == 0)

    def test_csv_and_text(self):
        packer = mixed_packer(n=200)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plan.csv")
            bp.plan_to_csv(packer, path)
            with open(path) as fh:
                rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), len(packer.get_bins()[0].get_items()))
        text = bp.format_plan(packer, max_rows_per_bin=3)
        self.assertIn("step", text)
        self.assertIn("more steps", text)
        self.assertIn("Not loaded", text)

    def test_summary(self):
        packer = mixed_packer(n=200)
        s = bp.summary(packer)
        self.assertEqual(s["loaded_items"] + s["unfit_items"], 200)
        self.assertEqual(sum(s["unfit_by_reason"].values()), s["unfit_items"])
        self.assertAlmostEqual(s["bins"][0]["volume_utilization"], packer.get_bins()[0].get_utilization())


class TestValidate(unittest.TestCase):
    def test_packer_output_is_valid_for_every_access_side(self):
        for access in bp.LoadingAccess.__members__.values():
            for seed in range(5):
                with self.subTest(access=access, seed=seed):
                    self.assertEqual(bp.validate(mixed_packer(seed, access=access)), [])

    def test_detects_broken_plans(self):
        packer = bp.Packer(min_support_ratio=1.0)
        packer.add_bin(bp.Bin("bin", 100, 200, 200))
        for i in range(4):
            packer.add_item(bp.Item(f"box {i}", 100, 100, 100, disable_stacking=(i == 0)))
        packer.pack()
        bin_ = packer.get_bins()[0]
        items = bin_.get_items()
        items[1].position = (0, 150, 0)       # floating, and out of the bin
        items[2].position = tuple(items[3].get_position())  # overlap
        bin_.set_items(items)
        checks = {i.check for i in bp.validate_bin(bin_, 1.0, bp.LoadingAccess.DOOR)}
        self.assertTrue({"bounds", "overlap", "support"} <= checks, checks)

    def test_matches_the_cpp_sequence_checker(self):
        """Independent Python and C++ implementations agree on shuffled orders."""
        for access in (bp.LoadingAccess.DOOR, bp.LoadingAccess.TOP, bp.LoadingAccess.LEFT_SIDE):
            for seed in range(6):
                packer = mixed_packer(seed, n=60, access=access)
                bin_ = packer.get_bins()[0]
                items = bin_.get_items()
                random.Random(seed).shuffle(items)
                bin_.set_items(items)
                cpp = sorted((int(a), int(b)) for a, b in
                             (re.findall(r"step (\d+)", p)[:2] for p in bin_.check_loading_sequence(access)))
                py = sorted((i.step, int(re.search(r"step (\d+)\)", i.detail).group(1)))
                            for i in bp.validate_bin(bin_, packer.min_support_ratio, access)
                            if i.check == "loading order")
                with self.subTest(access=access, seed=seed):
                    self.assertGreater(len(cpp), 0)
                    self.assertEqual(cpp, py)

    def test_group_and_count_checks(self):
        packer = bp.Packer()
        packer.add_bin(bp.Bin("bin", 100, 100, 100))
        packer.add_item(bp.Item("a", 50, 50, 50, group="g"))
        packer.pack()
        self.assertEqual(bp.validate(packer), [])


class TestPricing(unittest.TestCase):
    def item(self, w, h, d, kg, group=""):
        return bp.Item("x", w, h, d, weight=kg, group=group)

    def test_models(self):
        light = pricing.measure([self.item(1000, 1000, 1000, 100)])  # 1 m3, 100 kg
        dense = pricing.measure([self.item(500, 500, 400, 500)])     # 0.1 m3, 500 kg
        self.assertAlmostEqual(light.volume_m3, 1.0)
        self.assertAlmostEqual(pricing.chargeable_weight(2.0, 6000)(light), 2.0 * 1e6 / 6000)
        self.assertAlmostEqual(pricing.chargeable_weight(2.0, 6000)(dense), 2.0 * 500)
        self.assertAlmostEqual(pricing.weight_or_measure(50.0)(light), 50.0)        # 1 m3 > 0.1 t
        self.assertAlmostEqual(pricing.weight_or_measure(50.0)(dense), 25.0)        # 0.5 t > 0.1 m3
        self.assertAlmostEqual(pricing.road_chargeable_weight(0.1)(light), 33.3)
        self.assertAlmostEqual(pricing.loading_meters(100.0, 2.4, None)(light), 100.0 / 2.4)
        # 0.2 m2 footprint = 0.083 LDM, but 500 kg = 0.27 LDM by weight -> charged by weight
        self.assertAlmostEqual(pricing.loading_meters(100.0, 2.4, 1850.0)(dense), 100.0 * 500 / 1850)
        self.assertEqual(pricing.freight_class(light), 150)   # 100 kg/m3 = 6.24 lb/ft3 (6-7 -> 150)
        self.assertEqual(pricing.freight_class(dense), 50)    # 5000 kg/m3 = 312 lb/ft3 (>= 50 -> 50)
        self.assertEqual(pricing.freight_class(pricing.measure([self.item(1000, 1000, 1000, 10)])), 500)
        self.assertAlmostEqual(pricing.per_piece(7.0)(light), 7.0)
        self.assertAlmostEqual(pricing.minimum(pricing.per_kg(0.01), 30.0)(light), 30.0)
        fuel = pricing.surcharge(pricing.per_kg(1.0), percent=10, flat=5, per_piece=2)
        self.assertAlmostEqual(fuel(light), 100 * 1.1 + 5 + 2)
        self.assertAlmostEqual(pricing.profit(pricing.per_kg(1.0), pricing.per_piece(30))(light), 70.0)
        self.assertAlmostEqual(pricing.highest(pricing.per_kg(1.0), pricing.per_m3(300))(light), 300.0)

    def test_price_items_by_consignment(self):
        items = [self.item(1000, 1000, 1000, 100, "A"), self.item(1000, 1000, 500, 50, "A"),
                 self.item(100, 100, 100, 1)]
        tariff = pricing.minimum(pricing.weight_or_measure(40.0), 30.0)
        total = pricing.price_items(items, tariff)
        # Item.value is a 32-bit float.
        self.assertAlmostEqual(items[0].value + items[1].value, 40.0 * 1.5, places=4)  # one consignment, 1.5 m3
        # Split by what each item would cost alone: 40 vs 30 (the minimum applies to the small one).
        self.assertAlmostEqual(items[0].value / items[1].value, 40.0 / 30.0, places=5)
        self.assertAlmostEqual(items[2].value, 30.0, places=5)                         # minimum charge
        self.assertAlmostEqual(total, 90.0)

    def test_value_objective_earns_more(self):
        rnd = random.Random(5)
        items = []
        for g in range(30):
            dims = (rnd.randint(300, 900), rnd.randint(200, 800), rnd.randint(300, 900))
            for k in range(rnd.randint(1, 8)):
                items.append(bp.Item(f"G{g}-{k}", *dims, weight=rnd.randint(20, 400), group=f"G{g}"))
        pricing.price_items(items, pricing.weight_or_measure(50.0))
        for it in items:
            it.value *= {0: 0.5, 1: 1.0, 2: 3.0}[int(it.group[1:]) % 3]  # customer-specific rates
        revenue = {}
        for objective in (bp.Objective.VOLUME, bp.Objective.VALUE):
            packer = bp.Packer(objective=objective)
            packer.add_bin(bp.Bin("20ft", 2350, 2390, 5900, max_weight=21000))
            for it in items:
                packer.add_item(it)
            packer.pack()
            self.assertEqual(bp.validate(packer), [])
            revenue[objective] = bp.summary(packer)["loaded_value"]
        offered = sum(it.value for it in items)
        self.assertGreater(revenue[bp.Objective.VALUE], revenue[bp.Objective.VOLUME] * 1.05)
        self.assertGreater(revenue[bp.Objective.VALUE], 0.9 * offered)


def _ray_truth(lo, hi, v, right, up, samples, rng):
    """Box visible at random screen points (ray casting) vs. the box drawn last there."""
    corners = np.concatenate([lo, hi]).astype(float)
    pts = np.stack([corners @ right, corners @ up], 1)
    xy = rng.uniform(pts.min(0), pts.max(0), size=(samples, 2))
    P = xy[:, :1] * right + xy[:, 1:] * up
    t_lo = np.full((samples, len(lo)), -np.inf)
    t_hi = np.full((samples, len(lo)), np.inf)
    inside = np.ones((samples, len(lo)), dtype=bool)
    for k in range(3):
        if abs(v[k]) < 1e-12:
            inside &= (lo[None, :, k] < P[:, None, k]) & (P[:, None, k] < hi[None, :, k])
            continue
        a = (lo[None, :, k] - P[:, None, k]) / v[k]
        b = (hi[None, :, k] - P[:, None, k]) / v[k]
        t_lo = np.maximum(t_lo, np.minimum(a, b))
        t_hi = np.minimum(t_hi, np.maximum(a, b))
    hit = inside & (t_lo < t_hi - 1e-6)
    return hit, t_hi


def fleet_packer():
    packer = bp.Packer()
    packer.add_bin_type(bp.Bin("Truck", 2450, 2600, 7200, max_weight=12000, cost=1400))
    packer.add_bin_type(bp.Bin("Tempo", 1700, 1700, 3000, max_weight=1500, cost=350))
    for i in range(260):
        packer.add_item(bp.Item(f"carton {i}", 600, 400, 500, weight=18, value=12))
    for i in range(30):
        packer.add_item(bp.Item(f"pallet {i}", 1200, 1000, 800, weight=300, upright=True, value=90))
    packer.pack()
    return packer


class TestFleetTools(unittest.TestCase):
    def test_summary_and_plan(self):
        packer = fleet_packer()
        self.assertEqual(bp.validate(packer), [])
        s = bp.summary(packer)
        used = [b for b in packer.get_bins() if b.get_items()]
        self.assertEqual(s["bins_used"], len(used))
        self.assertEqual(s["total_cost"], packer.get_total_cost())
        self.assertEqual(sum(s["containers_by_type"].values()), len(used))
        self.assertEqual(set(s["containers_by_type"]) <= {"Truck", "Tempo"}, True)
        self.assertAlmostEqual(s["profit"], s["loaded_value"] - s["total_cost"], places=3)
        rows = bp.loading_plan(packer)
        self.assertEqual({r["bin_type"] for r in rows}, set(s["containers_by_type"]))
        self.assertTrue(bp.format_plan(packer).startswith("Fleet:"))

    def test_validate_checks_fleet_availability(self):
        packer = bp.Packer()
        packer.add_bin_type(bp.Bin("Box", 100, 100, 100), count=1)
        for i in range(16):
            packer.add_item(bp.Item(f"c{i}", 50, 50, 50))
        packer.pack()
        self.assertEqual(bp.validate(packer), [])
        self.assertEqual(len(packer.get_unfit_items()), 8)


class TestFleetRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import matplotlib
        matplotlib.use("Agg")
        cls.packer = fleet_packer()

    def test_fleet_view_common_scale(self):
        import matplotlib.pyplot as plt
        from binpack.render import _fleet_layout, _extent
        bins = [b for b in self.packer.get_bins() if b.get_items()]
        v, right, up = camera(bp.render.DEFAULT_VIEW)
        proj = np.stack([right, up], axis=1)
        offsets, box = _fleet_layout(bins, proj)
        placed = []
        for b, (ox, oy) in zip(bins, offsets):
            xmin, xmax, ymin, ymax = _extent(b, proj)
            placed.append((xmin + ox, xmax + ox, ymin + oy, ymax + oy))
            self.assertTrue(box[0] - 1e-6 <= xmin + ox and xmax + ox <= box[1] + 1e-6)
            self.assertTrue(box[2] - 1e-6 <= ymin + oy and ymax + oy <= box[3] + 1e-6)
        for i in range(len(placed)):  # drawn bins never overlap
            for j in range(i + 1, len(placed)):
                a, b = placed[i], placed[j]
                self.assertFalse(a[0] < b[1] and b[0] < a[1] and a[2] < b[3] and b[2] < a[3])
        fig = bp.render_packer(self.packer)
        captions = [t.get_text() for t in fig.axes[0].texts if "items" in t.get_text()]
        self.assertEqual(len(captions), len(bins))
        self.assertTrue(all("cost" in c for c in captions))
        plt.close("all")

    def test_same_product_same_colour_in_every_bin(self):
        palette = bp.Palette(self.packer.get_items())
        colours = {}
        for b in self.packer.get_bins():
            for it in b.get_items():
                colours.setdefault(it.name.split()[0], set()).add(palette.color(it))
        self.assertTrue(all(len(c) == 1 for c in colours.values()))
        self.assertEqual(len({next(iter(c)) for c in colours.values()}), len(colours))

    def test_fleet_legend_covers_every_bin(self):
        import matplotlib.pyplot as plt
        packer = bp.Packer()
        packer.add_bin(bp.Bin("Van", 100, 100, 100))     # smallest: filled first, only cartons fit
        packer.add_bin(bp.Bin("Truck", 300, 300, 300))
        for i in range(8):
            packer.add_item(bp.Item(f"carton {i}", 50, 50, 50))
        packer.add_item(bp.Item("crate 0", 250, 250, 250))
        packer.pack()
        self.assertEqual([b.get_name() for b in packer.get_bins() if b.get_items()], ["Van", "Truck"])
        self.assertNotIn("crate", {i.name.split()[0] for i in packer.get_bins()[0].get_items()})
        ax = bp.render_fleet(packer)
        legend = [t.get_text() for t in ax.get_legend().get_texts()]
        self.assertEqual(len(legend), 2)
        self.assertTrue(any(t.startswith("crate") for t in legend))
        plt.close("all")

    def test_fleet_steps_and_animation(self):
        import matplotlib.pyplot as plt
        bins = [b for b in self.packer.get_bins() if b.get_items()]
        fig = bp.render_loading_steps(self.packer, panels=3)
        self.assertEqual(len(fig.axes), 3 * len(bins))
        with tempfile.TemporaryDirectory() as tmp:
            path = bp.animate_loading(self.packer, os.path.join(tmp, "fleet.gif"), frames=8)
            from PIL import Image
            with Image.open(path) as im:
                self.assertGreaterEqual(im.n_frames, len(bins))
        plt.close("all")


class TestRenderOcclusion(unittest.TestCase):
    def check(self, lo, hi, view, rng, samples=2000):
        v, right, up = camera(view)
        owner, plo, phi = draw_order(lo, hi, v)
        hit, t_exit = _ray_truth(plo, phi, v, right, up, samples, rng)
        rank = np.arange(len(owner))
        covered = hit.any(1)
        truth = owner[np.where(hit, t_exit, -np.inf).argmax(1)]
        painted = owner[np.where(hit, rank[None, :], -1).argmax(1)]
        return int((covered & (truth != painted)).sum()), int(covered.sum())

    def test_front_boxes_are_never_painted_over(self):
        rng = np.random.default_rng(1)
        wrong = total = 0
        for seed in range(25):
            packer = mixed_packer(seed, n=100, fill_order=random.Random(seed).choice(
                list(bp.FillOrder.__members__.values())))
            lo, hi = boxes_array(packer.get_bins()[0].get_items())
            view = random.Random(seed).choice([(55, 28), (0, 0), (90, 0), (0, 90), (-140, 60), (200, 10)])
            w, t = self.check(lo, hi, view, rng)
            wrong, total = wrong + w, total + t
        self.assertGreater(total, 10000)
        self.assertEqual(wrong, 0)

    def test_cyclic_overlap_is_split(self):
        # Three boxes that hide each other in a cycle from this view.
        lo = np.array([[0, 1274, 0], [744, 1381, 0], [688, 2051, 1103]])
        hi = np.array([[744, 1911, 1407], [1467, 2280, 1103], [1148, 2386, 1348]])
        view = (-149.4, 57.4)
        owner, _, _ = draw_order(lo, hi, camera(view)[0])
        self.assertGreater(len(owner), 3)  # a box had to be split
        self.assertEqual(sorted(set(owner.tolist())), [0, 1, 2])
        wrong, total = self.check(lo, hi, view, np.random.default_rng(0), samples=20000)
        self.assertGreater(total, 1000)
        self.assertEqual(wrong, 0)


class TestRenderOutput(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import matplotlib
        matplotlib.use("Agg")

    def test_figures_and_animation(self):
        import matplotlib.pyplot as plt
        packer = mixed_packer(n=120)
        with tempfile.TemporaryDirectory() as tmp:
            fig = bp.render_packer(packer)
            fig.savefig(os.path.join(tmp, "bins.png"))
            fig = bp.render_loading_steps(packer.get_bins()[0], panels=4, cols=2)
            fig.savefig(os.path.join(tmp, "steps.png"))
            ax = bp.render_bin(packer.get_bins()[0], upto=10, highlight=3, view=(0, 90), labels=True)
            self.assertTrue(any(t.get_text() == "10" for t in ax.texts))
            path = bp.animate_loading(packer.get_bins()[0], os.path.join(tmp, "load.gif"), frames=5)
            self.assertGreater(os.path.getsize(path), 1000)
            plt.close("all")

    def test_hidden_labels_are_skipped(self):
        packer = bp.Packer()
        packer.add_bin(bp.Bin("bin", 100, 100, 300))
        for i in range(3):  # a row of equal boxes seen straight from the door
            packer.add_item(bp.Item(f"b{i}", 100, 100, 100))
        packer.pack()
        ax = bp.render_bin(packer.get_bins()[0], view=(0, 0), labels=True, show_container=False)
        self.assertEqual([t.get_text() for t in ax.texts], ["3"])  # only the box at the door is visible

    def test_empty_packer(self):
        with self.assertRaises(ValueError):
            bp.render_packer(bp.Packer())


SHAPES = ["sphere", "pyramid", "cone", "cylinder"]


def shaped_packer(seed=0, n=60, **kwargs):
    """A mixed load of cartons and shaped goods, some of which may be laid on their side."""
    rnd = random.Random(seed)
    packer = bp.Packer(**kwargs)
    packer.add_bin(bp.Bin("Truck", 2400, 2400, 4000))
    for i in range(n):
        shape = rnd.choice(SHAPES + ["box"])
        size = (rnd.randint(250, 700), rnd.randint(250, 900), rnd.randint(250, 700))
        packer.add_item(bp.Item(f"{shape} {i}", *size, shape=shape, upright=rnd.random() < 0.5))
    packer.pack()
    return packer


def _true_owner(items, origins, v, scale=1.0, samples=300):
    """For rays origins + t*v: the item whose real shape (scaled about its box
    centre) is closest to the camera, -1 where the ray misses every shape."""
    from binpack import _shapes

    best, owner = np.full(len(origins), -np.inf), np.full(len(origins), -1)
    axis_ok = np.abs(v) > 1e-12
    for idx, it in enumerate(items):
        lo = np.array(it.get_position(), float)
        hi = lo + np.array(it.get_dimension(), float)
        with np.errstate(divide="ignore", invalid="ignore"):
            a, b = (lo - origins) / v, (hi - origins) / v
        t0 = np.where(axis_ok, np.minimum(a, b), -np.inf).max(1)
        t1 = np.where(axis_ok, np.maximum(a, b), np.inf).min(1)
        rows = np.nonzero((t0 < t1) & np.all(axis_ok | ((origins > lo) & (origins < hi)), axis=1))[0]
        if not len(rows):
            continue
        ts = t0[rows, None] + (t1 - t0)[rows, None] * np.linspace(0, 1, samples)
        pts = origins[rows, None, :] + ts[..., None] * v
        centre = (lo + hi) / 2
        pts = centre + (pts - centre) / scale
        inside = _shapes.inside(it, pts.reshape(-1, 3)).reshape(ts.shape)
        t_front = np.where(inside, ts, -np.inf).max(1)
        closer = t_front > best[rows]
        best[rows[closer]], owner[rows[closer]] = t_front[closer], idx
    return owner


def _painter_errors(bin_, view, samples=3000, seed=0):
    """Screen points where the renderer paints a different item than the one
    really in front. Points where a 2% smaller shape would change the answer
    (silhouettes, which the mesh only approximates) are not counted.
    Returns (errors, points counted, points on a shape, box split?)."""
    from binpack.render import _BOX_FACE, _SHAPE_FACET, _Scene

    v, right, up = camera(view)
    proj = np.stack([right, up], axis=1)
    scene = _Scene(bin_, v)
    owner, paths, _, _, _, kind = scene.faces(v, proj, bp.Palette(scene.items))
    corners = np.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)])
    screen_pts = np.vstack([scene.lo + c * (scene.hi - scene.lo) for c in corners]) @ proj
    screen = np.random.default_rng(seed).uniform(screen_pts.min(0), screen_pts.max(0), size=(samples, 2))
    painted = np.full(samples, -1)
    for o, path, k in zip(owner, paths, kind):
        if k in (_BOX_FACE, _SHAPE_FACET):
            painted[path.contains_points(screen)] = o
    origins = screen[:, :1] * right + screen[:, 1:] * up - 1e7 * v
    truth = _true_owner(scene.items, origins, v)
    robust = truth == _true_owner(scene.items, origins, v, scale=0.98)
    # The ray march can step over thin slivers (near an apex): re-check disagreements finely.
    check = np.nonzero(painted != truth)[0]
    truth[check] = _true_owner(scene.items, origins[check], v, samples=20000)
    robust[check] = truth[check] == _true_owner(scene.items, origins[check], v, scale=0.98, samples=20000)
    split = len(scene.order[0]) > len(scene.items)
    return int((robust & (painted != truth)).sum()), int(robust.sum()), int((robust & (truth >= 0)).sum()), split


class TestShapes(unittest.TestCase):
    def test_shape_argument(self):
        self.assertEqual(bp.Item("a", 1, 2, 3).shape, bp.Shape.BOX)
        self.assertEqual(bp.Item("a", 1, 2, 3, "red").shape, bp.Shape.BOX)  # legacy colour shortcut
        self.assertEqual(bp.Item("a", 1, 2, 3, shape=bp.Shape.CONE).shape, bp.Shape.CONE)
        for name in SHAPES:
            self.assertEqual(bp.Item("a", 1, 2, 3, shape=name.upper()).shape.name.lower(), name)
        item = bp.Item("a", 1, 2, 3)
        item.shape = "cylinder"
        self.assertEqual(item.shape, bp.Shape.CYLINDER)
        self.assertEqual(bp.Shape("Pyramid"), bp.Shape.PYRAMID)
        with self.assertRaisesRegex(ValueError, "unknown shape 'donut'"):
            bp.Item("a", 1, 2, 3, shape="donut")
        with self.assertRaisesRegex(ValueError, "unknown shape"):
            item.shape = "cones"
        with self.assertRaises(TypeError):
            bp.Item("a", 1, 2, 3, shape=3)

    def test_shapes_are_packed_as_their_boxes(self):
        shaped = shaped_packer(seed=3)
        plain = bp.Packer()
        plain.add_bin(bp.Bin("Truck", 2400, 2400, 4000))
        for it in shaped.items:
            plain.add_item(bp.Item(it.name, it.width, it.height, it.depth, upright=it.upright))
        plain.pack()
        layout = lambda p: [(it.name, tuple(it.get_position()), it.get_rotation_type())  # noqa: E731
                            for b in p.get_bins() for it in b.get_items()]
        self.assertEqual(layout(shaped), layout(plain))
        self.assertEqual(bp.validate(shaped), [])

    def test_shape_survives_packing_and_fleet_planning(self):
        packer = bp.Packer()
        packer.add_bin_type(bp.Bin("Van", 1000, 1000, 1000, cost=100), count=2)
        kinds = SHAPES + ["box"]
        for i in range(60):
            packer.add_item(bp.Item(f"x{i}", 400, 400, 400, shape=kinds[i % 5]))
        packer.pack()
        loaded = [it for b in packer.get_bins() for it in b.get_items()]
        unfit = list(packer.get_unfit_items())
        self.assertTrue(loaded and unfit)
        for it in loaded + unfit:
            self.assertEqual(it.shape.name.lower(), kinds[int(it.name[1:]) % 5])

    def test_meshes_fill_their_box(self):
        from binpack import _shapes

        for name in SHAPES:
            mesh = _shapes.unit_mesh(bp.Shape(name))
            self.assertEqual(len(mesh.vertices) - len(mesh.edges) + len(mesh.faces), 2)  # closed
            for rotation in bp.ALL_ROTATIONS:
                item = bp.Item("x", 300, 500, 200, shape=name)
                item.set_rotation_type(rotation)
                item.set_position((10, 20, 30))
                placed = _shapes.place(item)
                lo = np.array([10, 20, 30.0])
                hi = lo + np.array(item.get_dimension())
                # Inscribed in the carton: inside it, touching its extent on every axis.
                np.testing.assert_allclose(placed.vertices.min(0), lo, atol=1e-9)
                np.testing.assert_allclose(placed.vertices.max(0), hi, atol=1e-9)
                # Normals point outwards: a step along one leaves the shape, a step against it doesn't.
                inverse = np.argsort(_shapes._AXES[rotation])
                size = np.array([300, 500, 200.0])
                inside = lambda p: _shapes.inside_unit(bp.Shape(name), (p - lo)[:, inverse] / size)  # noqa: E731
                centres = placed.vertices[mesh.faces].mean(1)
                self.assertFalse(inside(centres + 5 * placed.normals).any())
                self.assertTrue(inside(centres - 1 * placed.normals).all())
        # A cylinder turned with its height along x lies on its side.
        pipe = bp.Item("pipe", 300, 1200, 300, shape="cylinder")
        pipe.set_rotation_type(bp.RotationType.hwd)
        verts = _shapes.place(pipe).vertices
        self.assertAlmostEqual(np.ptp(verts[:, 0]), 1200)
        self.assertAlmostEqual(np.ptp(verts[:, 1]), 300)

    def test_front_shapes_are_never_painted_over(self):
        wrong = on_shape = 0
        for seed, view in enumerate([(55, 28), (0, 0), (90, 0), (0, 90), (-140, 60), (33, -20)]):
            w, _, s, _ = _painter_errors(shaped_packer(seed=seed, n=40).get_bins()[0], view, seed=seed)
            wrong, on_shape = wrong + w, on_shape + s
        self.assertGreater(on_shape, 8000)
        self.assertEqual(wrong, 0)

    def test_shapes_in_split_boxes(self):
        # The cyclic layout of TestRenderOcclusion: a box is split to draw it; so is its shape.
        lo = np.array([[0, 1274, 0], [744, 1381, 0], [688, 2051, 1103]])
        hi = np.array([[744, 1911, 1407], [1467, 2280, 1103], [1148, 2386, 1348]])
        for shapes in [("cylinder", "sphere", "cone"), ("sphere", "pyramid", "cylinder"), ("box", "sphere", "box")]:
            bin_ = bp.Bin("b", 2000, 3000, 2000)
            items = []
            for k, (l, h, shape) in enumerate(zip(lo, hi, shapes)):
                items.append(bp.Item(f"i{k}", *(int(x) for x in h - l), shape=shape))
                items[-1].set_position(tuple(int(x) for x in l))
            bin_.items = items
            wrong, _, on_shape, split = _painter_errors(bin_, (-149.4, 57.4), samples=8000)
            self.assertTrue(split)
            self.assertGreater(on_shape, 2000)
            self.assertEqual(wrong, 0, shapes)

    def test_report_legend_and_pictures(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from binpack.render import _CARTON, _Scene

        packer = shaped_packer(n=30)
        rows = bp.loading_plan(packer)
        self.assertEqual({r["shape"] for r in rows}, set(SHAPES) | {"box"})
        self.assertIn("shape", bp.format_plan(packer).splitlines()[1])
        self.assertNotIn("shape", bp.format_plan(mixed_packer(n=10)))  # box-only plans are unchanged
        with tempfile.TemporaryDirectory() as tmp:
            bp.plan_to_csv(packer, os.path.join(tmp, "plan.csv"))
            with open(os.path.join(tmp, "plan.csv")) as fh:
                self.assertEqual([r["shape"] for r in csv.DictReader(fh)], [r["shape"] for r in rows])
            ax = bp.render_bin(packer.get_bins()[0], labels=True)
            legend = [t.get_text() for t in ax.get_legend().get_texts()]
            self.assertTrue(any(re.search(r"^cone \d+x\d+x\d+ cone", t) for t in legend))
            self.assertTrue(any(t.get_text().isdigit() for t in ax.texts))
            bp.render_loading_steps(packer, panels=2).savefig(os.path.join(tmp, "steps.png"))
            bp.render_packer(packer, cartons=False).savefig(os.path.join(tmp, "fleet.png"))
            bp.animate_loading(packer.get_bins()[0], os.path.join(tmp, "load.gif"), frames=3)
        v, right, up = camera(bp.render.DEFAULT_VIEW)
        proj = np.stack([right, up], axis=1)
        palette = bp.Palette(packer.get_items())
        kinds = lambda cartons: _Scene(packer.get_bins()[0], v, cartons).faces(v, proj, palette)[-1]  # noqa: E731
        self.assertIn(_CARTON, kinds(True))
        self.assertNotIn(_CARTON, kinds(False))
        plt.close("all")


def _bulk_overlaps(container, samples=150, seed=0):
    """Pairs of pieces whose real shapes share volume (sampled where their boxes meet)."""
    from binpack import _shapes

    rng = np.random.default_rng(seed)
    items = container.get_items()
    lo = np.array([p.get_position() for p in items])
    hi = lo + np.array([p.get_dimension() for p in items])
    bad = 0
    for i in range(len(items)):
        shared = np.all((lo[i] < hi - 1e-6) & (lo < hi[i] - 1e-6), axis=1)
        shared[:i + 1] = False
        for j in np.nonzero(shared)[0]:
            a, b = np.maximum(lo[i], lo[j]), np.minimum(hi[i], hi[j])
            pts = a + rng.random((samples, 3)) * (b - a)
            ci, cj = (lo[i] + hi[i]) / 2, (lo[j] + hi[j]) / 2
            # 0.1% smaller shapes: exact contact (touching cones, pyramid faces) is fine
            bad += bool((_shapes.inside(items[i], ci + (pts - ci) / 0.999) &
                         _shapes.inside(items[j], cj + (pts - cj) / 0.999)).any())
    return bad


class TestBulk(unittest.TestCase):
    C40 = bp.Bin("40ft HC", 2350, 2690, 12030, max_weight=26500, cost=3000)

    def test_patterns_beat_one_carton_per_piece(self):
        cases = [  # item, minimum gain over cartons, pattern
            (bp.Item("ball", 400, 400, 400, shape="sphere"), 1.5, "close packing"),
            (bp.Item("pipe", 300, 1200, 300, shape="cylinder"), 1.2, "hexagonal"),
            (bp.Item("cone", 400, 700, 400, shape="cone"), 2.0, "tip down"),
            (bp.Item("pyramid", 700, 600, 700, shape="pyramid"), 1.9, "tip down"),
        ]
        for item, gain, pattern in cases:
            lay = bp.bulk_layout(item, self.C40)
            self.assertGreaterEqual(lay.count / lay.carton_count, gain, item.name)
            self.assertIn(pattern, lay.pattern)
            self.assertEqual(len(lay.positions), lay.count)
        # Spheres: denser than a plain grid (52 %) in a large container.
        ball = bp.Item("ball", 300, 300, 300, shape="sphere")
        self.assertGreater(bp.bulk_layout(ball, self.C40).count * bp.bulk.solid_volume(ball) / self.C40.get_volume(),
                           0.62)

    def test_upright_keeps_tips_up(self):
        for shape in ("cone", "pyramid"):
            item = bp.Item(shape, 400, 700, 400, shape=shape, upright=True)
            lay = bp.bulk_layout(item, self.C40)
            self.assertFalse(lay.inverted.any())
            self.assertIn(lay.rotation, bp.UPRIGHT_ROTATIONS)
        pyramid = bp.Item("pyramid", 700, 600, 700, shape="pyramid", upright=True)
        lay = bp.bulk_layout(pyramid, self.C40)
        self.assertEqual(lay.count, lay.carton_count)  # bases already tile the floor
        # Lying cones may point either way: that's a turn about the vertical axis.
        lying = bp.bulk_layout(bp.Item("cone", 400, 700, 400, shape="cone"), self.C40)
        self.assertTrue(lying.inverted.any())

    def test_pieces_never_overlap(self):
        rnd = random.Random(1)
        container = bp.Bin("c", 1500, 1400, 1900)
        for trial in range(16):
            shape = SHAPES[trial % 4]
            w = rnd.randint(250, 600)
            h = w if shape == "sphere" and trial % 8 < 4 else rnd.randint(250, 900)
            d = w if rnd.random() < 0.7 else rnd.randint(250, 600)
            item = bp.Item("x", w, h, d, shape=shape, upright=rnd.random() < 0.3)
            lay = bp.bulk_layout(item, container)
            if lay is None:
                continue
            plan = bp.pack_bulk(item, lay.count, [container])
            c = plan.containers[0]
            lo = np.array([p.get_position() for p in c.items])
            hi = lo + np.array([p.get_dimension() for p in c.items])
            self.assertTrue((lo >= -1e-6).all() and (hi <= np.array([1500, 1400, 1900]) + 1e-6).all())
            self.assertEqual(_bulk_overlaps(c, seed=trial), 0, (shape, w, h, d, lay.pattern))

    def test_containers_and_remainder(self):
        c20 = bp.Bin("20ft", 2350, 2390, 5900, max_weight=28000, cost=1800)
        ball = bp.Item("ball", 450, 450, 450, shape="sphere", weight=2)
        per40 = bp.bulk_layout(ball, self.C40).count
        per20 = bp.bulk_layout(ball, c20).count
        plan = bp.pack_bulk(ball, 2 * per40 + 10, [self.C40, c20])
        self.assertEqual([c.name for c in plan.containers], ["40ft HC #1", "40ft HC #2", "20ft #1"])
        self.assertEqual([len(c.items) for c in plan.containers], [per40, per40, 10])  # rest left empty
        self.assertEqual(len(plan.get_items()), 2 * per40 + 10)
        self.assertEqual(plan.get_total_cost(), 2 * 3000 + 1800)
        self.assertEqual(len({p.name for p in plan.get_items()}), 2 * per40 + 10)
        # The partial container is loaded from the back.
        z = [p.position[2] for p in plan.containers[-1].items]
        self.assertLess(max(z), 5900 / 2)
        self.assertGreater(per20, 0)
        # Weight limit caps the count.
        heavy = bp.Item("ball", 450, 450, 450, shape="sphere", weight=100)
        lay = bp.bulk_layout(heavy, c20)
        self.assertEqual(lay.count, 280)
        self.assertTrue(lay.limited_by_weight)
        # Too large for every container.
        plan = bp.pack_bulk(bp.Item("globe", 3000, 3000, 3000, shape="sphere"), 3, [c20])
        self.assertEqual(len(plan.get_unfit_items()), 3)
        self.assertEqual(plan.containers, [])
        with self.assertRaises(ValueError):
            bp.bulk_layout(bp.Item("carton", 400, 400, 400), c20)

    def test_report(self):
        cone = bp.Item("cone", 400, 700, 400, shape="cone", weight=3)
        plan = bp.pack_bulk(cone, 500, [self.C40])
        text = bp.format_bulk(plan)
        self.assertIn("500 of", text)
        self.assertIn("tip down", text)
        self.assertIn("one carton per piece", text)
        rows = bp.bulk.bulk_rows(plan)
        self.assertEqual(len(rows), 500)
        self.assertEqual(sum(r["tip_down"] for r in rows), sum(p.inverted for p in plan.get_items()))
        with tempfile.TemporaryDirectory() as tmp:
            bp.bulk_to_csv(plan, os.path.join(tmp, "bulk.csv"))
            with open(os.path.join(tmp, "bulk.csv")) as fh:
                self.assertEqual(len(list(csv.DictReader(fh))), 500)

    def test_pictures_are_correct(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        container = bp.Bin("c", 1800, 1600, 2400)
        cases = [("sphere", 450, 450, (55, 28)), ("cylinder", 350, 600, (99, -10)),
                 ("cone", 360, 415, (133, 6)), ("pyramid", 374, 792, (-117, -9)), ("cone", 450, 370, (0, 90))]
        wrong = on_shape = 0
        for k, (shape, w, h, view) in enumerate(cases):
            item = bp.Item(shape, w, h, w, shape=shape)
            plan = bp.pack_bulk(item, bp.bulk_layout(item, container).count, [container])
            e, _, s, _ = _painter_errors(plan.containers[0], view, samples=1500, seed=k)
            wrong, on_shape = wrong + e, on_shape + s
        self.assertGreater(on_shape, 5000)
        self.assertEqual(wrong, 0)
        with tempfile.TemporaryDirectory() as tmp:
            bp.render_packer(plan).savefig(os.path.join(tmp, "bulk.png"))
            bp.animate_loading(plan, os.path.join(tmp, "bulk.gif"), frames=3)
        plt.close("all")


def crate_packer(**kwargs):
    packer = bp.Packer(**kwargs)
    packer.add_bin_type(bp.Bin("20ft", 2350, 2390, 5900, max_weight=28000, cost=1800))
    for i in range(60):
        packer.add_item(bp.Item(f"ball {i}", 300, 300, 300, shape="sphere", weight=2, crate_required=True))
    for i in range(30):
        packer.add_item(bp.Item(f"cone {i}", 350, 500, 350, shape="cone", weight=1))
    for i in range(20):
        packer.add_item(bp.Item(f"glass {i}", 400, 300, 300, weight=8, crate_required=True))
    for i in range(10):
        packer.add_item(bp.Item(f"vase {i}", 250, 450, 250, weight=4, crate_required=True, upright=True))
    for i in range(25):
        packer.add_item(bp.Item(f"carton {i}", 600, 400, 500, weight=12))
    packer.add_item(bp.Item("statue", 1500, 1500, 1500, weight=200, crate_required=True))
    return packer


CRATES = [bp.CrateType("Crate L", outer=(1250, 1100, 1250), inner=(1200, 1000, 1200), tare_weight=40, max_weight=800),
          bp.CrateType("Trunk", outer=(900, 700, 650), inner=(860, 640, 610), tare_weight=15, max_weight=300, count=3)]


def _solids(scene):
    """Everything solid in a scene: loose items, the contents of crates and the
    bases of loading crates, in container coordinates."""
    out = []
    for i, it in enumerate(scene.items):
        k = getattr(it, "crate_index", -1)
        if scene.crates is None or k < 0:
            out.append(it)
            continue
        crate = scene.crates[k]
        out += crate.placed_contents(it)
        if crate.type.open_top:
            lo = scene.lo[i]
            base = bp.Item(f"crate base {i}", int(scene.hi[i][0] - lo[0]), int(crate.type.base_height),
                           int(scene.hi[i][2] - lo[2]))
            base.set_position(tuple(int(x) for x in lo))
            out.append(base)
    return out


def _crate_painter_errors(bin_, view, samples=2000, seed=0):
    """Like _painter_errors, item by item inside crates (crate walls are see-through)."""
    from binpack.render import _BOX_FACE, _SHAPE_FACET, _Scene, _palette_items

    v, right, up = camera(view)
    proj = np.stack([right, up], axis=1)
    scene = _Scene(bin_, v)
    _, paths, _, _, _, kind = scene.faces(v, proj, bp.Palette(_palette_items(scene.items, scene.crates)))
    solids = _solids(scene)
    key = lambda o: (o.name, tuple(np.round(o.get_position(), 3)))  # noqa: E731
    index = {key(o): n for n, o in enumerate(solids)}
    corners = np.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)])
    screen_pts = np.vstack([scene.lo + c * (scene.hi - scene.lo) for c in corners]) @ proj
    screen = np.random.default_rng(seed).uniform(screen_pts.min(0), screen_pts.max(0), size=(samples, 2))
    painted = np.full(samples, -1)
    for path, k, solid in zip(paths, kind, scene.solids):
        if isinstance(solid, tuple):  # the base of loading crate i
            solid = next(o for o in solids if o.name == f"crate base {solid[1]}")
        if k in (_BOX_FACE, _SHAPE_FACET):
            painted[path.contains_points(screen)] = index[key(solid)]
    origins = screen[:, :1] * right + screen[:, 1:] * up - 1e7 * v
    truth = _true_owner(solids, origins, v)
    robust = truth == _true_owner(solids, origins, v, scale=0.98)
    check = np.nonzero(painted != truth)[0]
    truth[check] = _true_owner(solids, origins[check], v, samples=20000)
    robust[check] = truth[check] == _true_owner(solids, origins[check], v, scale=0.98, samples=20000)
    return int((robust & (painted != truth)).sum()), int((robust & (truth >= 0)).sum())


class TestCrates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packer = crate_packer()
        cls.plan = bp.pack_with_crates(cls.packer, CRATES)

    def test_crate_type_checks(self):
        with self.assertRaisesRegex(ValueError, "does not fit"):
            bp.CrateType("bad", outer=(100, 100, 100), inner=(120, 90, 90))
        with self.assertRaisesRegex(ValueError, "distinct names"):
            bp.pack_with_crates(crate_packer(), [CRATES[0], CRATES[0]])
        t = bp.CrateType("t", outer=(100, 120, 100), inner=(90, 100, 90))
        self.assertEqual(t.inner_offset, (5.0, 10.0, 5.0))  # centred

    def test_plain_packer_never_loads_crate_items_loose(self):
        packer = bp.Packer()
        packer.add_bin(bp.Bin("b", 1000, 1000, 1000))
        packer.add_item(bp.Item("glass", 100, 100, 100, crate_required=True))
        packer.add_item(bp.Item("box", 100, 100, 100))
        packer.pack()
        self.assertEqual([it.name for it in packer.get_bins()[0].get_items()], ["box"])
        self.assertIn("crate", packer.get_unfit_items()[0].unfit_reason)

    def test_crate_rules(self):
        plan = self.plan
        self.assertEqual(bp.validate(plan), [])
        self.assertEqual(len(self.packer.items), 146)  # the caller's packer is left as it was
        self.assertEqual(self.packer.get_bins(), [])
        for crate in plan.crates:
            shapes = {it.shape for it in crate.contents}
            self.assertEqual(len(shapes), 1, crate.name)
            if shapes != {bp.Shape.BOX}:
                self.assertEqual(len({(it.width, it.height, it.depth) for it in crate.contents}), 1)
            self.assertLessEqual(crate.goods_weight, crate.type.max_weight)
        self.assertLessEqual(sum(c.type.name == "Trunk" for c in plan.crates), 3)
        loaded_goods = [g for c in plan.crates if c.item is not None for g in c.contents]
        top = [it for b in plan.get_bins() for it in b.get_items()]
        loose = [it for it in top if it.crate_index < 0]
        self.assertFalse(any(it.crate_required for it in loose))
        for name in ("ball", "glass", "vase"):  # required: all crated
            self.assertEqual(sum(g.name.startswith(name) for g in loaded_goods),
                             {"ball": 60, "glass": 20, "vase": 10}[name])
        # The statue fits no crate: reported, never loaded loose.
        self.assertEqual([g.name for g in plan.unloaded_goods()], ["statue"])
        self.assertIn("every crate", plan.get_unfit_items()[0].unfit_reason)
        # Optional cartons rode in the free space of a crate of glassware.
        self.assertTrue(any(g.name.startswith("carton") for g in loaded_goods))

    def test_optional_items(self):
        plan = bp.pack_with_crates(crate_packer(), CRATES, crate_optional=False)
        self.assertEqual(bp.validate(plan), [])
        for crate in plan.crates:
            self.assertTrue(all(g.crate_required for g in crate.contents), crate.name)
        # A few cones: a big crate would take more space than the cones loose.
        packer = bp.Packer()
        packer.add_bin(bp.Bin("truck", 2400, 2400, 6000))
        for i in range(3):
            packer.add_item(bp.Item(f"cone {i}", 350, 500, 350, shape="cone"))
        plan = bp.pack_with_crates(packer, CRATES[:1])
        self.assertEqual(plan.crates, [])
        self.assertEqual(len(plan.get_bins()[0].get_items()), 3)
        # Many cones: crated, as the crate is smaller than their boxes.
        for i in range(3, 40):
            packer.add_item(bp.Item(f"cone {i}", 350, 500, 350, shape="cone"))
        plan = bp.pack_with_crates(packer, CRATES[:1])
        self.assertEqual(len(plan.crates), 1)
        self.assertLess(plan.crates[0].type.outer_volume, 40 * 350 * 500 * 350)

    def test_stock_and_consignments(self):
        packer = bp.Packer()
        packer.add_bin(bp.Bin("truck", 2400, 2400, 6000))
        for g in ("A", "B"):
            for i in range(5):
                packer.add_item(bp.Item(f"{g} glass {i}", 400, 300, 300, crate_required=True, group=g))
        trunk = bp.CrateType("Trunk", outer=(900, 700, 650), inner=(860, 640, 610), count=1)
        plan = bp.pack_with_crates(packer, [trunk])
        self.assertEqual(len(plan.crates), 1)  # only one trunk: one consignment ships
        self.assertEqual({g.group for g in plan.crates[0].contents}, {plan.crates[0].group})
        self.assertEqual(len(plan.unloaded_goods()), 5)
        self.assertIn("no crate left", plan.get_unfit_items()[0].unfit_reason)
        plan = bp.pack_with_crates(packer, [bp.CrateType("Trunk", outer=(900, 700, 650), inner=(860, 640, 610))])
        self.assertEqual(sorted(c.group for c in plan.crates), ["A", "B"])  # never mixed
        self.assertEqual(bp.validate(plan), [])
        # A consignment bigger than a crate fills several crates, which travel in one container.
        for i in range(5, 40):
            packer.add_item(bp.Item(f"A glass {i}", 400, 300, 300, crate_required=True, group="A"))
        plan = bp.pack_with_crates(packer, [bp.CrateType("Trunk", outer=(900, 700, 650), inner=(860, 640, 610))])
        self.assertGreater(sum(c.group == "A" for c in plan.crates), 1)
        self.assertEqual(plan.unloaded_goods(), [])
        self.assertEqual(bp.validate(plan), [])

    def test_fleet_and_upright_contents(self):
        self.assertEqual(self.plan.get_total_cost(), 1800)
        self.assertTrue(self.plan.get_bins()[0].get_name().startswith("20ft"))
        loose_crate = bp.CrateType("Box", outer=(1000, 800, 900), inner=(950, 750, 850), upright=False)
        packer = bp.Packer()
        packer.add_bin(bp.Bin("truck", 2400, 2400, 6000))
        packer.add_item(bp.Item("vase", 250, 450, 250, crate_required=True, upright=True))
        plan = bp.pack_with_crates(packer, [loose_crate])
        self.assertTrue(plan.crates[0].item.upright)  # "this side up" inside: the crate stays upright

    def test_contents_follow_the_crate_in_every_rotation(self):
        from binpack import _shapes

        for crate in self.plan.crates:
            t = crate.type
            for rotation in bp.ALL_ROTATIONS:
                item = bp.Item("c", *t.outer)
                item.set_rotation_type(rotation)
                item.set_position((100, 200, 300))
                placed = crate.placed_contents(item)
                lo = np.array([p.get_position() for p in placed])
                hi = lo + np.array([p.get_dimension() for p in placed])
                axes = list(_shapes._AXES[rotation])
                inner_lo = np.array([100, 200, 300.0]) + np.array(t.inner_offset)[axes]
                self.assertTrue((lo >= inner_lo - 1e-6).all() and (hi <= inner_lo + np.array(t.inner)[axes] + 1e-6).all())

                class Holder:
                    def get_items(self):
                        return placed
                self.assertEqual(_bulk_overlaps(Holder(), samples=40), 0, (crate.name, rotation))

    def test_reports(self):
        rows = bp.loading_plan(self.plan)
        crates = [r for r in rows if r["contents"]]
        self.assertEqual(len(crates), len(self.plan.crates))
        self.assertRegex(crates[0]["contents"], r"^\d+ x ")
        manifest = bp.crate_manifest(self.plan)
        self.assertEqual(len(manifest), sum(len(c.contents) for c in self.plan.crates))
        text = bp.format_plan(self.plan)
        self.assertIn("== Crates:", text)
        self.assertIn("alternating tip up / tip down", text)

    def test_pictures_are_correct(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        wrong = on_solid = 0
        for k, view in enumerate([(55, 28), (0, 0), (-140, 60), (200, 10)]):
            w, s = _crate_painter_errors(self.plan.get_bins()[0], view, seed=k)
            wrong, on_solid = wrong + w, on_solid + s
        self.assertGreater(on_solid, 4000)
        self.assertEqual(wrong, 0)
        ax = bp.render_bin(self.plan.get_bins()[0])
        legend = [t.get_text() for t in ax.get_legend().get_texts()]
        self.assertTrue(any(t.startswith("ball") for t in legend))
        self.assertFalse(any("Crate" in t or "Trunk" in t for t in legend))  # crates show their goods
        with tempfile.TemporaryDirectory() as tmp:
            bp.render_loading_steps(self.plan, panels=2).savefig(os.path.join(tmp, "steps.png"))
            bp.animate_loading(self.plan, os.path.join(tmp, "crates.gif"), frames=3)
        plt.close("all")


class TestLoadingCrates(unittest.TestCase):
    DOLLY = dict(outer=(1250, 850), inner=(1200, 800), base_height=180, tare_weight=35, max_weight=900)

    def packer(self, *heights):
        packer = bp.Packer()
        for h in heights or (2390,):
            packer.add_bin_type(bp.Bin(f"box {h}", 2350, h, 5900, max_weight=28000, cost=h))
        for i in range(40):
            packer.add_item(bp.Item(f"tote {i}", 600, 400, 400, weight=6, crate_required=True))
        for i in range(30):
            packer.add_item(bp.Item(f"ball {i}", 300, 300, 300, shape="sphere", weight=2, crate_required=True))
        for i in range(10):
            packer.add_item(bp.Item(f"carton {i}", 600, 400, 500, weight=12))
        return packer

    def test_sizes(self):
        dolly = bp.LoadingCrate("Dolly", **self.DOLLY)
        self.assertFalse(dolly.resolved)
        self.assertEqual(dolly.inner_offset, (25.0, 180.0, 25.0))
        tall = dolly.with_height(2690)
        self.assertEqual((tall.outer, tall.inner), ((1250, 2690, 850), (1200, 2510, 800)))
        self.assertTrue(tall.floor_only and tall.upright and not tall.stackable)
        with self.assertRaisesRegex(ValueError, "footprint"):
            bp.LoadingCrate("x", outer=(1000, 800), inner=(1100, 800), base_height=100)
        with self.assertRaisesRegex(ValueError, "no room"):
            bp.LoadingCrate("x", outer=(1000, 800), inner=(900, 700), base_height=3000, height=2000)
        with self.assertRaisesRegex(ValueError, "containers"):
            bp.pack_with_crates(bp.Packer(), [dolly])

    def test_column_is_the_container_height(self):
        for heights, column in (((2390,), 2390), ((2690,), 2690), ((2690, 2390), 2390)):
            plan = bp.pack_with_crates(self.packer(*heights), [bp.LoadingCrate("Dolly", **self.DOLLY)])
            self.assertEqual(plan.crate_types[0].outer[1], column)
            self.assertEqual(plan.crate_types[0].inner[1], column - 180)
        fixed = bp.LoadingCrate("Dolly", height=2000, **self.DOLLY)
        plan = bp.pack_with_crates(self.packer(2690), [fixed])
        self.assertEqual(plan.crate_types[0].outer[1], 2000)

    def test_loading_rules(self):
        trunk = bp.CrateType("Trunk", outer=(900, 700, 650), inner=(860, 640, 610))
        plan = bp.pack_with_crates(self.packer(2690, 2390), [bp.LoadingCrate("Dolly", **self.DOLLY), trunk])
        self.assertEqual(bp.validate(plan), [])
        self.assertEqual(plan.unloaded_goods(), [])
        dollies = [(b, it) for b in plan.get_bins() for it in b.get_items()
                   if it.crate_index >= 0 and plan.crate_of(it).type.open_top]
        self.assertTrue(dollies)
        for b, it in dollies:
            self.assertEqual(it.get_position()[1], 0)  # on its wheels on the floor
            self.assertTrue(it.disable_stacking and it.bottom_load_only and it.upright)
            lo = np.array(it.get_position())
            hi = lo + np.array(it.get_dimension())
            for other in b.get_items():  # nothing above it, not even in a taller container
                if other is not it and other.get_position()[1] >= hi[1]:
                    o_lo = np.array(other.get_position())
                    o_hi = o_lo + np.array(other.get_dimension())
                    self.assertFalse(o_lo[0] < hi[0] and lo[0] < o_hi[0] and o_lo[2] < hi[2] and lo[2] < o_hi[2])
            for g in plan.crate_of(it).placed_contents(it):  # goods stand on the base, within the footprint
                self.assertGreaterEqual(g.get_position()[1], lo[1] + 180 - 1e-6)
        self.assertIn("loading crate, open to 2390", bp.format_plan(plan))

    def test_pictures_are_correct(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plan = bp.pack_with_crates(self.packer(2690), [bp.LoadingCrate("Dolly", **self.DOLLY)])
        wrong = on_solid = 0
        for k, view in enumerate([(55, 28), (-140, 30), (40, -15), (0, 0)]):  # from above and below
            w, s = _crate_painter_errors(plan.get_bins()[0], view, seed=k)
            wrong, on_solid = wrong + w, on_solid + s
        self.assertGreater(on_solid, 3000)
        self.assertEqual(wrong, 0)
        bp.render_packer(plan)
        plt.close("all")


if __name__ == "__main__":
    unittest.main()
