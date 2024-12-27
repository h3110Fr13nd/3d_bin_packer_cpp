#ifndef BOX_H
#define BOX_H

#include <string>

class Box {
public:
    Box(const std::string& name, float width, float height, float depth);
    
    std::string name;
    float width;
    float height;
    float depth;
    std::string getName() const;
    float getWidth() const;
    float getHeight() const;
    float getDepth() const;
    float getVolume() const;

};

#endif // BOX_H
