// packing_config.h - user-facing knobs that control *how* a container is filled.
//
// Coordinate convention (used everywhere in the library):
//   origin (0, 0, 0) is the back-bottom-left corner of the bin,
//   x  = width  axis, grows to the right   ("left"   side is x = 0)
//   y  = height axis, grows upwards        ("bottom" side is y = 0, gravity points to -y)
//   z  = depth  axis, grows towards the door ("back" side is z = 0, the container nose)
#pragma once

#include <array>
#include <string>
#include "item.h"

// Which side of the bin is filled first, second and third.
//
// The packer always places an item at the feasible position that comes first
// in this order, e.g. BackBottomLeft prefers the smallest z, then the smallest y,
// then the smallest x. Two orders cover most needs:
//   * BackBottomLeft   - "back first" / wall building: complete walls from the
//                        container nose towards the door (how containers are
//                        loaded by hand or forklift). This is the default.
//   * BottomBackLeft   - "bottom first" / layer building: cover the whole floor,
//                        then build the next layer (pallets, top-loaded boxes).
enum class FillOrder {
    BottomBackLeft,
    BottomLeftBack,
    BackBottomLeft,
    BackLeftBottom,
    LeftBottomBack,
    LeftBackBottom,
};

// Axis indices (0 = x/left, 1 = y/bottom, 2 = z/back) from highest to lowest priority.
inline std::array<int, 3> fillOrderAxes(FillOrder order) {
    switch (order) {
        case FillOrder::BottomBackLeft: return {1, 2, 0};
        case FillOrder::BottomLeftBack: return {1, 0, 2};
        case FillOrder::BackBottomLeft: return {2, 1, 0};
        case FillOrder::BackLeftBottom: return {2, 0, 1};
        case FillOrder::LeftBottomBack: return {0, 1, 2};
        case FillOrder::LeftBackBottom: return {0, 2, 1};
    }
    return {2, 1, 0};
}

// Where the load is accessed from. A loading sequence is feasible when every
// item, at its turn, rests on items already loaded and can be moved in a
// straight line from the access side to its spot without passing through an
// item already loaded (e.g. you cannot put a box at the top-back once the
// top-front is filled when loading through the door).
enum class LoadingAccess {
    Door,       // rear doors at z = depth (containers, box trucks) - default
    Top,        // from above (open-top containers, pallets, cartons, cranes)
    LeftSide,   // side at x = 0   (curtain-siders)
    RightSide,  // side at x = width
    None,       // no access check: sequence only respects support
};

// What to maximise when not everything fits.
enum class Objective {
    Volume,  // cubic utilisation (default)
    Weight,  // payload, e.g. when freight is charged per kg
    Value,   // Item::value, e.g. freight revenue computed from a tariff
    Count,   // number of items
    Profit,  // Item::value minus the cost of the containers used (fleet planning)
};

// What the fleet planner minimises once the cargo is loaded (see Packer::addBinType).
enum class FleetGoal {
    Cost,   // total container cost, then number of containers
    Count,  // number of containers, then cost
};

struct PackingConfig {
    // Which side of the bin is filled first (see FillOrder).
    FillOrder fill_order = FillOrder::BackBottomLeft;

    // Fraction [0, 1] of an item's base area that must rest on the floor or on
    // the tops of other items. 1.0 = no overhang, 0.0 = items may float
    // (legacy behaviour).
    double min_support_ratio = 0.75;

    // Non-stackable items (disable_stacking / height constraint) are packed
    // after all other items and placed as high as possible, so they end up on
    // top of the load instead of wasting the space above them.
    bool non_stackable_on_top = true;

    // Try several placement heuristics per bin and keep the one that packs the
    // most volume (about 2x the work). All of them respect the fill order and
    // every constraint; false = single, fastest pass.
    bool optimize = true;

    // Side the bin is loaded from; decides the loading sequence (see LoadingAccess).
    LoadingAccess loading_access = LoadingAccess::Door;

    // What to maximise when not everything fits. Items with a higher
    // Item::priority always win over lower priorities; within a priority the
    // objective decides.
    Objective objective = Objective::Volume;

    // Fleet planning: minimise cost or number of containers (ignored for Profit,
    // which trades container cost against cargo value directly).
    FleetGoal fleet_goal = FleetGoal::Cost;
};
