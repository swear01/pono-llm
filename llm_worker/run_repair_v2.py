#!/usr/bin/env python3
"""Task 66: Repair v2 with nontriviality and counterexample-blocking constraints.

Steps:
1. Build repair-v2 prompt with strict nontriviality requirements
2. Run one LLM repair batch
3. Validate: parse, init, one-step, induction, nontriviality gate
4. Write report
"""

import json, os, sys, time, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smt_checker import BTOR2SMT, parse_btor2, lemma_to_smt
from lemma_nontriviality import gate_repaired_lemma as gate

BTOR2_PATH = os.path.expanduser(
    "~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/"
    "qspiflash_dualflexpress_divfive-p040.btor2"
)
OUT_DIR = "logs/formal_yield/repair_v2"
CE_DIR = "logs/formal_yield/counterexamples"


# --- Candidate data with CE counterexample models ---

REPAIRABLE = [
    {
        "candidate_id": "cand_007",
        "original_lemma": "(=> (= state1536 10) (= state790 0))",
        "schema": "guarded_implication",
        "failure": "overstrong_implication",
        "verilog": {"state1536": "o_dspi_mod (4-bit DSPI mode register)",
                     "state790": "o_wb_stall (1-bit Wishbone stall output)"},
        "ce_next": {"state1536": "10", "state790": "1"},
        "ce_current": {"state1536": "0", "state790": "0"},
        "ce_inputs": "i_reset=0, i_wb_*=write_active",
        "ce_interpretation": "Antecedent holds (mode=10) but consequent fails (stall=1, not 0). In hardware, o_wb_stall IS active when o_dspi_mod=10.",
        "bitwidths": {"state1536": 4, "state790": 1},
        "banned": [
            "DO NOT propose consequents like (<= state790 N) — state790 is 1-bit, any bound >= 1 is trivial",
            "DO NOT propose consequents like (>= state790 N) with N<=0 — trivial",
            "DO NOT propose consequent (not (= state1536 V)) with V>15 — impossible value for 4-bit",
        ],
    },
    {
        "candidate_id": "cand_008",
        "original_lemma": "(=> (= state1536 0) (= state1558 0))",
        "schema": "guarded_implication",
        "failure": "overstrong_implication",
        "verilog": {"state1536": "o_dspi_mod (4-bit DSPI mode register)",
                     "state1558": "cfg_speed (1-bit config speed)"},
        "ce_next": {"state1536": "0", "state1558": "1"},
        "ce_current": {"state1536": "0", "state1558": "0"},
        "ce_inputs": "i_cfg_stb=1 (config strobe active), i_reset=0",
        "ce_interpretation": "cfg_speed becomes 1 via config strobe while mode stays 0 (IDLE). cfg_speed is independently controlled.",
        "bitwidths": {"state1536": 4, "state1558": 1},
        "banned": [
            "DO NOT propose consequents like (<= state1558 N) — state1558 is 1-bit, ANY bound is trivial",
            "cfg_speed is 1-bit; any proposition about its value range is vacuous. Instead, propose a guard or a different relation.",
        ],
    },
    {
        "candidate_id": "cand_004",
        "original_lemma": "(=> (= state2002 1) (= state1536 0))",
        "schema": "guarded_implication",
        "failure": "overstrong_implication",
        "verilog": {"state2002": "r_pipe_req (1-bit pipeline request flag)",
                     "state1536": "o_dspi_mod (4-bit DSPI mode register)"},
        "ce_next": {"state2002": "1", "state1536": "15"},
        "ce_current": {"state2002": "0", "state1536": "0"},
        "ce_inputs": "i_reset=0",
        "ce_interpretation": "r_pipe_req=1 AND mode=15 (not 0). Mode is non-zero when request is active.",
        "bitwidths": {"state2002": 1, "state1536": 4},
        "banned": [
            "DO NOT propose consequents like (<= state2002 N) — state2002 is 1-bit, any bound is trivial",
            "DO NOT propose (>= state1536 N) with N<=0 — trivial for unsigned",
            "DO NOT propose (<= state1536 N) with N>=15 — trivial for 4-bit",
        ],
    },
]

