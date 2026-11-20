// fleet_planner.h - internal: chooses which containers to use (variable-sized
// bin packing with costs and limited availability) on top of the bin planner.
#pragma once

#include <vector>

#include "bin_planner.h"

namespace binpack {

struct FleetType {
    const Bin* bin;  // template: size, weight limit, cost
    int available;   // how many may be used; < 0 = unlimited
};

struct FleetContainer {
    int type;
    BinPlan plan;
};

struct FleetPlan {
    std::vector<FleetContainer> containers;
    std::vector<Item*> rest;  // not shipped, in input order
};

// Ships as much as possible (by priority, then config.objective) in the
// cheapest fleet (config.fleet_goal), or - for Objective::Profit - maximises
// cargo value minus container cost.
FleetPlan planFleet(const std::vector<Item*>& items, const std::vector<FleetType>& types,
                    const PackingConfig& config);

}  // namespace binpack
