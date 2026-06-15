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

            # Other ops: record deps for COI BFS.
            # ops like slice/sext/uext have literal integer args that are NOT
            # node references — only their first data argument is a node ref.
            elif op not in ("sort", "constraint", "output", "justice", "fair"):
                arg_linenos = []
                # slice N SORT EXPR HIGH LOW  — only EXPR (parts[3]) is a node ref
                # sext/uext N SORT EXPR WIDTH — only EXPR (parts[3]) is a node ref
                if op in ("slice", "sext", "uext") and len(parts) >= 4:
                    ln = _parse_int_lineno(parts[3])
                    if ln is not None and ln != lineno:
                        arg_linenos.append(ln)
                else:
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


def hot_refs_near_bad(info: BTOR2Info, depth: int = 3,
                      transition_depth: int = 6) -> List[str]:
    """
    Return stateNN refs reachable from the bad property within `depth` BFS hops,
    plus states found within `transition_depth` hops through each found state's
    next-expression (secondary hot variables from transition logic).

    The secondary phase catches state variables that don't appear in the
    combinational property cone but are key invariant variables (e.g. loop
    counters that feed into hot-state transitions).
    Result is sorted by lineno for determinism.
    """
    if info.bad_lineno < 0:
        return []

    state_linenos: Set[int] = {sv.lineno for sv in info.states}
    visited: Set[int] = set()
    frontier: Set[int] = {info.bad_lineno}
    state_refs: Set[str] = set()

    for _ in range(depth):
        next_frontier: Set[int] = set()
        for ln in frontier:
            if ln in visited:
                continue
            visited.add(ln)
            if ln in state_linenos:
                ref = f"state{ln}"
                state_refs.add(ref)
                # Also follow this state's next-expression so we discover
                # state variables that influence its transition.
                nxt = info.next_map.get(ref)
                if nxt is not None and nxt not in visited:
                    next_frontier.add(nxt)
            for dep in info.deps.get(ln, []):
                if dep not in visited:
                    next_frontier.add(dep)
        frontier = next_frontier

    # Also scan the final frontier: states found at exactly `depth` hops are
    # in next_frontier after the last iteration but never get processed.
    for ln in frontier:
        if ln not in visited and ln in state_linenos:
            state_refs.add(f"state{ln}")

    # Secondary phase: for each primary hot state, BFS through its
    # next-expression up to `transition_depth` hops to find state variables
    # that appear in the transition logic (not visible from the property cone).
    for ref in list(state_refs):
        nxt_ln = info.next_map.get(ref)
        if nxt_ln is None:
            continue
        t_frontier: Set[int] = {nxt_ln}
        t_visited: Set[int] = set(visited)
        for _ in range(transition_depth):
            t_next: Set[int] = set()
            for ln in t_frontier:
                if ln in t_visited:
                    continue
                t_visited.add(ln)
                if ln in state_linenos:
                    state_refs.add(f"state{ln}")
                    # Don't recurse into this secondary state's own transitions
                else:
                    for dep in info.deps.get(ln, []):
                        if dep not in t_visited:
                            t_next.add(dep)
            t_frontier = t_next

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


def _node_formula(info: BTOR2Info, ln: int,
                  state_by_ln: Dict[int, StateVar],
                  input_by_ln: Dict[int, InputVar],
                  const_by_ln: Dict[int, str],
                  depth: int = 3) -> str:
    """Recursively build a short formula string for node ln."""
    if depth == 0:
        return f"node{ln}"
    if ln in state_by_ln:
        sv = state_by_ln[ln]
        return sv.symbol or sv.ref
    if ln in input_by_ln:
        return input_by_ln[ln].symbol
    if ln in const_by_ln:
        return const_by_ln[ln]

    deps = info.deps.get(ln, [])

    def arg(i: int) -> str:
        if i < len(deps):
            return _node_formula(info, deps[i], state_by_ln, input_by_ln,
                                 const_by_ln, depth - 1)
        return "?"

    # Find the op name from the parsed node_sketch (fallback)
    sketch = info.node_sketch.get(ln, "")
    if sketch:
        return sketch

    # We don't store op per node, so fall back to arg listing
    if len(deps) == 1:
        return f"f({arg(0)})"
    if len(deps) == 2:
        return f"f({arg(0)}, {arg(1)})"
    if len(deps) >= 3:
        return f"f({arg(0)}, {arg(1)}, {arg(2)})"
    return f"node{ln}"


