#!/usr/bin/env python3
"""Run the engine-only baseline over a frozen paired population."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import build_paired_corpus  # noqa: E402
import run_matrix  # noqa: E402
from experiment_manifest import file_sha256  # noqa: E402


SCREEN_SCHEMA = "pono-llm-paired-baseline-screen-v1"
FIELDS = (
    "schema",
    "population_sha256",
    "benchmark_id",
    "btor2_sha256",
    "source_family_id",
    "category",
    "expected_verdict",
    "baseline_verdict",
    "expected_match",
    "engine",
    "proof_time_sec",
    "error",
    "fast_results_json",
)


def load_population(path: Path) -> dict:
    population = json.loads(path.read_text())
    if population.get("schema") != build_paired_corpus.POPULATION_SCHEMA:
        raise ValueError("paired population has the wrong schema")
    declared = population.get("population_sha256")
    computed = build_paired_corpus.canonical_sha256({
        key: value
        for key, value in population.items()
        if key != "population_sha256"
    })
    if declared != computed:
        raise ValueError(
            f"paired population hash mismatch: declared {declared}, got {computed}"
        )
    return population


def task_path(task: dict, translation_repo: Path) -> Path:
    path = translation_repo / task["btor2_path"]
    if not path.is_file():
        raise ValueError(f"missing frozen BTOR2: {path}")
    digest = file_sha256(path)
    if digest != task["btor2_sha256"]:
        raise ValueError(
            f"BTOR2 hash mismatch for {task['benchmark_id']}: "
            f"expected {task['btor2_sha256']}, got {digest}"
        )
    return path


def screen_task(
    task: dict,
    path: Path,
    population_sha256: str,
    timeout: float,
) -> dict:
    result = run_matrix.baseline(path, timeout)
    verdict = result.get("verdict", "error")
    expected_formal = "unsat" if task["expected_verdict"] == "safe" else "sat"
    if verdict in {"sat", "unsat"} and verdict != expected_formal:
        raise RuntimeError(
            f"baseline contradicts expected verdict for {task['benchmark_id']}: "
            f"expected {expected_formal}, got {verdict}"
        )
    return {
        "schema": SCREEN_SCHEMA,
        "population_sha256": population_sha256,
        "benchmark_id": task["benchmark_id"],
        "btor2_sha256": task["btor2_sha256"],
        "source_family_id": task["source_family_id"],
        "category": task["category"],
        "expected_verdict": task["expected_verdict"],
        "baseline_verdict": verdict,
        "expected_match": str(verdict == expected_formal).lower(),
        "engine": result.get("engine", ""),
        "proof_time_sec": f"{float(result.get('proof_time', 0.0)):.6f}",
        "error": result.get("error", ""),
        "fast_results_json": json.dumps(
            result.get("fast_results", {}), sort_keys=True
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("population")
    parser.add_argument("translation_repo")
    parser.add_argument("--out", required=True)
    parser.add_argument("--ic3ia-timeout", type=float, default=10.0)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.ic3ia_timeout <= 0:
        parser.error("--ic3ia-timeout must be positive")
    if args.workers <= 0:
        parser.error("--workers must be positive")

    population_path = Path(args.population)
    population = load_population(population_path)
    translation_repo = Path(args.translation_repo).expanduser().resolve()
    build_paired_corpus.verify_repository(
        translation_repo,
        build_paired_corpus.TRANSLATION_REVISION,
        "translation",
    )
    tasks = [task for task in population["tasks"] if task["eligible"]]
    paths = {task["benchmark_id"]: task_path(task, translation_repo) for task in tasks}

    output = Path(args.out)
    partial = output.with_name(output.name + ".partial")
    if output.exists() or partial.exists():
        raise FileExistsError(f"refusing to overwrite baseline screen: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                screen_task,
                task,
                paths[task["benchmark_id"]],
                population["population_sha256"],
                args.ic3ia_timeout,
            ): task["benchmark_id"]
            for task in tasks
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            rows.append(future.result())
            if completed % 20 == 0 or completed == len(futures):
                print(
                    json.dumps({"completed": completed, "total": len(futures)}),
                    file=sys.stderr,
                    flush=True,
                )

    rows.sort(key=lambda row: row["benchmark_id"])
    with partial.open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    partial.replace(output)
    counts = {}
    for row in rows:
        key = row["baseline_verdict"]
        counts[key] = counts.get(key, 0) + 1
    print(json.dumps({
        "schema": SCREEN_SCHEMA,
        "population_sha256": population["population_sha256"],
        "row_count": len(rows),
        "verdict_counts": dict(sorted(counts.items())),
        "output_sha256": file_sha256(output),
        "output": output.as_posix(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
