#!/usr/bin/env python3
"""Parts 1+7: Prepare lifted lemmas for injection, select subsets, rank.

Loads solver-verified lifted lemmas, normalizes them for Pono injection,
and selects ranked subsets for experimentation.
"""

import json, os, sys, re
from collections import Counter


def load_verified(path):
    with open(path) as f:
        results = json.load(f)
    return [r for r in results if r.get("verdict") == "solver_verified"]


def normalize_lemma(lemma):
    """Normalize and extract structure from a lifted lemma."""
    info = {"original": lemma, "antecedents": [], "consequent": None,
            "variables": [], "ante_count": 0, "supported": True}

    matches = list(re.finditer(r'\(\s*=\s*(state\d+)\s+#[bx]?(\S+?)\s*\)', lemma))

    # Last match is the consequent, all others are antecedents
    for i, m in enumerate(matches):
        var = m.group(1)
        val = m.group(2).rstrip(")")
        info["variables"].append(var)
        if i < len(matches) - 1:
            info["antecedents"].append({"var": var, "value": val})
        else:
            info["consequent"] = {"var": var, "value": val}

    info["ante_count"] = len(info["antecedents"])
    info["supported"] = info["ante_count"] <= 2

    return info


def load_clause_data():
    """Load clause data for ranking."""
    frame_clauses = []
    with open("logs/pono_frame_dump/qspiflash_p040_frames.jsonl") as f:
        for line in f:
            if line.strip():
                try: frame_clauses.append(json.loads(line))
                except: pass
    return frame_clauses


def compute_lemma_score(info, var_counts):
    """Score a lemma for injection priority."""
    score = 0
    # Prefer state15 as consequent (proof-relevant)
    if info.get("consequent", {}).get("var") == "state15":
        score += 30
    # Prefer few antecedents (simpler)
    score += max(0, 10 - info.get("ante_count", 0) * 5)
    # Prefer high-frequency variables
    for v in info.get("variables", []):
        score += min(var_counts.get(v, 0), 20)
    # Prefer having a consequent
    if info.get("consequent"):
        score += 10
    return score


def main():
    verified = load_verified("logs/formal_yield/state15_lifted_validation_top50.json")
    print(f"Verified lifted lemmas: {len(verified)}")

    # Normalize all
    norm = []
    for r in verified:
        lemma = r.get("lemma", "")
        info = normalize_lemma(lemma)
        info["lemma_id"] = f"lift_{len(norm):03d}"
        norm.append(info)

    # Save dry-run
    out_dir = "logs/formal_yield"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "lifted_lemma_injection_dryrun.json"), "w") as f:
        json.dump(norm, f, indent=2)

    # Load clause data for ranking
    frame_clauses = load_clause_data()
    var_counts = Counter()
    for cl in frame_clauses:
        for lit in cl.get("literals", []):
            for v in lit.get("variables", []):
                var_counts[v] += 1
            for v in lit.get("state_values", {}).keys():
                var_counts[v] += 1

    # Score and rank
    for info in norm:
        info["_score"] = compute_lemma_score(info, var_counts)

    norm.sort(key=lambda x: -x["_score"])

    # Create subsets
    subsets = {
        "all_26": [i["lemma_id"] for i in norm],
        "top_5_by_score": [i["lemma_id"] for i in norm[:5]],
        "top_5_state15_consequent": [i["lemma_id"] for i in norm
                                     if i.get("consequent", {}).get("var") == "state15"][:5],
        "one_best": [norm[0]["lemma_id"]] if norm else [],
        "diverse_5": [],
    }

    # Diverse: take one from each consequent variable
    seen_cons = set()
    for i in norm:
        cvar = i.get("consequent", {}).get("var", "")
        if cvar and cvar not in seen_cons:
            subsets["diverse_5"].append(i["lemma_id"])
            seen_cons.add(cvar)
        if len(subsets["diverse_5"]) >= 5:
            break

    with open(os.path.join(out_dir, "lifted_lemma_injection_subsets.json"), "w") as f:
        json.dump({"subsets": subsets, "lemmas": norm}, f, indent=2, default=str)

    print(f"\n=== Top 10 Ranked ===")
    for i, info in enumerate(norm[:10]):
        ante_str = " AND ".join(f"{a['var']}={a['value']}" for a in info["antecedents"])
        cons_str = f"{info['consequent']['var']}={info['consequent']['value']}" if info.get("consequent") else "?"
        print(f"  {i+1}. [{info['_score']}] ({ante_str}) => {cons_str}")

    print(f"\n=== Subsets ===")
    for name, ids in subsets.items():
        print(f"  {name}: {len(ids)} lemmas")

    return 0


if __name__ == "__main__":
    sys.exit(main())
