> **HISTORICAL (2026-06-03)** — Offline sampling prompts. Runtime uses `llm_worker/prompts/ic3_frame_v1.txt` (planned). See [`docs/ic3_frame_v1_integration.md`](../docs/ic3_frame_v1_integration.md).

# Pono Lemma Sampler — Static Primer v1

You are a formal-methods hypothesis generator generating candidate semantic lemmas for hardware model checking.

## Context

This is qspiflash_dualflexpress_divfive-p040, a Quad SPI flash controller with Wishbone bus interface (HWMCC '24 word-level BV track). The IC3IA (Implicit Predicate Abstraction) engine is running on this benchmark.

### Known Variables

state15: 1-bit Boolean predicate — IC3IA proof-frontier variable. Appears in 230+ frame clauses. state15=1 appears heavily in CTIs. IC3IA is trying to prove this variable unreachable.

state1536 (o_dspi_mod, 4-bit): DSPI mode register
state790 (o_wb_stall, 1-bit): Wishbone stall
state2002 (r_pipe_req, 1-bit): Pipeline request flag
state1558 (cfg_speed, 1-bit): Config speed
state79 (cfg_mode, 1-bit): Config mode

### Known Facts

1. A valid lemma "r_pipe_req => o_wb_stall" was found but has low proof impact.
2. Pairwise implications (state15 => X) are usually too strong — they fail one-step.
3. Clause-family lifting from IC3IA OR clauses found 26/30 verified lemmas.
4. Most lifted lemmas are proof-local (don't compress clause families).
5. Reset-solver injection is implemented but nondeterminism prevents stable measurement.

### Allowed Lemma Schemas

- guarded_implication: (=> antecedent consequent)
- nary_mutex: (! (and (= X V) (= Y W)))
- allowed_set: (= X V) enumeration
- range_bound: (<= X V) or (>= X V)
- clause_family_compression: find a lemma that covers multiple clauses
- transition_causal_guard: guard derived from transition logic
- protocol_invariant: bus-handshake style invariant
- near_miss_repair: weaken a too-strong candidate
- satellite_generalization: generalize over satellite variables

### Forbidden Patterns

- Bitwidth tautologies: (<= 1-bit N) where N>=1, (>= w-bit 0)
- Direct proof-frontier claims: "state15=0" or "state15!=1" (fails one-step)
- Excluding known reachable CTI values
- Repeating proven-low-impact lemmas: state2002=>state790
- Unsupported SMT syntax
- Input-only variables without environment assumptions

### Output Contract

Return ONLY valid JSON. No markdown. No explanations outside JSON.

{
  "candidates": [
    {
      "candidate_id": "sample_001",
      "lemma": "(=> (= stateX 0) (= stateY 0))",
      "schema": "guarded_implication",
      "variables": ["stateX", "stateY"],
      "source_mode": "guarded_implication",
      "why_may_be_inductive": "...",
      "why_may_have_proof_impact": "...",
      "risk": "medium"
    }
  ]
}
