#include "bin.h"
#include "loading_sequence.h"
#include <cmath>
#include <algorithm>
#include <sstream>
#include <iostream>
#include <functional> 

Bin::Bin(const std::string& name, long w, long h, long d, float max_weight, const std::string& image, const std::string& description, int id, float cost)
    : Box(name, w, h, d), max_weight(max_weight), image(image), description(description), id(id), cost(cost) {
}

const std::vector<std::reference_wrapper<Item>>& Bin::getItems() const {
    return items;
}

void Bin::setItems(const std::vector<std::reference_wrapper<Item>>& new_items) {
    this->items = new_items;
}

void Bin::addItem(Item& item) {
    items.push_back(std::ref(item));
}

bool Bin::removeItem(Item& item) {
    auto it = std::find_if(items.begin(), items.end(), [&item](const std::reference_wrapper<Item>& ref) {
        return &ref.get() == &item;
    });
    
    if (it != items.end()) {
        items.erase(it);
        return true;
    }
    return false;
}

float Bin::scoreRotation(const Item& item, const std::tuple<long, long, long>& position, RotationType rotation_type) const {
    Item rotatedItem = item;
    rotatedItem.setRotationType(rotation_type);
    auto d = rotatedItem.getDimension();

    if (getWidth() < d[0] || getHeight() < d[1] || getDepth() < d[2]) {
        return 0;
    }
    float widthScore = std::pow(static_cast<float>(d[0]) / getWidth(), 2);
    float heightScore = std::pow(static_cast<float>(d[1]) / getHeight(), 2);
    float depthScore = std::pow(static_cast<float>(d[2]) / getDepth(), 2);

    float score = widthScore + heightScore + depthScore;
    return score;
}

RotationType Bin::getBestRotationOrder(const Item& item, const std::tuple<long, long, long>& position) const {
    // Use map to maintain same structure as Python dictionary
    std::map<RotationType, float> rotationScores;
    
    // Score all rotation types
    for (auto rotation : item.getAllowedRotations()) {
        rotationScores[rotation] = scoreRotation(item, position, rotation);
    }
    
    // Find rotation with highest score
    RotationType bestRotation = item.getAllowedRotations()[0]; // Default to first allowed rotation
    float bestScore = 0;
    
    for (const auto& [rotation, score] : rotationScores) {
        if (score > bestScore) {
            bestScore = score;
            bestRotation = rotation;
        }
    }
    
    return bestRotation;
}

bool Bin::putItem(Item& item, const std::tuple<long, long, long>& p) {
    bool fit = false;
    RotationType bestRotation = getBestRotationOrder(item, p);

    item.setPosition({std::get<0>(p), std::get<1>(p), std::get<2>(p)});
    item.setRotationType(bestRotation);
    auto d = item.getDimension();

    if (getWidth() < std::get<0>(p) + d[0] || 
        getHeight() < std::get<1>(p) + d[1] || 
        getDepth() < std::get<2>(p) + d[2]) {
        fit = false;
    } else {
        fit = true;
        for (const auto& otherItem : items) {
            if (otherItem.get().doesIntersect(item)) {
                fit = false;
                break;
            }
        }

        if (fit) {
            items.push_back(std::ref(item));
        }
    }

    return fit;
}

bool Bin::canItemFit(const Item& item, const std::tuple<long, long, long>& position) const {
    // Get item dimensions 
    const auto& item_dim = item.getDimension();
    
    // Check if the item fits within bin boundaries
    if (std::get<0>(position) + item_dim[0] > width ||
        std::get<1>(position) + item_dim[1] > height ||
        std::get<2>(position) + item_dim[2] > depth) {
        return false;
    }
    
    // Check if item exceeds weight limit
    float total_weight = 0.0f;
    for (const auto& existing_item : items) {
        total_weight += existing_item.get().weight;
    }
    
    if (max_weight > 0 && total_weight + item.weight > max_weight) {
        return false;
    }
    
    // Check for intersections with existing items
    Item temp_item = item;  // Create a temporary copy to check placement
    temp_item.setPosition(position);
    
    for (const auto& existing_item : items) {
        if (temp_item.doesIntersect(existing_item)) {
            return false;
        }
    }
    
    return true;
}

std::string Bin::toString() const {
    std::ostringstream oss;
    oss << "Bin: " << getName() << " (W x H x D = " << getWidth() << " x " << getHeight() << " x " << getDepth() << ")";
    return oss.str();
}

float Bin::getTotalWeight() const {
    float total = 0.0f;
    for (const auto& item : items) total += item.get().weight;
    return total;
}

long Bin::getPackedVolume() const {
    long total = 0;
    for (const auto& item : items) total += item.get().getVolume();
    return total;
}

double Bin::getUtilization() const {
    const long volume = getVolume();
    return volume > 0 ? static_cast<double>(getPackedVolume()) / static_cast<double>(volume) : 0.0;
}

namespace {
std::vector<binpack::SequenceBox> sequenceBoxes(const std::vector<std::reference_wrapper<Item>>& items) {
    std::vector<binpack::SequenceBox> boxes;
    boxes.reserve(items.size());
    for (const auto& ref : items) {
        const Item& item = ref.get();
        const auto d = item.getDimension();
        const auto& p = item.getPosition();
        binpack::SequenceBox box;
        box.lo = {static_cast<binpack::coord_t>(std::get<0>(p)), static_cast<binpack::coord_t>(std::get<1>(p)),
                  static_cast<binpack::coord_t>(std::get<2>(p))};
        box.hi = {static_cast<binpack::coord_t>(box.lo[0] + d[0]), static_cast<binpack::coord_t>(box.lo[1] + d[1]),
                  static_cast<binpack::coord_t>(box.lo[2] + d[2])};
        box.fixed = true;  // a finished layout is never altered
        boxes.push_back(box);
    }
    return boxes;
}
}  // namespace

std::vector<std::string> Bin::checkLoadingSequence(LoadingAccess access) const {
    std::vector<std::string> problems;
    const auto boxes = sequenceBoxes(items);
    for (const auto& violation : binpack::checkLoadingSequence(boxes, access)) {
        problems.push_back(violation.describe() + " (" + items[violation.step].get().getName() + " / " +
                           items[violation.other].get().getName() + ")");
    }
    return problems;
}

bool Bin::reorderForLoading(LoadingAccess access) {
    const auto plan = binpack::planLoadingSequence(sequenceBoxes(items), access, FillOrder::BackBottomLeft, 0.0);
    std::vector<std::reference_wrapper<Item>> ordered;
    ordered.reserve(items.size());
    for (std::size_t k : plan.order) ordered.push_back(items[k]);
    items = std::move(ordered);
    return plan.feasible;
}
