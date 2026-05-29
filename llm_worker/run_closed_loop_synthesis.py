#!/usr/bin/env python3
"""Task 70: Closed-loop solver-guided synthesis.

Propose → formal gates → extract counterexample → feedback → repeat.
Stops on solver_verified_useful or max_rounds.
"""

import json, os, sys, time, re, shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smt_checker import BTOR2SMT, parse_btor2, lemma_to_smt
from reachable_filter import evaluate_on_sample, filter_candidates
from lemma_nontriviality import gate_repaired_lemma as gate
from transition_slice import extract_btor_transition, explain_btor_expr

BTOR2_PATH = os.path.expanduser(
    "~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/"
    "qspiflash_dualflexpress_divfive-p040.btor2"
)
OUT_BASE = "logs/formal_yield/closed_loop_synthesis"

ALL_VARS = ["state1536", "state790", "state1558", "state2002", "state79"]

BANNED_CANDIDATES = [
    "(<= state1536 14)",
    "(not (= state1536 15))",
    "(=> (= state1536 10) (= state790 0))",
    "(=> (= state1536 15) (= state2002 1))",
    "(! (and (= state1536 15) (= state2002 0)))",
    "(=> (= state1536 0) (= state1558 0))",
    "(=> (= state2002 1) (= state1536 0))",
    "state1536=10=>stall=0",
    "state1536=15=>request=1",
]

BASE_PROMPT = """You are a formal-methods synthesis engine in a closed-loop system. Your job is to propose semantic lemma candidates that describe INVARIANTS of the hardware.

## CRITICAL RULES

1. NEVER exclude a known reachable sample. If the hardware CAN reach a state, any true invariant MUST hold there.
2. NEVER produce bitwidth tautologies: (<= 1-bit N), (>= w-bit 0), (< w-bit 2^w), etc.
3. NEVER propose a previously falsified candidate. Use the feedback blocks.
4. Prefer lemmas whose TRUTH follows from the transition update logic.
5. If no good lemma exists, use "reject".

## Design Variables

{transitions}

## Known Reachable Samples

{samples}

## Previously Falsified (DO NOT REPEAT)

{banned}

## Output Contract

Return ONLY valid JSON:
{{
  "round": {round_num},
  "candidates": [
    {{
      "candidate_id": "cls_r{round_num}_001",
      "lemma": "(! (and (= state1536 15) (= state790 1)))",
      "schema": "mutual_exclusion",
      "variables": ["state1536", "state790"],
      "transition_rationale": "...",
      "why_avoids_previous_counterexamples": "...",
      "why_consistent_with_reachable_samples": "...",
      "why_nontrivial": "...",
      "risk": "medium"
    }}
  ]
}}

Generate exactly {num_per_round} candidates. Return ONLY JSON.
"""

FEEDBACK_BLOCK = """

## Feedback from Previous Rounds

The following candidates were proposed but FAILED formal checks:

{feedback_list}
"""


def load_samples():
    with open("logs/formal_yield/reachable_samples.json") as f:
        return json.load(f)["samples"]


def load_transitions():
    btor = {}
    for line in open(BTOR2_PATH):
        parts = line.strip().split()
        if not parts or parts[0][0] == ";": continue
        try: int(parts[0])
        except: continue
        btor[parts[0]] = parts[1:]
    trans = extract_btor_transition(BTOR2_PATH, ALL_VARS)
    lines = []
    notes = {
        "state1536": "o_dspi_mod (4-bit mode reg). Reset=0(IDLE). Deps: state79,state790,state2002,state85,i_wb_*,i_cfg_stb. Complex ITE.",
        "state790": "o_wb_stall (1-bit). Init=1. Deps: state2002,state85,i_wb_*. Complex OR/ITE.",
        "state1558": "cfg_speed (1-bit). Init=0. next = (cfg_stb & !stall & write) ? i_wb_data[10] : keep.",
        "state2002": "r_pipe_req (1-bit). Init=0. next = (clk_ctr==1) ? 0 : write-conditions-match.",
        "state79": "cfg_mode (1-bit). Init=0. next = reset ? 0 : (cfg_stb & !stall & write) ? i_wb_data[12] : keep.",
    }
    for var in ALL_VARS:
        info = trans.get(var, {})
        bw = info.get("width", "?")
        deps = info.get("dependencies", [])
        dep_str = ", ".join(deps[:10]) if deps else "none"
        note = notes.get(var, "")
        lines.append(f"  {var} ({bw}-bit): {note}  [deps: {dep_str}]")
    return "\n".join(lines)


