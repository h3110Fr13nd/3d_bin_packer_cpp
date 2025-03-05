#ifndef INCLUDE_PACKER_H
#define INCLUDE_PACKER_H

#include <vector>
#include <optional>
#include <functional>  // Include for std::reference_wrapper
#include "../src/bin.h"
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
    // Helper function to calculate overlap between items - changed to use vector
    float calculateItemOverlap(const std::tuple<long, long, long>& pos1, const std::vector<long>& dim1,
                              const std::tuple<long, long, long>& pos2, const std::vector<long>& dim2) const;

    // Helper function to check if an item is directly above another with significant overlap
    bool isItemDirectlyAbove(const Item& bottom_item, const Item& top_item, float overlap_threshold) const;

    // Check if item's stuffing constraints are satisfied in this position
    bool checkStuffingConstraints(const Bin& bin, const Item& item, const std::tuple<long, long, long>& position);
    
    // Check if placing this item would violate constraints of items below it
    bool wouldViolateExistingItemConstraints(const Bin& bin, const Item& new_item, const std::tuple<long, long, long>& new_position);
};

#endif // INCLUDE_PACKER_H
