/*
  Cohen's integer division
  returns x % y
  http://www.cs.upc.edu/~erodri/webpage/polynomial_invariants/cohendiv.htm
*/
extern void abort(void);
extern void __assert_fail(const char *, const char *, unsigned int, const char *) __attribute__((__nothrow__, __leaf__)) __attribute__((__noreturn__));
void reach_error() { __assert_fail("0", "cohendiv-ll.c", 8, "reach_error"); }
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

int main() {
    int x, y;
    long long q, r, a, b;

    x = __VERIFIER_nondet_int();
    assume_abort_if_not(x >= 0 && x <= 5);
    y = __VERIFIER_nondet_int();
    assume_abort_if_not(y >= 0 && y <= 5);

    assume_abort_if_not(y >= 1);

    q = 0;
    r = x;
    a = 0;
    b = 0;

    while (1) {
    __VERIFIER_assume(((((r + 1 <= y && b <= y) && !((x == q * y + r) == 0)) || (((((((((2 * b <= r || r < b + y) && 0 <= x) && 1 <= y) && r <= 5) && r == x) && q == 0) && (b * 8 <= r || r < b * 4 + y)) && (b * 4 <= r || r < 2 * b + y)) && (!(b + y <= r) || b + x == a * y + r + q * y))) || ((((((x <= 5 && 0 <= x) && x == r + q * y) && 1 <= y) && (x == q * y + r) == 1) && r < b + y) && 2 * r <= 4)) || ((((x <= 5 && 0 <= x) && 1 <= y) && !(y <= r)) && !((x == q * y + r) == 0)));

        if (!(r >= y)) {
            break;
        }
        a = 1;
        b = y;

        while (1) {
            __VERIFIER_assert(x == q * y + r);

            if (!(r >= 2 * b)) {
                break;
            }

            a = 2 * a;
            b = 2 * b;
        }
        r = r - b;
        q = q + a;
    }

    return 0;
}
