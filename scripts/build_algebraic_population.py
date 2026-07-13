#!/usr/bin/env python3
"""Select the preregistered natural Gate 4B polynomial population structurally."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Sequence

import bv_poly_kernel as kernel
import cert_check


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strongly_connected_components(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    result: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for successor in sorted(graph[node]):
            if successor not in graph:
                continue
            if successor not in indices:
                visit(successor)
                lowlinks[node] = min(lowlinks[node], lowlinks[successor])
            elif successor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[successor])
        if lowlinks[node] == indices[node]:
            component = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            result.append(tuple(sorted(component, key=_ref_number)))

    for node in sorted(graph, key=_ref_number):
        if node not in indices:
            visit(node)
    return result


def _ref_number(ref: str) -> int:
    return int(ref.removeprefix("state").removeprefix("input"))


def _width_variables(model: dict, width: int) -> tuple[str, ...]:
    variables = [
        f"state{node}"
        for node in model["states"]
        if cert_check.width_of(model, node) == width
    ]
    variables.extend(
        f"input{node}"
        for node, (operation, args) in model["nodes"].items()
        if operation == "input" and model["sorts"][args[0]] == width
    )
    return tuple(sorted(variables, key=lambda ref: (ref.startswith("input"), _ref_number(ref))))


def _task_components(model: dict, branch_cap: int) -> tuple[list[dict], dict[str, int]]:
    by_width: dict[int, list[int]] = defaultdict(list)
    for state in model["states"]:
        by_width[cert_check.width_of(model, state)].append(state)
    components = []
    diagnostics: Counter[str] = Counter()
    for width, states in sorted(by_width.items()):
        variables = _width_variables(model, width)
        update_info: dict[str, dict] = {}
        for state in sorted(states):
            ref = f"state{state}"
            if state not in model["nexts"]:
                diagnostics["state-missing-next"] += 1
                continue
            try:
                branches = kernel.expand_polynomial_branches(
                    model,
                    model["nexts"][state],
                    width=width,
                    polynomial_variables=variables,
                )
            except (kernel.UnsupportedPolynomialModel, KeyError, ValueError):
                diagnostics["state-unsupported-next"] += 1
                continue
            update_info[ref] = {
                "branch_count": len(branches),
                "degree": max(branch.polynomial.degree() for branch in branches),
                "dependencies": sorted(
                    {
                        variable
                        for branch in branches
                        for variable in branch.polynomial.variables()
                        if variable.startswith("state")
                    },
                    key=_ref_number,
                ),
            }
            diagnostics["state-supported-next"] += 1
            if update_info[ref]["degree"] >= 2:
                diagnostics["state-nonlinear-next"] += 1
        graph = {
            ref: {dependency for dependency in info["dependencies"] if dependency in update_info}
            for ref, info in update_info.items()
        }
        for component in _strongly_connected_components(graph):
            maximum_degree = max(update_info[ref]["degree"] for ref in component)
            if maximum_degree < 2:
                continue
            diagnostics["nonlinear-scc"] += 1
            try:
                branches = kernel.extract_transition_branches(
                    model,
                    width=width,
                    polynomial_variables=variables,
                    tracked_state_variables=component,
                    branch_cap=branch_cap,
                )
            except (kernel.UnsupportedPolynomialModel, KeyError, ValueError) as error:
                if "branch count exceeds cap" in str(error):
                    diagnostics["nonlinear-scc-over-branch-cap"] += 1
                else:
                    diagnostics["nonlinear-scc-extraction-error"] += 1
                continue
            if len(component) > 1 and len(branches) > 1:
                structural_class = "coupled-guarded-polynomial"
            elif len(component) > 1:
                structural_class = "coupled-polynomial"
            elif len(branches) > 1:
                structural_class = "guarded-polynomial"
            else:
                structural_class = "single-branch-polynomial"
            components.append(
                {
                    "width": width,
                    "tracked_states": list(component),
                    "polynomial_variables": list(variables),
                    "scc_size": len(component),
                    "branch_count": len(branches),
                    "maximum_update_degree": maximum_degree,
                    "structural_class": structural_class,
                    "branch_ids": [branch.branch_id for branch in branches],
                }
            )
            diagnostics["eligible-component"] += 1
    return (
        sorted(
            components,
            key=lambda item: (
                -item["maximum_update_degree"],
                -item["scc_size"],
                item["branch_count"],
                item["width"],
                item["tracked_states"],
            ),
        ),
        dict(diagnostics),
    )


def _round_robin_select(rows: list[dict], count: int) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["component"]["structural_class"]].append(row)
    for values in groups.values():
        values.sort(key=lambda item: (item["source_family_id"], item["benchmark_id"]))
    selected = []
    classes = sorted(groups)
    while len(selected) < count and classes:
        next_classes = []
        for structural_class in classes:
            values = groups[structural_class]
            if values:
                selected.append(values.pop(0))
                if len(selected) == count:
                    break
            if values:
                next_classes.append(structural_class)
        classes = next_classes
    return selected


def build_population(
    population_path: Path,
    baseline_path: Path,
    translation_root: Path,
    output_path: Path,
    *,
    safe_count: int,
    unsafe_count: int,
    branch_cap: int,
) -> dict:
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite population: {output_path}")
    population = json.loads(population_path.read_text())
    if population.get("schema") != "pono-llm-paired-population-v1":
        raise ValueError("unsupported paired-population schema")
    baseline_rows = {
        row["benchmark_id"]: row for row in csv.DictReader(baseline_path.open())
    }
    eligible = []
    exclusions: Counter[str] = Counter()
    structural_diagnostics: Counter[str] = Counter()
    near_miss_examples: dict[str, list[str]] = defaultdict(list)
    for task in population.get("tasks", []):
        if task.get("has_array"):
            exclusions["array-theory"] += 1
            continue
        model_path = translation_root / task["btor2_path"]
        if not model_path.is_file():
            raise ValueError(f"missing translated benchmark: {model_path}")
        actual_hash = file_sha256(model_path)
        if actual_hash != task["btor2_sha256"]:
            raise ValueError(f"BTOR2 hash mismatch: {task['benchmark_id']}")
        try:
            model = cert_check.parse_btor2(model_path)
            components, diagnostics = _task_components(model, branch_cap)
            structural_diagnostics.update(diagnostics)
        except (KeyError, ValueError, NotImplementedError) as error:
            exclusions[f"parse-error:{type(error).__name__}"] += 1
            continue
        if not components:
            if diagnostics.get("nonlinear-scc-over-branch-cap", 0):
                reason = "nonlinear-scc-over-branch-cap"
            elif diagnostics.get("state-nonlinear-next", 0):
                reason = "nonlinear-update-not-v1-component"
            else:
                reason = "no-v1-nonlinear-update"
            exclusions[reason] += 1
            if len(near_miss_examples[reason]) < 20:
                near_miss_examples[reason].append(task["benchmark_id"])
            continue
        baseline = baseline_rows.get(task["benchmark_id"])
        baseline_verdict = baseline["baseline_verdict"] if baseline else "not-screened"
        row = {
            "benchmark_id": task["benchmark_id"],
            "btor2_path": task["btor2_path"],
            "btor2_sha256": actual_hash,
            "source_family_id": task["source_family_id"],
            "source_family_key": task["source_family_key"],
            "category": task["category"],
            "expected_verdict": task["expected_verdict"],
            "baseline_verdict": baseline_verdict,
            "component": components[0],
            "component_count": len(components),
        }
        eligible.append(row)

    deduplicated = []
    seen_families: set[str] = set()
    seen_contents: set[str] = set()
    for row in sorted(eligible, key=lambda item: (item["source_family_id"], item["benchmark_id"])):
        if row["source_family_id"] in seen_families:
            exclusions["source-family-duplicate"] += 1
            continue
        if row["btor2_sha256"] in seen_contents:
            exclusions["content-duplicate"] += 1
            continue
        seen_families.add(row["source_family_id"])
        seen_contents.add(row["btor2_sha256"])
        deduplicated.append(row)

    safe_pool = [
        row
        for row in deduplicated
        if row["expected_verdict"] == "safe"
        and row["baseline_verdict"] in {"timeout", "unknown"}
    ]
    unsafe_pool = [
        row for row in deduplicated if row["expected_verdict"] == "unsafe"
    ]
    safe_selected = _round_robin_select(safe_pool, safe_count)
    unsafe_selected = _round_robin_select(unsafe_pool, unsafe_count)
    selected = [
        {**row, "selection_role": "safe-baseline-hard", "counts_toward_h5a": True}
        for row in safe_selected
    ] + [
        {**row, "selection_role": "unsafe-soundness-control", "counts_toward_h5a": False}
        for row in unsafe_selected
    ]
    selected_classes = sorted(
        {row["component"]["structural_class"] for row in safe_selected}
    )
    population_sufficient = (
        len(safe_selected) >= safe_count
        and len(unsafe_selected) >= unsafe_count
        and len(selected_classes) >= 3
    )
    report = {
        "schema": "pono-modular-algebraic-population-v1",
        "selection_status": (
            "frozen-structural-population"
            if population_sufficient
            else "population-insufficient-for-h5a"
        ),
        "population_sufficient": population_sufficient,
        "source_population_sha256": file_sha256(population_path),
        "source_baseline_sha256": file_sha256(baseline_path),
        "translation_revision": population["provenance"]["translation_revision"],
        "branch_cap": branch_cap,
        "requested_safe_count": safe_count,
        "requested_unsafe_count": unsafe_count,
        "eligible_before_dedup_count": len(eligible),
        "eligible_after_dedup_count": len(deduplicated),
        "safe_baseline_hard_available_count": len(safe_pool),
        "unsafe_available_count": len(unsafe_pool),
        "selected_safe_count": len(safe_selected),
        "selected_unsafe_count": len(unsafe_selected),
        "selected_safe_structural_classes": selected_classes,
        "exclusion_counts": dict(sorted(exclusions.items())),
        "structural_diagnostics": dict(sorted(structural_diagnostics.items())),
        "near_miss_examples": {
            key: values for key, values in sorted(near_miss_examples.items())
        },
        "selected": selected,
    }
    report["population_sha256"] = canonical_sha256(report)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("population", type=Path)
    parser.add_argument("baseline_screen", type=Path)
    parser.add_argument("translation_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--safe-count", type=int, default=16)
    parser.add_argument("--unsafe-count", type=int, default=4)
    parser.add_argument("--branch-cap", type=int, default=8)
    args = parser.parse_args(argv)
    if args.safe_count < 12 or args.safe_count > 20:
        parser.error("--safe-count must be in the preregistered range 12..20")
    if args.unsafe_count < 4 or args.unsafe_count > 6:
        parser.error("--unsafe-count must be in the preregistered range 4..6")
    if args.branch_cap <= 0:
        parser.error("--branch-cap must be positive")
    try:
        report = build_population(
            args.population,
            args.baseline_screen,
            args.translation_root,
            args.output,
            safe_count=args.safe_count,
            unsafe_count=args.unsafe_count,
            branch_cap=args.branch_cap,
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(str(error))
        return 1
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "selection_status",
                    "eligible_after_dedup_count",
                    "safe_baseline_hard_available_count",
                    "unsafe_available_count",
                    "selected_safe_count",
                    "selected_unsafe_count",
                    "selected_safe_structural_classes",
                )
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
