"""Constraint guards: run these after every change.

``bp.validate`` is an independent audit of every loading rule. These tests
make sure that

* every feature produces plans that pass the audit (TestPlansAreValid), and
* the audit catches each kind of violation (TestValidatorCatches): a valid
  plan is broken one rule at a time and the matching check must fire.
  Without this half, a check that silently stopped working would let the
  first half pass.

Run: ``cd src && python -m unittest test_constraints``
"""
import random
import unittest
from types import SimpleNamespace

import binpack as bp

DOOR = bp.LoadingAccess.DOOR
SHAPES = ("sphere", "cylinder", "cone", "pyramid")


def checks(issues):
    return {i.check for i in issues}


# ----------------------------------------------------------------- scenarios --

def rules_packer(seed, fill_order, access):
    """Cartons with every handling rule, a weight limit, consignments and priorities."""
    rnd = random.Random(seed)
    packer = bp.Packer(fill_order=fill_order, loading_access=access)
    packer.add_bin(bp.Bin("20ft", 2350, 2390, 5900, max_weight=6000))
    sizes = [(600, 400, 500), (400, 300, 300), (800, 600, 600), (300, 900, 300)]
    for i in range(120):
        w, h, d = rnd.choice(sizes)
        packer.add_item(bp.Item(
            f"item {i}", w, h, d, weight=rnd.randint(5, 90),
            upright=rnd.random() < 0.3, bottom_load_only=rnd.random() < 0.1,
            disable_stacking=rnd.random() < 0.08,
            stuffing_max_weight=rnd.choice([0, 0, 60, 150]), stuffing_layers=rnd.choice([0, 0, 1, 2]),
            stuffing_height=rnd.choice([0, 0, 700]),
            allowed_rotations=rnd.choice([[], [], [bp.RotationType.whd, bp.RotationType.dhw]]),
            priority=rnd.choice([0, 0, 1]), group=rnd.choice(["", "", "", "A", "B"]),
            shape=rnd.choice(["box", "box", "box", *SHAPES])))
    packer.pack()
    return packer


def crate_packer(heights=(2390,), seed=0):
    """Goods that must be crated, optional goods, consignments, loose cartons."""
    rnd = random.Random(seed)
    packer = bp.Packer()
    for h in heights:
        packer.add_bin_type(bp.Bin(f"container {h}", 2350, h, 5900, max_weight=28000, cost=h))
    for g in ("", "C1"):
        for i in range(40):
            packer.add_item(bp.Item(f"{g}ball {i}", 300, 300, 300, shape="sphere", weight=2,
                                    crate_required=rnd.random() < 0.7, group=g))
        for i in range(25):
            packer.add_item(bp.Item(f"{g}cone {i}", 350, 500, 350, shape="cone", weight=1, group=g))
        for i in range(30):
            packer.add_item(bp.Item(f"{g}glass {i}", 400, 300, 300, weight=8, crate_required=True, group=g))
        for i in range(8):
            packer.add_item(bp.Item(f"{g}vase {i}", 250, 450, 250, weight=4, crate_required=True, upright=True,
                                    group=g))
        for i in range(15):
            packer.add_item(bp.Item(f"{g}carton {i}", 600, 400, 500, weight=12, group=g))
    packer.add_item(bp.Item("statue", 1500, 1500, 1500, weight=200, crate_required=True))  # fits no crate
    return packer


def crate_types():
    return [bp.CrateType("Crate L", outer=(1250, 1100, 1250), inner=(1200, 1000, 1200), tare_weight=40,
                         max_weight=800),
            bp.CrateType("Trunk", outer=(900, 700, 650), inner=(860, 640, 610), tare_weight=15, max_weight=300,
                         count=4, stackable=False),
            bp.LoadingCrate("Dolly", outer=(1250, 850), inner=(1200, 800), base_height=180, tare_weight=35,
                            max_weight=900, count=3)]


