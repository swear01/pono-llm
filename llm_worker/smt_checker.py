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
            if p[0] == "init" and len(p) >= 4 and p[2] in self.state_sorts:
                sid = p[2]
                name = f"state{sid}"
                init_expr = p[3]
                if init_expr in btor and btor[init_expr][0] == "const":
                    val = int(btor[init_expr][2]) if len(btor[init_expr]) > 2 else 0
                    w = self.state_sorts[name].bv_size()
                    self.init_values[name] = val

        # Find inputs
        for lid, p in btor.items():
            if p[0] == "input":
                name = p[2] if len(p) > 2 else f"input{lid}"
                sort = self.tm.mk_bv_sort(1)
                self.input_vars[name] = self.tm.mk_const(sort, name)

    def _translate(self, lid: str, suffix: str = "", depth: int = 0) -> Optional[bz.Term]:
        """Translate a BTOR2 expression to Bitwuzla Term. Returns None for unsupported ops."""
        if depth > 20: return None  # prevent infinite recursion
        cache_key = lid + suffix
        if cache_key in self.cache: return self.cache[cache_key]
        if lid not in self.btor: return None

        p = self.btor[lid]
        op = p[0]

        if op == "const":
            w = int(p[1]) if len(p) > 1 else 1
            val = int(p[2]) if len(p) > 2 else 0
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

        def t(a):
            return self._translate(a, suffix, depth + 1)

        if op == "not" and len(p) >= 3:
            a = t(p[2])
            return self.tm.mk_term(bz.Kind.BV_NOT, [a]) if a is not None else None

        if op == "and" and len(p) >= 4:
            a, b = t(p[2]), t(p[3])
            return self.tm.mk_term(bz.Kind.BV_AND, [a, b]) if a is not None and b is not None else None

        if op == "or" and len(p) >= 4:
            a, b = t(p[2]), t(p[3])
            return self.tm.mk_term(bz.Kind.BV_OR, [a, b]) if a is not None and b is not None else None

        if op == "eq" and len(p) >= 4:
            a, b = t(p[2]), t(p[3])
            return self.tm.mk_term(bz.Kind.EQUAL, [a, b]) if a is not None and b is not None else None

        if op == "ite" and len(p) >= 5:
            a, b, c = t(p[2]), t(p[3]), t(p[4])
            return self.tm.mk_term(bz.Kind.ITE, [a, b, c]) if all(x is not None for x in [a, b, c]) else None

        if op == "uext" and len(p) >= 3:
            a = t(p[2])
            return a  # simplified: treating uext as passthrough for same-width

        return None  # unsupported op

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
        """Return next-state constraints. Returns empty list if any op is unsupported."""
        constraints = []
        for lid, p in self.btor.items():
            if p[0] == "next" and len(p) >= 4:
                sid = p[2]
                name = f"state{sid}"
                next_term = self._translate(p[3], "_next")
                if next_term is None: return []  # bail on unsupported
                var = self.next_vars.get(name)
                if var is None: return []
                constraints.append(self.tm.mk_term(bz.Kind.EQUAL, [var, next_term]))
        return constraints


def lemma_to_smt(lemma: str, vars_dict: Dict[str, bz.Term],
                tm: bz.TermManager) -> Optional[bz.Term]:
    """Convert a lemma string to a Bitwuzla Boolean term."""
    if not vars_dict: return None

    lemma = lemma.strip().replace(" ", "")

    # Mutual exclusion: !(x && y)
    m = re.match(r"!\(\s*state(\d+)\s*&&\s*state(\d+)\s*\)", lemma)
    if m:
        x = vars_dict.get(f"state{m.group(1)}")
        y = vars_dict.get(f"state{m.group(2)}")
        if x is None or y is None: return None
        zero = tm.mk_bv_value(x.sort(), 0)
        return tm.mk_term(
            bz.Kind.EQUAL,
            [tm.mk_term(bz.Kind.BV_AND, [x, y]), zero]
        )

    # Equality: (= stateX const)
    m = re.match(r"\(\s*=\s*state(\d+)\s+(\S+)\s*\)", lemma)
    if m:
        x = vars_dict.get(f"state{m.group(1)}")
        if x is None: return None
        val_raw = m.group(2).replace("#b", "").replace("'d", "")
        val = int(val_raw, 2 if "#b" in m.group(2) or val_raw.isdigit() else 10)
        return tm.mk_term(bz.Kind.EQUAL, [x, tm.mk_bv_value(x.sort(), val)])

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
