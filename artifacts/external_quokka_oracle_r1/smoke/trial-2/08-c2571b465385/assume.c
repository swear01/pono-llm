/*
Geometric Series
computes x = sum(z^k)[k=0..k-1], y = z^(k-1)
*/

extern void abort(void);
extern void __assert_fail(const char *, const char *, unsigned int, const char *) __attribute__((__nothrow__, __leaf__)) __attribute__((__noreturn__));
void reach_error() { __assert_fail("0", "geo2-ll.c", 8, "reach_error"); }
extern int __VERIFIER_nondet_int(void);
extern void abort(void);
void assume_abort_if_not(int cond) {
    if (!cond) {
        abort();
    }
}
void __VERIFIER_assert(int cond) {
    if (!(cond)) {
    ERROR : { reach_error(); }
    }
    return;
}

int counter = 0;
int main() {
    int z, k;
    unsigned long long x, y, c;
    z = __VERIFIER_nondet_int();
    k = __VERIFIER_nondet_int();

    x = 1;
    y = 1;
    c = 1;

    while (counter++ < 5) {
    __VERIFIER_assume((((((((((x * z + 18446744073709551615 * x + 1 + 18446744073709551615 * y * z) % 18446744073709551616 == 0 && (18446744073709551615 * y * z * z * z * z + x * z * z * z * z + 18446744073709551615 * x * z * z * z + z * z * z) % 18446744073709551616 == 0) && (x * z * z + 18446744073709551615 * x * z + 18446744073709551615 * y * z * z + z) % 18446744073709551616 == 0) && 4 <= counter) && (18446744073709551615 * x * z * z + 18446744073709551615 * y * z * z * z + x * z * z * z + z * z) % 18446744073709551616 == 0) || (((2 <= counter && 0 <= z + 2147483648) && y == z * z) && x == z + 1 + z * z)) || (((0 <= z + 2147483648 && z + 1 + z * z + z * z * z == x) && y == z * z * z) && 3 <= counter)) || ((((y == z && 0 <= z + 2147483648) && counter <= 1) && 1 <= counter) && x == z + 1)) || ((((0 <= z + 2147483648 && 0 <= counter) && x == 1) && counter <= 0) && y == 1)) || ((((x * z + 18446744073709551615 * x + 1 + 18446744073709551615 * y * z) % 18446744073709551616 == 0 && (x * z * z + 18446744073709551615 * x * z + 18446744073709551615 * y * z * z + z) % 18446744073709551616 == 0) && 5 <= counter) && (18446744073709551615 * x * z * z + 18446744073709551615 * y * z * z * z + x * z * z * z + z * z) % 18446744073709551616 == 0));

        if (!(c < k)) {
            break;
        }

        c = c + 1;
        x = x * z + 1;
        y = y * z;
    }
    __VERIFIER_assert(1 + x * z - x - z * y == 0);
    return 0;
}
