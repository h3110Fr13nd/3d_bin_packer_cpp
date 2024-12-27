import unittest
import pybinding

class TestPybinding(unittest.TestCase):

    def setUp(self):
        self.test_datas = [
            {
                "name": "Edge case that needs rotation.",
                "bins": [
                    pybinding.Bin('Le grande box', 100, 100, 300),
                ],
                "items": [
                    pybinding.Item('Item 1', 150, 50, 50, [pybinding.RotationType.whd], "red"),
                ],
                "expectation": lambda packer: len(packer.get_bins()[0].get_items()) == 1 and len(packer.get_unfit_items()) == 0,
            },
            {
                "name": "Edge case with only rotation 3 and 0 enabled.",
                "bins": [
                    pybinding.Bin('Le grande box', 100, 100, 300),
                ],
                "items": [
                    pybinding.Item('Item 1', 150, 50, 50, [pybinding.RotationType.whd], "red"),
                ],
                "expectation": lambda packer: len(packer.get_bins()[0].get_items()) == 1 and len(packer.get_unfit_items()) == 0,
            },
            {
                "name": "Test three items fit into smaller bin after being rotated.",
                "bins": [
                    pybinding.Bin("1. Le petite box", 296, 296, 8),
                    pybinding.Bin("2. Le grande box", 2960, 2960, 80),
                ],
                "items": [
                    pybinding.Item("Item 1", 250, 250, 2, [pybinding.RotationType.whd], "red"),
                    pybinding.Item("Item 2", 250, 2, 250, [pybinding.RotationType.whd], "red"),
                    pybinding.Item("Item 3", 2, 250, 250, [pybinding.RotationType.whd], "red"),
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
                    pybinding.Item("Item 1", 2500, 2500, 20, [pybinding.RotationType.whd], "red"),
                    pybinding.Item("Item 2", 2500, 2500, 20, [pybinding.RotationType.whd], "red"),
                    pybinding.Item("Item 3", 2500, 2500, 20, [pybinding.RotationType.whd], "red"),
                ],
                "expectation": lambda packer: (
                    packer.get_bins()[0].get_name() == '1. Le petite box' and
                    len(packer.get_bins()[0].get_items()) == 0 and
                    len(packer.get_bins()[1].get_items()) == 3 and
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

if __name__ == "__main__":
    unittest.main()