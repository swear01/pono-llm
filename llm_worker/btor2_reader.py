"""
Lightweight BTOR2 parser for extracting semantic context for LLM prompts.

Parses only what we need for invariant generation:
  - Module name (from comment)
  - Input ports: name + width
  - State variables: stateNN ref, optional symbol, width, init value
  - Hot refs near the bad property (cone-of-influence, shallow BFS)
  - Simplified transition sketch for hot refs
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class BV2Sort:
    width: int


@dataclass
class InputVar:
    lineno: int
    ref: str       # "stateNN" doesn't apply; for inputs we use the symbol name
    symbol: str    # Verilog name
    width: int


@dataclass
class StateVar:
    lineno: int
    ref: str       # "state{lineno}" — matches pono internal naming
    symbol: Optional[str]  # From BTOR2 state line; None if auto-generated/absent
    width: int
    init_value: Optional[str] = None  # bitvec literal or None


@dataclass
class BTOR2Info:
    module_name: str
    inputs: List[InputVar] = field(default_factory=list)
    states: List[StateVar] = field(default_factory=list)
    bad_lineno: int = -1
    # lineno → list of linenos this node directly depends on
    deps: Dict[int, List[int]] = field(default_factory=dict)
    # stateNN → next-expr lineno
    next_map: Dict[str, int] = field(default_factory=dict)
    # lineno → human-readable sketch (best effort)
    node_sketch: Dict[int, str] = field(default_factory=dict)


_YOSYS_AUTO = re.compile(r"\$auto\$|\$techmap|\\|:execute\$|:246:|:245:|:222:|:256:")


def _is_meaningful_symbol(s: Optional[str]) -> bool:
    """Return True if the symbol is a meaningful Verilog name, not Yosys-internal."""
    if not s:
        return False
    return not bool(_YOSYS_AUTO.search(s))


def _sort_width(sorts: Dict[int, int], lineno: int) -> int:
    return sorts.get(lineno, 0)


def _parse_int_lineno(tok: str) -> Optional[int]:
    """Parse a token as a positive int lineno, stripping leading negation."""
    t = tok.lstrip("-")
    try:
        return int(t)
    except ValueError:
        return None


def parse_btor2(path: str) -> BTOR2Info:
    """Parse a BTOR2 file and return BTOR2Info."""
    info = BTOR2Info(module_name="unknown")
    sorts: Dict[int, int] = {}   # lineno → bit-width
    state_linenos: Set[int] = set()
    input_linenos: Set[int] = set()
    # lineno → list[int] direct argument linenos
    raw_deps: Dict[int, List[int]] = {}
    # state lineno → init expr lineno
    init_map: Dict[int, int] = {}

    with open(path) as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue

            # Module name from first comment
            if line.startswith(";"):
                m = re.search(r"for module (\w[\w./-]*)", line)
                if m and info.module_name == "unknown":
                    # strip trailing punctuation (Yosys sometimes adds a period)
                    info.module_name = m.group(1).rstrip(".,;")
                continue

            parts = line.split()
            if not parts:
                continue
            try:
                lineno = int(parts[0])
            except ValueError:
                continue
            if len(parts) < 2:
                continue
            op = parts[1]

            # Sort bitvec
            if op == "sort" and len(parts) >= 4 and parts[2] == "bitvec":
                try:
                    sorts[lineno] = int(parts[3])
                except ValueError:
                    pass

            # Input: N input SORT [SYMBOL]
            elif op == "input" and len(parts) >= 3:
                try:
                    sort_ln = int(parts[2])
                except ValueError:
                    continue
                width = sorts.get(sort_ln, 0)
                symbol = parts[3] if len(parts) > 3 else f"input{lineno}"
                info.inputs.append(InputVar(
                    lineno=lineno,
                    ref=f"input{lineno}",
                    symbol=symbol,
                    width=width,
                ))
                input_linenos.add(lineno)

            # State: N state SORT [SYMBOL]
            elif op == "state" and len(parts) >= 3:
                try:
                    sort_ln = int(parts[2])
                except ValueError:
                    continue
                width = sorts.get(sort_ln, 0)
                raw_sym = parts[3] if len(parts) > 3 else None
                symbol = raw_sym if _is_meaningful_symbol(raw_sym) else None
                info.states.append(StateVar(
                    lineno=lineno,
                    ref=f"state{lineno}",
                    symbol=symbol,
                    width=width,
                ))
                state_linenos.add(lineno)
                raw_deps[lineno] = []

            # Init: N init SORT STATE VALUE
            elif op == "init" and len(parts) >= 5:
                try:
                    state_ln = int(parts[3])
                    val_ln = int(parts[4])
                    init_map[state_ln] = val_ln
                except ValueError:
                    pass

            # Next: N next SORT STATE NEXT_EXPR
            elif op == "next" and len(parts) >= 5:
                try:
                    state_ln = int(parts[3])
                    next_ln = int(parts[4])
                    info.next_map[f"state{state_ln}"] = next_ln
                    raw_deps.setdefault(lineno, []).extend([state_ln, next_ln])
                except ValueError:
                    pass

            # Bad: N bad EXPR
            elif op == "bad" and len(parts) >= 3:
                try:
                    bad_expr_ln = int(parts[2])
                    info.bad_lineno = bad_expr_ln
                except ValueError:
                    pass

            # Other ops: record deps for COI BFS
            elif op not in ("sort", "constraint", "output", "justice", "fair"):
                arg_linenos = []
                for tok in parts[2:]:
                    ln = _parse_int_lineno(tok)
                    if ln is not None and ln != lineno:
                        arg_linenos.append(ln)
                raw_deps[lineno] = arg_linenos

    # Resolve init values for states
    lineno_to_const: Dict[int, str] = {}
    with open(path) as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith(";"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                lineno = int(parts[0])
            except ValueError:
                continue
            if parts[1] == "constd":
                lineno_to_const[lineno] = parts[3] if len(parts) > 3 else "0"
            elif parts[1] == "const":
                # "N const SORT VALUE" — VALUE is a binary string
                lineno_to_const[lineno] = parts[3] if len(parts) > 3 else "0"
            elif parts[1] == "zero":
                lineno_to_const[lineno] = "0"
            elif parts[1] == "one":
                lineno_to_const[lineno] = "1"
            elif parts[1] == "ones":
                lineno_to_const[lineno] = "all-ones"

    for sv in info.states:
        val_ln = init_map.get(sv.lineno)
        if val_ln is not None:
            sv.init_value = lineno_to_const.get(val_ln)

    info.deps = raw_deps
    return info


def hot_refs_near_bad(info: BTOR2Info, depth: int = 3) -> List[str]:
    """
    Return stateNN refs reachable from the bad property within `depth` BFS hops.
    Result is sorted by lineno for determinism.
    """
    if info.bad_lineno < 0:
        return []

    visited: Set[int] = set()
    frontier = {info.bad_lineno}
    state_refs: Set[str] = set()

    for _ in range(depth):
        next_frontier: Set[int] = set()
        for ln in frontier:
            if ln in visited:
                continue
            visited.add(ln)
            ref = f"state{ln}"
            if any(sv.lineno == ln for sv in info.states):
                state_refs.add(ref)
            for dep in info.deps.get(ln, []):
                if dep not in visited:
                    next_frontier.add(dep)
        frontier = next_frontier

    # Sort by lineno
    return sorted(state_refs, key=lambda r: int(r[5:]))


def build_hot_variables(info: BTOR2Info, refs: List[str]) -> List[dict]:
    """Build the hot_variables list for a Stage 0 request."""
    ref_set = set(refs)
    state_by_ref = {sv.ref: sv for sv in info.states}
    result = []
    for ref in refs:
        sv = state_by_ref.get(ref)
        if sv is None:
            continue
        entry: dict = {
            "ref": ref,
            "width": sv.width,
            "init": sv.init_value or "0",
        }
        if sv.symbol:
            entry["verilog"] = sv.symbol
        result.append(entry)
    return result


def build_transition_sketch(info: BTOR2Info, refs: List[str]) -> List[str]:
    """
    Very shallow transition sketch: just list which state variables have next-state
    logic, and describe the inputs they depend on.
    """
    lines = []
    input_by_lineno = {iv.lineno: iv.symbol for iv in info.inputs}
    state_by_lineno = {sv.lineno: sv for sv in info.states}

    for ref in refs:
        next_ln = info.next_map.get(ref)
        if next_ln is None:
            continue
        # Find input deps one level deep
        deps = info.deps.get(next_ln, [])
        input_deps = [input_by_lineno[d] for d in deps if d in input_by_lineno]
        state_deps = [f"state{d}" for d in deps if d in state_by_lineno and d != int(ref[5:])]

        sv = state_by_lineno.get(int(ref[5:]))
        name = sv.symbol if (sv and sv.symbol) else ref
        dep_parts = []
        if input_deps:
            dep_parts.append("inputs: " + ", ".join(input_deps[:4]))
        if state_deps:
            dep_parts.append("states: " + ", ".join(state_deps[:4]))
        if dep_parts:
            lines.append(f"{name}' depends on {'; '.join(dep_parts)}")
        else:
            lines.append(f"{name}' has next-state logic")
    return lines
