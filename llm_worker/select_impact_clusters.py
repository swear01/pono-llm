#!/usr/bin/env python3
"""Task 84: Select high-impact variable clusters from real IC3IA dumps.

Analyzes frame/CTI dumps to find variables and pairs with high proof-trace relevance,
then ranks them for the next closed-loop synthesis run.
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


def extract_vars_from_record(record, field="variables"):
    """Extract state variable names from any record."""
    vars_found = set()
    for src in [record.get(field, []),
                str(record.get("raw_smt", "")),
                str(record.get("raw_expr", "")),
                str(record.get("label", ""))]:
        if isinstance(src, list):
            for item in src:
                if isinstance(item, str):
                    for m in re.finditer(r'\b(state\d+)\b', item):
                        vars_found.add(m.group(1))
        else:
            for m in re.finditer(r'\b(state\d+)\b', str(src)):
                vars_found.add(m.group(1))

    # Also check literals
    for lit in record.get("cube", []) + record.get("literals", []):
        for k in ["varname", "raw", "expr", "variables"]:
            v = lit.get(k, "")
            if isinstance(v, list):
                for item in v:
                    for m in re.finditer(r'\b(state\d+)\b', str(item)):
                        vars_found.add(m.group(1))
            else:
                for m in re.finditer(r'\b(state\d+)\b', str(v)):
                    vars_found.add(m.group(1))
        # state_values keys
        for sv in lit.get("state_values", {}).keys():
            if sv.startswith("state"):
                vars_found.add(sv)

    return vars_found


def analyze_dumps(frame_path, cti_path, predicate_path=None):
    """Analyze frame and CTI dumps for variable impact metrics."""

    frames = load_jsonl(frame_path)
    ctis = load_jsonl(cti_path)

    print(f"Loaded {len(frames)} frame clauses, {len(ctis)} CTIs")

    # Per-variable metrics
    var_frame_count = Counter()
    var_cti_count = Counter()
    var_highest_frame = defaultdict(int)
    var_frame_clauses = defaultdict(list)  # sample clauses

    # Per-pair metrics
    pair_frame_count = Counter()
    pair_cti_count = Counter()
    pair_highest_frame = defaultdict(int)

    # Frame analysis
    for clause in frames:
        frm = clause.get("frame", 0)
        vars_found = extract_vars_from_record(clause)

        for v in vars_found:
            var_frame_count[v] += 1
            var_highest_frame[v] = max(var_highest_frame[v], frm)
            if len(var_frame_clauses[v]) < 2:
                var_frame_clauses[v].append(clause.get("raw_smt", "")[:100])

        # Co-occurrence pairs
        sorted_vars = sorted(vars_found)
        for i in range(len(sorted_vars)):
            for j in range(i + 1, len(sorted_vars)):
                pair = (sorted_vars[i], sorted_vars[j])
                pair_frame_count[pair] += 1
                pair_highest_frame[pair] = max(pair_highest_frame[pair], frm)

    # CTI analysis
    for cti in ctis:
        frm = cti.get("frame", 0)
        vars_found = extract_vars_from_record(cti, "cube")

        for v in vars_found:
            var_cti_count[v] += 1

        sorted_vars = sorted(vars_found)
        for i in range(len(sorted_vars)):
            for j in range(i + 1, len(sorted_vars)):
                pair = (sorted_vars[i], sorted_vars[j])
                pair_cti_count[pair] += 1

    # Build clusters from frame co-occurring pairs (focus on frame relevance)
    max_frame = max(var_highest_frame.values()) if var_highest_frame else 4

    # Filter: only consider variables appearing in frame clauses
    frame_relevant_vars = set(var_frame_count.keys())

    LOW_IMPACT_PAIRS = {
        ("state2002", "state790"): "valid lemma, low proof-impact",
    }

    clusters = []
    for (a, b), count in pair_frame_count.most_common(100):
        if a not in frame_relevant_vars or b not in frame_relevant_vars:
            continue

        cti_count = pair_cti_count.get((a, b), 0)
        hf = pair_highest_frame.get((a, b), 0)

        # Score: weighted by frame co-occurrence, higher frames, CTI presence
        frame_weight = count / max(len(frame_relevant_vars), 1) if frame_relevant_vars else count
        high_frame_weight = hf / max(max_frame, 1)
        cti_weight = min(cti_count / 100, 1.0) if cti_count else 0
        score = (frame_weight * 40) + (high_frame_weight * 30) + (cti_weight * 20) + min(count, 10)

        # Penalty for known low-impact pairs
        penalty = 0
        reason = ""
        if (a, b) in LOW_IMPACT_PAIRS or (b, a) in LOW_IMPACT_PAIRS:
            penalty = 40
            reason = LOW_IMPACT_PAIRS.get((a, b), LOW_IMPACT_PAIRS.get((b, a), "low impact"))

        clusters.append({
            "variables": [a, b],
            "score": round(score - penalty, 1),
            "frame_occurrences": count,
            "cti_occurrences": cti_count,
            "highest_frame": hf,
            "frame_weight": round(frame_weight, 3),
            "high_frame_weight": round(high_frame_weight, 3),
            "cti_weight": round(cti_weight, 3),
            "penalty": penalty,
            "reason": reason,
        })

    clusters.sort(key=lambda c: -c["score"])

    # Top 10
    return {
        "top_clusters": clusters[:10],
        "variable_frame_stats": {
            v: {"frames": var_frame_count[v],
                "ctis": var_cti_count[v],
                "highest_frame": var_highest_frame[v]}
            for v in sorted(frame_relevant_vars,
                            key=lambda x: -var_frame_count[x])[:20]
        },
        "total_variables_in_frames": len(frame_relevant_vars),
        "total_pairs_analyzed": len(pair_frame_count),
    }


def main():
    out_dir = "logs/formal_yield"
    os.makedirs(out_dir, exist_ok=True)

    result = analyze_dumps(
        frame_path="logs/pono_frame_dump/qspiflash_p040_frames.jsonl",
        cti_path="logs/pono_frame_dump/qspiflash_p040_ctis.jsonl",
        predicate_path="logs/pono_frame_dump/qspiflash_p040_predicates.jsonl",
    )

    with open(os.path.join(out_dir, "impact_guided_clusters.json"), "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"\n=== Top 10 Impact-Guided Clusters ===")
    for i, c in enumerate(result["top_clusters"][:10]):
        v = c["variables"]
        print(f"  {i+1}. {v[0]} + {v[1]}: score={c['score']:.1f} "
              f"frames={c['frame_occurrences']} ctis={c['cti_occurrences']} "
              f"max_frame={c['highest_frame']}")

    print(f"\n=== High-Impact Individual Variables ===")
    for v, s in list(result["variable_frame_stats"].items())[:10]:
        print(f"  {v}: frames={s['frames']} ctis={s['ctis']} "
              f"max_frame={s['highest_frame']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
