#!/usr/bin/env python3
"""Run Bitwuzla-backed formal checks on 5 shortlisted candidates."""

import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smt_checker import BTOR2SMT, parse_btor2, lemma_to_smt

BTOR2_PATH = os.path.expanduser(
    "~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/"
    "qspiflash_dualflexpress_divfive-p040.btor2"
)
OUT_DIR = "logs/formal_yield"

SHORTLIST = [
    {
        "rank": 1,
        "candidate_id": "cand_007_guarded_implication",
        "lemma": "(=> (= state1536 10) (= state790 0))",
        "schema": "guarded_implication",
        "variables": ["state1536", "state790"],
    },
    {
        "rank": 2,
        "candidate_id": "cand_008_guarded_implication",
        "lemma": "(=> (= state1536 0) (= state1558 0))",
        "schema": "guarded_implication",
        "variables": ["state1536", "state1558"],
    },
    {
        "rank": 3,
        "candidate_id": "cand_004_guarded_implication",
        "lemma": "(=> (= state2002 1) (= state1536 0))",
        "schema": "guarded_implication",
        "variables": ["state2002", "state1536"],
    },
    {
        "rank": 4,
        "candidate_id": "cand_005_mutual_exclusion",
        "lemma": "(! (and (= state1536 10) (= state79 1)))",
        "schema": "mutual_exclusion",
        "variables": ["state1536", "state79"],
    },
    {
        "rank": 5,
        "candidate_id": "cand_007_input",
        "lemma": "(=> (= state1536 11) (= ((_ extract 12 12) i_wb_data) 1))",
        "schema": "guarded_implication",
        "variables": ["state1536", "i_wb_data"],
        "has_input": True,
    },
]


def run_all_checks(btor_smt, bz, lemma_str, cand_info):
    tm = btor_smt.tm
    vars_dict = btor_smt.state_vars

    result = {
        "candidate_id": cand_info["candidate_id"],
        "rank": cand_info["rank"],
        "lemma": lemma_str[:150],
        "schema": cand_info["schema"],
        "variables": cand_info.get("variables", []),
    }

    # Parse lemma to SMT term
    lemma_term = lemma_to_smt(lemma_str, vars_dict, tm)
    if lemma_term is None:
        result["init"] = {"verdict": "parse_failed", "detail": "lemma_to_smt returned None"}
        result["one_step"] = {"verdict": "parse_failed"}
        result["inductive"] = {"verdict": "parse_failed"}
        result["overall_verdict"] = "parse_failed"
        return result

    # --- Init check: Init(s) AND NOT L(s) ---
    if btor_smt.init_values:
        solver = bz.Bitwuzla(tm)
        for c in btor_smt.get_init_constraints():
            solver.assert_formula(c)
        solver.assert_formula(tm.mk_term(bz.Kind.NOT, [lemma_term]))
        t0 = time.time()
        sat_result = solver.check_sat()
        ms = int((time.time() - t0) * 1000)
        if str(sat_result) == "unsat":
            result["init"] = {"verdict": "init_safe", "result": "unsat", "time_ms": ms}
        elif str(sat_result) == "sat":
            result["init"] = {"verdict": "init_fail", "result": "sat", "time_ms": ms}
        else:
            result["init"] = {"verdict": "init_unknown", "result": str(sat_result), "time_ms": ms}
    else:
        result["init"] = {"verdict": "no_init_data"}

    # --- One-step check: T(s,i,s') AND NOT L(s') ---
    trans_constraints = btor_smt.get_transition_constraints()
    if trans_constraints:
        # Verify target state transitions are included
        target_sids = set()
        for var in cand_info.get("variables", []):
            m = __import__('re').match(r"state(\d+)", var)
            if m:
                target_sids.add(m.group(1))

        target_trans_ok = all(
            any(f"state{sid}" in str(c) for c in trans_constraints
                if sid in str(c))
            for sid in target_sids
        ) if target_sids else True

        solver = bz.Bitwuzla(tm)
        for c in trans_constraints:
            solver.assert_formula(c)
        lemma_next = lemma_to_smt(lemma_str, btor_smt.next_vars, tm)
        if lemma_next is not None:
            solver.assert_formula(tm.mk_term(bz.Kind.NOT, [lemma_next]))
            t0 = time.time()
            sat_result = solver.check_sat()
            ms = int((time.time() - t0) * 1000)
            if str(sat_result) == "unsat":
                result["one_step"] = {"verdict": "one_step_valid", "result": "unsat",
                                       "time_ms": ms}
            elif str(sat_result) == "sat":
                result["one_step"] = {"verdict": "one_step_fail", "result": "sat",
                                       "time_ms": ms}
            else:
                result["one_step"] = {"verdict": "one_step_unknown",
                                       "result": str(sat_result), "time_ms": ms}
        else:
            result["one_step"] = {"verdict": "lemma_next_parse_failed"}
    else:
        result["one_step"] = {"verdict": "no_transition_constraints"}

    # --- Self-induction: L(s) AND T(s,i,s') AND NOT L(s') ---
    if trans_constraints:
        solver = bz.Bitwuzla(tm)
        solver.assert_formula(lemma_term)
        for c in trans_constraints:
            solver.assert_formula(c)
        lemma_next = lemma_to_smt(lemma_str, btor_smt.next_vars, tm)
        if lemma_next is not None:
            solver.assert_formula(tm.mk_term(bz.Kind.NOT, [lemma_next]))
            t0 = time.time()
            sat_result = solver.check_sat()
            ms = int((time.time() - t0) * 1000)
            if str(sat_result) == "unsat":
                result["inductive"] = {"verdict": "solver_inductive", "result": "unsat",
                                        "time_ms": ms}
            elif str(sat_result) == "sat":
                result["inductive"] = {"verdict": "induction_fail", "result": "sat",
                                        "time_ms": ms}
            else:
                result["inductive"] = {"verdict": "induction_unknown",
                                        "result": str(sat_result), "time_ms": ms}
        else:
            result["inductive"] = {"verdict": "lemma_next_parse_failed"}
    else:
        result["inductive"] = {"verdict": "no_transition_constraints"}

    # Overall verdict
    init_v = result.get("init", {}).get("verdict", "?")
    one_v = result.get("one_step", {}).get("verdict", "?")
    ind_v = result.get("inductive", {}).get("verdict", "?")

    if init_v == "init_safe" and one_v == "one_step_valid":
        result["overall_verdict"] = "solver_verified_strong"
    elif init_v == "init_safe" and ind_v == "solver_inductive":
        result["overall_verdict"] = "solver_inductive"
    elif init_v == "init_fail" and one_v == "one_step_valid":
        result["overall_verdict"] = "init_fail_one_step_pass"
    elif init_v == "init_safe" and one_v == "one_step_fail":
        result["overall_verdict"] = "init_pass_one_step_fail"
    elif init_v == "init_safe":
        result["overall_verdict"] = "init_pass_induction_fail"
    else:
        result["overall_verdict"] = "incomplete"

    return result


