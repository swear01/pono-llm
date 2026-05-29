#!/usr/bin/env python3
"""Task 67: Counterexample-aware lemma resynthesis.

Builds a prompt using all available context (CE models, Verilog symbols,
bitwidths, transition structure) and asks LLM to synthesize entirely new
semantic lemma candidates — not repair old ones.
"""

import json, os, sys, time, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smt_checker import BTOR2SMT, parse_btor2, lemma_to_smt
from lemma_nontriviality import gate_repaired_lemma as gate

BTOR2_PATH = os.path.expanduser(
    "~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/"
    "qspiflash_dualflexpress_divfive-p040.btor2"
)
OUT_DIR = "logs/formal_yield/resynthesis"
CE_DIR = "logs/formal_yield/counterexamples"

# --- Cluster-level failure context ---

FAILURE_CLUSTERS = [
    {
        "cluster_id": "CLUSTER_MODE_STALL",
        "description": "DSPI mode register (o_dspi_mod) and Wishbone stall output (o_wb_stall)",
        "failed_candidates": [
            "cand_007: (=> (= state1536 10) (= state790 0)) — overstrong_implication",
            "cand_005: (! (and (= state1536 10) (= state79 1))) — reachable_forbidden_mode",
        ],
        "variables": [
            {"name": "state1536", "verilog": "o_dspi_mod", "bw": 4,
             "description": "DSPI mode register. Values: 0=IDLE, 10=some active mode, 11=another mode, 15=request active"},
            {"name": "state790", "verilog": "o_wb_stall", "bw": 1,
             "description": "Wishbone stall output. 1 = bus is stalled"},
            {"name": "state79", "verilog": "cfg_mode", "bw": 1,
             "description": "Configuration mode flag"},
        ],
        "counterexamples": [
            {
                "source": "cand_007 one-step",
                "description": "state1536 transitions 0→10 while state790 transitions 0→1. Antecedent (mode=10) holds, consequent (stall=0) fails — stall IS active when mode=10.",
                "next_values": {"state1536": "10", "state790": "1"},
                "current_values": {"state1536": "0", "state790": "0"},
                "inputs": "i_reset=0, i_wb_stb=1, i_wb_we=1 (write transaction)",
            },
            {
                "source": "cand_005 one-step",
                "description": "Both state1536=10 AND state79=1 simultaneously reachable via config strobe. Mutex is false.",
                "next_values": {"state1536": "10", "state79": "1"},
                "current_values": {"state1536": "0", "state79": "0"},
                "inputs": "i_cfg_stb=1 (config strobe), i_reset=0",
            },
        ],
        "transition_hints": [
            "state1536 (o_dspi_mod): 4-bit, 68-node dependency cone, next-state is complex ITE chain over mode logic + inputs",
            "state790 (o_wb_stall): 1-bit, 49-node dependency cone, next-state depends on bus arbitration logic",
            "state79 (cfg_mode): 1-bit, 14-node dependency cone, config strobe driven",
            "state1536 transitions depend on: and(15x), state(9x), not(9x), input(7x), slice(7x), ite(6x)",
            "state790 transitions depend on: and(11x), state(6x), input(7x), not(5x), or(4x), ite(3x)",
        ],
        "allowed_schemas": ["mutual_exclusion", "mode_implication", "flag_consistency", "guarded_implication"],
        "banned": [
            "NO lemmas about state1558 (cfg_speed) — it is 1-bit and independently controlled",
            "NO (<= 1-bit N) bounds — trivially true for N>=1",
            "NO (>= 1-bit N) bounds with N<=0 — trivially true",
        ],
    },
    {
        "cluster_id": "CLUSTER_REQUEST_MODE",
        "description": "Pipeline request flag (r_pipe_req) and DSPI mode register relation",
        "failed_candidates": [
            "cand_004: (=> (= state2002 1) (= state1536 0)) — overstrong_implication",
        ],
        "variables": [
            {"name": "state2002", "verilog": "OPT_PIPE_BLOCK.r_pipe_req", "bw": 1,
             "description": "Pipeline request flag. 1 = request active"},
            {"name": "state1536", "verilog": "o_dspi_mod", "bw": 4,
             "description": "DSPI mode register. Values: 0=IDLE, 10=active mode, 15=request-active mode"},
        ],
        "counterexamples": [
            {
                "source": "cand_004 one-step",
                "description": "state2002 transitions 0→1 while state1536 transitions 0→15. Antecedent (request=1) holds, consequent (mode=0) fails — mode is 15, not 0.",
                "next_values": {"state2002": "1", "state1536": "15"},
                "current_values": {"state2002": "0", "state1536": "0"},
                "inputs": "i_reset=0, i_cfg_stb=1",
            },
        ],
        "transition_hints": [
            "state2002 (r_pipe_req): 1-bit, 34-node dependency cone, next-state ITE over pipe logic",
            "Relationship appears to be: request active => mode enters high range (10-15), not 0",
        ],
        "allowed_schemas": ["mode_implication", "range_bound", "disequality", "guarded_implication"],
        "banned": [
            "NO (<= state2002 N) bounds — trivially true for 1-bit",
        ],
    },
    {
        "cluster_id": "CLUSTER_MODE_CFG",
        "description": "DSPI mode (o_dspi_mod) and config speed (cfg_speed) — INSALVAGEABLE",
        "failed_candidates": [
            "cand_008: (=> (= state1536 0) (= state1558 0)) — overstrong_implication, cfg_speed is independent",
        ],
        "variables": [
            {"name": "state1536", "verilog": "o_dspi_mod", "bw": 4, "description": "DSPI mode register"},
            {"name": "state1558", "verilog": "cfg_speed", "bw": 1,
             "description": "Config speed setting. INDEPENDENTLY controlled via i_cfg_stb. No state-only invariant with mode."},
        ],
        "counterexamples": [
            {
                "source": "cand_008 one-step",
                "description": "state1536 stays 0, state1558 transitions 0→1 via i_cfg_stb=1. cfg_speed is independently configurable.",
                "next_values": {"state1536": "0", "state1558": "1"},
                "current_values": {"state1536": "0", "state1558": "0"},
                "inputs": "i_cfg_stb=1, i_reset=0",
            },
        ],
        "transition_hints": [
            "state1558 (cfg_speed): 1-bit, 21-node dependency cone, next-state is simple ITE driven by i_cfg_stb",
            "ASSESSMENT: No meaningful state-only invariant pairs mode with cfg_speed. cfg_speed is set by configuration strobe.",
        ],
        "allowed_schemas": ["reject"],
        "banned": ["ANY lemma pairing state1536 with state1558 is likely unsalvageable"],
    },
]