def load_samples_text():
    samples = load_samples()
    seen = set()
    lines = []
    for smp in samples:
        key = tuple(sorted(smp["values"].items()))
        if key in seen: continue
        seen.add(key)
        vals = ", ".join(f"{k}={v}" for k, v in sorted(smp["values"].items()))
        lines.append(f"  [{smp['source']}] {vals}")
    return "\n".join(lines)


def summarize_counterexample(lemma, one_step_model):
    """Create a compact feedback block for a failed candidate."""
    nvs = one_step_model.get("next_values", {})
    cvs = one_step_model.get("current_values", {})
    violated = one_step_model.get("violated_condition", "one-step SAT")

    return (
        f"  lemma: {lemma[:100]}\n"
        f"  failure: one_step (SAT counterexample found)\n"
        f"  next-state: {', '.join(f'{k}={v}' for k, v in sorted(nvs.items())[:6])}\n"
        f"  current-state: {', '.join(f'{k}={v}' for k, v in sorted(cvs.items())[:4])}\n"
        f"  reason: {violated[:150]}\n"
    )


def build_prompt(round_num, num_per_round, feedback_blocks=None):
    prompt = BASE_PROMPT.format(
        transitions=load_transitions(),
        samples=load_samples_text(),
        banned="\n".join(f"  - {b}" for b in BANNED_CANDIDATES),
        round_num=round_num,
        num_per_round=num_per_round,
    )
    if feedback_blocks:
        feedback_text = "\n".join(f"  ### Failure {i+1}\n{b}" for i, b in enumerate(feedback_blocks))
        prompt += FEEDBACK_BLOCK.format(feedback_list=feedback_text)
    return prompt


def call_llm(prompt):
    from deepseek_client import DeepSeekClient, get_api_key
    api_key = get_api_key()
    if not api_key: return None
    client = DeepSeekClient(api_key, model_name="deepseek-v4-pro")
    try:
        response_text, tokens, latency_ms = client.call(prompt)
        print(f"    LLM: {tokens} tokens, {latency_ms/1000:.0f}s")
    except Exception as e:
        print(f"    LLM error: {e}")
        return None

    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if m:
            try: result = json.loads(m.group(1))
            except: print("    Parse failed"); return None
        else:
            print("    Parse failed"); return None

    return result, response_text, tokens, latency_ms


