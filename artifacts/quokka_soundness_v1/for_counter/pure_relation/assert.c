extern void __VERIFIER_error(void);
extern void __VERIFIER_assume(int);

void __VERIFIER_assert(int cond) {
  if (!(cond)) {
    ERROR: __VERIFIER_error();
  }
}

int prune_and_true(void) {
  __VERIFIER_assume(0);
  return 1;
}
#define PRUNE_TRUE() (__VERIFIER_assume(0), 1)
int main(void) {
  int x = 0;
  for (; x < 3; ++x) {
  __VERIFIER_assert(x >= 0);
    int snapshot = x;
    (void)snapshot;
  }
  return 0;
}