REPAIR_V2_PROMPT = """You are a formal-methods repair engine. Below are counterexamples from SAT solver models showing exactly why 3 semantic lemma candidates failed one-step transition checks.

## Critical Rules — READ CAREFULLY

1. **NEVER produce trivial lemmas.** A trivial lemma is one that is always true regardless of state:
   - For a w-bit variable x: (<= x N) where N >= 2^w - 1 is ALWAYS TRUE
   - For a w-bit variable x: (>= x N) where N <= 0 is ALWAYS TRUE
   - For a w-bit variable x: (= x N) where N > 2^w - 1 is ALWAYS FALSE
   - 1-bit variables can only be 0 or 1 — any (<= 1-bit 1) or (>= 1-bit 0) is TRIVIAL

2. **Your repair MUST block the original counterexample.** The SAT model below shows specific next-state values that violated the original lemma. Your repair must evaluate to FALSE on those exact values (or change the truth condition so the CE no longer violates).

3. **Preserve at least one meaningful relation.** Do not simply delete the relationship. Keep a relation between the original variables.

4. **Prefer these repair strategies:**
   - **add_guard**: add a missing condition to the antecedent
   - **reverse_implication**: swap antecedent and consequent
   - **schema_change**: change lemma family (e.g., implication → mutual exclusion)
   - **reject**: if no meaningful repair exists, output "reject" — be honest

5. **Avoid these:**
   - Dropping the key variable
   - Replacing consequent with a tautology (e.g., x <= max_value)
   - Input-dependent lemmas unless justified

## Output Contract

Return ONLY valid JSON (no markdown, no comments):

{{
  "repairs": [
    {{
      "source_candidate_id": "cand_007",
      "repair_id": "cand_007_repair_v2_1",
      "repaired_lemma": "(=> (= state790 1) (= state1536 10))",
      "repair_strategy": "reverse_implication",
      "variables": ["state790", "state1536"],
      "why_blocks_counterexample": "Original CE: state1536=10, state790=1. With reversed implication, antecedent state790=1 holds AND consequent state1536=10 holds → lemma SATISFIES the CE (no longer violated).",
      "why_nontrivial": "state790 is 1-bit (0/1); state1536 is 4-bit (0-15). Neither consequent nor antecedent is a bitwidth tautology.",
      "risk": "medium"
    }}
  ]
}}

## Failed Lemmas and Counterexamples

{lemmas_block}

Now generate up to 3 repairs per candidate. If no nontrivial repair exists for a candidate, use strategy "reject". Return ONLY the JSON array.
"""


