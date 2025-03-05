#ifndef BIN_H
#define BIN_H

#include <vector>
#include <memory>
#include <algorithm>
#include <string>
#include <tuple>
#include "box.h"
#include "item.h"

class Bin : public Box {
public:
    std::vector<std::reference_wrapper<Item>> items;
    float max_weight;
    std::string image;
    std::string description;
    int id;

    // Constructor declaration
    Bin(const std::string& name, long w, long h, long d, 
        float max_weight = 0.0f, const std::string& image = "",
        const std::string& description = "", int id = 0);

    // Function declarations
    const std::vector<std::reference_wrapper<Item>>& getItems() const;
    void setItems(const std::vector<std::reference_wrapper<Item>>& new_items);
    void addItem(Item& item);
    bool removeItem(Item& item);
    bool putItem(Item& item, const std::tuple<long, long, long>& position);
    float scoreRotation(const Item& item, const std::tuple<long, long, long>& position, RotationType rotation_type) const;
    RotationType getBestRotationOrder(const Item& item, const std::tuple<long, long, long>& position) const;
    std::string toString() const;
    
    // Make sure this declaration is properly visible
    bool canItemFit(const Item& item, const std::tuple<long, long, long>& position) const;
};

#endif // BIN_H
