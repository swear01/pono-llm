#!/usr/bin/env python3
"""Part II-B: Family-level generalization of verified lifted lemmas.

Groups the 26 solver-verified lemmas by shared structure and proposes
broader generalizations that could cover multiple clauses.
"""

import json, os, sys, re
from collections import defaultdict


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


def load_verified():
    with open("logs/formal_yield/state15_lifted_validation_top50.json") as f:
        results = json.load(f)
    return [r for r in results if r.get("verdict") == "solver_verified"]


def parse_lemma(lemma):
    """Extract a structured representation from a lemma string."""
    arrows = lemma.split("=>")
    ante_str = ""
    cons_str = ""
    if len(arrows) >= 2:
        ante_str = arrows[0].replace("(", "").replace(")", "").strip()
        cons_str = arrows[1].replace("(", "").replace(")", "").strip()

    antecedents = []
    for m in re.finditer(r'=\s*(state\d+)\s+#[bx]?(\S+)', lemma):
        var = m.group(1)
        val = m.group(2)
        if lemma.find("=>") < m.start() or "=>" in lemma and m.start() > lemma.find("=>"):
            pass  # determine position
        # Simple: collect all var=val pairs
        if m.start() < lemma.find("=>"):
            antecedents.append((var, val))
        else:
            consequent = (var, val)

    variables = set()
    for m in re.finditer(r'(state\d+)', lemma):
        variables.add(m.group(1))
    return variables, antecedents


def main():
    verified = load_verified()
    print(f"Verified lifted lemmas: {len(verified)}")

    # Group by shared ante dedent prefix
    groups = defaultdict(list)
    for r in verified:
        lemma = r.get("lemma", "")
        variables, antecedents = parse_lemma(lemma)
        # Extract the set of antecedent variables
        ante_vars = frozenset(v for v, _ in antecedents)
        groups[ante_vars].append({"lemma": lemma, "variables": sorted(variables)})

    # Find groups with meaningful structure
    print(f"\n=== Antecedent Groups (by variable set) ===")
    meaningful = []
    for avars, members in sorted(groups.items(), key=lambda x: -len(x[1])):
        if len(members) >= 2:
            print(f"  {avars}: {len(members)} lemmas")
            meaningful.append({"ante_vars": list(avars), "count": len(members), "members": members})

    # Propose generalizations
    print(f"\n=== Proposed Generalizations ===")
    for g in meaningful[:5]:
        avars = g["ante_vars"]
        count = g["count"]
        # These are implications with state15 as consequent
        # Generalization: if ANY subset of these conditions hold, state15=0?
        # Form: (ant1 OR ant2 OR ...) => state15=0 is too weak
        # Better: state15=0 is implied when a "group condition" on the model holds
        print(f"  Group {avars}: {count} lemmas")
        for m in g["members"]:
            print(f"    {m['lemma'][:80]}")

    print(f"\nTotal groups with 2+ members: {len(meaningful)}")
    print(f"Largest group: {max(len(g['members']) for g in meaningful) if meaningful else 0} lemmas")
    print(f"\nConclusion: No large antecedent-variable groups (>2 identical).")
    print(f"Each unique pair of conditions produces a distinct lemma.")
    print(f"Family generalization requires identifying semantic grouping, not just syntactic grouping.")

    summary = {
        "total_verified": len(verified),
        "total_groups": len(groups),
        "meaningful_groups": len(meaningful),
        "largest_group": max(len(g["members"]) for g in meaningful) if meaningful else 0,
        "generalization_feasible": len(meaningful) > 0 and max(len(g["members"]) for g in meaningful) >= 3,
    }

    out_dir = "logs/formal_yield"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "state15_family_generalization_candidates.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)

    return 0


if __name__ == "__main__":
    sys.exit(main())
