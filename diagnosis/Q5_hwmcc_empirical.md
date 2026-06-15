# Q5: HWMCC Empirical Benchmark Results

**Date**: 2026-06-15  
**Goal**: Empirically test DeepSeek capability limits on real HWMCC benchmarks — find what it can and cannot do, rather than assuming it's strong.

---

## Setup

- Model: `deepseek-v4-pro` via sidecar.py, `reasoning_effort='none'` (thinking mode disabled)
- Engine: `ic3ia --llm-gen-mode semantic`
- Stage 0 timeout: 200s; Stage 2 timeout: 30s; max-requests: 4
- Baseline: IC3IA without LLM

---

## Benchmark Results

### 1. ab_sync.btor2 (synthetic)

**Structure**: Counters a, b (8-bit, init=0) both increment on same reset. c = top bit of (a XOR b). Property: c==0.

**Baseline**: Never terminates (14+ CEGAR rounds, timeout).

**Guided**: Stage 0 returns `eq(a, b)` as candidate #1. Injected → proved with **0 CEGAR rounds** in ~36s.

**Verdict**: ✓ CLASS-A. Symmetry between a and b is obvious (both init=0, depend only on i_reset).

---

### 2. fib_05.btor2 (HWMCC 2025, HKUST arithmetic)

**Structure**: 4 states, all 16-bit init=0:
- j, i: accumulators. j += y+{1,2} when j<300; i += x+1 when j<300.
- x, y: counters. Both increment by 1 when j<300.

**Property**: j ≥ i always (bad when j < i).

**Baseline**: TIMES OUT (120s+, only 3 of 30+ CEGAR rounds done).

**Guided (first attempt, no symmetry hint)**: DeepSeek missed eq(x,y) — returned only trivial bounds (uge(x,0), ule(j,65535)). Still timed out.

**Guided (with symmetry detection)**: x and y have identical init=0 and identical transition deps → symmetry hint added to prompt. DeepSeek returned `eq(state15, state17)` as candidate #2. Injected → proved with **0 CEGAR rounds** in **27.8s**.

**Verdict**: ✓ CLASS-A. eq(x,y) is the key invariant. Two engineering fixes were required:
1. **Secondary hot variables**: x, y were 10+ combinational hops from bad node — only reachable via j/i's transition formulas. Fixed by extending BFS through each hot state's next-expression.
2. **Symmetry detection**: same-init + same-dep pairs get an explicit "eq(stateA, stateB) is likely inductive" hint in the prompt. Without this hint, DeepSeek missed the equality.

---

### 3. fib_23.btor2 (HWMCC 2025, HKUST arithmetic)

**Structure**: 3 states (i, n=150, sum), all 19-bit. Counts 0..149 accumulating sum.

**Baseline**: 7 CEGAR rounds, ~103s. All rounds discover bit-extraction predicates about i's exact bit pattern (e.g. bit7(i)=0 when i≤150).

**Guided**: Stage 0 injects `ule(i, n)` and `uge(sum, i)` — correct algebraic invariants. Saves 2 CEGAR rounds (7→5). But with max-requests=8, Stage 2 call overhead dominates and total time exceeds 400s.

**Guided (max-requests=4)**: Still timed out at 120s with 6 CEGAR rounds → Stage 2 overhead + remaining bit-level CEGAR both contribute.

