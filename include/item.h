// item.h
#pragma once

#include <string>
#include <vector>
#include <map>
#include <ostream>
#include "box.h"

enum class RotationType {
    whd,
    hwd,
    hdw,
    dhw,
    dwh,
    wdh
};

enum class Axis {
    width,
    height,
    depth
};

enum class HeightConstraintType {
    MAXIMUM, // Height is a maximum value
    EXACT    // Height must be exactly filled
};

const std::map<RotationType, std::string> ROTATION_TYPE_STRINGS = {
    {RotationType::whd, "(w, h, d)"},
    {RotationType::hwd, "(h, w, d)"},
    {RotationType::hdw, "(h, d, w)"},
    {RotationType::dhw, "(d, h, w)"},
    {RotationType::dwh, "(d, w, h)"},
    {RotationType::wdh, "(w, d, h)"}
};

inline size_t axisToIndex(Axis axis) {
    switch (axis) {
        case Axis::width: return 0;
        case Axis::height: return 1;
        case Axis::depth: return 2;
        default: return 0;
    }
}

class Item : public Box {
public:
    // Updated constructor with stuffing parameters and new constraints
    Item(const std::string& name, 
         long w, 
         long h, 
         long d,
         const std::vector<RotationType>& allowed_rotations = {},
         const std::string& color = "#000000", float weight = 0.0f,
         int stuffing_layers = 0, float stuffing_max_weight = 0, long stuffing_height = 0,
         bool bottom_load_only = false, bool disable_stacking = false);

    const std::vector<RotationType>& getAllowedRotations() const;
    RotationType getRotationType() const;
    void setRotationType(RotationType type);

    const std::tuple<long, long, long>& getPosition() const;
    void setPosition(const std::tuple<long, long, long>& position);

    std::string getRotationTypeString() const;
    std::vector<long> getDimension() const;
    std::vector<long> getPos() const;

    bool doesIntersect(const Item& other) const;

    bool operator==(const Item& other) const;

    friend std::ostream& operator<<(std::ostream& os, const Item& item);

    // New stuffing getter/setter methods
    int getStuffingLayers() const;
    void setStuffingLayers(int layers);
    float getStuffingMaxWeight() const;
    void setStuffingMaxWeight(float max_weight);
    long getStuffingHeight() const;
    void setStuffingHeight(long height);

    bool isHeightConstrained() const;
    void setHeightConstraint(bool value, long heightValue);
    long getHeightConstraintValue() const;
    HeightConstraintType getHeightConstraintType() const;
    void setHeightConstraintType(HeightConstraintType type);

    // New constraint getter/setter methods
    bool isBottomLoadOnlyEnabled() const;
    void setBottomLoadOnly(bool value);
    bool isDisableStackingEnabled() const;
    void setDisableStacking(bool value);

    std::vector<RotationType> _allowed_rotations;
    std::tuple<long, long, long> _position;
    RotationType _rotation_type;
    std::string color;
    float weight;
    int _stuffing_layers;           // Number of stuffing layers
    float _stuffing_max_weight;     // Maximum weight for stuffing
    long _stuffing_height;          // Stuffing height in mm

private:
    bool height_constrained = false;
    long height_constraint_value = 0;
    HeightConstraintType height_constraint_type = HeightConstraintType::MAXIMUM;
    bool bottom_load_only = false;  // New: item must be placed at the bottom of the container
    bool disable_stacking = false;  // New: nothing can be stacked on top of this item
};

bool rectIntersect(const Item& item1, const Item& item2, Axis x, Axis y);

