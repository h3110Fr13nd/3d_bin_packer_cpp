#ifndef BIN_H
#define BIN_H

#include <vector>
#include <memory>
#include <algorithm>
#include <string>
#include <tuple>
#include "box.h"
#include "item.h"
#include "packing_config.h"

class Bin : public Box {
public:
    std::vector<std::reference_wrapper<Item>> items;
    float max_weight;
    std::string image;
    std::string description;
    int id;
    float cost = 0.0f;    // price of using this bin (fleet planning, reports)
    int type_index = -1;  // index in Packer::bin_types if opened by the fleet planner, else -1

    // Constructor declaration
    Bin(const std::string& name, long w, long h, long d, 
        float max_weight = 0.0f, const std::string& image = "",
        const std::string& description = "", int id = 0, float cost = 0.0f);

    // Function declarations
    const std::vector<std::reference_wrapper<Item>>& getItems() const;
    void setItems(const std::vector<std::reference_wrapper<Item>>& new_items);
    void addItem(Item& item);
    bool removeItem(Item& item);
    bool putItem(Item& item, const std::tuple<long, long, long>& position);
    float scoreRotation(const Item& item, const std::tuple<long, long, long>& position, RotationType rotation_type) const;
    RotationType getBestRotationOrder(const Item& item, const std::tuple<long, long, long>& position) const;
    std::string toString() const;

    // Totals over the packed items.
    float getTotalWeight() const;
    long getPackedVolume() const;
    double getUtilization() const;  // packed volume / bin volume, 0..1

    // Problems with loading the items in their current order from the given
    // side (an item loaded before what it rests on, or whose path is blocked
    // by an item loaded earlier). Empty = feasible.
    std::vector<std::string> checkLoadingSequence(LoadingAccess access = LoadingAccess::Door) const;

    // Re-orders the items into a feasible loading sequence for another
    // access side. Returns false if no such order exists for this layout
    // (the items are then in a best-effort order).
    bool reorderForLoading(LoadingAccess access = LoadingAccess::Door);
    
    // Make sure this declaration is properly visible
    bool canItemFit(const Item& item, const std::tuple<long, long, long>& position) const;
};

#endif // BIN_H
