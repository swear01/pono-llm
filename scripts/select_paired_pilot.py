#!/usr/bin/env python3
"""Select the frozen family-independent paired representation pilot."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import build_paired_corpus  # noqa: E402
import screen_paired_baseline  # noqa: E402
from experiment_manifest import file_sha256  # noqa: E402


PILOT_SCHEMA = "pono-llm-paired-pilot-v1"
SELECTION_SEED = "pono-llm-representation-phase-gate-v1"
TARGETS = {
    "safe-baseline-hard": 12,
    "safe-baseline-control": 4,
    "unsafe-soundness-control": 4,
}


def stable_rank(task: dict) -> str:
    identity = f"{SELECTION_SEED}:{task['benchmark_id']}:{task['btor2_sha256']}"
    return hashlib.sha256(identity.encode()).hexdigest()


def load_screen(path: Path, population: dict) -> dict[str, dict]:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    eligible = {
        task["benchmark_id"]: task
        for task in population["tasks"]
        if task["eligible"]
    }
    if len(rows) != len(eligible):
        raise ValueError(
            f"baseline screen row count mismatch: expected {len(eligible)}, got {len(rows)}"
        )
    indexed = {}
    for row in rows:
        benchmark_id = row.get("benchmark_id", "")
        if benchmark_id in indexed:
            raise ValueError(f"duplicate baseline row: {benchmark_id}")
        if benchmark_id not in eligible:
            raise ValueError(f"unexpected baseline row: {benchmark_id}")
        task = eligible[benchmark_id]
        if row.get("schema") != screen_paired_baseline.SCREEN_SCHEMA:
            raise ValueError(f"baseline row has wrong schema: {benchmark_id}")
        if row.get("population_sha256") != population["population_sha256"]:
            raise ValueError(f"baseline row references another population: {benchmark_id}")
        for field in ("btor2_sha256", "source_family_id", "expected_verdict"):
            if row.get(field) != task[field]:
                raise ValueError(f"baseline/task {field} mismatch: {benchmark_id}")
        expected_formal = "unsat" if task["expected_verdict"] == "safe" else "sat"
        verdict = row.get("baseline_verdict")
        if verdict in {"sat", "unsat"} and verdict != expected_formal:
            raise ValueError(
                f"baseline contradicts expected verdict for {benchmark_id}"
            )
        indexed[benchmark_id] = row
    if set(indexed) != set(eligible):
        raise ValueError("baseline screen does not cover the eligible population")
    return indexed


def role_for(task: dict, baseline: dict) -> str | None:
    verdict = baseline["baseline_verdict"]
    if task["expected_verdict"] == "unsafe":
        return "unsafe-soundness-control" if verdict == "sat" else None
    if verdict == "unsat":
        return "safe-baseline-control"
    if verdict in {"unknown", "timeout"}:
        return "safe-baseline-hard"
    return None


def stratified_family_select(
    tasks: list[dict],
    target: int,
    used_families: set[str],
    used_hashes: set[str],
) -> list[dict]:
    representatives = {}
    for task in tasks:
        if task["source_family_id"] in used_families:
            continue
        if task["btor2_sha256"] in used_hashes:
            continue
        key = (task["source_family_id"], task["btor2_sha256"])
        current = representatives.get(key)
        if current is None or (stable_rank(task), task["benchmark_id"]) < (
            stable_rank(current), current["benchmark_id"]
        ):
            representatives[key] = task

    groups = defaultdict(list)
    for task in representatives.values():
        groups[task["category"]].append(task)
    for group in groups.values():
        group.sort(key=lambda task: (stable_rank(task), task["benchmark_id"]))

    selected = []
    categories = sorted(groups)
    while categories and len(selected) < target:
        remaining = []
        for category in categories:
            group = groups[category]
            while group and (
                group[0]["source_family_id"] in used_families
                or group[0]["btor2_sha256"] in used_hashes
            ):
                group.pop(0)
            if group:
                task = group.pop(0)
                selected.append(task)
                used_families.add(task["source_family_id"])
                used_hashes.add(task["btor2_sha256"])
                if len(selected) >= target:
                    break
            if group:
                remaining.append(category)
        categories = remaining
    return selected


def select_pilot(population: dict, screen: dict[str, dict], screen_path: Path) -> dict:
    role_groups = defaultdict(list)
    excluded_screen = Counter()
    for task in population["tasks"]:
        if not task["eligible"]:
            continue
        role = role_for(task, screen[task["benchmark_id"]])
        if role is None:
            key = (
                f"{task['expected_verdict']}:"
                f"{screen[task['benchmark_id']]['baseline_verdict']}"
            )
            excluded_screen[key] += 1
            continue
        role_groups[role].append(task)

    selected = []
    used_families: set[str] = set()
    used_hashes: set[str] = set()
    for role in (
        "safe-baseline-hard",
        "safe-baseline-control",
        "unsafe-soundness-control",
    ):
        chosen = stratified_family_select(
            role_groups[role], TARGETS[role], used_families, used_hashes
        )
        for task in chosen:
            selected.append((role, task))

    benchmarks = []
    for role, task in selected:
        baseline = screen[task["benchmark_id"]]
        benchmarks.append({
            "benchmark_id": task["benchmark_id"],
            "path": task["btor2_path"],
            "content_sha256": task["btor2_sha256"],
            "source_path": task["source_path"],
            "source_sha256": task["source_sha256"],
            "source_yaml_path": task["source_yaml_path"],
            "source_yaml_sha256": task["source_yaml_sha256"],
            "source_family_id": task["source_family_id"],
            "source_family_key": task["source_family_key"],
            "category": task["category"],
            "expected_verdict": task["expected_verdict"],
            "selection_role": role,
            "baseline_verdict": baseline["baseline_verdict"],
            "baseline_engine": baseline["engine"],
            "baseline_proof_time_sec": baseline["proof_time_sec"],
            "source_state_mapping": task["source_state_mapping"],
            "phases": task["phases"],
        })
    benchmarks.sort(key=lambda row: (row["selection_role"], row["benchmark_id"]))
    actual_counts = Counter(row["selection_role"] for row in benchmarks)
    pilot = {
        "schema": PILOT_SCHEMA,
        "selection_seed": SELECTION_SEED,
        "selection_before_llm": True,
        "population_sha256": population["population_sha256"],
        "baseline_screen_sha256": file_sha256(screen_path),
        "target_counts": TARGETS,
        "available_counts": {
            role: len(tasks) for role, tasks in sorted(role_groups.items())
        },
        "actual_counts": dict(sorted(actual_counts.items())),
        "selected_count": len(benchmarks),
        "selected_family_count": len({row["source_family_id"] for row in benchmarks}),
        "selected_content_count": len({row["content_sha256"] for row in benchmarks}),
        "screen_exclusion_counts": dict(sorted(excluded_screen.items())),
        "benchmarks": benchmarks,
    }
    pilot["pilot_sha256"] = build_paired_corpus.canonical_sha256({
        key: value for key, value in pilot.items() if key != "pilot_sha256"
    })
    return pilot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("population")
    parser.add_argument("baseline_screen")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    population_path = Path(args.population)
    population = screen_paired_baseline.load_population(population_path)
    screen_path = Path(args.baseline_screen)
    screen = load_screen(screen_path, population)
    pilot = select_pilot(population, screen, screen_path)
    output = Path(args.out)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite paired pilot: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(pilot, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "selected_count": pilot["selected_count"],
        "actual_counts": pilot["actual_counts"],
        "selected_family_count": pilot["selected_family_count"],
        "selected_content_count": pilot["selected_content_count"],
        "pilot_sha256": pilot["pilot_sha256"],
        "output": output.as_posix(),
    }, sort_keys=True))
    if pilot["selected_count"] < sum(TARGETS.values()):
        print(
            "paired pilot is smaller than the target; no quota was silently relaxed",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
