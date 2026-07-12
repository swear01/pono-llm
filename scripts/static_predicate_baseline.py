#!/usr/bin/env python3
"""Deterministic affine/template and ranked predicate generators.

This is the non-LLM baseline for Phase 2. It emits predicate-AST JSON lines in
exactly the format accepted by `pono --initial-predicates`.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections.abc import Iterator
from math import gcd
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT_DIR / "llm_worker"))

from btor2_reader import hot_refs_near_bad, parse_btor2  # noqa: E402
from invariant_arith import detect_software_origin, get_software_vars  # noqa: E402

COEFFS = tuple(range(-4, 5))
PAIR_CONSTS = (0, 1, -1, 2, -2, 3, -3, 4, -4)
FAMILY_ORDER = ("unary", "pairwise", "affine2", "affine3")


def ref_ast(ref: str) -> dict:
    return {"form": "ref", "ref": ref}


def const_ast(value: int, width: int) -> dict:
    return {"form": "const", "const": str(value), "width": width}


def term_times(coeff: int, ref: str, width: int) -> dict:
    if abs(coeff) == 1:
        return ref_ast(ref)
    return {"form": "mul", "args": [const_ast(abs(coeff), width), ref_ast(ref)]}


def add_terms(terms: list[dict], width: int) -> dict:
    if not terms:
        return const_ast(0, width)
    cur = terms[0]
    for t in terms[1:]:
        cur = {"form": "add", "args": [cur, t]}
    return cur


def affine_sides(
    items: list[tuple[int, str]], width: int
) -> tuple[dict, dict] | None:
    positive = [term_times(coeff, ref, width) for coeff, ref in items if coeff > 0]
    negative = [term_times(coeff, ref, width) for coeff, ref in items if coeff < 0]
    if not positive or not negative:
        return None
    return add_terms(positive, width), add_terms(negative, width)


def normalize_coeffs(coeffs: tuple[int, ...]) -> tuple[int, ...] | None:
    if all(c == 0 for c in coeffs):
        return None
    g = 0
    for c in coeffs:
        g = gcd(g, abs(c))
    if g > 1:
        coeffs = tuple(c // g for c in coeffs)
    first = next(c for c in coeffs if c != 0)
    if first < 0:
        coeffs = tuple(-c for c in coeffs)
    return coeffs


def scalar_vars(info, max_vars: int) -> list[tuple[str, int]]:
    by_ref = {sv.ref: sv for sv in info.states if sv.width > 0}
    software = [sv.ref for sv in get_software_vars(info) if sv.ref in by_ref]
    software_set = set(software)
    hot = [
        ref
        for ref in hot_refs_near_bad(info, depth=4, transition_depth=6)
        if ref in by_ref and ref not in software_set
    ]
    selected = software_set | set(hot)
    rest = [
        state.ref
        for state in info.states
        if state.ref in by_ref and state.ref not in selected
    ]
    refs = (software + hot + rest)[:max_vars]
    return [(r, by_ref[r].width) for r in refs]


def candidate_key(ast: dict) -> str:
    return json.dumps(ast, sort_keys=True, separators=(",", ":"))


def _additive_terms(ast: dict) -> list[dict]:
    if ast.get("form") != "add":
        return [ast]
    terms: list[dict] = []
    for arg in ast.get("args", []):
        terms.extend(_additive_terms(arg))
    return terms


def abstraction_closure(entries: list[dict]) -> list[dict]:
    """Add deterministic projection predicates for selected affine equalities."""
    seen = {
        candidate_key(entry["predicate_ast"])
        for entry in entries
        if isinstance(entry.get("predicate_ast"), dict)
    }
    closure: list[dict] = []
    for entry in entries:
        ast = entry.get("predicate_ast", {})
        args = ast.get("args", [])
        if ast.get("form") != "eq" or len(args) != 2:
            continue
        lhs, rhs = args
        lhs_terms = _additive_terms(lhs)
        rhs_terms = _additive_terms(rhs)
        projections = []
        if len(lhs_terms) > 1:
            projections.extend((term, rhs) for term in lhs_terms)
        if len(rhs_terms) > 1:
            projections.extend((term, lhs) for term in rhs_terms)
        for term, bound in projections:
            candidate = {"form": "ule", "args": [term, bound]}
            key = candidate_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            closure.append({
                "predicate_ast": candidate,
                "template_family": "affine_projection",
            })
    return closure


def state_initial_values(info) -> dict[str, int]:
    values: dict[str, int] = {}
    for state in info.states:
        raw = state.init_value
        if not raw:
            continue
        try:
            if raw.startswith("#b"):
                value = int(raw[2:], 2)
            elif raw.startswith("#x"):
                value = int(raw[2:], 16)
            else:
                value = int(raw, 10)
        except ValueError:
            continue
        values[state.ref] = value
    return values


def unary_candidates(
    vars_: list[tuple[str, int]], init_values: dict[str, int]
) -> Iterator[dict]:
    for x, wx in vars_:
        if x not in init_values:
            continue
        k = const_ast(init_values[x] % (1 << wx), wx)
        yield {"form": "eq", "args": [ref_ast(x), k]}
        yield {"form": "ule", "args": [ref_ast(x), k]}
        yield {"form": "uge", "args": [ref_ast(x), k]}
    for c in range(9):
        for x, wx in vars_:
            if init_values.get(x) == c:
                continue
            if c >= (1 << wx):
                continue
            k = const_ast(c, wx)
            yield {"form": "eq", "args": [ref_ast(x), k]}
            yield {"form": "ule", "args": [ref_ast(x), k]}
            yield {"form": "uge", "args": [ref_ast(x), k]}


def pairwise_candidates(vars_: list[tuple[str, int]]) -> Iterator[dict]:
    pairs = [
        ((x, wx), (y, wy))
        for (x, wx), (y, wy) in itertools.permutations(vars_, 2)
        if wx == wy
    ]
    for c in PAIR_CONSTS:
        for (x, wx), (y, _) in pairs:
            y_plus_c = {
                "form": "add",
                "args": [ref_ast(y), const_ast(c % (1 << wx), wx)],
            }
            yield {"form": "eq", "args": [ref_ast(x), y_plus_c]}
            yield {"form": "ule", "args": [ref_ast(x), y_plus_c]}
            yield {"form": "uge", "args": [ref_ast(x), y_plus_c]}


def ranked_relational_candidates(
    vars_: list[tuple[str, int]],
) -> Iterator[dict]:
    pairs = [
        ((x, wx), (y, wy))
        for (x, wx), (y, wy) in itertools.permutations(vars_, 2)
        if wx == wy
    ]
    for (x, _), (y, _) in pairs:
        yield {"form": "ule", "args": [ref_ast(x), ref_ast(y)]}

    for triple in itertools.combinations(vars_, 3):
        if len({width for _, width in triple}) != 1:
            continue
        for result_index in range(3):
            result, _ = triple[result_index]
            operands = [
                ref_ast(ref)
                for index, (ref, _) in enumerate(triple)
                if index != result_index
            ]
            yield {
                "form": "eq",
                "args": [
                    {"form": "add", "args": operands},
                    ref_ast(result),
                ],
            }


def coefficient_patterns(nvars: int) -> list[tuple[int, ...]]:
    patterns = {
        normalize_coeffs(coeffs)
        for coeffs in itertools.product(COEFFS, repeat=nvars)
        if all(coeff != 0 for coeff in coeffs)
    }
    return sorted(
        (pattern for pattern in patterns if pattern),
        key=lambda pattern: (
            sum(abs(value) for value in pattern),
            max(abs(value) for value in pattern),
            pattern,
        ),
    )


def affine_candidates(
    vars_: list[tuple[str, int]], nvars: int
) -> Iterator[dict]:
    combos = [
        combo
        for combo in itertools.combinations(vars_, nvars)
        if len({width for _, width in combo}) == 1
    ]
    for coeffs in coefficient_patterns(nvars):
        for combo in combos:
            refs = [ref for ref, _ in combo]
            width = combo[0][1]
            sides = affine_sides(list(zip(coeffs, refs)), width)
            if sides is None:
                continue
            lhs, rhs = sides
            yield {"form": "eq", "args": [lhs, rhs]}
            yield {"form": "ule", "args": [lhs, rhs]}
            yield {"form": "uge", "args": [lhs, rhs]}


def quadratic_candidates(vars_: list[tuple[str, int]]) -> Iterator[dict]:
    pairs = [
        ((accumulator, width), counter)
        for (accumulator, width), (counter, counter_width)
        in itertools.permutations(vars_, 2)
        if width == counter_width
    ]
    for (accumulator, width), counter in pairs:
        for scale in (2, 1, 3, 4):
            lhs = term_times(scale, accumulator, width)
            for delta in (-1, 0, 1):
                if delta == 0:
                    shifted = ref_ast(counter)
                elif delta < 0:
                    shifted = {
                        "form": "sub",
                        "args": [ref_ast(counter), const_ast(1, width)],
                    }
                else:
                    shifted = {
                        "form": "add",
                        "args": [ref_ast(counter), const_ast(1, width)],
                    }
                product = {
                    "form": "mul",
                    "args": [ref_ast(counter), shifted],
                }
                yield {"form": "eq", "args": [lhs, product]}
                yield {"form": "ule", "args": [lhs, product]}
                yield {"form": "uge", "args": [lhs, product]}


def generate_entries(
    path: str, max_vars: int = 8, cap: int = 200
) -> list[dict]:
    if max_vars <= 0:
        raise ValueError("max_vars must be positive")
    if cap <= 0:
        raise ValueError("cap must be positive")
    info = parse_btor2(path)
    vars_ = scalar_vars(info, max_vars)
    generators: dict[str, Iterator[dict]] = {
        "unary": unary_candidates(vars_, state_initial_values(info)),
        "pairwise": pairwise_candidates(vars_),
        "affine2": affine_candidates(vars_, 2),
        "affine3": affine_candidates(vars_, 3),
    }
    active = list(FAMILY_ORDER)
    seen: set[str] = set()
    entries: list[dict] = []

    while active and len(entries) < cap:
        next_active: list[str] = []
        for family in active:
            generator = generators[family]
            while True:
                try:
                    ast = next(generator)
                except StopIteration:
                    break
                key = candidate_key(ast)
                if key in seen:
                    continue
                seen.add(key)
                entries.append({
                    "predicate_ast": ast,
                    "template_family": family,
                })
                next_active.append(family)
                break
            if len(entries) >= cap:
                break
        active = next_active
    return entries


def generate(path: str, max_vars: int = 8, cap: int = 200) -> list[dict]:
    return [
        entry["predicate_ast"]
        for entry in generate_entries(path, max_vars=max_vars, cap=cap)
    ]


def generate_ranked_entries(path: str, cap: int = 20) -> list[dict]:
    if cap <= 0:
        raise ValueError("cap must be positive")
    info = parse_btor2(path)
    clean = [
        (state.ref, state.width)
        for state in get_software_vars(info)
        if state.width > 0
    ][:8]
    vars_ = clean if len(clean) >= 2 else scalar_vars(info, max_vars=8)
    seen: set[str] = set()
    entries: list[dict] = []
    for ast in ranked_relational_candidates(vars_):
        key = candidate_key(ast)
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            "predicate_ast": ast,
            "template_family": (
                "ranked_pairwise_order"
                if ast["form"] == "ule"
                else "ranked_sum_equality"
            ),
        })
        if len(entries) >= cap:
            break
    return entries


def generate_quadratic_entries(
    path: str, max_vars: int = 8, cap: int = 2000
) -> list[dict]:
    if max_vars <= 0:
        raise ValueError("max_vars must be positive")
    if cap <= 0:
        raise ValueError("cap must be positive")
    info = parse_btor2(path)
    vars_ = scalar_vars(info, max_vars)
    seen: set[str] = set()
    entries: list[dict] = []
    for ast in quadratic_candidates(vars_):
        key = candidate_key(ast)
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            "predicate_ast": ast,
            "template_family": "quadratic",
        })
        if len(entries) >= cap:
            break
    return entries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("btor2")
    ap.add_argument("--out", help="Write JSONL to file instead of stdout")
    ap.add_argument("--max-vars", type=int, default=8)
    ap.add_argument("--cap", type=int, default=200)
    ap.add_argument("--require-software", action="store_true")
    args = ap.parse_args()

    info = parse_btor2(args.btor2)
    if args.require_software and not detect_software_origin(info):
        entries: list[dict] = []
    else:
        entries = generate_entries(
            args.btor2, max_vars=args.max_vars, cap=args.cap
        )
    text = "\n".join(json.dumps(entry, sort_keys=True) for entry in entries)
    if args.out:
        Path(args.out).write_text(text)
    else:
        if text:
            print(text)
    family_counts = {
        family: sum(
            entry.get("template_family") == family for entry in entries
        )
        for family in FAMILY_ORDER
    }
    print(json.dumps({
        "path": args.btor2,
        "n_candidates": len(entries),
        "family_counts": family_counts,
    }, sort_keys=True), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
