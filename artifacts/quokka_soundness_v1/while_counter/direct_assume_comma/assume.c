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
  while (x < 2) {
  __VERIFIER_assume((__VERIFIER_assume(0), 1));
    x++;
  }
  __VERIFIER_assert(x != 2);
  return 0;
}
