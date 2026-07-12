#!/usr/bin/env python3
"""Capture frozen LLM predicate candidates for replay.

This script performs only candidate generation. It does not claim any proof.
Each benchmark gets:
  - <slug>.jsonl       predicate_ast JSON lines, refs rewritten to state<lineno>
  - <slug>.meta.json   timing/model/prompt/candidate metadata
  - <slug>.prompt.txt  exact prompt sent to the LLM
  - system_prompt.txt  exact shared system prompt
  - provenance.json    Git/source hashes for the capture implementation
  - manifest.json      map from benchmark path to output files

Use --rounds 0 for a no-API smoke run that writes prompts/metadata only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT_DIR / "llm_worker"))

from btor2_reader import parse_btor2  # noqa: E402
from invariant_arith import build_software_prompt, detect_software_origin  # noqa: E402
from invariant_prompt import (  # noqa: E402
    INVARIANT_SYSTEM_PROMPT,
    parse_invariant_response_with_diagnostics,
)
from env_config import load_env  # noqa: E402
from experiment_manifest import (  # noqa: E402
    DEFAULT_BENCHMARK_ROOT,
    BenchmarkSpec,
    load_manifest,
    make_spec,
    stable_slug,
    verify_benchmark_content,
    write_capture_integrity,
)

CORPUS_PATTERNS = [
    "**/arithmetic_circuits/**/*.btor2",
    "**/nla-digbench*/**/*.btor2",
    "**/crafted/paper_v3/*.btor2",
]
PROVENANCE_SOURCE_FILES = (
    "scripts/capture_candidates.py",
    "llm_worker/invariant_prompt.py",
    "llm_worker/invariant_arith.py",
    "llm_worker/btor2_reader.py",
    "llm_worker/llm_client.py",
    "llm_worker/env_config.py",
    "llm_worker/openrouter_routing.py",
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def ensure_provenance(out_dir: Path) -> dict:
    system_prompt_path = out_dir / "system_prompt.txt"
    provenance_path = out_dir / "provenance.json"
    system_prompt_path.write_text(INVARIANT_SYSTEM_PROMPT)
    git_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT_DIR, text=True
    ).strip()
    git_status = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=no"],
        cwd=ROOT_DIR,
        text=True,
    )
    provenance = {
        "schema": "pono-llm-capture-provenance-v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "recorded_after_capture": False,
        "git_head": git_head,
        "git_tracked_worktree_dirty": bool(git_status.strip()),
        "system_prompt_file": system_prompt_path.name,
        "system_prompt_sha256": sha256_text(INVARIANT_SYSTEM_PROMPT),
        "source_sha256": {
            relative: hashlib.sha256((ROOT_DIR / relative).read_bytes()).hexdigest()
            for relative in PROVENANCE_SOURCE_FILES
        },
    }
    if provenance_path.exists():
        existing = json.loads(provenance_path.read_text())
        comparable = dict(existing)
        comparable.pop("recorded_at", None)
        expected = dict(provenance)
        expected.pop("recorded_at", None)
        if comparable != expected:
            raise RuntimeError(f"capture provenance changed inside run: {out_dir}")
        return existing
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    return provenance


def collect_circuits(benchmark_root: Path) -> list[BenchmarkSpec]:
    import glob

    out: list[str] = []
    for pattern in CORPUS_PATTERNS:
        out += glob.glob(os.path.join(benchmark_root, pattern), recursive=True)
    return [make_spec(path, benchmark_root) for path in sorted(set(out))]


def ast_to_state_refs(ast, sym2ref):
    a = dict(ast)
    if a.get("form") == "ref":
        r = a.get("ref", "")
        a["ref"] = sym2ref.get(r, r)
    if "args" in a and isinstance(a["args"], list):
        a["args"] = [ast_to_state_refs(x, sym2ref) for x in a["args"]]
    return a


def ast_has_var_mul(a):
    if isinstance(a, dict):
        if a.get("form") == "mul":
            non_const = [x for x in a.get("args", []) if x.get("form") != "const"]
            if len(non_const) >= 2:
                return True
        return any(ast_has_var_mul(x) for x in a.get("args", []))
    return False

def sym2ref_map(info) -> dict[str, str]:
    out: dict[str, str] = {}
    for sv in info.states:
        out[sv.ref] = sv.ref
        if sv.symbol:
            out[sv.symbol] = sv.ref
    return out


def canonical_key(ast: dict) -> str:
    return json.dumps(ast, sort_keys=True, separators=(",", ":"))


def iter_candidates(
    candidates: list[dict], sym2ref: dict[str, str]
) -> Iterable[tuple[dict, str, str]]:
    for cand in candidates:
        ast = cand.get("predicate_ast")
        if not ast:
            continue
        conv = ast_to_state_refs(ast, sym2ref)
        expr = cand.get("verilog_expr", "")
        intuition = cand.get("intuition", "")
        yield conv, expr, intuition


def capture_one(
    benchmark: BenchmarkSpec,
    out_dir: Path,
    client,
    rounds: int,
    effort: str,
    cap: int,
) -> dict:
    provenance = ensure_provenance(out_dir)
    path = str(benchmark.path)
    benchmark_content_sha256 = verify_benchmark_content(benchmark)
    info = parse_btor2(path)
    slug = stable_slug(benchmark.benchmark_id)
    prompt_path = out_dir / f"{slug}.prompt.txt"
    pred_path = out_dir / f"{slug}.jsonl"
    meta_path = out_dir / f"{slug}.meta.json"
    responses_path = out_dir / f"{slug}.responses.jsonl"

    meta = {
        "schema": "pono-llm-candidate-meta-v4",
        "benchmark_id": benchmark.benchmark_id,
        "benchmark_content_sha256": benchmark_content_sha256,
        "slug": slug,
        "provider": getattr(client, "provider", None),
        "model": getattr(client, "model_name", None),
        "software_origin": detect_software_origin(info),
        "rounds": rounds,
        "effort": effort,
        "temperature": 0.3,
        "cap": cap,
        "prompt_file": prompt_path.name,
        "prompt_sha256": "",
        "predicates_file": pred_path.name,
        "predicates_sha256": "",
        "responses_file": responses_path.name,
        "provenance_file": "provenance.json",
        "system_prompt_file": provenance["system_prompt_file"],
        "system_prompt_sha256": provenance["system_prompt_sha256"],
        "latency_sec": 0.0,
        "total_tokens": 0,
        "raw_candidate_count": 0,
        "invalid_candidate_count": 0,
        "candidate_errors": [],
        "dedup_candidate_count": 0,
        "linear_candidate_count": 0,
        "llm_calls": [],
        "status": "in_progress",
    }

    prompt = build_software_prompt({"benchmark": Path(path).name, "btor2_path": path}, info)
    prompt_path.write_text(prompt)
    meta["prompt_sha256"] = sha256_text(prompt)

    seen: dict[str, dict] = {}
    refs = sym2ref_map(info)
    pred_path.write_text("")
    responses_path.write_text("")
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True))

    def write_candidate_snapshot() -> list[dict]:
        vals = list(seen.values())[:cap]
        predicate_text = "\n".join(
            json.dumps({"predicate_ast": value["predicate_ast"]}, sort_keys=True)
            for value in vals
        )
        if predicate_text:
            predicate_text += "\n"
        pred_path.write_text(predicate_text)
        meta["dedup_candidate_count"] = len(vals)
        meta["linear_candidate_count"] = sum(
            1 for value in vals if value["is_linear"]
        )
        meta["predicates_sha256"] = sha256_text(predicate_text)
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True))
        return vals

    write_candidate_snapshot()
    for round_idx in range(rounds):
        t0 = time.monotonic()
        text, tokens, latency_ms = client.call(
            prompt,
            system_prompt=INVARIANT_SYSTEM_PROMPT,
            reasoning_effort=effort,
            temperature=0.3,
            max_tokens=4096,
        )
        elapsed = time.monotonic() - t0
        meta["latency_sec"] += elapsed
        meta["total_tokens"] += int(tokens or 0)
        response_sha256 = sha256_text(text)
        meta["llm_calls"].append({
            "round": round_idx,
            "wall_latency_sec": elapsed,
            "api_latency_ms": float(latency_ms),
            "tokens": int(tokens or 0),
            "response_sha256": response_sha256,
            "client_stats": getattr(client, "last_call_stats", {}),
        })
        response_record = json.dumps({
            "round": round_idx,
            "response": text,
            "response_sha256": response_sha256,
        }, sort_keys=True)
        with responses_path.open("a") as response_file:
            response_file.write(response_record + "\n")
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True))
        candidates, candidate_errors = parse_invariant_response_with_diagnostics(text)
        meta["raw_candidate_count"] += len(candidates) + len(candidate_errors)
        meta["invalid_candidate_count"] += len(candidate_errors)
        meta["candidate_errors"].extend({
            "round": round_idx,
            "index": error["index"],
            "error": error["error"],
        } for error in candidate_errors)
        for ast, expr, intuition in iter_candidates(candidates, refs):
            key = canonical_key(ast)
            if key not in seen:
                seen[key] = {
                    "predicate_ast": ast,
                    "verilog_expr": expr,
                    "intuition": intuition,
                    "is_linear": not ast_has_var_mul(ast),
                }
        write_candidate_snapshot()

    meta["status"] = "completed"
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True))
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", help="CSV with path column or newline-separated path list; default uses predicate_workflow corpus")
    ap.add_argument("--out", required=True, help="Output directory")
    ap.add_argument("--benchmark-root", default=str(DEFAULT_BENCHMARK_ROOT))
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--cap", type=int, default=20)
    ap.add_argument("--effort", default="none")
    ap.add_argument("--max-benchmarks", type=int, default=0)
    args = ap.parse_args()
    if args.rounds < 0:
        ap.error("--rounds must be non-negative")
    if args.cap <= 0:
        ap.error("--cap must be positive")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    if any(out_dir.iterdir()):
        raise FileExistsError(
            f"capture output directory must be empty for an immutable run: {out_dir}"
        )
    benchmark_root = Path(args.benchmark_root).expanduser().resolve()
    benchmarks = (
        load_manifest(args.manifest, benchmark_root)
        if args.manifest
        else collect_circuits(benchmark_root)
    )
    if args.max_benchmarks:
        benchmarks = benchmarks[:args.max_benchmarks]

    client = None
    if args.rounds > 0:
        load_env()
        from llm_client import create_llm_client
        client = create_llm_client()

    entries = []
    for benchmark in benchmarks:
        if not benchmark.path.exists():
            raise FileNotFoundError(benchmark.path)
        if args.rounds == 0:
            class NoClient:
                def call(self, *_, **__):
                    raise RuntimeError("rounds=0 should not call LLM")
            client = NoClient()
        meta = capture_one(
            benchmark, out_dir, client, args.rounds, args.effort, args.cap
        )
        entries.append({
            "benchmark_id": benchmark.benchmark_id,
            "content_sha256": meta["benchmark_content_sha256"],
            "slug": meta["slug"],
            "predicates_file": meta["predicates_file"],
            "metadata_file": f"{meta['slug']}.meta.json",
            "prompt_file": meta["prompt_file"],
            "responses_file": meta["responses_file"],
        })
        print(json.dumps({
            "benchmark_id": benchmark.benchmark_id,
            "slug": meta["slug"],
            "n": meta["dedup_candidate_count"],
        }), flush=True)

    manifest = {
        "schema": "pono-llm-candidate-capture-v4",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_root_env": "HWMCC_ROOT",
        "provenance_file": "provenance.json",
        "system_prompt_file": "system_prompt.txt",
        "integrity_file": "integrity.json",
        "benchmarks": entries,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    write_capture_integrity(
        out_dir,
        {
            entry["benchmark_id"]: entry["content_sha256"]
            for entry in entries
        },
        recorded_after_capture=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
