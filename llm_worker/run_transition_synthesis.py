#!/usr/bin/env python3
"""Task 69: Transition-explainer-guided synthesis.

Phases C-F: Analyze failures, build prompt, run LLM, validate.
"""

import json, os, sys, time, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smt_checker import BTOR2SMT, parse_btor2, lemma_to_smt
from reachable_filter import evaluate_on_sample, filter_candidates
from lemma_nontriviality import gate_repaired_lemma as gate
from transition_slice import extract_btor_transition, explain_btor_expr

BTOR2_PATH = os.path.expanduser(
    "~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/"
    "qspiflash_dualflexpress_divfive-p040.btor2"
)
OUT_DIR = "logs/formal_yield/transition_synthesis"

FAILED = [
    {"cid": "C1", "lemma": "(=> (= state1536 10) (= state790 0))",
     "ce_next": {"state1536": "10", "state790": "1"},
     "failure": "one_step_fail"},
    {"cid": "rsyn_001", "lemma": "(=> (= state1536 15) (= state2002 1))",
     "ce_next": {"state1536": "15", "state2002": "1"},
     "failure": "one_step_fail"},
    {"cid": "rsyn_002", "lemma": "(! (and (= state1536 15) (= state2002 0)))",
     "ce_next": {"state1536": "15", "state2002": "1"},
     "failure": "one_step_fail"},
]

PROMPT = """You are a formal-methods hypothesis generator. Below are:

1. Variable definitions with NEXT-STATE transition logic
2. Known reachable samples — states the hardware CAN reach
3. Failed lemma examples with analysis of WHY they failed (transition-based)

## CRITICAL RULES

- NEVER exclude a known reachable sample (your lemma must be TRUE on all samples).
- NEVER produce bitwidth tautologies (<= max_val, >= 0, any bound on 1-bit var).
- USE the transition logic to understand causal relations between variables.
- Propose NEW semantic lemmas, not repairs of failed ones.

## Variable Transition Logic

{transitions}

## Known Reachable Samples (your lemma MUST hold on ALL of these)

{samples}

## Failed Lemma Analysis (to learn from)

{failures}

## Output Contract

Return ONLY valid JSON:
{{
  "candidates": [
    {{
      "candidate_id": "tsyn_001",
      "lemma": "(! (and (= state1536 15) (= state790 1)))",
      "schema": "mutual_exclusion",
      "variables": ["state1536", "state790"],
      "transition_rationale": "state1536=15 is request-active mode; state790 stall depends on bus arbitration logic with state1536 as dependency — suggesting mode influences stall",
      "why_consistent_with_reachable_samples": "No sample shows both state1536=15 and state790=1 simultaneously",
      "why_nontrivial": "Both variables have nontrivial value ranges",
      "risk": "medium"
    }}
  ]
}}

Generate up to 4 candidates. If no good lemma exists, use \\"reject\\". Return ONLY JSON.
"""


def _parse_btor():
    btor = {}
    for line in open(BTOR2_PATH):
        parts = line.strip().split()
        if not parts or parts[0][0] == ';': continue
        try: int(parts[0])
        except: continue
        btor[parts[0]] = parts[1:]
    return btor


