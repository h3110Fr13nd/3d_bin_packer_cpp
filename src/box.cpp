#include "box.h"
#include "utils.h"

Box::Box(const std::string& name, float width, float height, float depth)
    : name(name), width(factored_integer(width)), height(factored_integer(height)), depth(factored_integer(depth)) {}

float Box::getVolume() const {
    return width * height * depth;
}

std::string Box::getName() const {
    return name;
}

float Box::getWidth() const {
    return width;
}

float Box::getHeight() const {
    return height;
}

float Box::getDepth() const {
    return depth;
}
