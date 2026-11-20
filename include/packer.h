#ifndef INCLUDE_PACKER_H
#define INCLUDE_PACKER_H

#include <vector>
#include <optional>
#include <functional>  // Include for std::reference_wrapper
#include "../src/bin.h"
#include "item.h"
#include "packing_config.h"

class Packer {
public:
    static constexpr int UNLIMITED = -1;

    // A kind of container that the fleet planner may book (see addBinType).
    struct BinType {
        Bin bin;    // template: size, max_weight, cost
        int count;  // how many are available; UNLIMITED = as many as needed
    };

    Packer();
    explicit Packer(const PackingConfig& config);

    const std::vector<Bin>& getBins() const;
    const std::vector<Item>& getItems() const;
    const std::vector<Item>& getUnfitItems() const;

    // A bin that is always available (filled first, smallest first).
    void addBin(const Bin& bin);
    void addItem(const Item& item);

    // Fleet planning: a container type that may be booked `count` times
    // (UNLIMITED = any number). After the explicit bins, pack() chooses which
    // containers to book - as few / as cheap as possible (config.fleet_goal),
    // or the most profitable ones (Objective::Profit) - and appends them to
    // `bins` as "<name> #k" with type_index set.
    void addBinType(const Bin& bin, int count = UNLIMITED);
    const std::vector<BinType>& getBinTypes() const;

    // Cost of the bins that received items.
    float getTotalCost() const;

    // Packing behaviour (fill order, support ratio, ...).
    const PackingConfig& getConfig() const;
    void setConfig(const PackingConfig& config);
    FillOrder getFillOrder() const;
    void setFillOrder(FillOrder order);
    double getMinSupportRatio() const;
    void setMinSupportRatio(double ratio);
    bool getNonStackableOnTop() const;
    void setNonStackableOnTop(bool value);
    bool getOptimize() const;
    void setOptimize(bool value);
    LoadingAccess getLoadingAccess() const;
    void setLoadingAccess(LoadingAccess access);
    Objective getObjective() const;
    void setObjective(Objective objective);
    FleetGoal getFleetGoal() const;
    void setFleetGoal(FleetGoal goal);

    // Smallest bin (by volume) that could hold the item on its own, if any.
    std::optional<std::reference_wrapper<Bin>> findFittedBin(Item& item);
    std::optional<std::reference_wrapper<Bin>> getBiggerBinThan(const Bin& other_bin);
    void unfitItem(std::vector<Item*>& item_ptrs);

    // Packs the items (in the given order) into the bin, keeping items already
    // in it. Returns the items that did not fit, in their input order. The
    // bin's items end up in loading order.
    std::vector<Item*> packToBin(Bin& bin, std::vector<Item*>& item_ptrs);

    // Packs all items into the bins, smallest bin first (the order of `bins`
    // and `items` is not changed). Can be called again after changing items,
    // bins or settings; previous results are discarded. Items that fit nowhere
    // are copied to unfit_items with an unfit_reason. Each bin's items are
    // listed in a feasible loading order for config.loading_access.
    void pack();

    // Public data members
    std::vector<Item> items;
    std::vector<Bin> bins;
    std::vector<Item> unfit_items;
    std::vector<BinType> bin_types;

private:
    PackingConfig config_;
};

#endif // INCLUDE_PACKER_H
