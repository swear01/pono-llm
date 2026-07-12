#!/usr/bin/env python3
"""Certify or replay deterministic grammar routes on the original BTOR2."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import candidate_cert_check  # noqa: E402
import grammar_routes  # noqa: E402
import run_matrix  # noqa: E402
from experiment_manifest import file_sha256  # noqa: E402

REPORT_SCHEMA = "pono-llm-phase-grammar-run-v1"


def entry_lines(entries: list[dict]) -> list[str]:
    return [json.dumps(entry, sort_keys=True) for entry in entries]


def prepare_entries(
    btor2: str,
    route_payload: object,
    *,
    phase_mode: str,
    cap: int,
) -> tuple[list[grammar_routes.GrammarRoute], list[grammar_routes.Phase], list[dict]]:
    routes = grammar_routes.compile_route_document(btor2, route_payload)
    global_entries = grammar_routes.expand_routes(btor2, routes, cap=cap)
    phases = (
        grammar_routes.extract_functional_phases(btor2)
        if phase_mode == "all"
        else []
    )
    entries = grammar_routes.apply_phase_mode(
        global_entries, phases, mode=phase_mode, cap=cap
    )
    if not entries:
        raise ValueError("grammar routes expanded to no candidates")
    return routes, phases, entries


def certify_entries(
    btor2: str, entries: list[dict], timeout_ms: int
) -> tuple[dict, float]:
    if timeout_ms <= 0:
        raise ValueError("certificate timeout must be positive")
    start = time.monotonic()
    report = candidate_cert_check.houdini_certify(
        btor2,
        [entry["predicate_ast"] for entry in entries],
        timeout_ms,
    )
    return report, time.monotonic() - start


def run_gate(
    btor2: str,
    route_payload: object,
    *,
    phase_mode: str,
    cap: int,
    cert_timeout_ms: int,
    pono_timeout: float,
    max_refinements: int | None,
) -> dict:
    if cap <= 0:
        raise ValueError("candidate cap must be positive")
    if pono_timeout <= 0:
        raise ValueError("Pono timeout must be positive")
    generation_start = time.monotonic()
    routes, phases, entries = prepare_entries(
        btor2, route_payload, phase_mode=phase_mode, cap=cap
    )
    generation_time = time.monotonic() - generation_start
    lines = entry_lines(entries)
    candidate_text = "\n".join(lines) + "\n"
    report, certificate_time = certify_entries(
        btor2, entries, cert_timeout_ms
    )

    if report["ok"]:
        result = {
            "verdict": "unsat",
            "time": 0.0,
            "exit": 0,
            "engine": "phase-grammar-certificate",
            "error": "",
        }
    else:
        result = run_matrix.run_with_predicates(
            Path(btor2), lines, pono_timeout, max_refinements
        )
        result["engine"] = "phase-grammar-ic3ia"

    selected = report.get("selected_indices", [])
    proof_time = certificate_time + float(result.get("time", 0.0))
    route_document = json.loads(grammar_routes.canonical_route_document(routes))
    return {
        "schema": REPORT_SCHEMA,
        "benchmark": str(Path(btor2).resolve()),
        "benchmark_sha256": file_sha256(btor2),
        "phase_mode": phase_mode,
        "phase_count": len(phases),
        "phases": [phase.canonical_payload() for phase in phases],
        "route_count": len(routes),
        "route_sha256": grammar_routes.canonical_sha256(route_document),
        "routes": route_document["routes"],
        "pool_candidate_count": len(entries),
        "selected_candidate_count": len(selected),
        "selected_indices": selected,
        "candidate_sha256": hashlib.sha256(candidate_text.encode()).hexdigest(),
        "candidate_generation_sec": generation_time,
        "certificate_time_sec": certificate_time,
        "model_checker_time_sec": float(result.get("time", 0.0)),
        "proof_time_sec": proof_time,
        "offline_time_sec": generation_time + proof_time,
        "end_to_end_sec": generation_time + proof_time,
        "certificate": report,
        "verdict": result.get("verdict", "error"),
        "engine": result.get("engine", ""),
        "exit": result.get("exit"),
        "error": result.get("error", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("btor2")
    parser.add_argument("routes")
    parser.add_argument("--phase-mode", choices=("global", "all"), required=True)
    parser.add_argument("--cap", type=int, default=2000)
    parser.add_argument("--cert-timeout-ms", type=int, default=20000)
    parser.add_argument("--pono-timeout", type=float, default=70.0)
    parser.add_argument("--ic3ia-max-refinements", type=int)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.cap <= 0:
        parser.error("--cap must be positive")
    if args.cert_timeout_ms <= 0 or args.pono_timeout <= 0:
        parser.error("timeouts must be positive")
    if args.ic3ia_max_refinements is not None and args.ic3ia_max_refinements < 0:
        parser.error("--ic3ia-max-refinements must be non-negative")
    output = Path(args.out)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite phase-grammar report: {output}")
    try:
        route_payload = json.loads(Path(args.routes).read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid route JSON: {exc}") from exc
    report = run_gate(
        args.btor2,
        route_payload,
        phase_mode=args.phase_mode,
        cap=args.cap,
        cert_timeout_ms=args.cert_timeout_ms,
        pono_timeout=args.pono_timeout,
        max_refinements=args.ic3ia_max_refinements,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        key: report[key]
        for key in (
            "verdict",
            "engine",
            "phase_mode",
            "phase_count",
            "route_count",
            "pool_candidate_count",
            "selected_candidate_count",
            "end_to_end_sec",
        )
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
