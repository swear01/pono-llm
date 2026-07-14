/* algorithm for computing the product of two natural numbers */

extern void abort(void);
extern void __assert_fail(const char *, const char *, unsigned int,
                          const char *) __attribute__((__nothrow__, __leaf__))
__attribute__((__noreturn__));
void reach_error() { __assert_fail("0", "prod4br-ll.c", 5, "reach_error"); }
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
    long long a, b, p, q;

    x = __VERIFIER_nondet_int();
    assume_abort_if_not(x >= 0 && x <= 2);
    y = __VERIFIER_nondet_int();
    assume_abort_if_not(y >= 0 && y <= 2);
    assume_abort_if_not(y >= 1);

    a = x;
    b = y;
    p = 1;
    q = 0;

    while (1) {
    __VERIFIER_assert(((((((((((((((0 <= b && q == x * y) && 0 <= x) && y <= 2) && 1 <= y) && b <= 1) && a <= 2) && (q + b * p == x * y || !(a == 1))) && 0 <= a) && (q == x * y || (!(b == 0) && !(a == 0)))) && x <= 2) && (!(a % 2 <= 0) || a == 0)) || (((((((((0 <= x && y <= 2) && 1 <= y) && a <= 2) && (q + b * p == x * y || !(a == 1))) && a <= 0) && 0 <= a) && (q == x * y || (!(b == 0) && !(a == 0)))) && x <= 2) && (!(a % 2 <= 0) || a == 0))) || ((((((((((0 <= x && y <= 2) && 1 <= y) && a <= 2) && (q + b * p == x * y || !(a == 1))) && 0 <= b + 1) && (b + 1) % 2 == 1) && 0 <= a) && (q == x * y || (!(b == 0) && !(a == 0)))) && 2 * b <= 1) && x <= 2)) || (((((((((((0 <= x && y <= 2) && 1 <= y) && a <= 2) && (q + b * p == x * y || !(a == 1))) && b == y / 2) && q == 0) && 0 <= a) && (q == x * y || (!(b == 0) && !(a == 0)))) && x <= 2) && (!(a % 2 <= 0) || a == 0)) && x % 2 <= 0)) || (((((((p == 1 && y <= 2) && 1 <= y) && b == y) && q == 0) && 0 <= a) && a == x) && x <= 2));

        if (!(a != 0 && b != 0)) {
            break;
        }

        if (a % 2 == 0 && b % 2 == 0) {
            a = a / 2;
            b = b / 2;
            p = 4 * p;
        } else if (a % 2 == 1 && b % 2 == 0) {
            a = a - 1;
            q = q + b * p;
        } else if (a % 2 == 0 && b % 2 == 1) {
            b = b - 1;
            q = q + a * p;
        } else {
            a = a - 1;
            b = b - 1;
            q = q + (a + b + 1) * p; /*fix a bug here---  was (a+b-1)*/
        }
    }

    return 0;
}