class TestPlansAreValid(unittest.TestCase):
    def test_handling_rules_for_every_fill_order_and_access(self):
        orders = list(bp.FillOrder.__members__.values())
        accesses = [bp.LoadingAccess.DOOR, bp.LoadingAccess.TOP, bp.LoadingAccess.LEFT_SIDE]
        for seed in range(6):
            packer = rules_packer(seed, orders[seed % len(orders)], accesses[seed % len(accesses)])
            with self.subTest(seed=seed):
                self.assertEqual(bp.validate(packer), [])

    def test_fleet(self):
        packer = bp.Packer(objective=bp.Objective.VALUE)
        packer.add_bin_type(bp.Bin("40ft", 2350, 2390, 12030, max_weight=26000, cost=3000), count=1)
        packer.add_bin_type(bp.Bin("Truck", 2450, 2600, 7200, max_weight=12000, cost=1400), count=2)
        packer.add_bin_type(bp.Bin("Van", 1700, 1700, 3000, max_weight=1500, cost=350))
        rnd = random.Random(1)
        for i in range(300):
            packer.add_item(bp.Item(f"c{i}", rnd.randint(300, 900), rnd.randint(200, 800), rnd.randint(300, 900),
                                    weight=rnd.randint(5, 80), value=rnd.randint(10, 200),
                                    group=rnd.choice(["", "", "G1", "G2"]), upright=rnd.random() < 0.3))
        packer.pack()
        self.assertEqual(bp.validate(packer), [])

    def test_bulk_loads(self):
        container = bp.Bin("c", 2350, 2390, 3000, max_weight=2000)
        for shape in SHAPES:
            for upright in (False, True):
                for weight in (0, 12):  # 12: the weight limit caps the count
                    item = bp.Item(shape, 400, 650 if shape != "sphere" else 400, 400, shape=shape,
                                   upright=upright, weight=weight)
                    plan = bp.pack_bulk(item, 500, [container])
                    with self.subTest(shape=shape, upright=upright, weight=weight):
                        self.assertEqual(bp.validate(plan), [])
                        if upright:
                            self.assertFalse(any(p.inverted for p in plan.get_items()))

    def test_crates_and_loading_crates(self):
        for heights, optional in (((2390,), True), ((2690, 2390), True), ((2390,), False)):
            plan = bp.pack_with_crates(crate_packer(heights), crate_types(), crate_optional=optional)
            with self.subTest(heights=heights, crate_optional=optional):
                self.assertEqual(bp.validate(plan), [])
                self.assertTrue(any(c.type.open_top for c in plan.crates))
                self.assertEqual([g.name for g in plan.unloaded_goods()], ["statue"])
                if not optional:
                    self.assertTrue(all(g.crate_required for c in plan.crates for g in c.contents))

    def test_this_side_up_goods_keep_their_crate_upright(self):
        packer = bp.Packer()
        packer.add_bin(bp.Bin("truck", 2400, 2400, 6000))
        for i in range(6):
            packer.add_item(bp.Item(f"vase {i}", 250, 450, 250, upright=True, crate_required=True))
        tippable = bp.CrateType("Box", outer=(900, 700, 650), inner=(860, 640, 610), upright=False)
        plan = bp.pack_with_crates(packer, [tippable])
        self.assertEqual(bp.validate(plan), [])


# ------------------------------------------------------------------ mutations --

def column_bin():
    """A valid hand-made plan: a stack of three cubes (a, b, c) and d beside them."""
    bin_ = bp.Bin("bin", 200, 300, 200, max_weight=100)
    items = {n: bp.Item(n, 100, 100, 100, weight=1) for n in "abcd"}
    for n, pos in zip("abcd", [(0, 0, 0), (0, 100, 0), (0, 200, 0), (100, 0, 0)]):
        items[n].set_position(pos)
    bin_.items = list(items.values())
    return bin_, items