ALL_VARIABLES_CONTEXT = """
## Design Context

This is qspiflash_dualflexpress_divfive-p040 (HWMCC '24 word-level BV track).
A Quad SPI flash controller with Wishbone bus interface.

Key state variables available for lemmas:
  state1536 (4-bit) = o_dspi_mod     — DSPI operating mode register
  state790  (1-bit) = o_wb_stall     — Wishbone stall output (bus is stalled)
  state79   (1-bit) = cfg_mode       — Configuration mode flag
  state2002 (1-bit) = r_pipe_req     — Pipeline request flag
  state1558 (1-bit) = cfg_speed      — Config speed setting (INDEPENDENT of mode)

Do NOT invent variables outside this list. The design has 249 state variables but
these are the only ones with known Verilog mappings.

## Nontriviality Rules

For each variable, know the exact bitwidth:
  state1536: 4-bit (values 0-15)
  state790:  1-bit (values 0, 1)
  state79:   1-bit (values 0, 1)
  state2002: 1-bit (values 0, 1)
  state1558: 1-bit (values 0, 1)

A lemma is TRIVIAL if:
- For a w-bit variable x: (<= x N) where N >= 2^w - 1
- For a w-bit variable x: (>= x N) where N <= 0
- For a 1-bit variable: any upper or lower bound is trivial
- For a 4-bit variable: (<= x 15), (>= x 0), (< x 16), (> x -1)

NEVER propose a lemma that is trivially true by bitwidth.
"""