def build_transition_summary():
    """Build human-readable transition summaries for LLM."""
    btor = _parse_btor()
    hot_vars = ['state1536', 'state790', 'state1558', 'state2002', 'state79']
    transitions = extract_btor_transition(BTOR2_PATH, hot_vars)

    lines = []
    for var in hot_vars:
        info = transitions.get(var, {})
        sid = var.replace('state', '')
        next_id = None
        for lid, p in btor.items():
            if p[0] == 'next' and len(p) >= 4 and p[2] == sid:
                next_id = p[3]
                break

        expanded = explain_btor_expr(btor, next_id) if next_id else '(none)'
        deps = info.get('dependencies', [])
        state_deps = [d for d in deps if d.startswith('state')]
        input_deps = [d for d in deps if d.startswith('i_')]
        n_deps = len(deps)

        lines.append(f"### {var} ({info.get('width', '?')}-bit)")
        lines.append(f"Next-state formula: {expanded[:250]}")
        lines.append(f"Depends on {n_deps} signals: {len(state_deps)} state vars, {len(input_deps)} inputs")
        lines.append(f"State deps: {', '.join(state_deps[:8])}")
        lines.append(f"Input deps: {', '.join(input_deps[:5])}")
        lines.append("")

        # Add semantic note
        notes = {
            'state1536': "o_dspi_mod — 4-bit DSPI mode register. Deeply nested ITE (667 chars). Reset to 0 (IDLE). Mode changes based on bus write commands and config strobes. Key modes: 0=IDLE, 10=active-mode, 15=request-active.",
            'state790': "o_wb_stall — 1-bit WB stall output. Init=1 (inactive?). Complex OR/ITE. Stall logic uses state2002, state85 (clk counter), and bus signals. state1536 is a dependency indicated by transition structure.",
            'state1558': "cfg_speed — 1-bit config speed. Simple: next = (cfg_stb & !stall & write) ? i_wb_data[10] : keep. READABLE.",
            'state2002': "r_pipe_req — 1-bit pipe request flag. Init=0. Next = (clk_ctr==1 && guard) ? 0 : write-conditions-match. Set when write strobe with address match.",
            'state79': "cfg_mode — 1-bit config mode. Simple: next = reset ? 0 : (cfg_stb & !stall & write) ? i_wb_data[12] : keep. READABLE.",
        }
        if var in notes:
            lines.append(f"Semantic: {notes[var]}")
        lines.append("")
    return "\n".join(lines)


def load_samples_text():
    with open("logs/formal_yield/reachable_samples.json") as f:
        samples = json.load(f)["samples"]
    seen = set()
    lines = []
    for smp in samples:
        key = tuple(sorted(smp["values"].items()))
        if key in seen: continue
        seen.add(key)
        vals = ", ".join(f"{k}={v}" for k, v in sorted(smp["values"].items()))
        lines.append(f"  [{smp['source']}] {vals}")
    return "\n".join(lines)


def build_failure_analysis():
    lines = []
    for f in FAILED:
        lines.append(f"### {f['cid']}: {f['lemma'][:80]}")
        lines.append(f"Failure: {f['failure']}")
        lines.append(f"Counterexample next values: {json.dumps(f['ce_next'])}")
        lines.append("")

        # Transition-based analysis
        if f['cid'] == 'C1':
            lines.append("  Analysis: state1536=10 is triggered by (wb_stb & !stall & ...).")
            lines.append("  state790 transition depends on bus logic with state2002 and state85.")
            lines.append("  state1536 and state790 share only indirect dependencies — no direct causal link.")
            lines.append("  state1536=10 does not force state790=0 or 1; both depend on bus state.")
        elif 'rsyn' in f['cid'] and 'state2002' in f['lemma']:
            lines.append("  Analysis: state1536 transitions to 15 via mode logic; state2002 set by write conditions.")
            lines.append("  Both variables appear in state1536's dependency list, but state2002=1 does")
            lines.append("  not FORCE state1536=15. The counterexample shows both=1, but transitions")
            lines.append("  can reach state1536=15 with state2002=0 via different paths.")
        lines.append("")
    return "\n".join(lines)


