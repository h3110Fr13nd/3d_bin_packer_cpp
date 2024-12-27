#include "utils.h"
#include <cmath>

const long FACTOR = 0;

long factored_integer(double value) {
    return static_cast<long>(round(value * pow(10, FACTOR)));
}
