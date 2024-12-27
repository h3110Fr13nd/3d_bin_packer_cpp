#include "box.h"
#include "utils.h"

Box::Box(const std::string& name, long width, long height, long depth)
    : name(name), width(factored_integer(width)), height(factored_integer(height)), depth(factored_integer(depth)) {}

long Box::getVolume() const {
    return width * height * depth;
}

std::string Box::getName() const {
    return name;
}

long Box::getWidth() const {
    return width;
}

long Box::getHeight() const {
    return height;
}

long Box::getDepth() const {
    return depth;
}
