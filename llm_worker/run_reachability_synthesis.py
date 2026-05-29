#!/usr/bin/env python3
"""Build reachability-aware synthesis prompt and optionally run LLM call."""

import json, os, sys, time, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smt_checker import BTOR2SMT, parse_btor2, lemma_to_smt
from reachable_filter import evaluate_on_sample, filter_candidates, filter_summary
from lemma_nontriviality import gate_repaired_lemma as gate

BTOR2_PATH = os.path.expanduser(
    "~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/"
    "qspiflash_dualflexpress_divfive-p040.btor2"
)
OUT_DIR = "logs/formal_yield/reachability_synthesis"

PROMPT_TEMPLATE = """You are a formal-methods hypothesis generator. You are given:
- Variable definitions with bitwidths and Verilog meanings
- Known reachable samples — states that the hardware CAN reach
- Failed lemmas that excluded these reachable samples

## CRITICAL RULE: Do NOT exclude any known reachable sample.

A lemma that evaluates to FALSE on any known reachable sample is an INVALID
invariant. The hardware has been observed in that state, so any true
invariant MUST be true there.

## Design Variables

{var_block}

## Known Reachable Samples

These states have been observed in the hardware (via SAT models or BMC):

{samples_block}

## Examples of INVALID lemmas (and why)

These lemmas were proposed but are INVALID because they exclude reachable samples:

{invalid_block}

## Your Task

Propose NEW semantic lemma candidates that:
1. Are TRUE on ALL known reachable samples (mandatory)
2. Are nontrivial — no bitwidth tautologies
3. May capture a meaningful transition-causal relation
4. Are likely to be inductive

Allowed schemas:
- mutual_exclusion: (! (and (= stateX V1) (= stateY V2)))
- guarded_implication: (=> antecedent consequent)
- range_bound: (<= stateX V) or (>= stateX V)
- disequality: (not (= stateX V))
- flag_consistency: relation between two 1-bit flags
- reject (if no meaningful candidate exists)

Banned:
- Trivial bounds: (<= 1-bit-var anything), (>= 4-bit-var 0)
- Lemmas that exclude any reachable sample
- Input-only variables without environment assumption

## Output Contract

Return ONLY valid JSON:

{{
  "candidates": [
    {{
      "candidate_id": "rsyn_001",
      "lemma": "(! (and (= state1536 10) (= state790 1)))",
      "schema": "mutual_exclusion",
      "variables": ["state1536", "state790"],
      "why_consistent_with_reachable_samples": "All reachable samples with state1536=10 have state790=1, so this mutex is consistent — the reachable samples don't show both at once",
      "why_nontrivial": "state1536 is 4-bit (0-15), state790 is 1-bit. Neither is a bitwidth tautology.",
      "risk": "medium"
    }}
  ]
}}

Generate up to 5 candidates total. Be conservative — if unsure, use \"reject\".
Return ONLY valid JSON.
"""


def load_samples():
    with open("logs/formal_yield/reachable_samples.json") as f:
        return json.load(f)["samples"]


def build_prompt():
    samples = load_samples()
    var_block, samples_block, invalid_block = "", "", ""

    vars_info = {
        "state1536": (4, "o_dspi_mod — DSPI operating mode register. Values: 0=IDLE, 10=active mode, 15=request-active"),
        "state790": (1, "o_wb_stall — Wishbone stall output. 1=bus stalled"),
        "state79": (1, "cfg_mode — Configuration mode flag"),
        "state2002": (1, "r_pipe_req — Pipeline request flag"),
        "state1558": (1, "cfg_speed — Config speed setting (INDEPENDENT, set by i_cfg_stb)"),
    }
    for var, (bw, desc) in vars_info.items():
        maxv = (1 << bw) - 1
        var_block += f"  {var}: {bw}-bit (values 0-{maxv}) = {desc}\n"

    # Known reachable samples — compact
    seen = set()
    for smp in samples:
        key = tuple(sorted(smp["values"].items()))
        if key in seen: continue
        seen.add(key)
        vals = ", ".join(f"{k}={v}" for k, v in sorted(smp["values"].items()))
        src = smp["source"]
        samples_block += f"  [{src}] {vals}\n"

    # Examples of invalid lemmas
    invalid_block += """Bad example 1: (<= state1536 14)
  REJECTED because reachable sample [cand_004 CE] has state1536=15
  A 4-bit variable can reach all values 0-15. Do not assert upper bounds
  below 15 unless you KNOW that value is unreachable.

Bad example 2: (not (= state1536 15))
  REJECTED because reachable sample [cand_004 CE] has state1536=15

Bad example 3: (state1536=10 => state790=0)
  REJECTED because reachable sample [cand_007 CE] has
  state1536=10, state790=1

Bad example 4: (state1536=0 => state1558=0)
  REJECTED because reachable sample [cand_008 CE] has
  state1536=0, state1558=1

Bad example 5: (<= state1558 1)
  TRIVIAL because state1558 is 1-bit. Any (<= 1-bit N) is always true.
"""

    prompt = PROMPT_TEMPLATE.format(
        var_block=var_block.strip(),
        samples_block=samples_block.strip(),
        invalid_block=invalid_block.strip(),
    )
    return prompt


