#include "packer.h"
#include <algorithm> 
#include <iostream>
#include <vector>
#include <functional>
#include <map>

const std::tuple<long, long, long> START_POSITION = {0, 0, 0};

Packer::Packer() {}

const std::vector<Bin>& Packer::getBins() const {
    return bins;
}

const std::vector<Item>& Packer::getItems() const {
    return items;
}

const std::vector<Item>& Packer::getUnfitItems() const {
    return unfit_items;
}

void Packer::addBin(const Bin& bin) {
    bins.push_back(bin);
}

void Packer::addItem(const Item& item) {
    items.push_back(item);
}

// Helper function to check if stuffing constraints are satisfied
bool Packer::checkStuffingConstraints(const Bin& bin, const Item& item, const std::tuple<long, long, long>& position) {
    // If no stuffing requirements, always return true
    if (item.getStuffingLayers() <= 0 && item.getStuffingMaxWeight() <= 0 && item.getStuffingHeight() <= 0) {
        return true;
    }
    
    // Check stuffing height constraint
    if (item.getStuffingHeight() > 0) {
        long available_height = bin.getHeight() - std::get<1>(position) - item.getDimension()[1];
        if (available_height < item.getStuffingHeight()) {
            return false;
        }
    }
    
    // Check for items above that might violate stuffing constraints
    float total_weight_above = 0.0f;
    
    // Track items by their vertical position to count actual layers
    std::map<long, std::vector<const Item*>> height_layers;
    
    for (const auto& other_item : bin.getItems()) {
        // Skip comparing with itself
        if (&other_item.get() == &item) {
            continue;
        }
        
        const auto& other_pos = other_item.get().getPosition();
        const auto& other_dim = other_item.get().getDimension();
        
        // Check if the other item is directly above this one
        if (std::get<0>(other_pos) + other_dim[0] > std::get<0>(position) && 
            std::get<0>(other_pos) < std::get<0>(position) + item.getDimension()[0] &&
            std::get<2>(other_pos) + other_dim[2] > std::get<2>(position) && 
            std::get<2>(other_pos) < std::get<2>(position) + item.getDimension()[2] &&
            std::get<1>(other_pos) >= std::get<1>(position) + item.getDimension()[1]) {
            
            // Add item to its height layer
            long layer_height = std::get<1>(other_pos);
            height_layers[layer_height].push_back(&other_item.get());
            
            // Add to total weight regardless of layer
            total_weight_above += other_item.get().weight;
        }
    }
    
    // Count actual distinct layers (not just items)
    int layer_count = height_layers.size();
    
    // Check stuffing layer constraint
    if (item.getStuffingLayers() > 0 && layer_count > item.getStuffingLayers()) {
        return false;
    }
    
    // Check stuffing weight constraint
    if (item.getStuffingMaxWeight() > 0 && total_weight_above > item.getStuffingMaxWeight()) {
        return false;
    }
    
    return true;
}

// Helper function to check if this item would violate another item's constraints
bool Packer::wouldViolateExistingItemConstraints(const Bin& bin, const Item& new_item, const std::tuple<long, long, long>& new_position) {
    for (const auto& existing_item : bin.getItems()) {
        // Skip for self
        if (&existing_item.get() == &new_item) {
            continue;
        }
        
        // Skip items without stuffing constraints
        if (existing_item.get().getStuffingLayers() <= 0 && 
            existing_item.get().getStuffingMaxWeight() <= 0 && 
            existing_item.get().getStuffingHeight() <= 0) {
            continue;
        }
        
        const auto& existing_pos = existing_item.get().getPosition();
        const auto& existing_dim = existing_item.get().getDimension();
        const auto& new_dim = new_item.getDimension();
        
        // Check if new item is above existing item
        if (std::get<0>(new_position) + new_dim[0] > std::get<0>(existing_pos) && 
            std::get<0>(new_position) < std::get<0>(existing_pos) + existing_dim[0] &&
            std::get<2>(new_position) + new_dim[2] > std::get<2>(existing_pos) && 
            std::get<2>(new_position) < std::get<2>(existing_pos) + existing_dim[2] &&
            std::get<1>(new_position) >= std::get<1>(existing_pos) + existing_dim[1]) {
            
            // Count existing layers above this item
            int existing_layers = 0;
            float existing_weight = 0.0f;
            std::map<long, bool> layer_heights;
            
            for (const auto& other_item : bin.getItems()) {
                if (&other_item.get() == &existing_item.get() || &other_item.get() == &new_item) {
                    continue;
                }
                
                const auto& other_pos = other_item.get().getPosition();
                const auto& other_dim = other_item.get().getDimension();
                
                if (std::get<0>(other_pos) + other_dim[0] > std::get<0>(existing_pos) && 
                    std::get<0>(other_pos) < std::get<0>(existing_pos) + existing_dim[0] &&
                    std::get<2>(other_pos) + other_dim[2] > std::get<2>(existing_pos) && 
                    std::get<2>(other_pos) < std::get<2>(existing_pos) + existing_dim[2] &&
                    std::get<1>(other_pos) >= std::get<1>(existing_pos) + existing_dim[1]) {
                    
                    // Count layer by height
                    layer_heights[std::get<1>(other_pos)] = true;
                    existing_weight += other_item.get().weight;
                }
            }
            
            existing_layers = layer_heights.size();
            
            // Add new item to the layer count if it's at a new height
            if (layer_heights.find(std::get<1>(new_position)) == layer_heights.end()) {
                existing_layers++;
            }
            
            // Add new item's weight
            existing_weight += new_item.weight;
            
            // Check if this would violate the existing item's constraints
            if ((existing_item.get().getStuffingLayers() > 0 && existing_layers > existing_item.get().getStuffingLayers()) ||
                (existing_item.get().getStuffingMaxWeight() > 0 && existing_weight > existing_item.get().getStuffingMaxWeight())) {
                return true;
            }
        }
    }
    
    return false;
}