def load_ce_model(candidate_id):
    """Load the one-step counterexample JSON model."""
    path = os.path.join(CE_DIR, f"{candidate_id}_one_step_model.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def build_prompt():
    """Build repair-v2 prompt with bitwidth info and CE data."""
    lemmas_text = ""

    for i, cand in enumerate(REPAIRABLE):
        lemmas_text += f"\n### Candidate {i+1}: {cand['candidate_id']}\n"
        lemmas_text += f"Original lemma: {cand['original_lemma']}\n"
        lemmas_text += f"Schema: {cand['schema']}\n"
        lemmas_text += f"Failure: {cand['failure']}\n\n"

        lemmas_text += "Verilog signals and bitwidths:\n"
        for var, desc in cand["verilog"].items():
            bw = cand["bitwidths"].get(var, "?")
            lemmas_text += f"  {var} = {desc}\n"
        lemmas_text += "\n"

        lemmas_text += "SAT counterexample (next-state values that violate the lemma):\n"
        for var, val in sorted(cand["ce_next"].items()):
            lemmas_text += f"  {var}_next = {val}\n"

        lemmas_text += "\nCurrent state when CE was triggered:\n"
        for var, val in sorted(cand["ce_current"].items()):
            lemmas_text += f"  {var} = {val}\n"

        lemmas_text += f"\nRelevant inputs: {cand['ce_inputs']}\n"
        lemmas_text += f"\nWhy the lemma fails: {cand['ce_interpretation']}\n"

        lemmas_text += "\nFORBIDDEN trivial patterns:\n"
        for ban in cand["banned"]:
            lemmas_text += f"  ⛔ {ban}\n"
        lemmas_text += "\n"

    prompt = REPAIR_V2_PROMPT.format(lemmas_block=lemmas_text.strip())
    return prompt


def run_llm(prompt):
    """Call LLM with the repair-v2 prompt."""
    from deepseek_client import DeepSeekClient, get_api_key

    api_key = get_api_key()
    if not api_key:
        print("ERROR: No API key")
        return None

    client = DeepSeekClient(api_key, model_name="deepseek-v4-pro")
    print(f"Calling LLM ({len(prompt)} char prompt)...")

    try:
        response_text, tokens, latency_ms = client.call(prompt)
        print(f"  Tokens: {tokens}, Latency: {latency_ms:.0f}ms")
    except Exception as e:
        print(f"  LLM error: {e}")
        return None

    os.makedirs(OUT_DIR, exist_ok=True)

    with open(os.path.join(OUT_DIR, "prompt.txt"), "w") as f:
        f.write(prompt)
    with open(os.path.join(OUT_DIR, "raw_response.txt"), "w") as f:
        f.write(response_text)

    # Parse response
    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if m:
            try:
                result = json.loads(m.group(1))
            except json.JSONDecodeError:
                print("  Parse failed: could not extract JSON")
                return None
        else:
            print("  Parse failed: no JSON found")
            return None

    repairs = result.get("repairs", [])
    with open(os.path.join(OUT_DIR, "parsed_repairs.json"), "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Parsed {len(repairs)} repairs")

    metadata = {
        "model": "deepseek-v4-pro",
        "tokens": tokens,
        "latency_ms": latency_ms,
        "prompt_chars": len(prompt),
        "num_candidates": len(REPAIRABLE),
        "num_repairs": len(repairs),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(os.path.join(OUT_DIR, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    return result


def validate_repairs(repairs, btor_smt, bz, opts, bitwidths):
    """Validate all repairs: parse, init, one-step, induction, gate."""
    tm = btor_smt.tm
    trans = btor_smt.get_transition_constraints()
    init_c = btor_smt.get_init_constraints()

    results = []
    for rep in repairs:
        rid = rep.get("repair_id", "?")
        lemma = rep.get("repaired_lemma", "")
        src_id = rep.get("source_candidate_id", "")

        r = {"repair_id": rid, "source_candidate_id": src_id,
             "lemma": lemma[:150], "repair_strategy": rep.get("repair_strategy", "?")}

        print(f"\n--- {rid} ---")
        print(f"  Lemma: {lemma[:80]}")

        lt = lemma_to_smt(lemma, btor_smt.state_vars, tm)
        if lt is None:
            r["parse"] = "failed"
            r["verdict"] = "parse_failed"
            results.append(r)
            print(f"  PARSE FAILED")
            continue

        r["parse"] = "ok"

        # Init
        s = bz.Bitwuzla(tm, opts)
        for c in init_c:
            s.assert_formula(c)
        s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt]))
        t0 = time.time()
        r["init"] = str(s.check_sat())
        r["init_ms"] = int((time.time() - t0) * 1000)

        # One-step
        lt_next = lemma_to_smt(lemma, btor_smt.next_vars, tm)
        if lt_next and trans:
            s = bz.Bitwuzla(tm, opts)
            for c in trans:
                s.assert_formula(c)
            s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
            t0 = time.time()
            r["one_step"] = str(s.check_sat())
            r["one_step_ms"] = int((time.time() - t0) * 1000)
        else:
            r["one_step"] = "blocked"

        # Induction
        if lt_next and trans:
            s = bz.Bitwuzla(tm, opts)
            s.assert_formula(lt)
            for c in trans:
                s.assert_formula(c)
            s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
            t0 = time.time()
            r["induction"] = str(s.check_sat())
            r["induction_ms"] = int((time.time() - t0) * 1000)
        else:
            r["induction"] = "blocked"

        # Verdict
        solver_v = "unknown"
        if r.get("init") == "unsat" and r.get("one_step") == "unsat":
            solver_v = "solver_verified_strong"
        elif r.get("init") == "unsat" and r.get("induction") == "unsat":
            solver_v = "solver_inductive"
        elif r.get("init") == "sat":
            solver_v = "init_fail"
        elif r.get("init") == "unsat" and r.get("one_step") == "sat":
            solver_v = "init_pass_one_step_fail"
        r["solver_verdict"] = solver_v

        # Nontriviality gate
        src_info = next((c for c in REPAIRABLE if c["candidate_id"] == src_id), {})
        orig_vars = list(src_info.get("bitwidths", {}).keys())
        orig_ce = load_ce_model(src_id)

        gated = gate(
            lemma=lemma,
            bitwidths=bitwidths,
            original_vars=orig_vars,
            original_ce=orig_ce,
            solver_verdict=solver_v,
        )

        r["gate_verdict"] = gated["gate_verdict"]
        r["gate_issues"] = gated["issues"]
        r["verdict"] = gated["gate_verdict"]

        print(f"  solver={solver_v} gate={gated['gate_verdict']}")
        if gated["issues"]:
            for iss in gated["issues"]:
                print(f"    issue: {iss}")

        results.append(r)

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()

    # Step 1: Build prompt
    prompt = build_prompt()
    os.makedirs(OUT_DIR, exist_ok=True)

    with open(os.path.join(OUT_DIR, "prompt.txt"), "w") as f:
        f.write(prompt)
    print(f"Prompt: {OUT_DIR}/prompt.txt ({len(prompt)} chars)")

    if args.no_llm:
        print("--no-llm: stopping after prompt")
        return 0

    # Step 2: Run LLM
    result = run_llm(prompt)
    if not result or not result.get("repairs"):
        print("No repairs generated.")
        return 1

    repairs = result["repairs"]
    print(f"\nGenerated {len(repairs)} repairs")

    # Step 3: Validate
    import bitwuzla as bz

    btor = parse_btor2(BTOR2_PATH)
    btor_smt = BTOR2SMT(btor)

    bw = {}
    for lid, p in btor.items():
        if p[0] == "state" and len(p) >= 2:
            bw[f"state{lid}"] = int(p[1])

    opts = bz.Options()
    opts.set(bz.Option.PRODUCE_MODELS, True)

    results = validate_repairs(repairs, btor_smt, bz, opts, bw)

    # Save results
    with open(os.path.join(OUT_DIR, "results.json"), "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {OUT_DIR}/results.json")

    # Summary
    from collections import Counter
    verdicts = Counter(r["verdict"] for r in results)
    print(f"\n=== Verdict Distribution ===")
    for v, c in verdicts.most_common():
        print(f"  {v}: {c}")

    useful = [r for r in results if r["verdict"] == "solver_verified_useful"]
    print(f"\n=== Solver-Verified Useful: {len(useful)} ===")
    for u in useful:
        print(f"  {u['repair_id']}: {u['lemma'][:80]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
