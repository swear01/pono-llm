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
    # lineno → BTOR2 op string (for expression-level comparison)
    ops: Dict[int, str] = field(default_factory=dict)
    # lineno → const value string (for canonical hashing of constants)
    consts: Dict[int, str] = field(default_factory=dict)


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
    # state lineno → name extracted from output statements (for unnamed states)
    output_labels: Dict[int, str] = {}

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

            # Output: N output REF [NAME]
            # When states lack explicit symbols, Yosys may record names via output stmts.
            elif op == "output" and len(parts) >= 4:
                try:
                    ref_ln = int(parts[2])
                    name = parts[3]
                    if _is_meaningful_symbol(name):
                        output_labels[ref_ln] = name
                except (ValueError, IndexError):
                    pass

            # Other ops: record deps for COI BFS.
            # ops like slice/sext/uext have literal integer args that are NOT
            # node references — only their first data argument is a node ref.
            elif op not in ("sort", "constraint", "justice", "fair"):
                info.ops[lineno] = op
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

    # Apply output labels to unnamed states (Yosys sometimes encodes names this way)
    for sv in info.states:
        if sv.symbol is None and sv.lineno in output_labels:
            sv.symbol = output_labels[sv.lineno]

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

    info.consts = lineno_to_const

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
    # Use state_linenos as seed (not full visited) so the primary BFS's
    # intermediate nodes don't accidentally block secondary exploration.
    for ref in list(state_refs):
        nxt_ln = info.next_map.get(ref)
        if nxt_ln is None:
            continue
        t_frontier: Set[int] = {nxt_ln}
        t_visited: Set[int] = set()
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


def _expr_canonical_hash(
    info: BTOR2Info,
    ln: int,
    self_ln: int,
    input_by_ln: Dict[int, "InputVar"],
    state_by_ln: Dict[int, "StateVar"],
    cache: Dict,
    depth: int = 30,
) -> str:
    """
    Compute a canonical structural hash of the expression rooted at `ln`.
    Self-references (state at `self_ln`) are replaced by placeholder "SELF".
    Used to compare next-state expressions for two states after substituting
    each state's own reference with "SELF" — if hashes match, the expressions
    are structurally identical and the equality invariant is inductive.
    """
    key = (ln, self_ln)
    if key in cache:
        return cache[key]
    if depth == 0:
        return f"#{ln}"

    if ln == self_ln:
        cache[key] = "SELF"
        return "SELF"
    if ln in input_by_ln:
        h = f"INP:{input_by_ln[ln].symbol}"
        cache[key] = h
        return h
    if ln in state_by_ln:
        h = f"ST:{state_by_ln[ln].ref}"
        cache[key] = h
        return h
    if ln in info.consts:
        h = f"CONST:{info.consts[ln]}"
        cache[key] = h
        return h

    op = info.ops.get(ln, "?")
    children = info.deps.get(ln, [])
    child_hashes = [
        _expr_canonical_hash(info, c, self_ln, input_by_ln, state_by_ln, cache, depth - 1)
        for c in children
    ]
    h = f"{op}({','.join(child_hashes)})"
    cache[key] = h
    return h


def detect_symmetric_pairs(info: BTOR2Info, refs: List[str]) -> List[Tuple[str, str]]:
    """
    Find pairs of hot state variables that likely maintain an equality invariant.

    Two states A and B form a symmetric pair if:
    1. They have the same initial value (or both have no init)
    2. Their next-state expressions are STRUCTURALLY IDENTICAL after substituting
       each state's self-reference with a SELF placeholder.

    This is stronger than dep-set matching: it guarantees eq(A, B) is inductive
    (given eq(A, B) in the current state and no cross-references between A and B).

    Falls back to dep-set matching if expression hashing is unavailable (e.g., no ops).
    """
    input_by_ln: Dict[int, InputVar] = {iv.lineno: iv for iv in info.inputs}
    state_by_ln: Dict[int, StateVar] = {sv.lineno: sv for sv in info.states}

    use_expr_hash = bool(info.ops)  # available if parser stored ops

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

    # Phase 1: dep-set filtering (fast)
    dep_sigs: Dict[str, Tuple] = {}
    for ref in refs:
        sv = state_by_ln.get(int(ref[5:]))
        if sv is None:
            continue
        nxt_ln = info.next_map.get(ref)
        if nxt_ln is None:
            continue
        inp, st = _bfs_dep_sets(nxt_ln, sv.lineno)
        dep_sigs[ref] = (sv.init_value or "0", inp, st)

    dep_candidates: List[Tuple[str, str]] = []
    ref_list = [r for r in refs if r in dep_sigs]
    for i, a in enumerate(ref_list):
        for b in ref_list[i + 1:]:
            if dep_sigs[a] == dep_sigs[b]:
                dep_candidates.append((a, b))

    if not use_expr_hash or not dep_candidates:
        return dep_candidates

    # Phase 2: expression hash for dep-set candidates only (precise)
    # Compute hash per-state lazily; cache shared across all pairs.
    cache: Dict = {}
    expr_hash_cache: Dict[str, str] = {}

    def _get_expr_hash(ref: str) -> str:
        if ref in expr_hash_cache:
            return expr_hash_cache[ref]
        sv = state_by_ln[int(ref[5:])]
        nxt_ln = info.next_map[ref]
        h = _expr_canonical_hash(info, nxt_ln, sv.lineno,
                                 input_by_ln, state_by_ln, cache)
        expr_hash_cache[ref] = h
        return h

    confirmed: List[Tuple[str, str]] = []
    for a, b in dep_candidates:
        try:
            if _get_expr_hash(a) == _get_expr_hash(b):
                confirmed.append((a, b))
        except RecursionError:
            # Fall back to dep-set match for very deep expressions
            confirmed.append((a, b))
    return confirmed


