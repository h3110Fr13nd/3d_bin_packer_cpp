// bin_planner.h - internal: plans the load of a single bin (not installed API).
#pragma once

#include <map>
#include <utility>
#include <vector>

#include "../src/bin.h"
#include "item.h"
#include "packing_config.h"
#include "packing_engine.h"

namespace binpack {

// Contribution of an item to the objective (value for Value and Profit).
double objectiveOf(const Item& item, Objective objective);

// Quality of a bin load: the objective per priority level (compared from the
// highest priority down), then packed volume as a tie-breaker.
struct Score {
    std::map<int, double, std::greater<int>> by_priority;
    double volume = 0.0;
    double weight = 0.0;
    double value = 0.0;
    int count = 0;

    void add(const Item& item, Objective objective);
    bool betterThan(const Score& other) const;
};

// Items already in a bin, with their placement.
using FixedItems = std::vector<std::pair<Item*, Placement>>;

// A planned bin load. Nothing is applied to the items until applyPlan().
struct BinPlan {
    std::vector<std::pair<Item*, Placement>> placed;  // fixed + new items, in loading order
    std::vector<Item*> rest;                          // did not fit, in the caller's order
    Score score;                                      // of the newly placed items
};

Placement placementOf(const Item& item);
FixedItems fixedItemsOf(const Bin& bin);

// Plans loading `sequence` into `bin` on top of `fixed` (kept in place). With
// `resequence`, strategies sort the items; otherwise the given order is kept.
BinPlan planBin(const Bin& bin, const FixedItems& fixed, const std::vector<Item*>& sequence,
                const PackingConfig& config, bool resequence);

// Writes the plan into the bin (item positions/rotations, bin.items in loading order).
void applyPlan(Bin& bin, const BinPlan& plan);

// Priority, constraint group, then biggest first.
void sortCanonical(std::vector<Item*>& items, const PackingConfig& config);

// Whether the item alone could go into an empty bin (size, rotation, weight).
bool fitsEmptyBin(const Item& item, const Bin& bin);

}  // namespace binpack
