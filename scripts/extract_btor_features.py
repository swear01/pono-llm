#!/usr/bin/env python3
"""Extract deterministic structural features for the Gate 2 HWMCC scan."""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT_DIR / "llm_worker"))

from btor2_reader import parse_btor2  # noqa: E402
from experiment_manifest import (  # noqa: E402
    DEFAULT_BENCHMARK_ROOT,
    benchmark_id_for_path,
)
from invariant_arith import detect_software_origin, get_software_vars  # noqa: E402


FIELDNAMES = (
    "benchmark_id",
    "content_sha256",
    "parse_status",
    "parse_error",
    "file_bytes",
    "line_count",
    "node_count",
    "dataset_year",
    "producer",
    "suite",
    "state_count",
    "scalar_state_count",
    "array_state_count",
    "input_count",
    "named_state_count",
    "clean_state_count",
    "named_state_ratio",
    "clean_named_ratio",
    "software_origin",
    "has_array",
    "array_sort_count",
    "bad_count",
    "constraint_count",
    "state_widths",
    "max_state_width",
    "add_count",
    "sub_count",
    "mul_count",
    "mul_const_const_count",
    "mul_const_var_count",
    "mul_var_var_count",
    "divrem_count",
    "ite_count",
    "read_count",
    "write_count",
    "arithmetic_class",
    "size_bucket",
    "operator_counts_json",
    "parse_time_sec",
)

_CONST_FORMS = frozenset({"zero", "one", "ones", "const", "constd", "consth"})
_DIVREM_FORMS = frozenset({"udiv", "sdiv", "urem", "srem", "smod"})


def collect_paths(root: Path) -> list[Path]:
    return sorted({*root.rglob("*.btor2"), *root.rglob("*.btor")})


def source_labels(benchmark_id: str) -> tuple[str, str, str]:
    parts = Path(benchmark_id).parts
    year = parts[0] if parts else "unknown"
    for producer in ("sosylab", "hkust", "hku", "beem", "goel", "mann", "wolf"):
        if producer in parts:
            index = parts.index(producer)
            suite = parts[index + 1] if index + 1 < len(parts) - 1 else "unknown"
            return year, producer, suite
    return year, "other", parts[-2] if len(parts) >= 2 else "unknown"


def data_dependencies(info, lineno: int, op: str) -> list[int]:
    dependencies = info.deps.get(lineno, [])
    if op in {"slice", "sext", "uext"}:
        return dependencies
    return dependencies[1:] if dependencies else []


def constant_expression_nodes(info) -> set[int]:
    constants = set(info.consts)
    for lineno in sorted(info.ops):
        if lineno in constants:
            continue
        op = info.ops[lineno]
        dependencies = data_dependencies(info, lineno, op)
        if dependencies and all(dependency in constants for dependency in dependencies):
            constants.add(lineno)
    return constants


def multiplication_counts(info) -> tuple[int, int, int]:
    constants = constant_expression_nodes(info)
    const_const = 0
    const_var = 0
    var_var = 0
    for lineno, op in info.ops.items():
        if op != "mul":
            continue
        dependencies = data_dependencies(info, lineno, op)
        if len(dependencies) < 2:
            var_var += 1
            continue
        constant_operands = sum(
            dependency in constants for dependency in dependencies[:2]
        )
        if constant_operands == 2:
            const_const += 1
        elif constant_operands == 1:
            const_var += 1
        else:
            var_var += 1
    return const_const, const_var, var_var


def size_bucket(node_count: int) -> str:
    if node_count < 1_000:
        return "lt1k"
    if node_count < 10_000:
        return "1k-10k"
    if node_count < 100_000:
        return "10k-100k"
    return "ge100k"


def arithmetic_class(operator_counts: Counter, mul_var_var: int) -> str:
    if mul_var_var or any(operator_counts[op] for op in _DIVREM_FORMS):
        return "nonlinear"
    if operator_counts["add"] or operator_counts["sub"] or operator_counts["mul"]:
        return "affine"
    return "non-arithmetic"


