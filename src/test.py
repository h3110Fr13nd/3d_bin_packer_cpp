import random
import time
import unittest

import pybinding

R = pybinding.RotationType
UPRIGHT = {R.whd, R.dhw}


def overlap(a0, a1, b0, b1):
    return max(0, min(a1, b1) - max(a0, b0))


def boxes_of(bin_):
    """(x0, y0, z0, x1, y1, z1, item) for every packed item, in loading order."""
    result = []
    for item in bin_.get_items():
        (x, y, z), (w, h, d) = item.get_position(), item.get_dimension()
        result.append((x, y, z, x + w, y + h, z + d, item))
    return result


def items_above(boxes, k):
    x0, _, z0, x1, y1, z1, _ = boxes[k]
    return [b for j, b in enumerate(boxes)
            if j != k and b[1] >= y1 and overlap(x0, x1, b[0], b[3]) * overlap(z0, z1, b[2], b[5]) > 0]


def support_ratio(boxes, k):
    x0, y0, z0, x1, _, z1, _ = boxes[k]
    area = (x1 - x0) * (z1 - z0)
    if y0 == 0 or area == 0:
        return 1.0
    supported = sum(overlap(x0, x1, b[0], b[3]) * overlap(z0, z1, b[2], b[5]) for b in boxes if b[4] == y0)
    return supported / area


class TestLegacyScenarios(unittest.TestCase):
    """Original scenarios. Rotations now match each test's intent: these
    items can only fit once rotated."""

    def setUp(self):
        self.test_datas = [
            {
                "name": "Edge case that needs rotation.",
                "bins": [pybinding.Bin('Le grande box', 100, 100, 300)],
                "items": [pybinding.Item('Item 1', 150, 50, 50, pybinding.ALL_ROTATIONS, "red")],
                "expectation": lambda packer: len(packer.get_bins()[0].get_items()) == 1 and len(packer.get_unfit_items()) == 0,
            },
            {
                # "Rotation 3 and 0" are the original JS indices: 0 = WHD, 3 = DHW.
                "name": "Edge case with only rotation 3 and 0 enabled.",
                "bins": [pybinding.Bin('Le grande box', 100, 100, 300)],
                "items": [pybinding.Item('Item 1', 150, 50, 50, [R.whd, R.dhw], "red")],
                "expectation": lambda packer: len(packer.get_bins()[0].get_items()) == 1 and len(packer.get_unfit_items()) == 0,
            },
            {
                "name": "Test three items fit into smaller bin after being rotated.",
                "bins": [
                    pybinding.Bin("1. Le petite box", 296, 296, 8),
                    pybinding.Bin("2. Le grande box", 2960, 2960, 80),
                ],
                "items": [
                    pybinding.Item("Item 1", 250, 250, 2, pybinding.ALL_ROTATIONS, "red"),
                    pybinding.Item("Item 2", 250, 2, 250, pybinding.ALL_ROTATIONS, "red"),
                    pybinding.Item("Item 3", 2, 250, 250, pybinding.ALL_ROTATIONS, "red"),
                ],
                "expectation": lambda packer: (
                    packer.get_bins()[0].get_name() == '1. Le petite box' and
                    len(packer.get_bins()[0].get_items()) == 3 and
                    len(packer.get_bins()[1].get_items()) == 0 and
                    len(packer.get_unfit_items()) == 0
                ),
            },
            {
                "name": "Test three items fit into larger bin.",
                "bins": [
                    pybinding.Bin("1. Le petite box", 296, 296, 8),
                    pybinding.Bin("2. Le grande box", 2960, 2960, 80),
                ],
                "items": [
                    pybinding.Item("Item 1", 2500, 2500, 20, [R.whd], "red"),
                    pybinding.Item("Item 2", 2500, 2500, 20, [R.whd], "red"),
                    pybinding.Item("Item 3", 2500, 2500, 20, [R.whd], "red"),
                ],
                "expectation": lambda packer: (
                    packer.get_bins()[0].get_name() == '1. Le petite box' and
                    len(packer.get_bins()[0].get_items()) == 0 and
                    len(packer.get_bins()[1].get_items()) == 3 and
                    len(packer.get_unfit_items()) == 0
                ),
            },
            {
                "name": "Larger items are tried first; bin order is preserved.",
                "bins": [
                    pybinding.Bin("Small Bin", 50, 100, 100),
                    pybinding.Bin("Bigger Bin", 150, 100, 100),
                    pybinding.Bin("Small Bin", 50, 100, 100),
                ],
                "items": [
                    pybinding.Item("Item 1 Small", 50, 100, 100, [R.whd]),
                    pybinding.Item("Item 3 Small", 50, 100, 100, [R.whd]),
                    pybinding.Item("Item 3 Small", 50, 100, 100, [R.whd]),
                    pybinding.Item("Item 2 Big", 100, 100, 100, [R.whd]),
                ],
                "expectation": lambda packer: (
                    packer.get_bins()[1].get_name() == "Bigger Bin" and
                    len(packer.get_bins()[1].get_items()) == 2 and
                    len(packer.get_bins()[0].get_items()) == 1 and
                    len(packer.get_unfit_items()) == 0
                ),
            },
        ]

    def test_packer(self):
        for test_data in self.test_datas:
            with self.subTest(test_data["name"]):
                packer = pybinding.Packer()
                for bin_ in test_data["bins"]:
                    packer.add_bin(bin_)
                for item in test_data["items"]:
                    packer.add_item(item)
                packer.pack()
                self.assertTrue(test_data["expectation"](packer))


