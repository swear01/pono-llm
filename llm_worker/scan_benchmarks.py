#!/usr/bin/env python3
"""Benchmark suitability scanner for LLM lemma generalization.

Scores benchmarks based on structural features that enable nontrivial
lemma synthesis: FSM/counter structure, state dependencies, clause clusters.

Usage:
  python3 llm_worker/scan_benchmarks.py --bench-dir ~/hwmcc_benchmarks --top 10
  python3 llm_worker/scan_benchmarks.py --btor2 path/to/foo.btor2 --json
"""

import argparse
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple


def parse_btor2(path: str) -> dict:
    """Parse BTOR2 file into indexed expression map."""
    btor = {}
    for line in open(path):
        parts = line.strip().split()
        if not parts or parts[0][0] == ";":
            continue
        lid = parts[0]
        try:
            int(lid)
        except ValueError:
            continue
        btor[lid] = parts[1:]
    return btor


def classify_var(btor: dict, sid: str) -> dict:
    """Analyze a state variable's transition structure."""
    info = {
        "var": f"state{sid}",
        "kind": "unknown",
        "state_deps": 0,
        "input_deps": 0,
        "next_is_const": False,
        "init_is_const": False,
        "next_val": "?",
        "init_val": "?",
        "reset_flag_like": False,
    }

    p = btor.get(sid, [])
    if len(p) < 2 or p[0] != "state":
        return info

    info["width"] = int(p[1])

    # Find next-state
    next_id = None
    init_id = None
    for lid, p2 in btor.items():
        if p2[0] == "next" and len(p2) >= 4 and p2[2] == sid:
            next_id = p2[3]
        if p2[0] == "init" and len(p2) >= 4 and p2[2] == sid:
            init_id = p2[3]

    def _get_deps(lid, visited=None):
        if visited is None:
            visited = set()
        if lid in visited or lid not in btor:
            return set()
        visited.add(lid)
        p2 = btor[lid]
        if p2[0] == "state":
            return {f"state{lid}"}
        if p2[0] == "input":
            return {p2[2] if len(p2) > 2 else f"input{lid}"}
        if p2[0] in ("const", "zero", "ones", "sort", "bitvec"):
            return set()
        deps = set()
        for arg in p2[1:]:
            try:
                deps |= _get_deps(arg, visited)
            except Exception:
                pass
        return deps

    def _get_const(lid):
        if lid and lid in btor and btor[lid][0] == "const":
            return btor[lid][2] if len(btor[lid]) > 2 else "?"
        if lid and lid in btor and btor[lid][0] == "zero":
            return "0"
        return None

    if next_id:
        deps = _get_deps(next_id)
        info["state_deps"] = len([d for d in deps if d.startswith("state")])
        info["input_deps"] = len(deps) - info["state_deps"]
        info["next_is_const"] = next_id in btor and btor[next_id][0] == "const"
        info["next_val"] = _get_const(next_id) or f"<L{next_id}>"

    if init_id:
        info["init_is_const"] = init_id in btor and btor[init_id][0] == "const"
        info["init_val"] = _get_const(init_id) or f"<L{init_id}>"

    # Classify
    if info["next_is_const"] and info.get("width") == 1:
        info["kind"] = "reset_flag"  # transitions to constant
        info["reset_flag_like"] = True
    elif info["state_deps"] >= 2:
        info["kind"] = "counter_like"  # depends on multiple states
    elif info["state_deps"] == 1:
        info["kind"] = "fsm_like"  # depends on one state (self or another)
    elif info["input_deps"] >= 1:
        info["kind"] = "data_reg"
    else:
        info["kind"] = "constant_like"

    return info


