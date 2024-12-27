#ifndef BOX_H
#define BOX_H

#include <string>

class Box {
public:
    Box(const std::string& name, long width, long height, long depth);
    
    std::string name;
    long width;
    long height;
    long depth;
    std::string getName() const;
    long getWidth() const;
    long getHeight() const;
    long getDepth() const;
    long getVolume() const;

};

#endif // BOX_H
