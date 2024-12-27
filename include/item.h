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
    // Single constructor with default arguments
    Item(const std::string& name, 
         long w, 
         long h, 
         long d,
         const std::vector<RotationType>& allowed_rotations = {},
         const std::string& color = "#000000");

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
    std::vector<RotationType> _allowed_rotations;
    std::tuple<long, long, long> _position;
    RotationType _rotation_type;
    std::string color;

private:
};

bool rectIntersect(const Item& item1, const Item& item2, Axis x, Axis y);