class TestFillOrder(unittest.TestCase):
    def pack_cubes(self, order, count=4):
        packer = pybinding.Packer(fill_order=order)
        packer.add_bin(pybinding.Bin("bin", 100, 100, 100))
        for i in range(count):
            packer.add_item(pybinding.Item(f"cube {i}", 50, 50, 50))
        packer.pack()
        self.assertEqual(len(packer.get_unfit_items()), 0)
        return boxes_of(packer.get_bins()[0])

    def test_bottom_first_covers_the_floor_before_stacking(self):
        boxes = self.pack_cubes(pybinding.FillOrder.BOTTOM_BACK_LEFT)
        self.assertTrue(all(b[1] == 0 for b in boxes))

    def test_back_first_builds_the_back_wall_first(self):
        boxes = self.pack_cubes(pybinding.FillOrder.BACK_BOTTOM_LEFT)
        self.assertTrue(all(b[2] == 0 for b in boxes))

    def test_left_first_fills_the_left_side_first(self):
        boxes = self.pack_cubes(pybinding.FillOrder.LEFT_BOTTOM_BACK)
        self.assertTrue(all(b[0] == 0 for b in boxes))

    def test_default_is_back_first(self):
        self.assertEqual(pybinding.Packer().fill_order, pybinding.FillOrder.BACK_BOTTOM_LEFT)

    def test_fill_order_can_be_changed_between_packs(self):
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("bin", 100, 100, 100))
        for i in range(4):
            packer.add_item(pybinding.Item(f"cube {i}", 50, 50, 50))
        packer.pack()
        self.assertTrue(all(b[2] == 0 for b in boxes_of(packer.get_bins()[0])))
        packer.fill_order = pybinding.FillOrder.BOTTOM_BACK_LEFT
        packer.pack()
        self.assertTrue(all(b[1] == 0 for b in boxes_of(packer.get_bins()[0])))
        self.assertEqual(len(packer.get_bins()[0].get_items()), 4)