def detect_symmetric_pairs(info: BTOR2Info, refs: List[str]) -> List[Tuple[str, str]]:
    """
    Find pairs of hot state variables that likely maintain an equality invariant.

    Two states are "symmetric" if they have:
    1. The same initial value (or both have no init)
    2. Identical transition dependency sets (same input deps + same state deps,
       excluding self-references)

    Returns a list of (refA, refB) pairs where eq(refA, refB) is likely inductive.
    """
    input_by_ln: Dict[int, InputVar] = {iv.lineno: iv for iv in info.inputs}
    state_by_ln: Dict[int, StateVar] = {sv.lineno: sv for sv in info.states}

    def _bfs_dep_sets(start_ln: int, self_ln: int) -> Tuple[frozenset, frozenset]:
        """Return (frozenset of input names, frozenset of state refs) excluding self."""
        visited: Set[int] = set()
        frontier: Set[int] = {start_ln}
        inp_deps: Set[str] = set()
        st_deps: Set[str] = set()
        while frontier:
            nxt: Set[int] = set()
            for n in frontier:
                if n in visited:
                    continue
                visited.add(n)
                if n in input_by_ln:
                    inp_deps.add(input_by_ln[n].symbol)
                elif n in state_by_ln:
                    if n != self_ln:
                        sv = state_by_ln[n]
                        st_deps.add(sv.ref)
                else:
                    for d in info.deps.get(n, []):
                        if d not in visited:
                            nxt.add(d)
            frontier = nxt
        return frozenset(inp_deps), frozenset(st_deps)

    # Collect (init_value, inp_deps, st_deps) for each ref
    sig: Dict[str, Tuple] = {}
    for ref in refs:
        sv = state_by_ln.get(int(ref[5:]))
        if sv is None:
            continue
        nxt_ln = info.next_map.get(ref)
        if nxt_ln is None:
            continue
        inp, st = _bfs_dep_sets(nxt_ln, sv.lineno)
        sig[ref] = (sv.init_value or "0", inp, st)

    # Find pairs with identical signatures
    pairs: List[Tuple[str, str]] = []
    ref_list = [r for r in refs if r in sig]
    for i, a in enumerate(ref_list):
        for b in ref_list[i + 1:]:
            if sig[a] == sig[b]:
                pairs.append((a, b))
    return pairs


def build_transition_sketch(info: BTOR2Info, refs: List[str]) -> List[str]:
    """
    Build a readable transition sketch for hot state variables.

    For each hot state variable, produces a line like:
      a' = ite(i_reset, 0, a+1)
      c' = depends on [state7, state8]

    Uses a BFS through the next-expression DAG to find all state/input
    variables that influence the transition, avoiding false matches from
    literal integer arguments (e.g. bit indices in slice).
    Also appends symmetry annotations when pairs of states have identical
    initial values and transition dependencies.
    """
    lines = []
    input_by_ln: Dict[int, InputVar] = {iv.lineno: iv for iv in info.inputs}
    state_by_ln: Dict[int, StateVar] = {sv.lineno: sv for sv in info.states}
    const_by_ln: Dict[int, str] = {}

    # Build const map from node_sketch if populated, else from deps (const/constd nodes)
    for ln, sk in info.node_sketch.items():
        if sk.lstrip("-").isdigit():
            const_by_ln[ln] = sk

    def _bfs_deps(start_ln: int, self_ln: int) -> Tuple[List[str], List[str]]:
        """BFS from start_ln; return (input_deps, state_deps) avoiding self_ln."""
        visited: Set[int] = set()
        frontier: Set[int] = {start_ln}
        inp_deps: List[str] = []
        st_deps: List[str] = []
        seen: Set[int] = set()

        while frontier:
            nxt: Set[int] = set()
            for n in frontier:
                if n in visited:
                    continue
                visited.add(n)
                if n in input_by_ln:
                    if n not in seen:
                        inp_deps.append(input_by_ln[n].symbol)
                        seen.add(n)
                elif n in state_by_ln:
                    if n not in seen and n != self_ln:
                        sv = state_by_ln[n]
                        st_deps.append(sv.symbol or sv.ref)
                        seen.add(n)
                    # Do NOT recurse into state's own transitions
                else:
                    for d in info.deps.get(n, []):
                        if d not in visited:
                            nxt.add(d)
            frontier = nxt
        return inp_deps, st_deps

    for ref in refs:
        next_ln = info.next_map.get(ref)
        sv = state_by_ln.get(int(ref[5:]))
        if sv is None:
            continue
        name = sv.symbol or ref

        if next_ln is None:
            continue

        inp_deps, st_deps = _bfs_deps(next_ln, sv.lineno)

        dep_parts = []
        if inp_deps:
            dep_parts.append("inputs: " + ", ".join(inp_deps[:6]))
        if st_deps:
            dep_parts.append("states: " + ", ".join(st_deps[:6]))

        if dep_parts:
            lines.append(f"{name}' depends on {'; '.join(dep_parts)}")
        else:
            lines.append(f"{name}' has next-state logic")

    # Append symmetry hints for pairs of states with identical transition signatures.
    pairs = detect_symmetric_pairs(info, refs)
    if pairs:
        lines.append("")
        lines.append("SYMMETRY HINT — pairs with identical init and transition structure:")
        for a, b in pairs:
            sv_a = state_by_ln.get(int(a[5:]))
            sv_b = state_by_ln.get(int(b[5:]))
            na = (sv_a.symbol or a) if sv_a else a
            nb = (sv_b.symbol or b) if sv_b else b
            lines.append(f"  {na} ({a}) and {nb} ({b}) have same init and same deps"
                         f" → eq({a}, {b}) is likely inductive")

    return lines
