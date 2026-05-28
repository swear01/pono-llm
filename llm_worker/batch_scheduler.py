#!/usr/bin/env python3
"""Batch scheduler: deterministic, cache-friendly, diverse batches for LLM generation."""

import json, hashlib, os
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from pathlib import Path

from cluster_pool import ClusterInfo, diversify_pool, build_cluster_pool
from lemma_schema import get_schema_list_for_prompt


@dataclass
class BatchDef:
    batch_id: str = ""
    clusters: List[ClusterInfo] = field(default_factory=list)
    candidate_budget: int = 30


def deterministic_batch_key(batch: BatchDef) -> str:
    """Stable cache key for a batch."""
    obj = {
        "clusters": sorted((
            {"id": c.cluster_id, "vars": sorted(c.vars)}
            for c in batch.clusters
        ), key=lambda x: x["id"]),
        "budget": batch.candidate_budget,
    }
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True).encode()
    ).hexdigest()[:16]


def schedule_batches(pool: List[ClusterInfo], clusters_per_batch: int = 2,
                     candidates_per_cluster: int = 15) -> List[BatchDef]:
    """Deterministic, diversity-aware batch scheduling."""
    batches = []
    for i in range(0, len(pool), clusters_per_batch):
        chunk = pool[i:i + clusters_per_batch]
        if len(chunk) < 1: continue
        budget = len(chunk) * candidates_per_cluster
        batch = BatchDef(
            batch_id=f"B{i // clusters_per_batch:02d}",
            clusters=chunk,
            candidate_budget=budget,
        )
        batch.batch_key = deterministic_batch_key(batch)
        batches.append(batch)
    return batches


def build_batch_prompt(batch: BatchDef, benchmark_context: dict) -> str:
    """Build a prompt for batch LLM lemma generation.

    Prompt layout (cache-friendly):
      [Layer 0] Static instruction + rules
      [Layer 1] Schema library
      [Layer 2] Benchmark-level stable context
      [Layer 3] Batch-specific cluster context
    """
    parts = []

    # ≡≡≡ Layer 0: Static instruction (same for all batches) ≡≡≡
    parts.append(
        "You are assisting a word-level IC3IA hardware model checker (Pono).\n"
        "Your task: Generate diverse candidate inductive lemmas for "
        "specific clusters of related CTI variables.\n\n"
        "RULES:\n"
        "- Generate multiple diverse lemmas per cluster (NOT just 1).\n"
        "- Use ONLY the allowed lemma schemas listed below.\n"
        "- Do NOT generate direct CTI literal rewrites.\n"
        "- Generate state-only lemmas; avoid constraining primary inputs.\n"
        "- All candidates will be validated by formal SMT checks.\n"
        "- Vary lemma families within each cluster.\n"
        "- Return JSON only."
    )

    # ≡≡≡ Layer 1: Schema library ≡≡≡
    parts.append("ALLOWED LEMMA SCHEMAS:\n" + get_schema_list_for_prompt())

    # ≡≡≡ Layer 2: Benchmark context ≡≡≡
    ctx_parts = []
    for key in ["target_property", "hot_variables", "transition_slice"]:
        val = benchmark_context.get(key, "")
        if val and val != "(none)" and val != "(unknown)":
            ctx_parts.append(f"{key.upper()}: {val[:400]}")
    if ctx_parts:
        parts.append("BENCHMARK CONTEXT:\n" + "\n".join(ctx_parts))

    # ≡≡≡ Layer 3: Batch-specific clusters ≡≡≡
    for c in batch.clusters:
        parts.append(
            f"CLUSTER {c.cluster_id}:\n"
            f"  Variables: {', '.join(c.vars)}\n"
            f"  CTI coverage: {c.coverage:.0%}\n"
            f"  Cluster size: {c.cluster_size}\n"
            f"  Non-reset vars: {c.non_reset_var_count}"
        )

    # ≡≡≡ Output contract — STRICT ≡≡≡
    per_cluster = batch.candidate_budget // len(batch.clusters)
    cluster_ids = [c.cluster_id for c in batch.clusters]
    cluster_req = "; ".join("exactly " + str(per_cluster) + " for " + cid for cid in cluster_ids)
    first_cid = cluster_ids[0] if cluster_ids else "C000"
    total = batch.candidate_budget

    contract = (
        "OUTPUT CONTRACT — YOU MUST FOLLOW EXACTLY\n"
        "Return exactly one JSON object. Nothing else.\n"
        "No markdown. No explanation outside JSON.\n"
        "No text before or after the JSON object.\n\n"
        'The top-level JSON object MUST have this shape:\n'
        '{\n'
        '  "batch_id": "' + batch.batch_id + '",\n'
        '  "candidates": [\n'
        '    {\n'
        '      "candidate_id": "' + batch.batch_id + '_' + first_cid + '_001",\n'
        '      "cluster_id": "' + first_cid + '",\n'
        '      "lemma": "(=> (= mode RUN) (< cnt limit))",\n'
        '      "schema": "guarded_implication",\n'
        '      "variables_used": ["mode", "cnt"],\n'
        '      "intuition": "brief reasoning",\n'
        '      "risk_level": "low|medium|high"\n'
        '    },\n'
        '    {\n'
        '      "candidate_id": "' + batch.batch_id + '_' + first_cid + '_002",\n'
        '      "cluster_id": "' + first_cid + '",\n'
        '      "lemma": "...",\n'
        '      "schema": "...",\n'
        '      "variables_used": ["..."],\n'
        '      "intuition": "...",\n'
        '      "risk_level": "low|medium|high"\n'
        '    }\n'
        '  ]\n'
        '}\n\n'
        "REQUIREMENTS:\n"
        '- The top-level key "candidates" IS MANDATORY.\n'
        '- "candidates" MUST be an array, not a single object.\n'
        "- Generate exactly " + str(total) + " candidates total (" + cluster_req + ").\n"
        "- Use exactly the schemas listed above.\n"
        "- Vary risk levels and lemma families.\n\n"
        "INVALID — DO NOT DO THIS:\n"
        '{\n'
        '  "candidate_id": "...",\n'
        '  "lemma": "..."\n'
        '}\n'
        'This is invalid because "candidates" array is MISSING.\n\n'
        "Generate now: only the JSON object, nothing else."
    )

    parts.append(contract)

    return "\n\n".join(parts)


