#!/usr/bin/env python3
"""WP5: Offline injection replay v2.

Estimates the effect of injecting lifted lemmas by comparing frame clauses
against lemma structures without C++ changes.
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


def load_subsets():
    with open("logs/formal_yield/lifted_lemma_injection_subsets.json") as f:
        return json.load(f)


def load_dryrun():
    with open("logs/formal_yield/lifted_lemma_injection_dryrun.json") as f:
        return json.load(f)


def vet_clause(clause, lemma_vars):
    """Check if clause variables overlap with lemma variables."""
    clause_vars = set()
    for lit in clause.get("literals", []):
        clause_vars.update(lit.get("variables", []))
        clause_vars.update(lit.get("state_values", {}).keys())
    return len(clause_vars & set(lemma_vars))


def analyze_subset(subset_name, lemma_ids, dryrun_lemmas, frame_clauses, ctis):
    """Estimate what this subset would affect."""
    id_to_info = {l["lemma_id"]: l for l in dryrun_lemmas}
    selected = [id_to_info[i] for i in lemma_ids if i in id_to_info]

    all_lemma_vars = set()
    for s in selected:
        all_lemma_vars.update(s["variables"])

    # Frame impact
    affected_clauses = 0
    strongly_affected = 0  # 2+ overlapping vars
    for clause in frame_clauses:
        overlap = vet_clause(clause, all_lemma_vars)
        if overlap >= 2:
            strongly_affected += 1
            affected_clauses += 1
        elif overlap >= 1:
            affected_clauses += 1

    # CTI impact
    cti_with_vars = 0
    for cti in ctis:
        cti_vars = set()
        for lit in cti.get("cube", []):
            vn = lit.get("varname", "")
            for m in re.finditer(r'state\d+', vn):
                cti_vars.add(m.group())
        if cti_vars & all_lemma_vars:
            cti_with_vars += 1

    frames_seen = set()
    for clause in frame_clauses:
        if vet_clause(clause, all_lemma_vars) >= 1:
            frames_seen.add(clause.get("frame", 0))

    return {
        "subset": subset_name,
        "lemma_count": len(selected),
        "unique_variables": len(all_lemma_vars),
        "frame_clauses_with_overlap": affected_clauses,
        "frame_clauses_strongly_affected": strongly_affected,
        "frames_touched": sorted(frames_seen),
        "ctis_with_vars": cti_with_vars,
        "cti_total": len(ctis),
        "clause_total": len(frame_clauses),
    }


def main():
    frame_clauses = load_jsonl("logs/pono_frame_dump/qspiflash_p040_frames.jsonl")
    ctis = load_jsonl("logs/pono_frame_dump/qspiflash_p040_ctis.jsonl")
    dryrun = load_dryrun()
    subsets_data = load_subsets()
    subsets = subsets_data.get("subsets", {})

    print(f"Frames: {len(frame_clauses)}, CTIs: {len(ctis)}, Lemmas: {len(dryrun)}")

    results = []
    for name, ids in subsets.items():
        r = analyze_subset(name, ids, dryrun, frame_clauses, ctis)
        results.append(r)
        print(f"  {name}: {r['lemma_count']} lemmas → {r['frame_clauses_strongly_affected']} strongly affected, "
              f"{r['frame_clauses_with_overlap']} overlapping, "
              f"frames={r['frames_touched']}")

    # Best subset
    results.sort(key=lambda r: -r["frame_clauses_strongly_affected"])
    best = results[0] if results else None

    out_dir = "logs/formal_yield"
    os.makedirs(out_dir, exist_ok=True)

    output = {
        "subsets": results,
        "best": best,
        "interpretation": (
            "Strongly affected clauses (2+ variable overlap) indicate clauses "
            "that might be simplified or removed if the lemma set were injected. "
            "This is an upper-bound estimate — not all overlapping clauses would "
            "be subsumed by the injected lemmas."
        ),
    }
    with open(os.path.join(out_dir, "offline_injection_replay_v2.json"), "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nBest: {best['subset']} with {best['frame_clauses_strongly_affected']} strongly affected clauses")
    print("Note: overlap ≠ subsumption. This is an upper-bound estimate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
