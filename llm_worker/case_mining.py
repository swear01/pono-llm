#!/usr/bin/env python3
"""Case mining metrics: score benchmarks for LLM lemma suitability.

Measures:
  1. CTI literal coverage by hot variable group
  2. Clause cluster size
  3. Transition readability
"""

import json, os, re, sys
from collections import defaultdict

RESET_PATTERNS = [
    "reset", "rst", "init_done", "clear", "clr",
    "startup", "boot", "por",
]
TRIVIAL_VARNAME_PATTERNS = [
    r"= #b0\b", r"= #b1\b", r"= 0\b", r"= 1\b",
    r"!= #b0\b", r"!= #b1\b", r"= const\b",
]


def compute_group_filters(ctis, group_vars):
    """Compute false-positive filter metrics for a variable group."""
    result = {
        "reset_flag_ratio": 0.0,
        "dominant_var_ratio": 0.0,
        "non_reset_var_count": 0,
        "trivial_literal_ratio": 0.0,
    }

    var_counts = defaultdict(int)
    total_group_lits = 0
    reset_lits = 0
    trivial_lits = 0
    non_reset_vars = set()

    for cti in ctis:
        for lit in cti.get("literals", []):
            vn = lit.get("varname", "")
            val = lit.get("value", "")

            # Check if this literal involves group vars
            involved = [v for v in group_vars if v in vn]
            if not involved:
                continue

            total_group_lits += 1
            for v in involved:
                var_counts[v] += 1

            # Trivial literal check: varname contains simple constant comparison
            is_trivial = any(re.search(pat, vn) for pat in TRIVIAL_VARNAME_PATTERNS)
            if is_trivial:
                trivial_lits += 1

            # Reset-like check
            is_reset = any(rp in vn.lower() for rp in RESET_PATTERNS)
            if is_reset:
                reset_lits += 1
            else:
                for v in involved:
                    if not any(rp in v.lower() for rp in RESET_PATTERNS):
                        non_reset_vars.add(v)

    if total_group_lits > 0:
        result["reset_flag_ratio"] = round(reset_lits / total_group_lits, 3)
        result["dominant_var_ratio"] = round(
            max(var_counts.values()) / total_group_lits, 3
        ) if var_counts else 0
        result["trivial_literal_ratio"] = round(trivial_lits / total_group_lits, 3)

    result["non_reset_var_count"] = len(non_reset_vars)

    return result


def analyze_case(req_path, stderr_path="", btor_path=""):
    """Analyze a benchmark run for LLM suitability metrics."""
    result = {
        "benchmark": os.path.basename(req_path).replace('.jsonl', ''),
        "req_path": req_path,
        "error": None,
    }

    # 1. Parse CTI batch
    try:
        with open(req_path) as f:
            first = json.loads(f.readline())
    except Exception as e:
        result["error"] = str(e)
        return result

    ctis = first.get("cti_contexts", [first] if "literals" in first else [])
    if not ctis:
        result["error"] = "no CTIs"
        return result

    # Count total literals and group by variable
    var_lit_count = defaultdict(int)
    total_lits = 0
    for cti in ctis:
        for lit in cti.get("literals", []):
            total_lits += 1
            vn = lit.get("varname", "")
            for m in re.finditer(r"\b(state\d+|input\d+)\b", vn):
                var_lit_count[m.group(1)] += 1

    # Find top variable groups (2-4 vars that together cover most literals)
    sorted_vars = sorted(var_lit_count.items(), key=lambda x: -x[1])
    top_vars = [v for v, _ in sorted_vars[:10]]

    # Try all combinations of 2-4 top vars, find best coverage
    best_coverage = 0
    best_group = []
    for size in [2, 3, 4]:
        for i in range(len(top_vars) - size + 1):
            group = top_vars[i:i + size]
            cov = sum(var_lit_count[v] for v in group)
            if cov > best_coverage and cov / total_lits >= 0.05:
                best_coverage = cov
                best_group = group

    result["total_literals"] = total_lits
    result["best_group"] = best_group
    result["coverage"] = round(best_coverage / total_lits, 3) if total_lits else 0
    result["top_vars"] = [(v, var_lit_count[v]) for v in top_vars[:5]]

    # 2. Clause cluster analysis
    # Build rough clusters from CTI literal overlap
    clause_vectors = []
    for cti in ctis[:50]:
        vec = set()
        for lit in cti.get("literals", []):
            for m in re.finditer(r"\b(state\d+)\b", lit.get("varname", "")):
                vec.add(m.group(1))
        if vec:
            clause_vectors.append(vec)

    # Simple clustering: group by shared state vars
    clusters = []
    used = set()
    for i, vec in enumerate(clause_vectors):
        if i in used:
            continue
        cluster = {i}
        for j, other in enumerate(clause_vectors):
            if j <= i or j in used:
                continue
            if len(vec & other) >= 2:
                cluster.add(j)
                vec &= other  # refine common core
        if len(cluster) >= 2:
            clusters.append(cluster)
            used.update(cluster)

    result["num_ctis"] = len(ctis)
    result["max_cluster_size"] = max((len(c) for c in clusters), default=0)
    result["num_clusters"] = len(clusters)

    # 3. Readability (if BTOR2 available)
    if btor_path and os.path.exists(btor_path):
        from transition_slice import extract_btor_transition, explain_transition_slice
        btor = {}
        for line in open(btor_path):
            parts = line.strip().split()
            if not parts or parts[0][0] == ";":
                continue
            lid = parts[0]
            try:
                int(lid)
            except ValueError:
                continue
            btor[lid] = parts[1:]
        trans = extract_btor_transition(btor_path, best_group)
        trans_text = explain_transition_slice(trans, btor)
        result["transition_lines"] = trans_text.count("\n")
        result["transition_opaque"] = trans_text.count("op=")

    # 4-7. False-positive filters
    filters = compute_group_filters(ctis, best_group)
    result.update(filters)

    # 8. Suitability score (with false-positive penalties)
    score = 0.0
    reasons = []

    score += 2.0 * result["coverage"]
    score += 1.5 * min(1.0, result["max_cluster_size"] / 10.0)
    score += 1.0 * (1.0 if len(best_group) >= 2 else 0.5)
    score -= 2.0 * result["reset_flag_ratio"]
    score -= 1.5 * result["dominant_var_ratio"]
    score -= 1.0 * result["trivial_literal_ratio"]

    if result["coverage"] >= 0.15:
        reasons.append("high coverage")
    elif result["coverage"] >= 0.08:
        reasons.append("medium coverage")

    if result["max_cluster_size"] >= 8:
        reasons.append("large cluster")
    elif result["max_cluster_size"] >= 3:
        reasons.append("medium cluster")

    if result["reset_flag_ratio"] > 0.30:
        reasons.append(f"reset-dominated ({result['reset_flag_ratio']:.0%})")
    if result["dominant_var_ratio"] > 0.65:
        reasons.append(f"single-var dominant ({result['dominant_var_ratio']:.0%})")
    if result["trivial_literal_ratio"] > 0.70:
        reasons.append(f"trivial-literal heavy ({result['trivial_literal_ratio']:.0%})")

    result["suitability_score"] = round(score, 2)
    result["suitability_reasons"] = reasons
    result["suitability"] = (
        "promising" if score >= 3.0
        else "maybe" if score >= 1.5
        else "low-impact"
    )

    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        path = sys.argv[1]
        r = analyze_case(path)
        print(json.dumps(r, indent=2))
    else:
        print("Usage: python case_mining.py <req.jsonl path>")
