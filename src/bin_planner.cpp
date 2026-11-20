// bin_planner.cpp - plans the load of one bin: strategy portfolio, priorities,
// consignments and a feasible loading order. Used by the Packer for single
// bins and by the fleet planner to evaluate candidate containers.
#include "bin_planner.h"

#include "loading_sequence.h"
#include "packing_engine.h"

#include <algorithm>
#include <cmath>
#include <functional>
#include <iterator>
#include <limits>
#include <map>
#include <set>
#include <string>
#include <tuple>

namespace binpack {

double objectiveOf(const Item& item, Objective objective) {
    switch (objective) {
        case Objective::Volume: return static_cast<double>(item.getVolume());
        case Objective::Weight: return item.weight;
        case Objective::Value:
        case Objective::Profit: return item.value;
        case Objective::Count: return 1.0;
    }
    return 0.0;
}

bool Score::betterThan(const Score& other) const {
    auto close = [](double a, double b) { return std::abs(a - b) <= 1e-9 * std::max({1.0, std::abs(a), std::abs(b)}); };
    std::set<int, std::greater<int>> levels;
    for (const auto& [p, v] : by_priority) levels.insert(p);
    for (const auto& [p, v] : other.by_priority) levels.insert(p);
    for (int p : levels) {
        const auto a = by_priority.count(p) ? by_priority.at(p) : 0.0;
        const auto b = other.by_priority.count(p) ? other.by_priority.at(p) : 0.0;
        if (!close(a, b)) return a > b;
    }
    return !close(volume, other.volume) && volume > other.volume;
}

void Score::add(const Item& item, Objective objective) {
    by_priority[item.priority] += objectiveOf(item, objective);
    volume += static_cast<double>(item.getVolume());
    weight += item.weight;
    value += item.value;
    ++count;
}

Placement placementOf(const Item& item) {
    const auto dims = item.getDimension();
    Placement p;
    p.position = {static_cast<coord_t>(std::get<0>(item.getPosition())),
                  static_cast<coord_t>(std::get<1>(item.getPosition())),
                  static_cast<coord_t>(std::get<2>(item.getPosition()))};
    p.dims = {static_cast<coord_t>(dims[0]), static_cast<coord_t>(dims[1]), static_cast<coord_t>(dims[2])};
    p.rotation = item.getRotationType();
    return p;
}

namespace {

// How the items are sequenced within their priority and constraint group.
enum class SequenceRule {
    Volume,    // biggest first
    BaseArea,  // biggest footprint first
    Density,   // most objective per unit of scarce capacity first (knapsack greedy)
    Select,    // pick by density until the bin is full, pack the pick biggest-footprint
               // first, then offer the rest by density (select-then-pack)
};

// A placement heuristic: item sequence + orientation scoring.
struct Strategy {
    SequenceRule sequence;
    double flush_bonus;
    double fill_target = 1.0;  // Select: share of the bin's volume/weight to pick
};

// Best single strategy first: it is the only one used when optimize=false.
std::vector<Strategy> strategiesFor(const PackingConfig& config, bool weight_limited) {
    std::vector<Strategy> strategies;
    // Density-aware selection pays off for non-volume objectives, and for
    // volume when the weight limit may run out first.
    if (config.objective != Objective::Volume || weight_limited) {
        strategies.push_back({SequenceRule::Select, 0.3, 1.0});  // what pays best, packed well
        strategies.push_back({SequenceRule::Select, 0.3, 0.9});
        strategies.push_back({SequenceRule::Density, 0.3});      // what pays best, in that order
    }
    strategies.push_back({SequenceRule::BaseArea, 0.3});  // even walls / layers
    strategies.push_back({SequenceRule::Volume, 0.0});    // classic big-items-first
    return strategies;
}

// Capacity of the bin being filled, to weigh volume against weight.
struct Capacity {
    double volume = 0.0;
    double weight = 0.0;  // 0 = unlimited
};

// Objective earned per unit of the item's scarcest resource (volume or
// weight share of the bin) - the classic greedy for multi-dimensional knapsacks.
double density(const Item& item, Objective objective, const Capacity& cap) {
    const double volume_share = cap.volume > 0 ? static_cast<double>(item.getVolume()) / cap.volume : 0.0;
    const double weight_share = cap.weight > 0 ? item.weight / cap.weight : 0.0;
    const double share = std::max(volume_share, weight_share);
    const double value = objectiveOf(item, objective);
    if (share <= 0.0) return value > 0 ? std::numeric_limits<double>::infinity() : 0.0;
    return value / share;
}

// Packing sequence group: floor-only items first (they need floor space before
// it is covered), then regular items, then non-stackable items (so they can be
// put on top of the load).
int sequenceGroup(const Item& item, const PackingConfig& config) {
    if (item.isBottomLoadOnlyEnabled()) return 0;
    if (config.non_stackable_on_top && (item.isDisableStackingEnabled() || item.isHeightConstrained())) return 2;
    return 1;
}

long baseArea(const Item& item) {
    long d[3] = {item.getWidth(), item.getHeight(), item.getDepth()};
    std::sort(d, d + 3);
    return d[1] * d[2];  // largest face
}

// Select-then-pack: which items to pick, greedily by density (consignments as
// a whole, higher priorities first) until `fill_target` of the bin's volume or
// weight is used.
std::set<const Item*> selectByDensity(const std::vector<Item*>& items, const PackingConfig& config,
                                      const Capacity& cap, double fill_target) {
    struct Unit {
        std::vector<const Item*> items;
        int priority = std::numeric_limits<int>::min();
        double value = 0, volume = 0, weight = 0;
    };
    std::vector<Unit> units;
    std::map<std::string, std::size_t> by_group;
    for (const Item* item : items) {
        std::size_t u;
        if (!item->group.empty() && by_group.count(item->group)) {
            u = by_group[item->group];
        } else {
            u = units.size();
            units.emplace_back();
            if (!item->group.empty()) by_group[item->group] = u;
        }
        Unit& unit = units[u];
        unit.items.push_back(item);
        unit.priority = std::max(unit.priority, item->priority);
        unit.value += objectiveOf(*item, config.objective);
        unit.volume += static_cast<double>(item->getVolume());
        unit.weight += item->weight;
    }
    auto unit_density = [&](const Unit& u) {
        const double share = std::max(cap.volume > 0 ? u.volume / cap.volume : 0.0,
                                      cap.weight > 0 ? u.weight / cap.weight : 0.0);
        return share > 0 ? u.value / share : (u.value > 0 ? std::numeric_limits<double>::infinity() : 0.0);
    };
    std::stable_sort(units.begin(), units.end(), [&](const Unit& a, const Unit& b) {
        if (a.priority != b.priority) return a.priority > b.priority;
        return unit_density(a) > unit_density(b);
    });
    std::set<const Item*> picked;
    double volume = 0, weight = 0;
    for (const Unit& u : units) {
        const bool fits = volume + u.volume <= fill_target * cap.volume &&
                          (cap.weight <= 0 || weight + u.weight <= fill_target * cap.weight);
        if (!fits) continue;
        volume += u.volume;
        weight += u.weight;
        picked.insert(u.items.begin(), u.items.end());
    }
    return picked;
}

// Priority first, then constraint group, then the rule; identical items stay together.
void sortSequence(std::vector<Item*>& sequence, const PackingConfig& config, SequenceRule rule, const Capacity& cap,
                  double fill_target = 1.0) {
    struct Keyed {
        Item* item;
        int priority;
        int picked;
        int group;
        double primary;
        long volume;
        long max_dim;
        std::tuple<long, long, long> dims;
    };
    const std::set<const Item*> picked =
        rule == SequenceRule::Select ? selectByDensity(sequence, config, cap, fill_target) : std::set<const Item*>{};
    std::vector<Keyed> keyed;
    keyed.reserve(sequence.size());
    for (Item* item : sequence) {
        double primary = 0.0;
        const bool is_picked = picked.count(item) != 0;
        switch (rule) {
            case SequenceRule::Volume: primary = static_cast<double>(item->getVolume()); break;
            case SequenceRule::BaseArea: primary = static_cast<double>(baseArea(*item)); break;
            case SequenceRule::Density: primary = density(*item, config.objective, cap); break;
            case SequenceRule::Select:
                primary = is_picked ? static_cast<double>(baseArea(*item)) : density(*item, config.objective, cap);
                break;
        }
        keyed.push_back({item, item->priority, is_picked ? 1 : 0, sequenceGroup(*item, config), primary,
                         item->getVolume(), std::max({item->getWidth(), item->getHeight(), item->getDepth()}),
                         std::make_tuple(item->getWidth(), item->getHeight(), item->getDepth())});
    }
    std::stable_sort(keyed.begin(), keyed.end(), [](const Keyed& a, const Keyed& b) {
        if (a.priority != b.priority) return a.priority > b.priority;
        if (a.picked != b.picked) return a.picked > b.picked;
        if (a.group != b.group) return a.group < b.group;
        if (a.primary != b.primary) return a.primary > b.primary;
        if (a.volume != b.volume) return a.volume > b.volume;
        if (a.max_dim != b.max_dim) return a.max_dim > b.max_dim;
        return a.dims > b.dims;
    });
    for (std::size_t i = 0; i < keyed.size(); ++i) sequence[i] = keyed[i].item;
}

// Outcome of packing one bin with one strategy (nothing is applied yet).
struct BinAttempt {
    std::vector<std::pair<Item*, Placement>> placed;  // pre-placed items first, then commit order
    std::vector<Item*> rest;                          // did not fit
    Score score;                                      // of the newly placed items
};

// Outcome of packing one bin with one strategy, plus the engine state so more
// items can be tried afterwards.
struct BinState {
    ContainerEngine engine;
    BinAttempt attempt;
};

BinState startBin(const Bin& bin, const FixedItems& fixed, const PackingConfig& config, double flush_bonus) {
    BinState state{ContainerEngine(bin.getWidth(), bin.getHeight(), bin.getDepth(), bin.max_weight, config,
                                   flush_bonus),
                   BinAttempt{}};
    // Items already in the bin keep their position.
    for (const auto& [item, p] : fixed) {
        state.engine.commit(ItemSpec::fromItem(*item), p);
        state.attempt.placed.emplace_back(item, p);
    }
    return state;
}

// Places the items one by one; those that do not fit go to attempt.rest.
// `keep_min_dim` keeps extreme points usable for items of that size that may
// still be tried later (e.g. consignments retried after this pass).
void placeSequence(BinState& state, const std::vector<Item*>& sequence, const PackingConfig& config,
                   coord_t keep_min_dim) {
    std::vector<ItemSpec> specs;
    specs.reserve(sequence.size());
    for (const Item* item : sequence) specs.push_back(ItemSpec::fromItem(*item));

    // Smallest extent of any item still to come; lets the engine drop
    // extreme points that are too cramped to ever be used.
    std::vector<coord_t> min_remaining(specs.size() + 1, keep_min_dim);
    for (std::size_t i = specs.size(); i-- > 0;) {
        min_remaining[i] = std::min(min_remaining[i + 1], specs[i].minDimension());
    }

    const ItemSpec* last_failed = nullptr;  // an identical item failed and nothing changed since
    for (std::size_t i = 0; i < sequence.size(); ++i) {
        if (last_failed != nullptr && *last_failed == specs[i]) {
            state.attempt.rest.push_back(sequence[i]);
            continue;
        }
        state.engine.setMinItemDimension(min_remaining[i]);
        Placement p;
        if (!state.engine.findPlacement(specs[i], p)) {
            last_failed = &specs[i];
            state.attempt.rest.push_back(sequence[i]);
            continue;
        }
        state.engine.commit(specs[i], p);
        state.attempt.placed.emplace_back(sequence[i], p);
        state.attempt.score.add(*sequence[i], config.objective);
        last_failed = nullptr;
    }
}

// All-or-nothing: places every item of `unit` on a copy of the state and keeps
// the copy only if all of them fit.
bool placeUnit(BinState& state, const std::vector<Item*>& unit, const PackingConfig& config,
               coord_t keep_min_dim) {
    BinState trial = state;
    trial.attempt.rest.clear();
    placeSequence(trial, unit, config, keep_min_dim);
    if (!trial.attempt.rest.empty()) return false;
    trial.attempt.rest = std::move(state.attempt.rest);
    state = std::move(trial);
    return true;
}

coord_t minDimension(const std::vector<Item*>& items) {
    coord_t m = std::numeric_limits<coord_t>::max();
    for (const Item* item : items) m = std::min(m, ItemSpec::fromItem(*item).minDimension());
    return m;
}

BinAttempt attemptBin(const Bin& bin, const FixedItems& fixed, const std::vector<Item*>& sequence,
                      const PackingConfig& config, double flush_bonus) {
    BinState state = startBin(bin, fixed, config, flush_bonus);
    placeSequence(state, sequence, config, std::numeric_limits<coord_t>::max());
    return std::move(state.attempt);
}

// Consignments ship complete or not at all. Pass 1: while some group is only
// partly loaded, take all of its items out and pack the bin again. Pass 2:
// retry the groups taken out, each as a whole, in the space that is left.
BinAttempt attemptWithGroups(const Bin& bin, const FixedItems& fixed_items, std::vector<Item*> sequence,
                             const PackingConfig& config, double flush_bonus) {
    const bool grouped = std::any_of(sequence.begin(), sequence.end(), [](const Item* i) { return !i->group.empty(); });
    if (!grouped) return attemptBin(bin, fixed_items, sequence, config, flush_bonus);

    const std::size_t fixed = fixed_items.size();
    const coord_t keep_min_dim = minDimension(sequence);
    const std::vector<Item*> original = sequence;
    std::set<std::string> excluded;
    for (;;) {
        BinState state = startBin(bin, fixed_items, config, flush_bonus);
        placeSequence(state, sequence, config, keep_min_dim);
        std::set<std::string> loaded, left;
        for (std::size_t k = fixed; k < state.attempt.placed.size(); ++k) {
            if (!state.attempt.placed[k].first->group.empty()) loaded.insert(state.attempt.placed[k].first->group);
        }
        for (const Item* item : state.attempt.rest) {
            if (!item->group.empty()) left.insert(item->group);
        }
        std::set<std::string> partial;
        std::set_intersection(loaded.begin(), loaded.end(), left.begin(), left.end(),
                              std::inserter(partial, partial.begin()));
        if (!partial.empty()) {
            excluded.insert(partial.begin(), partial.end());
            std::vector<Item*> kept;
            for (Item* item : sequence) {
                if (!partial.count(item->group)) kept.push_back(item);
            }
            sequence = std::move(kept);
            continue;
        }

        // Pass 2, in the strategy's order of the groups' first items.
        std::vector<std::string> retry_order;
        std::map<std::string, std::vector<Item*>> members;
        for (Item* item : original) {
            if (!excluded.count(item->group)) continue;
            if (!members.count(item->group)) retry_order.push_back(item->group);
            members[item->group].push_back(item);
        }
        for (const std::string& group : retry_order) {
            if (!placeUnit(state, members[group], config, keep_min_dim)) {
                state.attempt.rest.insert(state.attempt.rest.end(), members[group].begin(), members[group].end());
            }
        }
        return std::move(state.attempt);
    }
}

}  // namespace

BinPlan planBin(const Bin& bin, const FixedItems& fixed_items, const std::vector<Item*>& sequence,
                const PackingConfig& config, bool resequence) {
    const std::size_t fixed = fixed_items.size();
    const Capacity cap{static_cast<double>(bin.getVolume()), bin.max_weight};
    std::set<const Item*> excluded;  // taken out to break loading-order cycles

    for (;;) {
        std::vector<Item*> candidates;
        for (Item* item : sequence) {
            if (!excluded.count(item)) candidates.push_back(item);
        }

        BinAttempt best;
        bool have_best = false;
        for (const Strategy& strategy : strategiesFor(config, cap.weight > 0)) {
            std::vector<Item*> ordered = candidates;
            if (resequence) sortSequence(ordered, config, strategy.sequence, cap, strategy.fill_target);
            BinAttempt attempt = attemptWithGroups(bin, fixed_items, ordered, config, strategy.flush_bonus);
            if (!have_best || attempt.score.betterThan(best.score)) {
                best = std::move(attempt);
                have_best = true;
            }
            if (!config.optimize || best.rest.empty()) break;  // nothing left to gain
        }

        // A feasible loading order for the chosen layout.
        std::vector<SequenceBox> boxes;
        boxes.reserve(best.placed.size());
        for (std::size_t k = 0; k < best.placed.size(); ++k) {
            const Placement& p = best.placed[k].second;
            boxes.push_back({p.position, {p.position[0] + p.dims[0], p.position[1] + p.dims[1], p.position[2] + p.dims[2]},
                             k < fixed});
        }
        const SequencePlan order = planLoadingSequence(boxes, config.loading_access, config.fill_order,
                                                       config.min_support_ratio);

        if (!order.removed.empty()) {
            // Rare interlocked layout: repack without the offending items (and
            // their whole consignment) so every invariant still holds.
            for (std::size_t k : order.removed) {
                const Item* item = best.placed[k].first;
                excluded.insert(item);
                if (!item->group.empty()) {
                    for (Item* other : sequence) {
                        if (other->group == item->group) excluded.insert(other);
                    }
                }
            }
            continue;
        }

        BinPlan plan;
        plan.score = best.score;
        for (std::size_t k : order.order) plan.placed.push_back(best.placed[k]);
        // Leftovers keep the caller's order (strategies may have reordered them).
        std::set<const Item*> unplaced(best.rest.begin(), best.rest.end());
        unplaced.insert(excluded.begin(), excluded.end());
        for (Item* item : sequence) {
            if (unplaced.count(item)) plan.rest.push_back(item);
        }
        return plan;
    }
}

void applyPlan(Bin& bin, const BinPlan& plan) {
    bin.items.clear();
    for (const auto& [item, p] : plan.placed) {
        item->setRotationType(p.rotation);
        item->setPosition({p.position[0], p.position[1], p.position[2]});
        bin.items.push_back(std::ref(*item));
    }
}

FixedItems fixedItemsOf(const Bin& bin) {
    FixedItems fixed;
    for (const auto& ref : bin.items) fixed.emplace_back(&ref.get(), placementOf(ref.get()));
    return fixed;
}

void sortCanonical(std::vector<Item*>& items, const PackingConfig& config) {
    sortSequence(items, config, SequenceRule::Volume, Capacity{});
}

bool fitsEmptyBin(const Item& item, const Bin& bin) {
    if (bin.max_weight > 0 && item.weight > bin.max_weight + 1e-6f) return false;
    const ItemSpec spec = ItemSpec::fromItem(item);
    return std::any_of(spec.orientations.begin(), spec.orientations.end(), [&](const auto& o) {
        return o.dims[0] <= bin.getWidth() && o.dims[1] <= bin.getHeight() && o.dims[2] <= bin.getDepth();
    });
}

}  // namespace binpack
