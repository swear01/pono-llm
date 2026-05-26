#!/usr/bin/env python3
"""Standalone SMT formal checker using BTOR2 transition system.

Generates SMT queries for:
  - Init check: Init(s) ∧ ¬L(s)
  - One-step:   T(s,i,s') ∧ ¬L(s')
  - Inductive:  L(s) ∧ T(s,i,s') ∧ ¬L(s')

Uses BTOR2 structure to build the transition formula.
"""

import json, re, os, subprocess, tempfile, time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple
from collections import defaultdict


def parse_btor2(path: str) -> dict:
    btor = {}
    for line in open(path):
        parts = line.strip().split()
        if not parts or parts[0][0] == ";": continue
        lid = parts[0]
        try: int(lid)
        except: continue
        btor[lid] = parts[1:]
    return btor


def extract_state_info(btor: dict) -> dict:
    """Extract state var info: name, width, init value, next expr."""
    info = {}
    for lid, p in btor.items():
        if p[0] != "state" or len(p) < 2: continue
        info[lid] = {"name": f"state{lid}", "width": int(p[1]), "init": None, "next": None}

    for lid, p in btor.items():
        if p[0] == "init" and len(p) >= 4 and p[2] in info:
            info[p[2]]["init"] = p[3]
        if p[0] == "next" and len(p) >= 4 and p[2] in info:
            info[p[2]]["next"] = p[3]
    return info


def btor_to_smt_decl(btor: dict, lid: str, suffix: str = "") -> str:
    """Convert a BTOR2 expression to SMT-LIB (simplified)."""
    if lid not in btor: return f"<L{lid}>"
    p = btor[lid]
    op = p[0]

    if op == "const":
        w = int(p[1]) if len(p) > 1 else 1
        v = p[2] if len(p) > 2 else "0"
        return f"(_ bv{v} {w})"

    if op == "state":
        return f"state{lid}{suffix}"

    if op == "input":
        name = p[2] if len(p) > 2 else f"input{lid}"
        return name

    if op in ("zero", "ones"):
        return "error: need width"

    def rec(a): return btor_to_smt_decl(btor, a, suffix) if a in btor else f"<L{a}>"

    if op == "not":
        return f"(bvnot {rec(p[2])})" if len(p) >= 3 else "?"
    if op == "and" and len(p) >= 4:
        return f"(bvand {rec(p[2])} {rec(p[3])})"
    if op == "or" and len(p) >= 4:
        return f"(bvor {rec(p[2])} {rec(p[3])})"
    if op == "eq" and len(p) >= 4:
        return f"(= {rec(p[2])} {rec(p[3])})"
    if op == "neq" and len(p) >= 4:
        return f"(distinct {rec(p[2])} {rec(p[3])})"
    if op == "add" and len(p) >= 4:
        return f"(bvadd {rec(p[2])} {rec(p[3])})"
    if op == "sub" and len(p) >= 4:
        return f"(bvsub {rec(p[2])} {rec(p[3])})"
    if op == "ult" and len(p) >= 4:
        return f"(bvult {rec(p[2])} {rec(p[3])})"
    if op == "ule" and len(p) >= 4:
        return f"(bvule {rec(p[2])} {rec(p[3])})"
    if op == "ugt" and len(p) >= 4:
        return f"(bvugt {rec(p[2])} {rec(p[3])})"
    if op == "uge" and len(p) >= 4:
        return f"(bvuge {rec(p[2])} {rec(p[3])})"
    if op == "ite" and len(p) >= 5:
        return f"(ite {rec(p[2])} {rec(p[3])} {rec(p[4])})"
    if op == "concat" and len(p) >= 4:
        return f"(concat {rec(p[2])} {rec(p[3])})"
    if op == "slice" and len(p) >= 5:
        return f"((_ extract {p[3]} {p[4]}) {rec(p[2])})"
    if op == "uext":
        return f"((_ zero_extend {p[1]}) {rec(p[2])})" if len(p) >= 3 else "?"

    return f"<{op}_{lid}>"


def candidate_to_smt(lemma: str) -> str:
    """Convert a lemma string to an SMT assertion.
    Handles common patterns; returns raw string for complex cases.
    """
    lemma = lemma.strip().replace(" ", "")

    # Mutual exclusion: !(x && y)
    m = re.match(r"!\(\s*state(\d+)\s*&&\s*state(\d+)\s*\)", lemma)
    if m:
        x, y = f"state{m.group(1)}", f"state{m.group(2)}"
        return f"(not (and (= {x} #b1) (= {y} #b1)))"

    # Equality: (= stateX value)
    m = re.match(r"\(\s*=\s*state(\d+)\s+(.+)\s*\)", lemma)
    if m:
        x, v = f"state{m.group(1)}", m.group(2)
        v_clean = v.replace("#b", "").replace("'d", "")
        return f"(= state{m.group(1)} #b{v_clean})"

    # Disequality
    m = re.match(r"\(\s*distinct\s+state(\d+)\[(\d):(\d)\]\s+(.+)\s*\)", lemma)
    if m:
        var, hi, lo, val = m.group(1), m.group(2), m.group(3), m.group(4)
        v = val.replace("2'd", "").replace("'d", "").replace("#b", "")
        return f"(not (= ((_ extract {hi} {lo}) state{var}) #b{v}))"

    # Guarded implication
    m = re.match(r"\(\s*=>\s+\((.+)\)\s+\((.+)\)\s*\)", lemma)
    if m:
        guard, cons = m.group(1), m.group(2)
        return f"(=> ({candidate_to_smt(f'({guard})')}) ({candidate_to_smt(f'(= {cons})')}))"

    return lemma  # return raw for unsupported


