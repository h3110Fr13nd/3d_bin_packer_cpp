#pragma once

#include <vector>
#include <optional>
#include <functional>  // Include for std::reference_wrapper
#include "bin.h"
#include "item.h"

class Packer {
public:
    Packer();
    
    const std::vector<Bin>& getBins() const;
    const std::vector<Item>& getItems() const;
    const std::vector<Item>& getUnfitItems() const;

    void addBin(const Bin& bin);
    void addItem(const Item& item);
    std::optional<std::reference_wrapper<Bin>> findFittedBin(Item& item);
    std::optional<std::reference_wrapper<Bin>> getBiggerBinThan(const Bin& other_bin);
    void unfitItem(std::vector<Item*>& item_ptrs);
    std::vector<Item*> packToBin(Bin& bin, std::vector<Item*>& item_ptrs);
    void pack();
    
    // Public data members
    std::vector<Item> items;
    std::vector<Bin> bins;
    std::vector<Item> unfit_items;
    
private:
    // Check if item's stuffing constraints are satisfied in this position
    bool checkStuffingConstraints(const Bin& bin, const Item& item, const std::tuple<long, long, long>& position);
    
    // Check if placing this item would violate constraints of items below it
    bool wouldViolateExistingItemConstraints(const Bin& bin, const Item& new_item, const std::tuple<long, long, long>& new_position);
};
