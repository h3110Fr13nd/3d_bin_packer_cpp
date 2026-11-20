#include "packer.h"
#include "loading_sequence.h"
#include "bin.h"
#include "item.h"
#include <iostream>
#include <vector>

bool runTest(const std::string& testName, const std::vector<Bin>& bins, const std::vector<Item>& items, const std::function<bool(const Packer&)>& expectation) {
    Packer packer;
    for (const auto& bin : bins) {
        packer.addBin(bin);
    }
    for (const auto& item : items) {
        packer.addItem(item);
    }
    packer.pack();
    const bool ok = expectation(packer);
    std::cout << testName << ": " << (ok ? "PASSED" : "FAILED") << std::endl;
    return ok;
}

int main() {
    std::vector<std::tuple<std::string, std::vector<Bin>, std::vector<Item>, std::function<bool(const Packer&)>>> testDatas = {
        {
            "Edge case that needs rotation.",
            { Bin("Le grande box", 100, 100, 300) },
            { Item("Item 1", 150, 50, 50, {RotationType::whd, RotationType::hwd, RotationType::hdw, RotationType::dhw, RotationType::dwh, RotationType::wdh}, "red") },
            [](const Packer& packer) { return packer.getBins()[0].getItems().size() == 1 && packer.getUnfitItems().empty(); }
        },
        {
            "Edge case with only rotation 3 and 0 enabled.",
            { Bin("Le grande box", 100, 100, 300) },
            // "Rotation 3 and 0" are the original JS indices: 0 = WHD, 3 = DHW.
            { Item("Item 1", 150, 50, 50, {RotationType::whd, RotationType::dhw}, "red") },
            [](const Packer& packer) { return packer.getBins()[0].getItems().size() == 1 && packer.getUnfitItems().empty(); }
        },
        {
            "Test three items fit into smaller bin after being rotated.",
            { Bin("1. Le petite box", 296, 296, 8), Bin("2. Le grande box", 2960, 2960, 80) },
            // Items 2 and 3 only fit once rotated, so every rotation must be allowed.
            { Item("Item 1", 250, 250, 2, ALL_ROTATIONS, "red"), Item("Item 2", 250, 2, 250, ALL_ROTATIONS, "blue"), Item("Item 3", 2, 250, 250, ALL_ROTATIONS, "green") },
            [](const Packer& packer) {
                return packer.getBins()[0].getName() == "1. Le petite box" &&
                       packer.getBins()[0].getItems().size() == 3 &&
                       packer.getBins()[1].getItems().empty() &&
                       packer.getUnfitItems().empty();
            }
        },
        {
            "Test three items fit into larger bin.",
            { Bin("1. Le petite box", 296, 296, 8), Bin("2. Le grande box", 2960, 2960, 80) },
            { Item("Item 1", 2500, 2500, 20, {RotationType::whd}, "red"), Item("Item 2", 2500, 2500, 20, {RotationType::whd}, "blue"), Item("Item 3", 2500, 2500, 20, {RotationType::whd}, "green") },
            [](const Packer& packer) {
                return packer.getBins()[0].getName() == "1. Le petite box" &&
                       packer.getBins()[0].getItems().empty() &&
                       packer.getBins()[1].getItems().size() == 3 &&
                       packer.getUnfitItems().empty();
            }
        },
        {
            "1 bin with 7 items fit into.",
            { Bin("Bin 1", 220, 160, 100) },
            { Item("Item 1", 20, 100, 30, {RotationType::whd}, "red"), Item("Item 2", 100, 20, 30, {RotationType::whd}, "blue"), Item("Item 3", 20, 100, 30, {RotationType::whd}, "green"), Item("Item 4", 100, 20, 30, {RotationType::whd}, "yellow"), Item("Item 5", 100, 20, 30, {RotationType::whd}, "purple"), Item("Item 6", 100, 100, 30, {RotationType::whd}, "orange"), Item("Item 7", 100, 100, 30, {RotationType::whd}, "pink") },
            [](const Packer& packer) { return packer.getBins()[0].getItems().size() == 7 && packer.getUnfitItems().empty(); }
        },
        {
            "Big item is packed first.",
            { Bin("Bin 1", 100, 100, 100) },
            { Item("Item 1", 50, 100, 100, {RotationType::whd}, "red"), Item("Item 2", 100, 100, 100, {RotationType::whd}, "blue"), Item("Item 3", 50, 100, 100, {RotationType::whd}, "green") },
            [](const Packer& packer) { return packer.getBins()[0].getItems().size() == 1 && packer.getUnfitItems().size() == 2; }
        },
        {
            "Larger items are tried first.",
            { Bin("Small Bin", 50, 100, 100), Bin("Bigger Bin", 150, 100, 100), Bin("Small Bin", 50, 100, 100) },
            { Item("Item 1 Small", 50, 100, 100, {RotationType::whd}, "red"), Item("Item 3 Small", 50, 100, 100, {RotationType::whd}, "blue"), Item("Item 3 Small", 50, 100, 100, {RotationType::whd}, "green"), Item("Item 2 Big", 100, 100, 100, {RotationType::whd}, "yellow") },
            [](const Packer& packer) {
                return packer.getBins()[1].getName() == "Bigger Bin" &&
                       packer.getBins()[1].getItems().size() == 2 &&
                       packer.getBins()[0].getName() == "Small Bin" &&
                       packer.getBins()[0].getItems().size() == 1 &&
                       packer.getUnfitItems().empty();
            }
        },
        {
            "First item fits without rotation but needs to be rotated to fit all items.",
            { Bin("USPS Medium Flat Rate Box (Top Loading)", 11, 8.5, 5.5) },
            { Item("Item 1", 8.1, 5.2, 2.2, {RotationType::whd}, "red"), Item("Item 2", 8.1, 5.2, 3.3, {RotationType::whd}, "blue") },
            [](const Packer& packer) { return packer.getBins()[0].getItems().size() == 2 && packer.getUnfitItems().empty(); }
        },
        {
            "Floating point arithmetic is handled correctly.",
            { Bin("Bin 1", 12, 12, 5.5) },
            { Item("Item 1", 12, 12, 0.005, {RotationType::whd}, "red"), Item("Item 2", 12, 12, 0.005, {RotationType::whd}, "blue") },
            [](const Packer& packer) { return packer.getBins()[0].getItems().size() == 2 && packer.getUnfitItems().empty(); }
        }
    };

    int failures = 0;
    for (const auto& [name, bins, items, expectation] : testDatas) {
        failures += runTest(name, bins, items, expectation) ? 0 : 1;
    }

    // Fill order, orientation and stacking rules (PackingConfig + Item flags).
    auto check = [&failures](const std::string& name, bool ok) {
        std::cout << name << ": " << (ok ? "PASSED" : "FAILED") << std::endl;
        failures += ok ? 0 : 1;
    };
    for (FillOrder order : {FillOrder::BottomBackLeft, FillOrder::BackBottomLeft}) {
        PackingConfig config;
        config.fill_order = order;
        Packer packer(config);
        packer.addBin(Bin("Bin", 100, 100, 100));
        for (int i = 0; i < 4; ++i) packer.addItem(Item("Cube " + std::to_string(i), 50, 50, 50));
        packer.pack();
        const int axis = order == FillOrder::BottomBackLeft ? 1 : 2;
        bool ok = packer.getBins()[0].getItems().size() == 4;
        for (const auto& item : packer.getBins()[0].getItems()) {
            ok = ok && item.get().getPos()[axis] == 0;
        }
        check(order == FillOrder::BottomBackLeft ? "Bottom first fills the floor first."
                                                 : "Back first fills the back wall first.", ok);
    }
    {
        Packer packer;
        packer.addBin(Bin("Low bin", 300, 100, 300));
        packer.addItem(Item("Upright", 50, 150, 50, {}, "red", 0, 0, 0, 0, false, false, /*upright=*/true));
        packer.addItem(Item("Rotatable", 50, 150, 50));
        packer.pack();
        check("Upright item is never laid down.",
              packer.getUnfitItems().size() == 1 && packer.getUnfitItems()[0].getName() == "Upright");
    }
    {
        Packer packer;
        packer.addBin(Bin("Column", 50, 150, 50));
        packer.addItem(Item("Glass", 50, 50, 50, {}, "red", 0, 0, 0, 0, false, /*disable_stacking=*/true));
        packer.addItem(Item("Box 1", 50, 50, 50));
        packer.addItem(Item("Box 2", 50, 50, 50, {}, "blue", 0, 0, 0, 0, /*bottom_load_only=*/true));
        packer.pack();
        const auto& packed = packer.getBins()[0].getItems();
        check("Floor-only item at the bottom, non-stackable item on top.",
              packed.size() == 3 && packed[0].get().getName() == "Box 2" && packed[0].get().getPos()[1] == 0 &&
              packed[2].get().getName() == "Glass" && packed[2].get().getPos()[1] == 100);
    }

    {
        // Interlocking layout found by random search: no door-loading order
        // exists (each box is blocked by, or rests on, the next).
        const std::vector<std::array<int, 6>> cyclic = {
            {1, 0, 1, 5, 1, 5}, {3, 1, 3, 6, 4, 4}, {1, 1, 4, 5, 2, 6}, {1, 2, 2, 2, 3, 6},
            {1, 3, 0, 4, 6, 3}, {4, 1, 0, 6, 2, 2}, {2, 2, 5, 6, 4, 6}};
        std::vector<binpack::SequenceBox> boxes;
        for (const auto& c : cyclic) {
            boxes.push_back({{c[0] * 100, c[1] * 100, c[2] * 100}, {c[3] * 100, c[4] * 100, c[5] * 100}, false});
        }
        const auto plan = binpack::planLoadingSequence(boxes, LoadingAccess::Door, FillOrder::BackBottomLeft, 0.0);
        std::vector<binpack::SequenceBox> loaded;
        for (std::size_t k : plan.order) loaded.push_back(boxes[k]);
        check("Loading-order cycle is broken by removing a box.",
              plan.feasible && !plan.removed.empty() && plan.order.size() + plan.removed.size() == boxes.size() &&
              binpack::checkLoadingSequence(loaded, LoadingAccess::Door).empty());

        for (auto& box : boxes) box.fixed = true;  // pre-placed: may not be removed
        const auto stuck = binpack::planLoadingSequence(boxes, LoadingAccess::Door, FillOrder::BackBottomLeft, 0.0);
        check("Cycle of fixed boxes is reported as infeasible.",
              !stuck.feasible && stuck.removed.empty() && stuck.order.size() == boxes.size());
        const auto top = binpack::planLoadingSequence(boxes, LoadingAccess::Top, FillOrder::BackBottomLeft, 0.0);
        check("Same layout is loadable from the top.", top.feasible && top.removed.empty());
    }

    {
        // Fleet planning: 10 cubes, Big (8 cubes, 1000) or Small (2 cubes, 300): Big + Small is cheapest.
        Packer packer;
        packer.addBinType(Bin("Big", 100, 100, 100, 0, "", "", 0, 1000.0f));
        packer.addBinType(Bin("Small", 100, 50, 50, 0, "", "", 0, 300.0f), 3);
        for (int i = 0; i < 10; ++i) packer.addItem(Item("Cube " + std::to_string(i), 50, 50, 50));
        packer.pack();
        std::vector<std::string> names;
        for (const auto& bin : packer.getBins()) names.push_back(bin.getName());
        check("Fleet planner books the cheapest mix of containers.",
              names == std::vector<std::string>{"Big #1", "Small #1"} && packer.getTotalCost() == 1300.0f &&
              packer.getUnfitItems().empty());
    }

    {
        // Shapes are drawn only: a sphere packs exactly like a box of the same size, and keeps its shape.
        std::vector<std::tuple<std::string, long, long, long, Shape>> goods = {
            {"Ball", 50, 50, 50, Shape::Sphere}, {"Cone", 40, 70, 40, Shape::Cone},
            {"Drum", 60, 90, 60, Shape::Cylinder}, {"Pyramid", 70, 60, 70, Shape::Pyramid}};
        Packer shaped, plain;
        shaped.addBin(Bin("Bin", 150, 150, 150));
        plain.addBin(Bin("Bin", 150, 150, 150));
        for (int i = 0; i < 12; ++i) {
            const auto& [name, w, h, d, shape] = goods[i % goods.size()];
            shaped.addItem(Item(name, w, h, d, {}, "red", 0, 0, 0, 0, false, false, false, 0, 0, "", shape));
            plain.addItem(Item(name, w, h, d));
        }
        shaped.pack();
        plain.pack();
        const auto& a = shaped.getBins()[0].getItems();
        const auto& b = plain.getBins()[0].getItems();
        bool ok = a.size() == b.size() && !a.empty();
        for (std::size_t k = 0; ok && k < a.size(); ++k) {
            ok = a[k].get().getPos() == b[k].get().getPos() &&
                 a[k].get().getRotationType() == b[k].get().getRotationType() &&
                 b[k].get().shape == Shape::Box && a[k].get().shape != Shape::Box;
        }
        check("Shaped items are packed as their boxes and keep their shape.", ok);
    }
    {
        // Items that must travel in a crate are never loaded loose by the plain packer.
        Packer packer;
        packer.addBin(Bin("Bin", 100, 100, 100));
        packer.addItem(Item("Glass", 10, 10, 10, {}, "red", 0, 0, 0, 0, false, false, false, 0, 0, "", Shape::Box,
                            /*crate_required=*/true));
        packer.addItem(Item("Box", 10, 10, 10));
        packer.pack();
        check("Crate-only items are reported, not loaded loose.",
              packer.getBins()[0].getItems().size() == 1 && packer.getUnfitItems().size() == 1 &&
              packer.getUnfitItems()[0].getName() == "Glass" &&
              packer.getUnfitItems()[0].unfit_reason.find("crate") != std::string::npos);
    }

    return failures == 0 ? 0 : 1;
}
