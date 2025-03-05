#include "packer.h"
#include <algorithm> 
#include <iostream>
#include <vector>
#include <functional>
#include <map>
#include <chrono> // Add time-based early stopping

const std::tuple<long, long, long> START_POSITION = {0, 0, 0};

// Maximum time allowed for bin packing in milliseconds
const int MAX_PACK_TIME_MS = 30000;  // Increased to 30 seconds for complex packing problems

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

// Helper function to calculate overlap between items
float Packer::calculateItemOverlap(const std::tuple<long, long, long>& pos1, const std::vector<long>& dim1,
                                  const std::tuple<long, long, long>& pos2, const std::vector<long>& dim2) const {
    // Calculate overlap in X dimension
    float overlap_x = std::max(0.0f, 
        std::min(static_cast<float>(std::get<0>(pos1) + dim1[0]), 
                static_cast<float>(std::get<0>(pos2) + dim2[0])) - 
        std::max(static_cast<float>(std::get<0>(pos1)), 
                static_cast<float>(std::get<0>(pos2))));
    
    // Calculate overlap in Z dimension
    float overlap_z = std::max(0.0f, 
        std::min(static_cast<float>(std::get<2>(pos1) + dim1[2]), 
                static_cast<float>(std::get<2>(pos2) + dim2[2])) - 
        std::max(static_cast<float>(std::get<2>(pos1)), 
                static_cast<float>(std::get<2>(pos2))));
    
    // Return the overlap area
    return overlap_x * overlap_z;
}

// Helper function to check if an item is directly above another with significant overlap
bool Packer::isItemDirectlyAbove(const Item& bottom_item, const Item& top_item, float overlap_threshold) const {
    const auto& bottom_pos = bottom_item.getPosition();
    const auto& bottom_dim = bottom_item.getDimension();
    const auto& top_pos = top_item.getPosition();
    const auto& top_dim = top_item.getDimension();
    
    // Check if top item's bottom face is at or above the bottom item's top face
    if (std::get<1>(top_pos) < std::get<1>(bottom_pos) + bottom_dim[1]) {
        return false;
    }
    
    // Calculate overlap area
    float overlap_area = calculateItemOverlap(bottom_pos, bottom_dim, top_pos, top_dim);
    float bottom_area = static_cast<float>(bottom_dim[0] * bottom_dim[2]);
    
    // Return true if overlap exceeds threshold
    return overlap_area >= overlap_threshold * bottom_area;
}

