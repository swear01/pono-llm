#!/usr/bin/env python3
"""Independently certify Pono invariants for routed UNSAT rows."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import build_paired_corpus  # noqa: E402
import cert_check  # noqa: E402
from experiment_manifest import file_sha256, stable_slug  # noqa: E402
import grammar_routes  # noqa: E402
import representation_views  # noqa: E402
import run_matrix  # noqa: E402
import run_phase_grammar  # noqa: E402
import run_routed_phase_matrix  # noqa: E402


AUDIT_SCHEMA = "pono-llm-routed-unsat-audit-v1"
PONO = ROOT_DIR / "build" / "pono"


def replayable_route_payload(report: dict) -> dict:
    routes = []
    for compiled in report["routes"]:
        family = compiled["family"]
        route = {
            "variables": compiled["requested_variables"],
            "family": family,
            "relations": compiled["relations"],
            "signedness": compiled["signedness"],
        }
        for field in grammar_routes.FAMILY_FIELDS[family]:
            if field in compiled:
                route[field] = compiled[field]
        routes.append(route)
    return {"schema": grammar_routes.ROUTE_SCHEMA, "routes": routes}


def invariant_line(output: str) -> str:
    matches = re.findall(r"^INVAR:\s*(.+?)\s*$", output, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(f"expected one single-line INVAR, found {len(matches)}")
    return "INVAR: " + matches[0] + "\n"


def replay_and_certify(
    report: dict,
    btor2: Path,
    output: Path,
    pono_timeout: float,
    cert_timeout_ms: int,
) -> dict:
    route_payload = replayable_route_payload(report)
    _, _, entries = run_phase_grammar.prepare_entries(
        str(btor2),
        route_payload,
        phase_mode=report["phase_mode"],
        cap=20000,
    )
    lines = run_phase_grammar.entry_lines(entries)
    candidate_text = "\n".join(lines) + "\n"
    candidate_sha256 = hashlib.sha256(candidate_text.encode()).hexdigest()
    if candidate_sha256 != report["candidate_sha256"]:
        raise ValueError(
            f"candidate replay hash mismatch for {report['benchmark_id']}/"
            f"{report['config']}"
        )
    slug = stable_slug(report["benchmark_id"])
    stem = f"{slug}.{report['config']}"
    candidate_relative = Path("candidates") / f"{stem}.jsonl"
    transcript_relative = Path("transcripts") / f"{stem}.log"
    invariant_relative = Path("invariants") / f"{stem}.txt"
    candidate_path = output / candidate_relative
    transcript_path = output / transcript_relative
    invariant_path = output / invariant_relative
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    invariant_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(candidate_text)

    command = [
        str(PONO),
        "-e", "ic3ia",
        "--ic3ia-max-refinements", "2",
        "--show-invar",
        "--initial-predicates", str(candidate_path),
        str(btor2),
    ]
    started = time.monotonic()
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            timeout=pono_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or b"") + (exc.stderr or b"")
        transcript_path.write_bytes(partial)
        raise RuntimeError(
            f"Pono invariant replay timed out for {report['benchmark_id']}/"
            f"{report['config']} after {pono_timeout}s"
        ) from exc
    elapsed = time.monotonic() - started
    raw_output = process.stdout + process.stderr
    transcript_path.write_bytes(raw_output)
    verdict = run_matrix.parse_verdict(raw_output)
    if verdict != "unsat" or not run_matrix.verdict_matches_exit(
        verdict, process.returncode
    ):
        raise RuntimeError(
            f"Pono invariant replay did not reproduce UNSAT for "
            f"{report['benchmark_id']}/{report['config']}: "
            f"verdict={verdict}, exit={process.returncode}"
        )
    invar_text = invariant_line(raw_output.decode(errors="strict"))
    invariant_path.write_text(invar_text)
    checks = cert_check.certify(str(btor2), invar_text, cert_timeout_ms)
    check_rows = [{"name": name, "result": str(result)} for name, result in checks]
    if any(row["result"] != "unsat" for row in check_rows):
        raise RuntimeError(
            f"returned invariant failed independent certification for "
            f"{report['benchmark_id']}/{report['config']}: {check_rows}"
        )
    return {
        "benchmark_id": report["benchmark_id"],
        "config": report["config"],
        "content_sha256": file_sha256(btor2),
        "candidate_path": candidate_relative.as_posix(),
        "candidate_sha256": file_sha256(candidate_path),
        "transcript_path": transcript_relative.as_posix(),
        "transcript_sha256": file_sha256(transcript_path),
        "invariant_path": invariant_relative.as_posix(),
        "invariant_sha256": file_sha256(invariant_path),
        "pono_replay_time_sec": elapsed,
        "checks": check_rows,
        "certified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pilot")
    parser.add_argument("routed_matrix_dir")
    parser.add_argument("translation_repo")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--pono-timeout", type=float, default=70.0)
    parser.add_argument("--cert-timeout-ms", type=int, default=70000)
    args = parser.parse_args()
    if args.pono_timeout <= 0 or args.cert_timeout_ms <= 0:
        parser.error("timeouts must be positive")

    pilot = representation_views.verify_pilot(Path(args.pilot))
    tasks = {task["benchmark_id"]: task for task in pilot["benchmarks"]}
    matrix_dir = Path(args.routed_matrix_dir)
    manifest = json.loads((matrix_dir / "manifest.json").read_text())
    if manifest.get("schema") != run_routed_phase_matrix.MATRIX_SCHEMA:
        raise ValueError("routed matrix has the wrong schema")
    with (matrix_dir / "matrix.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    translation_repo = Path(args.translation_repo).expanduser().resolve()
    build_paired_corpus.verify_repository(
        translation_repo, build_paired_corpus.TRANSLATION_REVISION, "translation"
    )
    output = Path(args.out_dir)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite routed UNSAT audit: {output}")
    output.mkdir(parents=True)

    records = []
    direct = []
    for row in rows:
        if row["verdict"] != "unsat":
            continue
        report = json.loads((matrix_dir / row["report_path"]).read_text())
        if row["certificate_ok"] == "true":
            direct.append({
                "benchmark_id": row["benchmark_id"],
                "config": row["config"],
                "report_path": row["report_path"],
                "report_sha256": row["report_sha256"],
                "certificate_checks": json.loads(row["certificate_checks_json"]),
            })
            continue
        task = tasks[row["benchmark_id"]]
        btor2 = translation_repo / task["path"]
        records.append(replay_and_certify(
            report, btor2, output, args.pono_timeout, args.cert_timeout_ms
        ))
    audit = {
        "schema": AUDIT_SCHEMA,
        "pilot_sha256": pilot["pilot_sha256"],
        "routed_matrix_manifest_sha256": file_sha256(matrix_dir / "manifest.json"),
        "direct_certificate_count": len(direct),
        "returned_invariant_certificate_count": len(records),
        "audited_unsat_count": len(direct) + len(records),
        "direct_certificates": direct,
        "returned_invariant_certificates": records,
    }
    audit["audit_sha256"] = build_paired_corpus.canonical_sha256({
        key: value for key, value in audit.items() if key != "audit_sha256"
    })
    (output / "manifest.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({
        "audited_unsat_count": audit["audited_unsat_count"],
        "direct_certificate_count": audit["direct_certificate_count"],
        "returned_invariant_certificate_count": audit[
            "returned_invariant_certificate_count"
        ],
        "audit_sha256": audit["audit_sha256"],
        "output": output.as_posix(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
