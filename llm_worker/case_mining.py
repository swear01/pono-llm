#!/usr/bin/env python3
"""Case mining metrics: score benchmarks for LLM lemma suitability.

Measures:
  1. CTI literal coverage by hot variable group
  2. Clause cluster size
  3. Transition readability
"""

import json, os, re, sys
from pathlib import Path
from collections import defaultdict


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

    # 4. Suitability score
    score = 0
    reasons = []
    if result["coverage"] >= 0.15:
        score += 3
        reasons.append("high coverage")
    elif result["coverage"] >= 0.08:
        score += 1
        reasons.append("medium coverage")
    else:
        reasons.append("low coverage (like qspiflash: lemma correct but small)")

    if result["max_cluster_size"] >= 8:
        score += 3
        reasons.append("large cluster")
    elif result["max_cluster_size"] >= 3:
        score += 1
        reasons.append("medium cluster")
    else:
        reasons.append("small cluster")

    if len(best_group) >= 2:
        score += 1
        reasons.append("multi-var group")

    result["suitability_score"] = score
    result["suitability_reasons"] = reasons
    result["suitability"] = (
        "promising" if score >= 4
        else "maybe" if score >= 2
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
