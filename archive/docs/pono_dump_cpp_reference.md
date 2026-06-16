> **ACTIVE for v1 (2026-06-03)** — C++ dump reference for harness implementation.  
> Spec: [`ARCHITECTURE.md`](ARCHITECTURE.md)

# C++ Dump Implementation Reference

> **Status**: Specified, not compiled. See Phase C blocker below.

This document provides the exact C++ code to add to Pono for IC3IA
frame/CTI dump. It follows the existing code style (no external JSON
library, `std::ostringstream` pattern).

## Opt-in Mechanism

```bash
PONO_LLM_DUMP_IC3IA=1
PONO_LLM_DUMP_DIR=logs/pono_frame_dump
```

Environment variables, checked at runtime. Zero overhead when not set.

## Phase C Blocker

The C++ code was **not compiled** because:

1. IC3IA uses boolean predicate abstraction — CTI literals are boolean
   predicates (`pred_N`), not raw state variable comparisons (`state2002=1`).
   The `simplify_cti_literal()` output for IC3IA may not contain the original
   variable names.

2. Recompiling Pono risked breaking the existing LLM sidecar integration
   which is actively used by the Python pipeline.

3. The impact analyzer (Phase D) is fully functional with synthetic data
   and can accept real dumps when they become available.

## Files to Modify

| File | Addition | Location |
|---|---|---|
| `engines/llm_generalizer.h` | Add `dump_ic3ia_frame_clause()` declaration | After `write_offline_cti_context` |
| `engines/llm_generalizer.cpp` | Implement dump functions | New section at end |
| `engines/ic3base.cpp` | Call dump from `capture_cti_context()` | After line 1371 |
| `engines/ic3base.cpp` | Call dump from `constrain_frame()` | After line ~890 |

## llm_generalizer.h Additions

```cpp
// Add after line 156 (write_offline_cti_context declaration):

  // IC3IA frame/CTI dump for impact analysis (opt-in via env var)
  void dump_ic3ia_cti(const CTIContext & ctx, const smt::TermVec & raw_terms);
  void dump_ic3ia_frame_clause(size_t frame_idx,
                               const smt::Term & clause_term,
                               const smt::TermVec & literals);
```

## llm_generalizer.cpp Additions

Add a new section before `}  // namespace pono`:

```cpp
// --- IC3IA Frame/CTI Dump (opt-in) ---

namespace {

bool dump_enabled() {
    const char * env = std::getenv("PONO_LLM_DUMP_IC3IA");
    return env && std::string(env) != "0" && std::string(env) != "";
}

std::string dump_dir() {
    const char * env = std::getenv("PONO_LLM_DUMP_DIR");
    return env ? std::string(env) : "logs/pono_frame_dump";
}

std::string dump_escape(const std::string & s) {
    std::ostringstream out;
    for (char c : s) {
        switch (c) {
            case '"': out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\n': out << "\\n"; break;
            default: out << c;
        }
    }
    return out.str();
}

}  // namespace

void LLMGeneralizer::dump_ic3ia_cti(const CTIContext & ctx,
                                     const smt::TermVec & raw_terms) {
    if (!dump_enabled()) return;

    std::string dir = dump_dir();
    // create directory if needed (simplified: assume exists)

    std::string filename = dir + "/qspiflash_p040_ctis.jsonl";
    std::ofstream out(filename, std::ios::app);
    if (!out.is_open()) return;

    out << "{";
    out << "\"type\":\"cti\",";
    out << "\"frame\":" << ctx.frame_idx << ",";

    out << "\"cube\":[";
    for (size_t i = 0; i < ctx.literals.size(); ++i) {
        if (i > 0) out << ",";
        out << "{";
        out << "\"varname\":\"" << dump_escape(ctx.literals[i].varname) << "\",";
        out << "\"expr\":\"" << dump_escape(ctx.literals[i].expr) << "\",";
        out << "\"value\":\"" << dump_escape(ctx.literals[i].value) << "\",";
        out << "\"kind\":\"" << dump_escape(ctx.literals[i].kind) << "\"";
        out << "}";
    }
    out << "],";

    out << "\"variables\":[";
    std::unordered_set<std::string> seen_vars;
    bool first_var = true;
    for (const auto & lit : ctx.literals) {
        for (const auto & sig : lit.signals) {
            if (seen_vars.insert(sig).second) {
                if (!first_var) out << ",";
                out << "\"" << dump_escape(sig) << "\"";
                first_var = false;
            }
        }
    }
    out << "]";

    out << "}\n";
}

void LLMGeneralizer::dump_ic3ia_frame_clause(
    size_t frame_idx,
    const smt::Term & clause_term,
    const smt::TermVec & literals) {
    if (!dump_enabled()) return;

    std::string dir = dump_dir();
    std::string filename = dir + "/qspiflash_p040_frames.jsonl";
    std::ofstream out(filename, std::ios::app);
    if (!out.is_open()) return;

    out << "{";
    out << "\"type\":\"clause\",";
    out << "\"frame\":" << frame_idx << ",";

    out << "\"literals\":[";
    for (size_t i = 0; i < literals.size(); ++i) {
        if (i > 0) out << ",";
        std::string raw = literals[i]->to_string();
        std::string varname = raw;  // simplified
        // Extract variable name pattern
        // In practice, use simplify_cti_literal for better names
        out << "{";
        out << "\"raw\":\"" << dump_escape(raw) << "\",";
        out << "\"varname\":\"" << dump_escape(varname) << "\"";
        out << "}";
    }
    out << "],";

    out << "\"raw_smt\":\"" << dump_escape(clause_term->to_string()) << "\"";
    out << "}\n";
}
```

## ic3base.cpp Additions

### CTI Dump (at end of `capture_cti_context`, before closing brace)

```cpp
// --- starting at ic3base.cpp:1371, before the closing brace ---
  // Dump CTI context for impact analysis (opt-in)
  if (llm_gen_) {
    llm_gen_->dump_ic3ia_cti(ctx, cube.children);
  }
```

### Frame Clause Dump (in `constrain_frame`, after clause is added)

```cpp
// --- in constrain_frame(), after the clause is added to frames_[i] ---
  if (llm_gen_) {
    llm_gen_->dump_ic3ia_frame_clause(i, constraint.term, constraint.children);
  }
```

## Known Limitation

For IC3IA, predicate labels are boolean abstractions. The `varname` extracted
from `CTILiteral` may be `pred_N` rather than `state2002`. To resolve this:

1. Also dump the `lbl2pred_` mapping from IC3IA
2. Or iterate over the predicate label mapping when dumping

The `simplify_cti_literal()` function handles this for CTI cubes but the
frame clause dump would need similar treatment.

## Impact Analyzer Compatibility

The Python `analyze_lemma_impact.py` searches for `state2002` and `state790`
substrings in all fields (`varname`, `expr`, `raw`, `raw_smt`). Even if IC3IA
uses predicate labels, the raw SMT expression may still contain the original
variable names if the predicate is a direct equality. For complex predicates
(e.g., `state1536 > 10`), the analyzer would need the predicate mapping.

## Incremental Build

```bash
# After adding the above code:
cd build && make -j$(nproc) pono
```

If compilation fails, the dump code can be removed without affecting core
IC3IA behavior since it is entirely opt-in via environment variable check.
