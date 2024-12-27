#include "item.h"
#include <iostream>

// Single constructor without default arguments
Item::Item(const std::string& name, float w, float h, float d,
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
    _position = {0, 0, 0};
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

const std::vector<float>& Item::getPosition() const {
    return _position;
}

void Item::setPosition(const std::vector<float>& position) {
    _position = position;
}

std::string Item::getRotationTypeString() const {
    return ROTATION_TYPE_STRINGS.at(_rotation_type);
}

std::vector<float> Item::getDimension() const {
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

bool rectIntersect(const Item& item1, const Item& item2, Axis x, Axis y) {
    const auto& d1 = item1.getDimension();
    const auto& d2 = item2.getDimension();
    const auto& p1 = item1.getPosition();
    const auto& p2 = item2.getPosition();

    size_t xIndex = axisToIndex(x);
    size_t yIndex = axisToIndex(y);
    std::cout << "xIndex: " << xIndex << ", yIndex: " << yIndex << ", p1[xIndex]: " << p1[xIndex] 
              << ", d1[xIndex]: " << d1[xIndex] << ", p2[xIndex]: " << p2[xIndex] 
              << ", d2[xIndex]: " << d2[xIndex] << std::endl;
    // Calculate center points using position and dimensions
    float cx1 = p1[xIndex] + d1[xIndex] / 2;
    float cy1 = p1[yIndex] + d1[yIndex] / 2;
    float cx2 = p2[xIndex] + d2[xIndex] / 2;
    float cy2 = p2[yIndex] + d2[yIndex] / 2;

    // Calculate intersection distances using max-min
    float ix = std::max(cx1, cx2) - std::min(cx1, cx2);
    float iy = std::max(cy1, cy2) - std::min(cy1, cy2);

    // Check if boxes overlap in both dimensions
    return ix < (d1[xIndex] + d2[xIndex]) / 2 && 
           iy < (d1[yIndex] + d2[yIndex]) / 2;
}

bool Item::doesIntersect(const Item& other) const {
    // Check intersection in all three planes
    bool xy = rectIntersect(*this, other, Axis::width, Axis::height);
    bool yz = rectIntersect(*this, other, Axis::height, Axis::depth);
    bool xz = rectIntersect(*this, other, Axis::width, Axis::depth);
    std::cout << "Checking intersection between " << *this << " and " << other << std::endl;
    std::cout << "Width x Height: " << rectIntersect(*this, other, Axis::width, Axis::height) << std::endl;
    std::cout << "Height x Depth: " << rectIntersect(*this, other, Axis::height, Axis::depth) << std::endl;
    std::cout << "Width x Depth: " << rectIntersect(*this, other, Axis::width, Axis::depth) << std::endl;
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