class TestItemConstraints(unittest.TestCase):
    def test_upright_items_keep_their_height_vertical(self):
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("bin", 300, 200, 300))
        for i in range(6):
            packer.add_item(pybinding.Item(f"fridge {i}", 60, 180, 70, upright=True))
        packer.pack()
        for item in packer.get_bins()[0].get_items():
            self.assertIn(item.get_rotation_type(), UPRIGHT)
            self.assertEqual(item.get_dimension()[1], 180)

    def test_upright_item_that_only_fits_lying_down_is_unfit(self):
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("low bin", 300, 100, 300))
        packer.add_item(pybinding.Item("tall", 50, 150, 50, upright=True))
        packer.add_item(pybinding.Item("tall but rotatable", 50, 150, 50))
        packer.pack()
        self.assertEqual([i.name for i in packer.get_unfit_items()], ["tall"])

    def test_upright_is_combined_with_allowed_rotations(self):
        item = pybinding.Item("x", 1, 2, 3, allowed_rotations=[R.hwd, R.dhw], upright=True)
        self.assertEqual(item.get_effective_rotations(), [R.dhw])

    def test_bottom_load_only_items_stay_on_the_floor(self):
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("bin", 100, 100, 100))
        for i in range(8):
            packer.add_item(pybinding.Item(f"heavy {i}", 50, 50, 50, bottom_load_only=True))
        packer.pack()
        packed = boxes_of(packer.get_bins()[0])
        self.assertEqual(len(packed), 4)  # the floor holds 4; the rest may not be stacked
        self.assertTrue(all(b[1] == 0 for b in packed))
        self.assertEqual(len(packer.get_unfit_items()), 4)

    def test_bottom_load_only_items_get_floor_space_first(self):
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("bin", 100, 100, 100))
        for i in range(4):  # large regular items would otherwise take the floor
            packer.add_item(pybinding.Item(f"regular {i}", 50, 50, 50))
        for i in range(4):
            packer.add_item(pybinding.Item(f"floor {i}", 50, 40, 50, bottom_load_only=True))
        packer.pack()
        self.assertEqual(len(packer.get_unfit_items()), 0)
        for b in boxes_of(packer.get_bins()[0]):
            if b[6].bottom_load_only:
                self.assertEqual(b[1], 0)

    def test_nothing_is_stacked_on_non_stackable_items(self):
        packer = pybinding.Packer(non_stackable_on_top=False)
        packer.add_bin(pybinding.Bin("bin", 100, 100, 100))
        for i in range(4):
            packer.add_item(pybinding.Item(f"glass {i}", 50, 50, 50, disable_stacking=True))
        for i in range(4):
            packer.add_item(pybinding.Item(f"box {i}", 50, 50, 50))
        packer.pack()
        boxes = boxes_of(packer.get_bins()[0])
        for k, b in enumerate(boxes):
            if b[6].disable_stacking:
                self.assertEqual(items_above(boxes, k), [])

    def test_non_stackable_items_are_placed_on_top_of_the_load(self):
        packer = pybinding.Packer(fill_order=pybinding.FillOrder.BOTTOM_BACK_LEFT)
        packer.add_bin(pybinding.Bin("bin", 100, 100, 100))
        for i in range(4):
            packer.add_item(pybinding.Item(f"glass {i}", 50, 50, 50, disable_stacking=True))
        for i in range(4):
            packer.add_item(pybinding.Item(f"box {i}", 50, 50, 50))
        packer.pack()
        self.assertEqual(len(packer.get_unfit_items()), 0)
        for b in boxes_of(packer.get_bins()[0]):
            self.assertEqual(b[1], 50 if b[6].disable_stacking else 0, b[6].name)

    def test_non_stackable_items_go_on_top_even_with_free_floor(self):
        for order in pybinding.FillOrder.__members__.values():
            with self.subTest(order):
                packer = pybinding.Packer(fill_order=order)
                packer.add_bin(pybinding.Bin("bin", 100, 150, 100))  # headroom for any order
                packer.add_item(pybinding.Item("glass", 50, 50, 50, disable_stacking=True))
                packer.add_item(pybinding.Item("box 1", 50, 50, 50))
                packer.add_item(pybinding.Item("box 2", 50, 50, 50))
                packer.pack()
                glass = next(i for i in packer.get_bins()[0].get_items() if i.name == "glass")
                self.assertGreater(glass.get_position()[1], 0)  # on top of a box, not on the floor

    def test_height_constraint_also_prevents_stacking(self):
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("bin", 50, 100, 50))
        item = pybinding.Item("constrained", 50, 50, 50)
        item.set_height_constraint(True, 50)
        packer.add_item(item)
        packer.add_item(pybinding.Item("other", 50, 50, 50))
        packer.pack()
        # Both fit: the non-stackable item goes on top of the other one.
        positions = {i.name: tuple(i.get_position()) for i in packer.get_bins()[0].get_items()}
        self.assertEqual(positions, {"other": (0, 0, 0), "constrained": (0, 50, 0)})

        packer.non_stackable_on_top = False  # packed by size: it lands on the floor and blocks the column
        packer.pack()
        self.assertEqual(len(packer.get_bins()[0].get_items()), 1)
        self.assertEqual(len(packer.get_unfit_items()), 1)

    def test_stacking_limits(self):
        # max 1 layer on top, max 10 kg on top, at most 60 units of stacking height
        for kwargs, expected_packed in (({"stuffing_layers": 1}, 2),
                                        ({"stuffing_max_weight": 10.0}, 2),
                                        ({"stuffing_height": 60}, 2)):
            with self.subTest(kwargs):
                packer = pybinding.Packer()
                packer.add_bin(pybinding.Bin("column", 50, 200, 50))
                packer.add_item(pybinding.Item("base", 50, 50, 50, weight=1.0, **kwargs))
                for i in range(3):
                    packer.add_item(pybinding.Item(f"top {i}", 50, 40, 50, weight=8.0))
                packer.pack()
                self.assertEqual(len(packer.get_bins()[0].get_items()), expected_packed)

    def test_items_never_float(self):
        packer = pybinding.Packer(min_support_ratio=1.0)
        packer.add_bin(pybinding.Bin("bin", 1000, 1000, 1000))
        rnd = random.Random(7)
        for i in range(200):
            packer.add_item(pybinding.Item(f"i{i}", rnd.randint(50, 300), rnd.randint(50, 300), rnd.randint(50, 300)))
        packer.pack()
        boxes = boxes_of(packer.get_bins()[0])
        self.assertGreater(len(boxes), 20)
        for k in range(len(boxes)):
            self.assertAlmostEqual(support_ratio(boxes, k), 1.0)

    def test_support_ratio_is_validated(self):
        with self.assertRaises(ValueError):
            pybinding.Packer(min_support_ratio=1.5)
        packer = pybinding.Packer()
        with self.assertRaises(ValueError):
            packer.min_support_ratio = -0.1

    def test_negative_dimensions_are_rejected(self):
        packer = pybinding.Packer()
        with self.assertRaises(ValueError):
            packer.add_item(pybinding.Item("bad", -1, 10, 10))