def build_smt_check(btor: dict, lemma: str, check_type: str) -> Optional[str]:
    """Build an SMT-LIB query for formal check.

    check_type: 'init', 'one_step', 'inductive'
    """
    state_info = extract_state_info(btor)
    if not state_info: return None

    # Declare state variables
    decls = []
    for lid, info in state_info.items():
        w = info["width"]
        decls.append(f"(declare-fun state{lid} () (_ BitVec {w}))")
        if check_type in ("one_step", "inductive"):
            decls.append(f"(declare-fun state{lid}_next () (_ BitVec {w}))")

    # Declare input variables (one_step/inductive only)
    inputs = set()
    for lid, p in btor.items():
        if p[0] == "input":
            name = p[2] if len(p) > 2 else f"input{lid}"
            inputs.add(name)
    for inp in sorted(inputs):
        decls.append(f"(declare-fun {inp} () (_ BitVec 1))")

    # Init constraint (for init check)
    init_constraints = []
    for lid, info in state_info.items():
        if info["init"]:
            init_val_smt = btor_to_smt_decl(btor, info["init"])
            init_constraints.append(f"(assert (= state{lid} {init_val_smt}))")

    # Transition constraints
    trans_constraints = []
    for lid, info in state_info.items():
        if info["next"]:
            next_smt = btor_to_smt_decl(btor, info["next"], "_next")
            trans_constraints.append(
                f"(assert (= state{lid}_next {next_smt}))"
            )

    # Lemma negation  
    lemma_smt = candidate_to_smt(lemma)
    lemma_neg = f"(assert (not {lemma_smt}))"

    # Assemble query
    parts = ["(set-logic QF_BV)"]
    parts.extend(decls)

    if check_type == "init":
        parts.extend(init_constraints)
        parts.append(lemma_neg)
        parts.append("(check-sat)")
        parts.append("(get-model)")
    elif check_type == "one_step":
        parts.extend(trans_constraints)
        lemma_next = candidate_to_smt(lemma).replace(
            "state", "state"
        )  # use next-state version
        # Replace state vars with next-state vars in lemma
        for lid in state_info:
            lemma_next = lemma_next.replace(f"state{lid})", f"state{lid}_next)")
            lemma_next = lemma_next.replace(f"state{lid} ", f"state{lid}_next ")
        parts.append(f"(assert (not {lemma_next}))")
        parts.append("(check-sat)")
        parts.append("(get-model)")
    elif check_type == "inductive":
        # Assert lemma in current state
        parts.append(f"(assert {lemma_smt})")
        parts.extend(trans_constraints)
        lemma_next = lemma_smt
        for lid in state_info:
            lemma_next = lemma_next.replace(f"state{lid})", f"state{lid}_next)")
            lemma_next = lemma_next.replace(f"state{lid} ", f"state{lid}_next ")
        parts.append(f"(assert (not {lemma_next}))")
        parts.append("(check-sat)")

    return "\n".join(parts)


def run_smt_check(query: str, timeout_ms: int = 5000) -> dict:
    """Run an SMT query using Bitwuzla or Boolector."""
    solver_bin = None
    for cand in ["bitwuzla", "boolector"]:
        p = subprocess.run(["which", cand], capture_output=True)
        if p.returncode == 0:
            solver_bin = cand
            break

    if not solver_bin:
        # Try build/deps path
        for cand in [
            "build/deps/bitwuzla-install/bin/bitwuzla",
            "build/deps/boolector-install/bin/boolector",
        ]:
            if os.path.exists(cand):
                solver_bin = cand
                break

    if not solver_bin:
        return {"result": "no_solver", "detail": "no SMT solver found"}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".smt2", delete=False) as f:
        f.write(query)
        smt_file = f.name

    try:
        start = time.time()
        proc = subprocess.run(
            [solver_bin, smt_file],
            capture_output=True, text=True, timeout=timeout_ms / 1000 + 2,
        )
        elapsed_ms = int((time.time() - start) * 1000)
        output = (proc.stdout + proc.stderr).strip()

        if "unsat" in output.lower():
            result = "pass"
        elif "sat" in output.lower():
            result = "fail"
        else:
            result = "unknown"

        return {
            "result": result,
            "smt_output": output[:500],
            "time_ms": elapsed_ms,
            "query_file": smt_file,
        }
    except subprocess.TimeoutExpired:
        return {"result": "timeout", "time_ms": timeout_ms}
    except Exception as e:
        return {"result": "error", "detail": str(e)}


def run_formal_checks_smt(candidates: List[dict], btor_path: str,
                          checks: List[str] = None) -> List[dict]:
    """Run SMT formal checks on candidates."""
    if checks is None: checks = ["init", "one_step"]
    btor = parse_btor2(btor_path)
    results = []

    for cand in candidates:
        lemma = cand.get("lemma", "")
        if not lemma: continue

        record = {
            "candidate_id": cand.get("id", "?"),
            "lemma": lemma[:150],
            "schema": cand.get("schema", "unknown"),
        }

        for check in checks:
            query = build_smt_check(btor, lemma, check)
            if not query:
                record[f"{check}_result"] = "not_supported"
                continue
            smt_result = run_smt_check(query)
            record[f"{check}_result"] = smt_result.get("result", "?")
            record[f"{check}_time_ms"] = smt_result.get("time_ms", 0)

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
        {"id": "c2", "lemma": "(= state434 0)", "schema": "equality"},
    ]
    results = run_formal_checks_smt(samples, btor)
    for r in results:
        print(json.dumps(r, indent=2))
