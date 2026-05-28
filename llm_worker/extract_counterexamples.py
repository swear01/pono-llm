#!/usr/bin/env python3
"""Extract SAT counterexample models for candidates 1-4.

Phase A: Model extraction
Phase B: Failure classification
"""

import json, os, sys, re
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smt_checker import BTOR2SMT, parse_btor2, lemma_to_smt

BTOR2_PATH = os.path.expanduser(
    "~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/"
    "qspiflash_dualflexpress_divfive-p040.btor2"
)
OUT_DIR = "logs/formal_yield/counterexamples"
os.makedirs(OUT_DIR, exist_ok=True)

SHORTLIST = [
    {
        "rank": 1,
        "candidate_id": "cand_007",
        "lemma": "(=> (= state1536 10) (= state790 0))",
        "schema": "guarded_implication",
        "variables": ["state1536", "state790"],
        "verilog": {"state1536": "o_dspi_mod", "state790": "o_wb_stall"},
    },
    {
        "rank": 2,
        "candidate_id": "cand_008",
        "lemma": "(=> (= state1536 0) (= state1558 0))",
        "schema": "guarded_implication",
        "variables": ["state1536", "state1558"],
        "verilog": {"state1536": "o_dspi_mod", "state1558": "cfg_speed"},
    },
    {
        "rank": 3,
        "candidate_id": "cand_004",
        "lemma": "(=> (= state2002 1) (= state1536 0))",
        "schema": "guarded_implication",
        "variables": ["state2002", "state1536"],
        "verilog": {"state2002": "OPT_PIPE_BLOCK.r_pipe_req", "state1536": "o_dspi_mod"},
    },
    {
        "rank": 4,
        "candidate_id": "cand_005",
        "lemma": "(! (and (= state1536 10) (= state79 1)))",
        "schema": "mutual_exclusion",
        "variables": ["state1536", "state79"],
        "verilog": {"state1536": "o_dspi_mod", "state79": "cfg_mode"},
    },
]

KEY_INPUTS = ["i_reset", "i_wb_data", "i_wb_addr", "i_wb_stb", "i_wb_cyc", "i_wb_we"]
KEY_CONTROLS = ["state6"]  # i_reset state


def term_to_val_str(term, base=10):
    """Convert a Bitwuzla value term to a readable string."""
    try:
        s = term.sort()
        if s.is_bv():
            return str(int(term.value(base=2), 2))
        return str(term)
    except Exception as e:
        return f"<eval_err: {e}>"


def extract_model(solver, btor_smt, cand_info, check_name):
    """Extract SAT counterexample model."""
    import bitwuzla as bz
    tm = btor_smt.tm

    model = {
        "candidate_id": cand_info["candidate_id"],
        "lemma": cand_info["lemma"],
        "check": check_name,
        "result": "SAT",
    }

    # Extract lemma variables (current state)
    current_values = {}
    for var_name in cand_info["variables"]:
        if not var_name.startswith("state"):
            continue
        term = btor_smt.state_vars.get(var_name)
        if term is not None:
            try:
                val_term = solver.get_value(term)
                current_values[var_name] = term_to_val_str(val_term)
            except Exception as e:
                current_values[var_name] = f"<extract_err: {e}>"

    model["current_values"] = current_values

    # Extract next-state values
    next_values = {}
    for var_name in cand_info["variables"]:
        if not var_name.startswith("state"):
            continue
        next_name = var_name + "_next"
        term = btor_smt.next_vars.get(var_name)
        if term is not None:
            try:
                val_term = solver.get_value(term)
                next_values[var_name + "_next"] = term_to_val_str(val_term)
            except Exception as e:
                next_values[var_name + "_next"] = f"<extract_err: {e}>"

    model["next_values"] = next_values

    # Extract relevant inputs
    input_values = {}
    for inp_name in KEY_INPUTS:
        term = btor_smt.input_vars.get(inp_name)
        if term is not None:
            try:
                val_term = solver.get_value(term)
                input_values[inp_name] = term_to_val_str(val_term)
            except Exception:
                pass

    # Extract all inputs
    for inp_name, term in btor_smt.input_vars.items():
        if inp_name not in input_values:
            try:
                val_term = solver.get_value(term)
                input_values[inp_name] = term_to_val_str(val_term)
            except Exception:
                pass

    model["relevant_inputs"] = input_values

    # Extract key control state values
    control_values = {}
    for ctrl_name in KEY_CONTROLS:
        term = btor_smt.state_vars.get(ctrl_name)
        if term is not None:
            try:
                val_term = solver.get_value(term)
                control_values[ctrl_name] = term_to_val_str(val_term)
            except Exception:
                pass

    model["relevant_controls"] = control_values

    # Determine violated condition
    model["violated_condition"] = _analyze_violation(cand_info, current_values, next_values,
                                                       input_values, check_name)

    # Verilog symbols
    model["verilog_symbols"] = {}
    for var_name in cand_info["variables"]:
        sym = cand_info.get("verilog", {}).get(var_name, var_name)
        model["verilog_symbols"][var_name] = sym

    return model


