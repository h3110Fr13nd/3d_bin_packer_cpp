// packing_engine.h - geometric core of the packer (one instance per bin).
//
// The engine implements an Extreme-Point placement heuristic
// (Crainic, Perboli & Tadei, 2008) with gravity/support checks, per-item
// stacking rules and a configurable fill order.
//
// Performance notes:
//   * Placed boxes and extreme points are stored as structure-of-arrays of
//     32-bit integers so the hot loops (collision tests, ray casts, residual
//     space updates) are branch-free and auto-vectorised by the compiler.
//   * Every extreme point carries its "residual space" (free distance along
//     +x, +y, +z), which rejects most candidate placements in O(1) before any
//     O(n) collision test is run.
//   * Extreme points that can no longer host the smallest remaining item are
//     dropped, keeping the candidate list short in a filling container.
#pragma once

#include <array>
#include <cstdint>
#include <unordered_map>
#include <vector>

#include "item.h"
#include "packing_config.h"

namespace binpack {

using coord_t = std::int32_t;

// The properties of an item that matter for placement, resolved once.
struct ItemSpec {
    struct Orientation {
        RotationType rotation;
        std::array<coord_t, 3> dims;  // extents along x, y, z
    };

    std::vector<Orientation> orientations;  // distinct placed shapes only
    float weight = 0.0f;
    bool bottom_only = false;
    bool no_stack = false;
    coord_t max_stack_height = 0;  // 0 = unlimited (stuffing height above the item)
    float max_stack_weight = 0.0f; // 0 = unlimited
    int max_stack_layers = 0;      // 0 = unlimited

    static ItemSpec fromItem(const Item& item);
    bool hasStackingRules() const {
        return no_stack || max_stack_height > 0 || max_stack_weight > 0.0f || max_stack_layers > 0;
    }
    coord_t minDimension() const;
    bool operator==(const ItemSpec& other) const;
};

struct Placement {
    std::array<coord_t, 3> position;  // x, y, z of the back-bottom-left corner
    std::array<coord_t, 3> dims;      // extents along x, y, z
    RotationType rotation;
};

class ContainerEngine {
public:
    // flush_bonus > 0 rewards orientations whose far face is flush with an
    // existing face along the primary fill axis (even walls / layers).
    ContainerEngine(long width, long height, long depth, float max_weight, const PackingConfig& config,
                    double flush_bonus = 0.0);

    // Searches the best feasible placement for the item. Does not modify state.
    bool findPlacement(const ItemSpec& spec, Placement& out) const;

    // Records a placement (from findPlacement, or a pre-placed item).
    void commit(const ItemSpec& spec, const Placement& placement);

    // Hint: no remaining item has an extent smaller than this. Extreme points
    // with less free space are pruned on the next commit.
    void setMinItemDimension(coord_t value) { min_item_dim_ = value; }

    std::size_t boxCount() const { return weight_.size(); }
    std::size_t extremePointCount() const { return ep_[0].size(); }

private:
    struct StackRule {
        std::uint32_t box;
        bool no_stack;
        coord_t max_top;       // highest allowed top of anything above the box
        float max_load;        // 0 = unlimited
        int max_layers;        // 0 = unlimited
        float load = 0.0f;     // weight currently resting above the box
        std::vector<coord_t> levels;  // distinct bottom heights of boxes above
    };

    bool keyLess(const coord_t* a, const coord_t* b) const;
    bool feasible(std::size_t ep, const std::array<coord_t, 3>& d, const ItemSpec& spec) const;
    // Index of a placed box intersecting [lo, hi), or -1.
    std::int64_t findCollision(const std::array<coord_t, 3>& lo, const std::array<coord_t, 3>& hi) const;
    bool boxIntersects(std::uint32_t i, const std::array<coord_t, 3>& lo, const std::array<coord_t, 3>& hi) const;
    bool supported(const std::array<coord_t, 3>& lo, const std::array<coord_t, 3>& hi, std::uint32_t level) const;
    std::uint32_t levelId(coord_t y);  // id of the list of boxes whose top is at height y
    bool rulesBelowAllow(const std::array<coord_t, 3>& lo, const std::array<coord_t, 3>& hi, const ItemSpec& spec) const;
    bool ownRuleAllows(const std::array<coord_t, 3>& lo, const std::array<coord_t, 3>& hi, const ItemSpec& spec) const;
    double orientationScore(std::size_t ep, const std::array<coord_t, 3>& d) const;

    bool containsPoint(const std::array<coord_t, 3>& p) const;
    coord_t castRay(const std::array<coord_t, 3>& p, int axis) const;     // free distance along +axis
    coord_t projectBack(const std::array<coord_t, 3>& p, int axis) const; // nearest stop along -axis
    void updateExtremePoints(std::uint32_t box);

    // Bin.
    std::array<coord_t, 3> size_;
    float max_weight_;
    float total_weight_ = 0.0f;
    PackingConfig config_;
    std::array<int, 3> axes_;
    double flush_bonus_;
    coord_t min_item_dim_ = 0;

    // Placed boxes, structure-of-arrays: lo_[axis][i], hi_[axis][i].
    std::array<std::vector<coord_t>, 3> lo_;
    std::array<std::vector<coord_t>, 3> hi_;
    std::vector<float> weight_;
    // Boxes grouped by the height of their top ("levels"); extreme points keep
    // the id of their level so support checks need no lookup.
    std::unordered_map<coord_t, std::uint32_t> level_of_;
    std::vector<std::vector<std::uint32_t>> levels_;
    // How many boxes end at each coordinate of the primary fill axis
    // (wall fronts for back-first, layer tops for bottom-first).
    std::unordered_map<coord_t, std::uint32_t> primary_faces_;
    std::vector<StackRule> rules_;

    // Extreme points, sorted by fill order: ep_[axis][k] and residual space rs_[axis][k].
    std::array<std::vector<coord_t>, 3> ep_;
    std::array<std::vector<coord_t>, 3> rs_;
    // Per extreme point, the box that last blocked a candidate there ("witness"):
    // checked first, it rejects most repeated failures in O(1).
    static constexpr std::uint32_t kNoWitness = 0xffffffffu;
    mutable std::vector<std::uint32_t> witness_;
    std::vector<std::uint32_t> ep_level_;
};

}  // namespace binpack
