#!/usr/bin/env python3
"""Validate, summarize, and hash the canonical Gate 4B0 artifact bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Sequence


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_schema(path: Path, schema: str) -> dict:
    value = json.loads(path.read_text())
    if value.get("schema") != schema:
        raise ValueError(f"unexpected schema in {path}: {value.get('schema')}")
    return value


def verify_self_hash(value: dict, field: str, location: str) -> None:
    declared = value.get(field)
    payload = dict(value)
    payload.pop(field, None)
    actual = canonical_sha256(payload)
    if declared != actual:
        raise ValueError(f"self-hash mismatch in {location}: {declared} != {actual}")


def _solver_medians(matrix: dict) -> dict[str, dict[str, dict]]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in matrix["rows"]:
        grouped[(row["benchmark_id"], row["arm"])].append(row)
    result: dict[str, dict[str, dict]] = defaultdict(dict)
    for (benchmark_id, arm), rows in sorted(grouped.items()):
        counts = Counter(row["result"] for row in rows)
        solved_times = [
            row["wall_time_sec"] for row in rows if row["result"] == "unsat"
        ]
        result[benchmark_id][arm] = {
            "result_counts": dict(sorted(counts.items())),
            "median_unsat_wall_time_sec": (
                statistics.median(solved_times) if solved_times else None
            ),
            "all_trials_unsat": len(solved_times) == len(rows),
        }
    return dict(result)


def _kernel_medians(matrix: dict) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in matrix["rows"]:
        grouped[row["benchmark_id"]].append(row)
    result = {}
    for benchmark_id, rows in sorted(grouped.items()):
        result[benchmark_id] = {
            "all_kernel_c2_accepted": all(
                row["kernel_c2_result"] == "accepted" for row in rows
            ),
            "all_full_certificates_accepted": all(
                row["full_certificate_ok"] for row in rows
            ),
            "median_kernel_c2_wall_time_sec": statistics.median(
                row["kernel_c2_wall_time_sec"] for row in rows
            ),
            "median_full_certificate_wall_time_sec": statistics.median(
                row["full_certificate_wall_time_sec"] for row in rows
            ),
        }
    return result


def _pono_medians(matrix: dict) -> dict[str, dict[str, dict]]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in matrix["rows"]:
        grouped[(row["benchmark_id"], row["arm"])].append(row)
    result: dict[str, dict[str, dict]] = defaultdict(dict)
    for (benchmark_id, arm), rows in sorted(grouped.items()):
        counts = Counter(row["result"] for row in rows)
        unsat_times = [
            row["wall_time_sec"] for row in rows if row["result"] == "unsat"
        ]
        result[benchmark_id][arm] = {
            "result_counts": dict(sorted(counts.items())),
            "median_unsat_wall_time_sec": (
                statistics.median(unsat_times) if unsat_times else None
            ),
            "all_trials_unsat": len(unsat_times) == len(rows),
        }
    return dict(result)


def summarize(artifact_directory: Path) -> dict:
    controls_path = artifact_directory / "development_controls" / "manifest.json"
    queries_path = artifact_directory / "c2_queries" / "manifest.json"
    population_path = artifact_directory / "population.json"
    solver_path = artifact_directory / "solver_matrix.json"
    kernel_path = artifact_directory / "kernel_matrix.json"
    pono_path = artifact_directory / "pono_matrix" / "matrix.json"
    negative_path = artifact_directory / "negative_suite" / "report.json"
    controls = load_schema(
        controls_path, "pono-modular-algebraic-development-controls-v1"
    )
    queries = load_schema(queries_path, "pono-modular-algebraic-c2-corpus-v1")
    population = load_schema(
        population_path, "pono-modular-algebraic-population-v1"
    )
    solver = load_schema(
        solver_path, "pono-modular-algebraic-solver-matrix-v1"
    )
    kernel = load_schema(
        kernel_path, "pono-modular-algebraic-kernel-matrix-v1"
    )
    pono = load_schema(
        pono_path, "pono-modular-algebraic-pono-matrix-v1"
    )
    negative = load_schema(
        negative_path, "pono-modular-algebraic-negative-suite-v1"
    )
    for value, field, location in (
        (controls, "manifest_sha256", "development controls"),
        (queries, "manifest_sha256", "C2 query corpus"),
        (population, "population_sha256", "population"),
        (solver, "report_sha256", "solver matrix"),
        (kernel, "report_sha256", "kernel matrix"),
        (pono, "report_sha256", "Pono matrix"),
        (negative, "report_sha256", "negative suite"),
    ):
        verify_self_hash(value, field, location)
    if queries["source_manifest_sha256"] != file_sha256(controls_path):
        raise ValueError("query corpus does not bind the development-control manifest")
    if solver["corpus_manifest_sha256"] != file_sha256(queries_path):
        raise ValueError("solver matrix does not bind the C2 query manifest")
    if kernel["certificate_manifest_sha256"] != file_sha256(controls_path):
        raise ValueError("kernel matrix does not bind the certificate manifest")
    if pono["certificate_manifest_sha256"] != file_sha256(controls_path):
        raise ValueError("Pono matrix does not bind the certificate manifest")
    if not solver["polysat_activation_probe"]["polysat_statistics_present"]:
        raise ValueError("solver matrix does not evidence pinned PolySAT activation")
    if solver["polysat_source"]["source_commit"] != (
        "16fb86b636047fd79ad5827f768b6f26d8812948"
    ):
        raise ValueError("solver matrix does not bind the pinned PolySAT commit")

    controls_by_id = {row["benchmark_id"]: row for row in controls["controls"]}
    if len(controls_by_id) != len(controls["controls"]):
        raise ValueError("duplicate development-control benchmark id")
    for row in controls["controls"]:
        certificate_path = controls_path.parent / row["certificate"]
        report_path = controls_path.parent / row["report"]
        if file_sha256(certificate_path) != row["certificate_file_sha256"]:
            raise ValueError(f"certificate file hash mismatch: {row['benchmark_id']}")
        certificate = json.loads(certificate_path.read_text())
        if canonical_sha256(certificate) != row["certificate_sha256"]:
            raise ValueError(f"certificate canonical hash mismatch: {row['benchmark_id']}")
        if file_sha256(report_path) != row["report_file_sha256"]:
            raise ValueError(f"certificate report hash mismatch: {row['benchmark_id']}")
        certificate_report = load_schema(
            report_path, "pono-modular-algebraic-certificate-report-v1"
        )
        if not certificate_report["ok"] or certificate_report[
            "certificate_sha256"
        ] != row["certificate_sha256"]:
            raise ValueError(f"development certificate is not accepted: {row['benchmark_id']}")

    query_ids = set()
    for row in queries["queries"]:
        if row["benchmark_id"] in query_ids:
            raise ValueError("duplicate C2 query benchmark id")
        query_ids.add(row["benchmark_id"])
        query_path = queries_path.parent / row["query"]
        if file_sha256(query_path) != row["query_sha256"]:
            raise ValueError(f"C2 query hash mismatch: {row['benchmark_id']}")
        control = controls_by_id.get(row["benchmark_id"])
        if control is None or row["certificate_sha256"] != control[
            "certificate_sha256"
        ]:
            raise ValueError(f"C2 query certificate binding mismatch: {row['benchmark_id']}")
    if query_ids != set(controls_by_id):
        raise ValueError("C2 query corpus and development controls differ")

    required_solver_arms = {
        "python-z3-default",
        "local-z3-cli-default",
        "local-z3-intblast",
        "pinned-z3-default",
        "pinned-z3-polysat",
        "pinned-z3-intblast",
    }
    solver_arms = {arm["id"] for arm in solver["arms"]}
    if solver_arms != required_solver_arms:
        raise ValueError(f"solver arm set mismatch: {sorted(solver_arms)}")
    expected_solver_keys = {
        (benchmark_id, arm, trial)
        for benchmark_id in query_ids
        for arm in solver_arms
        for trial in range(solver["trials"])
    }
    solver_keys = {
        (row["benchmark_id"], row["arm"], row["trial"])
        for row in solver["rows"]
    }
    if len(solver["rows"]) != len(expected_solver_keys) or solver_keys != expected_solver_keys:
        raise ValueError("solver matrix row/trial contract mismatch")
    if any(
        row["result"] in {"error", "configuration-unverified"}
        for row in solver["rows"]
    ):
        raise ValueError("solver matrix contains infrastructure/configuration errors")

    expected_kernel_keys = {
        (benchmark_id, trial)
        for benchmark_id in controls_by_id
        for trial in range(kernel["trials"])
    }
    kernel_keys = {
        (row["benchmark_id"], row["trial"])
        for row in kernel["rows"]
    }
    if len(kernel["rows"]) != len(expected_kernel_keys) or kernel_keys != expected_kernel_keys:
        raise ValueError("kernel matrix row/trial contract mismatch")

    pono_keys = {
        (row["benchmark_id"], row["arm"], row["property_index"], row["trial"])
        for row in pono["rows"]
    }
    if len(pono_keys) != len(pono["rows"]):
        raise ValueError("duplicate Pono matrix row")
    if {row["arm"] for row in pono["rows"]} != {
        "pono-ic3ia-plain",
        "pono-ic3ia-certified-basis",
    }:
        raise ValueError("Pono arm set mismatch")
    if any(row["result"] == "error" for row in pono["rows"]):
        raise ValueError("Pono matrix contains infrastructure errors")
    for benchmark_id in controls_by_id:
        selected = [
            row for row in pono["rows"] if row["benchmark_id"] == benchmark_id
        ]
        properties_by_arm = {
            arm: {row["property_index"] for row in selected if row["arm"] == arm}
            for arm in ("pono-ic3ia-plain", "pono-ic3ia-certified-basis")
        }
        if (
            not properties_by_arm["pono-ic3ia-plain"]
            or properties_by_arm["pono-ic3ia-plain"]
            != properties_by_arm["pono-ic3ia-certified-basis"]
        ):
            raise ValueError(f"Pono property set mismatch: {benchmark_id}")
        property_indices = properties_by_arm["pono-ic3ia-plain"]
        if property_indices != set(range(max(property_indices) + 1)):
            raise ValueError(f"Pono property indices are not contiguous: {benchmark_id}")
        expected_count = 2 * len(property_indices) * pono["trials"]
        if len(selected) != expected_count:
            raise ValueError(f"Pono row/trial contract mismatch: {benchmark_id}")
    for row in pono["rows"]:
        predicate_path = pono_path.parent / row["predicate_file"]
        if file_sha256(predicate_path) != row["predicate_sha256"]:
            raise ValueError(f"Pono predicate hash mismatch: {row['benchmark_id']}")

    solver_medians = _solver_medians(solver)
    kernel_medians = _kernel_medians(kernel)
    pono_medians = _pono_medians(pono)
    speedups = {}
    for benchmark_id in sorted(kernel_medians):
        exact = [
            (arm, data["median_unsat_wall_time_sec"])
            for arm, data in solver_medians[benchmark_id].items()
            if data["all_trials_unsat"]
            and data["median_unsat_wall_time_sec"] is not None
        ]
        if not exact:
            speedups[benchmark_id] = {
                "best_exact_arm": None,
                "best_exact_median_sec": None,
                "kernel_median_sec": kernel_medians[benchmark_id][
                    "median_kernel_c2_wall_time_sec"
                ],
                "speedup": None,
            }
            continue
        best_arm, best_time = min(exact, key=lambda item: item[1])
        kernel_time = kernel_medians[benchmark_id]["median_kernel_c2_wall_time_sec"]
        speedup = best_time / kernel_time
        speedups[benchmark_id] = {
            "best_exact_arm": best_arm,
            "best_exact_median_sec": best_time,
            "kernel_median_sec": kernel_time,
            "speedup": speedup,
            "comparison_scope": (
                "exploratory process-wall versus in-process kernel core; "
                "development controls only"
            ),
        }

    population_sufficient = population["population_sufficient"]
    h5a_status = "not-run"
    h5a_reason = (
        "not run: preregistered official corpus contains no v1-eligible task"
        if not population_sufficient
        else "not run: primary certificate synthesis/results are absent"
    )
    h5c_development = (
        negative["all_rejected"]
        and negative["all_expectations_met"]
        and all(item["accepted"] for item in controls["controls"])
    )
    summary = {
        "schema": "pono-modular-algebraic-gate-summary-v1",
        "source_file_sha256": {
            "development_controls/manifest.json": file_sha256(controls_path),
            "c2_queries/manifest.json": file_sha256(queries_path),
            "population.json": file_sha256(population_path),
            "solver_matrix.json": file_sha256(solver_path),
            "kernel_matrix.json": file_sha256(kernel_path),
            "pono_matrix/matrix.json": file_sha256(pono_path),
            "negative_suite/report.json": file_sha256(negative_path),
        },
        "development_controls": {
            "count": len(controls["controls"]),
            "counts_toward_h5a": 0,
            "solver_medians": solver_medians,
            "kernel_medians": kernel_medians,
            "kernel_speedup_over_best_exact": speedups,
            "pono_original_model_medians": pono_medians,
            "development_controls_only": True,
            "b0_gate_decision_from_controls": "not-permitted",
        },
        "population": {
            "selection_status": population["selection_status"],
            "population_sufficient": population_sufficient,
            "eligible_after_dedup_count": population[
                "eligible_after_dedup_count"
            ],
            "safe_baseline_hard_available_count": population[
                "safe_baseline_hard_available_count"
            ],
            "unsafe_available_count": population["unsafe_available_count"],
            "exclusion_counts": population["exclusion_counts"],
            "structural_diagnostics": population["structural_diagnostics"],
        },
        "decisions": {
            "H5a_kernel_value": h5a_status,
            "H5a_reason": h5a_reason,
            "H5b_llm_value": "not-authorized",
            "H5c_development_soundness": h5c_development,
            "H5c_primary_soundness": "not-run-no-primary-population",
            "paid_llm_capture_performed": False,
            "gate_4b0": "stop",
            "next_gate": "known-map-certified-transport-oracle",
        },
        "negative_suite": {
            "case_count": negative["case_count"],
            "rejected_count": negative["rejected_count"],
            "accepted_count": negative["accepted_count"],
            "all_expectations_met": negative["all_expectations_met"],
        },
    }
    summary["summary_sha256"] = canonical_sha256(summary)
    return summary


def write_integrity(artifact_directory: Path) -> dict:
    files = {}
    for path in sorted(artifact_directory.rglob("*")):
        if not path.is_file() or path.name == "integrity.json":
            continue
        relative = path.relative_to(artifact_directory).as_posix()
        files[relative] = file_sha256(path)
    integrity = {
        "schema": "pono-modular-algebraic-integrity-v1",
        "files": files,
    }
    integrity["integrity_sha256"] = canonical_sha256(integrity)
    (artifact_directory / "integrity.json").write_text(
        json.dumps(integrity, indent=2, sort_keys=True) + "\n"
    )
    return integrity


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_directory", type=Path)
    args = parser.parse_args(argv)
    try:
        summary_path = args.artifact_directory / "summary.json"
        integrity_path = args.artifact_directory / "integrity.json"
        if summary_path.exists() or integrity_path.exists():
            raise FileExistsError(
                "refusing to overwrite existing summary/integrity artifact"
            )
        summary = summarize(args.artifact_directory)
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n"
        )
        integrity = write_integrity(args.artifact_directory)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(str(error))
        return 1
    print(
        json.dumps(
            {
                "decisions": summary["decisions"],
                "population": summary["population"],
                "summary_sha256": summary["summary_sha256"],
                "integrity_sha256": integrity["integrity_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