// Helper function to check if stuffing constraints are satisfied
bool Packer::checkStuffingConstraints(const Bin& bin, const Item& item, const std::tuple<long, long, long>& position) {
    // Check if item is bottom-load-only and is not placed at the bottom
    if (item.isBottomLoadOnlyEnabled() && std::get<1>(position) > 0) {
        return false;  // Bottom-load-only item must be placed at y=0 (bottom)
    }

    // If no stuffing requirements, quickly return true
    if (item.getStuffingLayers() <= 0 && item.getStuffingMaxWeight() <= 0 && 
        item.getStuffingHeight() <= 0 && !item.isHeightConstrained() && !item.isDisableStackingEnabled()) {
        return true;
    }
    
    // Get item dimensions with current rotation
    const auto& item_dim = item.getDimension();
    float overlap_threshold = 0.5; // 50% overlap required to consider an item "above" another
    
    // Check height constraint for both stuffing height and direct height constraint
    long top_of_item = std::get<1>(position) + item_dim[1];
    
    // If height is constrained (isHeight=true) or disable_stacking is true, 
    // ensure nothing is stacked above this item
    if (item.isHeightConstrained() || item.isDisableStackingEnabled()) {
        for (const auto& other_item : bin.getItems()) {
            // Skip comparing with itself
            if (&other_item.get() == &item) {
                continue;
            }
            
            if (isItemDirectlyAbove(item, other_item.get(), 0.1f)) { // Even small overlap should prevent stacking
                // If item is height constrained or has disable_stacking, no items should be above it
                return false;
            }
        }
    }
    
    // Check stuffing height constraint - interpret as EXACT height allowed for stacking
    if (item.getStuffingHeight() > 0) {
        long max_allowed_height = top_of_item + item.getStuffingHeight();
        bool has_items_above = false;
        
        // Find all items above this one
        for (const auto& other_item : bin.getItems()) {
            // Skip comparing with itself
            if (&other_item.get() == &item) {
                continue;
            }
            
            const auto& other_pos = other_item.get().getPosition();
            const auto& other_dim = other_item.get().getDimension();
            
            // Only check items that could be above (quick vertical position check)
            if (std::get<1>(other_pos) < top_of_item) {
                continue;
            }
            
            // Check if item is above with significant overlap
            if (isItemDirectlyAbove(item, other_item.get(), overlap_threshold)) {
                has_items_above = true;
                // Check if any item would exceed the allowed height
                if (std::get<1>(other_pos) + other_dim[1] > max_allowed_height) {
                    return false;
                }
            }
        }
        
        // If height value is a specific constraint (not being used for placement logic),
        // then we require items to be exactly at that height (not empty space)
        if (item.getHeightConstraintType() == HeightConstraintType::EXACT && !has_items_above) {
            return false;
        }
    }
    
    // Check for items above that might violate stuffing layer constraints
    if (item.getStuffingLayers() > 0) {
        // Create a map to track layers by height position
        std::map<long, bool> layer_heights;
        
        for (const auto& other_item : bin.getItems()) {
            // Skip comparing with itself
            if (&other_item.get() == &item) {
                continue;
            }
            
            const auto& other_pos = other_item.get().getPosition();
            
            // Check if the other item is directly above this one
            if (isItemDirectlyAbove(item, other_item.get(), overlap_threshold)) {
                // Add this layer height to our map
                layer_heights[std::get<1>(other_pos)] = true;
            }
        }
        
        int layer_count = static_cast<int>(layer_heights.size());
        
        // Apply constraint based on constraint type
        if (item.getHeightConstraintType() == HeightConstraintType::EXACT) {
            // For items that require EXACTLY the specified number of layers
            if (layer_count != item.getStuffingLayers()) {
                // This is a problematic constraint - log it
                std::cout << "Rejecting item due to EXACT layer constraint: has " << layer_count 
                          << " layers but needs " << item.getStuffingLayers() << std::endl;
                return false; // Violated constraint - need exactly the specified number
            }
        } else {
            // For MAXIMUM type, don't exceed the specified layers
            if (layer_count > item.getStuffingLayers()) {
                std::cout << "Rejecting item due to MAX layer constraint: has " << layer_count 
                          << " layers but max is " << item.getStuffingLayers() << std::endl;
                return false; // Violated constraint - too many layers
            }
        }
    }
    
    // Check stuffing weight constraint
    if (item.getStuffingMaxWeight() > 0) {
        float total_weight_above = 0.0f;
        
        for (const auto& other_item : bin.getItems()) {
            // Skip comparing with itself
            if (&other_item.get() == &item) {
                continue;
            }
            
            // Check if item is directly above
            if (isItemDirectlyAbove(item, other_item.get(), overlap_threshold)) {
                total_weight_above += other_item.get().weight;
                
                // Early exit if weight is already exceeded
                if (total_weight_above > item.getStuffingMaxWeight()) {
                    return false;
                }
            }
        }
    }
    
    return true;
}

