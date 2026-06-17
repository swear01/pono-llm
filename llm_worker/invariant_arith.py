"""
Software-origin arithmetic invariant support.

For circuits compiled from C programs (variable names preserved: i, n, x, y),
LLM can apply loop invariant reasoning to suggest arithmetic predicates like
x + y == 3 * i that structural analysis cannot find.

Pipeline:
  1. detect_software_origin() — check if circuit has C-style variable names
  2. build_software_prompt()  — prompt LLM with C-level semantics
  3. ast_to_btor2()           — convert predicate AST to BTOR2 constraint nodes
  4. verify_invariant()       — SMT soundness check via pono (NOT(inv) = unsat?)
  5. inject_constraints()     — write modified BTOR2 with verified constraints
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

from btor2_reader import BTOR2Info, parse_btor2


# ---------------------------------------------------------------------------
# 1. Detect software-origin circuit
# ---------------------------------------------------------------------------

_C_IDENT = re.compile(r'^[a-z_][a-z0-9_]*$', re.IGNORECASE)
_BAD_PREFIXES = ('state', 'v1_buf', 'v2_buf', 'reset0', 'valid', 'ap_', 'pc[')
_BAD_CHARS = ('!', '{', '(', '`', '.')
_BAD_PATTERNS = (
    '__',   # Verilog hierarchy flattening: module__submodule
)


def detect_software_origin(info: BTOR2Info) -> bool:
    """
    Return True if circuit likely originated from a C program:
    - At least 2 state variables with short, clean C-identifier names
    - No HLS-generated prefixes (u1., ap_CS_fsm, etc.)
    - No Verilog hierarchy names (double underscore: module__submodule)
    - Names like i, n, x, y, sum, a, b, counter (short, single-level)
    """
    clean = []
    for sv in info.states:
        name = sv.symbol or ""
        if not name:
            continue
        if any(c in name for c in _BAD_CHARS):
            continue
        if any(p in name for p in _BAD_PATTERNS):
            continue
        if any(name.startswith(p) for p in _BAD_PREFIXES):
            continue
        if _C_IDENT.match(name) and len(name) <= 12:
            clean.append(sv)
    return len(clean) >= 2


def get_software_vars(info: BTOR2Info):
    """Return state variables with clean C-style names."""
    result = []
    for sv in info.states:
        name = sv.symbol or ""
        if not name:
            continue
        if any(c in name for c in _BAD_CHARS):
            continue
        if any(p in name for p in _BAD_PATTERNS):
            continue
        if any(name.startswith(p) for p in _BAD_PREFIXES):
            continue
        if _C_IDENT.match(name) and len(name) <= 12:
            result.append(sv)
    return result


# ---------------------------------------------------------------------------
# 2. Build software-origin prompt
# ---------------------------------------------------------------------------

def _decode_init(init_val: Optional[str], width: int) -> str:
    """Convert binary init string to decimal for readability."""
    if init_val is None:
        return "?"
    try:
        return str(int(init_val, 2))
    except (ValueError, TypeError):
        return init_val or "?"


def build_software_prompt(request: dict, info: BTOR2Info) -> str:
    """
    Build a loop-invariant-focused prompt for software-compiled circuits.
    Emphasizes C-level semantics and asks for arithmetic invariants.
    """
    from btor2_reader import build_transition_sketch
    benchmark = request.get("benchmark", "unknown")
    property_desc = request.get("property_desc", "")
    if len(property_desc) > 200:
        property_desc = property_desc[:200] + "...(truncated)"

    sw_vars = get_software_vars(info)
    state_by_ref = {sv.ref: sv for sv in info.states}

    parts = [
        f"BENCHMARK: {benchmark}",
        "",
        "THIS CIRCUIT WAS COMPILED FROM A C PROGRAM.",
        "Variable names are preserved from the original source code.",
        "Apply loop invariant reasoning exactly as you would for software verification.",
        "",
        "STATE VARIABLES:",
    ]
    for sv in sw_vars:
        init_dec = _decode_init(sv.init_value, sv.width)
        nxt = info.next_map.get(sv.ref)
        role = ""
        if sv.symbol in ('i', 'j', 'k', 'counter', 'idx') or sv.symbol.endswith('_i'):
            role = "  ← likely loop counter"
        elif sv.symbol in ('n', 'm', 'bound', 'limit', 'max'):
            role = "  ← likely loop bound (constant)"
        parts.append(f"  {sv.symbol} ({sv.width}-bit, ref={sv.ref}, init={init_dec}){role}")
    parts.append("")

    # Build transition sketch for ALL software vars (not just hot refs).
    # For software-origin circuits, hot_refs often misses update vars that are
    # farther from the bad node (e.g. x,y in a counter circuit).
    sw_refs = [sv.ref for sv in sw_vars]
    sw_sketch = build_transition_sketch(info, sw_refs)
    if sw_sketch:
        parts.append("TRANSITION (per clock step):")
        for line in sw_sketch:
            parts.append(f"  {line}")
        parts.append("")

    if property_desc:
        parts.append(f"PROPERTY TO VERIFY: {property_desc}")
        parts.append("")

    # System prompt part
    var_names = [sv.symbol for sv in sw_vars]
    var_refs  = [sv.ref    for sv in sw_vars]
    parts += [
        "YOUR TASK: Generate INDUCTIVE LOOP INVARIANTS that hold at every clock step.",
        "These must be:",
        "  1. TRUE at initial state (when all variables have their init values)",
        "  2. PRESERVED by every transition step",
        "  3. Expressed over the state variables listed above",
        "",
        "CRITICAL RULE: NEVER use division in invariants. Use multiplication equivalents:",
        "  WRONG: sum == i*(i-1)/2",
        "  RIGHT: mul(const(2), sum) == mul(i, sub(i, const(1)))  [i.e. 2*sum == i*(i-1)]",
        "",
        "Think about relationships between variables that hold throughout the loop:",
        "  - Linear combinations (e.g., x + y == 3 * i)",
        "  - Counter bounds (e.g., i <= n)",
        "  - Triangular sums: 2*sum == i*(i-1)  NOT sum == i*(i-1)/2",
        "  - Equality invariants (e.g., x == y when both updated identically)",
        "  - Phase conditions (e.g., x == 2*i when mode==0)",
        "",
        "OUTPUT FORMAT — return a single JSON object:",
        '{',
        '  "candidates": [',
        '    {',
        '      "id": 1,',
        '      "kind": "Type1_invariant",',
        '      "verilog_expr": "x + y == 3 * i",',
        '      "predicate_ast": {',
        '        "form": "eq",',
        '        "args": [',
        '          {"form": "add", "args": [{"form":"ref","ref":"STATE_X"}, {"form":"ref","ref":"STATE_Y"}]},',
        '          {"form": "mul", "args": [{"form":"const","const":"3","width":W}, {"form":"ref","ref":"STATE_I"}]}',
        '        ]',
        '      },',
        '      "intuition": "each step adds exactly 3 to x+y and 1 to i"',
        '    }',
        '  ]',
        '}',
        "",
        "PREDICATE AST FORMS: ref, const, eq, ne, ult, ule, ugt, uge, add, sub, mul, not, and, or, implies",
        "  ref:   {\"form\":\"ref\", \"ref\":\"<stateN>\"}",
        "  const: {\"form\":\"const\", \"const\":\"<decimal>\", \"width\":<bits>}",
        "",
        f"STATE REFS for this circuit: {dict(zip(var_names, var_refs))}",
        "",
        "Generate 3-8 invariant candidates, most likely inductive first.",
    ]

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 3. AST → BTOR2 node generator
# ---------------------------------------------------------------------------

_ARITH_FORMS = frozenset(['add', 'sub', 'mul', 'and', 'or', 'not'])
_CMP_FORMS   = frozenset(['eq', 'ne', 'ult', 'ule', 'ugt', 'uge', 'slt', 'sle', 'sgt', 'sge'])

# BTOR2 uses 4-letter comparison names: ulte/ugte/slte/sgte
_BTOR2_OP = {'ule': 'ulte', 'uge': 'ugte', 'sle': 'slte', 'sge': 'sgte'}

class Btor2Builder:
    """Incrementally builds BTOR2 lines and tracks sort → lineno mappings."""

    def __init__(self, existing_lines: List[str], info: BTOR2Info):
        self.lines = list(existing_lines)
        self.info  = info
        self.next_ln = self._find_max_ln() + 1

        # Build sort map: width → existing sort lineno
        self.sort_map: Dict[int, str] = {}
        for l in self.lines:
            p = l.split()
            if len(p) == 4 and p[1] == 'sort' and p[2] == 'bitvec':
                self.sort_map[int(p[3])] = p[0]

        # Build ref map: state ref string → lineno string
        self.ref_to_ln: Dict[str, str] = {sv.ref: str(sv.lineno) for sv in info.states}

    def _find_max_ln(self) -> int:
        mx = 0
        for l in self.lines:
            p = l.split()
            if p and p[0].isdigit():
                mx = max(mx, int(p[0]))
        return mx

    def get_sort(self, width: int) -> str:
        """Return lineno for sort bitvec <width>, creating one if needed."""
        if width not in self.sort_map:
            ln = str(self.next_ln); self.next_ln += 1
            self.lines.append(f"{ln} sort bitvec {width}")
            self.sort_map[width] = ln
        return self.sort_map[width]

    def emit(self, op: str, sort_ln: str, *args: str) -> str:
        """Emit a BTOR2 line and return its lineno."""
        ln = str(self.next_ln); self.next_ln += 1
        args_str = " ".join(str(a) for a in args)
        self.lines.append(f"{ln} {op} {sort_ln} {args_str}")
        return ln

    def emit_const(self, value: int, width: int) -> str:
        sort_ln = self.get_sort(width)
        binary = format(value & ((1 << width) - 1), f'0{width}b')
        return self.emit("const", sort_ln, binary)

    def emit_constraint(self, pred_ln: str):
        ln = str(self.next_ln); self.next_ln += 1
        self.lines.append(f"{ln} constraint {pred_ln}")

    def emit_bad(self, pred_ln: str):
        """Emit 'bad pred' (used for invariant verification: bad = NOT(invariant))."""
        sort1 = self.get_sort(1)
        neg_ln = self.emit("not", sort1, pred_ln)
        ln = str(self.next_ln); self.next_ln += 1
        self.lines.append(f"{ln} bad {neg_ln}")


def _infer_width(ast: dict, info: BTOR2Info, ref_to_ln: Dict[str, str]) -> int:
    """Infer bit-width of an AST node."""
    form = ast.get("form", "")
    if form == "ref":
        ref = ast.get("ref", "")
        for sv in info.states:
            if sv.ref == ref:
                return sv.width
        return 1
    if form == "const":
        return int(ast.get("width", 1))
    if form in _CMP_FORMS:
        return 1
    if form in _ARITH_FORMS:
        args = ast.get("args", [])
        if args:
            return _infer_width(args[0], info, ref_to_ln)
        return 1
    return 1


def _compute_output_width(ast: dict, info: BTOR2Info) -> int:
    """
    Compute the actual output bit-width of an AST node (after operations).
    Arithmetic ops preserve the widest operand width (BTOR2 semantics).
    Comparison ops always output 1 bit.
    """
    form = ast.get("form", "")
    if form == "ref":
        ref = ast.get("ref", "")
        for sv in info.states:
            if sv.ref == ref:
                return sv.width
        return 1
    if form == "const":
        return int(ast.get("width", 1))
    if form in _CMP_FORMS or form == "not":
        return 1
    if form in _ARITH_FORMS:
        args = ast.get("args", [])
        widths = [_compute_output_width(a, info) for a in args]
        return max(widths) if widths else 1
    return 1


def ast_to_btor2(ast: dict, builder: Btor2Builder, target_width: Optional[int] = None) -> str:
    """
    Recursively convert predicate AST to BTOR2 nodes.
    Returns the lineno of the resulting node.
    target_width: if set, zero-extend leaves to this width before operating.
    """
    form = ast.get("form", "")

    if form == "ref":
        ref = ast.get("ref", "")
        ln = builder.ref_to_ln.get(ref)
        if ln is None:
            raise ValueError(f"Unknown ref: {ref}")
        actual_w = _compute_output_width(ast, builder.info)
        if target_width and target_width > actual_w:
            ln = builder.emit("uext", builder.get_sort(target_width), ln,
                              str(target_width - actual_w))
        return ln

    if form == "const":
        value = int(ast.get("const", "0"))
        width = int(ast.get("width", 1))
        use_w = max(width, target_width or 0)
        return builder.emit_const(value, use_w)

    if form == "not" and form in _ARITH_FORMS:
        args = ast.get("args", [])
        if len(args) == 1:
            arg_w = _compute_output_width(args[0], builder.info)
            w = max(arg_w, target_width or 0)
            arg_ln = ast_to_btor2(args[0], builder, w)
            return builder.emit("not", builder.get_sort(w), arg_ln)

    if form in _ARITH_FORMS:
        args = ast.get("args", [])
        if len(args) == 1:  # not
            arg_w = _compute_output_width(args[0], builder.info)
            w = max(arg_w, target_width or 0)
            arg_ln = ast_to_btor2(args[0], builder, w)
            return builder.emit(form, builder.get_sort(w), arg_ln)
        if len(args) == 2:
            w0 = _compute_output_width(args[0], builder.info)
            w1 = _compute_output_width(args[1], builder.info)
            w = max(w0, w1, target_width or 0)
            a0 = ast_to_btor2(args[0], builder, w)
            a1 = ast_to_btor2(args[1], builder, w)
            return builder.emit(form, builder.get_sort(w), a0, a1)

    if form in _CMP_FORMS:
        args = ast.get("args", [])
        if len(args) == 2:
            # Both comparison args must have same width — use max of their natural widths
            w0 = _compute_output_width(args[0], builder.info)
            w1 = _compute_output_width(args[1], builder.info)
            w = max(w0, w1)
            a0 = ast_to_btor2(args[0], builder, w)
            a1 = ast_to_btor2(args[1], builder, w)
            btor2_op = _BTOR2_OP.get(form, form)
            return builder.emit(btor2_op, builder.get_sort(1), a0, a1)

    if form == "implies":
        args = ast.get("args", [])
        if len(args) == 2:
            sort1 = builder.get_sort(1)
            a0 = ast_to_btor2(args[0], builder)
            a1 = ast_to_btor2(args[1], builder)
            not_a0 = builder.emit("not", sort1, a0)
            return builder.emit("or", sort1, not_a0, a1)

    raise ValueError(f"Unsupported AST form: {form}")



# ---------------------------------------------------------------------------
# 3b. Portfolio fast-path engine (k-induction / interpolation)
# ---------------------------------------------------------------------------

def try_fast_engines(btor2_path: str, k: int = 50, timeout_s: int = 5) -> Optional[str]:
    """
    Try ind and interp in PARALLEL before falling back to LLM + IC3IA.
    Returns the winning engine name if either proves UNSAT within timeout_s, else None.

    Both engines run concurrently so total overhead is max(ind_time, interp_time),
    not their sum. With timeout_s=5, max overhead for failing circuits is 5s.

    Use case: bounded-path circuits (location-bit FSMs, concurrent programs) where
    k-induction proves in <2s but IC3IA times out indefinitely.
    """
    result_engine: list[Optional[str]] = [None]
    done = threading.Event()

    def _try(engine: str) -> None:
        try:
            r = subprocess.run(
                [PONO_BIN, '-e', engine, '-k', str(k), btor2_path],
                capture_output=True, text=True, timeout=timeout_s,
            )
            if r.returncode == 1 and not done.is_set():  # UNSAT
                result_engine[0] = engine
                done.set()
        except Exception:
            pass

    threads = [threading.Thread(target=_try, args=(e,), daemon=True) for e in ('ind', 'interp')]
    for t in threads:
        t.start()
    done.wait(timeout=timeout_s + 0.5)
    return result_engine[0]


# ---------------------------------------------------------------------------
# 4. Invariant verifier (SMT soundness check)
# ---------------------------------------------------------------------------

PONO_BIN = os.path.join(os.path.dirname(__file__), '..', 'build', 'pono')


def verify_invariant(ast: dict, btor2_path: str, timeout_s: int = 15) -> Tuple[bool, str]:
    """
    Verify that `ast` is an inductive invariant of the circuit at `btor2_path`.

    Method: add `bad = NOT(invariant)` to the circuit and run IC3IA.
    If IC3IA says UNSAT → invariant holds for all reachable states → SOUND.
    If SAT/timeout → invariant may be wrong → REJECT.

    Returns (is_sound, reason).
    """
    try:
        info = parse_btor2(btor2_path)
    except Exception as e:
        return False, f"parse error: {e}"

    with open(btor2_path) as f:
        orig_lines = f.read().strip().split('\n')

    # Remove original bad/output statements to isolate invariant check
    filtered = [l for l in orig_lines
                if not (l.split()[:2] if l.split() else [''])[1:2] or
                (l.split()[1] if len(l.split()) > 1 else '') not in ('bad', 'output', 'justice', 'fair')]

    builder = Btor2Builder(filtered, info)
    try:
        pred_ln = ast_to_btor2(ast, builder)
    except Exception as e:
        return False, f"AST→BTOR2 error: {e}"

    # Add bad = NOT(invariant)
    builder.emit_bad(pred_ln)

    modified = '\n'.join(builder.lines) + '\n'
    with tempfile.NamedTemporaryFile(mode='w', suffix='.btor2', delete=False) as f:
        f.write(modified)
        tmp_path = f.name

    try:
        r = subprocess.run(
            [PONO_BIN, '-e', 'ic3ia', tmp_path],
            capture_output=True, text=True, timeout=timeout_s
        )
        result = r.stdout.strip().split('\n')[0] if r.stdout.strip() else "err"
        if result == 'unsat':
            return True, "verified (ic3ia unsat)"
        elif result == 'sat':
            return False, "counterexample exists (sat)"
        else:
            return False, f"inconclusive: {result}"
    except subprocess.TimeoutExpired:
        return False, "timeout during verification"
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# 5. Inject verified invariants into BTOR2
# ---------------------------------------------------------------------------

def inject_as_constraints(asts: List[dict], btor2_path: str) -> Tuple[Optional[str], int]:
    """
    Inject a list of verified invariant ASTs as BTOR2 constraint statements.
    Returns (modified_path, count_injected) or (None, 0) on error.
    """
    try:
        info = parse_btor2(btor2_path)
    except Exception as e:
        print(f"[arith] inject: parse error: {e}", file=sys.stderr)
        return None, 0

    with open(btor2_path) as f:
        orig_lines = f.read().strip().split('\n')

    builder = Btor2Builder(orig_lines, info)
    injected = 0
    for ast in asts:
        try:
            pred_ln = ast_to_btor2(ast, builder)
            builder.emit_constraint(pred_ln)
            injected += 1
        except Exception as e:
            print(f"[arith] inject: AST→BTOR2 error for {ast}: {e}", file=sys.stderr)

    if injected == 0:
        return None, 0

    modified = '\n'.join(builder.lines) + '\n'
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.btor2', delete=False)
    tmp.write(modified)
    tmp.close()
    return tmp.name, injected


# ---------------------------------------------------------------------------
# 6. End-to-end software-benchmark pre-processor
# ---------------------------------------------------------------------------

def _ast_has_arithmetic(ast: dict) -> bool:
    """Return True if AST contains at least one add/sub/mul node."""
    if ast.get("form") in ("add", "sub", "mul"):
        return True
    return any(_ast_has_arithmetic(a) for a in ast.get("args", []))


def _is_proof_fast(btor2_path: str, timeout_s: int = 3) -> bool:
    """Return True if IC3IA proves the circuit within timeout_s seconds."""
    try:
        r = subprocess.run(
            [PONO_BIN, '-e', 'ic3ia', '-k', '500', btor2_path],
            capture_output=True, text=True, timeout=timeout_s + 1
        )
        result = r.stdout.strip().split('\n')[0] if r.stdout.strip() else ""
        return result == 'unsat'
    except (subprocess.TimeoutExpired, Exception):
        return False


def _has_accumulator_pattern(info: BTOR2Info, sw_vars) -> bool:
    """
    Return True if any software variable accumulates another software variable.
    Pattern: X's next-expr contains add(A, B) where B is another sw var.
    Example: sum' = sum + i — sum accumulates i, so triangular invariants exist.
    """
    sw_linenos = {sv.lineno for sv in sw_vars}
    for sv in sw_vars:
        next_ln = info.next_map.get(sv.ref)
        if next_ln is None:
            continue
        visited: set = set()
        stack = [next_ln]
        while stack:
            ln = stack.pop()
            if ln in visited:
                continue
            visited.add(ln)
            if info.ops.get(ln) == "add":
                all_deps = info.deps.get(ln, [])
                for arg in (all_deps[1:] if all_deps else []):
                    if arg in sw_linenos and arg != sv.lineno:
                        return True
            for dep in info.deps.get(ln, []):
                if dep not in visited:
                    stack.append(dep)
    return False


def _build_retry_prompt(req: dict, info: BTOR2Info) -> str:
    """Prompt for retry when only simple bounds were found on first LLM attempt."""
    base = build_software_prompt(req, info)
    hint = "\n".join([
        "",
        "=== RETRY: PREVIOUS ATTEMPT FOUND ONLY SIMPLE BOUNDS ===",
        "Simple comparison invariants were verified but are INSUFFICIENT.",
        "The model checker still times out — a stronger arithmetic invariant is needed.",
        "",
        "FIND AN INVARIANT USING MULTIPLICATION.",
        "",
        "KEY PATTERN: If a variable ACCUMULATES another variable each step:",
        "  acc' = acc + counter  →  invariant: 2*acc == counter*(counter-1)",
        "  Example: sum' = sum + i  →  2*sum == i*(i-1)",
        "  Example:   c' = c + i   →  2*c == i*(i-1)",
        "",
        "Try the INEQUALITY version first (often easier for the verifier):",
        "  {\"form\": \"ule\", \"args\": [",
        "    {\"form\": \"mul\", \"args\": [{\"form\":\"const\",\"const\":\"2\",\"width\":W}, {\"form\":\"ref\",\"ref\":\"state_ACC\"}]},",
        "    {\"form\": \"mul\", \"args\": [{\"form\":\"ref\",\"ref\":\"state_I\"}, {\"form\":\"sub\",\"args\":[{\"form\":\"ref\",\"ref\":\"state_I\"},{\"form\":\"const\",\"const\":\"1\",\"width\":W}]}]}",
        "  ]}",
        "  meaning: 2*acc <= i*(i-1)",
        "",
        "Generate ONLY candidates with mul in their predicate_ast.",
        "=== END RETRY HINT ===",
    ])
    return base + hint


def preprocess_software_benchmark(
    btor2_path: str,
    client,
    request: Optional[dict] = None,
    timeout_s: int = 8,
) -> Tuple[str, int, Optional[str]]:
    """
    Full pre-processing for software-origin benchmarks.

    1. Detect software origin (C-style variable names).
    2. Portfolio fast-path: try k-induction and interpolation (5s parallel).
    3. Inject structural sym-pair equalities (e.g. eq(x,y) for structurally equal vars).
    4. Build LLM prompt and call LLM for arithmetic loop invariants.
    5. Verify each LLM candidate via IC3IA (verify_invariant).
    6. Inject all sound invariants as BTOR2 `constraint` statements.

    Returns (constrained_btor2_path, n_injected, fast_engine).
    - fast_engine is set when the circuit was proved by ind/interp; use that engine, not IC3IA.
    - n_injected == -1 when fast_engine is set (no LLM preprocessing was done).
    - If not software-origin or no sound invariants found: (btor2_path, 0, None).
    """
    from btor2_reader import detect_symmetric_pairs, hot_refs_near_bad
    from invariant_prompt import INVARIANT_SYSTEM_PROMPT, parse_invariant_response
    try:
        info = parse_btor2(btor2_path)
    except Exception:
        return btor2_path, 0, None

    if not detect_software_origin(info):
        return btor2_path, 0, None

    # Step 0: Portfolio fast-path — try ind and interp in parallel (5s cap).
    # Bounded-path circuits (location-bit FSMs, concurrent programs) prove in <2s;
    # arithmetic-loop circuits (fib_*, 93.c) cause both to timeout, adding only 5s overhead.
    fast_engine = try_fast_engines(btor2_path, k=50, timeout_s=5)
    if fast_engine:
        print(f"[preprocess_sw] fast engine '{fast_engine}' proved circuit directly (no LLM needed)", file=sys.stderr)
        return btor2_path, -1, fast_engine

    req = request or {}
    req = dict(req)
    req.setdefault("benchmark", os.path.basename(btor2_path))
    req.setdefault("btor2_path", btor2_path)

    sw_vars = get_software_vars(info)
    sw_refs = [sv.ref for sv in sw_vars]

    # Phase 1: inject structural sym-pair equalities before calling LLM.
    # If two state vars have identical init values and identical transition
    # dependency structure, eq(A,B) is inductive — inject it without LLM.
    sound_asts: List[dict] = []
    injected_sym_pairs: set = set()
    try:
        sym_pairs = detect_symmetric_pairs(info, sw_refs)
        for ref_a, ref_b in sym_pairs:
            eq_ast = {
                "form": "eq",
                "args": [{"form": "ref", "ref": ref_a}, {"form": "ref", "ref": ref_b}],
            }
            ok, reason = verify_invariant(eq_ast, btor2_path, timeout_s=timeout_s)
            sym_a = next((sv.symbol for sv in sw_vars if sv.ref == ref_a), ref_a)
            sym_b = next((sv.symbol for sv in sw_vars if sv.ref == ref_b), ref_b)
            if ok:
                print(f"[preprocess_sw] SOUND sym_pair eq({sym_a},{sym_b})", file=sys.stderr)
                sound_asts.append(eq_ast)
                injected_sym_pairs.add(frozenset([ref_a, ref_b]))
            else:
                print(f"[preprocess_sw] sym_pair eq({sym_a},{sym_b}) rejected ({reason})", file=sys.stderr)
    except Exception as e:
        print(f"[preprocess_sw] sym_pair detection failed: {e}", file=sys.stderr)

    # Phase 2: call LLM for arithmetic invariants
    prompt = build_software_prompt(req, info)
    try:
        text, tokens, ms = client.call(
            prompt,
            system_prompt=INVARIANT_SYSTEM_PROMPT,
            reasoning_effort=req.get("reasoning_effort", "none"),
            max_tokens=2048,
        )
    except Exception as e:
        print(f"[preprocess_sw] LLM call failed: {e}", file=sys.stderr)
        if not sound_asts:
            return btor2_path, 0, None
        # Fall through — inject sym_pairs even if LLM failed
        text = '{"candidates":[]}'

    # Phase 3: verify LLM candidates in two rounds.
    # Round 1: verify each candidate against original circuit (fast timeout).
    # Round 2: for those that timed out, retry with all Round-1 sound invariants
    #          injected as constraints (strengthened circuit). This handles
    #          invariants that are only verifiable conditioned on simpler invariants
    #          (e.g., 2*sum==i*(i-1) is only tractable for IC3IA when i<=n is known).
    candidates = parse_invariant_response(text)
    r1_candidates = []  # (ast, expr) pairs to verify in round 1
    for c in candidates:
        ast = c.get("predicate_ast")
        expr = c.get("verilog_expr", "?")
        if not ast:
            continue
        # Skip eq(A,B) pairs already covered by sym_pair injection
        if ast.get("form") == "eq":
            args = ast.get("args", [])
            if (len(args) == 2 and args[0].get("form") == "ref"
                    and args[1].get("form") == "ref"):
                pair = frozenset([args[0]["ref"], args[1]["ref"]])
                if pair in injected_sym_pairs:
                    print(f"[preprocess_sw] skipping duplicate sym_pair {expr!r}", file=sys.stderr)
                    continue
        # Only inject predicates with arithmetic content (add/mul/sub).
        # Pure ref-ref comparisons (i<=n) are also kept as they're cheap structural bounds.
        # Skip ref-const comparisons (n==40, i<=40) — they add IC3IA predicate dimensions
        # without helping convergence, and can slow down the proof.
        args = ast.get("args", [])
        has_arith = _ast_has_arithmetic(ast)
        is_ref_ref = (len(args) == 2 and
                      all(a.get("form") == "ref" for a in args))
        if not (has_arith or is_ref_ref):
            print(f"[preprocess_sw] skipping const-bound {expr!r}", file=sys.stderr)
            continue
        r1_candidates.append((ast, expr))

    # Round 1: parallel scan (short timeout) to find easy invariants.
    # Candidates are verified concurrently — up to 4 pono processes at once.
    r1_timeout = min(4, timeout_s)
    r2_retry: List[Tuple[dict, str]] = []
    if r1_candidates:
        _n_workers = min(len(r1_candidates), 4)
        with ThreadPoolExecutor(max_workers=_n_workers) as _pool:
            _futs = {
                _pool.submit(verify_invariant, ast, btor2_path, r1_timeout): (ast, expr)
                for ast, expr in r1_candidates
            }
            for _fut in as_completed(_futs):
                ast, expr = _futs[_fut]
                ok, reason = _fut.result()
                if ok:
                    print(f"[preprocess_sw] SOUND {expr!r}", file=sys.stderr)
                    sound_asts.append(ast)
                elif "timeout" in reason:
                    print(f"[preprocess_sw] timeout → round2 retry: {expr!r}", file=sys.stderr)
                    r2_retry.append((ast, expr))
                    if ast.get("form") == "eq" and len(ast.get("args", [])) == 2:
                        ule_ast = {"form": "ule", "args": ast["args"]}
                        r2_retry.append((ule_ast, f"{expr} [→ ule fallback]"))
                else:
                    print(f"[preprocess_sw] rejected {expr!r} ({reason})", file=sys.stderr)

    # Round 2: verify timed-out candidates with all round-1 sound invariants as helpers.
    # Sound invariants hold at all reachable states, so injecting them doesn't change
    # the reachable set — verification against the strengthened circuit is still sound.
    if r2_retry and sound_asts:
        helper_path, _ = inject_as_constraints(sound_asts, btor2_path)
        if helper_path:
            _r2_timeout = timeout_s + 2
            with ThreadPoolExecutor(max_workers=min(len(r2_retry), 4)) as _pool2:
                _futs2 = {
                    _pool2.submit(verify_invariant, ast, helper_path, _r2_timeout): (ast, expr)
                    for ast, expr in r2_retry
                }
                for _fut2 in as_completed(_futs2):
                    ast, expr = _futs2[_fut2]
                    ok, reason = _fut2.result()
                    if ok:
                        print(f"[preprocess_sw] SOUND (r2+helpers) {expr!r}", file=sys.stderr)
                        sound_asts.append(ast)
                    else:
                        print(f"[preprocess_sw] rejected (r2) {expr!r} ({reason})", file=sys.stderr)
            os.unlink(helper_path)

    if not sound_asts:
        return btor2_path, 0, None

    # Deduplicate sound ASTs by canonical JSON representation
    import json
    seen_ast_keys: set = set()
    deduped: List[dict] = []
    for ast in sound_asts:
        key = json.dumps(ast, sort_keys=True)
        if key not in seen_ast_keys:
            seen_ast_keys.add(key)
            deduped.append(ast)
    if len(deduped) < len(sound_asts):
        print(f"[preprocess_sw] deduplicated {len(sound_asts)} → {len(deduped)} constraints",
              file=sys.stderr)
    sound_asts = deduped

    # -----------------------------------------------------------------------
    # Retry: if no arithmetic invariants found but the circuit has an
    # accumulator pattern (X' = X + Y where Y is another sw var), the LLM
    # likely generated only simple bounds. Retry with an explicit hint.
    # -----------------------------------------------------------------------
    _MAX_LLM_RETRIES = 2
    for _retry in range(_MAX_LLM_RETRIES):
        if any(_ast_has_arithmetic(a) for a in sound_asts):
            break
        if not _has_accumulator_pattern(info, sw_vars):
            break
        # Probe: if current sound_asts already prove the circuit quickly, skip.
        # This avoids a wasted retry for circuits like fib_05 where sym_pair
        # equalities are sufficient even though they're not "arithmetic".
        if sound_asts:
            _probe_path, _ = inject_as_constraints(sound_asts, btor2_path)
            if _probe_path:
                _probe_fast = _is_proof_fast(_probe_path, timeout_s=3)
                os.unlink(_probe_path)
                if _probe_fast:
                    break
        print(f"[preprocess_sw] no arithmetic invariants; retry {_retry+1}/{_MAX_LLM_RETRIES}",
              file=sys.stderr)
        try:
            retry_text, _, _ = client.call(
                _build_retry_prompt(req, info),
                system_prompt=INVARIANT_SYSTEM_PROMPT,
                reasoning_effort=req.get("reasoning_effort", "none"),
                max_tokens=2048,
            )
        except Exception as e:
            print(f"[preprocess_sw] LLM retry failed: {e}", file=sys.stderr)
            break
        retry_cands = parse_invariant_response(retry_text)
        retry_arith: List[Tuple[dict, str]] = [
            (c["predicate_ast"], c.get("verilog_expr", "?"))
            for c in retry_cands
            if c.get("predicate_ast") and _ast_has_arithmetic(c["predicate_ast"])
        ]
        if not retry_arith:
            print(f"[preprocess_sw] retry {_retry+1}: LLM generated no arithmetic candidates",
                  file=sys.stderr)
            continue

        # Round 1: verify with existing sound_asts as helpers (parallel)
        retry_helper_path: Optional[str] = None
        if sound_asts:
            retry_helper_path, _ = inject_as_constraints(sound_asts, btor2_path)

        r2_retry_new: List[Tuple[dict, str]] = []
        new_sound: List[dict] = []
        _rtgt = retry_helper_path or btor2_path
        with ThreadPoolExecutor(max_workers=min(len(retry_arith), 4)) as _pr1:
            _rfuts = {
                _pr1.submit(verify_invariant, ast, _rtgt, r1_timeout): (ast, expr)
                for ast, expr in retry_arith
            }
            for _rf in as_completed(_rfuts):
                ast, expr = _rfuts[_rf]
                ok, reason = _rf.result()
                if ok:
                    print(f"[preprocess_sw] SOUND (retry-r1) {expr!r}", file=sys.stderr)
                    new_sound.append(ast)
                elif "timeout" in reason:
                    r2_retry_new.append((ast, expr))
                    if ast.get("form") == "eq" and len(ast.get("args", [])) == 2:
                        ule_ast = {"form": "ule", "args": ast["args"]}
                        r2_retry_new.append((ule_ast, f"{expr} [→ ule fallback]"))

        # Round 2: timed-out candidates with expanded helper set (parallel)
        if r2_retry_new:
            combined = list(sound_asts) + new_sound
            r2h, _ = inject_as_constraints(combined, btor2_path) if combined else (None, 0)
            if r2h:
                with ThreadPoolExecutor(max_workers=min(len(r2_retry_new), 4)) as _pr2:
                    _rfuts2 = {
                        _pr2.submit(verify_invariant, ast, r2h, timeout_s + 2): (ast, expr)
                        for ast, expr in r2_retry_new
                    }
                    for _rf2 in as_completed(_rfuts2):
                        ast, expr = _rfuts2[_rf2]
                        ok, reason = _rf2.result()
                        if ok:
                            print(f"[preprocess_sw] SOUND (retry-r2) {expr!r}", file=sys.stderr)
                            new_sound.append(ast)
                os.unlink(r2h)

        if retry_helper_path:
            os.unlink(retry_helper_path)

        if new_sound:
            sound_asts.extend(new_sound)
            seen_r: set = set()
            deduped_r: List[dict] = []
            for ast in sound_asts:
                k = json.dumps(ast, sort_keys=True)
                if k not in seen_r:
                    seen_r.add(k)
                    deduped_r.append(ast)
            sound_asts = deduped_r

    constrained_path, n = inject_as_constraints(sound_asts, btor2_path)
    if constrained_path:
        print(f"[preprocess_sw] injected {n} constraints → {constrained_path}", file=sys.stderr)
        return constrained_path, n, None
    return btor2_path, 0, None