def run_llm(prompt):
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

    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if m:
            try:
                result = json.loads(m.group(1))
            except json.JSONDecodeError:
                print("  Parse failed")
                return None
        else:
            print("  Parse failed: no JSON found")
            return None

    candidates = result.get("candidates", [])
    with open(os.path.join(OUT_DIR, "parsed_candidates.json"), "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Parsed {len(candidates)} candidates")

    metadata = {
        "model": "deepseek-v4-pro", "tokens": tokens, "latency_ms": latency_ms,
        "prompt_chars": len(prompt), "num_candidates": len(candidates),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(os.path.join(OUT_DIR, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    return candidates


def validate(candidates, btor_smt, bz, opts, bitwidths, samples):
    tm = btor_smt.tm
    trans = btor_smt.get_transition_constraints()
    init_c = btor_smt.get_init_constraints()

    results = []
    for c in candidates:
        cid = c.get("candidate_id", "?")
        lemma = c.get("lemma", "")
        schema = c.get("schema", "?")

        r = {"candidate_id": cid, "lemma": lemma[:150], "schema": schema}

        print(f"\n--- {cid} ({schema}) ---")
        print(f"  Lemma: {lemma[:80]}")

        # Gate 0: parse
        lt = lemma_to_smt(lemma, btor_smt.state_vars, tm)
        if lt is None and (schema and schema != "reject"):
            r["verdict"] = "parse_failed"
            results.append(r)
            print(f"  PARSE FAILED")
            continue

        # Gate 1: reachable filter
        filter_rec = filter_candidates(
            [{"candidate_id": cid, "lemma": lemma, "schema": schema}], samples
        )[0]
        r["reachable_filter"] = filter_rec["filter_result"]
        if filter_rec["filter_result"] == "violates_reachable_sample":
            r["verdict"] = "reachable_sample_violation"
            results.append(r)
            print(f"  REACHABLE VIOLATION: {filter_rec.get('violations', [{}])[0].get('evaluation', '?')[:80]}")
            continue

        # Gate 2: nontriviality
        gated = gate(lemma=lemma, bitwidths=bitwidths, original_vars=c.get("variables", []),
                     solver_verdict="solver_verified_strong")
        r["nontriviality"] = gated["gate_verdict"]
        if gated["gate_verdict"] in ("solver_verified_trivial",):
            r["verdict"] = "nontriviality_fail"
            results.append(r)
            print(f"  TRIVIAL: {gated.get('issues', [])}")
            continue

        # Gate 3: init
        s = bz.Bitwuzla(tm, opts)
        for ic in init_c: s.assert_formula(ic)
        s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt]))
        t0 = time.time()
        ri = s.check_sat()
        r["init"] = str(ri)
        if str(ri) == "sat":
            r["verdict"] = "init_fail"
            results.append(r)
            print(f"  INIT FAIL")
            continue

        # Gate 4: one-step
        lt_next = lemma_to_smt(lemma, btor_smt.next_vars, tm)
        if lt_next and trans:
            s = bz.Bitwuzla(tm, opts)
            for tc in trans: s.assert_formula(tc)
            s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
            t0 = time.time()
            ros = s.check_sat()
            r["one_step"] = str(ros)

            if str(ros) == "sat":
                r["verdict"] = "one_step_fail"
                results.append(r)
                print(f"  ONE-STEP FAIL")
                continue

            # Gate 5: induction
            s = bz.Bitwuzla(tm, opts)
            s.assert_formula(lt)
            for tc in trans: s.assert_formula(tc)
            s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
            t0 = time.time()
            ri2 = s.check_sat()
            r["induction"] = str(ri2)

            if str(ri2) == "unsat":
                r["verdict"] = "solver_inductive"
                print(f"  SOLVER INDUCTIVE!")
            else:
                r["verdict"] = "one_step_fail"
                print(f"  IND FAIL")
        else:
            r["one_step"] = "blocked"
            r["induction"] = "blocked"
            r["verdict"] = "blocked"

        results.append(r)

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()

    prompt = build_prompt()
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "prompt.txt"), "w") as f:
        f.write(prompt)
    print(f"Prompt: {OUT_DIR}/prompt.txt ({len(prompt)} chars)")
    print(f"First 300:\n{prompt[:300]}\n")

    if args.no_llm:
        return 0

    candidates = run_llm(prompt)
    if not candidates:
        print("No candidates generated")
        return 1

    print(f"\nGenerated {len(candidates)} candidates")

    import bitwuzla as bz
    btor = parse_btor2(BTOR2_PATH)
    btor_smt = BTOR2SMT(btor)

    bw = {}
    for lid, p in btor.items():
        if p[0] == "state" and len(p) >= 2:
            bw[f"state{lid}"] = int(p[1])

    opts = bz.Options()
    opts.set(bz.Option.PRODUCE_MODELS, True)

    samples = load_samples()

    results = validate(candidates, btor_smt, bz, opts, bw, samples)

    with open(os.path.join(OUT_DIR, "results.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSaved: {OUT_DIR}/results.json")

    from collections import Counter
    verdicts = Counter(r["verdict"] for r in results)
    print(f"\n=== Verdict Distribution ===")
    for v, c in verdicts.most_common():
        print(f"  {v}: {c}")

    useful = [r for r in results if r["verdict"] == "solver_inductive"]
    print(f"\n=== Solver Inductive: {len(useful)} ===")
    for u in useful:
        print(f"  {u['candidate_id']}: {u['lemma'][:80]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
