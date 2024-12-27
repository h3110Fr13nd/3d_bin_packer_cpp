#include "utils.h"
#include <cmath>

const int FACTOR = 0;

int factored_integer(double value) {
    return static_cast<int>(round(value * pow(10, FACTOR)));
}
