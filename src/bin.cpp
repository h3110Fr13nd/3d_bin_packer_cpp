#include "bin.h"
#include <cmath>
#include <algorithm>
#include <sstream>
#include <iostream>
#include <functional>  // Include for std::reference_wrapper

#define LOG(msg) std::cout << "[" << __FILE__ << ":" << __FUNCTION__ << "] " << msg << std::endl;

Bin::Bin(const std::string& name, float w, float h, float d) 
    : Box(name, w, h, d) {
    LOG("Created Bin with name: " << name << ", width: " << w << ", height: " << h << ", depth: " << d);
}

const std::vector<std::reference_wrapper<Item>>& Bin::getItems() const {
    LOG("Getting items");
    return items;
}

void Bin::setItems(const std::vector<std::reference_wrapper<Item>>& items) {
    LOG("Setting items");
    this->items = items;
}

void Bin::addItem(Item& item) {
    LOG("Adding item: " << item.getName());
    items.push_back(std::ref(item));
}

float Bin::scoreRotation(const Item& item, int rotationType) const {
    Item rotatedItem = item;
    rotatedItem.setRotationType(static_cast<RotationType>(rotationType));
    auto d = rotatedItem.getDimension();

    if (getWidth() < d[0] || getHeight() < d[1] || getDepth() < d[2]) {
        LOG("Item does not fit in bin");
        return 0;
    }

    float widthScore = std::pow(d[0] / getWidth(), 2);
    float heightScore = std::pow(d[1] / getHeight(), 2);
    float depthScore = std::pow(d[2] / getDepth(), 2);

    float score = widthScore + heightScore + depthScore;
    LOG("Score: " << score);
    return score;
}

std::vector<int> Bin::getBestRotationOrder(const Item& item) const {
    // Use map to maintain same structure as Python dictionary
    std::map<int, float> rotationScores;
    // Score all rotation types
    for (auto rotation : item.getAllowedRotations()) {
        // Explicitly cast RotationType to int for map key
        int rotationInt = static_cast<int>(rotation);
        rotationScores[rotationInt] = scoreRotation(item, rotationInt);
    }
    
    // Convert map to vector for sorting
    std::vector<int> bestRotations;
    bestRotations.reserve(rotationScores.size());
    
    // Extract keys and sort them based on their corresponding values
    for (const auto& [rotation, _] : rotationScores) {
        bestRotations.push_back(rotation);
    }
    
    std::sort(bestRotations.begin(), bestRotations.end(),
              [&rotationScores](int a, int b) {
                  return rotationScores[a] > rotationScores[b];
              });
    
    return bestRotations;
}

bool Bin::putItem(Item& item, const std::tuple<float, float, float>& p) {
    LOG("Putting item: " << item.getName() << " at position: (" << std::get<0>(p) << ", " << std::get<1>(p) << ", " << std::get<2>(p) << ")");
    bool fit = false;
    auto rotations = getBestRotationOrder(item);

    item.setPosition({std::get<0>(p), std::get<1>(p), std::get<2>(p)});
    LOG("Trying position: (" << std::get<0>(p) << ", " << std::get<1>(p) << ", " << std::get<2>(p) << ")");
    LOG("Current items in bin:");
    LOG("Number of items: " << items.size());
    for (int rotation : rotations) {
        item.setRotationType(static_cast<RotationType>(rotation));
        auto d = item.getDimension();

        if (getWidth() < std::get<0>(p) + d[0] || 
            getHeight() < std::get<1>(p) + d[1] || 
            getDepth() < std::get<2>(p) + d[2]) {
            LOG("Item does not fit with rotation: " << rotation << "   " << item.getName());
            fit = false;
        } else {
            fit = true;
            for (const auto& otherItem : items) {
                if (otherItem.get().doesIntersect(item)) {
                    LOG("Item intersects with another item");
                    fit = false;
                    break;
                }
            }

            if (fit) {
                items.push_back(std::ref(item));
                LOG("Item placed successfully");
                // log address of item and the reference to the item in the bin
                LOG("Item address: " << &item);
                LOG("Item reference in bin: " << &(items.back().get()));
            }
        }

        if (fit) {
            break;
        }
    }

    return fit;
}

std::string Bin::toString() const {
    LOG("Converting Bin to string");
    std::ostringstream oss;
    oss << "Bin: " << getName() << " (W x H x D = " << getWidth() << " x " << getHeight() << " x " << getDepth() << ")";
    return oss.str();
}
