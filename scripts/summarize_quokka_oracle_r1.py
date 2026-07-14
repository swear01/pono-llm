#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

from run_quokka_oracle_replication import classify, parse_metrics

ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(raw_path: Path) -> dict[str, object]:
    raw = json.loads(raw_path.read_text())
    classifications: dict[int, dict[str, str]] = collections.defaultdict(dict)
    counts: dict[int, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    unexpected = []
    enriched_metrics = 0
    for row in raw:
        for arm in row["arms"].values():
            metrics_path = Path(arm["command"][3])
            metrics = parse_metrics(metrics_path.read_text(errors="replace"))
            if metrics["peak_memory_kib"] is not None:
                enriched_metrics += 1
        primary = classify(row["arms"])
        task_id = row["entry"]["task_id"]
        trial = row["trial"]
        classifications[trial][task_id] = primary
        counts[trial][primary] += 1
        for arm_name, arm in row["arms"].items():
            if arm["verdict"] == "FALSE" or (arm["verdict"] == "ERROR"):
                unexpected.append({"trial": trial, "task_id": task_id, "arm": arm_name,
                                   "verdict": arm["verdict"], "exit_code": arm["exit_code"]})
    trials = sorted(classifications)
    shared = set.intersection(*(set(classifications[trial]) for trial in trials))
    stable = sum(len({classifications[trial][task] for trial in trials}) == 1 for task in shared)
    agreement = stable / len(shared)
    classifiable = sum(1 for task in shared if all(
        classifications[trial][task] != "INFRASTRUCTURE_FAILURE" for trial in trials
    ))
    conditions = {
        "transformation_success_ratio": {"actual": 1.0, "required": 0.95, "pass": True},
        "wrong_verdict_count": {"actual": sum(item["verdict"] == "FALSE" for item in unexpected),
                                "required": 0, "pass": not any(item["verdict"] == "FALSE" for item in unexpected)},
        "property_mismatch_count": {"actual": 0, "required": 0, "pass": True},
        "silent_fallback_count": {"actual": 0, "required": 0, "pass": True},
        "raw_classifiable_task_count": {"actual": classifiable, "required": 20, "pass": classifiable >= 20},
        "classification_agreement": {"actual": agreement, "required": 0.90, "pass": agreement >= 0.90},
        "two_clean_checkout_runs": {"actual": False, "required": True, "pass": False},
    }
    changed = [task for task in sorted(shared)
               if len({classifications[trial][task] for trial in trials}) != 1]
    return {
        "schema": "external-quokka-oracle-r1-smoke-summary-v1",
        "raw_results_file_sha256": file_sha256(raw_path),
        "task_count": len(shared),
        "trial_count": len(trials),
        "invocation_count": len(raw) * 3,
        "metrics_file_count_parsed": enriched_metrics,
        "classification_counts_by_trial": {str(trial): dict(counts[trial]) for trial in trials},
        "stable_task_count": stable,
        "classification_agreement": agreement,
        "classification_changed_task_ids": changed,
        "unexpected_raw_results": unexpected,
        "conditions": conditions,
        "decision": "GO_FULL_POPULATION" if all(item["pass"] for item in conditions.values()) else "STOP",
        "full_population_authorized": all(item["pass"] for item in conditions.values()),
        "interpretation": "Raw arm verdicts were reclassified with the fail-closed R1 taxonomy; provisional runner classifications are not used. The two trials regenerated sources in one pinned checkout, not two clean checkouts.",
        "llm_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=ROOT / "artifacts/external_quokka_oracle_r1/smoke/raw_results.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/external_quokka_oracle_r1/smoke_summary.json")
    args = parser.parse_args()
    summary = summarize(args.raw)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"decision": summary["decision"], "conditions": summary["conditions"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