def extract_features(path: Path, benchmark_root: Path) -> dict:
    start = time.monotonic()
    benchmark_id = benchmark_id_for_path(path, benchmark_root)
    info = parse_btor2(str(path))
    operator_counts = Counter(info.ops.values())
    states = info.states
    scalar_states = [state for state in states if not state.is_array]
    named_states = [state for state in states if state.symbol]
    clean_states = get_software_vars(info)
    const_const, const_var, var_var = multiplication_counts(info)
    year, producer, suite = source_labels(benchmark_id)
    widths = sorted({state.width for state in scalar_states if state.width > 0})
    named_count = len(named_states)
    has_array = bool(
        info.array_sort_count
        or any(state.is_array for state in states)
        or operator_counts["read"]
        or operator_counts["write"]
    )
    return {
        "benchmark_id": benchmark_id,
        "content_sha256": info.text_sha256,
        "parse_status": "ok",
        "parse_error": "",
        "file_bytes": path.stat().st_size,
        "line_count": info.line_count,
        "node_count": info.node_count,
        "dataset_year": year,
        "producer": producer,
        "suite": suite,
        "state_count": len(states),
        "scalar_state_count": len(scalar_states),
        "array_state_count": len(states) - len(scalar_states),
        "input_count": len(info.inputs),
        "named_state_count": named_count,
        "clean_state_count": len(clean_states),
        "named_state_ratio": f"{named_count / len(states):.6f}" if states else "0.000000",
        "clean_named_ratio": (
            f"{len(clean_states) / named_count:.6f}" if named_count else "0.000000"
        ),
        "software_origin": int(detect_software_origin(info)),
        "has_array": int(has_array),
        "array_sort_count": info.array_sort_count,
        "bad_count": info.bad_count,
        "constraint_count": info.constraint_count,
        "state_widths": ";".join(map(str, widths)),
        "max_state_width": max(widths, default=0),
        "add_count": operator_counts["add"],
        "sub_count": operator_counts["sub"],
        "mul_count": operator_counts["mul"],
        "mul_const_const_count": const_const,
        "mul_const_var_count": const_var,
        "mul_var_var_count": var_var,
        "divrem_count": sum(operator_counts[op] for op in _DIVREM_FORMS),
        "ite_count": operator_counts["ite"],
        "read_count": operator_counts["read"],
        "write_count": operator_counts["write"],
        "arithmetic_class": arithmetic_class(operator_counts, var_var),
        "size_bucket": size_bucket(info.node_count),
        "operator_counts_json": json.dumps(operator_counts, sort_keys=True),
        "parse_time_sec": f"{time.monotonic() - start:.6f}",
    }


def error_row(path: Path, benchmark_root: Path, exc: Exception, elapsed: float) -> dict:
    row = {field: "" for field in FIELDNAMES}
    row.update({
        "benchmark_id": benchmark_id_for_path(path, benchmark_root),
        "parse_status": "error",
        "parse_error": f"{type(exc).__name__}: {exc}",
        "file_bytes": path.stat().st_size,
        "parse_time_sec": f"{elapsed:.6f}",
    })
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-root", default=str(DEFAULT_BENCHMARK_ROOT))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    root = Path(args.benchmark_root).expanduser().resolve()
    output = Path(args.out)
    partial = output.with_name(output.name + ".partial")
    if output.exists() or partial.exists():
        raise FileExistsError(f"refusing to overwrite feature output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    paths = collect_paths(root)
    failures = 0
    counts = Counter()
    started = time.monotonic()
    with partial.open("x", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=FIELDNAMES, lineterminator="\n"
        )
        writer.writeheader()
        for index, path in enumerate(paths, start=1):
            row_start = time.monotonic()
            try:
                row = extract_features(path, root)
            except (OSError, UnicodeError, ValueError, KeyError, IndexError) as exc:
                failures += 1
                row = error_row(path, root, exc, time.monotonic() - row_start)
            writer.writerow(row)
            handle.flush()
            counts[row["parse_status"]] += 1
            if row.get("software_origin") == 1:
                counts["software_origin"] += 1
                if row.get("has_array") == 0:
                    counts["software_nonarray"] += 1
            if index % 100 == 0:
                print(
                    json.dumps({"processed": index, "total": len(paths)}),
                    file=sys.stderr,
                    flush=True,
                )
    partial.replace(output)
    print(json.dumps({
        "elapsed_sec": time.monotonic() - started,
        "files": len(paths),
        "counts": dict(sorted(counts.items())),
        "output": output.as_posix(),
    }, sort_keys=True))
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