def validate_candidate(cid, lemma, btor_smt, bz, opts, bitwidths, samples, ce_collector):
    tm = btor_smt.tm
    trans = btor_smt.get_transition_constraints()
    init_c = btor_smt.get_init_constraints()

    # Gate 1: parse
    lt = lemma_to_smt(lemma, btor_smt.state_vars, tm)
    if lt is None:
        return {"verdict": "parse_failed"}, None

    # Gate 2: reachable filter
    f_rec = filter_candidates([{"candidate_id": cid, "lemma": lemma}], samples)[0]
    if f_rec["filter_result"] == "violates_reachable_sample":
        return {"verdict": "reachable_sample_violation", "filter": f_rec}, None

    # Gate 3: nontriviality
    gated = gate(lemma=lemma, bitwidths=bitwidths, original_vars=ALL_VARS, solver_verdict="solver_verified_strong")
    if "trivial" in gated.get("gate_verdict", ""):
        return {"verdict": "nontriviality_fail", "gate": gated}, None

    # Gate 4: init
    s = bz.Bitwuzla(tm, opts)
    for ic in init_c: s.assert_formula(ic)
    s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt]))
    t0 = time.time()
    ri = s.check_sat()
    init_ms = int((time.time() - t0) * 1000)
    if str(ri) == "sat":
        return {"verdict": "init_fail", "init_result": str(ri), "init_ms": init_ms}, None

    # Gate 5: one-step
    lt_next = lemma_to_smt(lemma, btor_smt.next_vars, tm)
    if not lt_next or not trans:
        return {"verdict": "blocked"}, None

    s = bz.Bitwuzla(tm, opts)
    for tc in trans: s.assert_formula(tc)
    s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
    t0 = time.time()
    ros = s.check_sat()
    step_ms = int((time.time() - t0) * 1000)

    if str(ros) == "sat":
        # Extract counterexample
        ce_model = _extract_ce(s, btor_smt, lemma, "one_step")
        ce_model["verdict"] = "one_step_fail"
        ce_model["init_ms"] = init_ms
        ce_model["step_ms"] = step_ms
        if ce_collector is not None:
            ce_collector.append(ce_model)
        return {"verdict": "one_step_fail", "init_result": str(ri), "step_result": str(ros)}, ce_model

    # Gate 6: induction
    s = bz.Bitwuzla(tm, opts)
    s.assert_formula(lt)
    for tc in trans: s.assert_formula(tc)
    s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
    t0 = time.time()
    ri2 = s.check_sat()
    ind_ms = int((time.time() - t0) * 1000)

    if str(ri2) == "unsat":
        return {"verdict": "solver_verified_useful", "init_result": str(ri), "step_result": str(ros), "induction_result": str(ri2)}, None
    else:
        ce_model = _extract_ce(s, btor_smt, lemma, "induction")
        ce_model["verdict"] = "induction_fail"
        if ce_collector is not None:
            ce_collector.append(ce_model)
        return {"verdict": "induction_fail", "init_result": str(ri), "step_result": str(ros), "induction_result": str(ri2)}, ce_model


def _extract_ce(solver, btor_smt, lemma, check_name):
    tm = btor_smt.tm
    nvs, cvs = {}, {}
    for v in ALL_VARS:
        t = btor_smt.next_vars.get(v)
        if t:
            try:
                vt = solver.get_value(t)
                nvs[v + "_next"] = str(int(vt.value(base=2), 2))
            except: pass
        t = btor_smt.state_vars.get(v)
        if t:
            try:
                vt = solver.get_value(t)
                cvs[v] = str(int(vt.value(base=2), 2))
            except: pass

    # Determine violated condition
    violated = f"{check_name} SAT — lemma evaluates to FALSE"
    # Check implication: evaluate antecedent and consequent
    m = re.match(r'\(\s*=>\s*\(\s*=\s*(state\d+)\s+(\d+)\s*\)\s*\(\s*=.*', lemma.strip())
    if m:
        av, avv = m.group(1), m.group(2)
        if nvs.get(av + "_next") == avv:
            violated = f"antecedent {av}={avv} holds"
    m_mutex = re.match(r'\(\s*!\s*\(\s*and\s*.*', lemma.strip())
    if m_mutex:
        violated = "mutex violated — both conditions true"

    return {
        "lemma": lemma[:150], "check": check_name,
        "next_values": nvs, "current_values": cvs,
        "violated_condition": violated,
    }


