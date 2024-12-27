#include "log.h"
#include <iostream>

bool is_log_enabled = false;

void enable_log(bool enable) {
    is_log_enabled = enable;
}

void log(const std::string& ns, const std::string& message) {
    if (is_log_enabled) {
        std::cout << "DEBUG: " << ns << " " << message << std::endl;
    }
}
