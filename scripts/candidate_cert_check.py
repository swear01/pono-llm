#!/usr/bin/env python3
"""Direct C1/C2/C3 checker for predicate-AST conjunctions.

The checker evaluates predicates on the original unconstrained BTOR2 model.
Its AST semantics intentionally match ``build_predicate_term`` in
``engines/ic3_frame_ast.cpp``: boolean connectives are logical, bit-vector
operators require equal widths, and no implicit extension is inserted.

Default mode checks the conjunction exactly as supplied. ``--houdini`` removes
candidates falsified by an initial state or an inductiveness counterexample,
then checks whether the remaining conjunction implies every BAD property.
Only C1/C2/C3 all UNSAT is a certificate.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import z3

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import cert_check  # noqa: E402


def _normalise_entry(item: object, location: str) -> dict:
    if not isinstance(item, dict) or not isinstance(item.get("predicate_ast"), dict):
        raise ValueError(f"{location} does not contain predicate_ast")
    return item


def load_predicate_entries(path: str) -> list[dict]:
    text = Path(path).read_text().strip()
    if not text:
        return []

    if text[0] in "[{":
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, list):
            return [_normalise_entry(item, f"item {i}") for i, item in enumerate(obj)]
        if isinstance(obj, dict):
            if obj.get("predicate_ast"):
                return [_normalise_entry(obj, "object")]
            if isinstance(obj.get("candidates"), list):
                return [
                    _normalise_entry(item, f"candidate {i}")
                    for i, item in enumerate(obj["candidates"])
                ]

    entries: list[dict] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        value = line.strip()
        if not value:
            continue
        try:
            obj = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on line {lineno}: {exc}") from exc
        entries.append(_normalise_entry(obj, f"line {lineno}"))
    return entries


def load_predicate_asts(path: str) -> list[dict]:
    return [entry["predicate_ast"] for entry in load_predicate_entries(path)]


def is_bool(expr) -> bool:
    return z3.is_bool(expr)


def is_bv(expr) -> bool:
    return z3.is_bv(expr)


def to_bool(expr):
    if is_bool(expr):
        return expr
    if is_bv(expr) and expr.size() == 1:
        return expr == z3.BitVecVal(1, 1)
    width = expr.size() if is_bv(expr) else "n/a"
    raise TypeError(f"cannot coerce non-boolean expression (width={width})")


def require_bv(expr, form: str):
    if not is_bv(expr):
        raise TypeError(f"{form} requires bit-vector operands")
    return expr


def require_same_bv(lhs, rhs, form: str):
    require_bv(lhs, form)
    require_bv(rhs, form)
    if lhs.size() != rhs.size():
        raise TypeError(
            f"{form} requires equal bit-vector widths, got {lhs.size()} and {rhs.size()}"
        )
    return lhs, rhs


def require_same_sort(lhs, rhs, form: str):
    if is_bool(lhs) and is_bool(rhs):
        return lhs, rhs
    return require_same_bv(lhs, rhs, form)


def ref_expr(ref: str, model, statevars, inputvars):
    match = re.fullmatch(r"state(\d+)", ref)
    if match:
        lineno = int(match.group(1))
        if lineno not in statevars:
            raise KeyError(f"unknown state ref {ref}")
        return statevars[lineno]
    match = re.fullmatch(r"input(\d+)", ref)
    if match:
        lineno = int(match.group(1))
        if lineno not in inputvars:
            op, args = model["nodes"].get(lineno, (None, []))
            if op != "input":
                raise KeyError(f"unknown input ref {ref}")
            inputvars[lineno] = z3.BitVec(ref, model["sorts"][args[0]])
        return inputvars[lineno]
    raise KeyError(f"unsupported ref {ref!r}; expected stateN/inputN")


def const_expr(ast: dict):
    width = int(ast.get("width", 0))
    raw = str(ast.get("const", ""))
    if width == 0:
        if raw in {"true", "1"}:
            return z3.BoolVal(True)
        if raw in {"false", "0"}:
            return z3.BoolVal(False)
        raise ValueError(f"invalid boolean constant: {raw!r}")
    if width < 0:
        raise ValueError(f"constant width must be non-negative: {width}")
    if raw.startswith("#b"):
        value = int(raw[2:], 2)
    elif raw.startswith("#x"):
        value = int(raw[2:], 16)
    else:
        value = int(raw, 10)
    return z3.BitVecVal(value % (1 << width), width)


def ast_to_z3(ast: dict, model, statevars, inputvars):
    form = ast.get("form")
    if form == "ref":
        return ref_expr(ast.get("ref", ""), model, statevars, inputvars)
    if form == "const":
        return const_expr(ast)

    args = ast.get("args", [])
    if not isinstance(args, list):
        raise ValueError(f"{form} args must be a list")

    if form in {"add", "sub", "mul"}:
        if not args:
            raise ValueError(f"{form} needs at least 1 arg")
        current = require_bv(ast_to_z3(args[0], model, statevars, inputvars), form)
        if len(args) == 1:
            return -current if form == "sub" else current
        for arg in args[1:]:
            nxt = ast_to_z3(arg, model, statevars, inputvars)
            current, nxt = require_same_bv(current, nxt, form)
            if form == "add":
                current = current + nxt
            elif form == "sub":
                current = current - nxt
            else:
                current = current * nxt
        return current

    if form in {"and", "or"}:
        if not args:
            raise ValueError(f"{form} needs args")
        children = [
            to_bool(ast_to_z3(arg, model, statevars, inputvars)) for arg in args
        ]
        return z3.And(*children) if form == "and" else z3.Or(*children)

    if form == "not":
        if len(args) != 1:
            raise ValueError("not needs 1 arg")
        return z3.Not(to_bool(ast_to_z3(args[0], model, statevars, inputvars)))

    if form == "implies":
        if len(args) != 2:
            raise ValueError("implies needs 2 args")
        lhs = to_bool(ast_to_z3(args[0], model, statevars, inputvars))
        rhs = to_bool(ast_to_z3(args[1], model, statevars, inputvars))
        return z3.Implies(lhs, rhs)

    if form in {"bvand", "bvor", "bvxor"}:
        if len(args) != 2:
            raise ValueError(f"{form} needs 2 args")
        lhs = ast_to_z3(args[0], model, statevars, inputvars)
        rhs = ast_to_z3(args[1], model, statevars, inputvars)
        lhs, rhs = require_same_bv(lhs, rhs, form)
        if form == "bvand":
            return lhs & rhs
        if form == "bvor":
            return lhs | rhs
        return lhs ^ rhs

    if form == "bvnot":
        if len(args) != 1:
            raise ValueError("bvnot needs 1 arg")
        return ~require_bv(
            ast_to_z3(args[0], model, statevars, inputvars), form
        )

    if form in {"eq", "ne"}:
        if len(args) != 2:
            raise ValueError(f"{form} needs 2 args")
        lhs = ast_to_z3(args[0], model, statevars, inputvars)
        rhs = ast_to_z3(args[1], model, statevars, inputvars)
        lhs, rhs = require_same_sort(lhs, rhs, form)
        return lhs == rhs if form == "eq" else lhs != rhs

    if form in {"ult", "ule", "ugt", "uge", "slt", "sle", "sgt", "sge"}:
        if len(args) != 2:
            raise ValueError(f"{form} needs 2 args")
        lhs = ast_to_z3(args[0], model, statevars, inputvars)
        rhs = ast_to_z3(args[1], model, statevars, inputvars)
        lhs, rhs = require_same_bv(lhs, rhs, form)
        if form == "ult":
            return z3.ULT(lhs, rhs)
        if form == "ule":
            return z3.ULE(lhs, rhs)
        if form == "ugt":
            return z3.UGT(lhs, rhs)
        if form == "uge":
            return z3.UGE(lhs, rhs)
        if form == "slt":
            return lhs < rhs
        if form == "sle":
            return lhs <= rhs
        if form == "sgt":
            return lhs > rhs
        return lhs >= rhs

    if form == "concat":
        if len(args) < 2:
            raise ValueError("concat needs 2 or more args")
        children = [
            require_bv(ast_to_z3(arg, model, statevars, inputvars), form)
            for arg in args
        ]
        return z3.Concat(*children)

    if form == "extract":
        if len(args) != 1:
            raise ValueError("extract needs 1 arg")
        child = require_bv(
            ast_to_z3(args[0], model, statevars, inputvars), form
        )
        hi = int(ast.get("hi", 0))
        lo = int(ast.get("lo", 0))
        if lo < 0 or hi < lo or hi >= child.size():
            raise ValueError(
                f"invalid extract [{hi}:{lo}] for width {child.size()}"
            )
        return z3.Extract(hi, lo, child)

    raise ValueError(f"unsupported predicate_ast form: {form}")


def build_base_formulas(orig_path: str):
    model = cert_check.parse_btor2(orig_path)
    if not model["bads"]:
        raise ValueError("BTOR2 model contains no bad property")
    statevars = {
        lineno: z3.BitVec(f"state{lineno}", cert_check.width_of(model, lineno))
        for lineno in model["states"]
    }
    inputvars = {
        lineno: z3.BitVec(f"input{lineno}", model["sorts"][args[0]])
        for lineno, (op, args) in model["nodes"].items()
        if op == "input"
    }
    cache = {}

    init_terms = []
    for state_lineno, value_lineno in model["inits"].items():
        value = cert_check.build(
            model, value_lineno, statevars, inputvars, cache
        )
        init_terms.append(statevars[state_lineno] == value)
    init = z3.And(*init_terms) if init_terms else z3.BoolVal(True)

    constraint_terms = [
        cert_check.build(model, node, statevars, inputvars, cache) == 1
        for node in model["constraints"]
    ]
    constraints = (
        z3.And(*constraint_terms) if constraint_terms else z3.BoolVal(True)
    )
    bad = z3.Or(*[
        cert_check.build(model, node, statevars, inputvars, cache) == 1
        for node in model["bads"]
    ])

    next_expr = {}
    for state_lineno in model["states"]:
        if state_lineno in model["nexts"]:
            next_expr[state_lineno] = cert_check.build(
                model,
                model["nexts"][state_lineno],
                statevars,
                inputvars,
                cache,
            )
        else:
            next_expr[state_lineno] = statevars[state_lineno]
    input_next = {
        lineno: z3.BitVec(f"input{lineno}_n", value.size())
        for lineno, value in inputvars.items()
    }
    substitutions = (
        [(statevars[line], next_expr[line]) for line in model["states"]]
        + [(inputvars[line], input_next[line]) for line in inputvars]
    )
    constraints_next = z3.substitute(constraints, *substitutions)
    return {
        "model": model,
        "statevars": statevars,
        "inputvars": inputvars,
        "init": init,
        "constraints": constraints,
        "constraints_next": constraints_next,
        "bad": bad,
        "substitutions": substitutions,
    }


def compile_asts(asts: list[dict], base: dict) -> list:
    if not asts:
        raise ValueError("no predicate_ast entries to certify")
    return [
        to_bool(
            ast_to_z3(
                ast,
                base["model"],
                base["statevars"],
                base["inputvars"],
            )
        )
        for ast in asts
    ]


def solve_formula(formula, timeout_ms: int):
    solver = z3.Solver()
    solver.set("timeout", timeout_ms)
    solver.add(formula)
    return solver, solver.check()


def certify(orig_path: str, asts: list[dict], timeout_ms: int):
    base = build_base_formulas(orig_path)
    predicates = compile_asts(asts, base)
    invariant = z3.And(*predicates)
    invariant_next = z3.substitute(invariant, *base["substitutions"])
    checks = [
        (
            "C1 Init=>H",
            z3.And(
                base["init"], base["constraints"], z3.Not(invariant)
            ),
        ),
        (
            "C2 inductive",
            z3.And(
                invariant,
                base["constraints"],
                base["constraints_next"],
                z3.Not(invariant_next),
            ),
        ),
        (
            "C3 H=>notBAD",
            z3.And(invariant, base["constraints"], base["bad"]),
        ),
    ]
    return [
        (name, solve_formula(formula, timeout_ms)[1])
        for name, formula in checks
    ]


def _conjunction(expressions: list, active: list[int]):
    if not active:
        return z3.BoolVal(True)
    return z3.And(*[expressions[index] for index in active])


def _false_in_model(expressions: list, active: list[int], model) -> list[int]:
    return [
        index
        for index in active
        if z3.is_false(model.eval(expressions[index], model_completion=True))
    ]


def _houdini_certify_strict(
    orig_path: str, asts: list[dict], timeout_ms: int
) -> dict:
    deadline = time.monotonic() + timeout_ms / 1000.0

    def remaining_timeout_ms() -> int | None:
        remaining = int((deadline - time.monotonic()) * 1000)
        return remaining if remaining > 0 else None

    base = build_base_formulas(orig_path)
    predicates = compile_asts(asts, base)
    predicates_next = [
        z3.substitute(predicate, *base["substitutions"])
        for predicate in predicates
    ]
    active = list(range(len(predicates)))
    removed_initial: list[int] = []
    removed_step: list[int] = []
    init_queries = 0
    step_queries = 0

    while True:
        remaining = remaining_timeout_ms()
        if remaining is None:
            return {
                "ok": False,
                "checks": [
                    {"name": "C1 Init=>H", "result": "unknown"},
                    {"name": "C2 inductive", "result": "not-run"},
                    {"name": "C3 H=>notBAD", "result": "not-run"},
                ],
                "selected_indices": active,
                "removed_initial_indices": removed_initial,
                "removed_step_indices": removed_step,
                "init_queries": init_queries,
                "step_queries": step_queries,
                "timeout_phase": "C1",
            }
        invariant = _conjunction(predicates, active)
        solver, result = solve_formula(
            z3.And(base["init"], base["constraints"], z3.Not(invariant)),
            remaining,
        )
        init_queries += 1
        if result == z3.unsat:
            c1 = result
            break
        if result == z3.unknown:
            return {
                "ok": False,
                "checks": [
                    {"name": "C1 Init=>H", "result": "unknown"},
                    {"name": "C2 inductive", "result": "not-run"},
                    {"name": "C3 H=>notBAD", "result": "not-run"},
                ],
                "selected_indices": active,
                "removed_initial_indices": removed_initial,
                "removed_step_indices": removed_step,
                "init_queries": init_queries,
                "step_queries": step_queries,
                "timeout_phase": "C1",
            }
        rejected = _false_in_model(predicates, active, solver.model())
        if not rejected:
            raise RuntimeError("C1 counterexample did not falsify an active candidate")
        rejected_set = set(rejected)
        removed_initial.extend(rejected)
        active = [index for index in active if index not in rejected_set]

    while True:
        remaining = remaining_timeout_ms()
        if remaining is None:
            return {
                "ok": False,
                "checks": [
                    {"name": "C1 Init=>H", "result": str(c1)},
                    {"name": "C2 inductive", "result": "unknown"},
                    {"name": "C3 H=>notBAD", "result": "not-run"},
                ],
                "selected_indices": active,
                "removed_initial_indices": removed_initial,
                "removed_step_indices": removed_step,
                "init_queries": init_queries,
                "step_queries": step_queries,
                "timeout_phase": "C2",
            }
        invariant = _conjunction(predicates, active)
        invariant_next = _conjunction(predicates_next, active)
        solver, result = solve_formula(
            z3.And(
                invariant,
                base["constraints"],
                base["constraints_next"],
                z3.Not(invariant_next),
            ),
            remaining,
        )
        step_queries += 1
        if result == z3.unsat:
            c2 = result
            break
        if result == z3.unknown:
            return {
                "ok": False,
                "checks": [
                    {"name": "C1 Init=>H", "result": str(c1)},
                    {"name": "C2 inductive", "result": "unknown"},
                    {"name": "C3 H=>notBAD", "result": "not-run"},
                ],
                "selected_indices": active,
                "removed_initial_indices": removed_initial,
                "removed_step_indices": removed_step,
                "init_queries": init_queries,
                "step_queries": step_queries,
                "timeout_phase": "C2",
            }
        rejected = _false_in_model(predicates_next, active, solver.model())
        if not rejected:
            raise RuntimeError("C2 counterexample did not falsify an active candidate")
        rejected_set = set(rejected)
        removed_step.extend(rejected)
        active = [index for index in active if index not in rejected_set]

    invariant = _conjunction(predicates, active)
    remaining = remaining_timeout_ms()
    if remaining is None:
        c3 = z3.unknown
    else:
        _, c3 = solve_formula(
            z3.And(invariant, base["constraints"], base["bad"]), remaining
        )
    checks = [
        {"name": "C1 Init=>H", "result": str(c1)},
        {"name": "C2 inductive", "result": str(c2)},
        {"name": "C3 H=>notBAD", "result": str(c3)},
    ]
    return {
        "ok": c1 == z3.unsat and c2 == z3.unsat and c3 == z3.unsat,
        "checks": checks,
        "selected_indices": active,
        "removed_initial_indices": removed_initial,
        "removed_step_indices": removed_step,
        "init_queries": init_queries,
        "step_queries": step_queries,
    }


def filter_supported_asts(orig_path: str, asts: list[dict]) -> tuple[list[int], list[dict]]:
    base = build_base_formulas(orig_path)
    supported_indices: list[int] = []
    unsupported_candidates: list[dict] = []
    for index, ast in enumerate(asts):
        try:
            compile_asts([ast], base)
        except (ValueError, KeyError, TypeError, NotImplementedError, z3.Z3Exception) as exc:
            unsupported_candidates.append({"index": index, "error": str(exc)})
            continue
        supported_indices.append(index)
    return supported_indices, unsupported_candidates


def houdini_certify(orig_path: str, asts: list[dict], timeout_ms: int) -> dict:
    validation_start = time.monotonic()
    original_indices, unsupported_candidates = filter_supported_asts(
        orig_path, asts
    )
    supported_asts = [asts[index] for index in original_indices]

    if not supported_asts:
        return {
            "ok": False,
            "checks": [
                {"name": "C1 Init=>H", "result": "not-run"},
                {"name": "C2 inductive", "result": "not-run"},
                {"name": "C3 H=>notBAD", "result": "not-run"},
            ],
            "selected_indices": [],
            "removed_initial_indices": [],
            "removed_step_indices": [],
            "init_queries": 0,
            "step_queries": 0,
            "unsupported_candidates": unsupported_candidates,
            "error": "no supported predicate_ast candidates",
        }

    validation_ms = int((time.monotonic() - validation_start) * 1000)
    remaining_ms = timeout_ms - validation_ms
    if remaining_ms <= 0:
        return {
            "ok": False,
            "checks": [
                {"name": "C1 Init=>H", "result": "unknown"},
                {"name": "C2 inductive", "result": "not-run"},
                {"name": "C3 H=>notBAD", "result": "not-run"},
            ],
            "selected_indices": original_indices,
            "removed_initial_indices": [],
            "removed_step_indices": [],
            "init_queries": 0,
            "step_queries": 0,
            "unsupported_candidates": unsupported_candidates,
            "timeout_phase": "validation",
        }

    report = _houdini_certify_strict(orig_path, supported_asts, remaining_ms)
    for key in (
        "selected_indices",
        "removed_initial_indices",
        "removed_step_indices",
    ):
        report[key] = [original_indices[index] for index in report[key]]
    report["unsupported_candidates"] = unsupported_candidates
    return report


def write_selected(path: str, entries: list[dict], indices: list[int]) -> None:
    text = "\n".join(json.dumps(entries[index], sort_keys=True) for index in indices)
    Path(path).write_text(text + ("\n" if text else ""))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("btor2")
    parser.add_argument("predicates")
    parser.add_argument("--timeout-ms", type=int, default=20000)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--houdini", action="store_true")
    parser.add_argument("--emit-selected")
    args = parser.parse_args()
    if args.timeout_ms <= 0:
        parser.error("--timeout-ms must be positive")

    try:
        entries = load_predicate_entries(args.predicates)
        asts = [entry["predicate_ast"] for entry in entries]
        if args.houdini:
            report = houdini_certify(args.btor2, asts, args.timeout_ms)
            report.update({
                "btor2": args.btor2,
                "predicates": args.predicates,
                "n_predicates": len(asts),
                "n_selected": len(report["selected_indices"]),
                "mode": "houdini",
            })
        else:
            results = certify(args.btor2, asts, args.timeout_ms)
            report = {
                "btor2": args.btor2,
                "predicates": args.predicates,
                "n_predicates": len(asts),
                "n_selected": len(asts),
                "selected_indices": list(range(len(asts))),
                "mode": "conjunction",
                "ok": all(result == z3.unsat for _, result in results),
                "checks": [
                    {"name": name, "result": str(result)}
                    for name, result in results
                ],
            }
    except (ValueError, KeyError, TypeError, NotImplementedError, z3.Z3Exception) as exc:
        report = {
            "btor2": args.btor2,
            "predicates": args.predicates,
            "n_predicates": len(entries) if "entries" in locals() else 0,
            "ok": False,
            "error": str(exc),
            "mode": "houdini" if args.houdini else "conjunction",
        }
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.emit_selected:
        write_selected(args.emit_selected, entries, report["selected_indices"])

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"原始電路: {args.btor2}")
        print(f"模式: {report['mode']}")
        print(
            f"候選 predicates: {report['n_predicates']} "
            f"(selected={report['n_selected']})"
        )
        print("-" * 60)
        for check in report["checks"]:
            result = check["result"]
            verdict = (
                "✓ UNSAT"
                if result == "unsat"
                else ("✗ SAT" if result == "sat" else f"? {result}")
            )
            print(f"  {check['name']:<16} {verdict}")
        print("-" * 60)
        print("結論:", "✅ CERTIFIED" if report["ok"] else "❌ REJECT/UNKNOWN")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
