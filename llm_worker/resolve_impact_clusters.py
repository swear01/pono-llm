#!/usr/bin/env python3
"""Task 85: Resolve impact-guided clusters to word-level predicates.

Loads BTOR2 var names from predicate dump, then matches frame literal
variables against them. Rates clusters higher when they use BTOR2-level
(resolved) variable names.
"""

import json, os, sys, re
from collections import Counter, defaultdict


def load_jsonl(path):
    records = []
    if not os.path.exists(path):
        return records
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def load_btor2_vars(predicate_path):
    """Load BTOR2-level variable names from predicate dump expressions."""
    btor2_vars = set()
    pred_var_expr = {}  # btor2_var → example predicate expression
    records = load_jsonl(predicate_path)
    for rec in records:
        expr = rec.get("raw_expr", "")
        vars_list = rec.get("variables", [])
        for m in re.finditer(r'state(\d+)', expr):
            btor2_vars.add(f"state{m.group(1)}")
        for v in vars_list:
            if v.startswith("state"):
                btor2_vars.add(v)
                if v not in pred_var_expr:
                    pred_var_expr[v] = expr[:120]

    # Also add known Verilog-mapped variables
    for v in ["state1536", "state790", "state1558", "state2002", "state79"]:
        btor2_vars.add(v)

    print(f"Loaded {len(btor2_vars)} BTOR2 variable names from predicates")
    return btor2_vars, pred_var_expr


def extract_frame_vars(record):
    """Extract variables from a frame clause, separating BTOR2 vs internal."""
    btor2_found = set()
    internal_found = set()
    predicates = []

    for lit in record.get("literals", []):
        sv = lit.get("state_values", {})
        vars_list = lit.get("variables", [])
        raw = lit.get("raw", "")

        all_v = set(sv.keys()) | set(vars_list)
        for m in re.finditer(r'state(\d+)', raw):
            all_v.add(f"state{m.group(1)}")

        for v in all_v:
            btor2_found.add(v)  # we'll classify later

    return btor2_found