class TestRandomizedInvariants(unittest.TestCase):
    """Every constraint holds on random mixed loads, for every fill order."""

    def test_random_loads(self):
        orders = list(pybinding.FillOrder.__members__.values())
        for seed in range(60):
            rnd = random.Random(seed)
            ratio = rnd.choice([0.0, 0.75, 1.0])
            packer = pybinding.Packer(fill_order=rnd.choice(orders), min_support_ratio=ratio,
                                      optimize=rnd.random() < 0.5)
            for b in range(rnd.randint(1, 2)):
                packer.add_bin(pybinding.Bin(f"B{b}", rnd.randint(80, 300), rnd.randint(80, 300),
                                             rnd.randint(80, 500), rnd.choice([0, 400])))
            types = [(rnd.randint(10, 100), rnd.randint(10, 100), rnd.randint(10, 100)) for _ in range(5)]
            for i in range(rnd.randint(5, 120)):
                w, h, d = rnd.choice(types)
                packer.add_item(pybinding.Item(
                    f"i{i}", w, h, d, weight=rnd.choice([0, 2, 10]),
                    bottom_load_only=rnd.random() < 0.1, disable_stacking=rnd.random() < 0.1,
                    upright=rnd.random() < 0.3, stuffing_layers=rnd.choice([0, 0, 1]),
                    stuffing_max_weight=rnd.choice([0, 0, 15])))
            packer.pack()
            with self.subTest(seed=seed):
                self.check(packer, ratio)

    def check(self, packer, ratio):
        names = []
        for bin_ in packer.get_bins():
            boxes = boxes_of(bin_)
            position = {id(b[6]): k for k, b in enumerate(boxes)}
            weight = 0.0
            for k, (x0, y0, z0, x1, y1, z1, item) in enumerate(boxes):
                names.append(item.name)
                weight += item.weight
                self.assertTrue(0 <= x0 and 0 <= y0 and 0 <= z0)
                self.assertTrue(x1 <= bin_.get_width() and y1 <= bin_.get_height() and z1 <= bin_.get_depth())
                for b in boxes[k + 1:]:
                    self.assertFalse(overlap(x0, x1, b[0], b[3]) and overlap(y0, y1, b[1], b[4]) and
                                     overlap(z0, z1, b[2], b[5]), f"{item.name} overlaps {b[6].name}")
                self.assertGreaterEqual(support_ratio(boxes, k), ratio - 1e-9)
                if item.upright:
                    self.assertIn(item.get_rotation_type(), UPRIGHT)
                if item.bottom_load_only:
                    self.assertEqual(y0, 0)
                above = items_above(boxes, k)
                if item.disable_stacking:
                    self.assertEqual(above, [])
                if item.stuffing_layers:
                    self.assertLessEqual(len({b[1] for b in above}), item.stuffing_layers)
                if item.stuffing_max_weight:
                    load = sum(b[6].weight * overlap(x0, x1, b[0], b[3]) * overlap(z0, z1, b[2], b[5]) /
                               ((b[3] - b[0]) * (b[5] - b[2])) for b in above)
                    self.assertLessEqual(load, item.stuffing_max_weight + 1e-3)
                # loading sequence: an item is listed after everything it rests on
                for b in boxes:
                    if b[4] == y0 and overlap(x0, x1, b[0], b[3]) and overlap(z0, z1, b[2], b[5]):
                        self.assertLess(position[id(b[6])], k)
            if bin_.max_weight > 0:
                self.assertLessEqual(weight, bin_.max_weight + 1e-3)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names) + len(packer.get_unfit_items()), len(packer.get_items()))


class TestLoadingSequence(unittest.TestCase):
    ACCESS = pybinding.LoadingAccess

    def random_packer(self, seed, access, order=None):
        rnd = random.Random(seed)
        packer = pybinding.Packer(loading_access=access,
                                  fill_order=order or rnd.choice(list(pybinding.FillOrder.__members__.values())))
        packer.add_bin(pybinding.Bin("bin", rnd.randint(300, 1200), rnd.randint(300, 1200), rnd.randint(500, 3000)))
        types = [(rnd.randint(50, 400), rnd.randint(50, 400), rnd.randint(50, 400)) for _ in range(6)]
        for i in range(rnd.randint(10, 120)):
            packer.add_item(pybinding.Item(f"i{i}", *rnd.choice(types)))
        packer.pack()
        return packer

    def test_sequence_is_feasible_for_every_access_side_and_fill_order(self):
        for access in self.ACCESS.__members__.values():
            for order in pybinding.FillOrder.__members__.values():
                for seed in range(4):
                    with self.subTest(access=access, order=order, seed=seed):
                        bin_ = self.random_packer(seed, access, order).get_bins()[0]
                        self.assertEqual(bin_.check_loading_sequence(access), [])

    def test_cannot_load_top_back_after_top_front(self):
        # Two stacks, back (z=0) and front (z=100); loading the front top box
        # before the back top box blocks the door path of the latter.
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("bin", 100, 200, 200))
        for i in range(4):
            packer.add_item(pybinding.Item(f"box {i}", 100, 100, 100))
        packer.pack()
        bin_ = packer.get_bins()[0]
        order = [(tuple(i.get_position())) for i in bin_.get_items()]
        self.assertEqual(order, [(0, 0, 0), (0, 100, 0), (0, 0, 100), (0, 100, 100)])
        items = bin_.get_items()
        bad = [items[0], items[2], items[3], items[1]]  # back-top loaded last
        bin_.set_items(bad)
        problems = bin_.check_loading_sequence(self.ACCESS.DOOR)
        self.assertEqual(len(problems), 1)
        self.assertIn("blocked", problems[0])
        self.assertEqual(bin_.check_loading_sequence(self.ACCESS.TOP), [])  # fine from above
        self.assertTrue(bin_.reorder_for_loading(self.ACCESS.DOOR))
        self.assertEqual(bin_.check_loading_sequence(self.ACCESS.DOOR), [])

    def test_reorder_for_another_access_side(self):
        packer = self.random_packer(3, self.ACCESS.DOOR)
        bin_ = packer.get_bins()[0]
        for access in (self.ACCESS.TOP, self.ACCESS.LEFT_SIDE, self.ACCESS.RIGHT_SIDE, self.ACCESS.DOOR):
            self.assertTrue(bin_.reorder_for_loading(access))
            self.assertEqual(bin_.check_loading_sequence(access), [])

    def test_door_order_goes_from_the_back_to_the_door(self):
        packer = pybinding.Packer(fill_order=pybinding.FillOrder.BOTTOM_BACK_LEFT)
        packer.add_bin(pybinding.Bin("bin", 100, 100, 300))
        for i in range(6):
            packer.add_item(pybinding.Item(f"box {i}", 100, 50, 100))
        packer.pack()
        depths = [i.get_position()[2] for i in packer.get_bins()[0].get_items()]
        self.assertEqual(depths, sorted(depths))


