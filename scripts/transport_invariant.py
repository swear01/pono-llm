#!/usr/bin/env python3
"""Canonical invariant conversion, substitution, and exact certification."""
from __future__ import annotations

import itertools
import re
import sys
import time
from pathlib import Path

import z3

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import candidate_cert_check  # noqa: E402
import cert_check  # noqa: E402
import transport_schema  # noqa: E402


_STATE_REF = re.compile(r"state(\d+)")
_INPUT_REF = re.compile(r"input(\d+)")

_Z3_FORM = {
    "=": "eq",
    "=>": "implies",
    "and": "and",
    "bvadd": "add",
    "bvand": "bvand",
    "bvashr": "sra",
    "bvcomp": "bvcomp",
    "bvlshr": "srl",
    "bvmul": "mul",
    "bvor": "bvor",
    "bvsdiv": "sdiv",
    "bvsge": "sge",
    "bvsgt": "sgt",
    "bvshl": "sll",
    "bvsle": "sle",
    "bvslt": "slt",
    "bvsrem": "srem",
    "bvsub": "sub",
    "bvudiv": "udiv",
    "bvuge": "uge",
    "bvugt": "ugt",
    "bvule": "ule",
    "bvult": "ult",
    "bvurem": "urem",
    "bvxor": "bvxor",
    "concat": "concat",
    "if": "ite",
    "not": "not",
    "or": "or",
    "xor": "xor",
}
_ASSOCIATIVE_Z3 = {"and", "or", "bvadd", "bvmul", "concat"}


def ast_refs(ast: dict) -> set[str]:
    normalized = transport_schema.normalize_ast(ast)
    refs = set()
    stack = [normalized]
    while stack:
        node = stack.pop()
        if node["form"] == "ref":
            refs.add(node["ref"])
        stack.extend(node.get("args", []))
    return refs


def ast_node_count(ast: dict) -> int:
    normalized = transport_schema.normalize_ast(ast)
    count = 0
    stack = [normalized]
    while stack:
        node = stack.pop()
        count += 1
        stack.extend(node.get("args", []))
    return count


def predicate_node_count(predicates: list[dict]) -> int:
    return sum(ast_node_count(predicate) for predicate in predicates)


def substitute_ast(ast: dict, substitutions: dict[str, dict]) -> dict:
    normalized = transport_schema.normalize_ast(ast)
    replacements = {
        ref: transport_schema.normalize_ast(value, f"substitution {ref}")
        for ref, value in substitutions.items()
    }
    for ref in replacements:
        if not isinstance(ref, str) or not (
            _STATE_REF.fullmatch(ref) or _INPUT_REF.fullmatch(ref)
        ):
            raise ValueError(f"invalid substitution reference: {ref!r}")

    def visit(node: dict) -> dict:
        if node["form"] == "ref" and node["ref"] in replacements:
            return transport_schema.normalize_ast(replacements[node["ref"]])
        result = {key: value for key, value in node.items() if key != "args"}
        if "args" in node:
            result["args"] = [visit(child) for child in node["args"]]
        return result

    return visit(normalized)


def transport_document(invariant_document: object, map_document: object) -> dict:
    invariant = transport_schema.normalize_invariant_document(invariant_document)
    mapping = transport_schema.normalize_map_document(map_document)
    if invariant["source"] != mapping["source"]:
        raise ValueError("transport map source identity does not match invariant source")
    if transport_schema.canonical_sha256(invariant) != mapping["source_certificate_sha256"]:
        raise ValueError("transport map source certificate hash mismatch")
    substitutions = dict(mapping["projection"])
    substitutions.update(mapping["input_map"])
    required = set().union(*(ast_refs(ast) for ast in invariant["predicates"]))
    missing = sorted(ref for ref in required if ref not in substitutions)
    if missing:
        raise ValueError(f"transport map does not cover invariant refs: {missing}")
    predicates = [substitute_ast(ast, substitutions) for ast in invariant["predicates"]]
    return {
        "schema": transport_schema.INVARIANT_SCHEMA,
        "source": mapping["target"],
        "predicates": predicates,
        "origin": {
            "kind": invariant["origin"]["kind"],
            "artifacts": invariant["origin"]["artifacts"],
        },
    }


def _to_bool(expression, location: str):
    if z3.is_bool(expression):
        return expression
    if z3.is_bv(expression) and expression.size() == 1:
        return expression == z3.BitVecVal(1, 1)
    raise TypeError(f"{location} is not Boolean or BV1")


def _require_bv(expression, location: str):
    if not z3.is_bv(expression):
        raise TypeError(f"{location} requires a bit-vector")
    return expression


def _same_bv(lhs, rhs, location: str):
    _require_bv(lhs, location)
    _require_bv(rhs, location)
    if lhs.size() != rhs.size():
        raise TypeError(
            f"{location} requires equal widths, got {lhs.size()} and {rhs.size()}"
        )
    return lhs, rhs


def _same_sort(lhs, rhs, location: str):
    if lhs.sort() != rhs.sort():
        raise TypeError(f"{location} requires equal sorts")
    return lhs, rhs


