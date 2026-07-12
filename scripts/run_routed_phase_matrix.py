#!/usr/bin/env python3
"""Replay LLM, structural, and random routes with all-phase certificates."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import build_paired_corpus  # noqa: E402
import capture_grammar_routes  # noqa: E402
from experiment_manifest import file_sha256, stable_slug  # noqa: E402
import grammar_routes  # noqa: E402
import representation_views  # noqa: E402
import run_phase_grammar  # noqa: E402


MATRIX_SCHEMA = "pono-llm-routed-phase-matrix-v1"
RANDOM_SEED = "pono-llm-budget-matched-random-route-v1"
FIELDS = (
    "schema",
    "pilot_sha256",
    "benchmark_id",
    "content_sha256",
    "source_family_id",
    "selection_role",
    "expected_verdict",
    "config",
    "router",
    "arm",
    "route_valid",
    "route_error",
    "verdict",
    "engine",
    "route_count",
    "pool_candidate_count",
    "selected_candidate_count",
    "phase_count",
    "candidate_sha256",
    "route_sha256",
    "certificate_time_sec",
    "model_checker_time_sec",
    "offline_time_sec",
    "generation_time_sec",
    "end_to_end_sec",
    "certificate_ok",
    "certificate_checks_json",
    "report_path",
    "report_sha256",
)


def verify_capture(directory: Path, view_bundle_sha256: str, pilot_sha256: str) -> dict:
    manifest_path = directory / "manifest.json"
    integrity_path = directory / "integrity.json"
    manifest = json.loads(manifest_path.read_text())
    integrity = json.loads(integrity_path.read_text())
    if manifest.get("schema") != capture_grammar_routes.CAPTURE_SCHEMA:
        raise ValueError("grammar-route capture has the wrong schema")
    if integrity.get("schema") != capture_grammar_routes.INTEGRITY_SCHEMA:
        raise ValueError("grammar-route capture integrity has the wrong schema")
    if integrity.get("status") != "completed":
        raise ValueError("grammar-route capture is incomplete")
    if manifest.get("view_bundle_sha256") != view_bundle_sha256:
        raise ValueError("capture references another representation bundle")
    if manifest.get("pilot_sha256") != pilot_sha256:
        raise ValueError("capture references another paired pilot")
    if integrity.get("manifest_sha256") != file_sha256(manifest_path):
        raise ValueError("capture manifest hash mismatch")
    declared_integrity = integrity.get("integrity_sha256")
    computed_integrity = build_paired_corpus.canonical_sha256({
        key: value for key, value in integrity.items() if key != "integrity_sha256"
    })
    if declared_integrity != computed_integrity:
        raise ValueError("capture integrity self-hash mismatch")
    indexed_files = {}
    for record in integrity.get("files", []):
        relative = record.get("path")
        if relative in indexed_files:
            raise ValueError(f"duplicate capture integrity path: {relative}")
        path = directory / relative
        if not path.is_file() or file_sha256(path) != record.get("sha256"):
            raise ValueError(f"capture file hash mismatch: {relative}")
        indexed_files[relative] = record["sha256"]
    for required in ("manifest.json", "provenance.json", "system_prompt.txt"):
        if required not in indexed_files:
            raise ValueError(f"capture integrity omits {required}")
    return manifest


def random_budget_route_document(
    btor2: Path,
    variables: list[dict],
    benchmark_id: str,
    arm: str,
    target_candidates: int,
) -> tuple[dict, dict]:
    if target_candidates <= 0:
        raise ValueError("random route target must be positive")
    exhaustive = grammar_routes.bounded_exhaustive_route_document(variables)
    compiled = grammar_routes.compile_route_document(str(btor2), exhaustive)
    candidates = []
    for route in compiled:
        payload = {"schema": grammar_routes.ROUTE_SCHEMA, "routes": [route.semantic_payload()]}
        count = len(grammar_routes.expand_routes(
            str(btor2), [route], cap=capture_grammar_routes.FORMAL_CANDIDATE_CAP + 1
        ))
        rank = hashlib.sha256(
            f"{RANDOM_SEED}:{benchmark_id}:{arm}:{route.route_id}".encode()
        ).hexdigest()
        candidates.append((rank, route, count, payload))
    candidates.sort(key=lambda row: (row[0], row[1].route_id))
    selected = []
    count = 0
    for _, route, route_count, _ in candidates:
        if count + route_count <= target_candidates:
            selected.append(route)
            count += route_count
    if not selected:
        _, route, count, _ = min(
            candidates, key=lambda row: (row[2], row[0], row[1].route_id)
        )
        selected = [route]
    document = {
        "schema": grammar_routes.ROUTE_SCHEMA,
        "routes": [route.semantic_payload() for route in selected],
    }
    return document, {
        "seed": RANDOM_SEED,
        "target_candidates": target_candidates,
        "selected_global_candidates": count,
        "selected_route_ids": [route.route_id for route in selected],
    }


def _worker(spec: dict) -> dict:
    report = run_phase_grammar.run_gate(
        spec["btor2"],
        spec["route_payload"],
        phase_mode=spec["phase_mode"],
        cap=capture_grammar_routes.FORMAL_CANDIDATE_CAP,
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
        "router": spec["router"],
        "arm": spec["arm"],
        "route_valid": True,
        "route_error": "",
        "route_diagnostics": spec["route_diagnostics"],
        "generation_time_sec": spec["generation_time_sec"],
    })
    report["end_to_end_with_generation_sec"] = (
        report["offline_time_sec"] + spec["generation_time_sec"]
    )
    return report


def invalid_report(spec: dict) -> dict:
    return {
        "matrix_schema": MATRIX_SCHEMA,
        "pilot_sha256": spec["pilot_sha256"],
        "benchmark_id": spec["benchmark_id"],
        "benchmark_sha256": spec["content_sha256"],
        "source_family_id": spec["source_family_id"],
        "selection_role": spec["selection_role"],
        "expected_verdict": spec["expected_verdict"],
        "config": spec["config"],
        "router": spec["router"],
        "arm": spec["arm"],
        "route_valid": False,
        "route_error": spec["route_error"],
        "verdict": "invalid-route",
        "engine": "",
        "route_count": 0,
        "pool_candidate_count": 0,
        "selected_candidate_count": 0,
        "phase_count": spec["phase_count"],
        "candidate_sha256": "",
        "route_sha256": "",
        "certificate_time_sec": 0.0,
        "model_checker_time_sec": 0.0,
        "offline_time_sec": 0.0,
        "generation_time_sec": spec["generation_time_sec"],
        "end_to_end_with_generation_sec": spec["generation_time_sec"],
        "certificate": {"ok": False, "checks": []},
        "error": "",
    }


def row_for(report: dict, relative: str, digest: str) -> dict:
    return {
        "schema": MATRIX_SCHEMA,
        "pilot_sha256": report["pilot_sha256"],
        "benchmark_id": report["benchmark_id"],
        "content_sha256": report["benchmark_sha256"],
        "source_family_id": report["source_family_id"],
        "selection_role": report["selection_role"],
        "expected_verdict": report["expected_verdict"],
        "config": report["config"],
        "router": report["router"],
        "arm": report["arm"],
        "route_valid": str(report["route_valid"]).lower(),
        "route_error": report["route_error"],
        "verdict": report["verdict"],
        "engine": report["engine"],
        "route_count": report["route_count"],
        "pool_candidate_count": report["pool_candidate_count"],
        "selected_candidate_count": report["selected_candidate_count"],
        "phase_count": report["phase_count"],
        "candidate_sha256": report["candidate_sha256"],
        "route_sha256": report["route_sha256"],
        "certificate_time_sec": f"{report['certificate_time_sec']:.6f}",
        "model_checker_time_sec": f"{report['model_checker_time_sec']:.6f}",
        "offline_time_sec": f"{report['offline_time_sec']:.6f}",
        "generation_time_sec": f"{report['generation_time_sec']:.6f}",
        "end_to_end_sec": f"{report['end_to_end_with_generation_sec']:.6f}",
        "certificate_ok": str(bool(report["certificate"].get("ok"))).lower(),
        "certificate_checks_json": json.dumps(
            report["certificate"].get("checks", []), sort_keys=True
        ),
        "report_path": relative,
        "report_sha256": digest,
    }


def decision(rows: list[dict], exhaustive_rows: list[dict]) -> dict:
    hard = {
        row["benchmark_id"]
        for row in rows
        if row["selection_role"] == "safe-baseline-hard"
    }
    solved = {}
    for config in sorted({row["config"] for row in rows}):
        solved[config] = sorted({
            row["benchmark_id"] for row in rows
            if row["config"] == config
            and row["benchmark_id"] in hard
            and row["verdict"] == "unsat"
        })
    source_set = set(solved.get("llm-source", []))
    other_repr = set(solved.get("llm-lifted", [])) | set(solved.get("llm-raw", []))
    source_unique = sorted(source_set - other_repr)

    exhaustive_by_id = {
        row["benchmark_id"]: row for row in exhaustive_rows
        if row["config"] == "all-phase-exhaustive"
    }
    exhaustive_set = {
        benchmark_id for benchmark_id, row in exhaustive_by_id.items()
        if row["selection_role"] == "safe-baseline-hard" and row["verdict"] == "unsat"
    }
    structural_set = set(solved.get("structural-all", []))
    structural_global_set = set(solved.get("structural-global", []))
    structural_phase_additions = sorted(structural_set - structural_global_set)
    structural_reference_rows = {
        row["benchmark_id"]: row for row in rows
        if row["config"] == "structural-all"
        and row["benchmark_id"] in structural_set
    }
    structural_reference_time = sum(
        float(row["end_to_end_sec"])
        for row in structural_reference_rows.values()
    )
    arm_decisions = {}
    for arm in representation_views.ARMS:
        config = f"llm-{arm}"
        arm_rows = [
            row for row in rows
            if row["config"] == config
            and row["route_valid"] == "true"
            and row["selection_role"] == "safe-baseline-hard"
        ]
        arm_set = set(solved.get(config, []))
        exhaustive_preservation = (
            len(arm_set & exhaustive_set) / len(exhaustive_set)
            if exhaustive_set else None
        )
        deterministic_preservation = (
            len(arm_set & structural_set) / len(structural_set)
            if structural_set else None
        )
        reductions = []
        for row in arm_rows:
            exhaustive = exhaustive_by_id.get(row["benchmark_id"])
            routed_count = int(row["pool_candidate_count"] or 0)
            if exhaustive and routed_count:
                reductions.append(int(exhaustive["pool_candidate_count"]) / routed_count)
        median_reduction = statistics.median(reductions) if reductions else 0.0
        arm_reference_rows = {
            row["benchmark_id"]: row for row in rows
            if row["config"] == config
            and row["benchmark_id"] in structural_set
        }
        arm_reference_time = sum(
            float(row["end_to_end_sec"])
            for row in arm_reference_rows.values()
        )
        end_to_end_beats_structural = bool(structural_set) and (
            arm_reference_time < structural_reference_time
        )
        arm_decisions[arm] = {
            "solved": sorted(arm_set),
            "exhaustive_preservation": exhaustive_preservation,
            "deterministic_reference_preservation": deterministic_preservation,
            "median_candidate_reduction": median_reduction,
            "unique_over_structural": sorted(arm_set - structural_set),
            "beats_structural_solve_count": len(arm_set) > len(structural_set),
            "end_to_end_on_structural_reference_sec": arm_reference_time,
            "structural_reference_end_to_end_sec": structural_reference_time,
            "end_to_end_beats_structural": end_to_end_beats_structural,
            "h3_pass": (
                exhaustive_preservation is not None
                and exhaustive_preservation >= 0.9
                and deterministic_preservation is not None
                and deterministic_preservation >= 0.9
                and median_reduction >= 10.0
                and len(arm_set) > len(structural_set)
                and end_to_end_beats_structural
            ),
        }
    unsafe = [
        {
            "benchmark_id": row["benchmark_id"],
            "config": row["config"],
            "verdict": row["verdict"],
        }
        for row in rows if row["expected_verdict"] == "unsafe"
    ]
    return {
        "solved_sets": solved,
        "h2_source_unique_count": len(source_unique),
        "h2_source_unique": source_unique,
        "h2_pass": len(source_unique) >= 3,
        "exhaustive_all_phase_baseline_hard_set": sorted(exhaustive_set),
        "structural_baseline_hard_set": sorted(structural_set),
        "structural_global_baseline_hard_set": sorted(structural_global_set),
        "h1_structural_phase_only_addition_count": len(structural_phase_additions),
        "h1_structural_phase_only_additions": structural_phase_additions,
        "h1_pass": len(structural_phase_additions) >= 3,
        "h3_by_arm": arm_decisions,
        "h3_pass": any(value["h3_pass"] for value in arm_decisions.values()),
        "h4_false_safe_count": sum(row["verdict"] == "unsat" for row in rows if row["expected_verdict"] == "unsafe"),
        "h4_pass": not any(row["verdict"] == "unsat" for row in rows if row["expected_verdict"] == "unsafe"),
        "unsafe_results": unsafe,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pilot")
    parser.add_argument("view_bundle")
    parser.add_argument("route_capture")
    parser.add_argument("exhaustive_matrix")
    parser.add_argument("translation_repo")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--cert-timeout-ms", type=int, default=20000)
    parser.add_argument("--pono-timeout", type=float, default=10.0)
    parser.add_argument("--ic3ia-max-refinements", type=int, default=2)
    args = parser.parse_args()
    if args.workers <= 0 or args.cert_timeout_ms <= 0 or args.pono_timeout <= 0:
        parser.error("workers and timeouts must be positive")
    if args.ic3ia_max_refinements < 0:
        parser.error("refinement cap must be non-negative")

    pilot = representation_views.verify_pilot(Path(args.pilot))
    view_dir = Path(args.view_bundle)
    view_manifest = capture_grammar_routes.verify_view_bundle(view_dir)
    capture_dir = Path(args.route_capture)
    capture = verify_capture(
        capture_dir, view_manifest["bundle_sha256"], pilot["pilot_sha256"]
    )
    translation_repo = Path(args.translation_repo).expanduser().resolve()
    build_paired_corpus.verify_repository(
        translation_repo, build_paired_corpus.TRANSLATION_REVISION, "translation"
    )
    output = Path(args.out_dir)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite routed matrix: {output}")
    reports_dir = output / "reports"
    reports_dir.mkdir(parents=True)

    tasks = {
        task["benchmark_id"]: task for task in pilot["benchmarks"]
        if task["selection_role"] != "safe-baseline-control"
    }
    capture_records = {
        (record["benchmark_id"], record["arm"]): record
        for record in capture["records"]
    }
    specs = []
    for benchmark_id, task in sorted(tasks.items()):
        btor2 = translation_repo / task["path"]
        if file_sha256(btor2) != task["content_sha256"]:
            raise ValueError(f"frozen BTOR2 hash mismatch: {benchmark_id}")
        structural, diagnostics = grammar_routes.structural_route_document(
            str(btor2), task["source_state_mapping"]
        )
        common = {
            "pilot_sha256": pilot["pilot_sha256"],
            "benchmark_id": benchmark_id,
            "content_sha256": task["content_sha256"],
            "btor2": str(btor2),
            "source_family_id": task["source_family_id"],
            "selection_role": task["selection_role"],
            "expected_verdict": task["expected_verdict"],
            "cert_timeout_ms": args.cert_timeout_ms,
            "pono_timeout": args.pono_timeout,
            "max_refinements": args.ic3ia_max_refinements,
            "phase_count": len(task["phases"]),
        }
        for config, phase_mode in (
            ("structural-global", "global"),
            ("structural-all", "all"),
        ):
            specs.append({
                **common,
                "config": config,
                "router": "structural",
                "arm": "target",
                "phase_mode": phase_mode,
                "route_payload": structural,
                "route_diagnostics": diagnostics,
                "route_valid": True,
                "route_error": "",
                "generation_time_sec": 0.0,
            })
        for arm in representation_views.ARMS:
            capture_record = capture_records[(benchmark_id, arm)]
            metadata = json.loads(
                (capture_dir / capture_record["metadata_path"]).read_text()
            )
            response = (capture_dir / capture_record["response_path"]).read_text()
            config = f"llm-{arm}"
            if metadata["route_valid"]:
                route_payload = json.loads(response)
                specs.append({
                    **common,
                    "config": config,
                    "router": "llm",
                    "arm": arm,
                    "phase_mode": "all",
                    "route_payload": route_payload,
                    "route_diagnostics": {"capture_metadata": capture_record["metadata_path"]},
                    "route_valid": True,
                    "route_error": "",
                    "generation_time_sec": float(metadata["wall_latency_sec"]),
                })
                random_payload, random_diagnostics = random_budget_route_document(
                    btor2,
                    task["source_state_mapping"],
                    benchmark_id,
                    arm,
                    int(metadata["global_candidate_count"]),
                )
                specs.append({
                    **common,
                    "config": f"random-{arm}",
                    "router": "random",
                    "arm": arm,
                    "phase_mode": "all",
                    "route_payload": random_payload,
                    "route_diagnostics": random_diagnostics,
                    "route_valid": True,
                    "route_error": "",
                    "generation_time_sec": 0.0,
                })
            else:
                specs.append({
                    **common,
                    "config": config,
                    "router": "llm",
                    "arm": arm,
                    "phase_mode": "all",
                    "route_valid": False,
                    "route_error": metadata["route_error"],
                    "generation_time_sec": float(metadata["wall_latency_sec"]),
                })

    reports = []
    valid_specs = [spec for spec in specs if spec["route_valid"]]
    invalid_specs = [spec for spec in specs if not spec["route_valid"]]
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(_worker, spec): spec for spec in valid_specs}
        for completed, future in enumerate(as_completed(futures), start=1):
            report = future.result()
            expected_formal = "unsat" if report["expected_verdict"] == "safe" else "sat"
            if report["verdict"] in {"sat", "unsat"} and report["verdict"] != expected_formal:
                raise RuntimeError(
                    f"routed proof contradicts expected verdict for "
                    f"{report['benchmark_id']} ({report['config']})"
                )
            reports.append(report)
            print(json.dumps({
                "completed": completed,
                "total": len(valid_specs),
                "benchmark_id": report["benchmark_id"],
                "config": report["config"],
                "verdict": report["verdict"],
            }), file=sys.stderr, flush=True)
    reports.extend(invalid_report(spec) for spec in invalid_specs)
    reports.sort(key=lambda report: (report["benchmark_id"], report["config"]))

    rows = []
    for report in reports:
        slug = stable_slug(report["benchmark_id"])
        relative = Path("reports") / f"{slug}.{report['config']}.json"
        path = output / relative
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        rows.append(row_for(report, relative.as_posix(), file_sha256(path)))
    matrix_path = output / "matrix.csv"
    with matrix_path.open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with Path(args.exhaustive_matrix).open(newline="") as handle:
        exhaustive_rows = list(csv.DictReader(handle))
    result_decision = decision(rows, exhaustive_rows)
    manifest = {
        "schema": MATRIX_SCHEMA,
        "pilot_sha256": pilot["pilot_sha256"],
        "view_bundle_sha256": view_manifest["bundle_sha256"],
        "route_capture_manifest_sha256": file_sha256(capture_dir / "manifest.json"),
        "translation_revision": build_paired_corpus.TRANSLATION_REVISION,
        "excluded_selection_roles": ["safe-baseline-control"],
        "row_count": len(rows),
        "valid_run_count": len(valid_specs),
        "invalid_route_count": len(invalid_specs),
        "matrix_sha256": file_sha256(matrix_path),
        "verdict_counts": dict(sorted(Counter(
            f"{row['config']}:{row['verdict']}" for row in rows
        ).items())),
        "decision": result_decision,
        "reports": {row["report_path"]: row["report_sha256"] for row in rows},
    }
    manifest["manifest_sha256"] = build_paired_corpus.canonical_sha256({
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    })
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({
        "row_count": manifest["row_count"],
        "valid_run_count": manifest["valid_run_count"],
        "invalid_route_count": manifest["invalid_route_count"],
        "decision": result_decision,
        "manifest_sha256": manifest["manifest_sha256"],
        "output": output.as_posix(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
