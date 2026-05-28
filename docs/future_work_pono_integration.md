# Pono Integration: Future Work

## Current Status (2026-05-28, updated after BTOR2 translation fix)

### Translation Status

**Transition translation is now mostly working.** 218/247 transitions (88%)
translate successfully after fixing 3 BTOR2 translator bugs. All 5 shortlisted
solver-validation candidates can now generate init, one-step, and induction
queries.

### What Works
- Variable identification: stateNN → BTOR2 node → Verilog symbol (via `symbol_map_`)
- Init values: 216/249 states have init values available
- Init checks: 4/5 solver-validation candidates pass init (UNSAT), confirmed post-fix
- **One-step checks: 4/5 candidates produce SAT (lemma too strong, transition-violable)**
- **Induction checks: 4/5 candidates produce SAT (not inductive)**
- Transition translation: 218/247 transitions (88%)
- 18+ BTOR2 operators supported

### What Doesn't Work
- Full transition translation: 29/247 lines still fail (node-208 redor cascade, non-target)
- Solver-verified lemmas: 0/5 candidates are solver-inductive (all are init-safe but transition-violable)
- Input-lemma validation: Candidate 5 (i_wb_data) still fails lemma parser
- SAT model extraction: counterexample models not extracted for repair-loop feedback

### Bugs Fixed (Task 63)

| Bug | Root Cause | Fix |
|---|---|---|
| slice OOB | hi >= src_w rejected | Zero-extend source before extraction |
| uext source index | `t(p[3])` instead of `t(p[2])` | Fixed to correct argument index |
| Boolean/BV mismatch | eq/ult/ulte return Boolean | Wrapped in ITE to produce 1-bit BV |

### What Doesn't Work
- Full transition translation for target states
- One-step and induction checks for real HWMCC candidates
- Input-lemma validation (primary inputs lack environment assumptions)

## Minimal C++ Dump Needed for Solver-Backed Validation

To validate IC3IA-generated or LLM-generated candidate lemmas outside Pono, the prototype needs a dump mapping:

- IC3IA label, e.g. `state1536`
- bitwidth
- kind: state / input / derived predicate
- current-state SMT expression
- next-state SMT expression
- BTOR2 node id or original symbol if available

Minimal JSON format:

```json
{
  "state1536": {
    "bitwidth": 4,
    "kind": "state",
    "current_expr": "state1536",
    "next_expr": "<SMT-LIB2 transition expression>",
    "btor2_node": "1536",
    "verilog_symbol": "o_dspi_mod"
  }
}
```

Location in Pono to add the dump:

1. **BTOR2 Encoder** (`frontends/btor2_encoder.cpp:312`): The `symbol_map_[new_symbol] = orig_symbol` already stores the mapping. Export this as JSON after BTOR2 loading.

2. **IC3IA** (`engines/ic3ia.cpp`): After `register_symbol_mappings()` (line 490), dump the predicate label → solver term mapping.

3. **Simplest approach**: At BTOR2 encode time, write a JSON file alongside the BTOR2 file:
   ```cpp
   {
     "state1536": {
       "width": 4,
       "symbol": "o_dspi_mod",
       "node_id": 1536
     }
   }
   ```

   Then at IC3IA CTI export time, include the BTOR2 node ID in each literal's metadata:
   ```json
   {
     "literals": [
       {"varname": "state1536 = 10", "btor2_id": 1536, "verilog": "o_dspi_mod"}
     ]
   }
   ```

## Alternative: Use Bitwuzla CLI Directly

Instead of Python BTOR2-to-SMT translation, use Bitwuzla's native BTOR2 parser:

```bash
# Add candidate lemma as bad property
echo "(bad (not (=> (= state1536 10) (= state790 0))))" >> file.btor2
bitwuzla file.btor2
```

This would require modifying the BTOR2 file to add bad properties encoding lemma violations. Bitwuzla's native parser supports all BTOR2 operators correctly.

## Priority

1. **High**: SAT counterexample model extraction (for repair-loop feedback)
2. **High**: Lemma parser support for SMT-LIB2 `(_ extract ...)` syntax (Candidate 5)
3. **Medium**: Pono C++ predicate-to-BTOR2 mapping dump (for IC3IA trace integration)
4. **Medium**: Fix node-208 redor cascade (29 remaining failures, non-target)
5. **Low**: Full BTOR2 opcode support (sext, sll, rol, etc.)
6. **Deferred**: Controlled Verilog benchmarks where baseline IC3IA times out and oracle lemma unlocks

### Next Step: Repair Loop

All 4 state-only candidates are init-safe but one-step-fail (SAT). This means:
- Lemma holds at reset state
- Some transition can violate the lemma
- SAT counterexample provides concrete witness

The natural next step: extract SAT counterexample models and feed them back to
the LLM repair loop (analogous to the qspiflash case study where init-failing
lemma `state1361 = !state1359` was repaired to `!(state1359 && state1361)`).
