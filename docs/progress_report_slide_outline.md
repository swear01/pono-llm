> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Progress Report Slide Outline

> Keyword-first slide structure. Each section = one slide.
> Bullets = on-slide content. *Italic* = speaker notes.

---

## Slide 1: Title

**LLM-Assisted Semantic Lemma Synthesis for Pono IC3IA Traces**

- Closed-loop solver-guided synthesis
- qspiflash cross-parameter invariant discovered
- First solver-verified useful semantic lemma

*Speaker: This is the progress report for the pono-llm research prototype.
We found a genuinely inductive lemma using solver-in-the-loop LLM synthesis.*

---

## Slide 2: Research Positioning

- **Complementary** to Pono clause generalization (literal deletion, unsat-core)
- **Cluster-level** semantic synthesis: new invariants, not CTI subsets
- **Formal methods as gatekeeper**: LLM proposes, solver verifies
- **Not a prover**: LLM is an untrusted hypothesis generator

---

## Slide 3: Direction Evolution

```
Phase 1: Cube-subset / literal deletion
    ↓ (too close to Pono's built-in generalization)
Phase 2: Template-guided semantic lemma generation
    ↓
Phase 3: Solver feedback + closed-loop convergence
    ↓
Current: First solver-verified useful lemma
```

*Speaker: We started with cube-subset which overlapped with Pono internals,
shifted to cluster-level synthesis, then discovered that single-shot prompting
was insufficient — only iterative solver feedback produced results.*

---

## Slide 4: Pipeline (Flowchart)

```
IC3IA/CTI context
    ↓
LLM candidate generation
    ↓
Gate 1: Reachable filter (solver-free)
    ↓
Gate 2: Nontriviality gate (bitwidth analysis)
    ↓
Gate 3: Init check (light SMT)
    ↓
Gate 4: One-step check (full SMT)
    ↓
Gate 5: Induction check (full SMT)
    ↓
If SAT: extract CE → feed back to LLM → refine
If UNSAT: ACCEPT
```

*Speaker: Three pre-gates filter ~80% of doomed candidates before expensive SMT.
The closed loop is the key innovation that enabled convergence.*

---

## Slide 5: Negative Lessons (5 Single-Shot Experiments)

| Experiment | Result |
|---|---|
| Repair v1/v2 | Trivialization or one-step-fail |
| Resynthesis | Excluded known reachable CE values |
| Reachability-aware | Plausible but not inductive |
| Transition-aware | Structurally better, still one-step-fail |

**Key lesson**: Single-shot prompts are insufficient

*Speaker: Five single-shot experiments produced zero solver-verified useful
lemmas across ~30 total candidates. The LLM cannot infer inductiveness from
prompt context alone.*

---

## Slide 6: Gate Ladder

| Gate | Cost | Catches |
|---|---|---|
| Reachable filter | Zero | False invariants (excludes known reachable) |
| Nontriviality | Zero | Bitwidth tautologies (`<= max_val`, `>= 0`) |
| Init check | Low | Reset-state violations |
| One-step check | High | Non-inductive transition failures |
| Induction check | Highest | Self-induction failures |

- Each gate cheaply rejects candidates before expensive ones
- 80% of doomed candidates caught before SMT

---

## Slide 7: Closed-Loop Success

```
Round 0: 3 state1536-based candidates → all one-step fail
         ↓ 3 CE feedback blocks appended to prompt
Round 1: LLM shifts variables → state2002 ⇒ state790
         ↓
         SOLVER-VERIFIED USEFUL ✓
```

```
Lemma: r_pipe_req ⇒ o_wb_stall
Init: UNSAT | One-step: UNSAT | Induction: UNSAT
Nontrivial | Non-vacuity pass | Consistent with all samples
```

*Speaker: Round 0 failures were all state1536-based (mode register, 667-char
transition logic). CE feedback showed the LLM that state1536 implications
were unreliable. Round 1 the LLM pivoted to state2002/state790 — a genuinely
causal bus-handshake relation.*

---

## Slide 8: Cross-Parameter Validation

6/6 qspiflash variants pass:

| p020 | p027 | p040 | p063 | p114 | p162 |
|---|---|---|---|---|---|
| ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

- Lemma holds independent of clock divider configuration
- Not a quirk of p040 — genuine design invariant
- Same BTOR2 node IDs enable instant validation

---

## Slide 9: Repeatability

| Trials | Target Found | Verified Useful |
|---|---|---|
| 8 | 5 (63%) | 4 (50%) |

- Lemma always found in round 1, never round 0
- CE feedback required for variable shift
- Recommend 3-5 parallel trials for robust discovery

---

## Slide 10: Current Blocker

**IC3IA frame / CTI data unavailable**

- Can't measure clause subsumption
- Can't estimate proof impact
- Can't count CTI violations blocked
- Need minimal Pono C++ dump

---

## Slide 11: Claim and Non-Claim

**Safe claim**:
> Closed-loop synthesis found a nontrivial, solver-verified qspiflash-family invariant under offline Bitwuzla validation.

**Do NOT claim**:
- runtime speedup — benchmark unlock — Pono integration
- rel_ind_check — frame injection — clause impact
- broad generality beyond qspiflash

---

## Slide 12: Next Steps

1. Pono IC3IA frame/CTI dump (blocking)
2. Lemma impact proxy (clause subsumption estimate)
3. If positive: Pono `rel_ind_check` integration
4. Controlled benchmark (lemma-critical design)
5. Multi-benchmark closed-loop synthesis