std::optional<std::reference_wrapper<Bin>> Packer::findFittedBin(Item& item) {
    for (auto& bin : bins) {
        if (!bin.putItem(item, START_POSITION)) {
            continue;
        }
        
        // Verify stuffing constraints
        if (!checkStuffingConstraints(bin, item, START_POSITION) || 
            wouldViolateExistingItemConstraints(bin, item, START_POSITION)) {
            // Remove the item if constraints aren't satisfied
            if (bin.getItems().size() == 1 && &bin.getItems()[0].get() == &item) {
                bin.setItems({});
            }
            continue;
        }
        
        if (bin.getItems().size() == 1 && &bin.getItems()[0].get() == &item) {
            bin.setItems({});
        }
        return std::ref(bin);
    }
    return std::nullopt;
}

std::optional<std::reference_wrapper<Bin>> Packer::getBiggerBinThan(const Bin& other_bin) {
    auto it = std::find_if(bins.begin(), bins.end(), [&other_bin](Bin& bin) {
        return bin.getVolume() > other_bin.getVolume();
    });
    if (it != bins.end()) {
        return std::ref(*it);
    }
    return std::nullopt;
}

void Packer::unfitItem(std::vector<Item*>& item_ptrs) {
    if (!item_ptrs.empty()) {
        unfit_items.push_back(*item_ptrs.front());
        item_ptrs.erase(item_ptrs.begin());
    }
}

std::vector<Item*> Packer::packToBin(Bin& bin, std::vector<Item*>& item_ptrs) {
    std::vector<Item*> unpacked;
    std::optional<std::reference_wrapper<Bin>> b2;
    
    if (!bin.putItem(*item_ptrs[0], START_POSITION) || 
        !checkStuffingConstraints(bin, *item_ptrs[0], START_POSITION) ||
        wouldViolateExistingItemConstraints(bin, *item_ptrs[0], START_POSITION)) {
        b2 = getBiggerBinThan(bin);
        if (b2) {
            return packToBin(b2->get(), item_ptrs);
        }
        return {item_ptrs.begin(), item_ptrs.end()};
    }
    
    for (size_t i = 1; i < item_ptrs.size(); ++i) {
        bool fitted = false;
        
        for (const auto& axis : {Axis::height, Axis::depth, Axis::width}) {
            if (fitted) break;
            for (const auto& item_b : bin.getItems()) {
                std::tuple<long, long, long> item_position;
                
                // Calculate position based on current axis and respect stuffing settings
                if (axis == Axis::width) {
                    item_position = {
                        std::get<0>(item_b.get().getPosition()) + item_b.get().getDimension()[0],
                        std::get<1>(item_b.get().getPosition()),
                        std::get<2>(item_b.get().getPosition())
                    };
                } else if (axis == Axis::depth) {
                    item_position = {
                        std::get<0>(item_b.get().getPosition()),
                        std::get<1>(item_b.get().getPosition()),
                        std::get<2>(item_b.get().getPosition()) + item_b.get().getDimension()[2]
                    };
                } else {
                    long height_offset = item_b.get().getDimension()[1];
                    
                    // Add stuffing height if needed
                    if (item_b.get().getStuffingHeight() > 0) {
                        height_offset += item_b.get().getStuffingHeight();
                    }
                    
                    item_position = {
                        std::get<0>(item_b.get().getPosition()),
                        std::get<1>(item_b.get().getPosition()) + height_offset,
                        std::get<2>(item_b.get().getPosition())
                    };
                }
                
                // First try to place the item
                if (bin.putItem(*item_ptrs[i], item_position)) {
                    // Then check if this placement violates any stuffing constraints
                    if (!checkStuffingConstraints(bin, *item_ptrs[i], item_position) ||
                        wouldViolateExistingItemConstraints(bin, *item_ptrs[i], item_position)) {
                        // Remove the item from bin if stuffing constraints are violated
                        bin.removeItem(*item_ptrs[i]);
                    } else {
                        // Keep the item placed if no constraints are violated
                        fitted = true;
                        break;
                    }
                }
            }
        }
        
        if (!fitted) {
            while (b2) {
                b2 = getBiggerBinThan(bin);
                if (b2) {
                    b2->get().addItem(*item_ptrs[i]);
                    std::vector<Item*> b2_item_ptrs;
                    for (auto& ref : b2->get().getItems()) {
                        b2_item_ptrs.push_back(&ref.get());
                    }
                    auto left = packToBin(b2->get(), b2_item_ptrs);
                    if (left.empty()) {
                        bin = b2->get();
                        fitted = true;
                        break;
                    }
                }
            }
            if (!fitted) {
                unpacked.push_back(item_ptrs[i]);
            }
        }
    }
    return unpacked;
}

void Packer::pack() {
    std::sort(bins.begin(), bins.end(), [](const Bin& a, const Bin& b) {
        return a.getVolume() < b.getVolume();
    });
    std::sort(items.begin(), items.end(), [](const Item& a, const Item& b) {
        return a.getVolume() > b.getVolume();
    });

    std::vector<Item*> item_ptrs;
    for (auto& itm : items) {
        item_ptrs.push_back(&itm);
    }

    while (!item_ptrs.empty()) {
        auto bin = findFittedBin(*item_ptrs[0]);
        if (!bin) {
            unfitItem(item_ptrs);
            continue;
        }
        auto unpacked_items = packToBin(bin->get(), item_ptrs);
        item_ptrs = unpacked_items;
    }
}