// Helper function to check if this item would violate another item's constraints
bool Packer::wouldViolateExistingItemConstraints(const Bin& bin, const Item& new_item, const std::tuple<long, long, long>& new_position) {
    const auto& new_dim = new_item.getDimension();
    float overlap_threshold = 0.5;

    for (const auto& existing_item : bin.getItems()) {
        // Skip for self
        if (&existing_item.get() == &new_item) {
            continue;
        }
        
        // Check if existing item is height constrained - no items can be stacked on it
        if (existing_item.get().isHeightConstrained()) {
            // Check if new item would be above existing item with any overlap
            const auto& existing_pos = existing_item.get().getPosition();
            const auto& existing_dim = existing_item.get().getDimension();
            
            // Calculate overlap area
            float area_overlap = calculateItemOverlap(existing_pos, existing_dim, new_position, new_dim);
            
            // If new item would be placed above a height-constrained item (with ANY overlap), return true
            if (std::get<1>(new_position) >= std::get<1>(existing_pos) + existing_dim[1] &&
                area_overlap > 0) {
                return true; // Cannot place items above height-constrained items
            }
        }
        
        // Check if existing item has disable_stacking enabled
        if (existing_item.get().isDisableStackingEnabled()) {
            // Check if new item would be above existing item with any overlap
            const auto& existing_pos = existing_item.get().getPosition();
            const auto& existing_dim = existing_item.get().getDimension();
            
            // Calculate overlap area
            float area_overlap = calculateItemOverlap(existing_pos, existing_dim, new_position, new_dim);
            
            // If new item would be placed above a disable-stacking item (with ANY overlap), return true
            if (std::get<1>(new_position) >= std::get<1>(existing_pos) + existing_dim[1] &&
                area_overlap > 0) {
                return true; // Cannot place items above disable-stacking items
            }
        }
        
        // Skip items without other stuffing constraints
        if (existing_item.get().getStuffingLayers() <= 0 && 
            existing_item.get().getStuffingMaxWeight() <= 0 && 
            existing_item.get().getStuffingHeight() <= 0) {
            continue;
        }
        
        const auto& existing_pos = existing_item.get().getPosition();
        const auto& existing_dim = existing_item.get().getDimension();
        
        // Check if new item would be above existing item (with overlap)
        // Calculate overlap area
        float area_overlap = calculateItemOverlap(existing_pos, existing_dim, new_position, new_dim);
        float area_existing = static_cast<float>(existing_dim[0] * existing_dim[2]);
        
        // If new item would be placed above an existing item
        if (std::get<1>(new_position) >= std::get<1>(existing_pos) + existing_dim[1] &&
            area_overlap >= overlap_threshold * area_existing) {
            
            // Check height constraint
            if (existing_item.get().getStuffingHeight() > 0) {
                long max_allowed_height = std::get<1>(existing_pos) + existing_dim[1] + 
                                         existing_item.get().getStuffingHeight();
                                         
                if (std::get<1>(new_position) + new_dim[1] > max_allowed_height) {
                    return true; // Exceeds allowed height
                }
            }
            
            // Check layers constraint - count existing layers plus the new one
            if (existing_item.get().getStuffingLayers() > 0) {
                std::map<long, bool> distinct_layers;
                
                // Count existing layers
                for (const auto& other_item : bin.getItems()) {
                    if (&other_item.get() == &existing_item.get() || 
                        &other_item.get() == &new_item) {
                        continue;
                    }
                    
                    // Check if directly above with significant overlap
                    if (isItemDirectlyAbove(existing_item.get(), other_item.get(), overlap_threshold)) {
                        distinct_layers[std::get<1>(other_item.get().getPosition())] = true;
                    }
                }
                
                // Add the new item's layer
                distinct_layers[std::get<1>(new_position)] = true;
                
                // Apply constraint based on constraint type
                if (existing_item.get().getHeightConstraintType() == HeightConstraintType::EXACT) {
                    if (static_cast<int>(distinct_layers.size()) != existing_item.get().getStuffingLayers()) {
                        return true; // Violates layers constraint - need exactly the specified number
                    }
                } else {
                    // For MAXIMUM type, don't exceed the specified layers
                    if (static_cast<int>(distinct_layers.size()) > existing_item.get().getStuffingLayers()) {
                        return true; // Violates constraint - too many layers
                    }
                }
            }
            
            // Check weight constraint
            if (existing_item.get().getStuffingMaxWeight() > 0) {
                float total_weight = 0.0f;
                
                // Sum weights of items above
                for (const auto& other_item : bin.getItems()) {
                    if (&other_item.get() == &existing_item.get() || 
                        &other_item.get() == &new_item) {
                        continue;
                    }
                    
                    // Check if directly above
                    if (isItemDirectlyAbove(existing_item.get(), other_item.get(), overlap_threshold)) {
                        total_weight += other_item.get().weight;
                    }
                }
                
                // Add new item's weight
                total_weight += new_item.weight;
                
                if (total_weight > existing_item.get().getStuffingMaxWeight()) {
                    return true; // Exceeds weight constraint
                }
            }
        }
    }
    
    return false;
}

