#!/usr/bin/env python3
"""Run matched global/all-phase bounded grammars on the frozen paired pilot."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import build_paired_corpus  # noqa: E402
from experiment_manifest import file_sha256, stable_slug  # noqa: E402
import grammar_routes  # noqa: E402
import representation_views  # noqa: E402
import run_phase_grammar  # noqa: E402


MATRIX_SCHEMA = "pono-llm-paired-phase-matrix-v1"
CONFIGS = {
    "global-exhaustive": "global",
    "all-phase-exhaustive": "all",
}
SUMMARY_FIELDS = (
    "schema",
    "pilot_sha256",
    "benchmark_id",
    "content_sha256",
    "source_family_id",
    "selection_role",
    "expected_verdict",
    "config",
    "phase_mode",
    "verdict",
    "engine",
    "pool_candidate_count",
    "selected_candidate_count",
    "route_count",
    "phase_count",
    "candidate_sha256",
    "route_sha256",
    "certificate_time_sec",
    "model_checker_time_sec",
    "offline_time_sec",
    "certificate_ok",
    "certificate_checks_json",
    "error",
    "report_path",
    "report_sha256",
)


def _worker(spec: dict) -> dict:
    route_payload = grammar_routes.bounded_exhaustive_route_document(
        spec["source_state_mapping"]
    )
    report = run_phase_grammar.run_gate(
        spec["btor2"],
        route_payload,
        phase_mode=spec["phase_mode"],
        cap=spec["candidate_cap"],
        cert_timeout_ms=spec["cert_timeout_ms"],
        pono_timeout=spec["pono_timeout"],
        max_refinements=spec["max_refinements"],
    )
    report.update({
        "matrix_schema": MATRIX_SCHEMA,
        "pilot_sha256": spec["pilot_sha256"],
        "benchmark_id": spec["benchmark_id"],
        "source_family_id": spec["source_family_id"],
        "selection_role": spec["selection_role"],
        "expected_verdict": spec["expected_verdict"],
        "config": spec["config"],
        "bounded_grammar_max_variables": grammar_routes.BOUNDED_GRAMMAR_MAX_VARIABLES,
    })
    return report


def summary_row(report: dict, report_path: str, report_sha256: str) -> dict:
    certificate = report["certificate"]
    return {
        "schema": MATRIX_SCHEMA,
        "pilot_sha256": report["pilot_sha256"],
        "benchmark_id": report["benchmark_id"],
        "content_sha256": report["benchmark_sha256"],
        "source_family_id": report["source_family_id"],
        "selection_role": report["selection_role"],
        "expected_verdict": report["expected_verdict"],
        "config": report["config"],
        "phase_mode": report["phase_mode"],
        "verdict": report["verdict"],
        "engine": report["engine"],
        "pool_candidate_count": report["pool_candidate_count"],
        "selected_candidate_count": report["selected_candidate_count"],
        "route_count": report["route_count"],
        "phase_count": report["phase_count"],
        "candidate_sha256": report["candidate_sha256"],
        "route_sha256": report["route_sha256"],
        "certificate_time_sec": f"{report['certificate_time_sec']:.6f}",
        "model_checker_time_sec": f"{report['model_checker_time_sec']:.6f}",
        "offline_time_sec": f"{report['offline_time_sec']:.6f}",
        "certificate_ok": str(bool(certificate.get("ok"))).lower(),
        "certificate_checks_json": json.dumps(
            certificate.get("checks", []), sort_keys=True
        ),
        "error": report.get("error", ""),
        "report_path": report_path,
        "report_sha256": report_sha256,
    }


def gate_decision(rows: list[dict]) -> dict:
    by_benchmark = {}
    for row in rows:
        by_benchmark.setdefault(row["benchmark_id"], {})[row["config"]] = row
    additions = []
    hard_additions = []
    global_solves = []
    phase_solves = []
    unsafe_results = []
    for benchmark_id, configs in sorted(by_benchmark.items()):
        if set(configs) != set(CONFIGS):
            raise ValueError(f"incomplete phase matrix for {benchmark_id}")
        global_row = configs["global-exhaustive"]
        phase_row = configs["all-phase-exhaustive"]
        if global_row["expected_verdict"] == "unsafe":
            unsafe_results.append({
                "benchmark_id": benchmark_id,
                "global": global_row["verdict"],
                "all_phase": phase_row["verdict"],
            })
            continue
        if global_row["verdict"] == "unsat":
            global_solves.append(benchmark_id)
        if phase_row["verdict"] == "unsat":
            phase_solves.append(benchmark_id)
            if global_row["verdict"] != "unsat":
                additions.append(benchmark_id)
                if global_row["selection_role"] == "safe-baseline-hard":
                    hard_additions.append(benchmark_id)
    return {
        "h1_pass_threshold": 3,
        "h1_phase_only_addition_count": len(additions),
        "h1_phase_only_additions": additions,
        "h1_baseline_hard_addition_count": len(hard_additions),
        "h1_baseline_hard_additions": hard_additions,
        "h1_pass": len(hard_additions) >= 3,
        "global_safe_solve_count": len(global_solves),
        "all_phase_safe_solve_count": len(phase_solves),
        "global_safe_solves": global_solves,
        "all_phase_safe_solves": phase_solves,
        "unsafe_results": unsafe_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pilot")
    parser.add_argument("translation_repo")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--candidate-cap", type=int, default=50000)
    parser.add_argument("--cert-timeout-ms", type=int, default=20000)
    parser.add_argument("--pono-timeout", type=float, default=10.0)
    parser.add_argument("--ic3ia-max-refinements", type=int, default=2)
    args = parser.parse_args()
    if args.workers <= 0 or args.candidate_cap <= 0:
        parser.error("worker and candidate caps must be positive")
    if args.cert_timeout_ms <= 0 or args.pono_timeout <= 0:
        parser.error("timeouts must be positive")
    if args.ic3ia_max_refinements < 0:
        parser.error("--ic3ia-max-refinements must be non-negative")

    pilot_path = Path(args.pilot)
    pilot = representation_views.verify_pilot(pilot_path)
    translation_repo = Path(args.translation_repo).expanduser().resolve()
    build_paired_corpus.verify_repository(
        translation_repo,
        build_paired_corpus.TRANSLATION_REVISION,
        "translation",
    )
    output = Path(args.out_dir)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite paired phase matrix: {output}")
    reports_dir = output / "reports"
    reports_dir.mkdir(parents=True)

    specs = []
    for task in pilot["benchmarks"]:
        btor2 = translation_repo / task["path"]
        if file_sha256(btor2) != task["content_sha256"]:
            raise ValueError(f"frozen BTOR2 hash mismatch: {task['benchmark_id']}")
        for config, phase_mode in CONFIGS.items():
            specs.append({
                "pilot_sha256": pilot["pilot_sha256"],
                "benchmark_id": task["benchmark_id"],
                "btor2": str(btor2),
                "source_family_id": task["source_family_id"],
                "selection_role": task["selection_role"],
                "expected_verdict": task["expected_verdict"],
                "source_state_mapping": task["source_state_mapping"],
                "config": config,
                "phase_mode": phase_mode,
                "candidate_cap": args.candidate_cap,
                "cert_timeout_ms": args.cert_timeout_ms,
                "pono_timeout": args.pono_timeout,
                "max_refinements": args.ic3ia_max_refinements,
            })

    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(_worker, spec): spec for spec in specs}
        for completed, future in enumerate(as_completed(futures), start=1):
            spec = futures[future]
            report = future.result()
            expected_formal = (
                "unsat" if report["expected_verdict"] == "safe" else "sat"
            )
            if report["verdict"] in {"sat", "unsat"} and report["verdict"] != expected_formal:
                raise RuntimeError(
                    f"phase grammar contradicts expected verdict for "
                    f"{report['benchmark_id']} ({report['config']}): "
                    f"expected {expected_formal}, got {report['verdict']}"
                )
            slug = stable_slug(report["benchmark_id"])
            relative = Path("reports") / f"{slug}.{report['config']}.json"
            path = output / relative
            path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            rows.append(summary_row(report, relative.as_posix(), file_sha256(path)))
            print(
                json.dumps({
                    "completed": completed,
                    "total": len(specs),
                    "benchmark_id": spec["benchmark_id"],
                    "config": spec["config"],
                    "verdict": report["verdict"],
                }),
                file=sys.stderr,
                flush=True,
            )

    rows.sort(key=lambda row: (row["benchmark_id"], row["config"]))
    summary_path = output / "matrix.csv"
    with summary_path.open("x", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=SUMMARY_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    verdict_counts = Counter(
        f"{row['config']}:{row['verdict']}" for row in rows
    )
    decision = gate_decision(rows)
    manifest = {
        "schema": MATRIX_SCHEMA,
        "pilot_sha256": pilot["pilot_sha256"],
        "translation_revision": build_paired_corpus.TRANSLATION_REVISION,
        "configs": list(CONFIGS),
        "bounded_grammar_max_variables": grammar_routes.BOUNDED_GRAMMAR_MAX_VARIABLES,
        "candidate_cap": args.candidate_cap,
        "certificate_timeout_ms": args.cert_timeout_ms,
        "pono_timeout_sec": args.pono_timeout,
        "ic3ia_max_refinements": args.ic3ia_max_refinements,
        "asan_options": os.environ.get("ASAN_OPTIONS", ""),
        "row_count": len(rows),
        "matrix_sha256": file_sha256(summary_path),
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "decision": decision,
        "reports": {
            row["report_path"]: row["report_sha256"] for row in rows
        },
    }
    manifest["manifest_sha256"] = build_paired_corpus.canonical_sha256({
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    })
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({
        "row_count": manifest["row_count"],
        "verdict_counts": manifest["verdict_counts"],
        "decision": decision,
        "manifest_sha256": manifest["manifest_sha256"],
        "output": output.as_posix(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
