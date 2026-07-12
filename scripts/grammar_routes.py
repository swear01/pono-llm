#!/usr/bin/env python3
"""Strict grammar-route validation and deterministic predicate expansion."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import sys
from dataclasses import dataclass
from math import gcd
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT_DIR / "llm_worker"))

from btor2_reader import hot_refs_near_bad, parse_btor2  # noqa: E402
import cert_check  # noqa: E402

ROUTE_SCHEMA = "pono-llm-grammar-route-v1"
ROUTE_FAMILIES = {
    "unary",
    "pairwise_offset",
    "affine",
    "sum_equality",
    "quadratic_recurrence",
}
RELATION_ORDER = ("eq", "le", "ge")
SIGNEDNESS = {"signed", "unsigned"}
TOP_LEVEL_FIELDS = {"schema", "routes"}
COMMON_ROUTE_FIELDS = {
    "variables",
    "family",
    "relations",
    "signedness",
}
FAMILY_FIELDS = {
    "unary": {"constants"},
    "pairwise_offset": {"offsets"},
    "affine": {"coefficient_bound"},
    "sum_equality": set(),
    "quadratic_recurrence": {"scales", "counter_shifts"},
}
DEFAULT_CONSTANTS = tuple(range(9))
DEFAULT_OFFSETS = (0, 1, -1, 2, -2, 3, -3, 4, -4)
DEFAULT_SCALES = (1, 2, 3, 4)
DEFAULT_COUNTER_SHIFTS = (-1, 0, 1)
BOUNDED_GRAMMAR_MAX_VARIABLES = 6


def canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def bounded_exhaustive_route_document(
    variables: list[dict],
    *,
    max_variables: int = BOUNDED_GRAMMAR_MAX_VARIABLES,
) -> dict:
    """Build the preregistered bounded grammar without model-specific guessing."""
    if max_variables <= 0:
        raise ValueError("max_variables must be positive")
    normalized = []
    seen_refs = set()
    for index, variable in enumerate(variables):
        if not isinstance(variable, dict):
            raise ValueError(f"variable {index} must be an object")
        ref = variable.get("state_ref") or variable.get("ref")
        width = variable.get("width")
        if not isinstance(ref, str) or not re.fullmatch(r"state\d+", ref):
            raise ValueError(f"variable {index} must have a stateN reference")
        if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
            raise ValueError(f"variable {index} must have a positive width")
        if ref in seen_refs:
            raise ValueError(f"duplicate bounded-grammar variable: {ref}")
        seen_refs.add(ref)
        normalized.append((int(ref[5:]), ref, width))
    normalized.sort()
    normalized = normalized[:max_variables]
    if not normalized:
        raise ValueError("bounded grammar requires at least one scalar variable")

    routes = []
    for _, ref, _ in normalized:
        routes.append({
            "variables": [ref],
            "family": "unary",
            "relations": ["eq", "le", "ge"],
            "signedness": "unsigned",
            "constants": [0, 1],
        })
        routes.append({
            "variables": [ref],
            "family": "unary",
            "relations": ["le", "ge"],
            "signedness": "signed",
            "constants": [0, 1],
        })

    by_width: dict[int, list[str]] = {}
    for _, ref, width in normalized:
        by_width.setdefault(width, []).append(ref)
    for width in sorted(by_width):
        refs = by_width[width]
        for lhs, rhs in itertools.combinations(refs, 2):
            routes.append({
                "variables": [lhs, rhs],
                "family": "pairwise_offset",
                "relations": ["eq", "le", "ge"],
                "signedness": "unsigned",
                "offsets": [0, 1, -1, 2, -2],
            })
            routes.append({
                "variables": [lhs, rhs],
                "family": "pairwise_offset",
                "relations": ["le", "ge"],
                "signedness": "signed",
                "offsets": [0, 1, -1, 2, -2],
            })
            routes.append({
                "variables": [lhs, rhs],
                "family": "affine",
                "relations": ["eq", "le", "ge"],
                "signedness": "unsigned",
                "coefficient_bound": 2,
            })
            routes.append({
                "variables": [lhs, rhs],
                "family": "affine",
                "relations": ["le", "ge"],
                "signedness": "signed",
                "coefficient_bound": 2,
            })
        for triple in itertools.combinations(refs, 3):
            routes.append({
                "variables": list(triple),
                "family": "affine",
                "relations": ["eq"],
                "signedness": "unsigned",
                "coefficient_bound": 2,
            })
            for result in triple:
                operands = [ref for ref in triple if ref != result]
                routes.append({
                    "variables": [result, *operands],
                    "family": "sum_equality",
                    "relations": ["eq"],
                    "signedness": "unsigned",
                })
        for accumulator, counter in itertools.permutations(refs, 2):
            routes.append({
                "variables": [accumulator, counter],
                "family": "quadratic_recurrence",
                "relations": ["eq"],
                "signedness": "unsigned",
                "scales": [1, 2, 3, 4],
                "counter_shifts": [-1, 0, 1],
            })
    return {"schema": ROUTE_SCHEMA, "routes": routes}


def structural_route_document(
    path: str,
    variables: list[dict],
    *,
    max_routes: int = 8,
) -> tuple[dict, dict]:
    """Build a fixed budget route using only target-structure heuristics."""
    if max_routes <= 0:
        raise ValueError("max_routes must be positive")
    info = parse_btor2(path)
    available = {}
    for index, variable in enumerate(variables):
        if not isinstance(variable, dict):
            raise ValueError(f"variable {index} must be an object")
        ref = variable.get("state_ref") or variable.get("ref")
        width = variable.get("width")
        if not isinstance(ref, str) or not re.fullmatch(r"state\d+", ref):
            raise ValueError(f"variable {index} must have a stateN reference")
        if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
            raise ValueError(f"variable {index} must have a positive width")
        if ref in available:
            raise ValueError(f"duplicate structural-router variable: {ref}")
        available[ref] = width
    if not available:
        raise ValueError("structural router requires at least one scalar variable")

    state_linenos = {state.lineno for state in info.states}
    hot = set(hot_refs_near_bad(info, depth=6, transition_depth=10))
    scores = {ref: (100 if ref in hot else 0) for ref in available}
    dependency_edges = set()
    update_ops = {}
    for owner in sorted(available, key=lambda ref: int(ref[5:])):
        next_node = info.next_map.get(owner)
        if next_node is None:
            continue
        queue = [next_node]
        visited = set()
        ops = set()
        while queue and len(visited) < 2000:
            node = abs(queue.pop(0))
            if node in visited:
                continue
            visited.add(node)
            op = info.ops.get(node)
            if op:
                ops.add(op)
            if node in state_linenos:
                dependency = f"state{node}"
                if dependency in available and dependency != owner:
                    dependency_edges.add((owner, dependency))
                    scores[dependency] += 10
                continue
            queue.extend(abs(dep) for dep in info.deps.get(node, []))
        update_ops[owner] = sorted(ops)
        scores[owner] += 5

    ranked = sorted(
        available,
        key=lambda ref: (-scores[ref], int(ref[5:])),
    )[:3]
    routes = []

    def add(route: dict) -> None:
        if len(routes) >= max_routes:
            return
        key = canonical_json(route)
        if any(canonical_json(existing) == key for existing in routes):
            return
        routes.append(route)

    for ref in ranked:
        add({
            "variables": [ref],
            "family": "unary",
            "relations": ["eq", "le", "ge"],
            "signedness": "signed",
            "constants": [0, 1],
        })
    same_width_pairs = [
        pair for pair in itertools.combinations(ranked, 2)
        if available[pair[0]] == available[pair[1]]
    ]
    same_width_pairs.sort(key=lambda pair: (
        not (
            (pair[0], pair[1]) in dependency_edges
            or (pair[1], pair[0]) in dependency_edges
        ),
        tuple(int(ref[5:]) for ref in pair),
    ))
    for lhs, rhs in same_width_pairs:
        add({
            "variables": [lhs, rhs],
            "family": "pairwise_offset",
            "relations": ["eq", "le", "ge"],
            "signedness": "signed",
            "offsets": [0, 1, -1, 2, -2],
        })
    if len(ranked) == 3 and len({available[ref] for ref in ranked}) == 1:
        add({
            "variables": ranked,
            "family": "affine",
            "relations": ["eq"],
            "signedness": "unsigned",
            "coefficient_bound": 2,
        })
        for result in ranked:
            operands = [ref for ref in ranked if ref != result]
            add({
                "variables": [result, *operands],
                "family": "sum_equality",
                "relations": ["eq"],
                "signedness": "unsigned",
            })
    for owner, dependency in sorted(dependency_edges):
        if available[owner] != available[dependency]:
            continue
        add({
            "variables": [owner, dependency],
            "family": "quadratic_recurrence",
            "relations": ["eq"],
            "signedness": "unsigned",
            "scales": [1, 2, 3, 4],
            "counter_shifts": [-1, 0, 1],
        })
    document = {"schema": ROUTE_SCHEMA, "routes": routes}
    diagnostics = {
        "ranked_variables": ranked,
        "scores": {ref: scores[ref] for ref in sorted(scores)},
        "hot_variables": sorted(hot),
        "dependency_edges": [list(edge) for edge in sorted(dependency_edges)],
        "update_ops": update_ops,
        "max_routes": max_routes,
    }
    return document, diagnostics


def ref_ast(ref: str) -> dict:
    return {"form": "ref", "ref": ref}


def const_ast(value: int, width: int) -> dict:
    return {
        "form": "const",
        "const": str(value % (1 << width)),
        "width": width,
    }


def add_terms(terms: list[dict], width: int) -> dict:
    if not terms:
        return const_ast(0, width)
    current = terms[0]
    for term in terms[1:]:
        current = {"form": "add", "args": [current, term]}
    return current


def term_times(coefficient: int, ref: str, width: int) -> dict:
    if coefficient == 1:
        return ref_ast(ref)
    if coefficient <= 0:
        raise ValueError("term_times requires a positive coefficient")
    return {
        "form": "mul",
        "args": [const_ast(coefficient, width), ref_ast(ref)],
    }


def relation_form(relation: str, signedness: str) -> str:
    if relation == "eq":
        return "eq"
    if relation == "le":
        return "sle" if signedness == "signed" else "ule"
    if relation == "ge":
        return "sge" if signedness == "signed" else "uge"
    raise ValueError(f"unsupported route relation: {relation}")


def normalize_coefficients(values: tuple[int, ...]) -> tuple[int, ...] | None:
    if not values or all(value == 0 for value in values):
        return None
    divisor = 0
    for value in values:
        divisor = gcd(divisor, abs(value))
    if divisor > 1:
        values = tuple(value // divisor for value in values)
    first = next(value for value in values if value)
    if first < 0:
        values = tuple(-value for value in values)
    return values


def affine_coefficient_patterns(
    count: int, bound: int
) -> list[tuple[int, ...]]:
    patterns = {
        normalize_coefficients(values)
        for values in itertools.product(range(-bound, bound + 1), repeat=count)
        if all(value != 0 for value in values)
    }
    return sorted(
        (pattern for pattern in patterns if pattern),
        key=lambda pattern: (
            sum(abs(value) for value in pattern),
            max(abs(value) for value in pattern),
            pattern,
        ),
    )


def affine_sides(
    coefficients: tuple[int, ...], variables: tuple[str, ...], width: int
) -> tuple[dict, dict] | None:
    positive = [
        term_times(coefficient, ref, width)
        for coefficient, ref in zip(coefficients, variables)
        if coefficient > 0
    ]
    negative = [
        term_times(-coefficient, ref, width)
        for coefficient, ref in zip(coefficients, variables)
        if coefficient < 0
    ]
    if not positive or not negative:
        return None
    return add_terms(positive, width), add_terms(negative, width)


@dataclass(frozen=True)
class GrammarRoute:
    requested_variables: tuple[str, ...]
    variables: tuple[str, ...]
    width: int
    family: str
    relations: tuple[str, ...]
    signedness: str
    constants: tuple[int, ...] = ()
    offsets: tuple[int, ...] = ()
    coefficient_bound: int = 0
    scales: tuple[int, ...] = ()
    counter_shifts: tuple[int, ...] = ()
    route_id: str = ""

    def semantic_payload(self) -> dict:
        payload: dict[str, object] = {
            "variables": list(self.variables),
            "family": self.family,
            "relations": list(self.relations),
            "signedness": self.signedness,
        }
        if self.family == "unary":
            payload["constants"] = list(self.constants)
        elif self.family == "pairwise_offset":
            payload["offsets"] = list(self.offsets)
        elif self.family == "affine":
            payload["coefficient_bound"] = self.coefficient_bound
        elif self.family == "quadratic_recurrence":
            payload["scales"] = list(self.scales)
            payload["counter_shifts"] = list(self.counter_shifts)
        return payload

    def canonical_payload(self) -> dict:
        payload = self.semantic_payload()
        payload["requested_variables"] = list(self.requested_variables)
        payload["width"] = self.width
        payload["route_id"] = self.route_id
        return payload


@dataclass(frozen=True)
class Phase:
    phase_id: str
    pc_ref: str
    width: int
    value: int
    guard_ast: dict
    equality_node: int
    is_initial: bool
    is_bad: bool

    def canonical_payload(self) -> dict:
        return {
            "phase_id": self.phase_id,
            "pc_ref": self.pc_ref,
            "width": self.width,
            "value": self.value,
            "guard_ast": self.guard_ast,
            "equality_node": self.equality_node,
            "is_initial": self.is_initial,
            "is_bad": self.is_bad,
        }


def _strict_fields(value: dict, allowed: set[str], location: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{location} has unknown fields: {unknown}")


def _integer_list(
    value: object,
    field: str,
    *,
    minimum: int,
    maximum: int,
) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty integer list")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise ValueError(f"{field} must contain only integers")
    if any(item < minimum or item > maximum for item in value):
        raise ValueError(
            f"{field} values must be between {minimum} and {maximum}"
        )
    if len(set(value)) != len(value):
        raise ValueError(f"{field} must not contain duplicates")
    return tuple(value)


def _state_catalog(info) -> tuple[dict[str, tuple[str, int]], set[str]]:
    by_name: dict[str, list[tuple[str, int]]] = {}
    for state in info.states:
        if state.width <= 0:
            continue
        by_name.setdefault(state.ref, []).append((state.ref, state.width))
        if state.symbol:
            by_name.setdefault(state.symbol, []).append((state.ref, state.width))
    catalog: dict[str, tuple[str, int]] = {}
    ambiguous: set[str] = set()
    for name, values in by_name.items():
        unique = sorted(set(values))
        if len(unique) == 1:
            catalog[name] = unique[0]
        else:
            ambiguous.add(name)
    return catalog, ambiguous


def _resolve_variables(
    raw: object,
    catalog: dict[str, tuple[str, int]],
    ambiguous: set[str],
    location: str,
) -> tuple[tuple[str, ...], tuple[str, ...], int]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{location}.variables must be a non-empty string list")
    if any(not isinstance(value, str) or not value for value in raw):
        raise ValueError(f"{location}.variables must contain non-empty strings")
    requested = tuple(raw)
    resolved = []
    widths = []
    for name in requested:
        if name in ambiguous:
            raise ValueError(f"ambiguous state symbol in {location}: {name}")
        if name not in catalog:
            raise ValueError(f"unknown scalar state in {location}: {name}")
        ref, width = catalog[name]
        resolved.append(ref)
        widths.append(width)
    if len(set(resolved)) != len(resolved):
        raise ValueError(f"{location}.variables resolve to duplicate states")
    if len(set(widths)) != 1:
        raise ValueError(f"{location}.variables must have one common width")
    return requested, tuple(resolved), widths[0]


def _normalise_relations(value: object, location: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{location}.relations must be a non-empty list")
    if any(relation not in RELATION_ORDER for relation in value):
        raise ValueError(
            f"{location}.relations must use only {list(RELATION_ORDER)}"
        )
    if len(set(value)) != len(value):
        raise ValueError(f"{location}.relations must not contain duplicates")
    return tuple(relation for relation in RELATION_ORDER if relation in value)


def _route_variable_count(family: str, count: int, location: str) -> None:
    if family == "unary" and count != 1:
        raise ValueError(f"{location} unary requires exactly 1 variable")
    if family in {"pairwise_offset", "quadratic_recurrence"} and count != 2:
        raise ValueError(f"{location} {family} requires exactly 2 variables")
    if family == "affine" and count not in {2, 3}:
        raise ValueError(f"{location} affine requires exactly 2 or 3 variables")
    if family == "sum_equality" and count != 3:
        raise ValueError(f"{location} sum_equality requires exactly 3 variables")


def _compile_route(
    raw: object,
    index: int,
    catalog: dict[str, tuple[str, int]],
    ambiguous: set[str],
) -> GrammarRoute:
    location = f"route {index}"
    if not isinstance(raw, dict):
        raise ValueError(f"{location} must be an object")
    family = raw.get("family")
    if family not in ROUTE_FAMILIES:
        raise ValueError(
            f"{location}.family must be one of {sorted(ROUTE_FAMILIES)}"
        )
    allowed = COMMON_ROUTE_FIELDS | FAMILY_FIELDS[family]
    unknown = sorted(set(raw) - allowed)
    if unknown:
        known_other_fields = set().union(*FAMILY_FIELDS.values())
        irrelevant = sorted(set(unknown) & known_other_fields)
        if irrelevant:
            raise ValueError(f"{location} {family} does not allow fields: {irrelevant}")
        raise ValueError(f"{location} has unknown route fields: {unknown}")
    missing = sorted(COMMON_ROUTE_FIELDS - set(raw))
    if missing:
        raise ValueError(f"{location} is missing fields: {missing}")

    requested, variables, width = _resolve_variables(
        raw["variables"], catalog, ambiguous, location
    )
    _route_variable_count(family, len(variables), location)
    relations = _normalise_relations(raw["relations"], location)
    signedness = raw["signedness"]
    if signedness not in SIGNEDNESS:
        raise ValueError(f"{location}.signedness must be signed or unsigned")

    constants: tuple[int, ...] = ()
    offsets: tuple[int, ...] = ()
    coefficient_bound = 0
    scales: tuple[int, ...] = ()
    counter_shifts: tuple[int, ...] = ()
    if family == "unary":
        constants = _integer_list(
            raw.get("constants", list(DEFAULT_CONSTANTS)),
            f"{location}.constants",
            minimum=-16,
            maximum=16,
        )
    elif family == "pairwise_offset":
        offsets = _integer_list(
            raw.get("offsets", list(DEFAULT_OFFSETS)),
            f"{location}.offsets",
            minimum=-16,
            maximum=16,
        )
    elif family == "affine":
        coefficient_bound = raw.get("coefficient_bound", 4)
        if (
            isinstance(coefficient_bound, bool)
            or not isinstance(coefficient_bound, int)
            or not 1 <= coefficient_bound <= 8
        ):
            raise ValueError(
                f"{location}.coefficient_bound must be an integer from 1 to 8"
            )
    elif family == "quadratic_recurrence":
        scales = _integer_list(
            raw.get("scales", list(DEFAULT_SCALES)),
            f"{location}.scales",
            minimum=1,
            maximum=8,
        )
        counter_shifts = _integer_list(
            raw.get("counter_shifts", list(DEFAULT_COUNTER_SHIFTS)),
            f"{location}.counter_shifts",
            minimum=-4,
            maximum=4,
        )

    provisional = GrammarRoute(
        requested_variables=requested,
        variables=variables,
        width=width,
        family=family,
        relations=relations,
        signedness=signedness,
        constants=constants,
        offsets=offsets,
        coefficient_bound=coefficient_bound,
        scales=scales,
        counter_shifts=counter_shifts,
    )
    route_id = canonical_sha256({
        "schema": ROUTE_SCHEMA,
        "route": provisional.semantic_payload(),
    })
    return GrammarRoute(**{
        **provisional.__dict__,
        "route_id": route_id,
    })


def compile_route_document(path: str, payload: object) -> list[GrammarRoute]:
    if not isinstance(payload, dict):
        raise ValueError("route document must be an object")
    _strict_fields(payload, TOP_LEVEL_FIELDS, "route document")
    if payload.get("schema") != ROUTE_SCHEMA:
        raise ValueError(f"route document schema must be {ROUTE_SCHEMA}")
    raw_routes = payload.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ValueError("route document routes must be a non-empty list")
    info = parse_btor2(path)
    catalog, ambiguous = _state_catalog(info)
    routes = [
        _compile_route(raw, index, catalog, ambiguous)
        for index, raw in enumerate(raw_routes)
    ]
    ids = [route.route_id for route in routes]
    if len(ids) != len(set(ids)):
        raise ValueError("route document contains duplicate semantic routes")
    return routes


def load_route_document(path: str, route_path: str) -> list[GrammarRoute]:
    try:
        payload = json.loads(Path(route_path).read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid route JSON: {exc}") from exc
    return compile_route_document(path, payload)


def canonical_route_document(routes: list[GrammarRoute]) -> str:
    return canonical_json({
        "schema": ROUTE_SCHEMA,
        "routes": [route.canonical_payload() for route in routes],
    })


def _constant_value(model: dict, node: int) -> int | None:
    if node not in model["nodes"]:
        return None
    op, args = model["nodes"][node]
    if op == "zero":
        return 0
    if op == "one":
        return 1
    if op == "ones":
        return (1 << model["sorts"][args[0]]) - 1
    if op not in {"const", "constd", "consth"}:
        return None
    literal = args[1]
    base = {"const": 2, "constd": 10, "consth": 16}[op]
    return int(literal, base)


def extract_functional_phases(path: str) -> list[Phase]:
    """Extract explicit one-word CPV program-counter phases without guessing."""
    model = cert_check.parse_btor2(path)
    pc_states = []
    for state in model["states"]:
        raw = model["raw"][state]
        symbol = raw[3] if len(raw) > 3 else ""
        if symbol == "!pc":
            pc_states.append(state)
    if len(pc_states) != 1:
        raise ValueError(
            "functional phase extraction requires exactly one !pc state; "
            f"found {len(pc_states)}"
        )
    pc_state = pc_states[0]
    if pc_state not in model["nexts"]:
        raise ValueError("functional !pc state has no next expression")
    if pc_state not in model["inits"]:
        raise ValueError("functional !pc state has no initialization")
    width = cert_check.width_of(model, pc_state)
    if width <= 1:
        raise ValueError("functional !pc state must be a multi-bit phase word")

    initial_value = _constant_value(model, model["inits"][pc_state])
    if initial_value is None:
        raise ValueError("functional !pc initialization must be a constant")

    phase_nodes: dict[int, int] = {}
    for node, (op, args) in model["nodes"].items():
        if op != "eq" or len(args) < 3:
            continue
        lhs, rhs = args[1], args[2]
        constant_node = None
        if lhs == pc_state:
            constant_node = rhs
        elif rhs == pc_state:
            constant_node = lhs
        if constant_node is None:
            continue
        value = _constant_value(model, constant_node)
        if value is None:
            continue
        value %= 1 << width
        phase_nodes.setdefault(value, node)
    if len(phase_nodes) < 2:
        raise ValueError(
            "functional !pc state must have at least two constant equality phases"
        )
    if initial_value % (1 << width) not in phase_nodes:
        raise ValueError("functional !pc initial value is absent from phase equalities")

    phases = []
    bad_nodes = set(model["bads"])
    for value, equality_node in sorted(phase_nodes.items()):
        phase_id = f"pc_state{pc_state}_w{width}_v{value}"
        phases.append(Phase(
            phase_id=phase_id,
            pc_ref=f"state{pc_state}",
            width=width,
            value=value,
            guard_ast={
                "form": "eq",
                "args": [
                    ref_ast(f"state{pc_state}"),
                    const_ast(value, width),
                ],
            },
            equality_node=equality_node,
            is_initial=value == initial_value % (1 << width),
            is_bad=equality_node in bad_nodes,
        ))
    return phases


def apply_phase_mode(
    entries: list[dict],
    phases: list[Phase],
    *,
    mode: str,
    cap: int,
) -> list[dict]:
    if cap <= 0:
        raise ValueError("cap must be positive")
    if mode == "global":
        return [dict(entry) for entry in entries[:cap]]
    if mode != "all":
        raise ValueError("phase mode must be global or all")
    if not phases:
        raise ValueError("all phase mode requires at least one extracted phase")

    guarded = []
    seen = set()
    for entry in entries:
        candidate = entry["predicate_ast"]
        for phase in phases:
            ast = {
                "form": "implies",
                "args": [phase.guard_ast, candidate],
            }
            key = canonical_json(ast)
            if key in seen:
                continue
            seen.add(key)
            guarded_entry = dict(entry)
            guarded_entry["predicate_ast"] = ast
            guarded_entry["phase_id"] = phase.phase_id
            guarded_entry["phase"] = phase.canonical_payload()
            guarded.append(guarded_entry)
            if len(guarded) >= cap:
                return guarded
    return guarded


def _route_predicates(route: GrammarRoute, init_values: dict[str, int]):
    variables = route.variables
    width = route.width
    if route.family == "unary":
        constants = list(route.constants)
        initial = init_values.get(variables[0])
        if initial is not None and initial not in constants:
            constants.insert(0, initial)
        for constant in constants:
            for relation in route.relations:
                yield {
                    "form": relation_form(relation, route.signedness),
                    "args": [ref_ast(variables[0]), const_ast(constant, width)],
                }
        return

    if route.family == "pairwise_offset":
        lhs, rhs = variables
        for offset in route.offsets:
            rhs_offset = {
                "form": "add",
                "args": [ref_ast(rhs), const_ast(offset, width)],
            }
            for relation in route.relations:
                yield {
                    "form": relation_form(relation, route.signedness),
                    "args": [ref_ast(lhs), rhs_offset],
                }
        return

    if route.family == "affine":
        for coefficients in affine_coefficient_patterns(
            len(variables), route.coefficient_bound
        ):
            sides = affine_sides(coefficients, variables, width)
            if sides is None:
                continue
            lhs, rhs = sides
            for relation in route.relations:
                yield {
                    "form": relation_form(relation, route.signedness),
                    "args": [lhs, rhs],
                }
        return

    if route.family == "sum_equality":
        result, first, second = variables
        sum_ast = {
            "form": "add",
            "args": [ref_ast(first), ref_ast(second)],
        }
        for relation in route.relations:
            yield {
                "form": relation_form(relation, route.signedness),
                "args": [ref_ast(result), sum_ast],
            }
        return

    if route.family == "quadratic_recurrence":
        accumulator, counter = variables
        for scale in route.scales:
            lhs = term_times(scale, accumulator, width)
            for shift in route.counter_shifts:
                if shift == 0:
                    shifted = ref_ast(counter)
                elif shift < 0:
                    shifted = {
                        "form": "sub",
                        "args": [
                            ref_ast(counter),
                            const_ast(-shift, width),
                        ],
                    }
                else:
                    shifted = {
                        "form": "add",
                        "args": [
                            ref_ast(counter),
                            const_ast(shift, width),
                        ],
                    }
                product = {
                    "form": "mul",
                    "args": [ref_ast(counter), shifted],
                }
                for relation in route.relations:
                    yield {
                        "form": relation_form(relation, route.signedness),
                        "args": [lhs, product],
                    }
        return

    raise ValueError(f"unsupported route family: {route.family}")


def _initial_values(path: str) -> dict[str, int]:
    info = parse_btor2(path)
    values = {}
    for state in info.states:
        if state.init_value is None:
            continue
        try:
            values[state.ref] = int(state.init_value, 10)
        except ValueError:
            continue
    return values


def expand_routes(
    path: str, routes: list[GrammarRoute], *, cap: int
) -> list[dict]:
    if cap <= 0:
        raise ValueError("cap must be positive")
    init_values = _initial_values(path)
    entries = []
    seen = set()
    for route in routes:
        for predicate in _route_predicates(route, init_values):
            key = canonical_json(predicate)
            if key in seen:
                continue
            seen.add(key)
            entries.append({
                "predicate_ast": predicate,
                "route_id": route.route_id,
                "template_family": route.family,
                "phase_id": None,
                "provenance": {
                    "requested_variables": list(route.requested_variables),
                    "variables": list(route.variables),
                    "width": route.width,
                    "signedness": route.signedness,
                },
            })
            if len(entries) >= cap:
                return entries
    return entries


def serialise_entries(entries: list[dict]) -> str:
    text = "\n".join(json.dumps(entry, sort_keys=True) for entry in entries)
    return text + ("\n" if text else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("btor2")
    parser.add_argument("routes")
    parser.add_argument("--out", required=True)
    parser.add_argument("--cap", type=int, default=2000)
    parser.add_argument("--phase-mode", choices=("global", "all"), default="global")
    args = parser.parse_args()
    if args.cap <= 0:
        parser.error("--cap must be positive")
    output = Path(args.out)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite route expansion: {output}")
    routes = load_route_document(args.btor2, args.routes)
    entries = expand_routes(args.btor2, routes, cap=args.cap)
    phases = (
        extract_functional_phases(args.btor2)
        if args.phase_mode == "all"
        else []
    )
    entries = apply_phase_mode(
        entries, phases, mode=args.phase_mode, cap=args.cap
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialise_entries(entries))
    print(json.dumps({
        "schema": ROUTE_SCHEMA,
        "route_count": len(routes),
        "candidate_count": len(entries),
        "phase_mode": args.phase_mode,
        "phase_count": len(phases),
        "route_sha256": canonical_sha256(
            json.loads(canonical_route_document(routes))
        ),
        "candidate_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