std::optional<std::reference_wrapper<Bin>> Packer::findFittedBin(Item& item) {
    // Try to fit item in smallest bins first for better packing efficiency
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
    // Start timing
    auto start_time = std::chrono::high_resolution_clock::now();
    
    std::vector<Item*> unpacked;
    std::optional<std::reference_wrapper<Bin>> b2;
    
    // Try to place the first item
    if (!bin.putItem(*item_ptrs[0], START_POSITION) || 
        !checkStuffingConstraints(bin, *item_ptrs[0], START_POSITION) ||
        wouldViolateExistingItemConstraints(bin, *item_ptrs[0], START_POSITION)) {
        // If first item doesn't fit, try a bigger bin
        b2 = getBiggerBinThan(bin);
        if (b2) {
            return packToBin(b2->get(), item_ptrs);
        }
        return {item_ptrs.begin(), item_ptrs.end()};
    }
    
    // Optimization: Pre-calculate potential placement positions
    // This avoids redundant calculations in the inner loops
    struct PlacementPosition {
        std::tuple<long, long, long> position;
        Axis axis;
        std::reference_wrapper<Item> relative_to;
    };

    // For remaining items, try to place them efficiently
    for (size_t i = 1; i < item_ptrs.size(); ++i) {
        auto current_time = std::chrono::high_resolution_clock::now();
        auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            current_time - start_time).count();
            
        // Check time limit
        if (elapsed_ms > MAX_PACK_TIME_MS / 2) {  // Half the total time budget
            // Add remaining to unpacked
            unpacked.insert(unpacked.end(), item_ptrs.begin() + i, item_ptrs.end());
            break;
        }
    
        bool fitted = false;
        std::vector<PlacementPosition> positions;
        
        // Generate potential positions based on existing items
        for (const auto& item_b : bin.getItems()) {
            for (const auto& axis : {Axis::height, Axis::depth, Axis::width}) {
                std::tuple<long, long, long> item_position;
                
                // Calculate position based on current axis
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
                    item_position = {
                        std::get<0>(item_b.get().getPosition()),
                        std::get<1>(item_b.get().getPosition()) + item_b.get().getDimension()[1],
                        std::get<2>(item_b.get().getPosition())
                    };
                }
                
                positions.push_back({item_position, axis, item_b});
            }
        }
        
        // Sort positions by potential for efficient packing
        // This helps place items more compactly
        std::sort(positions.begin(), positions.end(), 
            [&bin](const PlacementPosition& a, const PlacementPosition& b) {
                // Prioritize positions closer to origin
                long a_dist = std::get<0>(a.position) + std::get<1>(a.position) + std::get<2>(a.position);
                long b_dist = std::get<0>(b.position) + std::get<1>(b.position) + std::get<2>(b.position);
                return a_dist < b_dist;
            });
        
        // Try each position
        for (const auto& pos : positions) {
            if (fitted) break;
            
            // Quickly check position constraints
            auto item_dim = item_ptrs[i]->getDimension();
            
            // Skip if exceeds bin dimensions
            if (std::get<0>(pos.position) + item_dim[0] > bin.getWidth() ||
                std::get<1>(pos.position) + item_dim[1] > bin.getHeight() ||
                std::get<2>(pos.position) + item_dim[2] > bin.getDepth()) {
                continue;
            }
            
            // Skip if weight limit would be exceeded
            float total_weight = 0.0f;
            for (const auto& existing_item : bin.getItems()) {
                total_weight += existing_item.get().weight;
            }
            if (bin.max_weight > 0 && total_weight + item_ptrs[i]->weight > bin.max_weight) {
                continue;
            }
            
            // Try to place item at this position
            if (bin.putItem(*item_ptrs[i], pos.position)) {
                // Verify constraints
                if (!checkStuffingConstraints(bin, *item_ptrs[i], pos.position) ||
                    wouldViolateExistingItemConstraints(bin, *item_ptrs[i], pos.position)) {
                    bin.removeItem(*item_ptrs[i]);
                } else {
                    fitted = true;
                    break;
                }
            }
        }
        
        // If item couldn't be placed, try next bigger bin or mark as unfit
        if (!fitted) {
            b2 = getBiggerBinThan(bin);
            if (b2) {
                // Create a named vector instead of a temporary one
                std::vector<Item*> remaining_items(item_ptrs.begin() + i, item_ptrs.end());
                auto left = packToBin(b2->get(), remaining_items);
                if (left.empty()) {
                    // Successfully placed in bigger bin
                    break;
                }
            }
            unpacked.push_back(item_ptrs[i]);
        }
    }
    
    return unpacked;
}