# ≡≡≡ CLI test ≡≡≡
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python batch_scheduler.py <req.jsonl> [--dry-run]")
        sys.exit(1)

    req_path = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    pool = build_cluster_pool(req_path, min_cov=0.03, max_pool=30)
    diverse = diversify_pool(pool, target=8)
    batches = schedule_batches(diverse, clusters_per_batch=2, candidates_per_cluster=15)

    # Load benchmark context
    with open(req_path) as f:
        first = json.loads(f.readline())
    ctx = {
        "target_property": first.get("property", "(unknown)")[:300],
        "hot_variables": "see cluster sections",
        "transition_slice": "(from BTOR2 explainer)",
    }

    print(f"Pool: {len(pool)}, Diverse: {len(diverse)}, Batches: {len(batches)}")
    for b in batches:
        prompt = build_batch_prompt(b, ctx)
        print(f"\n{b.batch_id}: {len(b.clusters)} clusters, budget={b.candidate_budget}, "
              f"prompt={len(prompt)} chars, key={b.batch_key}")

    if not dry_run and batches:
        # Save first batch prompt
        out = "/tmp/batch_prompt.txt"
        Path(out).write_text(build_batch_prompt(batches[0], ctx))
        print(f"\nFirst batch prompt saved to {out}")


def build_batch_prompt_v2(batch, benchmark_context):
    """Rich cluster-context batch prompt with semantic lemma framing."""
    from pathlib import Path
    prompt_dir = Path(__file__).resolve().parent / "prompts"
    v2_template = (prompt_dir / "batch_generation_v2.txt").read_text()

    # Build rich cluster blocks
    cluster_blocks = []
    for c in batch.clusters:
        block = (
            f"Cluster {c.cluster_id}\n"
            f"Purpose: Find semantic lemmas that explain or block this CTI cluster.\n"
            f"Priority score: {c.score:.2f}\n"
            f"Cluster size: {c.cluster_size} CTIs\n"
            f"CTI literal coverage: {c.coverage:.0%}\n"
            f"Reset flag ratio: {c.reset_flag_ratio:.0%}\n"
            f"Trivial literal ratio: {c.trivial_literal_ratio:.0%}\n"
            f"Non-reset variables: {c.non_reset_var_count}\n\n"
            f"Hot state variables:\n"
        )
        for v in c.vars:
            block += f"- {v}\n"
        block += (
            f"\nSuggested lemma families:\n"
            f"- mutual_exclusion, guarded_implication, mode_exclusion,\n"
            f"  bitslice_disequality, range_bound, equality, disequality\n"
            f"\nGenerate exactly {batch.candidate_budget // len(batch.clusters)} "
            f"candidates for {c.cluster_id}.\n"
        )
        cluster_blocks.append(block)

    batch_context = (
        f"Batch ID: {batch.batch_id}\n"
        f"Number of clusters: {len(batch.clusters)}\n"
        f"Candidates per cluster: {batch.candidate_budget // len(batch.clusters)}\n"
        f"Total candidates required: {batch.candidate_budget}\n\n"
        + "\n".join(cluster_blocks)
    )

    # Output contract
    contract = (
        "\n\nOUTPUT CONTRACT — STRICT\n\n"
        'Return exactly one JSON object and nothing else.\n'
        'The top-level JSON object MUST have this exact shape:\n\n'
        '{\n'
        '  "batch_id": "' + batch.batch_id + '",\n'
        '  "candidates": [\n'
        '    {\n'
        '      "candidate_id": "' + batch.batch_id + '_' + batch.clusters[0].cluster_id + '_001",\n'
        '      "cluster_id": "' + batch.clusters[0].cluster_id + '",\n'
        '      "lemma": "...",\n'
        '      "schema": "guarded_implication",\n'
        '      "variables": ["var1", "var2"],\n'
        '      "intuition": "brief reasoning",\n'
        '      "risk": "low|medium|high"\n'
        '    }\n'
        '  ]\n'
        '}\n\n'
        "REQUIREMENTS:\n"
        '- The key "candidates" IS MANDATORY.\n'
        '- "candidates" MUST be an array, never a single object.\n'
        "- Generate exactly " + str(batch.candidate_budget) + " candidates total.\n"
        "- Candidate IDs must be unique.\n"
        "- Do NOT wrap JSON in markdown.\n"
        "- Do NOT include explanations outside JSON.\n\n"
        "INVALID (single object, no candidates array):\n"
        '{"candidate_id": "...", "lemma": "..."}\n\n'
        "Generate now: only the JSON object, nothing else."
    )

    return v2_template + "\n\n" + batch_context + contract
