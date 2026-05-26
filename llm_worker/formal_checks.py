#!/usr/bin/env python3
"""Formal check runner for batch candidate validation.

Checks: init validity, one-step validity, relative induction.
Uses BTOR2 parsing for analytical checks (init values, transition structure).
Marks checks needing SMT solver as 'not_run' with reason.
"""

import json, re, os
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

from candidate_gate import GateResult, classify_candidate, gate_batch


@dataclass
class FormalResult:
    candidate_id: str = ""
    raw_lemma: str = ""
    schema: str = ""

    init_check: str = "not_run"
    init_model: Dict = field(default_factory=dict)
    init_detail: str = ""

    one_step_check: str = "not_run"
    one_step_model: Dict = field(default_factory=dict)
    one_step_detail: str = ""

    induction_check: str = "not_run"
    induction_detail: str = ""

    near_miss_type: str = ""
    near_miss_score: float = 0.0
    decision: str = "rejected"


def parse_btor2(path: str) -> dict:
    """Parse BTOR2 file into indexed expression map."""
    btor = {}
    for line in open(path):
        parts = line.strip().split()
        if not parts or parts[0][0] == ";": continue
        lid = parts[0]
        try: int(lid)
        except: continue
        btor[lid] = parts[1:]
    return btor


def get_init_values(btor: dict) -> Dict[str, str]:
    """Extract init values for all state variables."""
    values = {}
    for lid, p in btor.items():
        if p[0] == "state": varname = f"state{lid}"
        else: continue
        for lid2, p2 in btor.items():
            if p2[0] == "init" and len(p2) >= 4 and p2[2] == lid:
                init_expr = p2[3]
                if init_expr in btor and btor[init_expr][0] == "const":
                    values[varname] = btor[init_expr][2] if len(btor[init_expr]) > 2 else "?"
                break
    return values


def get_next_structure(btor: dict, var: str) -> Optional[str]:
    """Get structural next-state info for a variable.
    Returns: 'const_0', 'const_1', 'not_of_<other>', 'ite_chain', etc.
    """
    sid = var.replace("state", "")
    next_expr = None
    for lid, p in btor.items():
        if p[0] == "next" and len(p) >= 4 and p[2] == sid:
            next_expr = p[3]
            break
    if not next_expr or next_expr not in btor: return None

    p = btor[next_expr]
    if p[0] == "const":
        return f"const_{p[2]}" if len(p) > 2 else "const_?"
    if p[0] == "not" and len(p) >= 3:
        negated = p[2]
        # Check if negated is a state var
        if negated in btor and btor[negated][0] == "state":
            return f"not_of_state{negated}"
    if p[0] == "ite":
        return "ite_chain"
    return p[0]


def check_init_analytical(lemma: str, variables: List[str],
                          init_values: Dict[str, str]) -> Tuple[bool, str, Dict]:
    """Analytically check if lemma holds at init state.
    Only works for simple lemma patterns (equality, mutex, constant comparison).
    """
    # Mutual exclusion: !(x && y)
    m = re.match(r"!\(\s*state(\d+)\s*&&\s*state(\d+)\s*\)", lemma.replace(" ", ""))
    if m:
        v1, v2 = f"state{m.group(1)}", f"state{m.group(2)}"
        iv1 = init_values.get(v1, "?")
        iv2 = init_values.get(v2, "?")
        if iv1 == "0" and iv2 == "0":
            return True, "both init to 0, mutex holds", {}
        elif iv1 != "?" and iv2 != "?":
            both_one = (iv1 == "1" or iv1 not in ("0", "1")) and (iv2 == "1" or iv2 not in ("0", "1"))
            if not both_one:
                return True, f"init values {iv1},{iv2}: not both 1", {}
            else:
                return False, f"init: both may be 1 ({iv1},{iv2})", {"v1": iv1, "v2": iv2}
        return True, "could not determine init values", {}

    # Simple equality: (= stateX const_val)
    m = re.match(r"=?\s*state(\d+)\s+(\S+)", lemma.replace("(", "").replace(")", "").strip())
    if m:
        var = f"state{m.group(1)}"
        val = m.group(2)
        iv = init_values.get(var, "?")
        if iv != "?" and val.strip() in ("0", "1", "#b0", "#b1"):
            expected = val.strip().replace("#b", "")
            if iv == expected:
                return True, f"init {var}={iv}, lemma expects {expected}", {}
            else:
                return False, f"init {var}={iv}, lemma expects {expected}", {"var": iv}
        return True, "could not determine", {}

    return True, "analytical check inconclusive", {}


def check_one_step_analytical(lemma: str, variables: List[str],
                              btor: dict) -> Tuple[bool, str, Dict]:
    """Analytically check if lemma is preserved by transition structure."""
    # Mutual exclusion: check if vars have complementary next-states
    m = re.match(r"!\(\s*state(\d+)\s*&&\s*state(\d+)\s*\)", lemma.replace(" ", ""))
    if m:
        v1, v2 = f"state{m.group(1)}", f"state{m.group(2)}"
        n1 = get_next_structure(btor, v1)
        n2 = get_next_structure(btor, v2)
        if n1 and n2:
            if n1.startswith("not_of_") and n2.startswith("not_of_"):
                return True, f"complementary transitions: {n1}, {n2}", {}
        return True, f"analytical check inconclusive: {n1}, {n2}", {}

    return True, "analytical check inconclusive", {}


