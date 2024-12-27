#include "packer.h"
#include "bin.h"
#include "item.h"
#include <iostream>
#include <vector>

void runTest(const std::string& testName, const std::vector<Bin>& bins, const std::vector<Item>& items, const std::function<bool(const Packer&)>& expectation) {
    Packer packer;
    for (const auto& bin : bins) {
        packer.addBin(bin);
    }
    for (const auto& item : items) {
        packer.addItem(item);
    }
    packer.pack();
    if (expectation(packer)) {
        std::cout << testName << ": PASSED" << std::endl;
    } else {
        std::cout << testName << ": FAILED" << std::endl;
    }
}

long main() {
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
            { Item("Item 1", 150, 50, 50, {RotationType::whd, RotationType::hwd}, "red") },
            [](const Packer& packer) { return packer.getBins()[0].getItems().size() == 1 && packer.getUnfitItems().empty(); }
        },
        {
            "Test three items fit into smaller bin after being rotated.",
            { Bin("1. Le petite box", 296, 296, 8), Bin("2. Le grande box", 2960, 2960, 80) },
            { Item("Item 1", 250, 250, 2, {RotationType::whd}, "red"), Item("Item 2", 250, 2, 250, {RotationType::whd}, "blue"), Item("Item 3", 2, 250, 250, {RotationType::whd}, "green") },
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

    for (const auto& [name, bins, items, expectation] : testDatas) {
        runTest(name, bins, items, expectation);
    }

    return 0;
}
