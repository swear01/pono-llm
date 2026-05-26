#!/usr/bin/env python3
"""Candidate canonicalizer + validator for batch formal gate.

Parses LLM lemma strings into canonical forms, checks syntax,
detects duplicates, classifies schema. No SMT solving yet.
"""

import json, re, hashlib
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple


@dataclass
class GateResult:
    candidate_id: str = ""
    batch_id: str = ""
    cluster_id: str = ""
    raw_lemma: str = ""
    canonical_lemma: str = ""
    schema: str = "unknown"
    variables: List[str] = field(default_factory=list)
    parse_ok: bool = False
    type_ok: bool = False
    dedup_signature: str = ""
    is_duplicate: bool = False
    init_check: str = "not_run"
    one_step_check: str = "not_run"
    induction_check: str = "not_run"
    failure_type: str = ""
    near_miss_score: float = 0.0
    decision: str = "rejected"
    issues: List[str] = field(default_factory=list)


SCHEMA_PATTERNS = [
    ("mutual_exclusion", r"^!\(\s*(\w+)\s*&&\s*(\w+)\s*\)$"),
    ("guarded_implication", r"^\(=>\s+(.+?)\s+(.+?)\)$"),
    ("equality", r"^=\s+(\S+)\s+(\S+)$"),
    ("disequality", r"^(distinct|!=)\s+(\S+)\s+(\S+)$"),
    ("bitslice_range", r"^\(\s*(\w+)\s*\[(\d+):(\d+)\]\s*<=\s*(\S+)\s*\)$"),
]


def extract_variables(lemma: str) -> List[str]:
    """Extract state/input variable names from lemma string."""
    return sorted(set(re.findall(r"\b(state\d+|input\d+)\b", lemma)))


def canonicalize_lemma(lemma: str) -> str:
    """Normalize lemma format for dedup. Strips whitespace, normalizes operators."""
    lemma = re.sub(r"\s+", " ", lemma.strip())
    lemma = lemma.replace("),", ") ,").replace(" ,", ",")
    return lemma


def make_dedup_sig(canonical: str, schema: str, variables: List[str]) -> str:
    """Create dedup signature: schema + sorted variables + normalized lemma."""
    key = f"{schema}|{','.join(sorted(variables))}|{canonical}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def classify_candidate(candidate: dict) -> GateResult:
    """Parse and classify a single LLM candidate."""
    gr = GateResult()
    gr.raw_lemma = candidate.get("lemma", "")
    gr.candidate_id = candidate.get("id", "?")
    gr.batch_id = candidate.get("batch_id", "")
    gr.cluster_id = candidate.get("cluster_id", "")
    gr.schema = candidate.get("schema", "unknown")

    if not gr.raw_lemma:
        gr.parse_ok = False
        gr.issues.append("empty lemma")
        return gr

    # Parse: try to match known schema patterns
    gr.canonical_lemma = canonicalize_lemma(gr.raw_lemma)
    gr.variables = extract_variables(gr.raw_lemma)

    if not gr.variables:
        gr.issues.append("no state/input variables extracted")
    else:
        gr.parse_ok = True

    # Schema validation
    valid_schemas = {
        "mutual_exclusion", "guarded_implication", "equality",
        "disequality", "range", "mode_implication", "bitslice",
        "offset", "stability",
    }
    if gr.schema not in valid_schemas:
        gr.issues.append(f"unknown schema: {gr.schema}")
    else:
        gr.type_ok = True

    # Dedup
    gr.dedup_signature = make_dedup_sig(gr.canonical_lemma, gr.schema, gr.variables)

    # Near-miss score (initial heuristics)
    if gr.parse_ok and gr.type_ok:
        gr.near_miss_score += 1.0
    if len(gr.variables) >= 2:
        gr.near_miss_score += 1.0
    if gr.schema in ("mutual_exclusion", "guarded_implication", "bitslice"):
        gr.near_miss_score += 1.0

    if gr.parse_ok and gr.type_ok:
        gr.decision = "candidate"
    else:
        gr.decision = "rejected"

    return gr


def gate_batch(candidates: List[dict]) -> Tuple[List[GateResult], dict]:
    """Run gate on a batch of candidates.

    Returns: (results, summary)
    """
    results = []
    seen_sigs = set()
    dup_count = 0

    for cand in candidates:
        gr = classify_candidate(cand)
        if gr.dedup_signature and gr.dedup_signature in seen_sigs:
            gr.is_duplicate = True
            gr.decision = "rejected"
            gr.issues.append("duplicate")
            dup_count += 1
        else:
            seen_sigs.add(gr.dedup_signature)
        results.append(gr)

    # Summary
    parse_ok = sum(1 for r in results if r.parse_ok)
    type_ok = sum(1 for r in results if r.type_ok)
    unique = len(results) - dup_count
    candidates = sum(1 for r in results if r.decision == "candidate")

    schemas = {}
    for r in results:
        if r.schema not in schemas: schemas[r.schema] = 0
        schemas[r.schema] += 1

    # Top near-misses
    near_miss = sorted(
        [r for r in results if r.decision == "candidate"],
        key=lambda r: -r.near_miss_score
    )[:5]

    summary = {
        "total": len(results),
        "parse_ok": parse_ok,
        "type_ok": type_ok,
        "unique": unique,
        "duplicates": dup_count,
        "candidates": candidates,
        "near_miss_count": len(near_miss),
        "schema_distribution": schemas,
        "top_near_misses": [
            {
                "id": r.candidate_id,
                "lemma": r.raw_lemma[:150],
                "schema": r.schema,
                "variables": r.variables,
                "score": round(r.near_miss_score, 1),
            } for r in near_miss
        ],
    }
    return results, summary


if __name__ == "__main__":
    import sys
    # Test with a few sample candidates
    samples = [
        {"id": "c1", "lemma": "!(state1359 && state1361)", "schema": "mutual_exclusion", "cluster_id": "C00"},
        {"id": "c2", "lemma": "(distinct state1536[1:0] 2'd1)", "schema": "disequality", "cluster_id": "C01"},
        {"id": "c3", "lemma": "(=> (= mode RUN) (< cnt limit))", "schema": "guarded_implication", "cluster_id": "C02"},
        {"id": "c4", "lemma": "", "schema": "equality", "cluster_id": "C00"},
        {"id": "c5", "lemma": "!(state1359 && state1361)", "schema": "mutual_exclusion", "cluster_id": "C00"},  # duplicate
    ]
    results, summary = gate_batch(samples)
    print(json.dumps(summary, indent=2))