def score_benchmark(btor: dict, req_path: str = "") -> dict:
    """Compute suitability score for a benchmark."""
    reasons = []
    score = 0

    # Collect state variables
    state_ids = [lid for lid, p in btor.items() if p[0] == "state"]
    num_states = len(state_ids)
    num_inputs = len([lid for lid, p in btor.items() if p[0] == "input"])

    # Analyze each state var
    var_infos = {}
    fsm_count = 0
    counter_count = 0
    reset_flag_count = 0
    nontrivial_deps_count = 0

    for sid in state_ids[:100]:  # cap for performance
        info = classify_var(btor, sid)
        var_infos[sid] = info
        if info["kind"] == "fsm_like":
            fsm_count += 1
        elif info["kind"] == "counter_like":
            counter_count += 1
        elif info["reset_flag_like"]:
            reset_flag_count += 1

        if info["state_deps"] >= 2:
            nontrivial_deps_count += 1

    # Score
    if fsm_count >= 1:
        score += 2
        reasons.append(f"+2: {fsm_count} FSM-like state vars")

    if counter_count >= 1:
        score += 2
        reasons.append(f"+2: {counter_count} counter-like state vars")

    if nontrivial_deps_count >= 1:
        score += 2
        reasons.append(f"+2: {nontrivial_deps_count} vars with >=2 state dependencies")

    if fsm_count + counter_count >= 2:
        score += 1
        reasons.append(f"+1: multiple nontrivial state vars")

    if reset_flag_count > num_states * 0.3:
        score -= 3
        reasons.append(f"-3: {reset_flag_count} reset-flag vars dominate")

    # CTI/cluster analysis (if req_path available)
    cti_varying = 0
    max_cluster = 0
    if req_path and os.path.exists(req_path):
        try:
            with open(req_path) as f:
                cti_lines = [json.loads(l) for l in f if l.strip()]
            ctis = []
            for line in cti_lines:
                if "cti_contexts" in line:
                    ctis = line["cti_contexts"]
                    break
                elif "literals" in line:
                    ctis = [line]

            # Count varying state vars across CTIs
            all_state_vals = defaultdict(set)
            for cti in ctis[:20]:
                for lit in cti.get("literals", []):
                    for m in re.finditer(r"\b(state\d+)\b", lit.get("varname", "")):
                        sv = m.group(1)
                        all_state_vals[sv].add(lit.get("value", "?"))

            cti_varying = len([sv for sv, vals in all_state_vals.items() if len(vals) >= 2])

            if cti_varying >= 2:
                score += 1
                reasons.append(f"+1: {cti_varying} varying state vars in CTI batch")

            # Rough cluster size estimate
            clause_groups = defaultdict(list)
            for i, cti in enumerate(ctis[:20]):
                key = tuple(sorted(set(
                    m.group(1) for lit in cti.get("literals", [])
                    for m in re.finditer(r"\b(state\d+)\b", lit.get("varname", ""))
                )))
                clause_groups[key].append(i)
            max_cluster = max((len(v) for v in clause_groups.values()), default=0)

            if max_cluster >= 5:
                score += 1
                reasons.append(f"+1: max clause cluster size {max_cluster}")

        except Exception:
            pass

    # Penalize if most state vars are reset-flags
    if cti_varying == 0 and fsm_count + counter_count == 0:
        score -= 2
        reasons.append("-2: no varying state vars, no FSM/counter structure")

    top_vars = sorted(var_infos.values(),
                      key=lambda v: v["state_deps"] + v["input_deps"],
                      reverse=True)[:5]

    return {
        "score": score,
        "reasons": reasons,
        "stats": {
            "num_state_vars": num_states,
            "num_input_vars": num_inputs,
            "fsm_like_count": fsm_count,
            "counter_like_count": counter_count,
            "reset_flag_count": reset_flag_count,
            "vars_with_state_deps_ge2": nontrivial_deps_count,
            "cti_varying_state_vars": cti_varying,
            "max_cluster_size": max_cluster,
        },
        "top_vars": top_vars,
    }


def find_btor2_files(hwmcc_dir: str, years: List[int] = None) -> List[str]:
    """Find all BTOR2 files in HWMCC directory."""
    if years is None:
        years = [2020, 2024, 2025]
    files = []
    base = Path(hwmcc_dir)
    for year in years:
        year_dir = base / str(year)
        if year_dir.exists():
            files.extend(str(p) for p in year_dir.rglob("*.btor2")[:200])
    return files


def main():
    p = argparse.ArgumentParser(description="Benchmark suitability scanner")
    p.add_argument("--btor2", help="Single BTOR2 file to score")
    p.add_argument("--req-path", help="CTI context JSONL from pono (for CTI-aware scoring)")
    p.add_argument("--bench-dir", help="HWMCC benchmarks directory for batch scanning")
    p.add_argument("--top", type=int, default=10, help="Show top N results")
    p.add_argument("--json", action="store_true", help="Output full JSON")
    args = p.parse_args()

    if args.btor2:
        btor = parse_btor2(args.btor2)
        result = {os.path.basename(args.btor2): score_benchmark(btor)}
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            for name, r in result.items():
                print(f"{name}: score={r['score']}")
                for reason in r["reasons"]:
                    print(f"  {reason}")
                for v in r["top_vars"][:3]:
                    print(f"  top var: {v['var']} kind={v['kind']} state_deps={v['state_deps']} next_is_const={v['next_is_const']}")
        return 0

    if args.bench_dir:
        files = find_btor2_files(args.bench_dir)
        if not files:
            print("No BTOR2 files found")
            return 1

        results = {}
        for f in files[:100]:  # limit for speed
            btor = parse_btor2(f)
            results[os.path.basename(f)] = score_benchmark(btor)

        ranked = sorted(results.items(), key=lambda x: x[1]["score"], reverse=True)

        if args.json:
            print(json.dumps(dict(ranked[:args.top]), indent=2))
        else:
            for name, r in ranked[:args.top]:
                print(f"{name}: score={r['score']}")
                for reason in r["reasons"]:
                    print(f"  {reason}")
                for v in r["top_vars"][:3]:
                    print(f"  top var: {v['var']} kind={v['kind']} state_deps={v['state_deps']} next_is_const={v['next_is_const']}")
                print()

        return 0

    p.print_help()
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())


def score_readability(btor: dict, state_ids: list) -> tuple:
    """Score how readable BTOR2 transitions are for LLM.
    Returns (score, reasons, opaque_count, total_count)."""
    from transition_slice import explain_btor_expr
    opaque = 0
    total = 0
    reasons = []
    for sid in state_ids[:30]:
        next_id = None
        for lid, p in btor.items():
            if p[0] == "next" and len(p) >= 4 and p[2] == sid:
                next_id = p[3]
                break
        if not next_id:
            continue
        total += 1
        expanded = explain_btor_expr(btor, next_id, 0)
        oc = expanded.count("op=")
        if oc > 0:
            opaque += 1
        if len(expanded) > 300:
            opaque += 1
    score = 10
    if total > 0:
        ratio = opaque / total
        if ratio > 0.5: score -= 6
        elif ratio > 0.2: score -= 3
        elif ratio > 0: score -= 1
    return score, reasons, opaque, total