def _decode_expr(
    info: "BTOR2Info",
    ln: int,
    input_by_ln: Dict[int, "InputVar"],
    state_by_ln: Dict[int, "StateVar"],
    depth: int = 0,
    max_depth: int = 6,
    _cache: Optional[Dict] = None,
) -> str:
    """
    Recursively decode a BTOR2 expression node into a human-readable formula string.
    Returns a simplified C-like expression.

    BTOR2 convention: for all non-trivial ops, deps[0] is the sort node (bitvec/array).
    Data args start at deps[1]. For ite: deps[1]=cond, deps[2]=then, deps[3]=else.
    """
    if _cache is None:
        _cache = {}
    if ln in _cache:
        return _cache[ln]
    if depth > max_depth:
        return "..."

    if ln in input_by_ln:
        r = input_by_ln[ln].symbol
        _cache[ln] = r
        return r
    if ln in state_by_ln:
        sv = state_by_ln[ln]
        r = sv.symbol or sv.ref
        _cache[ln] = r
        return r

    op = info.ops.get(ln)

    # Const: look up in info.consts (binary string) and convert to decimal
    if op in ("const", "constd") or (op is None and ln in info.consts):
        raw = info.consts.get(ln, "")
        if raw:
            try:
                val = int(raw, 2) if set(raw) <= {'0', '1'} else int(raw)
                result = str(val)
            except ValueError:
                result = raw
        else:
            result = f"const{ln}"
        _cache[ln] = result
        return result

    if op is None:
        r = f"node{ln}"
        _cache[ln] = r
        return r

    # BTOR2 dep layout differs by op:
    # - uext/sext/slice: parser only records the data expr (not sort) → data_args = all_deps
    # - all other ops: parser records sort+all_data → data_args = all_deps[1:] (skip sort)
    all_deps = info.deps.get(ln, [])
    if op in ("uext", "sext", "slice"):
        data_args = all_deps  # no sort in deps for these (parser handles specially)
    else:
        data_args = all_deps[1:] if all_deps else []  # skip sort arg

    def mk(**kw2: int) -> str:
        return ""  # not used

    def child(i: int) -> str:
        if i >= len(data_args):
            return "?"
        return _decode_expr(info, data_args[i], input_by_ln, state_by_ln,
                            depth + 1, max_depth, _cache)

    result: str
    if op == "ite" and len(data_args) >= 3:
        cond = child(0)
        then_ = child(1)
        else_ = child(2)
        if cond in ("rst", "reset") and then_ == "0":
            result = else_
        else:
            result = f"({cond} ? {then_} : {else_})"
    elif op == "add" and len(data_args) >= 2:
        result = f"({child(0)} + {child(1)})"
    elif op == "sub" and len(data_args) >= 2:
        result = f"({child(0)} - {child(1)})"
    elif op == "mul" and len(data_args) >= 2:
        result = f"({child(0)} * {child(1)})"
    elif op in ("uext", "sext") and data_args:
        result = child(0)  # extension invisible at high level
    elif op == "not" and data_args:
        result = f"!{child(0)}"
    elif op in ("and", "bvand") and len(data_args) >= 2:
        result = f"({child(0)} && {child(1)})"
    elif op in ("or", "bvor") and len(data_args) >= 2:
        result = f"({child(0)} || {child(1)})"
    elif op == "ult" and len(data_args) >= 2:
        result = f"({child(0)} < {child(1)})"
    elif op == "ulte" and len(data_args) >= 2:
        result = f"({child(0)} <= {child(1)})"
    elif op == "ugt" and len(data_args) >= 2:
        result = f"({child(0)} > {child(1)})"
    elif op == "ugte" and len(data_args) >= 2:
        result = f"({child(0)} >= {child(1)})"
    elif op in ("slt", "slte", "sgt", "sgte") and len(data_args) >= 2:
        _ops = {"slt": "<s", "slte": "<=s", "sgt": ">s", "sgte": ">=s"}
        result = f"({child(0)} {_ops[op]} {child(1)})"
    elif op == "eq" and len(data_args) >= 2:
        result = f"({child(0)} == {child(1)})"
    elif op == "neq" and len(data_args) >= 2:
        result = f"({child(0)} != {child(1)})"
    elif op in ("const", "constd"):
        result = info.consts.get(ln, f"const{ln}")
    else:
        shown = [child(i) for i in range(min(len(data_args), 4))]
        result = f"{op}({', '.join(shown)})"

    _cache[ln] = result
    return result


def build_transition_sketch(info: BTOR2Info, refs: List[str]) -> List[str]:
    """
    Build a readable transition sketch for hot state variables.

    For each hot state variable, produces the actual formula like:
      c' = (rst ? 0 : (i >= n ? c : (c + i)))
      i' = (rst ? 0 : (i >= n ? i : (i + 1)))

    Falls back to dependency list if formula decoding fails.
    """
    lines = []
    input_by_ln: Dict[int, InputVar] = {iv.lineno: iv for iv in info.inputs}
    state_by_ln: Dict[int, StateVar] = {sv.lineno: sv for sv in info.states}

    for ref in refs:
        next_ln = info.next_map.get(ref)
        sv = state_by_ln.get(int(ref[5:]))
        if sv is None:
            continue
        name = sv.symbol or ref
        if next_ln is None:
            continue

        try:
            formula = _decode_expr(info, next_ln, input_by_ln, state_by_ln)
            lines.append(f"{name}' = {formula}")
        except Exception:
            # Fall back to dependency summary
            lines.append(f"{name}' = (complex expression)")

    return lines
