#include <cstdio>
#include <cstdlib>
#include <ios>

extern "C" {

long __isoc23_strtol(const char *nptr, char **endptr, int base) {
    return strtol(nptr, endptr, base);
}

long long __isoc23_strtoll(const char *nptr, char **endptr, int base) {
    return strtoll(nptr, endptr, base);
}

unsigned long __isoc23_strtoul(const char *nptr, char **endptr, int base) {
    return strtoul(nptr, endptr, base);
}

unsigned long long __isoc23_strtoull(const char *nptr, char **endptr, int base) {
    return strtoull(nptr, endptr, base);
}

int __isoc23_fscanf(FILE *stream, const char *format, ...) {
    (void)stream;
    (void)format;
    return -1;
}

}

namespace std {
    void ios_base_library_init() {}
}