**Verdict**: ⚠ CLASS-B. LLM correctly identifies high-level arithmetic invariants. But bit-level predicates (i's exact bit pattern for i≤150) remain, and Stage 2 overhead makes guided slower than baseline in practice.

**Root limit**: Predicate abstraction requires explicit bit-extraction predicates to reason about exact bitvector ranges. LLM cannot predict these without knowing the binary representation of n=150.

---

### 4. stack-p2.btor2 (HWMCC 2024, mann)

**Structure**: Stack equality verification, 145 state variables.

**Baseline**: 1 CEGAR round, ~7s (12 predicates added — mostly bit-level).

**Guided**: Stage 0 correctly returns `eq(state27, state30)` — but it's insufficient. CEGAR still needs 11 more bit-level predicates about the deep stack arrays (state1555, state1577).

**Verdict**: ⚠ CLASS-C. Correct predicate identified but insufficient. LLM overhead (>100s Stage 0) makes guided much slower than baseline.

---

### 5. rast-p10.btor2 (HWMCC 2024, mann)

**Baseline**: 0 CEGAR rounds, ~6s.

**Verdict**: ℹ TRIVIAL. Nothing to help.

---

## Summary Table

| Benchmark | Baseline | Guided | CEGAR Δ | Verdict |
|-----------|----------|--------|---------|---------|
| ab_sync | timeout (14+ rounds) | **unsat 36s** | ∞ → 0 | ✓ CLASS-A |
| fib_05 | timeout (3/30+ rounds) | **unsat 28s** | ∞ → 0 | ✓ CLASS-A |
| fib_23 | 7 rounds, 103s | timeout (Stage 2 overhead) | 7 → 5 (net worse) | ⚠ CLASS-B |
| stack-p2 | 1 round, 7s | 1 round, 117s (LLM overhead) | no change | ⚠ CLASS-C |
| rast-p10 | 0 rounds, 6s | — | — | ℹ TRIVIAL |

---

## Bug Fixes Applied

| Bug | Symptom | Fix |
|-----|---------|-----|
| `reasoning_effort='low'` (thinking mode) | 0 candidates — JSON truncated by 7200 thinking tokens | Changed default to `'none'` |
| BFS depth off-by-one in `hot_refs_near_bad` | States at exactly `depth` hops not collected | Scan `final frontier` after loop |
| Stage 2 max-requests overflow | Each extra trigger wasted 30s waiting | Tuned max-requests to 4 |
| Secondary hot variables missing | x, y in fib_05 invisible to LLM | BFS through each hot state's next-expression (transition_depth=6) |
| Symmetry not communicated to LLM | DeepSeek suggests trivial bounds instead of eq(x,y) | `detect_symmetric_pairs()` adds explicit hint to prompt |
| Mock sidecar wrong AST format | args as strings rejected by parser | Correct format: nested `{"form":"ref","ref":"stateNN"}` nodes |

---

## Key Findings

### What LLM does well
- Identifies structurally obvious equality invariants (a=b, x=y) when given a symmetry hint
- Finds high-level algebraic relationships (i≤n, sum≥i) for arithmetic circuits
- Responds in ~21-25s with `reasoning_effort='none'` — fast enough for Stage 0

### What LLM cannot do
- Predict bit-level predicates (bit7(i)=0, bit8(i)=0...) — these require knowing exact bitvector ranges
- Replace CEGAR when the proof requires 10+ bit-extraction predicates per round
- Help when the benchmark is trivial or when overhead exceeds baseline

### Class-A pattern
Circuits with **structurally symmetric state variables** (same init, same transition deps) where one equality invariant is sufficient to prove the property. With explicit symmetry hints, LLM reliably identifies these.

### Stage 2 overhead problem
Stage 2 is triggered when IC3 gets stuck. Each call takes ~15s. For fib_23 (Class-B), multiple Stage 2 triggers add 45-60s overhead while only saving 2 CEGAR rounds (~28s each). Net result: guided is slower. Needs a better trigger strategy or should be disabled for Class-B cases.

---

## Conclusion

**LLM quality is not the bottleneck** — DeepSeek correctly identifies relevant invariants when given sufficient structural context. **The bottleneck is predicate abstraction**: LLM-suggested high-level predicates only help when they're sufficient to close the proof without bit-level CEGAR. Engineering the prompt (secondary hot vars, symmetry hints) is critical to bridge the gap between what LLM can reason about and what the model checker needs.

**Next directions**:
1. Scan full HWMCC set for more Class-A benchmarks (structural symmetry detector as a filter)
2. Disable Stage 2 for Class-B benchmarks — overhead exceeds savings
3. For Class-C: investigate whether suggesting the deep stack predicates (state1555/state1577 relationships) changes the result
