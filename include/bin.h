#pragma once
#include <vector>
#include <string>
#include <functional>  // Include for std::reference_wrapper
#include "box.h"
#include "item.h"

class Bin : public Box {
public:
    Bin(const std::string& name, long w, long h, long d);
    
    const std::vector<std::reference_wrapper<Item>>& getItems() const;
    void setItems(const std::vector<std::reference_wrapper<Item>>& items);

    float scoreRotation(const Item& item, long rotationType) const;
    std::vector<long> getBestRotationOrder(const Item& item) const;
    bool putItem(Item& item, const std::tuple<long, long, long>& p);

    void addItem(Item& item);

    std::string toString() const;

private:
    std::vector<std::reference_wrapper<Item>> items;
};
