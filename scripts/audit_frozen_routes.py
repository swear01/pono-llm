#!/usr/bin/env python3
"""Classify frozen LLM formulas against the preregistered bounded grammar."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT_DIR / "llm_worker"))

from btor2_reader import parse_btor2  # noqa: E402
import build_paired_corpus  # noqa: E402
import candidate_cert_check  # noqa: E402
from experiment_manifest import file_sha256  # noqa: E402
import experiment_manifest  # noqa: E402
import grammar_routes  # noqa: E402


AUDIT_SCHEMA = "pono-llm-frozen-route-audit-v1"
FAMILY_ORDER = {
    "unary": 0,
    "pairwise_offset": 1,
    "sum_equality": 2,
    "affine": 3,
    "quadratic_recurrence": 4,
}


def normalize_ast(ast: object) -> object:
    if not isinstance(ast, dict):
        return ast
    form = ast.get("form")
    if form == "const":
        width = int(ast.get("width", 0))
        raw = str(ast.get("const", "0"))
        if width > 0:
            value = int(raw[2:], 2) if raw.startswith("#b") else (
                int(raw[2:], 16) if raw.startswith("#x") else int(raw, 10)
            )
            return {"form": "const", "const": str(value % (1 << width)), "width": width}
        return {"form": "const", "const": raw, "width": width}
    if form == "ref":
        return {"form": "ref", "ref": ast.get("ref")}
    args = [normalize_ast(arg) for arg in ast.get("args", [])]

    if form in {"add", "mul", "and", "or"}:
        flattened = []
        for arg in args:
            if isinstance(arg, dict) and arg.get("form") == form:
                flattened.extend(arg.get("args", []))
            else:
                flattened.append(arg)
        args = flattened
        if form == "add":
            args = [
                arg for arg in args
                if not (
                    isinstance(arg, dict)
                    and arg.get("form") == "const"
                    and int(arg.get("const", "0")) == 0
                )
            ]
        if form == "mul" and any(
            isinstance(arg, dict)
            and arg.get("form") == "const"
            and int(arg.get("const", "0")) == 0
            for arg in args
        ):
            zero = next(
                arg for arg in args
                if isinstance(arg, dict)
                and arg.get("form") == "const"
                and int(arg.get("const", "0")) == 0
            )
            return zero
        if form == "mul":
            args = [
                arg for arg in args
                if not (
                    isinstance(arg, dict)
                    and arg.get("form") == "const"
                    and int(arg.get("const", "0")) == 1
                )
            ]
        if len(args) == 1:
            return args[0]
        args.sort(key=grammar_routes.canonical_json)

    if form == "sub" and len(args) == 2:
        rhs = args[1]
        if (
            isinstance(rhs, dict)
            and rhs.get("form") == "const"
            and int(rhs.get("const", "0")) == 0
        ):
            return args[0]

    inverse = {"uge": "ule", "ugt": "ult", "sge": "sle", "sgt": "slt"}
    if form in inverse and len(args) == 2:
        form = inverse[form]
        args = [args[1], args[0]]
    if form in {"eq", "ne"} and len(args) == 2:
        args.sort(key=grammar_routes.canonical_json)
    normalized = {"form": form, "args": args}
    for field in ("hi", "lo"):
        if field in ast:
            normalized[field] = ast[field]
    return normalized


def semantic_ast_key(ast: dict) -> str:
    return grammar_routes.canonical_json(normalize_ast(ast))


def referenced_states(ast: object) -> tuple[str, ...]:
    refs = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if value.get("form") == "ref":
                ref = value.get("ref")
                if isinstance(ref, str):
                    refs.add(ref)
            for child in value.get("args", []):
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(ast)
    return tuple(sorted(refs, key=lambda ref: (not ref.startswith("state"), ref)))


def route_index_for_refs(
    btor2: str,
    refs: tuple[str, ...],
    state_widths: dict[str, int],
) -> tuple[dict[str, list[tuple[grammar_routes.GrammarRoute, dict]]], list[grammar_routes.GrammarRoute]]:
    variables = []
    for ref in refs:
        if ref not in state_widths:
            raise ValueError(f"candidate uses non-scalar or unknown state ref: {ref}")
        variables.append({"state_ref": ref, "width": state_widths[ref]})
    route_payload = grammar_routes.bounded_exhaustive_route_document(
        variables, max_variables=len(variables)
    )
    routes = grammar_routes.compile_route_document(btor2, route_payload)
    entries = grammar_routes.expand_routes(btor2, routes, cap=50000)
    route_by_id = {route.route_id: route for route in routes}
    index: dict[str, list[tuple[grammar_routes.GrammarRoute, dict]]] = {}
    for entry in entries:
        key = semantic_ast_key(entry["predicate_ast"])
        index.setdefault(key, []).append((route_by_id[entry["route_id"]], entry))
    return index, routes


def audit_benchmark(btor2: Path, predicate_path: Path, benchmark_id: str) -> dict:
    info = parse_btor2(str(btor2))
    state_widths = {
        state.ref: state.width
        for state in info.states
        if not state.is_array and state.width > 0
    }
    entries = candidate_cert_check.load_predicate_entries(str(predicate_path))
    cache = {}
    classifications = []
    chosen_routes: dict[str, grammar_routes.GrammarRoute] = {}
    family_counts = Counter()
    for index, entry in enumerate(entries):
        ast = entry["predicate_ast"]
        refs = referenced_states(ast)
        reason = ""
        matched = []
        if not refs:
            reason = "no-state-reference"
        elif any(not ref.startswith("state") for ref in refs):
            reason = "input-or-nonstate-reference"
        elif len(refs) > 3:
            reason = "more-than-three-state-references"
        elif any(ref not in state_widths for ref in refs):
            reason = "unknown-or-nonscalar-state-reference"
        else:
            if refs not in cache:
                cache[refs] = route_index_for_refs(
                    str(btor2), refs, state_widths
                )[0]
            matched = cache[refs].get(semantic_ast_key(ast), [])
            if not matched:
                reason = "outside-preregistered-bounded-grammar"
        if matched:
            matched.sort(key=lambda pair: (
                FAMILY_ORDER[pair[0].family], pair[0].route_id
            ))
            route = matched[0][0]
            chosen_routes[route.route_id] = route
            family_counts[route.family] += 1
            classifications.append({
                "candidate_index": index,
                "candidate_sha256": grammar_routes.canonical_sha256(ast),
                "state_refs": list(refs),
                "matched": True,
                "family": route.family,
                "route_id": route.route_id,
            })
        else:
            family_counts["unmatched"] += 1
            classifications.append({
                "candidate_index": index,
                "candidate_sha256": grammar_routes.canonical_sha256(ast),
                "state_refs": list(refs),
                "matched": False,
                "reason": reason,
            })

    route_payload = {
        "schema": grammar_routes.ROUTE_SCHEMA,
        "routes": [
            chosen_routes[route_id].semantic_payload()
            for route_id in sorted(chosen_routes)
        ],
    }
    routed_candidate_count = 0
    route_sha256 = ""
    if chosen_routes:
        compiled = grammar_routes.compile_route_document(str(btor2), route_payload)
        routed_candidate_count = len(
            grammar_routes.expand_routes(str(btor2), compiled, cap=50000)
        )
        route_sha256 = grammar_routes.canonical_sha256(route_payload)
    matched_count = sum(row["matched"] for row in classifications)
    return {
        "benchmark_id": benchmark_id,
        "btor2_sha256": file_sha256(btor2),
        "predicate_sha256": file_sha256(predicate_path),
        "candidate_count": len(entries),
        "matched_candidate_count": matched_count,
        "matched_candidate_ratio": (
            f"{matched_count / len(entries):.6f}" if entries else "0.000000"
        ),
        "unique_route_count": len(chosen_routes),
        "routed_expansion_candidate_count": routed_candidate_count,
        "route_sha256": route_sha256,
        "family_counts": dict(sorted(family_counts.items())),
        "routes": route_payload["routes"],
        "classifications": classifications,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_dir")
    parser.add_argument("benchmark_root")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    capture_dir = Path(args.capture_dir).resolve()
    benchmark_root = Path(args.benchmark_root).expanduser().resolve()
    bundle = experiment_manifest.validate_capture_archive(capture_dir)
    records = []
    for benchmark_id, capture in sorted(bundle["records"].items()):
        btor2 = benchmark_root / benchmark_id
        if not btor2.is_file():
            raise ValueError(f"missing frozen benchmark: {btor2}")
        actual = file_sha256(btor2)
        if actual != capture["content_sha256"]:
            raise ValueError(
                f"benchmark/capture hash mismatch for {benchmark_id}: "
                f"expected {capture['content_sha256']}, got {actual}"
            )
        records.append(audit_benchmark(
            btor2, capture["predicate_path"], benchmark_id
        ))
    totals = Counter()
    families = Counter()
    for record in records:
        totals["candidate_count"] += record["candidate_count"]
        totals["matched_candidate_count"] += record["matched_candidate_count"]
        totals["unique_route_count"] += record["unique_route_count"]
        totals["routed_expansion_candidate_count"] += record[
            "routed_expansion_candidate_count"
        ]
        families.update(record["family_counts"])
    candidate_count = totals["candidate_count"]
    report = {
        "schema": AUDIT_SCHEMA,
        "capture_manifest_sha256": bundle["manifest_sha256"],
        "capture_integrity_sha256": bundle["integrity_sha256"],
        "benchmark_count": len(records),
        "candidate_count": candidate_count,
        "matched_candidate_count": totals["matched_candidate_count"],
        "matched_candidate_ratio": (
            f"{totals['matched_candidate_count'] / candidate_count:.6f}"
            if candidate_count else "0.000000"
        ),
        "unique_route_count_sum": totals["unique_route_count"],
        "routed_expansion_candidate_count_sum": totals[
            "routed_expansion_candidate_count"
        ],
        "family_counts": dict(sorted(families.items())),
        "records": records,
    }
    report["report_sha256"] = build_paired_corpus.canonical_sha256({
        key: value for key, value in report.items() if key != "report_sha256"
    })
    output = Path(args.out)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite frozen route audit: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "benchmark_count": report["benchmark_count"],
        "candidate_count": report["candidate_count"],
        "matched_candidate_count": report["matched_candidate_count"],
        "matched_candidate_ratio": report["matched_candidate_ratio"],
        "family_counts": report["family_counts"],
        "report_sha256": report["report_sha256"],
        "output": output.as_posix(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
