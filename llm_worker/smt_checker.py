#!/usr/bin/env python3
"""SMT formal checker using Bitwuzla Python bindings.

Supports: init check, one-step check, inductive check.
Translates BTOR2 transition + candidate lemma into SMT queries.
"""

import json, re, os, time
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

try:
    import bitwuzla as bz
    HAS_BITWUZLA = True
except ImportError:
    HAS_BITWUZLA = False


def parse_btor2(path: str) -> dict:
    btor = {}
    for line in open(path):
        parts = line.strip().split()
        if not parts or parts[0][0] == ";": continue
        try: int(parts[0])
        except: continue
        btor[parts[0]] = parts[1:]
    return btor


class BTOR2SMT:
    """Translates BTOR2 expressions to Bitwuzla Terms."""

    def __init__(self, btor: dict):
        self.btor = btor
        self.tm = bz.TermManager()
        self.cache = {}  # lid → Term
        self.state_sorts = {}  # var_name → BitVecSort
        self.state_vars = {}  # var_name → Term (current)
        self.next_vars = {}   # var_name → Term (next-state)
        self.init_values = {} # var_name → init value (0/1)
        self.input_vars = {}  # input_name → Term
        self.sort_map = {}    # sort_id → bitwidth

        # Parse sort declarations: <id> sort bitvec <width>
        for lid, p in btor.items():
            if p[0] == "sort" and len(p) >= 3 and p[1] == "bitvec":
                self.sort_map[lid] = int(p[2])

        # Register state variables
        for lid, p in btor.items():
            if p[0] == "state" and len(p) >= 2:
                w = int(p[1])
                name = f"state{lid}"
                sort = self.tm.mk_bv_sort(w)
                self.state_sorts[name] = sort
                self.state_vars[name] = self.tm.mk_const(sort, name)
                self.next_vars[name] = self.tm.mk_const(sort, name + "_next")

        # Find init values
        for lid, p in btor.items():
            if p[0] == "init" and len(p) >= 4:
                sid = p[2]
                name = f"state{sid}"
                if name not in self.state_sorts:
                    continue
                init_expr = p[3]
                if init_expr in btor and btor[init_expr][0] == "const":
                    val = int(btor[init_expr][2], 2) if len(btor[init_expr]) > 2 else 0
                    self.init_values[name] = val

        # Find inputs with correct bitwidth
        for lid, p in btor.items():
            if p[0] == "input" and len(p) >= 3:
                name = p[2]
                w = int(p[1])
                sort = self.tm.mk_bv_sort(w)
                self.input_vars[name] = self.tm.mk_const(sort, name)

    def _sort_w(self, sort_id: str) -> int:
        w = self.sort_map.get(sort_id)
        if w is not None:
            return w
        return int(sort_id)

    def _as_bool(self, term: bz.Term) -> bz.Term:
        """Convert a 1-bit BV to Boolean if needed."""
        s = term.sort()
        if not s.is_bv():
            return term
        if s.bv_size() == 1:
            one = self.tm.mk_bv_value(self.tm.mk_bv_sort(1), 1)
            return self.tm.mk_term(bz.Kind.EQUAL, [term, one])
        return term

    def _mk_bv1(self, bool_term: bz.Term) -> bz.Term:
        """Convert a Boolean term to a 1-bit BV (0/1)."""
        zero = self.tm.mk_bv_value(self.tm.mk_bv_sort(1), 0)
        one = self.tm.mk_bv_value(self.tm.mk_bv_sort(1), 1)
        return self.tm.mk_term(bz.Kind.ITE, [bool_term, one, zero])

    def _translate(self, lid: str, suffix: str = "", depth: int = 0) -> Optional[bz.Term]:
        """Translate a BTOR2 expression to Bitwuzla Term. Returns None for unsupported ops."""
        if depth > 30: return None
        cache_key = lid + suffix
        if cache_key in self.cache: return self.cache[cache_key]
        if lid not in self.btor: return None

        p = self.btor[lid]
        op = p[0]

        if op == "const":
            w = int(p[1]) if len(p) > 1 else 1
            val_str = p[2] if len(p) > 2 else "0"
            val = int(val_str, 2) if all(c in "01" for c in val_str) else int(val_str)
            return self.tm.mk_bv_value(self.tm.mk_bv_sort(w), val)

        if op == "state":
            name = f"state{lid}"
            return self.next_vars.get(name) if suffix == "_next" else self.state_vars.get(name)

        if op == "input":
            name = p[2] if len(p) > 2 else f"input{lid}"
            return self.input_vars.get(name)

        if op == "zero":
            w = int(p[1]) if len(p) > 1 else 1
            return self.tm.mk_bv_value(self.tm.mk_bv_sort(w), 0)

        if op == "ones":
            w = int(p[1]) if len(p) > 1 else 1
            return self.tm.mk_bv_value(self.tm.mk_bv_sort(w), (1 << w) - 1)

        def t(a):
            return self._translate(a, suffix, depth + 1)

        # Unary ops
        if op == "not" and len(p) >= 3:
            a = t(p[2])
            return self.tm.mk_term(bz.Kind.BV_NOT, [a]) if a is not None else None

        # Binary logical ops
        if op in ("and", "or", "xor", "xnor") and len(p) >= 4:
            a, b = t(p[2]), t(p[3])
            if a is None or b is None: return None
            kind = {"and": bz.Kind.BV_AND, "or": bz.Kind.BV_OR,
                    "xor": bz.Kind.BV_XOR, "xnor": bz.Kind.BV_XNOR}[op]
            return self.tm.mk_term(kind, [a, b])

        if op in ("add", "sub", "srl") and len(p) >= 4:
            a, b = t(p[2]), t(p[3])
            if a is None or b is None: return None
            kind = {"add": bz.Kind.BV_ADD, "sub": bz.Kind.BV_SUB, "srl": bz.Kind.BV_SHR}[op]
            return self.tm.mk_term(kind, [a, b])

        # Comparisons
        if op in ("eq", "neq") and len(p) >= 4:
            a, b = t(p[2]), t(p[3])
            if a is None or b is None: return None
            eq_bool = self.tm.mk_term(bz.Kind.EQUAL, [a, b])
            result = self._mk_bv1(eq_bool)
            if op == "neq":
                return self.tm.mk_term(bz.Kind.BV_NOT, [result])
            return result

        if op in ("ult", "ulte") and len(p) >= 4:
            a, b = t(p[2]), t(p[3])
            if a is None or b is None: return None
            kind = {"ult": bz.Kind.BV_ULT, "ulte": bz.Kind.BV_ULE}[op]
            bool_term = self.tm.mk_term(kind, [a, b])
            return self._mk_bv1(bool_term)

        # Ternary ops
        if op == "ite" and len(p) >= 5:
            a, b, c = t(p[2]), t(p[3]), t(p[4])
            if a is None or b is None or c is None: return None
            return self.tm.mk_term(bz.Kind.ITE, [self._as_bool(a), b, c])

        # slice: extract bits hi:lo from operand
        if op == "slice" and len(p) >= 5:
            src = t(p[2])
            hi, lo = int(p[3]), int(p[4])
            if src is None: return None
            src_w = src.sort().bv_size()
            if lo > hi:
                return None
            if hi >= src_w:
                if lo >= src_w:
                    w = hi - lo + 1
                    return self.tm.mk_bv_value(self.tm.mk_bv_sort(w), 0)
                ext = hi + 1 - src_w
                src = self.tm.mk_term(bz.Kind.BV_ZERO_EXTEND, [src], [ext])
            return self.tm.mk_term(bz.Kind.BV_EXTRACT, [src],
                                   [hi, lo])

        # concat: operand1 (MSB) + operand2 (LSB)
        if op == "concat" and len(p) >= 4:
            a, b = t(p[2]), t(p[3])
            if a is None or b is None: return None
            return self.tm.mk_term(bz.Kind.BV_CONCAT, [a, b])

        # Reduction ops
        if op == "redor" and len(p) >= 3:
            a = t(p[2])
            return self.tm.mk_term(bz.Kind.BV_REDOR, [a]) if a is not None else None

        if op == "redand" and len(p) >= 3:
            a = t(p[2])
            return self.tm.mk_term(bz.Kind.BV_REDAND, [a]) if a is not None else None

        # Zero-extension
        if op == "uext" and len(p) >= 4:
            a = t(p[2])
            ext = int(p[1]) if len(p) > 1 else 0
            if a is None: return None
            src_w = a.sort().bv_size()
            if ext > src_w:
                return self.tm.mk_term(bz.Kind.BV_ZERO_EXTEND, [a], [ext - src_w])
            return a

        return None

    def get_init_constraints(self) -> List[bz.Term]:
        """Return init constraints for all state vars."""
        constraints = []
        for name, val in self.init_values.items():
            var = self.state_vars.get(name)
            if var is None: continue
            sort = var.sort()
            c = self.tm.mk_term(bz.Kind.EQUAL, [var, self.tm.mk_bv_value(sort, val)])
            constraints.append(c)
        return constraints

    def get_transition_constraints(self) -> List[bz.Term]:
        """Return next-state constraints. Skips any that fail translation."""
        constraints = []
        failed = 0
        for lid, p in self.btor.items():
            if p[0] == "next" and len(p) >= 4:
                sid = p[2]
                name = f"state{sid}"
                if name not in self.next_vars:
                    continue
                try:
                    next_term = self._translate(p[3], "_next")
                except Exception:
                    next_term = None
                if next_term is None:
                    failed += 1
                    continue
                var = self.next_vars.get(name)
                if var is None: continue
                try:
                    constraints.append(self.tm.mk_term(bz.Kind.EQUAL, [var, next_term]))
                except Exception:
                    failed += 1
        if failed > 0:
            print(f"  (skipped {failed} transition lines due to translation errors)")
        return constraints