def _analyze_violation(cand_info, current_values, next_values, input_values, check_name):
    """Analyze which part of the lemma is violated."""
    lemma = cand_info["lemma"]
    schema = cand_info["schema"]
    variables = cand_info["variables"]

    if check_name == "one_step":
        prefix = "one-step: "
    elif check_name == "induction":
        prefix = "induction: "
    else:
        prefix = ""

    if schema == "guarded_implication":
        m = re.match(
            r'\(\s*=>\s*\(\s*=\s*(state\d+)\s+(\d+)\s*\)\s*'
            r'\(\s*=\s*(state\d+)\s+(\d+)\s*\)\s*\)',
            lemma)
        if m:
            ant_var, ant_val, con_var, con_val = m.group(1), m.group(2), m.group(3), m.group(4)
            ant_next = next_values.get(ant_var + "_next", "?")
            con_next = next_values.get(con_var + "_next", "?")
            ant_cur = current_values.get(ant_var, "?")
            con_cur = current_values.get(con_var, "?")

            ant_match = (ant_next == ant_val)
            con_violated = (con_next != con_val)

            if ant_match and con_violated:
                return (f"{prefix}antecedent ({ant_var}={ant_val}) holds in next state (got {ant_next}), "
                        f"but consequent ({con_var}={con_val}) fails (got {con_next})")
            elif not ant_match:
                return (f"{prefix}antecedent ({ant_var}={ant_val}) does NOT hold in next state "
                        f"(got {ant_next}) — lemma may be vacuously violated through other paths")
            else:
                return f"{prefix}violation pattern unclear (ant={ant_match}, con_viol={con_violated})"

    elif schema == "mutual_exclusion":
        m = re.match(
            r'\(\s*!\s*\(\s*and\s*\(=\s*(state\d+)\s+(\d+)\s*\)\s*'
            r'\(=\s*(state\d+)\s+(\d+)\s*\)\s*\)\s*\)',
            lemma)
        if m:
            v1, val1, v2, val2 = m.group(1), m.group(2), m.group(3), m.group(4)
            n1 = next_values.get(v1 + "_next", "?")
            n2 = next_values.get(v2 + "_next", "?")
            both_match = (n1 == val1 and n2 == val2)
            if both_match:
                return (f"{prefix}both conditions ({v1}={val1}, {v2}={val2}) "
                        f"satisfied in next state (got {n1}, {n2}) — mutex violated")
            else:
                return (f"{prefix}v1={n1}(expect {val1}), v2={n2}(expect {val2}) — "
                        f"one or both conditions not met, mutex holds vacuously")

    return f"{prefix}violation detected (schema={schema}, see model for details)"


