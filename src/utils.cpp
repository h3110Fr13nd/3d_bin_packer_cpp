#include "utils.h"
#include <cmath>

const int FACTOR = 1;

int factored_integer(double value) {
    return static_cast<int>(round(value * pow(10, FACTOR)));
}
