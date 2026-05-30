#!/usr/bin/env python3
"""Task 91: Impact analysis for solver-verified lifted state15 lemmas.

For each lifted lemma, compute clause coverage, family coverage, and impact.
"""

import json, os, sys, re
from collections import Counter, defaultdict


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


def load_verified(path):
    results = load_jsonl(path) if path.endswith('.jsonl') else []
    if not results:
        with open(path) as f:
            results = json.load(f)
    return [r for r in results if r.get("verdict") == "solver_verified"]


def parse_lemma_vars(lemma):
    """Extract variables and values from a lifted lemma."""
    antecedents = []  # list of (var, val)
    consequent = None  # (var, val)
    all_vars = set()

    for m in re.finditer(r'\(\s*=\s*(state\d+)\s+#[bx]?(\S+?)\s*\)', lemma):
        var = m.group(1)
        val = m.group(2).rstrip(")")
        if consequent is None and not antecedents:
            # First match might be direct guardian
            pass
        all_vars.add(var)
        # Check position relative to =>
        if lemma.find("=>") < lemma.find(m.group(0)):
            antecedents.append((var, val))
        else:
            consequent = (var, val)
        if not consequent and "=>" not in lemma[:lemma.find(m.group(0))]:
            antecedents.append((var, val))
        elif "=>" in lemma:
            pos = m.start()
            arrow_pos = lemma.find("=>")
            if pos < arrow_pos:
                antecedents.append((var, val))
            else:
                consequent = (var, val)

    # Simpler: extract everything
    matches = list(re.finditer(r'\(\s*=\s*(state\d+)\s+#[bx]?(\S+?)\s*\)', lemma))
    if len(matches) >= 2:
        arrow_pos = lemma.find("=>")
        for m in matches:
            var = m.group(1)
            val = m.group(2).rstrip(")")
            if m.start() < arrow_pos:
                antecedents.append((var, val))
            else:
                if consequent is None:
                    consequent = (var, val)

    return antecedents, consequent, all_vars


def normalize_literal(var, val):
    """Normalize a (var, val) pair for matching."""
    v = val.replace("#b", "").lstrip("0") or "0"
    return f"{var}={v}"


def analyze_coverage(lemma, antecedents, consequent, frame_clauses):
    """Check how many frame clauses this lemma covers.

    Coverage definition: a frame clause is covered if the lemma's CNF form
    matches or subsumes the clause's literals.
    """
    ante_lits = {normalize_literal(v, va) for v, va in antecedents}
    cons_lit = normalize_literal(consequent[0], consequent[1]) if consequent else None

    cover_same_family = 0
    cover_any = 0
    exact_count = 0

    lemma_vars = set()
    for v, _ in antecedents: lemma_vars.add(v)
    if consequent: lemma_vars.add(consequent[0])

    for clause in frame_clauses:
        clause_vars = set()
        clause_lits = set()
        for lit in clause.get("literals", []):
            sv = lit.get("state_values", {})
            for var, val in sv.items():
                clause_vars.add(var)
                clause_lits.add(normalize_literal(var, val))
            for v in lit.get("variables", []):
                clause_vars.add(v)

        # Check overlap of variables
        var_overlap = lemma_vars & clause_vars
        if len(var_overlap) < 2:
            continue

        # Check if lemma's CNF form matches clause structure
        # Lemma: (A AND B) => C ≡ (NOT A) OR (NOT B) OR C
        # Clause: (NOT A') OR (NOT B') OR C'
        # Match if same variables and compatible values
        if var_overlap >= lemma_vars:
            same_fam = clause.get("literal_count", 0) <= len(ante_lits) + 2
            if same_fam:
                cover_same_family += 1

        cover_any += 1

    return {
        "exact_match": exact_count,
        "same_family": cover_same_family,
        "any_overlap": cover_any,
        "lemma_vars": sorted(lemma_vars),
    }


def classify_impact(coverage, total_clauses):
    cov = coverage.get("same_family", 0)
    if cov >= 20:
        return "high_potential"
    elif cov >= 5:
        return "medium_potential"
    elif cov >= 2:
        return "low_potential"
    else:
        return "low_potential"


def main():
    verified = load_verified("logs/formal_yield/state15_lifted_validation_top50.json")
    print(f"Verified lemmas: {len(verified)}")

    frame_clauses = load_jsonl("logs/pono_frame_dump/qspiflash_p040_frames.jsonl")
    ctis = load_jsonl("logs/pono_frame_dump/qspiflash_p040_ctis.jsonl")
    print(f"Frame clauses: {len(frame_clauses)}, CTIs: {len(ctis)}")

    results = []
    for lemma_rec in verified:
        lemma = lemma_rec.get("lemma", "")
        antecedents, consequent, all_vars = parse_lemma_vars(lemma)
        coverage = analyze_coverage(lemma, antecedents, consequent, frame_clauses)
        impact = classify_impact(coverage, len(frame_clauses))

        results.append({
            "lemma": lemma[:150],
            "antecedents": [(v, va) for v, va in antecedents],
            "consequent": consequent,
            "coverage": coverage,
            "impact": impact,
        })

    # Rank by coverage
    results.sort(key=lambda r: -r["coverage"]["same_family"])

    # Summary
    impact_counts = Counter(r["impact"] for r in results)
    print(f"\n=== Impact Distribution ===")
    for imp, c in impact_counts.most_common():
        print(f"  {imp}: {c}")

    print(f"\n=== Top 10 by Coverage ===")
    for i, r in enumerate(results[:10]):
        cov = r["coverage"]
        ante_str = " AND ".join(f"{v}={va}" for v, va in r["antecedents"])
        cons_str = f"{r['consequent'][0]}={r['consequent'][1]}" if r['consequent'] else "?"
        print(f"  {i+1}. [{r['impact']}] ({ante_str}) => {cons_str}")
        print(f"     family={cov['same_family']} overlap={cov['any_overlap']}")

    # Determine branch
    any_medium = any(r["impact"] in ("medium_potential", "high_potential") for r in results)
    if any_medium:
        branch = "II-A: medium/high impact found"
    else:
        branch = "II-B: all low impact → family generalization"

    print(f"\n*** BRANCH: {branch} ***")

    # Save
    out_dir = "logs/formal_yield"
    os.makedirs(out_dir, exist_ok=True)
    summary = {
        "total_verified": len(verified),
        "impact_distribution": dict(impact_counts),
        "top_ranked": results[:15],
        "all_results": results,
        "branch": branch,
    }
    with open(os.path.join(out_dir, "state15_lifted_impact.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nSaved: state15_lifted_impact.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
