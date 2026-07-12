#!/usr/bin/env python3
"""Validate and summarize the canonical representation/phase gate artifact."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import build_paired_corpus  # noqa: E402
import capture_grammar_routes  # noqa: E402
from experiment_manifest import file_sha256  # noqa: E402
import representation_views  # noqa: E402
import run_paired_phase_matrix  # noqa: E402
import run_routed_phase_matrix  # noqa: E402
import screen_paired_baseline  # noqa: E402
import select_paired_pilot  # noqa: E402


SUMMARY_SCHEMA = "pono-llm-representation-phase-summary-v1"
ARTIFACT_INTEGRITY_SCHEMA = "pono-llm-representation-phase-artifact-integrity-v1"


def verify_self_hash(payload: dict, field: str, label: str) -> None:
    declared = payload.get(field)
    computed = build_paired_corpus.canonical_sha256({
        key: value for key, value in payload.items() if key != field
    })
    if declared != computed:
        raise ValueError(f"{label} self-hash mismatch: {declared} != {computed}")


def verify_report_manifest(directory: Path, schema: str) -> dict:
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != schema:
        raise ValueError(f"wrong schema in {manifest_path}")
    verify_self_hash(manifest, "manifest_sha256", manifest_path.as_posix())
    matrix_path = directory / "matrix.csv"
    if file_sha256(matrix_path) != manifest["matrix_sha256"]:
        raise ValueError(f"matrix hash mismatch in {directory}")
    for relative, digest in manifest["reports"].items():
        if file_sha256(directory / relative) != digest:
            raise ValueError(f"report hash mismatch: {directory / relative}")
    with matrix_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != manifest["row_count"]:
        raise ValueError(f"matrix row count mismatch in {directory}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir")
    args = parser.parse_args()
    root = Path(args.artifact_dir)
    summary_path = root / "summary.json"
    integrity_path = root / "integrity.json"
    if summary_path.exists() or integrity_path.exists():
        raise FileExistsError("refusing to overwrite representation gate summary/integrity")

    population = screen_paired_baseline.load_population(root / "population.json")
    baseline_path = root / "baseline_screen.csv"
    baseline = select_paired_pilot.load_screen(baseline_path, population)
    pilot = representation_views.verify_pilot(root / "pilot.json")
    if pilot["population_sha256"] != population["population_sha256"]:
        raise ValueError("pilot/population hash mismatch")
    if pilot["baseline_screen_sha256"] != file_sha256(baseline_path):
        raise ValueError("pilot/baseline hash mismatch")

    view_manifest = capture_grammar_routes.verify_view_bundle(root / "views")
    if view_manifest["pilot_sha256"] != pilot["pilot_sha256"]:
        raise ValueError("view/pilot hash mismatch")
    frozen_audit = json.loads((root / "frozen_route_audit.json").read_text())
    if frozen_audit.get("schema") != "pono-llm-frozen-route-audit-v1":
        raise ValueError("frozen route audit has the wrong schema")
    verify_self_hash(frozen_audit, "report_sha256", "frozen route audit")

    exhaustive = verify_report_manifest(
        root / "exhaustive_phase_matrix",
        run_paired_phase_matrix.MATRIX_SCHEMA,
    )
    capture = run_routed_phase_matrix.verify_capture(
        root / "route_capture",
        view_manifest["bundle_sha256"],
        pilot["pilot_sha256"],
    )
    routed = verify_report_manifest(
        root / "routed_phase_matrix",
        run_routed_phase_matrix.MATRIX_SCHEMA,
    )
    if routed["route_capture_manifest_sha256"] != file_sha256(
        root / "route_capture" / "manifest.json"
    ):
        raise ValueError("routed matrix/capture hash mismatch")
    unsat_audit_dir = root / "routed_unsat_audit"
    unsat_audit = json.loads((unsat_audit_dir / "manifest.json").read_text())
    if unsat_audit.get("schema") != "pono-llm-routed-unsat-audit-v1":
        raise ValueError("routed UNSAT audit has the wrong schema")
    verify_self_hash(unsat_audit, "audit_sha256", "routed UNSAT audit")
    if unsat_audit["routed_matrix_manifest_sha256"] != file_sha256(
        root / "routed_phase_matrix" / "manifest.json"
    ):
        raise ValueError("routed UNSAT audit/matrix hash mismatch")
    with (root / "routed_phase_matrix" / "matrix.csv").open(newline="") as handle:
        routed_rows = list(csv.DictReader(handle))
    routed_unsat_count = sum(row["verdict"] == "unsat" for row in routed_rows)
    if unsat_audit["audited_unsat_count"] != routed_unsat_count:
        raise ValueError("routed UNSAT audit does not cover every UNSAT row")

    baseline_counts = Counter(
        (task["expected_verdict"], baseline[task["benchmark_id"]]["baseline_verdict"])
        for task in population["tasks"] if task["eligible"]
    )
    view_counts = Counter(
        (record["arm"], record["representation_truncated"])
        for record in view_manifest["records"]
    )
    summary = {
        "schema": SUMMARY_SCHEMA,
        "population": {
            "population_sha256": population["population_sha256"],
            "task_count": population["task_count"],
            "eligible_count": population["eligible_count"],
            "eligible_verdict_counts": population["eligible_verdict_counts"],
            "source_family_count": population["source_family_count"],
            "baseline_counts": {
                f"{expected}:{verdict}": count
                for (expected, verdict), count in sorted(baseline_counts.items())
            },
        },
        "pilot": {
            "pilot_sha256": pilot["pilot_sha256"],
            "selected_count": pilot["selected_count"],
            "actual_counts": pilot["actual_counts"],
            "selected_family_count": pilot["selected_family_count"],
            "selected_content_count": pilot["selected_content_count"],
        },
        "views": {
            "bundle_sha256": view_manifest["bundle_sha256"],
            "record_count": view_manifest["record_count"],
            "lexical_token_budget": view_manifest["lexical_token_budget"],
            "truncation_counts": {
                f"{arm}:{str(truncated).lower()}": count
                for (arm, truncated), count in sorted(view_counts.items())
            },
        },
        "frozen_route_audit": {
            "report_sha256": frozen_audit["report_sha256"],
            "benchmark_count": frozen_audit["benchmark_count"],
            "candidate_count": frozen_audit["candidate_count"],
            "matched_candidate_count": frozen_audit["matched_candidate_count"],
            "matched_candidate_ratio": frozen_audit["matched_candidate_ratio"],
            "family_counts": frozen_audit["family_counts"],
        },
        "deterministic_phase_gate": {
            "manifest_sha256": exhaustive["manifest_sha256"],
            "verdict_counts": exhaustive["verdict_counts"],
            "decision": exhaustive["decision"],
        },
        "route_capture": {
            "manifest_sha256": file_sha256(root / "route_capture" / "manifest.json"),
            "integrity_sha256": json.loads(
                (root / "route_capture" / "integrity.json").read_text()
            )["integrity_sha256"],
            "record_count": capture["record_count"],
            "valid_route_count": capture["valid_route_count"],
            "invalid_route_count": capture["invalid_route_count"],
            "total_tokens": capture["total_tokens"],
            "total_wall_latency_sec": capture["total_wall_latency_sec"],
        },
        "routed_gate": {
            "manifest_sha256": routed["manifest_sha256"],
            "row_count": routed["row_count"],
            "valid_run_count": routed["valid_run_count"],
            "invalid_route_count": routed["invalid_route_count"],
            "verdict_counts": routed["verdict_counts"],
            "decision": routed["decision"],
        },
        "routed_unsat_audit": {
            "audit_sha256": unsat_audit["audit_sha256"],
            "audited_unsat_count": unsat_audit["audited_unsat_count"],
            "direct_certificate_count": unsat_audit["direct_certificate_count"],
            "returned_invariant_certificate_count": unsat_audit[
                "returned_invariant_certificate_count"
            ],
        },
    }
    decisions = {
        "H1_phase_local": bool(routed["decision"]["h1_pass"]),
        "H2_source_representation": bool(routed["decision"]["h2_pass"]),
        "H3_llm_routing": bool(routed["decision"]["h3_pass"]),
        "H4_soundness": bool(routed["decision"]["h4_pass"]),
    }
    summary["decisions"] = decisions
    if decisions["H1_phase_local"]:
        summary["next_gate"] = "expand phase-local natural cases"
    elif decisions["H2_source_representation"]:
        summary["next_gate"] = "expand the paired representation population"
    elif decisions["H3_llm_routing"]:
        summary["next_gate"] = "replicate grammar routing on independent captures"
    else:
        summary["next_gate"] = (
            "close this gate; do not scale phase/source/LLM routing without a new hypothesis"
        )
    summary["summary_sha256"] = build_paired_corpus.canonical_sha256({
        key: value for key, value in summary.items() if key != "summary_sha256"
    })
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path == integrity_path:
            continue
        files.append({
            "path": path.relative_to(root).as_posix(),
            "sha256": file_sha256(path),
        })
    integrity = {
        "schema": ARTIFACT_INTEGRITY_SCHEMA,
        "status": "completed",
        "summary_sha256": file_sha256(summary_path),
        "files": files,
    }
    integrity["integrity_sha256"] = build_paired_corpus.canonical_sha256({
        key: value for key, value in integrity.items() if key != "integrity_sha256"
    })
    integrity_path.write_text(json.dumps(integrity, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "decisions": decisions,
        "summary_sha256": summary["summary_sha256"],
        "integrity_sha256": integrity["integrity_sha256"],
        "next_gate": summary["next_gate"],
        "artifact_dir": root.as_posix(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