def main():
    import bitwuzla as bz

    print("Loading BTOR2...")
    btor = parse_btor2(BTOR2_PATH)
    btor_smt = BTOR2SMT(btor)
    print(f"  States: {len(btor_smt.state_vars)}, Inputs: {len(btor_smt.input_vars)}")
    print(f"  Init values: {len(btor_smt.init_values)}")

    trans = btor_smt.get_transition_constraints()
    print(f"  Transition constraints: {len(trans)}")

    results = []
    for cand in SHORTLIST:
        print(f"\n=== Candidate {cand['rank']}: {cand['candidate_id']} ===")
        print(f"  Lemma: {cand['lemma'][:80]}")
        result = run_all_checks(btor_smt, bz, cand["lemma"], cand)
        results.append(result)

        print(f"  Init:      {result.get('init', {}).get('verdict', '?')} "
              f"({result.get('init', {}).get('time_ms', '?')}ms)")
        print(f"  One-step:  {result.get('one_step', {}).get('verdict', '?')} "
              f"({result.get('one_step', {}).get('time_ms', '?')}ms)")
        print(f"  Inductive: {result.get('inductive', {}).get('verdict', '?')} "
              f"({result.get('inductive', {}).get('time_ms', '?')}ms)")
        print(f"  OVERALL:   {result['overall_verdict']}")

    # Summary
    summary = {
        "total": len(results),
        "solver_verified_strong": sum(1 for r in results if r["overall_verdict"] == "solver_verified_strong"),
        "solver_inductive": sum(1 for r in results if r["overall_verdict"] == "solver_inductive"),
        "init_fail_one_step_pass": sum(1 for r in results if r["overall_verdict"] == "init_fail_one_step_pass"),
        "init_pass_one_step_fail": sum(1 for r in results if r["overall_verdict"] == "init_pass_one_step_fail"),
        "init_pass_induction_fail": sum(1 for r in results if r["overall_verdict"] == "init_pass_induction_fail"),
        "parse_failed": sum(1 for r in results if r["overall_verdict"] == "parse_failed"),
        "incomplete": sum(1 for r in results if r["overall_verdict"] == "incomplete"),
    }

    print(f"\n=== Summary ===")
    for k, v in summary.items():
        if v > 0:
            print(f"  {k}: {v}")

    os.makedirs(OUT_DIR, exist_ok=True)

    output = {
        "btor2_path": BTOR2_PATH,
        "transition_constraints_count": len(trans),
        "summary": summary,
        "results": results,
    }
    out_file = os.path.join(OUT_DIR, "solver_validation_results_after_btor2_fix.json")
    with open(out_file, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved: {out_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
