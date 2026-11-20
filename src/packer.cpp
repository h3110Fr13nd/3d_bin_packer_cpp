#include "packer.h"
#include "packing_engine.h"

#include "bin_planner.h"
#include "fleet_planner.h"
#include "loading_sequence.h"

#include <algorithm>
#include <cmath>
#include <functional>
#include <iterator>
#include <limits>
#include <map>
#include <numeric>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

namespace {

using binpack::ContainerEngine;
using binpack::coord_t;
using binpack::ItemSpec;
using binpack::Placement;

void validateDimensions(const Box& box, const char* what) {
    if (box.getWidth() < 0 || box.getHeight() < 0 || box.getDepth() < 0) {
        throw std::invalid_argument(std::string(what) + " '" + box.getName() +
                                    "' has a negative dimension");
    }
}

// Packs `sequence` into the bin (on top of what it holds) and returns the rest.
std::vector<Item*> packBin(Bin& bin, const std::vector<Item*>& sequence, const PackingConfig& config,
                           bool resequence) {
    const binpack::BinPlan plan = binpack::planBin(bin, binpack::fixedItemsOf(bin), sequence, config, resequence);
    binpack::applyPlan(bin, plan);
    return plan.rest;
}

// Why an item ended up unloaded. Messages are generic (the item's group is in
// Item::group) so they can be counted per reason.
std::string unfitReason(const Item& item, const std::vector<Bin>& bins, const std::vector<Packer::BinType>& types,
                        const PackingConfig& config) {
    const ItemSpec spec = ItemSpec::fromItem(item);
    if (spec.orientations.empty()) return "no allowed rotation (check allowed_rotations / upright)";
    auto fits = [&](const Bin& bin) {
        return std::any_of(spec.orientations.begin(), spec.orientations.end(), [&](const auto& o) {
            return o.dims[0] <= bin.getWidth() && o.dims[1] <= bin.getHeight() && o.dims[2] <= bin.getDepth();
        });
    };
    auto light_enough = [&](const Bin& bin) { return bin.max_weight <= 0 || item.weight <= bin.max_weight; };
    bool fits_some_bin = false, weight_ok_somewhere = false, capacity_weight_ok = false;
    bool type_fits = false, type_left = false;
    for (const Bin& bin : bins) {
        if (bin.type_index >= 0 || !fits(bin)) continue;
        fits_some_bin = true;
        if (light_enough(bin)) {
            weight_ok_somewhere = true;
            if (bin.max_weight <= 0 || bin.getTotalWeight() + item.weight <= bin.max_weight) capacity_weight_ok = true;
        }
    }
    for (std::size_t t = 0; t < types.size(); ++t) {
        if (types[t].count == 0 || !fits(types[t].bin)) continue;
        fits_some_bin = true;
        if (!light_enough(types[t].bin)) continue;
        weight_ok_somewhere = type_fits = true;
        const auto used = std::count_if(bins.begin(), bins.end(), [&](const Bin& b) {
            return b.type_index == static_cast<int>(t) && !b.items.empty();
        });
        if (types[t].count < 0 || used < types[t].count) type_left = true;
    }
    if (!fits_some_bin) return "too large for every bin";
    if (!weight_ok_somewhere) return "heavier than the weight limit of every bin it fits in";
    if (type_fits) {
        if (config.objective == Objective::Profit) return "not profitable: worth less than the container it needs";
        if (!type_left) return "no container left: all available containers are in use";
    }
    if (!item.group.empty()) return "group could not be loaded completely into one bin";
    if (!capacity_weight_ok && !type_fits) return "weight limit reached";
    return "no space left";
}

}  // namespace

Packer::Packer() = default;

Packer::Packer(const PackingConfig& config) {
    setConfig(config);
}

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
    validateDimensions(bin, "Bin");
    bins.push_back(bin);
}

void Packer::addItem(const Item& item) {
    validateDimensions(item, "Item");
    items.push_back(item);
}

const PackingConfig& Packer::getConfig() const {
    return config_;
}

void Packer::setConfig(const PackingConfig& config) {
    setMinSupportRatio(config.min_support_ratio);  // validates
    config_ = config;
}

FillOrder Packer::getFillOrder() const {
    return config_.fill_order;
}

void Packer::setFillOrder(FillOrder order) {
    config_.fill_order = order;
}

double Packer::getMinSupportRatio() const {
    return config_.min_support_ratio;
}

void Packer::setMinSupportRatio(double ratio) {
    if (!(ratio >= 0.0 && ratio <= 1.0)) {
        throw std::invalid_argument("min_support_ratio must be between 0 and 1");
    }
    config_.min_support_ratio = ratio;
}