class TestValidatorCatches(unittest.TestCase):
    def test_placement_and_handling_rules(self):
        def mutate(rule):
            bin_, it = column_bin()
            order = list(it.values())
            if rule == "bounds":
                it["d"].set_position((150, 0, 0))
            elif rule == "overlap":
                it["d"].set_position((50, 0, 0))
            elif rule == "support":
                it["d"].set_position((100, 50, 0))
            elif rule == "rotation":
                it["d"].allowed_rotations = [bp.RotationType.whd]
                it["d"].set_rotation_type(bp.RotationType.hwd)
            elif rule == "upright":
                it["d"].upright = True
                it["d"].set_rotation_type(bp.RotationType.hwd)
            elif rule == "floor only":
                it["b"].bottom_load_only = True
            elif rule == "no stacking":
                it["a"].disable_stacking = True
            elif rule == "stacking height":
                it["a"].stuffing_height = 50
            elif rule == "stacking layers":
                it["a"].stuffing_layers = 1
            elif rule == "stacking weight":
                it["a"].stuffing_max_weight = 1.5
            elif rule == "loading order":
                order = [it["b"], it["a"], it["c"], it["d"]]
            elif rule == "bin weight":
                bin_.max_weight = 3
            elif rule == "crate":
                it["d"].crate_required = True
            bin_.items = order
            return checks(bp.validate_bin(bin_, 0.75, DOOR))

        self.assertEqual(mutate(None), set())
        for rule in ("bounds", "overlap", "support", "rotation", "upright", "floor only", "no stacking",
                     "stacking height", "stacking layers", "stacking weight", "loading order", "bin weight",
                     "crate"):
            with self.subTest(rule=rule):
                self.assertIn(rule, mutate(rule))

    def test_consignments_fleet_and_count(self):
        packer = bp.Packer()
        packer.add_bin_type(bp.Bin("Van", 100, 100, 100, cost=10), count=2)
        for i in range(12):
            packer.add_item(bp.Item(f"x{i}", 50, 50, 50, group="g" if i < 2 else ""))
        packer.pack()
        bins = packer.get_bins()
        self.assertEqual(len(bins), 2)
        self.assertEqual(bp.validate(packer), [])

        def plan(bins=bins, unfit=(), items=None, count=2):
            return SimpleNamespace(loading_access=DOOR, min_support_ratio=0.75, get_bins=lambda: bins,
                                   get_unfit_items=lambda: list(unfit),
                                   get_items=lambda: items if items is not None else packer.get_items(),
                                   get_bin_types=lambda: [SimpleNamespace(bin=bins[0], count=count)])

        # The consignment split over both vans.
        g0 = next(it for it in bins[0].get_items() if it.group != "g")
        g1 = next(it for it in bins[1].get_items() if it.group != "g")
        g0.group = g1.group = "split"
        self.assertIn("group", checks(bp.validate(plan())))
        g0.group = g1.group = ""
        # Part of a consignment left behind.
        left = bp.Item("g left", 50, 50, 50, group="g")
        self.assertIn("group", checks(bp.validate(plan(unfit=[left], items=packer.get_items() + [left]))))
        # More vans than available; an item neither loaded nor reported.
        self.assertIn("fleet", checks(bp.validate(plan(count=1))))
        self.assertIn("count", checks(bp.validate(plan(items=packer.get_items() + [left]))))

    def test_bulk_loads(self):
        container = bp.Bin("c", 2350, 2390, 3000, max_weight=5000)
        pyramid = bp.Item("pyramid", 700, 600, 700, shape="pyramid", weight=10)  # tip-up / tip-down rows

        def mutate(rule):
            plan = bp.pack_bulk(pyramid, 40, [container])  # the plan keeps its own limits
            c = plan.containers[0]
            p = c.items
            if rule == "overlap":
                x, y, z = p[0].position
                p[1].position = (x + 100, y, z)
            elif rule == "bounds":
                p[-1].position = (container.width - 100, 0, 0)
            elif rule == "upright":
                plan.product.upright = True
            elif rule == "tip down":  # "this side up", standing, but one piece on its tip
                plan.product.upright = True
                for piece in p:
                    piece.rotation_type, piece.inverted = bp.RotationType.whd, piece is p[0]
            elif rule == "rotation":
                plan.product.allowed_rotations = [bp.RotationType.whd]
                p[0].rotation_type = bp.RotationType.hwd
            elif rule == "product":
                other = bp.Item("cone", 400, 700, 400, shape="cone")
                p.append(bp.bulk.BulkPiece(other, "cone 1", bp.RotationType.whd, (0, 1700, 2500), False))
            elif rule == "bin weight":
                c.max_weight = 50
            elif rule == "count":
                p.pop()
            issues = bp.validate(plan)
            plan.product.upright, plan.product.allowed_rotations = False, bp.ALL_ROTATIONS
            if rule == "tip down":
                return {"tip down"} if any(i.check == "upright" and "tip" in i.detail for i in issues) else set()
            return checks(issues)

        self.assertEqual(mutate(None), set())
        self.assertTrue(any(p.inverted for p in bp.pack_bulk(pyramid, 40, [container]).get_items()))
        for rule in ("overlap", "bounds", "upright", "tip down", "rotation", "product", "bin weight", "count"):
            with self.subTest(rule=rule):
                self.assertIn(rule, mutate(rule))

    def test_crates(self):
        def crate_items(plan):
            return {plan.crate_of(it).name: it for b in plan.get_bins() for it in b.get_items()
                    if it.crate_index >= 0}

        def mutate(rule):
            plan = bp.pack_with_crates(crate_packer(), crate_types())
            balls = next(c for c in plan.crates if c.kind == "sphere")
            dolly = next(c for c in plan.crates if c.type.open_top)
            loaded = crate_items(plan)
            if rule == "crate contents":  # a cone in the crate of balls
                cone = bp.Item("cone", 350, 500, 350, shape="cone")
                balls.contents.append(bp.bulk.BulkPiece(cone, "cone", bp.RotationType.whd, (0, 0, 0), False))
            elif rule == "overlap":  # two balls pushed into each other
                x, y, z = balls.contents[0].position
                balls.contents[1].position = (x + 50, y, z)
            elif rule == "bounds":
                balls.contents[0].position = (balls.type.inner[0], 0, 0)
            elif rule == "upright":  # a "this side up" vase laid down inside its crate
                vase = next(g for c in plan.crates if c._bin is not None for g in c._bin.get_items() if g.upright)
                vase.set_rotation_type(bp.RotationType.hwd)
            elif rule == "crate weight":  # goods over the crate's limit
                balls.type.max_weight = 1
            elif rule == "crate size":
                loaded[balls.name].depth += 10
            elif rule == "crates":  # more trunks than in stock
                next(t for t in plan.crate_types if t.name == "Trunk").count = 0
            elif rule == "floor only":  # a loading crate off the floor
                loaded[dolly.name].bottom_load_only = False
            elif rule == "no stacking":  # something may go on a loading crate
                loaded[dolly.name].disable_stacking = False
            elif rule == "count":  # an item lost from a crate
                balls.contents.pop()
            return checks(bp.validate(plan))

        self.assertEqual(mutate(None), set())
        for rule in ("crate contents", "overlap", "bounds", "upright", "crate weight", "crate size", "crates",
                     "floor only", "no stacking", "count"):
            with self.subTest(rule=rule):
                self.assertIn(rule, mutate(rule))
        # The crate weighs its tare plus its goods; "this side up" goods keep their crate upright.
        plan = bp.pack_with_crates(crate_packer(), crate_types())
        vase_crate = next(c for c in plan.crates if any(getattr(g, "upright", False) for g in c.contents))
        item = crate_items(plan)[vase_crate.name]
        item.weight -= 5
        item.upright = False
        self.assertTrue({"crate weight", "upright"} <= checks(bp.validate(plan)))


if __name__ == "__main__":
    unittest.main()