def analyze_resolved_dumps(frame_path, cti_path, predicate_path):
    btor2_vars, pred_var_expr = load_btor2_vars(predicate_path)
    frames = load_jsonl(frame_path)
    ctis = load_jsonl(cti_path)

    print(f"Loaded {len(frames)} frame clauses, {len(ctis)} CTIs")

    # Per-variable metrics
    var_frame_count = Counter()
    var_cti_count = Counter()
    var_highest_frame = defaultdict(int)
    var_is_btor2 = {}

    # Per-pair metrics
    pair_frame_count = Counter()
    pair_cti_count = Counter()
    pair_highest_frame = defaultdict(int)
    pair_resolved = {}

    # Frame analysis
    for clause in frames:
        frm = clause.get("frame", 0)
        vars_in_clause = set()

        for lit in clause.get("literals", []):
            for v in lit.get("variables", []):
                vars_in_clause.add(v)
            for v in lit.get("state_values", {}).keys():
                vars_in_clause.add(v)
            for m in re.finditer(r'state(\d+)', lit.get("raw", "")):
                vars_in_clause.add(f"state{m.group(1)}")

        for v in vars_in_clause:
            var_frame_count[v] += 1
            var_highest_frame[v] = max(var_highest_frame[v], frm)
            if v not in var_is_btor2:
                var_is_btor2[v] = v in btor2_vars

        # Co-occurrence pairs
        sorted_vars = sorted(vars_in_clause)
        for i in range(len(sorted_vars)):
            for j in range(i + 1, len(sorted_vars)):
                pair = (sorted_vars[i], sorted_vars[j])
                pair_frame_count[pair] += 1
                pair_highest_frame[pair] = max(pair_highest_frame[pair], frm)
                if pair not in pair_resolved:
                    pair_resolved[pair] = (sorted_vars[i] in btor2_vars
                                            and sorted_vars[j] in btor2_vars)

    # CTI analysis
    for cti in ctis:
        frm = cti.get("frame", 0)
        vars_in_cti = set()
        for lit in cti.get("cube", []):
            vn = lit.get("varname", "")
            for m in re.finditer(r'state(\d+)', vn):
                vars_in_cti.add(f"state{m.group(1)}")

        for v in vars_in_cti:
            var_cti_count[v] += 1
            if v not in var_is_btor2:
                var_is_btor2[v] = v in btor2_vars

        sorted_vars = sorted(vars_in_cti)
        for i in range(len(sorted_vars)):
            for j in range(i + 1, len(sorted_vars)):
                pair = (sorted_vars[i], sorted_vars[j])
                pair_cti_count[pair] += 1

    # Build clusters
    LOW_IMPACT_PAIRS = {
        ("state2002", "state790"): "valid lemma, low proof-impact",
    }

    max_frame = max(var_highest_frame.values()) if var_highest_frame else 4

    clusters = []
    for (a, b), count in pair_frame_count.most_common(200):
        cti_count = pair_cti_count.get((a, b), 0)
        hf = pair_highest_frame.get((a, b), 0)
        is_resolved = pair_resolved.get((a, b), False)

        frame_weight = count / max(len(var_frame_count), 1)
        high_frame_weight = hf / max(max_frame, 1)
        cti_weight = min(cti_count / 100, 1.0)
        score = (frame_weight * 40) + (high_frame_weight * 30) + (cti_weight * 20) + min(count, 10)

        # Bonus for resolved clusters
        if is_resolved:
            score += 15

        # Penalty for known low-impact
        penalty = 0
        reason = ""
        if (a, b) in LOW_IMPACT_PAIRS or (b, a) in LOW_IMPACT_PAIRS:
            penalty = 40

        # Get predicate expressions
        preds = []
        for v in [a, b]:
            if v in pred_var_expr:
                preds.append(pred_var_expr[v])

        clusters.append({
            "internal_vars": [a, b],
            "word_vars": [a, b] if is_resolved else [],
            "predicates": preds,
            "resolution_status": "resolved" if is_resolved else "partial" if (var_is_btor2.get(a) or var_is_btor2.get(b)) else "unresolved",
            "score": round(score - penalty, 1),
            "frame_occurrences": count,
            "cti_occurrences": cti_count,
            "highest_frame": hf,
            "penalty": penalty,
        })

    clusters.sort(key=lambda c: -c["score"])

    return {
        "top_clusters": clusters[:15],
        "resolved_count": sum(1 for c in clusters if c["resolution_status"] == "resolved"),
        "partial_count": sum(1 for c in clusters if c["resolution_status"] == "partial"),
        "unresolved_count": sum(1 for c in clusters if c["resolution_status"] == "unresolved"),
        "total_btor2_vars": len(btor2_vars),
        "total_pairs": len(pair_frame_count),
    }


def main():
    out_dir = "logs/formal_yield"

    result = analyze_resolved_dumps(
        frame_path="logs/pono_frame_dump/qspiflash_p040_frames.jsonl",
        cti_path="logs/pono_frame_dump/qspiflash_p040_ctis.jsonl",
        predicate_path="logs/pono_frame_dump/qspiflash_p040_predicates.jsonl",
    )

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "impact_guided_clusters_resolved.json"), "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"\n=== Top 10 Resolved Clusters ===")
    for i, c in enumerate(result["top_clusters"][:10]):
        v = c["internal_vars"]
        wv = c.get("word_vars", v)
        rs = c["resolution_status"]
        print(f"  {i+1}. {v[0]} + {v[1]}: score={c['score']:.1f} frames={c['frame_occurrences']} "
              f"resolved={rs}")
        if c.get("predicates"):
            print(f"     preds: {c['predicates']}")
        if rs != "resolved" and wv:
            print(f"     word-vars: {wv}")

    print(f"\nStatus: {result['resolved_count']} resolved, "
          f"{result['partial_count']} partial, {result['unresolved_count']} unresolved")
    print(f"BTOR2 vars loaded: {result['total_btor2_vars']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
