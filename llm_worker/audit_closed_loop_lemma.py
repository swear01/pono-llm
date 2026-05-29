#!/usr/bin/env python3
"""Task 71: Proof audit of closed-loop solver-verified useful lemma.

Target: (=> (= state2002 1) (= state790 1))
"""

import json, os, sys, time, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smt_checker import BTOR2SMT, parse_btor2, lemma_to_smt
from reachable_filter import evaluate_on_sample
from lemma_nontriviality import gate_repaired_lemma as gate

BTOR2_PATH = os.path.expanduser(
    "~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/"
    "qspiflash_dualflexpress_divfive-p040.btor2"
)
AUDIT_DIR = "logs/formal_yield/closed_loop_synthesis/audit"

LEMMA = "(=> (= state2002 1) (= state790 1))"


def export_smt_lib(solver, tm, constraints, negated_lemma, filename, description):
    """Export SMT-LIB2 query to file."""
    lines = ["(set-logic QF_BV)", "(set-option :produce-models true)"]
    lines.append(f"; {description}")
    lines.append(f"; Lemma: {LEMMA}")
    for c in constraints:
        lines.append(f"(assert {c})")
    lines.append(f"(assert (not {negated_lemma}))")
    lines.append("(check-sat)")
    with open(filename, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  SMT exported: {filename}")


def main():
    import bitwuzla as bz

    btor = parse_btor2(BTOR2_PATH)
    btor_smt = BTOR2SMT(btor)
    tm = btor_smt.tm
    trans = btor_smt.get_transition_constraints()
    init_c = btor_smt.get_init_constraints()
    opts = bz.Options(); opts.set(bz.Option.PRODUCE_MODELS, True)

    os.makedirs(AUDIT_DIR, exist_ok=True)

    lt = lemma_to_smt(LEMMA, btor_smt.state_vars, tm)
    if lt is None:
        print("PARSE FAILED"); return 1
    print(f"Parse: OK")

    lt_next = lemma_to_smt(LEMMA, btor_smt.next_vars, tm)

    # --- Init check ---
    print(f"\n{'='*50}")
    print("INIT CHECK: Init(s) ∧ ¬L(s)")
    print(f"{'='*50}")
    s = bz.Bitwuzla(tm, opts)
    for ic in init_c: s.assert_formula(ic)
    s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt]))
    t0 = time.time()
    ri = s.check_sat()
    init_ms = int((time.time() - t0) * 1000)
    init_result = str(ri)
    print(f"  Result: {init_result} ({init_ms}ms)")

    init_file = os.path.join(AUDIT_DIR, "lemma_init_result.txt")
    with open(init_file, "w") as f:
        f.write(f"Lemma: {LEMMA}\n")
        f.write(f"Query: Init(s) ∧ ¬L(s)\n")
        f.write(f"Result: {init_result}\n")
    print(f"  Saved: {init_file}")

    # --- One-step check ---
    print(f"\n{'='*50}")
    print("ONE-STEP CHECK: T(s,i,s') ∧ ¬L(s')")
    print(f"{'='*50}")
    if lt_next and trans:
        s = bz.Bitwuzla(tm, opts)
        for tc in trans: s.assert_formula(tc)
        s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
        t0 = time.time()
        ros = s.check_sat()
        step_ms = int((time.time() - t0) * 1000)
        step_result = str(ros)
        print(f"  Result: {step_result} ({step_ms}ms)")
        print(f"  Transition constraints: {len(trans)}")

        step_file = os.path.join(AUDIT_DIR, "lemma_one_step_result.txt")
        with open(step_file, "w") as f:
            f.write(f"Lemma: {LEMMA}\n")
            f.write(f"Query: T(s,i,s') ∧ ¬L(s')\n")
            f.write(f"Transition constraints: {len(trans)}\n")
            f.write(f"Result: {step_result}\n")
        print(f"  Saved: {step_file}")

        # --- Induction check ---
        print(f"\n{'='*50}")
        print("INDUCTION CHECK: L(s) ∧ T(s,i,s') ∧ ¬L(s')")
        print(f"{'='*50}")
        s = bz.Bitwuzla(tm, opts)
        s.assert_formula(lt)
        for tc in trans: s.assert_formula(tc)
        s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
        t0 = time.time()
        ri2 = s.check_sat()
        ind_ms = int((time.time() - t0) * 1000)
        ind_result = str(ri2)
        print(f"  Result: {ind_result} ({ind_ms}ms)")

        ind_file = os.path.join(AUDIT_DIR, "lemma_induction_result.txt")
        with open(ind_file, "w") as f:
            f.write(f"Lemma: {LEMMA}\n")
            f.write(f"Query: L(s) ∧ T(s,i,s') ∧ ¬L(s')\n")
            f.write(f"Transition constraints: {len(trans)}\n")
            f.write(f"Result: {ind_result}\n")
        print(f"  Saved: {ind_file}")
    else:
        step_result = "blocked"
        ind_result = "blocked"
        print("  Blocked: no transition constraints")

    # --- Encoding scope ---
    print(f"\n{'='*50}")
    print("ENCODING SCOPE")
    print(f"{'='*50}")
    scope = {
        "translation_method": "Python BTOR2-to-SMT via smt_checker.BTOR2SMT",
        "btor2_file": BTOR2_PATH,
        "transition_constraints_count": len(trans),
        "transition_translation_coverage": "218/247 (88%)",
        "init_constraints_count": len(init_c),
        "state_variables": len(btor_smt.state_vars),
        "input_variables": len(btor_smt.input_vars),
        "operator_support": "18 BTOR2 operators (const, state, input, zero, ones, not, and, or, xor, xnor, eq, neq, add, sub, srl, ult, ulte, ite, slice, concat, redor, redand, uext)",
        "limitations": [
            "29/247 transition lines fail (node-208 redor cascade, non-target states)",
            "Not a full Pono rel_ind_check — standalone Bitwuzla validation",
            "Init values parsed from BTOR2 init lines (216/249 states)",
        ],
    }
    scope_file = os.path.join(AUDIT_DIR, "encoding_scope.json")
    with open(scope_file, "w") as f:
        json.dump(scope, f, indent=2)
    print(f"  Saved: {scope_file}")

    # --- Non-vacuity: check if antecedent is reachable ---
    print(f"\n{'='*50}")
    print("NON-VACUITY: Is state2002=1 reachable?")
    print(f"{'='*50}")

    with open("logs/formal_yield/reachable_samples.json") as f:
        samples = json.load(f)["samples"]

    vacuity_evidence = []
    for smp in samples:
        vals = smp.get("values", {})
        if vals.get("state2002_next") == "1":
            vacuity_evidence.append({
                "sample_id": smp["sample_id"],
                "source": smp["source"],
                "semantics": smp.get("semantics", ""),
                "state2002_value": "1",
            })
            print(f"  FOUND: {smp['sample_id']} has state2002_next=1 ({smp.get('semantics', '')})")

    # Also check one-step SAT models from cand_004 counterexamples
    ce_dir = "logs/formal_yield/counterexamples"
    for fname in sorted(os.listdir(ce_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(ce_dir, fname)) as f:
                ce = json.load(f)
            nvs = ce.get("next_values", {})
            if nvs.get("state2002_next") == "1":
                vacuity_evidence.append({
                    "sample_id": ce.get("candidate_id", "?") + "_" + ce.get("check", "?"),
                    "source": "counterexample_model",
                    "state2002_value": "1",
                })
                print(f"  FOUND in CE: {fname} has state2002_next=1")

    non_vacuity = "pass" if vacuity_evidence else "unknown"
    print(f"  Non-vacuity: {non_vacuity} ({len(vacuity_evidence)} evidence items)")

    # --- Consequent nontriviality ---
    print(f"\n{'='*50}")
    print("CONSEQUENT NONTRIVIALITY")
    print(f"{'='*50}")
    # state790 is 1-bit => state790=1 is false when state790=0, so nontrivial
    print(f"  state790 is 1-bit: (= state790 1) is nontrivial (false when 0)")

    # --- Relevance / blocking ---
    print(f"\n{'='*50}")
    print("RELEVANCE / BLOCKING")
    print(f"{'='*50}")

    reachable_pass = 0
    reachable_total = 0
    for smp in samples:
        vals = smp.get("values", {})
        r = evaluate_on_sample(LEMMA, vals)
        reachable_total += 1
        if r["result"] == "holds":
            reachable_pass += 1
        elif r["result"] == "violated":
            print(f"  VIOLATED sample: {smp['sample_id']}")

    print(f"  Reachable: {reachable_pass}/{reachable_total} pass")

    # Check against previous CE models
    ce_results = []
    for fname in sorted(os.listdir(ce_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(ce_dir, fname)) as f:
                ce = json.load(f)
            cid = ce.get("candidate_id", "?")
            check = ce.get("check", "?")
            nvs = ce.get("next_values", {})
            r = evaluate_on_sample(LEMMA, nvs)
            ce_results.append({
                "ce_id": fname.replace(".json", ""),
                "source_candidate": cid, "check": check,
                "result": r["result"], "reason": r.get("reason", ""),
                "next_values": dict(list(nvs.items())[:4]),
            })
            status = r["result"]
            print(f"  {fname:45s} result={status}")

    # Check nontriviality gate
    gated = gate(lemma=LEMMA, bitwidths={"state2002": 1, "state790": 1},
                 original_vars=["state2002", "state790"],
                 solver_verdict="solver_verified_strong")
    print(f"\n  Nontriviality gate: {gated['gate_verdict']}")
    if gated.get("issues"):
        for iss in gated["issues"]:
            print(f"    Issue: {iss}")

    # --- Build audit summary ---
    audit = {
        "lemma": LEMMA,
        "semantic_mapping": {"state2002": "r_pipe_req", "state790": "o_wb_stall"},
        "human_interpretation": "r_pipe_req = 1 => o_wb_stall = 1 (pipeline request implies bus stall)",
        "validation_results": {
            "init_check": init_result,
            "one_step_check": step_result,
            "induction_check": ind_result,
            "init_ms": init_ms, "step_ms": step_ms, "induction_ms": ind_ms,
        },
        "encoding_scope": {
            "method": "standalone Bitwuzla validation, 218/247 transition lines, 216 init values",
            "note": "NOT full Pono rel_ind_check — offline Python/Bitwuzla pipeline",
        },
        "non_vacuity": {"status": non_vacuity, "evidence_count": len(vacuity_evidence),
                        "evidence": vacuity_evidence[:5]},
        "consequent_nontriviality": {"status": "pass",
                                      "reason": "state790 is 1-bit, (= state790 1) excludes state790=0"},
        "nontriviality_gate": gated["gate_verdict"],
        "relevance": {
            "reachable_samples_checked": reachable_total,
            "reachable_samples_pass": reachable_pass,
            "previous_ces_checked": len(ce_results),
            "ce_results": ce_results,
        },
        "conclusion": "audited_solver_verified_useful" if non_vacuity == "pass" else "audited_solver_verified_useful"
    }

    # Adjust conclusion if issues
    if non_vacuity != "pass":
        audit["conclusion"] = "solver_verified_but_vacuity_unknown"
    if init_result != "unsat" or step_result != "unsat" or ind_result != "unsat":
        audit["conclusion"] = "audit_failed"

    with open(os.path.join(AUDIT_DIR, "audit_summary.json"), "w") as f:
        json.dump(audit, f, indent=2)
    print(f"\n{'='*50}")
    print(f"CONCLUSION: {audit['conclusion']}")
    print(f"{'='*50}")
    print(f"\nSaved: {AUDIT_DIR}/audit_summary.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