def classify_failure(cand_info, one_step_model, induction_model):
    """Classify failure mode from counterexample models."""
    lemma = cand_info["lemma"]
    schema = cand_info["schema"]

    # Extract key values from one-step model
    nvs = one_step_model.get("next_values", {})
    cvs = one_step_model.get("current_values", {})
    inputs = one_step_model.get("relevant_inputs", {})
    violated = one_step_model.get("violated_condition", "")

    failure_class = "translation_or_model_unclear"
    repairability = "low"
    repair_direction = ""
    notes = ""

    if schema == "guarded_implication":
        m = re.match(
            r'\(\s*=>\s*\(\s*=\s*(state\d+)\s+(\d+)\s*\)\s*'
            r'\(\s*=\s*(state\d+)\s+(\d+)\s*\)\s*\)',
            lemma)
        if m:
            ant_var, ant_val, con_var, con_val = m.group(1), m.group(2), m.group(3), m.group(4)
            ant_next = nvs.get(ant_var + "_next", "?")
            con_next = nvs.get(con_var + "_next", "?")
            ant_cur = cvs.get(ant_var, "?")

            if con_next != "?":
                if ant_next == ant_val:
                    failure_class = "overstrong_implication"
                    repairability = "medium"
                    notes = (f"antecedent {ant_var}={ant_val} holds (got {ant_next}), "
                             f"but consequent {con_var}={con_val} fails (got {con_next}). "
                             f"Lemma needs to be weakened: either add guard on extra condition "
                             f"or narrow the consequent.")
                elif ant_next == "?":
                    failure_class = "translation_or_model_unclear"
                    repairability = "low"
                    notes = f"Could not read {ant_var}_next value."
                else:
                    antecedent_does_not_hold = (ant_next != ant_val)
                    if antecedent_does_not_hold:
                        failure_class = "reachable_forbidden_mode"
                        repairability = "medium"
                        notes = (f"antecedent {ant_var}={ant_val} does NOT hold in next (got {ant_next}). "
                                 f"The transition can reach states where the consequent is violated "
                                 f"through paths where the antecedent doesn't hold. "
                                 f"May need to check if violated state is reachable at all "
                                 f"(BMC check) or if a stronger invariant covers this case.")

    elif schema == "mutual_exclusion":
        failure_class = "reachable_forbidden_mode"
        repairability = "medium"
        notes = "Mutex violated: both conditions simultaneously true in some reachable state."

    # Check if i_reset is active (suggests reset-path violation)
    reset_val = inputs.get("i_reset", "?")
    if reset_val == "1":
        notes += " [i_reset=1 active in counterexample — may be reset transition]"

    return {
        "failure_class": failure_class,
        "repairability": repairability,
        "repair_direction": repair_direction,
        "notes": notes,
        "one_step_violated_condition": violated,
        "one_step_antecedent_holds": "to_be_determined",
        "one_step_consequent_fails": "to_be_determined",
    }


