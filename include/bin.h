#pragma once
#include <vector>
#include <string>
#include <functional>  // Include for std::reference_wrapper
#include "box.h"
#include "item.h"

class Bin : public Box {
public:
    Bin(const std::string& name, long w, long h, long d, float max_weight, const std::string& image, const std::string& description, int id);
    
    const std::vector<std::reference_wrapper<Item>>& getItems() const;
    void setItems(const std::vector<std::reference_wrapper<Item>>& items);

    float scoreRotation(const Item& item, long rotationType) const;
    std::vector<long> getBestRotationOrder(const Item& item) const;
    bool putItem(Item& item, const std::tuple<long, long, long>& p);

    void addItem(Item& item);
    
    // Add method to remove an item
    void removeItem(Item& item);

    std::string toString() const;
    
    int id;
    float max_weight;
    std::string image;
    std::string description;
    std::vector<std::reference_wrapper<Item>> items;

private:
};