def lemma_to_smt(lemma: str, vars_dict: Dict[str, bz.Term],
                tm: bz.TermManager) -> Optional[bz.Term]:
    """Convert a lemma string to a Bitwuzla Boolean term.

    Handles:
    - (=> (= stateX V) (= stateY V))           guarded implication
    - (=> (= stateX V) (not (= stateY W)))     guarded implication, negated consequent
    - (=> (= stateX V) (<= stateY W))          guarded implication, consequent bound
    - (=> (= stateX V) (>= stateY W))          guarded implication, consequent lower bound
    - (! (and (= stateX V) (= stateY V)))      mutual exclusion
    """
    if not vars_dict or not lemma.strip():
        return None

    lemma_clean = lemma.strip()

    def _mk_eq(var_name: str, val_str: str) -> Optional[bz.Term]:
        """Build (EQUAL var value) with matching widths.
        Handles: plain numbers, #b binary, #x hex, or another state variable.
        """
        var = vars_dict.get(var_name)
        if var is None: return None
        w = var.sort().bv_size()

        # Check if val_str is another state variable
        if re.match(r'state\d+', val_str):
            other = vars_dict.get(val_str)
            if other is None: return None
            return tm.mk_term(bz.Kind.EQUAL, [var, other])

        # Handle #b and #x prefixes, and bare # prefix
        clean = val_str
        if clean.startswith("#b"):
            clean = clean[2:]
            base = 2
        elif clean.startswith("#x"):
            clean = clean[2:]
            base = 16
        elif clean.startswith("#"):
            clean = clean[1:]
            base = 2  # Assume binary for bare #
        else:
            base = 10
        val = int(clean, base)
        return tm.mk_term(bz.Kind.EQUAL, [var, tm.mk_bv_value(tm.mk_bv_sort(w), val)])

    def _mk_bv_val(var_name: str, val_str: str) -> Optional[bz.Term]:
        var = vars_dict.get(var_name)
        if var is None: return None
        val = int(val_str)
        w = var.sort().bv_size()
        return tm.mk_bv_value(tm.mk_bv_sort(w), val)

    # (=> (= stateX V) (= stateY V))  → guarded implication
    m = re.match(
        r'\(\s*=>\s*\(\s*=\s*(state\d+)\s+([#b#x]?\w+)\s*\)\s*\(\s*=\s*(state\d+)\s+([#b#x]?\w+)\s*\)\s*\)',
        lemma_clean)
    if m:
        guard = _mk_eq(m.group(1), m.group(2))
        consequent = _mk_eq(m.group(3), m.group(4))
        if guard is None or consequent is None: return None
        not_guard = tm.mk_term(bz.Kind.NOT, [guard])
        return tm.mk_term(bz.Kind.OR, [not_guard, consequent])

    # (=> (= stateX V) (not (= stateY W)))  → guarded, negated consequent
    m = re.match(
        r'\(\s*=>\s*\(\s*=\s*(state\d+)\s+(\d+)\s*\)\s*\(\s*not\s*\(\s*=\s*(state\d+)\s+(\d+)\s*\)\s*\)\s*\)',
        lemma_clean)
    if m:
        guard = _mk_eq(m.group(1), m.group(2))
        consequent_eq = _mk_eq(m.group(3), m.group(4))
        if guard is None or consequent_eq is None: return None
        not_guard = tm.mk_term(bz.Kind.NOT, [guard])
        neg_consequent = tm.mk_term(bz.Kind.NOT, [consequent_eq])
        return tm.mk_term(bz.Kind.OR, [not_guard, neg_consequent])

    # (=> (= stateX V) (<= stateY W))  → consequent upper bound
    m = re.match(
        r'\(\s*=>\s*\(\s*=\s*(state\d+)\s+(\d+)\s*\)\s*\(\s*<=\s*(state\d+)\s+(\d+)\s*\)\s*\)',
        lemma_clean)
    if m:
        guard = _mk_eq(m.group(1), m.group(2))
        var_y = _mk_bv_val(m.group(3), m.group(4))
        y = vars_dict.get(m.group(3))
        if guard is None or var_y is None or y is None: return None
        consequent = tm.mk_term(bz.Kind.BV_ULE, [y, var_y])
        not_guard = tm.mk_term(bz.Kind.NOT, [guard])
        return tm.mk_term(bz.Kind.OR, [not_guard, consequent])

    # (=> (= stateX V) (>= stateY W))  → consequent lower bound
    m = re.match(
        r'\(\s*=>\s*\(\s*=\s*(state\d+)\s+(\d+)\s*\)\s*\(\s*>=\s*(state\d+)\s+(\d+)\s*\)\s*\)',
        lemma_clean)
    if m:
        guard = _mk_eq(m.group(1), m.group(2))
        var_y = _mk_bv_val(m.group(3), m.group(4))
        y = vars_dict.get(m.group(3))
        if guard is None or var_y is None or y is None: return None
        consequent = tm.mk_term(bz.Kind.BV_UGE, [y, var_y])
        not_guard = tm.mk_term(bz.Kind.NOT, [guard])
        return tm.mk_term(bz.Kind.OR, [not_guard, consequent])

    # (=> (and (= stateX V) (= stateY W)) (= stateZ U))  → guarded with conjunction
    m = re.match(
        r'\(\s*=>\s*\(\s*and\s*\(\s*=\s*(state\d+)\s+(.+?)\s*\)\s*'
        r'\(\s*=\s*(state\d+)\s+(.+?)\s*\)\s*\)\s*'
        r'\(\s*=\s*(state\d+)\s+(.+?)\s*\)\s*\)',
        lemma_clean)
    if m:
        g1 = _mk_eq(m.group(1), m.group(2).strip())
        g2 = _mk_eq(m.group(3), m.group(4).strip())
        cons = _mk_eq(m.group(5), m.group(6).strip())
        if g1 is None or g2 is None or cons is None: return None
        guard = tm.mk_term(bz.Kind.AND, [g1, g2])
        not_guard = tm.mk_term(bz.Kind.NOT, [guard])
        return tm.mk_term(bz.Kind.OR, [not_guard, cons])

    # (! (and (= stateX V) (= stateY V)))  → mutual exclusion
    m = re.match(
        r'\(\s*!\s*\(\s*and\s*\(\s*=\s*(state\d+)\s+(\d+)\s*\)\s*\(\s*=\s*(state\d+)\s+(\d+)\s*\)\s*\)\s*\)',
        lemma_clean)
    if m:
        a = _mk_eq(m.group(1), m.group(2))
        b = _mk_eq(m.group(3), m.group(4))
        if a is None or b is None: return None
        violation = tm.mk_term(bz.Kind.AND, [a, b])
        return tm.mk_term(bz.Kind.NOT, [violation])

    # Fallback: symbolic format
    lemma_nosp = lemma_clean.replace(" ", "")
    m = re.match(r"!\(\s*state(\d+)\s*&&\s*state(\d+)\s*\)", lemma_nosp)
    if m:
        x = vars_dict.get(f"state{m.group(1)}")
        y = vars_dict.get(f"state{m.group(2)}")
        if x is None or y is None: return None
        zero = tm.mk_bv_value(x.sort(), 0)
        return tm.mk_term(bz.Kind.EQUAL,
                          [tm.mk_term(bz.Kind.BV_AND, [x, y]), zero])

    # (=> (= stateX V) (or (= stateY W) (= stateZ U)))  → OR consequent
    m = re.match(
        r'\(\s*=>\s*\(\s*=\s*(state\d+)\s+(\d+)\s*\)\s*\(\s*or\s*\(\s*=\s*(state\d+)\s+(\d+)\s*\)\s*'
        r'\(\s*=\s*(state\d+)\s+(\d+)\s*\)\s*\)\s*\)',
        lemma_clean)
    if m:
        guard = _mk_eq(m.group(1), m.group(2))
        c1 = _mk_eq(m.group(3), m.group(4))
        c2 = _mk_eq(m.group(5), m.group(6))
        if guard is None or c1 is None or c2 is None: return None
        not_guard = tm.mk_term(bz.Kind.NOT, [guard])
        return tm.mk_term(bz.Kind.OR, [not_guard, c1, c2])

    # Standalone: (= stateX stateY)  → variable equality
    m = re.match(r'\(\s*=\s*(state\d+)\s+(state\d+)\s*\)', lemma_clean)
    if not m:
        m = re.match(r'^\s*=\s*(state\d+)\s+(state\d+)$', lemma_clean)
    if m:
        a = vars_dict.get(m.group(1))
        b = vars_dict.get(m.group(2))
        if a is None or b is None: return None
        return tm.mk_term(bz.Kind.EQUAL, [a, b])

    # Standalone: (= stateX V)  → equality with constant
    m = re.match(r'\(\s*=\s*(state\d+)\s+(.+?)\s*\)', lemma_clean)
    if m:
        eq = _mk_eq(m.group(1), m.group(2).strip())
        if eq is None: return None
        return eq

    # Standalone: (<= stateX V)  → upper bound
    m = re.match(r'\(\s*<=\s*(state\d+)\s+(\d+)\s*\)', lemma_clean)
    if m:
        var = vars_dict.get(m.group(1))
        val = int(m.group(2))
        if var is None: return None
        bv_val = tm.mk_bv_value(tm.mk_bv_sort(var.sort().bv_size()), val)
        return tm.mk_term(bz.Kind.BV_ULE, [var, bv_val])

    # Standalone: (>= stateX V)  → lower bound
    m = re.match(r'\(\s*>=\s*(state\d+)\s+(\d+)\s*\)', lemma_clean)
    if m:
        var = vars_dict.get(m.group(1))
        val = int(m.group(2))
        if var is None: return None
        bv_val = tm.mk_bv_value(tm.mk_bv_sort(var.sort().bv_size()), val)
        return tm.mk_term(bz.Kind.BV_UGE, [var, bv_val])

    # Standalone: (not (= stateX V))  → disequality
    m = re.match(r'\(\s*not\s*\(\s*=\s*(state\d+)\s+(.+?)\s*\)\s*\)', lemma_clean)
    if m:
        eq = _mk_eq(m.group(1), m.group(2).strip())
        if eq is None: return None
        return tm.mk_term(bz.Kind.NOT, [eq])

    return None