def compile_ast(
    ast: dict,
    model: dict,
    statevars: dict[int, object],
    inputvars: dict[int, object],
):
    node = transport_schema.normalize_ast(ast)

    def build(current: dict):
        form = current["form"]
        if form == "ref":
            match = _STATE_REF.fullmatch(current["ref"])
            if match:
                lineno = int(match.group(1))
                if lineno not in statevars:
                    raise KeyError(f"unknown state ref {current['ref']}")
                return statevars[lineno]
            match = _INPUT_REF.fullmatch(current["ref"])
            if match:
                lineno = int(match.group(1))
                if lineno not in inputvars:
                    raise KeyError(f"unknown input ref {current['ref']}")
                return inputvars[lineno]
            raise KeyError(f"unknown ref {current['ref']}")
        if form == "const":
            return candidate_cert_check.const_expr(current)

        args = [build(child) for child in current["args"]]
        if form in {"and", "or", "xor"}:
            values = [_to_bool(arg, form) for arg in args]
            if form == "and":
                return z3.And(*values)
            if form == "or":
                return z3.Or(*values)
            result = values[0]
            for value in values[1:]:
                result = z3.Xor(result, value)
            return result
        if form == "not":
            return z3.Not(_to_bool(args[0], form))
        if form == "implies":
            return z3.Implies(_to_bool(args[0], form), _to_bool(args[1], form))
        if form in {"add", "sub", "mul"}:
            result = _require_bv(args[0], form)
            if len(args) == 1:
                return -result if form == "sub" else result
            for value in args[1:]:
                result, value = _same_bv(result, value, form)
                if form == "add":
                    result = result + value
                elif form == "sub":
                    result = result - value
                else:
                    result = result * value
            return result
        if form in {"bvand", "bvor", "bvxor"}:
            lhs, rhs = _same_bv(args[0], args[1], form)
            return lhs & rhs if form == "bvand" else (
                lhs | rhs if form == "bvor" else lhs ^ rhs
            )
        if form == "bvnot":
            return ~_require_bv(args[0], form)
        if form == "bvcomp":
            lhs, rhs = _same_bv(args[0], args[1], form)
            return z3.If(lhs == rhs, z3.BitVecVal(1, 1), z3.BitVecVal(0, 1))
        if form in {"eq", "ne"}:
            lhs, rhs = _same_sort(args[0], args[1], form)
            return lhs == rhs if form == "eq" else lhs != rhs
        if form in {"ult", "ule", "ugt", "uge", "slt", "sle", "sgt", "sge"}:
            lhs, rhs = _same_bv(args[0], args[1], form)
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
        if form in {"udiv", "urem", "sdiv", "srem"}:
            lhs, rhs = _same_bv(args[0], args[1], form)
            if form == "udiv":
                return z3.UDiv(lhs, rhs)
            if form == "urem":
                return z3.URem(lhs, rhs)
            if form == "sdiv":
                return lhs / rhs
            return z3.SRem(lhs, rhs)
        if form in {"sll", "srl", "sra"}:
            lhs, rhs = _same_bv(args[0], args[1], form)
            if form == "sll":
                return lhs << rhs
            if form == "srl":
                return z3.LShR(lhs, rhs)
            return lhs >> rhs
        if form == "concat":
            return z3.Concat(*[_require_bv(arg, form) for arg in args])
        if form == "extract":
            child = _require_bv(args[0], form)
            if current["hi"] >= child.size():
                raise TypeError(
                    f"extract [{current['hi']}:{current['lo']}] exceeds width {child.size()}"
                )
            return z3.Extract(current["hi"], current["lo"], child)
        if form in {"uext", "sext"}:
            child = _require_bv(args[0], form)
            amount = current["width"] - child.size()
            if amount < 0:
                raise TypeError(f"{form} target width is smaller than its operand")
            return z3.ZeroExt(amount, child) if form == "uext" else z3.SignExt(amount, child)
        if form == "ite":
            condition = _to_bool(args[0], form)
            then_value, else_value = _same_sort(args[1], args[2], form)
            return z3.If(condition, then_value, else_value)
        raise ValueError(f"unsupported transport AST form: {form}")

    return build(node)


def _flatten_z3(expression, name: str) -> list:
    children = []
    stack = list(reversed(expression.children()))
    while stack:
        child = stack.pop()
        if str(child.decl().name()) == name:
            stack.extend(reversed(child.children()))
        else:
            children.append(child)
    return children


