#!/usr/bin/env python3
"""Cluster pool: find multiple diverse variable groups from CTI data.

Builds a pool of candidate clusters for batch LLM lemma generation.
Each cluster represents a group of CTI variables that frequently appear
together, forming a potential semantic bottleneck.
"""

import json, os, re
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from itertools import combinations


@dataclass
class ClusterInfo:
    cluster_id: str = ""
    vars: List[str] = field(default_factory=list)
    score: float = 0.0
    coverage: float = 0.0
    cluster_size: int = 0
    reset_flag_ratio: float = 0.0
    dominant_var_ratio: float = 0.0
    trivial_literal_ratio: float = 0.0
    non_reset_var_count: int = 0
    likely_families: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


RESET_PATTERNS = ["reset", "rst", "init_done", "clear", "clr", "startup", "boot", "por"]
TRIVIAL_VARNAME_PATTERNS = [r"= #b0\b", r"= #b1\b", r"= 0\b", r"= 1\b", r"!= #b0\b"]


def _compute_group_filters(ctis, group_vars):
    result = {"reset_flag_ratio": 0.0, "dominant_var_ratio": 0.0,
              "non_reset_var_count": 0, "trivial_literal_ratio": 0.0}
    var_counts = defaultdict(int)
    total, reset_lits, trivial_lits = 0, 0, 0
    non_reset_vars = set()
    for cti in ctis:
        for lit in cti.get("literals", []):
            vn = lit.get("varname", "")
            involved = [v for v in group_vars if v in vn]
            if not involved: continue
            total += 1
            for v in involved: var_counts[v] += 1
            if any(re.search(p, vn) for p in TRIVIAL_VARNAME_PATTERNS): trivial_lits += 1
            is_reset = any(rp in vn.lower() for rp in RESET_PATTERNS)
            if is_reset: reset_lits += 1
            else:
                for v in involved:
                    if not any(rp in v.lower() for rp in RESET_PATTERNS): non_reset_vars.add(v)
    if total > 0:
        result["reset_flag_ratio"] = round(reset_lits / total, 3)
        result["dominant_var_ratio"] = round(max(var_counts.values()) / total, 3) if var_counts else 0
        result["trivial_literal_ratio"] = round(trivial_lits / total, 3)
    result["non_reset_var_count"] = len(non_reset_vars)
    return result


def build_cluster_pool(req_path: str, min_vars: int = 2, max_vars: int = 4,
                       min_cov: float = 0.03, max_pool: int = 30) -> List[ClusterInfo]:
    """Build a pool of candidate clusters from CTI data.

    Args:
        req_path: Path to JSONL CTI request file
        min_vars: Minimum variables per group
        max_vars: Maximum variables per group
        min_cov: Minimum CTI literal coverage to include
        max_pool: Maximum pool size
    """
    with open(req_path) as f:
        first = json.loads(f.readline())
    ctis = first.get("cti_contexts", [first] if "literals" in first else [])
    if not ctis: return []

    # Count variable appearances across all CTIs
    var_lit_count = defaultdict(int)
    total_lits = 0
    for cti in ctis:
        for lit in cti.get("literals", []):
            total_lits += 1
            vn = lit.get("varname", "")
            for m in re.finditer(r"\b(state\d+|input\d+)\b", vn):
                var_lit_count[m.group(1)] += 1

    top_vars = sorted(var_lit_count, key=lambda v: -var_lit_count[v])[:25]
    if len(top_vars) < min_vars: return []

    # Generate combinations of 2-4 top vars
    pool = []
    seen_varsets = set()
    for size in range(min_vars, min(max_vars + 1, len(top_vars) + 1)):
        for combo in combinations(top_vars, size):
            if len(combo) < min_vars: continue
            varset = frozenset(combo)
            if varset in seen_varsets: continue
            seen_varsets.add(varset)

            coverage = sum(var_lit_count[v] for v in combo) / total_lits if total_lits else 0
            if coverage < min_cov: continue

            # Cluster size: count CTIs where all vars appear
            cluster_ct = 0
            for cti in ctis:
                lit_text = " ".join(l.get("varname", "") for l in cti.get("literals", []))
                if all(v in lit_text for v in combo): cluster_ct += 1
            if cluster_ct < 2: continue

            filters = _compute_group_filters(ctis, list(combo))

            # Score
            score = (2.0 * coverage + 1.5 * min(1.0, cluster_ct / 10.0)
                     + 1.0 - 2.0 * filters["reset_flag_ratio"]
                     - 1.5 * filters["dominant_var_ratio"]
                     - 1.0 * filters["trivial_literal_ratio"])

            reasons = []
            if coverage >= 0.10: reasons.append("high_cov")
            if cluster_ct >= 5: reasons.append("large_cluster")
            if filters["reset_flag_ratio"] > 0.3: reasons.append("reset_dominated")
            if filters["dominant_var_ratio"] > 0.65: reasons.append("single_var_dom")

            ci = ClusterInfo(
                cluster_id=f"C{len(pool):03d}",
                vars=list(combo),
                score=round(score, 3),
                coverage=round(coverage, 3),
                cluster_size=cluster_ct,
                reset_flag_ratio=filters["reset_flag_ratio"],
                dominant_var_ratio=filters["dominant_var_ratio"],
                trivial_literal_ratio=filters["trivial_literal_ratio"],
                non_reset_var_count=filters["non_reset_var_count"],
                reasons=reasons,
            )
            pool.append(ci)

    # Rank by score, dedup by var overlap
    pool.sort(key=lambda c: -c.score)
    deduped = []
    for c in pool:
        cvars = set(c.vars)
        # Skip if too similar to any already-selected cluster
        if any(len(cvars & set(prev.vars)) / len(cvars | set(prev.vars)) > 0.7
               for prev in deduped):
            continue
        deduped.append(c)
        if len(deduped) >= max_pool: break

    return deduped


def diversify_pool(pool: List[ClusterInfo], target: int = 6) -> List[ClusterInfo]:
    """Select diverse clusters from pool for batch exploration."""
    if len(pool) <= target: return pool

    # Classify by reset/trivial cleanliness
    clean = [c for c in pool if c.reset_flag_ratio < 0.3 and c.trivial_literal_ratio < 0.7]
    dirty = [c for c in pool if c not in clean]

    selected = []
    # Prioritize clean clusters
    for c in clean:
        if len(selected) >= target: break
        cvars = set(c.vars)
        if any(len(cvars & set(p.vars)) / len(cvars | set(p.vars)) > 0.6
               for p in selected):
            continue
        selected.append(c)

    # Fill remaining with dirty but high-coverage
    for c in dirty:
        if len(selected) >= target: break
        cvars = set(c.vars)
        if any(len(cvars & set(p.vars)) / len(cvars | set(p.vars)) > 0.6
               for p in selected):
            continue
        selected.append(c)

    return selected


# CLI test
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        path = sys.argv[1]
        pool = build_cluster_pool(path, min_cov=0.03)
        diverse = diversify_pool(pool)
        print(f"Pool size: {len(pool)}, Diverse: {len(diverse)}")
        for c in diverse[:8]:
            print(f"  {c.cluster_id}: score={c.score:.2f} cov={c.coverage:.0%} "
                  f"size={c.cluster_size} vars={c.vars} nonreset={c.non_reset_var_count} "
                  f"reasons={c.reasons}")
