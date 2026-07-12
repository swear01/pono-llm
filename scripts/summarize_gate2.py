#!/usr/bin/env python3
"""Build the canonical Gate 2 machine-readable research summary."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import statistics
from collections import Counter
from pathlib import Path

from experiment_manifest import (
    file_sha256,
    validate_capture_archive,
    validate_replay_matrix,
)
from select_gate2_llm_targets import PRIOR_CONFIGS


SOURCE_FILES = (
    "gate2_features.csv",
    "gate2_features.summary.json",
    "gate2_manifest.json",
    "gate2_baseline_screen_10s.csv",
    "gate2_baseline_screen_survivors_le10k.json",
    "gate2_static_quadratic_le10k_70s.csv",
    "gate2_llm_targets.json",
    "gate2_llm_capture_v3/manifest.json",
    "gate2_llm_capture_v3/integrity.json",
    "gate2_llm_houdini_70s.csv",
    "gate2_llm_linear_refine_70s.csv",
    "gate2_static_linear_cap200_refine_70s.csv",
    "gate2_static_ranked_cap20_refine_70s.csv",
    "gate2_up_manifest.json",
    "gate2_up_matched_matrix.csv",
    "gate2_up_llm_vs_ranked_5trials.csv",
    "gate2_up_static_ranked_cap15.csv",
    "gate2_up_static_ranked_cap16.csv",
    "gate2_up_static_linear_cap192_v2.csv",
    "gate2_up_cert_check.txt",
    "gate2_up_static_cap200_cert_check.txt",
    "gate2_up_static_ranked_cap16.jsonl",
    "gate2_up_static_ranked_cap16_cert_check.txt",
    "phase1_2_corrected_full21_matrix_final.csv",
    "phase1_2_frozen_v2/manifest.json",
    "phase1_2_frozen_v2/integrity.json",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def verdict_summary(rows: list[dict]) -> dict:
    return {
        "verdict_counts": dict(sorted(Counter(row["verdict"] for row in rows).items())),
        "sat_benchmark_ids": sorted(
            row["benchmark_id"] for row in rows if row["verdict"] == "sat"
        ),
        "unsat_benchmark_ids": sorted(
            row["benchmark_id"] for row in rows if row["verdict"] == "unsat"
        ),
        "total_proof_sec": sum(float(row["proof_time_sec"]) for row in rows),
        "total_generation_sec": sum(
            float(row["candidate_generation_sec"]) for row in rows
        ),
        "total_end_to_end_sec": sum(float(row["end_to_end_sec"]) for row in rows),
    }


def assert_unique(rows: list[dict], expected_count: int) -> set[str]:
    identities = {(row["benchmark_id"], row["config"], row["trial"]) for row in rows}
    if len(identities) != len(rows):
        raise ValueError("matrix contains duplicate replay identities")
    benchmark_ids = {row["benchmark_id"] for row in rows}
    if len(benchmark_ids) != expected_count:
        raise ValueError(
            f"expected {expected_count} benchmark IDs, got {len(benchmark_ids)}"
        )
    return benchmark_ids


def benchmark_hashes(rows: list[dict]) -> dict[str, str]:
    hashes: dict[str, set[str]] = {}
    for row in rows:
        digest = row.get("benchmark_content_sha256", "")
        if not _SHA256.fullmatch(digest):
            raise ValueError(
                f"missing/invalid benchmark hash for {row.get('benchmark_id', '?')}"
            )
        hashes.setdefault(row["benchmark_id"], set()).add(digest)
    if any(len(values) != 1 for values in hashes.values()):
        raise ValueError("matrix rows disagree on benchmark content hashes")
    return {benchmark_id: next(iter(values)) for benchmark_id, values in hashes.items()}


def validate_capture_lineage(rows: list[dict], capture: dict) -> None:
    for row in rows:
        if row.get("candidate_capture", "") != capture["manifest_path"].parent.name:
            raise ValueError(
                f"capture directory mismatch for {row.get('benchmark_id', '?')}"
            )
        if row.get("capture_manifest_sha256", "") != capture["manifest_sha256"]:
            raise ValueError(
                f"capture manifest hash mismatch for {row.get('benchmark_id', '?')}"
            )
        if row.get("capture_integrity_sha256", "") != capture["integrity_sha256"]:
            raise ValueError(
                f"capture integrity hash mismatch for {row.get('benchmark_id', '?')}"
            )


def certificate_pass(path: Path) -> bool:
    text = path.read_text()
    return all(
        re.search(rf"^\s*{label}\b.*✓\s+UNSAT", text, re.MULTILINE)
        for label in ("C1", "C2", "C3")
    ) and "SOUND PROOF" in text


def build_summary(artifact_dir: Path) -> dict:
    feature_run = json.loads(
        (artifact_dir / "gate2_features.summary.json").read_text()
    )
    corpus = json.loads((artifact_dir / "gate2_manifest.json").read_text())
    baseline = read_csv(artifact_dir / "gate2_baseline_screen_10s.csv")
    small_survivors = json.loads(
        (artifact_dir / "gate2_baseline_screen_survivors_le10k.json").read_text()
    )
    deterministic_cert = read_csv(
        artifact_dir / "gate2_static_quadratic_le10k_70s.csv"
    )
    targets = json.loads((artifact_dir / "gate2_llm_targets.json").read_text())
    llm_houdini = read_csv(artifact_dir / "gate2_llm_houdini_70s.csv")
    llm_seed = read_csv(artifact_dir / "gate2_llm_linear_refine_70s.csv")
    static_seed = read_csv(
        artifact_dir / "gate2_static_linear_cap200_refine_70s.csv"
    )
    ranked_seed = read_csv(
        artifact_dir / "gate2_static_ranked_cap20_refine_70s.csv"
    )
    up_matrix = read_csv(artifact_dir / "gate2_up_matched_matrix.csv")
    up_trials = read_csv(
        artifact_dir / "gate2_up_llm_vs_ranked_5trials.csv"
    )
    ranked_cap15 = read_csv(
        artifact_dir / "gate2_up_static_ranked_cap15.csv"
    )
    ranked_cap16 = read_csv(
        artifact_dir / "gate2_up_static_ranked_cap16.csv"
    )
    static_cap192 = read_csv(
        artifact_dir / "gate2_up_static_linear_cap192_v2.csv"
    )
    up_manifest_path = artifact_dir / "gate2_up_manifest.json"
    up_manifest = json.loads(up_manifest_path.read_text())
    prior_matrix_path = (
        artifact_dir / "phase1_2_corrected_full21_matrix_final.csv"
    )
    prior_matrix = read_csv(prior_matrix_path)
    prior_capture = validate_capture_archive(
        artifact_dir / "phase1_2_frozen_v2"
    )

    corpus_hashes = {
        row["benchmark_id"]: row["content_sha256"]
        for row in corpus["benchmarks"]
    }
    corpus_manifest_sha256 = file_sha256(
        artifact_dir / "gate2_manifest.json"
    )
    baseline_contract = validate_replay_matrix(
        baseline,
        corpus_hashes,
        ["baseline"],
        1,
        benchmark_manifest_sha256=corpus_manifest_sha256,
    )
    survivor_hashes = {
        row["benchmark_id"]: row["content_sha256"]
        for row in small_survivors["benchmarks"]
    }
    survivor_manifest_sha256 = file_sha256(
        artifact_dir / "gate2_baseline_screen_survivors_le10k.json"
    )
    deterministic_contract = validate_replay_matrix(
        deterministic_cert,
        survivor_hashes,
        ["static-quadratic-oracle"],
        1,
        benchmark_manifest_sha256=survivor_manifest_sha256,
    )
    if small_survivors.get("source_matrix_sha256") != file_sha256(
        artifact_dir / "gate2_baseline_screen_10s.csv"
    ):
        raise ValueError("survivor manifest references a different baseline matrix")
    if small_survivors.get("source_matrix_contract_sha256") != baseline_contract[
        "matrix_contract_sha256"
    ]:
        raise ValueError("survivor manifest baseline contract differs")
    if small_survivors.get("benchmark_manifest_sha256") != corpus_manifest_sha256:
        raise ValueError("survivor manifest references a different corpus manifest")
    target_hashes = {
        row["benchmark_id"]: row["content_sha256"]
        for row in targets["benchmarks"]
    }
    target_manifest_sha256 = file_sha256(
        artifact_dir / "gate2_llm_targets.json"
    )
    for rows, configs in (
        (llm_houdini, ["llm-houdini-cert"]),
        (llm_seed, ["llm-linear"]),
        (static_seed, ["static-linear"]),
        (ranked_seed, ["static-ranked"]),
    ):
        validate_replay_matrix(
            rows,
            target_hashes,
            configs,
            1,
            benchmark_manifest_sha256=target_manifest_sha256,
        )

    prior_hashes = {
        benchmark_id: record["content_sha256"]
        for benchmark_id, record in prior_capture["records"].items()
    }
    validate_replay_matrix(
        prior_matrix,
        prior_hashes,
        PRIOR_CONFIGS,
        1,
        benchmark_manifest_sha256=prior_capture["manifest_sha256"],
    )
    if targets.get("source_survivors_sha256") != survivor_manifest_sha256:
        raise ValueError("target manifest references different survivors")
    if targets.get("prior_matrix_sha256") != file_sha256(prior_matrix_path):
        raise ValueError("target manifest references a different prior matrix")
    if targets.get("prior_capture_manifest_sha256") != prior_capture[
        "manifest_sha256"
    ]:
        raise ValueError("target manifest references a different prior capture")
    if targets.get("prior_capture_integrity_sha256") != prior_capture[
        "integrity_sha256"
    ]:
        raise ValueError("target manifest references different prior integrity")
    if targets.get("deterministic_matrix_sha256") != file_sha256(
        artifact_dir / "gate2_static_quadratic_le10k_70s.csv"
    ):
        raise ValueError("target manifest references a different deterministic matrix")
    if targets.get("deterministic_matrix_contract_sha256") != deterministic_contract[
        "matrix_contract_sha256"
    ]:
        raise ValueError("target manifest deterministic contract differs")

    up_hashes = {
        row["benchmark_id"]: row["content_sha256"]
        for row in up_manifest["benchmarks"]
    }
    up_manifest_sha256 = file_sha256(up_manifest_path)
    for rows, configs, trials in (
        (
            up_matrix,
            [
                "baseline",
                "llm-linear",
                "portfolio",
                "static-linear",
                "static-oracle",
                "static-quadratic-oracle",
            ],
            1,
        ),
        (up_trials, ["llm-linear", "static-ranked"], 5),
        (ranked_cap15, ["static-ranked"], 1),
        (ranked_cap16, ["static-ranked"], 1),
        (static_cap192, ["static-linear"], 1),
    ):
        validate_replay_matrix(
            rows,
            up_hashes,
            configs,
            trials,
            benchmark_manifest_sha256=up_manifest_sha256,
        )

    capture_dir = artifact_dir / "gate2_llm_capture_v3"
    capture = validate_capture_archive(capture_dir)
    capture_meta = [
        record["meta"] for record in capture["records"].values()
    ]
    if len(capture_meta) != targets["selected_count"]:
        raise ValueError("capture metadata count does not match target count")
    if any(meta["status"] != "completed" for meta in capture_meta):
        raise ValueError("Gate 2 capture contains an incomplete benchmark")
    capture_hashes = {
        benchmark_id: record["content_sha256"]
        for benchmark_id, record in capture["records"].items()
    }
    if target_hashes != capture_hashes:
        raise ValueError("Gate 2 target/capture benchmark hashes differ")
    validate_capture_lineage(llm_houdini, capture)
    validate_capture_lineage(llm_seed, capture)
    validate_capture_lineage(
        [row for row in up_matrix if row["config"] in {"llm-linear", "portfolio"}],
        capture,
    )
    validate_capture_lineage(
        [row for row in up_trials if row["config"] == "llm-linear"],
        capture,
    )

    llm_summary = verdict_summary(llm_seed)
    static_summary = verdict_summary(static_seed)
    ranked_summary = verdict_summary(ranked_seed)
    llm_unsat = set(llm_summary["unsat_benchmark_ids"])
    static_unsat = set(static_summary["unsat_benchmark_ids"])
    ranked_unsat = set(ranked_summary["unsat_benchmark_ids"])
    if not (llm_unsat == static_unsat == ranked_unsat):
        raise ValueError("corrected LLM/static solved sets do not match")

    up_rows = {row["config"]: row for row in up_matrix}
    llm_trial_rows = [row for row in up_trials if row["config"] == "llm-linear"]
    ranked_trial_rows = [
        row for row in up_trials if row["config"] == "static-ranked"
    ]
    if len(llm_trial_rows) != 5 or len(ranked_trial_rows) != 5:
        raise ValueError("expected five up.btor2 trials per ranked comparison")
    if any(row["verdict"] != "unsat" for row in up_trials):
        raise ValueError("up.btor2 reliability replay contains a failed trial")
    if (
        ranked_cap15[0]["verdict"] != "unknown"
        or int(ranked_cap15[0]["candidate_count"]) != 15
    ):
        raise ValueError("ranked cap-15 boundary result changed")
    if (
        ranked_cap16[0]["verdict"] != "unsat"
        or int(ranked_cap16[0]["candidate_count"]) != 16
    ):
        raise ValueError("ranked cap-16 boundary result changed")
    if (
        static_cap192[0]["verdict"] != "timeout"
        or int(static_cap192[0]["candidate_count"]) != 192
    ):
        raise ValueError("static cap-192 boundary result changed")
    ranked_cap16_candidate_path = (
        artifact_dir / "gate2_up_static_ranked_cap16.jsonl"
    )
    ranked_cap16_candidate_sha256 = hashlib.sha256(
        ranked_cap16_candidate_path.read_bytes()
    ).hexdigest()
    if ranked_cap16_candidate_sha256 != ranked_cap16[0]["candidate_sha256"]:
        raise ValueError("ranked cap-16 replay/file candidate hashes differ")
    llm_trial_hashes = {row["candidate_sha256"] for row in llm_trial_rows}
    ranked_trial_hashes = {
        row["candidate_sha256"] for row in ranked_trial_rows
    }
    if len(llm_trial_hashes) != 1 or len(ranked_trial_hashes) != 1:
        raise ValueError("candidate hashes changed across up.btor2 trials")
    up_id = next(iter(llm_unsat), "")
    if not up_id.endswith("/loop-invgen/up.btor2"):
        raise ValueError(f"unexpected Gate 2 solved set: {sorted(llm_unsat)}")
    up_hash = {up_id: target_hashes[up_id]}
    for name, rows in (
        ("matched up matrix", up_matrix),
        ("up trials", up_trials),
        ("ranked cap 15", ranked_cap15),
        ("ranked cap 16", ranked_cap16),
        ("static cap 192", static_cap192),
    ):
        if benchmark_hashes(rows) != up_hash:
            raise ValueError(f"{name}/target benchmark hashes differ")

    source_hashes = {}
    for relative in SOURCE_FILES:
        path = artifact_dir / relative
        source_hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()

    return {
        "schema": "pono-llm-gate2-summary-v1",
        "date": "2026-07-12",
        "claim_boundary": (
            "Gate 2 adds zero LLM-specific coverage. A post-hoc fixed "
            "low-complexity relational ranking baseline also removes the apparent "
            "predicate-compactness advantage on loop-invgen/up.btor2."
        ),
        "feature_census": {
            "all_files": feature_run["files"],
            "parsed_ok": feature_run["counts"]["ok"],
            "software_origin": feature_run["counts"]["software_origin"],
            "software_nonarray": feature_run["counts"]["software_nonarray"],
            "elapsed_sec": feature_run["elapsed_sec"],
            "unique_eligible": corpus["unique_eligible"],
            "duplicates_removed": corpus["duplicate_instances_removed"],
        },
        "baseline_screen": verdict_summary(baseline),
        "small_survivor_count": small_survivors["selected_count"],
        "oversized_excluded_count": small_survivors["excluded_by_size_count"],
        "deterministic_certificate_screen": verdict_summary(deterministic_cert),
        "new_llm_target_count": targets["selected_count"],
        "llm_capture": {
            "benchmark_count": len(capture_meta),
            "call_count": sum(len(meta["llm_calls"]) for meta in capture_meta),
            "total_tokens": sum(meta["total_tokens"] for meta in capture_meta),
            "total_generation_sec": sum(meta["latency_sec"] for meta in capture_meta),
            "median_benchmark_generation_sec": statistics.median(
                meta["latency_sec"] for meta in capture_meta
            ),
            "invalid_candidate_count": sum(
                meta["invalid_candidate_count"] for meta in capture_meta
            ),
        },
        "llm_houdini": verdict_summary(llm_houdini),
        "llm_raw_predicate_seed": llm_summary,
        "static_raw_predicate_seed_cap200": static_summary,
        "static_ranked_predicate_seed_cap20": ranked_summary,
        "llm_specific_unsat_benchmark_ids": sorted(
            llm_unsat - static_unsat - ranked_unsat
        ),
        "matched_unsat_set_equal": llm_unsat == static_unsat == ranked_unsat,
        "up_case": {
            "benchmark_id": up_id,
            "llm_candidate_count": int(up_rows["llm-linear"]["candidate_count"]),
            "llm_candidate_sha256": next(iter(llm_trial_hashes)),
            "llm_proof_sec": float(up_rows["llm-linear"]["proof_time_sec"]),
            "llm_end_to_end_sec": float(up_rows["llm-linear"]["end_to_end_sec"]),
            "static_cap200_proof_sec": float(
                next(
                    row["proof_time_sec"]
                    for row in static_seed
                    if row["benchmark_id"] == up_id
                )
            ),
            "static_cap200_end_to_end_sec": float(
                next(
                    row["end_to_end_sec"]
                    for row in static_seed
                    if row["benchmark_id"] == up_id
                )
            ),
            "ranked_cap20_candidate_count": int(
                ranked_trial_rows[0]["candidate_count"]
            ),
            "ranked_cap20_candidate_sha256": next(
                iter(ranked_trial_hashes)
            ),
            "ranked_cap20_median_proof_sec": statistics.median(
                float(row["proof_time_sec"]) for row in ranked_trial_rows
            ),
            "ranked_cap20_median_end_to_end_sec": statistics.median(
                float(row["end_to_end_sec"]) for row in ranked_trial_rows
            ),
            "llm_median_proof_sec": statistics.median(
                float(row["proof_time_sec"]) for row in llm_trial_rows
            ),
            "llm_median_end_to_end_sec": statistics.median(
                float(row["end_to_end_sec"]) for row in llm_trial_rows
            ),
            "llm_trial_unsat_count": len(llm_trial_rows),
            "ranked_trial_unsat_count": len(ranked_trial_rows),
            "baseline_verdict": up_rows["baseline"]["verdict"],
            "llm_certificate_pass": certificate_pass(
                artifact_dir / "gate2_up_cert_check.txt"
            ),
            "static_certificate_pass": certificate_pass(
                artifact_dir / "gate2_up_static_cap200_cert_check.txt"
            ),
            "ranked_certificate_pass": certificate_pass(
                artifact_dir / "gate2_up_static_ranked_cap16_cert_check.txt"
            ),
            "largest_recorded_failing_static_prefix": int(
                static_cap192[0]["candidate_count"]
            ),
            "smallest_recorded_successful_static_prefix": int(
                next(
                    row["candidate_count"]
                    for row in static_seed
                    if row["benchmark_id"] == up_id
                )
            ),
            "largest_recorded_failing_ranked_prefix": int(
                ranked_cap15[0]["candidate_count"]
            ),
            "smallest_recorded_successful_ranked_prefix": int(
                ranked_cap16[0]["candidate_count"]
            ),
            "ranked_cap16_candidate_sha256": ranked_cap16_candidate_sha256,
        },
        "source_sha256": source_hashes,
    }


def main() -> int:
    print(json.dumps(build_summary(Path("artifacts")), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