void Packer::pack() {
    // Start timing
    auto start_time = std::chrono::high_resolution_clock::now();

    // Sort bins by volume (smallest to largest)
    std::sort(bins.begin(), bins.end(), [](const Bin& a, const Bin& b) {
        return a.getVolume() < b.getVolume();
    });
    
    // Sort items by volume (largest to smallest) for better packing
    // And prioritize items with constraints
    std::sort(items.begin(), items.end(), [](const Item& a, const Item& b) {
        // Give highest priority to items with layer constraints
        bool a_has_layer_constraint = a.getStuffingLayers() > 0;
        bool b_has_layer_constraint = b.getStuffingLayers() > 0;
        
        if (a_has_layer_constraint && !b_has_layer_constraint)
            return true;
        if (!a_has_layer_constraint && b_has_layer_constraint)
            return false;
            
        // Then prioritize other constraints
        bool a_has_other_constraints = a.getStuffingMaxWeight() > 0 || 
                                     a.getStuffingHeight() > 0 ||
                                     a.isHeightConstrained();
                                     
        bool b_has_other_constraints = b.getStuffingMaxWeight() > 0 || 
                                     b.getStuffingHeight() > 0 ||
                                     b.isHeightConstrained();
        
        // If one has constraints and the other doesn't, prioritize the constrained one
        if (a_has_other_constraints && !b_has_other_constraints)
            return true;
        if (!a_has_other_constraints && b_has_other_constraints)
            return false;
        
        // Otherwise sort by volume as before
        return a.getVolume() > b.getVolume();
    });

    // Group similar items together to optimize placement decisions
    std::unordered_map<std::string, std::vector<Item*>> item_groups;
    std::vector<Item*> item_ptrs;
    for (auto& itm : items) {
        item_ptrs.push_back(&itm);
        
        // Create a unique key based on dimensions (ignoring position)
        std::string dim_key = std::to_string(itm.getWidth()) + "x" + 
                             std::to_string(itm.getHeight()) + "x" + 
                             std::to_string(itm.getDepth());
        item_groups[dim_key].push_back(&itm);
    }

    // Process items in batches for better efficiency
    std::vector<Item*> remaining_items = item_ptrs;
    std::vector<Item*> batch_items;

    while (!remaining_items.empty()) {
        auto current_time = std::chrono::high_resolution_clock::now();
        auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            current_time - start_time).count();
            
        // Check time limit
        if (elapsed_ms > MAX_PACK_TIME_MS) {
            // Just stop and return the best solution so far
            break;
        }
        
        // Take the next item (largest volume first)
        Item* current_item = remaining_items[0];
        batch_items.clear();
        batch_items.push_back(current_item);
        
        // Find similar items and group them
        std::string dim_key = std::to_string(current_item->getWidth()) + "x" + 
                            std::to_string(current_item->getHeight()) + "x" + 
                            std::to_string(current_item->getDepth());
        
        // Add similar items to this batch
        for (size_t i = 1; i < remaining_items.size() && batch_items.size() < 100; ++i) {
            std::string item_key = std::to_string(remaining_items[i]->getWidth()) + "x" + 
                                  std::to_string(remaining_items[i]->getHeight()) + "x" + 
                                  std::to_string(remaining_items[i]->getDepth());
                                  
            if (item_key == dim_key) {
                batch_items.push_back(remaining_items[i]);
            }
        }
        
        // Find a bin for this batch
        auto bin = findFittedBin(*batch_items[0]);
        if (!bin) {
            // No bin fits, mark as unfit
            unfitItem(remaining_items);
            continue;
        }
        
        // Pack this batch
        auto unpacked_items = packToBin(bin->get(), remaining_items);
        
        // Update remaining items
        remaining_items = unpacked_items;
    }
}
