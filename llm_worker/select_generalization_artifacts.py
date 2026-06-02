#!/usr/bin/env python3
"""WP3: Select proof artifacts for generalization.

Selects frame clauses, clause families, lifted lemmas, and CTI patterns
as generalization seeds.
"""

import json, os, sys, re
from collections import Counter


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


def main():
    os.makedirs("logs/formal_yield/generalization_artifacts", exist_ok=True)
    artifacts = []
    aid = 0

    # --- Frame Clauses: top 10 by literal count ---
    frames = load_jsonl("logs/pono_frame_dump/qspiflash_p040_frames.jsonl")
    frames_with_vars = []
    for cl in frames:
        vars_found = set()
        for lit in cl.get("literals", []):
            vars_found.update(lit.get("variables", []))
            vars_found.update(lit.get("state_values", {}).keys())
        if vars_found:
            frames_with_vars.append((cl, vars_found))

    frames_with_vars.sort(key=lambda x: -len(x[1]))
    for cl, vars_found in frames_with_vars[:10]:
        aid += 1
        artifacts.append({
            "artifact_id": f"artifact_{aid:03d}",
            "artifact_type": "frame_clause",
            "frame": cl.get("frame", 0),
            "raw": cl.get("raw_smt", "")[:150],
            "variables": sorted(vars_found)[:10],
            "lit_count": cl.get("literal_count", 0),
            "why_selected": "high variable count frame clause",
            "recommended_operators": ["clause_lifting", "literal_deletion"],
        })

    # --- Clause Families: top 5 ---
    try:
        with open("logs/formal_yield/state15_clause_families.json") as f:
            families = json.load(f)
        for fam in families[:5]:
            aid += 1
            top_sats = fam.get("top_satellites", [])
            artifacts.append({
                "artifact_id": f"artifact_{aid:03d}",
                "artifact_type": "clause_family",
                "family": fam.get("family", ""),
                "count": fam.get("count", 0),
                "frames": fam.get("frames", []),
                "top_satellites": top_sats[:5] if isinstance(top_sats[0], list) else top_sats,
                "why_selected": "repeated proof-local clause family",
                "recommended_operators": ["family_compression", "satellite_generalization"],
            })
    except: pass

    # --- Lifted Lemmas: top 5 verified ---
    try:
        with open("logs/formal_yield/state15_lifted_validation_top50.json") as f:
            lifted = json.load(f)
        verified = [l for l in lifted if l.get("verdict") == "solver_verified"]
        for l in verified[:5]:
            aid += 1
            artifacts.append({
                "artifact_id": f"artifact_{aid:03d}",
                "artifact_type": "lifted_lemma",
                "lemma": l.get("lemma", "")[:120],
                "variables": l.get("variables", []),
                "why_selected": "solver-verified but proof-local — good generalization target",
                "recommended_operators": ["family_compression", "satellite_generalization"],
            })
    except: pass

    # --- Failed parallel sampling candidates ---
    try:
        with open("logs/formal_yield/parallel_sampling/validated_candidates.json") as f:
            failed = json.load(f)
        for f in failed[:3]:
            if f.get("verdict") in ("parse_failed", "nontriviality_fail"):
                aid += 1
                artifacts.append({
                    "artifact_id": f"artifact_{aid:03d}",
                    "artifact_type": "failed_candidate",
                    "lemma": f.get("lemma", "")[:120],
                    "verdict": f.get("verdict", ""),
                    "why_selected": "failed pattern to learn from",
                    "recommended_operators": ["repair", "guard_strengthening"],
                })
    except: pass

    with open("logs/formal_yield/generalization_artifacts/selected_artifacts.json", "w") as f:
        json.dump(artifacts, f, indent=2, default=str)

    print(f"Selected {len(artifacts)} artifacts for generalization")
    for a in artifacts:
        print(f"  {a['artifact_id']} [{a['artifact_type']}]: {str(a.get('raw', a.get('lemma', '')))[:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