def run_formal_checks(candidates: List[dict], btor_path: str = "") -> List[FormalResult]:
    """Run formal checks on a batch of candidates."""
    btor = parse_btor2(btor_path) if btor_path and os.path.exists(btor_path) else {}
    init_values = get_init_values(btor) if btor else {}

    results = []
    for cand in candidates:
        fr = FormalResult()
        fr.raw_lemma = cand.get("lemma", "")
        fr.candidate_id = cand.get("id", "?")
        fr.schema = cand.get("schema", "unknown")

        if not fr.raw_lemma:
            fr.decision = "rejected"
            results.append(fr)
            continue

        variables = re.findall(r"\b(state\d+)\b", fr.raw_lemma)

        # Init check
        if init_values:
            ok, detail, model = check_init_analytical(fr.raw_lemma, variables, init_values)
            if detail == "analytical check inconclusive" or "could not determine" in detail:
                fr.init_check = "inconclusive"  # need solver
            else:
                fr.init_check = "pass" if ok else "fail"
            fr.init_detail = detail
            fr.init_model = model
        else:
            fr.init_check = "not_run"

        # One-step check
        if btor:
            ok, detail, model = check_one_step_analytical(fr.raw_lemma, variables, btor)
            if detail.startswith("analytical check inconclusive"):
                fr.one_step_check = "inconclusive"
            else:
                fr.one_step_check = "pass" if ok else "fail"
            fr.one_step_detail = detail
        else:
            fr.one_step_check = "not_run"

        # Near-miss classification
        if fr.init_check == "fail" and fr.one_step_check == "pass":
            fr.near_miss_type = "init_fail_one_step_pass"
            fr.near_miss_score = 6.0
            fr.decision = "repair_candidate"
        elif fr.init_check == "pass" and fr.one_step_check == "fail":
            fr.near_miss_type = "init_pass_one_step_fail"
            fr.near_miss_score = 4.0
            fr.decision = "repair_candidate"
        elif fr.init_check == "pass" and fr.one_step_check == "pass":
            fr.near_miss_type = "analytically_verified"
            fr.near_miss_score = 8.0
            fr.decision = "accepted"
        elif fr.init_check == "pass" and fr.one_step_check == "inconclusive":
            fr.decision = "promising"
            fr.near_miss_score = 3.0
        elif fr.init_check == "inconclusive":
            fr.decision = "needs_solver"
            fr.near_miss_score = 1.0
        else:
            fr.decision = "rejected"

        results.append(fr)

    return results


def formal_summary(results: List[FormalResult]) -> dict:
    """Generate batch formal summary."""
    total = len(results)
    init_pass = sum(1 for r in results if r.init_check == "pass")
    init_fail = sum(1 for r in results if r.init_check == "fail")
    one_step_pass = sum(1 for r in results if r.one_step_check == "pass")
    one_step_fail = sum(1 for r in results if r.one_step_check == "fail")
    accepted = sum(1 for r in results if r.decision == "accepted")
    repair = sum(1 for r in results if r.decision == "repair_candidate")
    rejected = sum(1 for r in results if r.decision == "rejected")

    near_miss_types = defaultdict(int)
    for r in results:
        if r.near_miss_type:
            near_miss_types[r.near_miss_type] += 1

    schemas = defaultdict(int)
    for r in results:
        schemas[r.schema] += 1

    top_repair = sorted(
        [r for r in results if r.decision == "repair_candidate"],
        key=lambda r: -r.near_miss_score
    )[:8]

    return {
        "total": total,
        "init_pass": init_pass, "init_fail": init_fail,
        "one_step_pass": one_step_pass, "one_step_fail": one_step_fail,
        "accepted": accepted, "repair_candidates": repair, "rejected": rejected,
        "near_miss_types": dict(near_miss_types),
        "schema_distribution": dict(schemas),
        "top_repair_candidates": [
            {
                "id": r.candidate_id,
                "lemma": r.raw_lemma[:150],
                "type": r.near_miss_type,
                "score": r.near_miss_score,
                "init": r.init_check,
                "one_step": r.one_step_check,
            } for r in top_repair
        ],
    }


if __name__ == "__main__":
    import sys
    # Test
    samples = [
        {"id": "c1", "lemma": "!(state1359 && state1361)", "schema": "mutual_exclusion"},
        {"id": "c2", "lemma": "(distinct state1536[1:0] 2'd1)", "schema": "disequality"},
        {"id": "c3", "lemma": "(=> (= mode RUN) (< cnt limit))", "schema": "guarded_implication"},
    ]
    btor = os.path.expanduser("~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/qspiflash_dualflexpress_divfive-p040.btor2")
    results = run_formal_checks(samples, btor)
    summary = formal_summary(results)
    print(json.dumps(summary, indent=2))
    for r in results:
        print(f"\n{r.candidate_id}: init={r.init_check} step={r.one_step_check} type={r.near_miss_type} decision={r.decision}")
        print(f"  init: {r.init_detail}")
        print(f"  step: {r.one_step_detail}")