RESYNTHESIS_PROMPT = """You are a formal-methods hypothesis generator. You are given failed lemma candidates with SAT counterexample models showing exactly why they fail. Your job is to propose ENTIRELY NEW semantic lemma candidates — DO NOT repair or edit the old formulas.

## Critical Rules

1. **NEW lemmas, not repairs.** Do not output variants of the failed lemmas. Think about what invariant the real hardware actually satisfies.

2. **Must be nontrivial.** See bitwidth rules below. No tautologies.

3. **Must block at least one counterexample.** If you propose a lemma for a specific failure, the lemma must evaluate to FALSE on the exact next-state values of that counterexample (or make the antecedent not hold).

4. **State-only preference.** Prefer lemmas over state variables. If you reference inputs, they must be in a guard role with clear justification.

5. **Allowed schemas:**
   - mutual_exclusion: `(! (and (= X V1) (= Y V2)))`
   - mode_implication: `(=> (= mode M) constraint)`
   - flag_consistency: relation between two 1-bit flags
   - guarded_implication: `(=> antecedent consequent)` with nontrivial guard
   - range_bound: `(<= var N)` or `(>= var N)` with MEANINGFUL bound
   - disequality: `(not (= X Y))` or `(distinct X V)`
   - reject: if no lemma is plausible

6. **Output ONLY valid JSON.** No markdown, no explanations outside JSON.

## Output Contract

{{
  "resynthesized_candidates": [
    {{
      "source_failure_id": "CLUSTER_MODE_STALL",
      "candidate_id": "resyn_001",
      "lemma": "(! (and (= state1536 10) (= state79 1)))",
      "schema": "mutual_exclusion",
      "variables": ["state1536", "state79"],
      "why_avoids_counterexample": "CE: state1536=10, state79=1. The lemma says they cannot both be true, so it VIOLATES the lemma (both true). This means the lemma blocks this CE.",
      "why_nontrivial": "state1536 is 4-bit, state79 is 1-bit. Neither is a bitwidth tautology.",
      "risk": "medium"
    }}
  ]
}}

{context_block}

{clusters_block}

Now generate up to 4 new lemma candidates per cluster. Be creative but conservative. If a cluster is unsalvageable, use \"reject\" as the schema. Return ONLY valid JSON.
"""


