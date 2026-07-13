#!/usr/bin/env python3
"""Exact sparse polynomials over Z/(2^w)Z for Gate 4B certificates."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence


class UnsupportedPolynomialModel(ValueError):
    pass


Monomial = tuple[tuple[str, int], ...]


def _canonical_payload(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


@dataclasses.dataclass(frozen=True)
class Polynomial:
    width: int
    terms: tuple[tuple[Monomial, int], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.width, int) or self.width <= 0:
            raise ValueError("polynomial width must be a positive integer")
        modulus = 1 << self.width
        previous: Monomial | None = None
        for monomial, coefficient in self.terms:
            if previous is not None and monomial <= previous:
                raise ValueError("polynomial terms must be canonical and unique")
            previous = monomial
            if not 0 < coefficient < modulus:
                raise ValueError("polynomial coefficients must be normalized and nonzero")
            names = [name for name, _ in monomial]
            if names != sorted(set(names)):
                raise ValueError("monomial variables must be sorted and unique")
            if any(exponent <= 0 for _, exponent in monomial):
                raise ValueError("canonical monomial exponents must be positive")

    @classmethod
    def _from_map(cls, width: int, raw: Mapping[Monomial, int]) -> "Polynomial":
        if not isinstance(width, int) or width <= 0:
            raise ValueError("polynomial width must be a positive integer")
        modulus = 1 << width
        normalized = {
            monomial: coefficient % modulus
            for monomial, coefficient in raw.items()
            if coefficient % modulus
        }
        return cls(width, tuple(sorted(normalized.items())))

    @classmethod
    def zero(cls, width: int) -> "Polynomial":
        return cls(width, ())

    @classmethod
    def constant(cls, width: int, value: int) -> "Polynomial":
        return cls._from_map(width, {(): value})

    @classmethod
    def variable(cls, width: int, name: str) -> "Polynomial":
        if not isinstance(name, str) or not name:
            raise ValueError("polynomial variable name must be non-empty")
        return cls._from_map(width, {((name, 1),): 1})

    @classmethod
    def from_terms(
        cls,
        width: int,
        terms: Sequence[dict],
        *,
        allowed_variables: set[str],
    ) -> "Polynomial":
        if not isinstance(terms, list) or not terms:
            raise ValueError("polynomial terms must be a non-empty list")
        result: dict[Monomial, int] = {}
        for index, term in enumerate(terms):
            if not isinstance(term, dict):
                raise ValueError(f"term {index} must be an object")
            unknown = set(term) - {"coefficient", "powers"}
            missing = {"coefficient", "powers"} - set(term)
            if unknown or missing:
                raise ValueError(
                    f"term {index} has unknown fields {sorted(unknown)} "
                    f"or missing fields {sorted(missing)}"
                )
            coefficient = term["coefficient"]
            if not isinstance(coefficient, str) or not re.fullmatch(
                r"-?(?:0|[1-9][0-9]*)", coefficient
            ):
                raise ValueError(f"term {index} coefficient must be a decimal string")
            powers = term["powers"]
            if not isinstance(powers, dict):
                raise ValueError(f"term {index} powers must be an object")
            monomial_parts = []
            for name, exponent in powers.items():
                if name not in allowed_variables:
                    raise ValueError(f"term {index} uses unknown variable {name!r}")
                if not isinstance(exponent, int) or isinstance(exponent, bool) or exponent <= 0:
                    raise ValueError(
                        f"term {index} exponent for {name!r} must be positive"
                    )
                monomial_parts.append((name, exponent))
            monomial = tuple(sorted(monomial_parts))
            result[monomial] = result.get(monomial, 0) + int(coefficient)
        return cls._from_map(width, result)

    def _require_same_width(self, other: "Polynomial") -> None:
        if not isinstance(other, Polynomial) or self.width != other.width:
            raise ValueError("polynomial operation requires equal widths")

    def __add__(self, other: "Polynomial") -> "Polynomial":
        self._require_same_width(other)
        result = dict(self.terms)
        for monomial, coefficient in other.terms:
            result[monomial] = result.get(monomial, 0) + coefficient
        return self._from_map(self.width, result)

    def __neg__(self) -> "Polynomial":
        return self._from_map(
            self.width, {monomial: -coefficient for monomial, coefficient in self.terms}
        )

    def __sub__(self, other: "Polynomial") -> "Polynomial":
        return self + (-other)

    def __mul__(self, other: "Polynomial") -> "Polynomial":
        self._require_same_width(other)
        result: dict[Monomial, int] = {}
        for lhs_monomial, lhs_coefficient in self.terms:
            lhs_powers = dict(lhs_monomial)
            for rhs_monomial, rhs_coefficient in other.terms:
                powers = dict(lhs_powers)
                for name, exponent in rhs_monomial:
                    powers[name] = powers.get(name, 0) + exponent
                monomial = tuple(sorted(powers.items()))
                result[monomial] = (
                    result.get(monomial, 0) + lhs_coefficient * rhs_coefficient
                )
        return self._from_map(self.width, result)

    def __pow__(self, exponent: int) -> "Polynomial":
        if not isinstance(exponent, int) or exponent < 0:
            raise ValueError("polynomial exponent must be a non-negative integer")
        result = self.constant(self.width, 1)
        base = self
        power = exponent
        while power:
            if power & 1:
                result = result * base
            power >>= 1
            if power:
                base = base * base
        return result

    def scale(self, coefficient: int) -> "Polynomial":
        return self._from_map(
            self.width,
            {
                monomial: coefficient * term_coefficient
                for monomial, term_coefficient in self.terms
            },
        )

    def substitute(self, substitutions: Mapping[str, "Polynomial"]) -> "Polynomial":
        result = self.zero(self.width)
        for monomial, coefficient in self.terms:
            expanded = self.constant(self.width, coefficient)
            for name, exponent in monomial:
                replacement = substitutions.get(name, self.variable(self.width, name))
                if replacement.width != self.width:
                    raise ValueError("polynomial substitution requires equal widths")
                expanded = expanded * (replacement**exponent)
            result = result + expanded
        return result

    def is_zero(self) -> bool:
        return not self.terms

    def variables(self) -> frozenset[str]:
        return frozenset(name for monomial, _ in self.terms for name, _ in monomial)

    def degree(self) -> int:
        return max(
            (sum(exponent for _, exponent in monomial) for monomial, _ in self.terms),
            default=0,
        )

    def canonical_terms(self) -> list[dict]:
        return [
            {
                "coefficient": str(coefficient),
                "powers": {name: exponent for name, exponent in monomial},
            }
            for monomial, coefficient in self.terms
        ]


@dataclasses.dataclass(frozen=True)
class TransitionBranch:
    branch_id: str
    decisions: tuple[tuple[int, bool], ...]
    substitutions: dict[str, Polynomial] = dataclasses.field(compare=False)


@dataclasses.dataclass(frozen=True)
class ExpandedPolynomialBranch:
    decisions: tuple[tuple[int, bool], ...]
    polynomial: Polynomial


def _node_width(model: dict, node: int) -> int:
    if node < 0:
        node = -node
    return int(model["sorts"][int(model["raw"][node][2])])


def _constant_value(model: dict, node: int) -> tuple[int, int] | None:
    if node < 0:
        child = _constant_value(model, -node)
        if child is None:
            return None
        width, value = child
        return width, (~value) % (1 << width)
    op, args = model["nodes"][node]
    width = _node_width(model, node)
    if op == "zero":
        return width, 0
    if op == "one":
        return width, 1
    if op == "ones":
        return width, (1 << width) - 1
    if op in {"const", "constd", "consth"}:
        literal = args[1]
        base = 2 if op == "const" else (10 if op == "constd" else 16)
        return width, int(literal, base) % (1 << width)
    if op in {"add", "sub", "mul"}:
        lhs = _constant_value(model, int(args[1]))
        rhs = _constant_value(model, int(args[2]))
        if lhs is None or rhs is None or lhs[0] != width or rhs[0] != width:
            return None
        if op == "add":
            value = lhs[1] + rhs[1]
        elif op == "sub":
            value = lhs[1] - rhs[1]
        else:
            value = lhs[1] * rhs[1]
        return width, value % (1 << width)
    if op == "neg":
        child = _constant_value(model, int(args[1]))
        if child is None or child[0] != width:
            return None
        return width, (-child[1]) % (1 << width)
    if op in {"uext", "sext"}:
        child = _constant_value(model, int(args[1]))
        if child is None:
            return None
        child_width, value = child
        if child_width + int(args[2]) != width:
            raise UnsupportedPolynomialModel(
                f"malformed {op} at node {node}: extension width does not match"
            )
        if op == "sext" and value & (1 << (child_width - 1)):
            value -= 1 << child_width
        return width, value % (1 << width)
    return None


def _merge_decisions(
    lhs: tuple[tuple[int, bool], ...], rhs: tuple[tuple[int, bool], ...]
) -> tuple[tuple[int, bool], ...] | None:
    merged = dict(lhs)
    for node, value in rhs:
        if node in merged and merged[node] != value:
            return None
        merged[node] = value
    return tuple(sorted(merged.items()))


def guard_identity(decisions: tuple[tuple[int, bool], ...]) -> str:
    payload = [[node, value] for node, value in decisions]
    return "g-" + hashlib.sha256(_canonical_payload(payload)).hexdigest()[:16]


def _combine_expanded(
    lhs: Iterable[ExpandedPolynomialBranch],
    rhs: Iterable[ExpandedPolynomialBranch],
    operation: str,
) -> tuple[ExpandedPolynomialBranch, ...]:
    result = []
    for left in lhs:
        for right in rhs:
            decisions = _merge_decisions(left.decisions, right.decisions)
            if decisions is None:
                continue
            if operation == "add":
                polynomial = left.polynomial + right.polynomial
            elif operation == "sub":
                polynomial = left.polynomial - right.polynomial
            else:
                polynomial = left.polynomial * right.polynomial
            result.append(ExpandedPolynomialBranch(decisions, polynomial))
    return tuple(result)


def _expand_node(
    model: dict,
    node: int,
    *,
    width: int,
    allowed_variables: set[str],
) -> tuple[ExpandedPolynomialBranch, ...]:
    constant = _constant_value(model, node)
    if constant is not None:
        node_width, value = constant
        if node_width != width:
            raise UnsupportedPolynomialModel(
                f"constant node {node} has width {node_width}, expected {width}"
            )
        return (ExpandedPolynomialBranch((), Polynomial.constant(width, value)),)
    if node < 0:
        raise UnsupportedPolynomialModel(f"nonconstant bitwise-not ref {node} is unsupported")
    op, args = model["nodes"][node]
    node_width = _node_width(model, node)
    if op in {"state", "input"}:
        name = f"{op}{node}"
        if node_width != width:
            raise UnsupportedPolynomialModel(
                f"{name} has width {node_width}, expected {width}"
            )
        if name not in allowed_variables:
            raise UnsupportedPolynomialModel(
                f"transition references undeclared polynomial variable {name}"
            )
        return (ExpandedPolynomialBranch((), Polynomial.variable(width, name)),)
    if op in {"add", "sub", "mul"}:
        if node_width != width:
            raise UnsupportedPolynomialModel(
                f"{op} node {node} has width {node_width}, expected {width}"
            )
        lhs = _expand_node(
            model, int(args[1]), width=width, allowed_variables=allowed_variables
        )
        rhs = _expand_node(
            model, int(args[2]), width=width, allowed_variables=allowed_variables
        )
        return _combine_expanded(lhs, rhs, op)
    if op == "neg":
        if node_width != width:
            raise UnsupportedPolynomialModel(
                f"neg node {node} has width {node_width}, expected {width}"
            )
        values = _expand_node(
            model, int(args[1]), width=width, allowed_variables=allowed_variables
        )
        return tuple(
            ExpandedPolynomialBranch(value.decisions, -value.polynomial)
            for value in values
        )
    if op == "ite":
        if node_width != width:
            raise UnsupportedPolynomialModel(
                f"ite node {node} has width {node_width}, expected {width}"
            )
        condition = int(args[1])
        if _node_width(model, condition) != 1:
            raise UnsupportedPolynomialModel(
                f"ite condition {condition} is not one bit"
            )
        true_values = _expand_node(
            model, int(args[2]), width=width, allowed_variables=allowed_variables
        )
        false_values = _expand_node(
            model, int(args[3]), width=width, allowed_variables=allowed_variables
        )
        result = []
        for item in true_values:
            decisions = _merge_decisions(item.decisions, ((condition, True),))
            if decisions is not None:
                result.append(ExpandedPolynomialBranch(decisions, item.polynomial))
        for item in false_values:
            decisions = _merge_decisions(item.decisions, ((condition, False),))
            if decisions is not None:
                result.append(ExpandedPolynomialBranch(decisions, item.polynomial))
        return tuple(result)
    raise UnsupportedPolynomialModel(f"operator {op} at node {node} is unsupported")


def expand_polynomial_branches(
    model: dict,
    node: int,
    *,
    width: int,
    polynomial_variables: Sequence[str],
) -> tuple[ExpandedPolynomialBranch, ...]:
    variables = tuple(polynomial_variables)
    if len(variables) != len(set(variables)):
        raise ValueError("polynomial variables must be unique")
    for name in variables:
        if not re.fullmatch(r"(?:state|input)[0-9]+", name):
            raise ValueError(f"invalid polynomial variable {name!r}")
    return _expand_node(
        model, node, width=width, allowed_variables=set(variables)
    )


def extract_transition_branches(
    model: dict,
    *,
    width: int,
    polynomial_variables: Sequence[str],
    tracked_state_variables: Sequence[str],
    branch_cap: int,
) -> tuple[TransitionBranch, ...]:
    if not isinstance(branch_cap, int) or branch_cap <= 0:
        raise ValueError("branch cap must be positive")
    if not tracked_state_variables:
        raise ValueError("at least one tracked state variable is required")
    all_variables = tuple(polynomial_variables)
    if len(all_variables) != len(set(all_variables)):
        raise ValueError("polynomial variables must be unique")
    for name in all_variables:
        if not re.fullmatch(r"(?:state|input)[0-9]+", name):
            raise ValueError(f"invalid polynomial variable {name!r}")
    if len(tracked_state_variables) != len(set(tracked_state_variables)):
        raise ValueError("tracked state variables must be unique")
    for name in tracked_state_variables:
        if not re.fullmatch(r"state[0-9]+", name):
            raise ValueError(f"invalid tracked state variable {name!r}")
        if name not in all_variables:
            raise ValueError(f"tracked state variable {name!r} is undeclared")
    allowed = set(all_variables)
    combined: list[tuple[tuple[tuple[int, bool], ...], dict[str, Polynomial]]] = [
        ((), {})
    ]
    for name in tracked_state_variables:
        state_node = int(name.removeprefix("state"))
        if state_node not in model["states"]:
            raise UnsupportedPolynomialModel(f"unknown BTOR2 state {name}")
        if _node_width(model, state_node) != width:
            raise UnsupportedPolynomialModel(
                f"{name} has width {_node_width(model, state_node)}, expected {width}"
            )
        if state_node not in model["nexts"]:
            raise UnsupportedPolynomialModel(
                f"tracked state {name} has no functional next-state definition"
            )
        next_node = model["nexts"][state_node]
        expanded = _expand_node(
            model, next_node, width=width, allowed_variables=allowed
        )
        next_combined = []
        for decisions, substitutions in combined:
            for value in expanded:
                merged = _merge_decisions(decisions, value.decisions)
                if merged is None:
                    continue
                updated = dict(substitutions)
                updated[name] = value.polynomial
                next_combined.append((merged, updated))
        combined = next_combined
        if len(combined) > branch_cap:
            raise UnsupportedPolynomialModel(
                f"transition branch count exceeds cap {branch_cap}"
            )

    branches = []
    seen_ids: set[str] = set()
    for decisions, substitutions in combined:
        payload = {
            "decisions": [[node, value] for node, value in decisions],
            "substitutions": {
                name: substitutions[name].canonical_terms()
                for name in sorted(substitutions)
            },
        }
        branch_id = "b-" + hashlib.sha256(_canonical_payload(payload)).hexdigest()[:16]
        if branch_id in seen_ids:
            raise AssertionError("duplicate transition branch identity")
        seen_ids.add(branch_id)
        branches.append(TransitionBranch(branch_id, decisions, substitutions))
    branches.sort(key=lambda branch: branch.branch_id)
    if not branches:
        raise UnsupportedPolynomialModel("transition has no consistent branches")
    return tuple(branches)


def check_multiplier_identity(
    basis: Sequence[Polynomial],
    substitutions: Mapping[str, Polynomial],
    multipliers: Sequence[Sequence[Polynomial]],
) -> tuple[str, ...]:
    if not basis:
        raise ValueError("invariant basis must not be empty")
    if len(multipliers) != len(basis) or any(
        len(row) != len(basis) for row in multipliers
    ):
        raise ValueError("multiplier matrix dimensions must match invariant basis")
    width = basis[0].width
    if any(polynomial.width != width for polynomial in basis):
        raise ValueError("invariant basis requires one common width")
    errors = []
    for index, invariant in enumerate(basis):
        lhs = invariant.substitute(substitutions)
        rhs = Polynomial.zero(width)
        for multiplier, basis_polynomial in zip(multipliers[index], basis, strict=True):
            if multiplier.width != width:
                raise ValueError("multiplier width must match invariant width")
            rhs = rhs + multiplier * basis_polynomial
        if lhs != rhs:
            errors.append(f"P{index} branch identity mismatch")
    return tuple(errors)
