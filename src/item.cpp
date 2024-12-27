#include "item.h"
#include <iostream>

// Single constructor without default arguments
Item::Item(const std::string& name, long w, long h, long d,
           const std::vector<RotationType>& allowed_rotations,
           const std::string& color)
    : Box(name, w, h, d),
      _allowed_rotations(allowed_rotations.empty() ? std::vector<RotationType>{
          RotationType::whd,
          RotationType::hwd,
          RotationType::hdw,
          RotationType::dhw,
          RotationType::dwh,
          RotationType::wdh
      } : allowed_rotations),
      _rotation_type(_allowed_rotations[0]),
      color(color.empty() ? "#000000" : color) {
    _position = std::tuple<long, long, long>{0, 0, 0};
}

const std::vector<RotationType>& Item::getAllowedRotations() const {
    return _allowed_rotations;
}

RotationType Item::getRotationType() const {
    return _rotation_type;
}

void Item::setRotationType(RotationType type) {
    _rotation_type = type;
}

const std::tuple<long, long, long>& Item::getPosition() const {
    return _position;
}

void Item::setPosition(const std::tuple<long, long, long>& position) {
    _position = position;
}

std::string Item::getRotationTypeString() const {
    return ROTATION_TYPE_STRINGS.at(_rotation_type);
}

std::vector<long> Item::getDimension() const {
    switch (_rotation_type) {
        case RotationType::whd:
            return {width, height, depth};
        case RotationType::hwd:
            return {height, width, depth};
        case RotationType::hdw:
            return {height, depth, width};
        case RotationType::dhw:
            return {depth, height, width};
        case RotationType::dwh:
            return {depth, width, height};
        case RotationType::wdh:
            return {width, depth, height};
        default:
            return {width, height, depth};
    }
}

template <size_t X, size_t Y>
bool rectIntersectImpl(const Item& item1, const Item& item2) {
    const auto& d1 = item1.getDimension();
    const auto& d2 = item2.getDimension();
    const auto& p1 = item1.getPosition();
    const auto& p2 = item2.getPosition();

    // Calculate center points using position and dimensions
    float cx1 = std::get<X>(p1) + d1[X] / 2.0f;
    float cy1 = std::get<Y>(p1) + d1[Y] / 2.0f;
    float cx2 = std::get<X>(p2) + d2[X] / 2.0f;
    float cy2 = std::get<Y>(p2) + d2[Y] / 2.0f;

    // Calculate intersection distances using max-min
    float ix = std::max(cx1, cx2) - std::min(cx1, cx2);
    float iy = std::max(cy1, cy2) - std::min(cy1, cy2);

    // Check if boxes overlap in both dimensions
    return ix < (d1[X] + d2[X]) / 2.0f && 
           iy < (d1[Y] + d2[Y]) / 2.0f;
}

bool rectIntersect(const Item& item1, const Item& item2, Axis x, Axis y) {
    if (x == Axis::width && y == Axis::height) {
        return rectIntersectImpl<0, 1>(item1, item2);
    } else if (x == Axis::height && y == Axis::depth) {
        return rectIntersectImpl<1, 2>(item1, item2);
    } else if (x == Axis::width && y == Axis::depth) {
        return rectIntersectImpl<0, 2>(item1, item2);
    }
    return false;
}

bool Item::doesIntersect(const Item& other) const {
    // Check intersection in all three planes
    bool xy = rectIntersect(*this, other, Axis::width, Axis::height);
    bool yz = rectIntersect(*this, other, Axis::height, Axis::depth);
    bool xz = rectIntersect(*this, other, Axis::width, Axis::depth);
    return xy && yz && xz;
}

bool Item::operator==(const Item& other) const {
    return this == &other;
}

std::ostream& operator<<(std::ostream& os, const Item& item) {
    os << "Item: " << item.name << " (" << item.getRotationTypeString() << " = ";
    const auto& dim = item.getDimension();
    os << dim[0] << " x " << dim[1] << " x " << dim[2] << ")";
    return os;
}