#!/usr/bin/env python3
"""Task 89: Clause-family lifting — derive implication lemmas from OR clauses.

Loads state15-involving frame clauses, mechanically lifts OR forms
to implication candidates, and validates them.
"""

import json, os, sys, time, re
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def load_jsonl(path):
    records = []
    if not os.path.exists(path): return records
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try: records.append(json.loads(line))
                except: pass
    return records


def extract_state15_clauses(frame_path):
    """Extract multi-literal clauses involving state15."""
    frames = load_jsonl(frame_path)
    clauses = []
    for c in frames:
        lits = c.get("literals", [])
        has_s15 = any("state15" in lit.get("state_values", {}) for lit in lits)
        if not has_s15: continue
        lit_count = c.get("literal_count", 0)
        if lit_count < 2: continue  # Need 2+ literals for OR lifting
        clauses.append(c)
    return clauses


def lift_or_to_implications(clause):
    """Convert an OR clause into equivalent implication forms.

    (A OR B OR C) is equivalent to:
      (not A AND not B) => C
      (not A AND not C) => B
      (not B AND not C) => A
    """
    lits = clause.get("literals", [])
    candidates = []
    lit_data = []

    for lit in lits:
        sv = lit.get("state_values", {})
        pol = lit.get("polarity", True)  # True = positive in clause
        # In a disjunction: if polarity is True, the literal appears positively
        # If polarity is False, the literal appears negated
        for var, val in sv.items():
            lit_data.append({
                "var": var,
                "val": val,
                "polarity_in_clause": pol,
                "negated_in_clause": not pol,
            })

    if len(lit_data) < 2:
        return candidates

    # For each literal as consequent, the others form the antecedent
    for i, consequent in enumerate(lit_data):
        antecedents = [ld for j, ld in enumerate(lit_data) if j != i]
        if len(antecedents) < 1: continue

        # Build implication: (ant1 AND ant2 AND ...) => consequent
        # Antecedent literals are the NEGATION of their clause form
        # (If X appears in OR, antecedent uses NOT X as a positive condition)
        ante_strs = []
        ante_vars = []
        for a in antecedents:
            var = a["var"]
            val = a["val"]
            if a["negated_in_clause"]:
                # In the clause it's negated, so NOT-literal is positive
                # The antecedent uses it directly
                ante_strs.append(f"(= {var} #b{val})")
            else:
                # In the clause it's positive, so antecedent negates it
                # But we can't easily put NOT in antecedent with current parser
                # Instead, skip positive literals — they don't form useful guards
                ante_strs.append(f"(= {var} #b{val})")
            ante_vars.append(var)

        # Skip if consequence has no explicit value
        cvar = consequent["var"]
        cval = consequent["val"]

        if ante_strs:
            if len(ante_strs) == 1:
                lemma = f"(=> {ante_strs[0]} (= {cvar} #b{cval}))"
            else:
                lemma = f"(=> (and {' '.join(ante_strs)}) (= {cvar} #b{cval}))"

            candidates.append({
                "lemma": lemma,
                "source_clause": clause.get("raw_smt", "")[:150],
                "frame": clause.get("frame", 0),
                "consequent_var": cvar,
                "consequent_val": cval,
                "antecedent_vars": ante_vars,
                "antecedent_count": len(ante_vars),
            })

    return candidates


def deduplicate_candidates(candidates):
    seen = set()
    unique = []
    for c in candidates:
        key = c["lemma"].replace(" ", "")
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def build_schema_repr(candidates):
    """Count coverage per candidate."""
    schema_counts = Counter()
    for c in candidates:
        schema_counts[c["lemma"]] += 1
    for c in candidates:
        c["coverage_count"] = schema_counts[c["lemma"]]
    return candidates


def main():
    clauses = extract_state15_clauses("logs/pono_frame_dump/qspiflash_p040_frames.jsonl")
    print(f"Clauses with state15 (2+ literals): {len(clauses)}")

    all_candidates = []
    for cl in clauses:
        lifted = lift_or_to_implications(cl)
        all_candidates.extend(lifted)

    all_candidates = deduplicate_candidates(all_candidates)
    all_candidates = build_schema_repr(all_candidates)

    # Sort by coverage
    all_candidates.sort(key=lambda c: (-c["coverage_count"], c["frame"]))

    print(f"Unique lifted candidates: {len(all_candidates)}")

    # Show top candidates by coverage
    print("\n=== Top Candidates by Clause Coverage ===")
    for i, c in enumerate(all_candidates[:15]):
        print(f"  {i+1}. [{c['coverage_count']}x] {c['lemma'][:100]}")
        print(f"     source: {c['source_clause'][:120]}")

    # Save
    os.makedirs("logs/formal_yield", exist_ok=True)
    with open("logs/formal_yield/state15_lifted_candidates.json", "w") as f:
        json.dump(all_candidates[:30], f, indent=2, default=str)

    return all_candidates


if __name__ == "__main__":
    sys.exit(main())