bool Packer::getNonStackableOnTop() const {
    return config_.non_stackable_on_top;
}

void Packer::setNonStackableOnTop(bool value) {
    config_.non_stackable_on_top = value;
}

bool Packer::getOptimize() const {
    return config_.optimize;
}

void Packer::setOptimize(bool value) {
    config_.optimize = value;
}

LoadingAccess Packer::getLoadingAccess() const {
    return config_.loading_access;
}

void Packer::setLoadingAccess(LoadingAccess access) {
    config_.loading_access = access;
}

Objective Packer::getObjective() const {
    return config_.objective;
}

void Packer::setObjective(Objective objective) {
    config_.objective = objective;
}

FleetGoal Packer::getFleetGoal() const {
    return config_.fleet_goal;
}

void Packer::setFleetGoal(FleetGoal goal) {
    config_.fleet_goal = goal;
}

std::optional<std::reference_wrapper<Bin>> Packer::findFittedBin(Item& item) {
    std::vector<std::size_t> order(bins.size());
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [this](std::size_t a, std::size_t b) {
        return bins[a].getVolume() < bins[b].getVolume();
    });
    const ItemSpec spec = ItemSpec::fromItem(item);
    for (std::size_t b : order) {
        Bin& bin = bins[b];
        if (bin.max_weight > 0 && item.weight > bin.max_weight) continue;
        for (const auto& o : spec.orientations) {
            if (o.dims[0] <= bin.getWidth() && o.dims[1] <= bin.getHeight() && o.dims[2] <= bin.getDepth()) {
                return std::ref(bin);
            }
        }
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
    // The caller's sequence is respected; only the orientation scoring varies.
    return packBin(bin, item_ptrs, config_, /*resequence=*/false);
}

void Packer::addBinType(const Bin& bin, int count) {
    validateDimensions(bin, "Bin type");
    if (count < UNLIMITED) throw std::invalid_argument("count must be >= 0, or UNLIMITED (-1)");
    bin_types.push_back({bin, count});
}

const std::vector<Packer::BinType>& Packer::getBinTypes() const {
    return bin_types;
}

float Packer::getTotalCost() const {
    float total = 0.0f;
    for (const Bin& bin : bins) {
        if (!bin.items.empty()) total += bin.cost;
    }
    return total;
}

void Packer::pack() {
    // Start from a clean slate so pack() can be called repeatedly: containers
    // opened by an earlier fleet plan are removed, explicit bins emptied.
    bins.erase(std::remove_if(bins.begin(), bins.end(), [](const Bin& b) { return b.type_index >= 0; }), bins.end());
    for (auto& bin : bins) bin.items.clear();
    unfit_items.clear();
    for (auto& item : items) item.unfit_reason.clear();

    // The user's item order is left untouched; strategies sort their own copy.
    std::vector<Item*> remaining;
    remaining.reserve(items.size());
    for (auto& item : items) {
        if (item.crate_required) {  // crating happens before packing (binpack.crates), never loose
            unfit_items.push_back(item);
            unfit_items.back().unfit_reason = "must travel in a crate: pack it with pack_with_crates";
            continue;
        }
        remaining.push_back(&item);
    }
    binpack::sortCanonical(remaining, config_);

    // Bins are filled smallest first; their order in `bins` is preserved.
    std::vector<std::size_t> bin_order(bins.size());
    std::iota(bin_order.begin(), bin_order.end(), 0);
    std::stable_sort(bin_order.begin(), bin_order.end(), [this](std::size_t a, std::size_t b) {
        return bins[a].getVolume() < bins[b].getVolume();
    });

    for (std::size_t b : bin_order) {
        if (remaining.empty()) break;
        remaining = packBin(bins[b], remaining, config_, /*resequence=*/true);
    }

    // Fleet planning: book containers from the bin types for what is left.
    if (!remaining.empty() && !bin_types.empty()) {
        std::vector<binpack::FleetType> types;
        for (const auto& type : bin_types) types.push_back({&type.bin, type.count});
        binpack::FleetPlan fleet = binpack::planFleet(remaining, types, config_);
        std::vector<int> opened(bin_types.size(), 0);
        for (const auto& container : fleet.containers) {
            Bin bin = bin_types[container.type].bin;
            bin.items.clear();
            bin.type_index = container.type;
            bin.name = bin.name + " #" + std::to_string(++opened[container.type]);
            binpack::applyPlan(bin, container.plan);
            bins.push_back(std::move(bin));
        }
        remaining = fleet.rest;
    }

    for (Item* item : remaining) {
        unfit_items.push_back(*item);
        unfit_items.back().unfit_reason = unfitReason(*item, bins, bin_types, config_);
    }
}