def build_prompt():
    """Build the resynthesis prompt with all context."""
    clusters_text = ""
    for cluster in FAILURE_CLUSTERS:
        clusters_text += f"\n### {cluster['cluster_id']}: {cluster['description']}\n\n"

        clusters_text += "Previously failed:\n"
        for fc in cluster["failed_candidates"]:
            clusters_text += f"  ❌ {fc}\n"

        clusters_text += "\nVariables:\n"
        for v in cluster["variables"]:
            clusters_text += f"  {v['name']} ({v['bw']}-bit) = {v['verilog']}: {v['description']}\n"

        clusters_text += "\nCounterexamples:\n"
        for ce in cluster["counterexamples"]:
            clusters_text += f"  [{ce['source']}] {ce['description']}\n"
            clusters_text += f"  Next-state CE values: {json.dumps(ce['next_values'])}\n"
            clusters_text += f"  Current-state values: {json.dumps(ce['current_values'])}\n"
            clusters_text += f"  Inputs: {ce['inputs']}\n\n"

        clusters_text += "Transition structure hints:\n"
        for th in cluster["transition_hints"]:
            clusters_text += f"  - {th}\n"

        clusters_text += "\nAllowed schemas: " + ", ".join(cluster["allowed_schemas"]) + "\n"
        clusters_text += "Banned patterns:\n"
        for ban in cluster["banned"]:
            clusters_text += f"  ⛔ {ban}\n"
        clusters_text += "\n---\n"

    prompt = RESYNTHESIS_PROMPT.format(
        context_block=ALL_VARIABLES_CONTEXT.strip(),
        clusters_block=clusters_text.strip(),
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

    # Parse
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

    candidates = result.get("resynthesized_candidates", [])
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


def validate_candidates(candidates, btor_smt, bz, opts, bitwidths):
    tm = btor_smt.tm
    trans = btor_smt.get_transition_constraints()
    init_c = btor_smt.get_init_constraints()

    def load_ce(cid):
        for cluster in FAILURE_CLUSTERS:
            for ce_info in cluster["counterexamples"]:
                if "cand_" in ce_info.get("source", "").lower():
                    parts = ce_info["source"].split()
                    if parts and parts[0] in cid:
                        return {
                            "next_values": {k + "_next": v for k, v in ce_info["next_values"].items()},
                        }
        return None

    results = []
    for c in candidates:
        cid = c.get("candidate_id", "?")
        lemma = c.get("lemma", "")
        schema = c.get("schema", "?")
        src_id = c.get("source_failure_id", "")

        r = {"candidate_id": cid, "source_failure_id": src_id,
             "lemma": lemma[:150], "schema": schema}

        print(f"\n--- {cid} ({schema}) ---")
        print(f"  Lemma: {lemma[:80]}")

        if schema == "reject" or lemma.strip().lower() == "reject":
            r["verdict"] = "rejected_by_llm"
            results.append(r)
            print(f"  REJECTED")
            continue

        lt = lemma_to_smt(lemma, btor_smt.state_vars, tm)
        if lt is None:
            r["verdict"] = "parse_failed"
            results.append(r)
            print(f"  PARSE FAILED")
            continue

        r["parse"] = "ok"

        s = bz.Bitwuzla(tm, opts)
        for ic in init_c:
            s.assert_formula(ic)
        s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt]))
        t0 = time.time()
        r["init"] = str(s.check_sat())
        r["init_ms"] = int((time.time() - t0) * 1000)

        lt_next = lemma_to_smt(lemma, btor_smt.next_vars, tm)
        if lt_next and trans:
            s = bz.Bitwuzla(tm, opts)
            for tc in trans:
                s.assert_formula(tc)
            s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
            t0 = time.time()
            r["one_step"] = str(s.check_sat())
            r["one_step_ms"] = int((time.time() - t0) * 1000)

            s = bz.Bitwuzla(tm, opts)
            s.assert_formula(lt)
            for tc in trans:
                s.assert_formula(tc)
            s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
            t0 = time.time()
            r["induction"] = str(s.check_sat())
            r["induction_ms"] = int((time.time() - t0) * 1000)
        else:
            r["one_step"] = "blocked"
            r["induction"] = "blocked"

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

        orig_vars = list(set(re.findall(r'state\d+', json.dumps(
            next((cl for cl in FAILURE_CLUSTERS if cl["cluster_id"] == src_id), {}).get("variables", [])))))
        orig_ce = load_ce(cid)

        gated = gate(lemma=lemma, bitwidths=bitwidths, original_vars=orig_vars or [],
                     original_ce=orig_ce, solver_verdict=solver_v)
        r["gate_verdict"] = gated["gate_verdict"]
        r["gate_issues"] = gated["issues"]
        r["verdict"] = gated["gate_verdict"]

        print(f"  solver={solver_v} gate={r['gate_verdict']}")
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

    prompt = build_prompt()
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "prompt.txt"), "w") as f:
        f.write(prompt)
    print(f"Prompt: {OUT_DIR}/prompt.txt ({len(prompt)} chars)")

    if args.no_llm:
        print("--no-llm: stopping after prompt")
        return 0

    candidates = run_llm(prompt)
    if not candidates:
        print("No candidates generated.")
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

    results = validate_candidates(candidates, btor_smt, bz, opts, bw)

    with open(os.path.join(OUT_DIR, "results.json"), "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {OUT_DIR}/results.json")

    from collections import Counter
    verdicts = Counter(r["verdict"] for r in results)
    print(f"\n=== Verdict Distribution ===")
    for v, c in verdicts.most_common():
        print(f"  {v}: {c}")

    useful = [r for r in results if r["verdict"] == "solver_verified_useful"]
    print(f"\n=== Solver-Verified Useful: {len(useful)} ===")
    for u in useful:
        print(f"  {u['candidate_id']}: {u['lemma'][:80]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
