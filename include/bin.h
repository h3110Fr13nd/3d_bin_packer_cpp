#pragma once
#include <vector>
#include <string>
#include <functional>  // Include for std::reference_wrapper
#include "box.h"
#include "item.h"

class Bin : public Box {
public:
    Bin(const std::string& name, float w, float h, float d);
    
    const std::vector<std::reference_wrapper<Item>>& getItems() const;
    void setItems(const std::vector<std::reference_wrapper<Item>>& items);

    float scoreRotation(const Item& item, int rotationType) const;
    std::vector<int> getBestRotationOrder(const Item& item) const;
    bool putItem(Item& item, const std::tuple<float, float, float>& p);

    void addItem(Item& item);

    std::string toString() const;

private:
    std::vector<std::reference_wrapper<Item>> items;
};