def z3_to_ast(expression, *, max_nodes: int = 50000) -> dict:
    if max_nodes <= 0:
        raise ValueError("max_nodes must be positive")
    emitted = 0

    def convert(current) -> dict:
        nonlocal emitted
        emitted += 1
        if emitted > max_nodes:
            raise ValueError(f"normalized invariant exceeds {max_nodes} AST nodes")
        if z3.is_true(current):
            return {"form": "const", "const": "true", "width": 0}
        if z3.is_false(current):
            return {"form": "const", "const": "false", "width": 0}
        if z3.is_bv_value(current):
            return {
                "form": "const",
                "const": str(current.as_long()),
                "width": current.size(),
            }
        if z3.is_const(current) and current.decl().kind() == z3.Z3_OP_UNINTERPRETED:
            ref = str(current.decl().name())
            if not (_STATE_REF.fullmatch(ref) or _INPUT_REF.fullmatch(ref)):
                raise ValueError(f"Pono invariant contains unknown symbol: {ref}")
            return {"form": "ref", "ref": ref}

        name = str(current.decl().name())
        if name == "distinct":
            children = list(current.children())
            if len(children) < 2:
                raise ValueError("distinct requires at least two operands")
            pairs = [
                {"form": "ne", "args": [convert(lhs), convert(rhs)]}
                for lhs, rhs in itertools.combinations(children, 2)
            ]
            return pairs[0] if len(pairs) == 1 else {"form": "and", "args": pairs}
        if name == "bvneg":
            return {"form": "sub", "args": [convert(current.arg(0))]}
        if name == "bvnot":
            return {"form": "bvnot", "args": [convert(current.arg(0))]}
        if name == "extract":
            hi, lo = (int(value) for value in current.params())
            return {
                "form": "extract",
                "args": [convert(current.arg(0))],
                "hi": hi,
                "lo": lo,
            }
        if name in {"zero_ext", "sign_ext"}:
            return {
                "form": "uext" if name == "zero_ext" else "sext",
                "args": [convert(current.arg(0))],
                "width": current.size(),
            }
        form = _Z3_FORM.get(name)
        if form is None:
            raise ValueError(f"Pono invariant uses unsupported Z3 operator: {name}")
        source_children = (
            _flatten_z3(current, name)
            if name in _ASSOCIATIVE_Z3
            else list(current.children())
        )
        return {"form": form, "args": [convert(child) for child in source_children]}

    prior_limit = sys.getrecursionlimit()
    if prior_limit < max_nodes + 100:
        sys.setrecursionlimit(max_nodes + 100)
    try:
        result = convert(expression)
    finally:
        if sys.getrecursionlimit() != prior_limit:
            sys.setrecursionlimit(prior_limit)
    return transport_schema.normalize_ast(result)


def extract_pono_invariant(output: str) -> str:
    lines = [line for line in output.splitlines() if line.startswith("INVAR:")]
    if len(lines) != 1:
        raise ValueError(f"expected exactly one INVAR line, found {len(lines)}")
    return lines[0]


def pono_invariant_to_ast(
    btor2_path: str | Path, output: str, *, max_nodes: int = 50000
) -> dict:
    model = cert_check.parse_btor2(str(btor2_path))
    statevars = {
        lineno: z3.BitVec(f"state{lineno}", cert_check.width_of(model, lineno))
        for lineno in model["states"]
    }
    inputvars = {
        lineno: z3.BitVec(f"input{lineno}", model["sorts"][args[0]])
        for lineno, (op, args) in model["nodes"].items()
        if op == "input"
    }
    parsed = cert_check.parse_invar(
        extract_pono_invariant(output), statevars, inputvars, model
    )
    return z3_to_ast(parsed, max_nodes=max_nodes)


def certify_predicates(
    btor2_path: str | Path, predicates: list[dict], timeout_ms: int = 20000
) -> dict:
    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be positive")
    if not predicates:
        raise ValueError("no predicates to certify")
    base = candidate_cert_check.build_base_formulas(str(btor2_path))
    compiled = [
        _to_bool(
            compile_ast(
                predicate,
                base["model"],
                base["statevars"],
                base["inputvars"],
            ),
            f"predicate {index}",
        )
        for index, predicate in enumerate(predicates)
    ]
    invariant = z3.And(*compiled)
    invariant_next = z3.substitute(invariant, *base["substitutions"])
    cache = {}
    bads = [
        cert_check.build(
            base["model"],
            node,
            base["statevars"],
            base["inputvars"],
            cache,
        )
        == 1
        for node in base["model"]["bads"]
    ]
    if not bads:
        raise ValueError("BTOR2 model contains no bad property")
    obligations = [
        (
            "C1 Init=>H",
            z3.And(base["init"], base["constraints"], z3.Not(invariant)),
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
    ] + [
        (
            f"C3[{index}] H=>notBAD",
            z3.And(invariant, base["constraints"], bad),
        )
        for index, bad in enumerate(bads)
    ]
    checks = []
    for name, formula in obligations:
        start = time.monotonic()
        solver = z3.Solver()
        solver.set("timeout", timeout_ms)
        solver.add(formula)
        result = solver.check()
        checks.append({
            "name": name,
            "result": str(result),
            "time_sec": time.monotonic() - start,
            "unknown_reason": solver.reason_unknown() if result == z3.unknown else "",
        })
    return {
        "ok": all(check["result"] == "unsat" for check in checks),
        "checks": checks,
        "bad_count": len(bads),
        "predicate_count": len(predicates),
        "ast_node_count": predicate_node_count(predicates),
    }