def run_check(btor_smt: BTOR2SMT, lemma: str) -> dict:
    """Run init + one-step + inductive checks on a lemma."""
    tm = btor_smt.tm
    vars_dict = btor_smt.state_vars
    lemma_term = lemma_to_smt(lemma, vars_dict, tm)

    results = {}

    # Init check
    if lemma_term is not None and btor_smt.init_values:
        solver = bz.Bitwuzla(tm)
        for c in btor_smt.get_init_constraints():
            solver.assert_formula(c)
        solver.assert_formula(tm.mk_term(bz.Kind.NOT, [lemma_term]))
        t0 = time.time()
        r = solver.check_sat()
        results["init"] = {"result": str(r), "time_ms": int((time.time() - t0) * 1000)}
    else:
        results["init"] = {"result": "not_supported"}

    # One-step check: T ⇒ lemma'
    if lemma_term is not None and btor_smt.get_transition_constraints():
        solver = bz.Bitwuzla(tm)
        for c in btor_smt.get_transition_constraints():
            solver.assert_formula(c)
        lemma_next = lemma_to_smt(lemma, btor_smt.next_vars, tm)
        if lemma_next is not None:
            solver.assert_formula(tm.mk_term(bz.Kind.NOT, [lemma_next]))
            t0 = time.time()
            r = solver.check_sat()
            results["one_step"] = {"result": str(r), "time_ms": int((time.time() - t0) * 1000)}
        else:
            results["one_step"] = {"result": "not_supported"}
    else:
        results["one_step"] = {"result": "no_transition"}

    # Inductive check: lemma ∧ T ⇒ lemma'
    if lemma_term is not None and btor_smt.get_transition_constraints():
        solver = bz.Bitwuzla(tm)
        solver.assert_formula(lemma_term)
        for c in btor_smt.get_transition_constraints():
            solver.assert_formula(c)
        lemma_next = lemma_to_smt(lemma, btor_smt.next_vars, tm)
        if lemma_next is not None:
            solver.assert_formula(tm.mk_term(bz.Kind.NOT, [lemma_next]))
            t0 = time.time()
            r = solver.check_sat()
            results["inductive"] = {"result": str(r), "time_ms": int((time.time() - t0) * 1000)}
        else:
            results["inductive"] = {"result": "not_supported"}
    else:
        results["inductive"] = {"result": "no_transition"}

    return results


def run_batch_checks(candidates: List[dict], btor_path: str) -> List[dict]:
    """Run formal checks on a batch of candidates."""
    btor = parse_btor2(btor_path)
    btor_smt = BTOR2SMT(btor)

    results = []
    for cand in candidates:
        lemma = cand.get("lemma", "")
        record = {
            "candidate_id": cand.get("id", "?"),
            "lemma": lemma[:150],
            "schema": cand.get("schema", "unknown"),
        }
        if lemma:
            record["checks"] = run_check(btor_smt, lemma)
        results.append(record)
    return results


if __name__ == "__main__":
    import sys
    btor = os.path.expanduser(
        "~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/"
        "qspiflash_dualflexpress_divfive-p040.btor2"
    )
    samples = [
        {"id": "c1", "lemma": "!(state1359 && state1361)", "schema": "mutual_exclusion"},
        {"id": "c2", "lemma": "(= state1359 0)", "schema": "equality"},
    ]
    results = run_batch_checks(samples, btor)
    for r in results:
        print(json.dumps(r, indent=2))