class TestObjectives(unittest.TestCase):
    def pack(self, objective, items, max_weight=0.0, size=(100, 100, 100)):
        packer = pybinding.Packer(objective=objective)
        packer.add_bin(pybinding.Bin("bin", *size, max_weight=max_weight))
        for item in items:
            packer.add_item(item)
        packer.pack()
        return packer.get_bins()[0]

    def test_value_objective_prefers_what_pays(self):
        def items():  # either the big cheap crate or the 4 valuable cartons fit
            return ([pybinding.Item("crate", 100, 100, 60, value=10.0)] +
                    [pybinding.Item(f"carton {i}", 50, 100, 50, value=20.0) for i in range(4)])
        by_volume = self.pack(pybinding.Objective.VOLUME, items())
        by_value = self.pack(pybinding.Objective.VALUE, items())
        # The crate is the most volume (nothing else fits beside it); the cartons pay 8x more.
        self.assertEqual({i.name for i in by_volume.get_items()}, {"crate"})
        self.assertEqual(sum(i.value for i in by_value.get_items()), 80.0)

    def test_weight_objective_fills_the_payload(self):
        def items():
            return ([pybinding.Item(f"feathers {i}", 50, 100, 50, weight=1.0) for i in range(4)] +
                    [pybinding.Item(f"steel {i}", 50, 50, 50, weight=30.0) for i in range(2)])
        # Both steel blocks + the one feather bag that still fits = 61 (by volume: 2 bags = 2).
        heavy = self.pack(pybinding.Objective.WEIGHT, items(), size=(100, 100, 50))
        self.assertEqual(heavy.get_total_weight(), 61.0)
        self.assertEqual(self.pack(pybinding.Objective.VOLUME, items(), size=(100, 100, 50)).get_total_weight(), 2.0)

    def test_count_objective_loads_the_most_items(self):
        def items():
            return ([pybinding.Item("big", 100, 100, 100)] +
                    [pybinding.Item(f"small {i}", 50, 50, 50) for i in range(8)])
        self.assertEqual(len(self.pack(pybinding.Objective.COUNT, items()).get_items()), 8)
        self.assertEqual(len(self.pack(pybinding.Objective.VOLUME, items()).get_items()), 1)

    def test_weight_limit_does_not_waste_volume(self):
        # Dense items first would hit the weight limit with the bin half empty.
        items = ([pybinding.Item(f"dense {i}", 50, 100, 100, weight=50.0) for i in range(2)] +
                 [pybinding.Item(f"light {i}", 50, 100, 50, weight=1.0) for i in range(4)])
        bin_ = self.pack(pybinding.Objective.VOLUME, items, max_weight=60.0)
        self.assertAlmostEqual(bin_.get_utilization(), 1.0)

    def test_priority_beats_size(self):
        items = [pybinding.Item("big", 100, 100, 100), pybinding.Item("urgent", 100, 100, 60, priority=1)]
        bin_ = self.pack(pybinding.Objective.VOLUME, items)
        self.assertEqual([i.name for i in bin_.get_items()], ["urgent"])

    def test_priority_beats_value(self):
        items = [pybinding.Item("urgent", 100, 100, 100, value=1.0, priority=1),
                 pybinding.Item("lucrative", 100, 100, 100, value=1000.0)]
        bin_ = self.pack(pybinding.Objective.VALUE, items)
        self.assertEqual([i.name for i in bin_.get_items()], ["urgent"])


class TestGroups(unittest.TestCase):
    def test_groups_ship_complete_or_not_at_all(self):
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("bin", 100, 100, 100))
        for i in range(3):  # 3 of 4 slots; group B (2 items) can't be completed after A
            packer.add_item(pybinding.Item(f"A{i}", 50, 100, 50, group="A"))
        for i in range(2):
            packer.add_item(pybinding.Item(f"B{i}", 50, 100, 50, group="B"))
        packer.add_item(pybinding.Item("loose", 50, 100, 50))
        packer.pack()
        loaded = {i.name for i in packer.get_bins()[0].get_items()}
        self.assertEqual(loaded, {"A0", "A1", "A2", "loose"})
        reasons = {i.name: i.unfit_reason for i in packer.get_unfit_items()}
        self.assertEqual(set(reasons), {"B0", "B1"})
        self.assertEqual(reasons["B0"], "group could not be loaded completely into one bin")

    def test_dropped_group_is_retried_in_the_space_left(self):
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("bin", 100, 100, 100))
        for i in range(6):  # too big as a whole, gets dropped
            packer.add_item(pybinding.Item(f"big{i}", 50, 100, 50, group="big"))
        for i in range(2):
            packer.add_item(pybinding.Item(f"small{i}", 50, 50, 50, group="small"))
        packer.pack()
        loaded = {i.group for i in packer.get_bins()[0].get_items()}
        self.assertEqual(loaded, {"small"})
        self.assertEqual(len(packer.get_unfit_items()), 6)

    def test_groups_left_partial_are_retried_whole(self):
        # Interleaved consignments: A1 B1 C1 A2 fill the 4 slots, so B and C are
        # partial and get dropped; the retry puts B back in the 2 free slots.
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("bin", 100, 100, 100))
        for name in ("A1", "B1", "C1", "A2", "B2", "C2"):
            packer.add_item(pybinding.Item(name, 50, 100, 50, group=name[0]))
        packer.pack()
        self.assertEqual(sorted(i.name for i in packer.get_bins()[0].get_items()), ["A1", "A2", "B1", "B2"])
        self.assertEqual(sorted(i.name for i in packer.get_unfit_items()), ["C1", "C2"])

    def test_group_goes_to_one_bin(self):
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("small", 100, 100, 100))
        packer.add_bin(pybinding.Bin("large", 100, 100, 300))
        for i in range(8):
            packer.add_item(pybinding.Item(f"g{i}", 50, 100, 50, group="g"))
        packer.pack()
        self.assertEqual(len(packer.get_bins()[0].get_items()), 0)
        self.assertEqual(len(packer.get_bins()[1].get_items()), 8)


