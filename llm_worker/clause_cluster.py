"""Group IC3 frame clauses into clusters for LLM subsumption targeting.

Identifies groups of clauses that share common predicate labels,
so LLM can generate a broader lemma to subsume the cluster.
"""

import re
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict


def tag_predicate(
    predicate: str,
    property_text: str = "",
    init_preds: Optional[List[str]] = None,
    cti_literals: Optional[List[dict]] = None,
) -> List[str]:
    """Return role tags for a predicate string.

    Tags indicate semantic role: property/init/CTI appearance,
    input vs state variable, relation type.
    """
    tags = []

    if property_text and predicate[:60] in property_text:
        tags.append("appears_in_property")
    if init_preds and any(predicate[:60] in p for p in init_preds):
        tags.append("appears_in_init_predicates")
    if cti_literals and any(predicate[:60] in str(l) for l in cti_literals):
        tags.append("appears_in_cti_batch")

    has_input = bool(re.search(r"\binput\d+\b", predicate))
    has_state = bool(re.search(r"\bstate\d+\b", predicate))

    if has_input and not has_state:
        tags.append("input_only")
        tags.append("WARNING:input-only predicates cannot be standalone invariants")
    elif has_state and not has_input:
        tags.append("state_only")
    elif has_input and has_state:
        tags.append("connects_input_and_state")

    for op, tag in [("=", "equality_relation"), ("<", "bound"), (">", "bound"),
                     ("≥", "bound"), ("≤", "bound"), ("!=", "disequality")]:
        if op in predicate:
            tags.append(tag)
            break

    return tags


def cluster_clauses(
    clauses: List[List[str]],
    min_shared: int = 2,
    max_varying: int = 20,
) -> List[Dict]:
    """Group clauses sharing common predicate labels.

    Args:
        clauses: Each clause is a list of predicate label names (strings)
        min_shared: Minimum shared predicates to consider a cluster
        max_varying: Maximum varying predicates (skip clusters that are too diverse)

    Returns:
        Sorted list of clusters (largest first), each with:
            clause_indices, size, common_predicates, varying_predicates
    """
    # Build inverted index: predicate -> set of clause indices
    pred_to_clauses: Dict[str, Set[int]] = defaultdict(set)
    for i, clause in enumerate(clauses):
        for pred in clause:
            pred_to_clauses[pred].add(i)

    clustered: Set[int] = set()
    results = []

    for i, clause in enumerate(clauses):
        if i in clustered:
            continue

        common_preds = set(clause)
        cluster = {i}

        for j, other in enumerate(clauses):
            if j <= i or j in clustered:
                continue
            shared = common_preds & set(other)
            if len(shared) >= min_shared:
                cluster.add(j)
                common_preds &= set(other)  # refine common core

        if len(cluster) >= 2:
            clustered.update(cluster)

            all_preds = [set(clauses[j]) for j in cluster]
            core = set.intersection(*all_preds) if all_preds else set()
            varying: Set[str] = set()
            for pset in all_preds:
                varying.update(pset - core)

            if len(varying) <= max_varying:
                results.append(
                    {
                        "clause_indices": sorted(cluster),
                        "size": len(cluster),
                        "common_predicates": sorted(core),
                        "varying_predicates": sorted(varying),
                    }
                )

    results.sort(key=lambda r: r["size"], reverse=True)
    return results


def format_cluster_for_prompt(
    cluster: Dict,
    cluster_id: str = "",
    property_text: str = "",
    init_preds: Optional[List[str]] = None,
) -> str:
    """Format a clause cluster as human-readable text for LLM prompt.

    Args:
        cluster: Output from cluster_clauses()
        cluster_id: Label for this cluster (e.g., 'cluster_01')
        property_text: Design property text for tag generation
        init_preds: Initial IC3IA predicates for tag generation
    """
    lines = []
    label = f"Cluster {cluster_id}" if cluster_id else "Cluster"
    lines.append(f"{label}: {cluster['size']} similar clauses")

    lines.append("  Common core predicates (shared across all clauses):")
    for p in cluster["common_predicates"][:6]:
        tags = tag_predicate(p, property_text, init_preds)
        tag_str = f"  [{', '.join(t for t in tags if not t.startswith('WARNING:'))}]" if tags else ""
        warning = [t for t in tags if t.startswith("WARNING:")]
        lines.append(f"    {p} {tag_str}")
        for w in warning:
            lines.append(f"      ⚠ {w}")

    lines.append("  Varying predicates (differ across clauses):")
    for p in cluster["varying_predicates"][:10]:
        tags = tag_predicate(p, property_text, init_preds)
        tag_str = f"  [{', '.join(t for t in tags if not t.startswith('WARNING:'))}]" if tags else ""
        lines.append(f"    {p} {tag_str}")

    lines.append(
        f"  Task: generate a broader lemma that may subsume all {cluster['size']} clauses."
    )
    return "\n".join(lines)


def format_all_clusters_for_prompt(
    clusters: List[Dict],
    property_text: str = "",
    init_preds: Optional[List[str]] = None,
) -> str:
    """Format all clusters for LLM prompt with optional role tags."""
    if not clusters:
        return "(no clause clusters identified)"

    parts = []
    for i, cluster in enumerate(clusters[:10]):
        parts.append(format_cluster_for_prompt(
            cluster, f"cluster_{i:02d}",
            property_text=property_text,
            init_preds=init_preds,
        ))
        parts.append("")
    return "\n".join(parts)