def run_llm(prompt):
    from deepseek_client import DeepSeekClient, get_api_key
    api_key = get_api_key()
    if not api_key: return None
    client = DeepSeekClient(api_key, model_name="deepseek-v4-pro")
    print(f"Calling LLM ({len(prompt)} char prompt)...")
    try:
        response_text, tokens, latency_ms = client.call(prompt)
        print(f"  Tokens: {tokens}, Latency: {latency_ms:.0f}ms")
    except Exception as e:
        print(f"  LLM error: {e}"); return None

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "prompt.txt"), "w") as f: f.write(prompt)
    with open(os.path.join(OUT_DIR, "raw_response.txt"), "w") as f: f.write(response_text)

    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if m:
            try: result = json.loads(m.group(1))
            except: print("Parse failed"); return None
        else:
            print("Parse failed: no JSON"); return None

    candidates = result.get("candidates", [])
    with open(os.path.join(OUT_DIR, "parsed_candidates.json"), "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Parsed {len(candidates)} candidates")

    metadata = {"model": "deepseek-v4-pro", "tokens": tokens, "latency_ms": latency_ms,
                "prompt_chars": len(prompt), "num_candidates": len(candidates),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
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

        # Parse
        lt = lemma_to_smt(lemma, btor_smt.state_vars, tm)
        if lt is None and (not schema or schema != "reject"):
            r["verdict"] = "parse_failed"; results.append(r); continue

        # Gate 1: reachable filter
        f_rec = filter_candidates([{"candidate_id": cid, "lemma": lemma}], samples)[0]
        if f_rec["filter_result"] == "violates_reachable_sample":
            r["verdict"] = "reachable_sample_violation"; results.append(r)
            print(f"  REACHABLE VIOLATION"); continue
        print(f"  reachable: pass", end=" ")

        # Gate 2: nontriviality
        gated = gate(lemma=lemma, bitwidths=bitwidths, original_vars=c.get("variables", []),
                     solver_verdict="solver_verified_strong")
        if "trivial" in gated.get("gate_verdict", ""):
            r["verdict"] = "nontriviality_fail"; results.append(r)
            print(f" TRIVIAL"); continue
        print(f"nontrivial: pass", end=" ")

        # Gate 3: init
        s = bz.Bitwuzla(tm, opts)
        for ic in init_c: s.assert_formula(ic)
        s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt]))
        ri = s.check_sat()
        if str(ri) == "sat":
            r["verdict"] = "init_fail"; results.append(r)
            print(f" INIT FAIL"); continue
        print(f"init: ok", end=" ")

        # Gate 4: one-step
        lt_next = lemma_to_smt(lemma, btor_smt.next_vars, tm)
        if lt_next and trans:
            s = bz.Bitwuzla(tm, opts)
            for tc in trans: s.assert_formula(tc)
            s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
            ros = s.check_sat()
            if str(ros) == "sat":
                r["verdict"] = "one_step_fail"; results.append(r)
                print(f" STEP FAIL"); continue
            print(f"step: ok", end=" ")

            # Gate 5: induction
            s = bz.Bitwuzla(tm, opts)
            s.assert_formula(lt)
            for tc in trans: s.assert_formula(tc)
            s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
            ri2 = s.check_sat()
            if str(ri2) == "unsat":
                r["verdict"] = "solver_inductive"
                print(f" INDUCTIVE!")
            else:
                r["verdict"] = "one_step_fail"
                print(f" IND FAIL")
        results.append(r)

    return results


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--no-llm", action="store_true")
    args = p.parse_args()

    # Build prompt
    transitions = build_transition_summary()
    samples = load_samples_text()
    failures = build_failure_analysis()

    prompt = PROMPT.format(transitions=transitions, samples=samples, failures=failures)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "prompt.txt"), "w") as f: f.write(prompt)
    print(f"Prompt: {OUT_DIR}/prompt.txt ({len(prompt)} chars)")

    if args.no_llm:
        return 0

    candidates = run_llm(prompt)
    if not candidates:
        print("No candidates generated"); return 1

    print(f"\nGenerated {len(candidates)} candidates")

    import bitwuzla as bz
    btor = parse_btor2(BTOR2_PATH)
    btor_smt = BTOR2SMT(btor)
    bw = {}
    for lid, pp in btor.items():
        if pp[0] == "state" and len(pp) >= 2: bw[f"state{lid}"] = int(pp[1])
    opts = bz.Options(); opts.set(bz.Option.PRODUCE_MODELS, True)

    with open("logs/formal_yield/reachable_samples.json") as f:
        smps = json.load(f)["samples"]

    results = validate(candidates, btor_smt, bz, opts, bw, smps)
    with open(os.path.join(OUT_DIR, "results.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSaved: {OUT_DIR}/results.json")

    from collections import Counter
    for v, c in Counter(r["verdict"] for r in results).most_common():
        print(f"  {v}: {c}")

    ind = [r for r in results if r["verdict"] == "solver_inductive"]
    print(f"\nSolver Inductive: {len(ind)}")
    for u in ind: print(f"  {u['candidate_id']}: {u['lemma'][:80]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
