#!/usr/bin/env python3
"""MVP driver: template-guided semantic lemma generation.

Usage:
  # Generate CTI contexts from pono
  build/pono -e ic3ia --llm-gen-mode async-cti --llm-candidate-language cube-subset \
    --llm-model deepseek-v4-pro --llm-req-path /tmp/mvp/req.jsonl foo.btor2

  # Run MVP driver on captured CTIs
  python3 llm_worker/run_mvp.py --req-path /tmp/mvp/req.jsonl --output /tmp/mvp/report.json

  # Or run end-to-end with sidecar
  python3 llm_worker/run_mvp.py --benchmark foo.btor2
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional


def build_context_bundle(req_path: str, pono_stderr: str = "", btor2_path: str = "") -> Dict:
    """Read CTI contexts from JSONL and build a context bundle."""
    with open(req_path) as f:
        lines = [json.loads(line) for line in f if line.strip()]

    if not lines:
        raise ValueError(f"No CTI contexts found in {req_path}")

    # Use the first multi-CTI batch (or first single CTI if no batch)
    first = lines[0]
    ctis = first.get("cti_contexts", [first] if "literals" in first else [])
    if not ctis and "literals" in first:
        ctis = [first]

    # Build hot variable list from CTI literals
    from transition_slice import (
        extract_hot_variables,
        format_variable_list,
        summarize_cti_batch,
        extract_design_context,
        extract_btor_transition,
        format_btor_transition,
        explain_transition_slice,
    )

    all_lits = []
    for cti in ctis[:15]:
        all_lits.extend(cti.get("literals", []))
    hot_vars = extract_hot_variables(all_lits)

    # Build clause clusters (heuristic: group by shared signal names)
    from clause_cluster import (
        cluster_clauses,
        format_all_clusters_for_prompt,
    )

    clauses = []
    for cti in ctis[:15]:
        clause = [lit.get("varname", "") for lit in cti.get("literals", [])]
        if len(clause) >= 2:
            # Split each literal into individual predicate-like tokens
            tokens = []
            for c in clause:
                # Extract variable names as tokens
                import re
                for m in re.finditer(r'\b(state\d+|input\d+|[a-z_]{3,})\b', c):
                    tokens.append(m.group(1))
            if len(tokens) >= 2:
                clauses.append(tokens)

    clusters = cluster_clauses(clauses, min_shared=1) if clauses else []

    # Design context from pono stderr
    design_ctx = {}
    if pono_stderr and os.path.exists(pono_stderr):
        with open(pono_stderr) as f:
            design_ctx = extract_design_context(f.read())

    # BTOR2 transition info for hot state variables
    btor_transition = {}
    trans_text = "(no BTOR2 transition info extracted — provide --btor2-path)"
    if btor2_path and os.path.exists(btor2_path):
        import json as _json
        btor_transition = extract_btor_transition(btor2_path, hot_vars)
        # Parse BTOR2 for expression expansion
        btor_data = {}
        for line in open(btor2_path):
            parts = line.strip().split()
            if not parts or parts[0][0] == ";": continue
            lid = parts[0]
            try: int(lid)
            except: continue
            btor_data[lid] = parts[1:]
        trans_text = explain_transition_slice(btor_transition, btor_data)
        if not trans_text.strip():
            trans_text = "(BTOR2 expressions could not be expanded)"

    clusters_text = format_all_clusters_for_prompt(
        clusters,
        property_text=design_ctx.get("property", ""),
        init_preds=design_ctx.get("initial_predicates", []),
    )

    return {
        "_hot_vars": hot_vars,
        "design_context": design_ctx,
        "target_property": first.get("property", "(unknown)")[:500],
        "hot_variables": format_variable_list(hot_vars),
        "transition_slice": trans_text,
        "cti_batch": summarize_cti_batch(ctis, max_ctis=10, max_lits_per_cti=10),
        "clause_clusters": clusters_text,
        "lemma_memory": {},
        "previous_failure": {
            "cti_literal": "",
            "candidate": "(=> (= state434 0) (= input10 0))",
            "input_constrained": True,
            "issue": "candidate constrains primary input 'input10' in consequent — needs repair to state-only form",
        },
        "candidate_language": "template-guided",
        "model": first.get("model", "deepseek-v4-pro"),
        "frame_idx": first.get("frame_idx", 1),
    }


def run_sidecar(req_path: str, resp_path: str, model: str, timeout: int = 600) -> bool:
    """Run sidecar to process one template-guided request."""
    sidecar = Path(__file__).resolve().parent / "sidecar.py"

    env = os.environ.copy()
    proc = subprocess.run(
        [
            sys.executable, "-u", str(sidecar),
            "--req-path", req_path,
            "--resp-path", resp_path,
            "--candidate-language", "template-guided",
            "--max-requests", "1",
            "--poll-interval", "0.5",
            "--model", model,
        ],
        capture_output=True, text=True, timeout=timeout,
        env=env,
    )
    print(f"Sidecar stdout: {proc.stdout[-300:]}")
    if proc.stderr:
        print(f"Sidecar stderr: {proc.stderr[-300:]}")
    return proc.returncode == 0 and os.path.exists(resp_path)


def validate_candidates(
    resp_path: str, cti_lits: List[dict],
    design_state_vars: list = None,
    design_input_vars: list = None,
) -> List[dict]:
    """Run cheap validation on LLM candidates."""
    from lemma_schema import (
        validate_lemma_syntax,
        check_triviality,
        detect_cube_subset,
        get_schema_names,
        check_input_constraint,
    )

    results = []
    try:
        with open(resp_path) as f:
            candidate = json.loads(f.readline())
    except (FileNotFoundError, json.JSONDecodeError):
        return [{"error": "no valid response"}]

    lemma = candidate.get("lemma", "")
    schema = candidate.get("schema", candidate.get("lemma_type", "unknown"))
    schema_valid = schema in get_schema_names()

    results.append({
        "id": candidate.get("id", "cand_000"),
        "lemma": lemma,
        "schema": schema,
        "schema_valid": schema_valid,
        "syntax_valid": validate_lemma_syntax(lemma) if lemma else False,
        "trivial": check_triviality(lemma) if lemma else "empty lemma",
        "nontrivial": check_triviality(lemma) is None if lemma else False,
        "cube_subset_like": detect_cube_subset(lemma, cti_lits) if lemma else False,
        "target_clusters": candidate.get("target_clusters", []),
        "variables_used": candidate.get("variables_used", []),
        "intuition": candidate.get("intuition", ""),
        "risk_level": candidate.get("risk_level", "unknown"),
        "raw_type": candidate.get("type", "?"),
        "input_constrained": check_input_constraint(
            lemma, candidate.get("variables_used", []),
            design_state_vars, design_input_vars,
        ) if lemma else None,
    })

    return results


def main():
    parser = argparse.ArgumentParser(description="MVP: template-guided lemma generation")
    parser.add_argument("--req-path", help="Path to JSONL CTI context file from pono")
    parser.add_argument("--pono-stderr", default="", help="Path to pono stderr log (for design context)")
    parser.add_argument("--btor2-path", default="", help="Path to BTOR2 file (for transition extraction)")
    parser.add_argument("--output", default="/tmp/mvp_report.json", help="Output report path")
    parser.add_argument("--model", default="deepseek-v4-pro", help="LLM model")
    parser.add_argument("--timeout", type=int, default=600, help="Sidecar timeout (seconds)")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM, just build context")
    args = parser.parse_args()

    if not args.req_path:
        parser.error("--req-path is required")

    # Step 1: Build context bundle
    print("=== Step 1: Building context bundle ===")
    ctx = build_context_bundle(args.req_path, args.pono_stderr, args.btor2_path)
    print(f"  Hot variables: {ctx['hot_variables'].count(chr(10))} variables")
    print(f"  CTI batch: {len(ctx['cti_batch'])} chars")
    print(f"  Clusters: {ctx['clause_clusters'][:100]}...")

    # Gather CTI literals for validation
    with open(args.req_path) as f:
        all_cti = [json.loads(line) for line in f if line.strip()]
    cti_literals = []
    for c in all_cti[:15]:
        cti_literals.extend(c.get("literals", []))

    # Step 2: Write context to JSONL file
    tmpdir = tempfile.mkdtemp(prefix="mvp_")
    req_file = os.path.join(tmpdir, "context.jsonl")
    resp_file = os.path.join(tmpdir, "response.jsonl")
    with open(req_file, "w") as f:
        json.dump(ctx, f)  # no newline — sidecar reads single line

    if args.no_llm:
        print(f"\nContext written to {req_file} (--no-llm, skipping LLM call)")
        # Write context to output
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            json.dump({"context": ctx, "candidates": []}, f, indent=2)
        print(f"Output: {args.output}")
        return 0

    # Step 3: Run sidecar
    print(f"\n=== Step 2: Running LLM ({args.model}, timeout={args.timeout}s) ===")
    start = time.time()
    ok = run_sidecar(req_file, resp_file, args.model, args.timeout)
    elapsed = time.time() - start
    print(f"  Sidecar {'OK' if ok else 'FAILED'} in {elapsed:.0f}s")

    # Step 4: Validate
    print("\n=== Step 3: Validating candidates ===")

    # Save raw response for debugging
    if os.path.exists(resp_file):
        with open(resp_file) as f:
            raw = f.read()
        raw_path = args.output.replace('.json', '_raw_response.json')
        with open(raw_path, 'w') as f:
            f.write(raw)
        print(f"  Raw response: {raw_path} ({len(raw)} chars)")
        print(f"  Raw first 500: {raw[:500]}")

    design_input = [v for v in ctx["_hot_vars"] if v.startswith("input")]
    report = validate_candidates(resp_file, cti_literals, ctx["_hot_vars"], design_input)

    for r in report:
        if "error" in r:
            print(f"  ERROR: {r['error']}")
            continue
        print(f"\n  Candidate: {r['id']}")
        print(f"    Lemma:      {r['lemma'][:120]}")
        print(f"    Schema:     {r['schema']} (valid={r['schema_valid']})")
        print(f"    Syntax:     {'PASS' if r['syntax_valid'] else 'FAIL'}")
        print(f"    Trivial:    {r['trivial'] or 'none'}")
        print(f"    Nontrivial: {r['nontrivial']}")
        print(f"    Cube-subset:{r['cube_subset_like']}")
        print(f"    Clusters:   {r['target_clusters']}")
        print(f"    Variables:  {r['variables_used']}")
        print(f"    Intuition:  {r['intuition'][:200]}")

    # Step 5: Save report
    output_data = {
        "context_summary": {
            "hot_variables": ctx["hot_variables"],
            "cti_batch_size": len(ctx["cti_batch"]),
            "clusters": ctx["clause_clusters"][:200],
        },
        "llm_latency_s": round(elapsed, 1),
        "candidates": report,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=2)
    print(f"\nReport: {args.output}")

    # Cleanup
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