class TestFleet(unittest.TestCase):
    """Choosing which containers to book (add_bin_type)."""

    @staticmethod
    def cubes(packer, n, **kwargs):
        for i in range(n):
            packer.add_item(pybinding.Item(f"cube {i}", 50, 50, 50, **kwargs))

    @staticmethod
    def used(packer):
        return sorted(b.get_name() for b in packer.get_bins() if b.get_items())

    def test_fewest_containers_of_one_type(self):
        packer = pybinding.Packer()
        packer.add_bin_type(pybinding.Bin("Box", 100, 100, 100))  # 8 cubes each, unlimited
        self.cubes(packer, 100)
        packer.pack()
        bins = packer.get_bins()
        self.assertEqual(len(bins), 13)
        self.assertEqual(sorted(len(b.get_items()) for b in bins)[1:], [8] * 12)
        self.assertEqual({b.type_index for b in bins}, {0})
        self.assertIn("Box #13", [b.get_name() for b in bins])
        self.assertEqual(len(packer.get_unfit_items()), 0)

    def test_cheapest_mix_of_types(self):
        packer = pybinding.Packer()
        packer.add_bin_type(pybinding.Bin("Big", 100, 100, 100, cost=1000))   # 8 cubes
        packer.add_bin_type(pybinding.Bin("Small", 100, 50, 50, cost=300))    # 2 cubes
        self.cubes(packer, 10)  # Big+Small 1300 < 5 Small 1500 < 2 Big 2000
        packer.pack()
        self.assertEqual(self.used(packer), ["Big #1", "Small #1"])
        self.assertEqual(packer.get_total_cost(), 1300)

    def test_cost_versus_count_goal(self):
        def plan(goal):
            packer = pybinding.Packer(fleet_goal=goal)
            packer.add_bin_type(pybinding.Bin("Big", 100, 100, 100, cost=1000))
            packer.add_bin_type(pybinding.Bin("Small", 100, 50, 50, cost=100))
            self.cubes(packer, 8)
            packer.pack()
            return self.used(packer), packer.get_total_cost()
        self.assertEqual(plan(pybinding.FleetGoal.MIN_COST), (["Small #1", "Small #2", "Small #3", "Small #4"], 400))
        self.assertEqual(plan(pybinding.FleetGoal.MIN_COUNT), (["Big #1"], 1000))

    def test_without_costs_the_fewest_containers_win(self):
        packer = pybinding.Packer()
        packer.add_bin_type(pybinding.Bin("Big", 100, 100, 100))
        packer.add_bin_type(pybinding.Bin("Small", 100, 50, 50))
        self.cubes(packer, 8)
        packer.pack()
        self.assertEqual(self.used(packer), ["Big #1"])

    def test_limited_availability(self):
        packer = pybinding.Packer()
        packer.add_bin_type(pybinding.Bin("Big", 100, 100, 100, cost=1000), count=1)
        packer.add_bin_type(pybinding.Bin("Small", 100, 50, 50, cost=300), count=2)
        self.cubes(packer, 14)
        packer.pack()
        self.assertEqual(self.used(packer), ["Big #1", "Small #1", "Small #2"])
        self.assertEqual(len(packer.get_unfit_items()), 2)
        self.assertEqual({i.unfit_reason for i in packer.get_unfit_items()},
                         {"no container left: all available containers are in use"})
        types = packer.get_bin_types()
        self.assertEqual([(t.bin.get_name(), t.count) for t in types], [("Big", 1), ("Small", 2)])

    def test_unlimited_is_none(self):
        packer = pybinding.Packer()
        packer.add_bin_type(pybinding.Bin("Truck", 10, 10, 10))
        packer.add_bin_type(pybinding.Bin("Van", 10, 10, 10), count=pybinding.UNLIMITED)
        self.assertEqual([t.count for t in packer.get_bin_types()], [None, None])
        with self.assertRaises(ValueError):
            packer.add_bin_type(pybinding.Bin("Bad", 10, 10, 10), count=-5)

    def test_profit_only_books_containers_that_pay(self):
        packer = pybinding.Packer(objective=pybinding.Objective.PROFIT)
        packer.add_bin_type(pybinding.Bin("Box", 100, 100, 100, cost=100))
        self.cubes(packer, 8, value=30.0)                  # one box: 240 - 100 > 0
        for i in range(8):                                 # a second box: 40 < 100
            packer.add_item(pybinding.Item(f"cheap {i}", 50, 50, 50, value=5.0))
        packer.pack()
        self.assertEqual(self.used(packer), ["Box #1"])
        self.assertTrue(all(i.name.startswith("cube") for i in packer.get_bins()[0].get_items()))
        self.assertEqual({i.unfit_reason for i in packer.get_unfit_items()},
                         {"not profitable: worth less than the container it needs"})

    def test_explicit_bins_are_filled_first(self):
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("Own truck", 100, 100, 100))
        packer.add_bin_type(pybinding.Bin("Hired", 100, 100, 100, cost=500))
        self.cubes(packer, 12)
        packer.pack()
        self.assertEqual([(b.get_name(), len(b.get_items()), b.type_index) for b in packer.get_bins()],
                         [("Own truck", 8, -1), ("Hired #1", 4, 0)])
        self.assertEqual(packer.get_total_cost(), 500)

    def test_repacking_replaces_the_fleet(self):
        packer = pybinding.Packer()
        packer.add_bin_type(pybinding.Bin("Box", 100, 100, 100))
        self.cubes(packer, 20)
        packer.pack()
        packer.pack()
        self.assertEqual(len(packer.get_bins()), 3)
        self.assertEqual(sum(len(b.get_items()) for b in packer.get_bins()), 20)

    def test_groups_are_never_split_across_containers(self):
        packer = pybinding.Packer()
        packer.add_bin_type(pybinding.Bin("Box", 100, 100, 100))
        for g in range(5):  # groups of 3 cubes: at most 2 groups per box
            for k in range(3):
                packer.add_item(pybinding.Item(f"g{g}-{k}", 50, 50, 50, group=f"g{g}"))
        packer.pack()
        where = {}
        for b in packer.get_bins():
            for it in b.get_items():
                where.setdefault(it.group, set()).add(b.get_name())
        self.assertEqual(len(where), 5)
        self.assertTrue(all(len(bins) == 1 for bins in where.values()))
        self.assertEqual(len(packer.get_bins()), 3)

    def test_group_with_an_unshippable_item_stays_home(self):
        packer = pybinding.Packer()
        packer.add_bin_type(pybinding.Bin("Low", 200, 100, 200))
        packer.add_item(pybinding.Item("tall", 50, 150, 50, upright=True, group="g"))  # fits no container
        for i in range(3):
            packer.add_item(pybinding.Item(f"ok {i}", 50, 50, 50, group="g"))
        packer.add_item(pybinding.Item("other", 50, 50, 50))
        packer.pack()
        self.assertEqual([i.name for b in packer.get_bins() for i in b.get_items()], ["other"])
        reasons = {i.name: i.unfit_reason for i in packer.get_unfit_items()}
        self.assertEqual(reasons["tall"], "too large for every bin")
        self.assertEqual(reasons["ok 0"], "group could not be loaded completely into one bin")

    def test_matches_brute_force_on_small_instances(self):
        import itertools
        for seed in range(6):
            rnd = random.Random(seed)
            types = [("Big", (200, 200, 400), rnd.choice([900, 1200])), ("Mid", (200, 200, 250), rnd.choice([500, 700])),
                     ("Small", (150, 150, 200), rnd.choice([200, 300]))]
            kinds = [(rnd.randint(40, 120), rnd.randint(40, 120), rnd.randint(40, 120)) for _ in range(2)]
            items = [rnd.choice(kinds) for _ in range(rnd.randint(8, 30))]
            packer = pybinding.Packer()
            for name, dims, cost in types:
                packer.add_bin_type(pybinding.Bin(name, *dims, cost=cost))
            for k, dims in enumerate(items):
                packer.add_item(pybinding.Item(f"i{k}", *dims))
            packer.pack()
            best = None
            for n in range(1, 5):
                for combo in itertools.combinations_with_replacement(range(3), n):
                    cost = sum(types[t][2] for t in combo)
                    if best is not None and cost >= best:
                        continue
                    trial = pybinding.Packer()
                    for t in combo:
                        trial.add_bin(pybinding.Bin(types[t][0], *types[t][1]))
                    for k, dims in enumerate(items):
                        trial.add_item(pybinding.Item(f"i{k}", *dims))
                    trial.pack()
                    if not trial.get_unfit_items():
                        best = cost
            with self.subTest(seed=seed):
                self.assertEqual(len(packer.get_unfit_items()), 0)
                self.assertLessEqual(packer.get_total_cost(), best)


