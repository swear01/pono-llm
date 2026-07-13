# Gate 4B0-v2 — Baseline-First Natural C2

**Frozen:** 2026-07-13
**Status:** complete — **STOP**

The historical Gate 4B0-v1 result is preserved but not reused. V2 selected the
lowest structurally eligible nonlinear-equality row from six natural cases in
`artifacts/phase1_2_frozen_v2/` before observing solver results: egcd row 1,
hard row 0, lcm1-unwind row 0, lcm1-value row 4, lcm2 row 0, and prodbin row 0.
They represent four family labels; repeated lcm variants count once.

Eligibility requires equal-width scalar state references, equality residuals,
genuine state-by-state multiplication, functional complete next substitutions,
and only `add/sub/mul/neg` in the relevant single-branch next cone. Mixed width,
extensions, concat/extract, arrays, division/remainder, shifts, inequalities,
`ite`, missing next, and unknown variables reject. `fib_23/30` remain controls.

The exact obligation is `H && Constraints && Transition && !H'`. Only UNSAT is
a proof; SAT, UNKNOWN, timeout, unsupported, and unavailable remain distinct.
The future certificate identity would be
`P_i(T_b)=sum_j Q_i,j,b*P_j mod 2^w`, but no v1 kernel was imported or run.

Every available arm returned SAT in all five trials per case: direct
`candidate_cert_check`, local Z3 default, and local Z3 integer blasting. Direct
medians are below 1ms and CLI medians below 20ms. The pinned `/tmp/z3-poly`
checkout was absent and is explicitly unavailable without replacement.

**Decision:** stop before kernel implementation. This result proves only that
the frozen conjunctions are not 1-inductive. It does not distinguish false
candidates, k-induction, missing support, Boolean/guard structure, selection,
or property insufficiency; that distinction is delegated to a new independent
Inductiveness-Gap Decomposition gate.

Canonical artifact: `artifacts/algebraic_baseline_v2/`.
Summary hash: `877890dd219ea2e5750d955b38fa5c045dfa32c0b4c0e98160ffbfcf86e1c71d`.
Integrity hash: `751c181dfcbcc69842e3b628a7300fefa4663f0797b53e4c6dd32e48d5690d7f`.

No LLM call, paid capture, kernel expansion, new solver installation, natural
population expansion, or Pono C++ change is authorized by this gate.