def run_round(round_num, num_per_round, feedback_blocks, btor_smt, bz, opts, bitwidths, samples):
    print(f"\n{'='*60}")
    print(f"ROUND {round_num}")
    print(f"{'='*60}")

    out_dir = os.path.join(OUT_BASE, f"round_{round_num}")
    os.makedirs(out_dir, exist_ok=True)

    prompt = build_prompt(round_num, num_per_round, feedback_blocks)
    with open(os.path.join(out_dir, "prompt.txt"), "w") as f:
        f.write(prompt)
    print(f"  Prompt: {len(prompt)} chars")

    result = call_llm(prompt)
    if result is None:
        print("  LLM call failed")
        return None, feedback_blocks

    llm_result, response_text, tokens, latency_ms = result
    with open(os.path.join(out_dir, "raw_response.txt"), "w") as f:
        f.write(response_text)
    with open(os.path.join(out_dir, "parsed_candidates.json"), "w") as f:
        json.dump(llm_result, f, indent=2)

    candidates = llm_result.get("candidates", [])
    print(f"  Candidates: {len(candidates)}")

    round_ces = []
    round_results = []

    for c in candidates:
        cid = c.get("candidate_id", "?")
        lemma = c.get("lemma", "")
        schema = c.get("schema", "?")

        if not lemma.strip() or lemma.strip().lower() == "reject" or schema == "reject":
            print(f"    {cid}: REJECTED")
            round_results.append({"candidate_id": cid, "lemma": "reject", "verdict": "rejected_by_llm"})
            continue

        ce_collector = []
        info, ce = validate_candidate(cid, lemma, btor_smt, bz, opts, bitwidths, samples, ce_collector)

        rec = {"candidate_id": cid, "lemma": lemma[:150], "schema": schema,
               "verdict": info["verdict"]}
        rec.update({k: v for k, v in info.items() if k in ("init_result", "step_result", "induction_result")})

        if info["verdict"] == "solver_verified_useful":
            print(f"\n  *** SOLVER VERIFIED USEFUL: {cid} ***\n  {lemma}")
            round_results.append(rec)
            with open(os.path.join(out_dir, "validation_results.json"), "w") as f:
                json.dump(round_results, f, indent=2, default=str)
            return round_results, feedback_blocks
        elif info["verdict"] in ("one_step_fail", "induction_fail"):
            block = summarize_counterexample(lemma, ce)
            feedback_blocks.append(block)
            print(f"    {cid}: {info['verdict']} (CE extracted)")
            rec["counterexample"] = ce.get("next_values", {}) if ce else {}
        else:
            print(f"    {cid}: {info['verdict']}")

        round_results.append(rec)
        if ce_collector:
            round_ces.extend(ce_collector)

    with open(os.path.join(out_dir, "validation_results.json"), "w") as f:
        json.dump(round_results, f, indent=2, default=str)
    if round_ces:
        with open(os.path.join(out_dir, "counterexamples.json"), "w") as f:
            json.dump(round_ces, f, indent=2, default=str)

    return round_results, feedback_blocks


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--candidates-per-round", type=int, default=3)
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()

    import bitwuzla as bz
    btor = parse_btor2(BTOR2_PATH)
    btor_smt = BTOR2SMT(btor)
    bitwidths = {}
    for lid, p in btor.items():
        if p[0] == "state" and len(p) >= 2:
            bitwidths[f"state{lid}"] = int(p[1])
    opts = bz.Options(); opts.set(bz.Option.PRODUCE_MODELS, True)
    samples = load_samples()

    if args.no_llm:
        prompt = build_prompt(0, args.candidates_per_round, [])
        out_dir = os.path.join(OUT_BASE, "round_0")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "prompt.txt"), "w") as f:
            f.write(prompt)
        print(f"Prompt: {out_dir}/prompt.txt ({len(prompt)} chars)")
        return 0

    feedback_blocks = []
    all_results = []
    best_verdict = "none"
    found_useful = False

    for rnd in range(args.max_rounds):
        round_results, feedback_blocks = run_round(
            rnd, args.candidates_per_round, feedback_blocks,
            btor_smt, bz, opts, bitwidths, samples
        )
        if round_results is None:
            break
        all_results.extend(round_results)

        for rr in round_results:
            if rr["verdict"] == "solver_verified_useful":
                found_useful = True
                best_verdict = "solver_verified_useful"
                break

        # Check if all rejected
        all_reject = all(r["verdict"] in ("rejected_by_llm",) for r in round_results)
        if all_reject:
            print(f"\n  All candidates rejected — stopping")

        if found_useful:
            break

    # Summary
    from collections import Counter
    verdicts = Counter(r["verdict"] for r in all_results)
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Rounds run: {args.max_rounds if not found_useful else rnd + 1}")
    print(f"Total candidates: {sum(1 for r in all_results if r['verdict'] != 'rejected_by_llm')}")
    print(f"Best verdict: {best_verdict}")
    print(f"Verdict distribution: {dict(verdicts)}")

    # Save summary
    summary = {
        "max_rounds": args.max_rounds, "rounds_run": rnd + 1,
        "total_candidates": len(all_results),
        "best_verdict": best_verdict, "found_useful": found_useful,
        "verdict_distribution": dict(verdicts),
        "feedback_blocks": len(feedback_blocks),
    }
    os.makedirs(OUT_BASE, exist_ok=True)
    with open(os.path.join(OUT_BASE, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved: {OUT_BASE}/summary.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