def run_extraction():
    import bitwuzla as bz

    btor = parse_btor2(BTOR2_PATH)
    btor_smt = BTOR2SMT(btor)
    tm = btor_smt.tm

    # Create options with model production enabled
    opts = bz.Options()
    opts.set(bz.Option.PRODUCE_MODELS, True)

    trans_constraints = btor_smt.get_transition_constraints()
    init_constraints = btor_smt.get_init_constraints()

    all_results = []
    failure_classes = []

    for cand in SHORTLIST:
        print(f"\n{'='*60}")
        print(f"Candidate {cand['rank']}: {cand['candidate_id']}")
        print(f"  Lemma: {cand['lemma']}")

        lemma_term = lemma_to_smt(cand["lemma"], btor_smt.state_vars, tm)
        if lemma_term is None:
            print("  SKIP: cannot parse lemma")
            cand_result = {
                "candidate_id": cand["candidate_id"],
                "model_extraction": "parse_failed",
                "reason": "lemma_to_smt returned None",
            }
            all_results.append(cand_result)
            _save_raw_model(cand["candidate_id"], "parse_failed", str(cand_result))
            _save_json_model(cand["candidate_id"], "parse_failed", cand_result)
            continue

        lemma_next = lemma_to_smt(cand["lemma"], btor_smt.next_vars, tm)
        one_step_model = None
        induction_model = None

        # ---- One-step check ----
        print("  [One-step]")
        solver1 = bz.Bitwuzla(tm, opts)
        for c in trans_constraints:
            solver1.assert_formula(c)
        if lemma_next is not None:
            solver1.assert_formula(tm.mk_term(bz.Kind.NOT, [lemma_next]))
            r1 = solver1.check_sat()
            print(f"    result: {r1}")
            if str(r1) == "sat":
                one_step_model = extract_model(solver1, btor_smt, cand, "one_step")
                _save_raw_model(cand["candidate_id"], "one_step", _format_raw_model(one_step_model))
                _save_json_model(cand["candidate_id"], "one_step", one_step_model)
            else:
                _save_json_model(cand["candidate_id"], "one_step", {
                    "candidate_id": cand["candidate_id"],
                    "check": "one_step",
                    "result": str(r1),
                    "model_extraction": "not_sat",
                })

        # ---- Induction check ----
        print("  [Induction]")
        solver2 = bz.Bitwuzla(tm, opts)
        solver2.assert_formula(lemma_term)
        for c in trans_constraints:
            solver2.assert_formula(c)
        if lemma_next is not None:
            solver2.assert_formula(tm.mk_term(bz.Kind.NOT, [lemma_next]))
            r2 = solver2.check_sat()
            print(f"    result: {r2}")
            if str(r2) == "sat":
                induction_model = extract_model(solver2, btor_smt, cand, "induction")
                _save_raw_model(cand["candidate_id"], "induction", _format_raw_model(induction_model))
                _save_json_model(cand["candidate_id"], "induction", induction_model)
            else:
                _save_json_model(cand["candidate_id"], "induction", {
                    "candidate_id": cand["candidate_id"],
                    "check": "induction",
                    "result": str(r2),
                    "model_extraction": "not_sat",
                })

        # Classify
        if one_step_model and one_step_model.get("result") == "SAT":
            ind_model = induction_model if (induction_model and induction_model.get("result") == "SAT") else None
            cl = classify_failure(cand, one_step_model, ind_model or one_step_model)
            cl["rank"] = cand["rank"]
            cl["candidate_id"] = cand["candidate_id"]
            cl["lemma"] = cand["lemma"][:120]
            cl["schema"] = cand["schema"]
            failure_classes.append(cl)
            print(f"    Failure class: {cl['failure_class']}")
            print(f"    Repairability: {cl['repairability']}")
        else:
            failure_classes.append({
                "rank": cand["rank"],
                "candidate_id": cand["candidate_id"],
                "lemma": cand["lemma"][:120],
                "schema": cand["schema"],
                "failure_class": "translation_or_model_unclear",
                "repairability": "low",
                "notes": "No SAT model extracted",
            })

    # Save failure classification
    os.makedirs("logs/formal_yield", exist_ok=True)
    with open("logs/formal_yield/solver_counterexample_analysis.json", "w") as f:
        json.dump(failure_classes, f, indent=2)
    print(f"\nSaved: logs/formal_yield/solver_counterexample_analysis.json")

    # Print summary
    print(f"\n=== Failure Classification Summary ===")
    for fc in failure_classes:
        print(f"  C{fc['rank']} {fc['candidate_id']}: {fc['failure_class']} "
              f"(repairability={fc['repairability']})")
        if fc.get("notes"):
            print(f"    {fc['notes'][:120]}")

    return failure_classes


def _format_raw_model(model):
    lines = []
    lines.append(f"Candidate: {model.get('candidate_id', '?')}")
    lines.append(f"Lemma: {model.get('lemma', '?')}")
    lines.append(f"Check: {model.get('check', '?')}")
    lines.append(f"Result: {model.get('result', '?')}")
    lines.append(f"Violated: {model.get('violated_condition', '?')}")
    lines.append("")
    lines.append("Current values:")
    for k, v in model.get("current_values", {}).items():
        verilog = model.get("verilog_symbols", {}).get(k, "")
        lines.append(f"  {k:<25} = {v:<10}  ({verilog})")
    lines.append("")
    lines.append("Next values:")
    for k, v in model.get("next_values", {}).items():
        lines.append(f"  {k:<25} = {v}")
    lines.append("")
    lines.append("Inputs:")
    for k, v in model.get("relevant_inputs", {}).items():
        lines.append(f"  {k:<25} = {v}")
    lines.append("")
    lines.append("Controls:")
    for k, v in model.get("relevant_controls", {}).items():
        lines.append(f"  {k:<25} = {v}")
    return "\n".join(lines)


def _save_raw_model(cid, check, text):
    fname = os.path.join(OUT_DIR, f"{cid}_{check}_model.raw.txt")
    with open(fname, "w") as f:
        f.write(text)
    print(f"    Saved: {fname}")


def _save_json_model(cid, check, data):
    fname = os.path.join(OUT_DIR, f"{cid}_{check}_model.json")
    with open(fname, "w") as f:
        json.dump(data, f, indent=2)
    print(f"    Saved: {fname}")


if __name__ == "__main__":
    run_extraction()
