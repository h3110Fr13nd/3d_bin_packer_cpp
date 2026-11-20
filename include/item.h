// item.h
#pragma once

#include <string>
#include <vector>
#include <map>
#include <ostream>
#include <array>
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

// Physical shape of an item. Packing always treats an item as its w x h x d
// box (shaped goods ship in a thin carton of that size); the shape is only
// used to draw the item as it really is. Cylinders, cones and pyramids stand
// on their base with the axis / apex along the item's height; round shapes
// fill the w x d footprint (an ellipse when w != d).
enum class Shape {
    Box,
    Sphere,
    Pyramid,
    Cone,
    Cylinder
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

// All six axis permutations, in declaration order.
const std::vector<RotationType> ALL_ROTATIONS = {
    RotationType::whd, RotationType::hwd, RotationType::hdw,
    RotationType::dhw, RotationType::dwh, RotationType::wdh
};

// Rotations that keep the item's original height axis vertical
// ("this side up"): the item may only spin around the vertical axis.
const std::vector<RotationType> UPRIGHT_ROTATIONS = {
    RotationType::whd, RotationType::dhw
};

// Placed (x, y, z) extents of a w x h x d box under the given rotation.
inline std::array<long, 3> rotatedDimensions(long w, long h, long d, RotationType r) {
    switch (r) {
        case RotationType::whd: return {w, h, d};
        case RotationType::hwd: return {h, w, d};
        case RotationType::hdw: return {h, d, w};
        case RotationType::dhw: return {d, h, w};
        case RotationType::dwh: return {d, w, h};
        case RotationType::wdh: return {w, d, h};
    }
    return {w, h, d};
}

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
         bool bottom_load_only = false, bool disable_stacking = false,
         bool upright = false, float value = 0.0f, int priority = 0,
         const std::string& group = "", Shape shape = Shape::Box, bool crate_required = false);

    const std::vector<RotationType>& getAllowedRotations() const;
    // Rotations the packer may actually use: allowed_rotations, further
    // restricted to UPRIGHT_ROTATIONS when the item is marked upright.
    std::vector<RotationType> getEffectiveRotations() const;
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
    // "This side up": the original height axis must stay vertical.
    bool isUpright() const;
    void setUpright(bool value);

    // Commercial data used when not everything fits (see PackingConfig::objective).
    float value = 0.0f;          // revenue / profit of shipping this item
    int priority = 0;            // higher priorities are loaded before any lower one
    std::string group;           // consignment id: a group ships complete in one bin, or not at all
    std::string unfit_reason;    // set by Packer::pack() on items that could not be loaded
    Shape shape = Shape::Box;    // drawn shape; packed as its box either way (see Shape)
    bool crate_required = false; // must travel inside a crate: Packer::pack() never loads it loose
    int crate_index = -1;        // >= 0: this item is a filled crate (index into the crate plan, Python side)

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
    bool bottom_load_only = false;  // item must be placed on the container floor
    bool disable_stacking = false;  // nothing can be stacked on top of this item
    bool upright = false;           // only rotations around the vertical axis
};

bool rectIntersect(const Item& item1, const Item& item2, Axis x, Axis y);