class TestUnfitReasons(unittest.TestCase):
    def test_reasons(self):
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("bin", 100, 100, 100, max_weight=50.0))
        packer.add_item(pybinding.Item("huge", 200, 10, 10))
        packer.add_item(pybinding.Item("lead", 10, 10, 10, weight=80.0))
        packer.add_item(pybinding.Item("no rotation", 10, 10, 10, allowed_rotations=[R.hwd], upright=True))
        packer.add_item(pybinding.Item("filler", 100, 100, 100, weight=1.0))
        packer.add_item(pybinding.Item("late", 10, 10, 10))
        packer.pack()
        reasons = {i.name: i.unfit_reason for i in packer.get_unfit_items()}
        self.assertEqual(reasons["huge"], "too large for every bin")
        self.assertIn("heavier", reasons["lead"])
        self.assertIn("no allowed rotation", reasons["no rotation"])
        self.assertEqual(reasons["late"], "no space left")
        self.assertNotIn("filler", reasons)


class TestApi(unittest.TestCase):
    def test_legacy_positional_constructors(self):
        self.assertEqual(pybinding.Item("a", 1, 2, 3).get_allowed_rotations(), pybinding.ALL_ROTATIONS)
        self.assertEqual(pybinding.Item("a", 1, 2, 3, "red").color, "red")
        self.assertEqual(pybinding.Item("a", 1, 2, 3, [R.whd], "red", 5.0).weight, 5.0)
        item = pybinding.Item("a", 1, 2, 3, [R.whd], "red", 1.0, 2, 3.0, 4, True, True)
        self.assertEqual((item.stuffing_layers, item.stuffing_max_weight, item.stuffing_height), (2, 3.0, 4))
        self.assertTrue(item.is_bottom_load_only() and item.is_disable_stacking())

    def test_keyword_constructor_and_properties(self):
        item = pybinding.Item("a", 1, 2, 3, weight=2.5, upright=True, disable_stacking=True)
        self.assertTrue(item.upright and item.is_upright() and item.disable_stacking)
        self.assertFalse(item.bottom_load_only)
        item.bottom_load_only = True
        self.assertTrue(item.is_bottom_load_only())

    def test_pack_is_repeatable_and_keeps_item_order(self):
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("bin", 100, 100, 100))
        names = [f"i{i}" for i in range(10)]
        for i, name in enumerate(names):
            packer.add_item(pybinding.Item(name, 20 + i * 3, 30, 40))
        packer.pack()
        first = [(i.name, tuple(i.get_position())) for i in packer.get_bins()[0].get_items()]
        packer.pack()
        second = [(i.name, tuple(i.get_position())) for i in packer.get_bins()[0].get_items()]
        self.assertEqual(first, second)
        self.assertEqual([i.name for i in packer.get_items()], names)

    def test_bin_statistics(self):
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("bin", 100, 100, 100))
        for i in range(2):
            packer.add_item(pybinding.Item(f"i{i}", 50, 100, 100, weight=3.0))
        packer.pack()
        bin_ = packer.get_bins()[0]
        self.assertAlmostEqual(bin_.get_utilization(), 1.0)
        self.assertEqual(bin_.get_packed_volume(), 1000000)
        self.assertAlmostEqual(bin_.get_total_weight(), 6.0)

    def test_bins_stay_valid_after_the_packer_is_gone(self):
        def make():
            packer = pybinding.Packer()
            packer.add_bin(pybinding.Bin("bin", 100, 100, 100))
            for i in range(20):
                packer.add_item(pybinding.Item(f"item {i}", 50, 50, 25))
            packer.pack()
            return packer.get_bins()[0]
        bin_ = make()
        import gc
        gc.collect()
        self.assertEqual(sorted(i.name for i in bin_.get_items()), sorted(f"item {i}" for i in range(16)))

    def test_items_stay_valid_after_the_packer_is_gone(self):
        import gc
        import weakref
        def make():
            packer = pybinding.Packer()
            packer.add_bin(pybinding.Bin("bin", 100, 100, 100))
            for i in range(20):
                packer.add_item(pybinding.Item(f"item {i}", 50, 50, 25))
            packer.pack()
            return packer.get_bins()[0].get_items(), weakref.ref(packer)
        items, packer_ref = make()
        gc.collect()
        self.assertIsNotNone(packer_ref())  # the items keep the packer (their owner) alive
        self.assertEqual(sorted(i.name for i in items), sorted(f"item {i}" for i in range(16)))
        del items
        gc.collect()
        self.assertIsNone(packer_ref())     # ... and no longer than that

    def test_bin_weight_limit(self):
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("bin", 100, 100, 100, max_weight=10.0))
        for i in range(5):
            packer.add_item(pybinding.Item(f"i{i}", 10, 10, 10, weight=3.0))
        packer.pack()
        self.assertEqual(len(packer.get_bins()[0].get_items()), 3)
        self.assertEqual(len(packer.get_unfit_items()), 2)


class TestPerformance(unittest.TestCase):
    def test_thousands_of_items_pack_quickly(self):
        packer = pybinding.Packer()
        packer.add_bin(pybinding.Bin("40ft HC", 2350, 2690, 12030))
        rnd = random.Random(3)
        types = [(rnd.randint(200, 800), rnd.randint(150, 600), rnd.randint(200, 700)) for _ in range(10)]
        for i in range(3000):
            packer.add_item(pybinding.Item(f"c{i}", *rnd.choice(types)))
        start = time.perf_counter()
        packer.pack()
        elapsed = time.perf_counter() - start
        self.assertGreater(packer.get_bins()[0].get_utilization(), 0.75)
        self.assertLess(elapsed, 5.0)


if __name__ == "__main__":
    unittest.main()
