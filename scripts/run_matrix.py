#!/usr/bin/env python3
"""Replay frozen predicates against fair deterministic and engine baselines."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT_DIR / "llm_worker"))

from candidate_cert_check import (  # noqa: E402
    filter_supported_asts,
    houdini_certify,
)
from experiment_manifest import (  # noqa: E402
    DEFAULT_BENCHMARK_ROOT,
    MATRIX_CONTRACT_FIELDS,
    BenchmarkSpec,
    file_sha256,
    load_manifest,
    make_spec,
    replay_matrix_contract,
    stable_slug,
    validate_capture_bundle,
    verify_benchmark_content,
)
from invariant_prompt import predicate_ast_error  # noqa: E402
from static_predicate_baseline import (  # noqa: E402
    abstraction_closure,
    generate_entries,
    generate_quadratic_entries,
    generate_ranked_entries,
)

PONO = str(ROOT_DIR / "build" / "pono")
CORPUS_PATTERNS = [
    "**/arithmetic_circuits/**/*.btor2",
    "**/nla-digbench*/**/*.btor2",
    "**/crafted/paper_v3/*.btor2",
]
VALID_CONFIGS = {
    "baseline",
    "llm-linear",
    "llm-full",
    "llm-two-tier",
    "llm-houdini-cert",
    "static-linear",
    "static-ranked",
    "static-oracle",
    "static-quadratic-oracle",
    "portfolio",
}
QUADRATIC_TEMPLATE_TIMEOUT_MS = 5000
STATIC_QUADRATIC_POOL_CAP = 2000
ROW_FIELDS = (
    "trial",
    "benchmark_id",
    "benchmark_expected_sha256",
    "benchmark_content_sha256",
    "benchmark_hash_status",
    "benchmark_manifest_sha256",
    *MATRIX_CONTRACT_FIELDS,
    "circuit",
    "config",
    "candidate_capture",
    "capture_manifest_sha256",
    "capture_integrity_sha256",
    "capture_created_at",
    "verdict",
    "proof_time_sec",
    "certificate_time_sec",
    "model_checker_time_sec",
    "candidate_generation_sec",
    "candidate_processing_sec",
    "llm_generation_sec",
    "llm_provider",
    "llm_model",
    "llm_total_tokens",
    "llm_call_count",
    "capture_meta_schema",
    "offline_time_sec",
    "end_to_end_sec",
    "exit",
    "engine",
    "tier",
    "candidate_count",
    "pool_candidate_count",
    "working_candidate_count",
    "selected_candidate_count",
    "affine_selected_candidate_count",
    "quadratic_tested_count",
    "quadratic_timeout_count",
    "quadratic_winner_index",
    "unsupported_candidate_count",
    "candidate_errors",
    "closure_candidate_count",
    "linear_candidate_count",
    "quadratic_candidate_count",
    "candidate_sha256",
    "certificate_status",
    "error",
    "fast_results",
)


def collect_circuits(benchmark_root: Path) -> list[BenchmarkSpec]:
    import glob

    paths: list[str] = []
    for pattern in CORPUS_PATTERNS:
        paths += glob.glob(os.path.join(benchmark_root, pattern), recursive=True)
    return [make_spec(path, benchmark_root) for path in sorted(set(paths))]


def ast_has_var_mul(ast):
    if isinstance(ast, dict):
        if ast.get("form") == "mul":
            non_constants = [
                arg
                for arg in ast.get("args", [])
                if arg.get("form") != "const"
            ]
            if len(non_constants) >= 2:
                return True
        return any(ast_has_var_mul(arg) for arg in ast.get("args", []))
    return False


def candidate_paths(pred_dir: Path, benchmark: BenchmarkSpec) -> tuple[Path, Path]:
    slug = stable_slug(benchmark.benchmark_id)
    return pred_dir / f"{slug}.jsonl", pred_dir / f"{slug}.meta.json"


def load_candidate_capture(
    pred_dir: Path,
    benchmark: BenchmarkSpec,
    capture_bundle: dict | None = None,
) -> tuple[Path, dict, dict]:
    bundle = capture_bundle or validate_capture_bundle(pred_dir, [benchmark])
    record = bundle["records"].get(benchmark.benchmark_id)
    if record is None:
        raise ValueError(
            f"capture is missing benchmark {benchmark.benchmark_id}"
        )
    if file_sha256(record["predicate_path"]) != record["meta"]["predicates_sha256"]:
        raise ValueError(
            f"capture predicates changed after validation: {benchmark.benchmark_id}"
        )
    return record["predicate_path"], record["meta"], bundle


def load_candidate_meta(pred_dir: Path, benchmark: BenchmarkSpec) -> dict:
    return load_candidate_capture(pred_dir, benchmark)[1]


def attach_llm_metadata(result: dict, meta: dict) -> dict:
    result.update({
        "llm_provider": meta.get("provider", ""),
        "llm_model": meta.get("model", ""),
        "llm_total_tokens": int(meta.get("total_tokens", 0) or 0),
        "llm_call_count": len(meta.get("llm_calls", [])),
        "capture_meta_schema": meta.get("schema", ""),
    })
    return result


def uses_candidate_capture(config: str, result: dict) -> bool:
    return config.startswith("llm-") or (
        config == "portfolio" and result.get("tier") == "llm-after-baseline"
    )


def parse_verdict(output: bytes) -> str | None:
    exact = {
        line.strip().lower()
        for line in output.decode(errors="replace").splitlines()
    }
    verdicts = exact & {"unsat", "sat", "unknown"}
    return next(iter(verdicts)) if len(verdicts) == 1 else None


def verdict_matches_exit(verdict: str, returncode: int) -> bool:
    return returncode == {"sat": 0, "unsat": 1, "unknown": 255}[verdict]


def run_pono(args: list[str], timeout: float) -> dict:
    start = time.monotonic()
    try:
        result = subprocess.run(
            [PONO] + args,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - start
        partial = (exc.stdout or b"") + (exc.stderr or b"")
        return {
            "verdict": "timeout",
            "time": elapsed,
            "exit": None,
            "partial_verdict": parse_verdict(partial) or "",
            "error": "",
        }

    elapsed = time.monotonic() - start
    output = result.stdout + result.stderr
    verdict = parse_verdict(output)
    if verdict is None or not verdict_matches_exit(verdict, result.returncode):
        tail = output.decode(errors="replace").strip().splitlines()[-3:]
        return {
            "verdict": "error",
            "time": elapsed,
            "exit": result.returncode,
            "error": " | ".join(tail),
        }
    return {
        "verdict": verdict,
        "time": elapsed,
        "exit": result.returncode,
        "error": "",
    }


def run_fast_engines(path: Path, timeout: float = 10.0) -> dict:
    start = time.monotonic()
    processes = {
        engine: subprocess.Popen(
            [PONO, "-e", engine, "-k", "50", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for engine in ("ind", "interp")
    }
    results: dict[str, dict] = {}

    def collect(engine: str) -> None:
        process = processes[engine]
        stdout, stderr = process.communicate()
        elapsed = time.monotonic() - start
        verdict = parse_verdict(stdout + stderr)
        if verdict is None or not verdict_matches_exit(
            verdict, process.returncode
        ):
            tail = (stdout + stderr).decode(errors="replace").strip().splitlines()[-3:]
            results[engine] = {
                "verdict": "error",
                "time": elapsed,
                "exit": process.returncode,
                "error": " | ".join(tail),
            }
        else:
            results[engine] = {
                "verdict": verdict,
                "time": elapsed,
                "exit": process.returncode,
                "error": "",
            }

    while True:
        for engine, process in processes.items():
            if engine not in results and process.poll() is not None:
                collect(engine)

        decisive = {
            result["verdict"]
            for result in results.values()
            if result["verdict"] in {"sat", "unsat"}
        }
        if len(decisive) > 1:
            raise RuntimeError(
                f"fast engines disagree on {path}: "
                + json.dumps(results, sort_keys=True)
            )
        if decisive or len(results) == len(processes):
            break
        if time.monotonic() - start >= timeout:
            break
        time.sleep(0.01)

    elapsed = time.monotonic() - start
    for engine, process in processes.items():
        if engine in results:
            continue
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        partial = parse_verdict(stdout + stderr)
        results[engine] = {
            "verdict": "cancelled" if decisive else "timeout",
            "partial_verdict": partial or "",
            "time": elapsed,
            "exit": process.returncode,
            "error": "",
        }

    verdict = next(iter(decisive)) if decisive else "unknown"
    winners = [
        engine for engine, result in results.items() if result["verdict"] == verdict
    ]
    return {
        "verdict": verdict,
        "time": elapsed,
        "engine": "+".join(winners) if decisive else "ind+interp",
        "exit": "",
        "fast_results": results,
        "error": "",
    }


def _base_timing(result: dict) -> dict:
    model_checker = float(result.get("time", 0.0))
    result.update({
        "proof_time": model_checker,
        "certificate_time": 0.0,
        "model_checker_time": model_checker,
        "candidate_generation_sec": 0.0,
        "candidate_processing_sec": 0.0,
        "llm_generation_sec": 0.0,
        "offline_time": model_checker,
        "end_to_end_time": model_checker,
    })
    return result


def baseline(path: Path, timeout: float) -> dict:
    fast = run_fast_engines(path)
    if fast["verdict"] in {"sat", "unsat"}:
        return _base_timing(fast)
    ic3ia = run_pono(["-e", "ic3ia", str(path)], timeout)
    ic3ia["time"] += fast["time"]
    ic3ia["engine"] = "ic3ia"
    ic3ia["fast_results"] = fast["fast_results"]
    return _base_timing(ic3ia)


def cached_baseline(
    benchmark: BenchmarkSpec,
    timeout: float,
    cache: dict[str, dict] | None,
) -> dict:
    if cache is not None and benchmark.benchmark_id in cache:
        return dict(cache[benchmark.benchmark_id])
    result = baseline(benchmark.path, timeout)
    if cache is not None:
        cache[benchmark.benchmark_id] = dict(result)
    return result


def load_predicate_lines(
    path: Path, mode: str, cap: int
) -> tuple[list[str], float, list[dict], list[int]]:
    start = time.monotonic()
    if not path.exists():
        raise FileNotFoundError(path)
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    if mode not in {"full", "linear"}:
        raise ValueError(f"unknown predicate mode: {mode}")
    selected = []
    selected_indices = []
    errors = []
    for index, line in enumerate(lines):
        obj = json.loads(line)
        ast = obj.get("predicate_ast")
        error = predicate_ast_error(ast)
        if error:
            errors.append({"index": index, "error": error})
            continue
        if mode == "full" or not ast_has_var_mul(ast):
            selected.append(line)
            selected_indices.append(index)
        if len(selected) >= cap:
            break
    return selected, time.monotonic() - start, errors, selected_indices


def semantic_filter_predicate_lines(
    btor2_path: Path,
    lines: list[str],
    source_indices: list[int],
) -> tuple[list[str], list[dict]]:
    asts = [json.loads(line)["predicate_ast"] for line in lines]
    supported_indices, errors = filter_supported_asts(str(btor2_path), asts)
    supported = [lines[index] for index in supported_indices]
    remapped_errors = [{
        "index": source_indices[error["index"]],
        "error": error["error"],
    } for error in errors]
    return supported, remapped_errors


def lines_sha256(lines: list[str]) -> str:
    text = "\n".join(lines) + ("\n" if lines else "")
    return hashlib.sha256(text.encode()).hexdigest()


def run_with_predicates(
    path: Path,
    lines: list[str],
    timeout: float,
    max_refinements: int | None,
) -> dict:
    if not lines:
        return {
            "verdict": "no-candidates",
            "time": 0.0,
            "exit": None,
            "error": "",
        }
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as handle:
        handle.write("\n".join(lines) + "\n")
        predicate_file = handle.name
    try:
        args = ["-e", "ic3ia"]
        if max_refinements is not None:
            args += ["--ic3ia-max-refinements", str(max_refinements)]
        args += ["--initial-predicates", predicate_file, str(path)]
        return run_pono(args, timeout)
    finally:
        os.unlink(predicate_file)


def _finish_predicate_result(
    result: dict,
    generation: float,
    processing: float,
    llm_generation: float,
    lines: list[str],
    certificate_time: float = 0.0,
) -> dict:
    model_checker = float(result.get("time", 0.0))
    proof = certificate_time + model_checker
    result.update({
        "proof_time": proof,
        "certificate_time": certificate_time,
        "model_checker_time": model_checker,
        "candidate_generation_sec": generation,
        "candidate_processing_sec": processing,
        "llm_generation_sec": llm_generation,
        "offline_time": processing + proof,
        "end_to_end_time": generation + processing + proof,
        "candidate_count": len(lines),
        "candidate_sha256": lines_sha256(lines),
    })
    return result


def run_llm_houdini_cert(
    benchmark: BenchmarkSpec,
    pred_dir: Path,
    cap: int,
    cert_timeout_ms: int,
    capture_bundle: dict | None = None,
) -> dict:
    predicate_file, meta, _ = load_candidate_capture(
        pred_dir, benchmark, capture_bundle
    )
    generation = float(meta.get("latency_sec", 0.0) or 0.0)

    processing_start = time.monotonic()
    all_lines = [
        line for line in predicate_file.read_text().splitlines() if line.strip()
    ]
    lines = all_lines[:cap]
    entries = [json.loads(line) for line in lines]
    processing = time.monotonic() - processing_start
    if not entries:
        result = {
            "verdict": "no-candidates",
            "time": 0.0,
            "exit": None,
            "engine": "llm-houdini-certificate",
            "error": "",
        }
        result = _finish_predicate_result(
            result, generation, processing, generation, []
        )
        return attach_llm_metadata(result, meta)

    asts = [entry["predicate_ast"] for entry in entries]
    certificate_start = time.monotonic()
    report = houdini_certify(str(benchmark.path), asts, cert_timeout_ms)
    certificate_time = time.monotonic() - certificate_start
    selected_lines = [lines[index] for index in report["selected_indices"]]
    result = {
        "verdict": "unsat" if report["ok"] else "unknown",
        "time": 0.0,
        "exit": 0 if report["ok"] else None,
        "engine": "llm-houdini-certificate",
        "error": "",
    }
    result = _finish_predicate_result(
        result,
        generation,
        processing,
        generation,
        selected_lines,
        certificate_time,
    )
    result.update({
        "pool_candidate_count": len(lines),
        "selected_candidate_count": len(selected_lines),
        "unsupported_candidate_count": len(
            report.get("unsupported_candidates", [])
        ),
        "candidate_errors": json.dumps(
            report.get("unsupported_candidates", []), sort_keys=True
        ),
        "linear_candidate_count": sum(
            not ast_has_var_mul(json.loads(line)["predicate_ast"])
            for line in selected_lines
        ),
        "certificate_status": json.dumps(report["checks"], sort_keys=True),
    })
    return attach_llm_metadata(result, meta)


def run_llm_config(
    benchmark: BenchmarkSpec,
    config: str,
    pred_dir: Path,
    timeout: float,
    cap: int,
    max_refinements: int | None,
    capture_bundle: dict | None = None,
) -> dict:
    predicate_file, meta, _ = load_candidate_capture(
        pred_dir, benchmark, capture_bundle
    )
    generation = float(meta.get("latency_sec", 0.0) or 0.0)
    total_count = int(meta.get("dedup_candidate_count", 0) or 0)

    if config in {"llm-linear", "llm-full"}:
        mode = "linear" if config == "llm-linear" else "full"
        lines, processing, candidate_errors, source_indices = load_predicate_lines(
            predicate_file, mode, cap
        )
        semantic_start = time.monotonic()
        lines, semantic_errors = semantic_filter_predicate_lines(
            benchmark.path, lines, source_indices
        )
        processing += time.monotonic() - semantic_start
        candidate_errors += semantic_errors
        result = run_with_predicates(
            benchmark.path, lines, timeout, max_refinements
        )
        result = _finish_predicate_result(
            result, generation, processing, generation, lines
        )
        result["pool_candidate_count"] = total_count or len(lines)
        result["linear_candidate_count"] = sum(
            not ast_has_var_mul(json.loads(line)["predicate_ast"])
            for line in lines
        )
        result["unsupported_candidate_count"] = len(candidate_errors)
        result["candidate_errors"] = json.dumps(
            candidate_errors, sort_keys=True
        )
        return attach_llm_metadata(result, meta)

    if config != "llm-two-tier":
        raise ValueError(f"not an LLM config: {config}")
    linear, processing1, linear_errors, linear_indices = load_predicate_lines(
        predicate_file, "linear", cap
    )
    semantic_start = time.monotonic()
    linear, semantic_errors = semantic_filter_predicate_lines(
        benchmark.path, linear, linear_indices
    )
    processing1 += time.monotonic() - semantic_start
    linear_errors += semantic_errors
    first = run_with_predicates(
        benchmark.path, linear, min(20.0, timeout), max_refinements
    )
    if first["verdict"] in {"sat", "unsat"}:
        first["tier"] = 1
        first = _finish_predicate_result(
            first, generation, processing1, generation, linear
        )
        first["pool_candidate_count"] = total_count or len(linear)
        first["linear_candidate_count"] = len(linear)
        first["unsupported_candidate_count"] = len(linear_errors)
        first["candidate_errors"] = json.dumps(linear_errors, sort_keys=True)
        return attach_llm_metadata(first, meta)

    full, processing2, full_errors, full_indices = load_predicate_lines(
        predicate_file, "full", cap
    )
    semantic_start = time.monotonic()
    full, semantic_errors = semantic_filter_predicate_lines(
        benchmark.path, full, full_indices
    )
    processing2 += time.monotonic() - semantic_start
    full_errors += semantic_errors
    second = run_with_predicates(
        benchmark.path, full, timeout, max_refinements
    )
    second["time"] += first["time"]
    second["tier"] = 2
    second = _finish_predicate_result(
        second,
        generation,
        processing1 + processing2,
        generation,
        full,
    )
    second["pool_candidate_count"] = total_count or len(full)
    second["linear_candidate_count"] = len(linear)
    second["unsupported_candidate_count"] = len(full_errors)
    second["candidate_errors"] = json.dumps(full_errors, sort_keys=True)
    return attach_llm_metadata(second, meta)


def serialise_entries(entries: list[dict]) -> list[str]:
    return [json.dumps(entry) for entry in entries]


def run_static_linear(
    benchmark: BenchmarkSpec,
    timeout: float,
    cap: int,
    max_refinements: int | None,
) -> dict:
    start = time.monotonic()
    entries = generate_entries(str(benchmark.path), cap=cap)
    generation = time.monotonic() - start
    lines = serialise_entries(entries)
    result = run_with_predicates(
        benchmark.path, lines, timeout, max_refinements
    )
    result = _finish_predicate_result(result, generation, 0.0, 0.0, lines)
    result["pool_candidate_count"] = len(entries)
    result["linear_candidate_count"] = len(entries)
    return result


def run_static_ranked(
    benchmark: BenchmarkSpec,
    timeout: float,
    cap: int,
    max_refinements: int | None,
) -> dict:
    start = time.monotonic()
    entries = generate_ranked_entries(str(benchmark.path), cap=cap)
    generation = time.monotonic() - start
    lines = serialise_entries(entries)
    result = run_with_predicates(
        benchmark.path, lines, timeout, max_refinements
    )
    result = _finish_predicate_result(result, generation, 0.0, 0.0, lines)
    result["pool_candidate_count"] = len(entries)
    result["linear_candidate_count"] = len(entries)
    return result


def run_static_oracle(
    benchmark: BenchmarkSpec,
    timeout: float,
    pool_cap: int,
    inject_cap: int,
    cert_timeout_ms: int,
    max_refinements: int | None,
    quadratic_pool_cap: int = 0,
) -> dict:
    generation_start = time.monotonic()
    affine_entries = generate_entries(str(benchmark.path), cap=pool_cap)
    quadratic_entries = (
        generate_quadratic_entries(
            str(benchmark.path), cap=quadratic_pool_cap
        )
        if quadratic_pool_cap
        else []
    )
    generation = time.monotonic() - generation_start

    certificate_start = time.monotonic()
    affine_report = houdini_certify(
        str(benchmark.path),
        [entry["predicate_ast"] for entry in affine_entries],
        cert_timeout_ms,
    )
    report = affine_report
    working_entries = affine_entries
    quadratic_tested_count = 0
    quadratic_timeout_count = 0
    quadratic_winner_index: int | None = None

    affine_checks = {
        check["name"]: check["result"] for check in affine_report["checks"]
    }
    if (
        quadratic_entries
        and not affine_report["ok"]
        and affine_checks.get("C1 Init=>H") == "unsat"
        and affine_checks.get("C2 inductive") == "unsat"
    ):
        affine_selected = [
            affine_entries[index]
            for index in affine_report["selected_indices"]
        ]
        for index, quadratic_entry in enumerate(quadratic_entries):
            elapsed_ms = int(
                (time.monotonic() - certificate_start) * 1000
            )
            remaining_ms = cert_timeout_ms - elapsed_ms
            if remaining_ms <= 0:
                break
            trial_entries = affine_selected + [quadratic_entry]
            trial_report = houdini_certify(
                str(benchmark.path),
                [entry["predicate_ast"] for entry in trial_entries],
                min(remaining_ms, QUADRATIC_TEMPLATE_TIMEOUT_MS),
            )
            quadratic_tested_count += 1
            if any(
                check["result"] == "unknown"
                for check in trial_report["checks"]
            ):
                quadratic_timeout_count += 1
            if trial_report["ok"]:
                report = trial_report
                working_entries = trial_entries
                quadratic_winner_index = index
                break
    certificate_time = time.monotonic() - certificate_start

    processing_start = time.monotonic()
    houdini_selected = [
        working_entries[index] for index in report["selected_indices"]
    ]
    closure = abstraction_closure(houdini_selected)
    selected = (
        houdini_selected
        if report["ok"]
        else (houdini_selected + closure)[:inject_cap]
    )
    processing = time.monotonic() - processing_start
    lines = serialise_entries(selected)

    checks = {check["name"]: check["result"] for check in report["checks"]}
    if report["ok"]:
        result = {
            "verdict": "unsat",
            "time": 0.0,
            "exit": 0,
            "engine": "static-houdini-certificate",
            "error": "",
        }
    elif checks.get("C1 Init=>H") == "unsat" and checks.get("C2 inductive") == "unsat":
        result = run_with_predicates(
            benchmark.path, lines, timeout, max_refinements
        )
        result["engine"] = "static-houdini+ic3ia"
    else:
        result = {
            "verdict": "unknown",
            "time": 0.0,
            "exit": None,
            "engine": "static-houdini",
            "error": "",
        }
    result = _finish_predicate_result(
        result,
        generation,
        processing,
        0.0,
        lines,
        certificate_time,
    )
    result.update({
        "pool_candidate_count": len(affine_entries) + len(quadratic_entries),
        "working_candidate_count": len(working_entries),
        "affine_selected_candidate_count": len(
            affine_report["selected_indices"]
        ),
        "quadratic_tested_count": quadratic_tested_count,
        "quadratic_timeout_count": quadratic_timeout_count,
        "quadratic_winner_index": (
            quadratic_winner_index
            if quadratic_winner_index is not None
            else ""
        ),
        "linear_candidate_count": sum(
            not ast_has_var_mul(entry["predicate_ast"])
            for entry in selected
        ),
        "quadratic_candidate_count": sum(
            ast_has_var_mul(entry["predicate_ast"])
            for entry in selected
        ),
        "selected_candidate_count": len(report["selected_indices"]),
        "unsupported_candidate_count": len(
            report.get("unsupported_candidates", [])
        ),
        "candidate_errors": json.dumps(
            report.get("unsupported_candidates", []), sort_keys=True
        ),
        "closure_candidate_count": sum(
            entry.get("template_family") == "affine_projection"
            for entry in selected
        ),
        "certificate_status": json.dumps(report["checks"], sort_keys=True),
    })
    return result


def run_config(
    benchmark: BenchmarkSpec,
    config: str,
    pred_dir: Path,
    timeout: float,
    cap: int,
    max_refinements: int | None,
    baseline_cache: dict[str, dict] | None,
    static_oracle_pool_cap: int,
    static_oracle_inject_cap: int,
    cert_timeout_ms: int,
    capture_bundle: dict | None = None,
) -> dict:
    if config == "baseline":
        return cached_baseline(benchmark, timeout, baseline_cache)
    if config in {"llm-linear", "llm-full", "llm-two-tier"}:
        return run_llm_config(
            benchmark,
            config,
            pred_dir,
            timeout,
            cap,
            max_refinements,
            capture_bundle,
        )
    if config == "llm-houdini-cert":
        return run_llm_houdini_cert(
            benchmark, pred_dir, cap, cert_timeout_ms, capture_bundle
        )
    if config == "static-linear":
        return run_static_linear(
            benchmark, timeout, cap, max_refinements
        )
    if config == "static-ranked":
        return run_static_ranked(
            benchmark, timeout, cap, max_refinements
        )
    if config == "static-oracle":
        return run_static_oracle(
            benchmark,
            timeout,
            static_oracle_pool_cap,
            static_oracle_inject_cap,
            cert_timeout_ms,
            max_refinements,
        )
    if config == "static-quadratic-oracle":
        return run_static_oracle(
            benchmark,
            timeout,
            static_oracle_pool_cap,
            static_oracle_inject_cap,
            cert_timeout_ms,
            max_refinements,
            STATIC_QUADRATIC_POOL_CAP,
        )
    if config == "portfolio":
        base = cached_baseline(benchmark, timeout, baseline_cache)
        if base["verdict"] in {"unsat", "sat"}:
            base["tier"] = "baseline"
            return base
        llm = run_llm_config(
            benchmark,
            "llm-two-tier",
            pred_dir,
            timeout,
            cap,
            max_refinements,
            capture_bundle,
        )
        llm["proof_time"] += base["proof_time"]
        llm["certificate_time"] += base["certificate_time"]
        llm["model_checker_time"] += base["model_checker_time"]
        llm["offline_time"] += base["proof_time"]
        llm["end_to_end_time"] += base["proof_time"]
        llm["time"] = llm["proof_time"]
        llm["tier"] = "llm-after-baseline"
        return llm
    raise ValueError(f"unknown config: {config}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest")
    parser.add_argument("--benchmark-root", default=str(DEFAULT_BENCHMARK_ROOT))
    parser.add_argument("--pred-dir", default=".")
    parser.add_argument(
        "--configs",
        default=(
            "baseline,static-linear,static-oracle,static-quadratic-oracle,"
            "llm-linear,"
            "llm-houdini-cert,llm-two-tier,portfolio"
        ),
    )
    parser.add_argument("--timeout", type=float, default=70.0)
    parser.add_argument("--cap", type=int, default=20)
    parser.add_argument("--static-oracle-pool-cap", type=int, default=2000)
    parser.add_argument("--static-oracle-inject-cap", type=int, default=64)
    parser.add_argument("--cert-timeout-ms", type=int, default=20000)
    parser.add_argument("--ic3ia-max-refinements", type=int)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--out")
    parser.add_argument("--max-benchmarks", type=int, default=0)
    args = parser.parse_args()

    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.cap <= 0 or args.static_oracle_pool_cap <= 0:
        parser.error("candidate caps must be positive")
    if args.static_oracle_inject_cap <= 0 or args.cert_timeout_ms <= 0:
        parser.error("oracle inject cap and certificate timeout must be positive")
    if args.trials <= 0:
        parser.error("--trials must be positive")
    if args.max_benchmarks < 0:
        parser.error("--max-benchmarks must be non-negative")

    configs = [value.strip() for value in args.configs.split(",") if value.strip()]
    if len(configs) != len(set(configs)):
        parser.error("--configs must not contain duplicates")
    unknown_configs = sorted(set(configs) - VALID_CONFIGS)
    if unknown_configs:
        parser.error(f"unknown configs: {', '.join(unknown_configs)}")

    benchmark_root = Path(args.benchmark_root).expanduser().resolve()
    benchmarks = (
        load_manifest(args.manifest, benchmark_root)
        if args.manifest
        else collect_circuits(benchmark_root)
    )
    if args.max_benchmarks:
        benchmarks = benchmarks[: args.max_benchmarks]
    pred_dir = Path(args.pred_dir)
    capture_required = any(
        config.startswith("llm-") or config == "portfolio"
        for config in configs
    )
    capture_bundle = (
        validate_capture_bundle(pred_dir, benchmarks)
        if capture_required
        else None
    )
    capture_manifest_sha256 = (
        capture_bundle["manifest_sha256"] if capture_bundle else ""
    )
    capture_integrity_sha256 = (
        capture_bundle["integrity_sha256"] if capture_bundle else ""
    )
    capture_created_at = ""
    if capture_bundle:
        capture_created_at = capture_bundle["manifest"].get("created_at", "")

    benchmark_manifest_sha256 = (
        file_sha256(args.manifest) if args.manifest else ""
    )
    benchmark_hashes = {}
    for benchmark in benchmarks:
        capture_hash = (
            capture_bundle["records"][benchmark.benchmark_id]["content_sha256"]
            if capture_bundle
            else None
        )
        actual = verify_benchmark_content(benchmark, capture_hash)
        expected = benchmark.content_sha256 or capture_hash
        benchmark_hashes[benchmark.benchmark_id] = {
            "actual": actual,
            "expected": expected or "",
            "status": "verified" if expected else "recorded-only",
        }
    matrix_contract = replay_matrix_contract(
        {
            benchmark_id: record["actual"]
            for benchmark_id, record in benchmark_hashes.items()
        },
        configs,
        args.trials,
    )

    output_path = Path(args.out) if args.out else None
    partial_path = (
        output_path.with_name(output_path.name + ".partial")
        if output_path
        else None
    )
    if output_path and (output_path.exists() or partial_path.exists()):
        raise FileExistsError(f"refusing to overwrite replay matrix: {output_path}")
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output = partial_path.open("x", newline="")
    else:
        output = sys.stdout
    writer = csv.DictWriter(output, fieldnames=ROW_FIELDS, lineterminator="\n")
    writer.writeheader()
    output.flush()

    completed = False
    try:
        for trial in range(args.trials):
            baseline_cache: dict[str, dict] = {}
            for benchmark in benchmarks:
                if file_sha256(benchmark.path) != benchmark_hashes[
                    benchmark.benchmark_id
                ]["actual"]:
                    raise ValueError(
                        "benchmark changed after validation: "
                        + benchmark.benchmark_id
                    )
                for config in configs:
                    result = run_config(
                        benchmark,
                        config,
                        pred_dir,
                        args.timeout,
                        args.cap,
                        args.ic3ia_max_refinements,
                        baseline_cache,
                        args.static_oracle_pool_cap,
                        args.static_oracle_inject_cap,
                        args.cert_timeout_ms,
                        capture_bundle,
                    )
                    uses_capture = uses_candidate_capture(config, result)
                    hash_record = benchmark_hashes[benchmark.benchmark_id]
                    row = {
                    "trial": trial,
                    "benchmark_id": benchmark.benchmark_id,
                    "benchmark_expected_sha256": hash_record["expected"],
                    "benchmark_content_sha256": hash_record["actual"],
                    "benchmark_hash_status": hash_record["status"],
                    "benchmark_manifest_sha256": benchmark_manifest_sha256,
                    **matrix_contract,
                    "circuit": benchmark.path.name,
                    "config": config,
                    "candidate_capture": (
                        pred_dir.name if uses_capture else ""
                    ),
                    "capture_manifest_sha256": (
                        capture_manifest_sha256 if uses_capture else ""
                    ),
                    "capture_integrity_sha256": (
                        capture_integrity_sha256 if uses_capture else ""
                    ),
                    "capture_created_at": (
                        capture_created_at if uses_capture else ""
                    ),
                    "verdict": result.get("verdict", "error"),
                    "proof_time_sec": f"{float(result.get('proof_time', 0.0)):.6f}",
                    "certificate_time_sec": f"{float(result.get('certificate_time', 0.0)):.6f}",
                    "model_checker_time_sec": f"{float(result.get('model_checker_time', 0.0)):.6f}",
                    "candidate_generation_sec": f"{float(result.get('candidate_generation_sec', 0.0)):.6f}",
                    "candidate_processing_sec": f"{float(result.get('candidate_processing_sec', 0.0)):.6f}",
                    "llm_generation_sec": f"{float(result.get('llm_generation_sec', 0.0)):.6f}",
                    "llm_provider": result.get("llm_provider", ""),
                    "llm_model": result.get("llm_model", ""),
                    "llm_total_tokens": result.get("llm_total_tokens", ""),
                    "llm_call_count": result.get("llm_call_count", ""),
                    "capture_meta_schema": result.get("capture_meta_schema", ""),
                    "offline_time_sec": f"{float(result.get('offline_time', 0.0)):.6f}",
                    "end_to_end_sec": f"{float(result.get('end_to_end_time', 0.0)):.6f}",
                    "exit": result.get("exit", ""),
                    "engine": result.get("engine", ""),
                    "tier": result.get("tier", ""),
                    "candidate_count": result.get("candidate_count", ""),
                    "pool_candidate_count": result.get("pool_candidate_count", ""),
                    "working_candidate_count": result.get("working_candidate_count", ""),
                    "selected_candidate_count": result.get("selected_candidate_count", ""),
                    "affine_selected_candidate_count": result.get("affine_selected_candidate_count", ""),
                    "quadratic_tested_count": result.get("quadratic_tested_count", ""),
                    "quadratic_timeout_count": result.get("quadratic_timeout_count", ""),
                    "quadratic_winner_index": result.get("quadratic_winner_index", ""),
                    "unsupported_candidate_count": result.get("unsupported_candidate_count", ""),
                    "candidate_errors": result.get("candidate_errors", ""),
                    "closure_candidate_count": result.get("closure_candidate_count", ""),
                    "linear_candidate_count": result.get("linear_candidate_count", ""),
                    "quadratic_candidate_count": result.get("quadratic_candidate_count", ""),
                    "candidate_sha256": result.get("candidate_sha256", ""),
                    "certificate_status": result.get("certificate_status", ""),
                    "error": result.get("error", ""),
                    "fast_results": json.dumps(
                        result.get("fast_results", {}), sort_keys=True
                    ),
                    }
                    writer.writerow(row)
                    output.flush()
                    print(
                        json.dumps(row, sort_keys=True),
                        file=sys.stderr,
                        flush=True,
                    )
        completed = True
    finally:
        if output_path:
            output.close()
    if completed and output_path:
        partial_path.replace(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
