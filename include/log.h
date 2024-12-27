#ifndef LOG_H
#define LOG_H

#include <string>

extern bool is_log_enabled;

void enable_log(bool enable);
void log(const std::string& ns, const std::string& message);

#endif // LOG_H
