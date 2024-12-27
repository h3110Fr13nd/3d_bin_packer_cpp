#include "bin.h"
#include <cmath>
#include <algorithm>
#include <sstream>
#include <iostream>
#include <functional> 

Bin::Bin(const std::string& name, float w, float h, float d) 
    : Box(name, w, h, d) {
}

const std::vector<std::reference_wrapper<Item>>& Bin::getItems() const {
    return items;
}

void Bin::setItems(const std::vector<std::reference_wrapper<Item>>& items) {
    this->items = items;
}

void Bin::addItem(Item& item) {
    items.push_back(std::ref(item));
}

float Bin::scoreRotation(const Item& item, int rotationType) const {
    Item rotatedItem = item;
    rotatedItem.setRotationType(static_cast<RotationType>(rotationType));
    auto d = rotatedItem.getDimension();

    if (getWidth() < d[0] || getHeight() < d[1] || getDepth() < d[2]) {
        return 0;
    }

    float widthScore = std::pow(d[0] / getWidth(), 2);
    float heightScore = std::pow(d[1] / getHeight(), 2);
    float depthScore = std::pow(d[2] / getDepth(), 2);

    float score = widthScore + heightScore + depthScore;
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
    bool fit = false;
    auto rotations = getBestRotationOrder(item);

    item.setPosition({std::get<0>(p), std::get<1>(p), std::get<2>(p)});
    for (int rotation : rotations) {
        item.setRotationType(static_cast<RotationType>(rotation));
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

        if (fit) {
            break;
        }
    }

    return fit;
}

std::string Bin::toString() const {
    std::ostringstream oss;
    oss << "Bin: " << getName() << " (W x H x D = " << getWidth() << " x " << getHeight() << " x " << getDepth() << ")";
    return oss.str();
}
