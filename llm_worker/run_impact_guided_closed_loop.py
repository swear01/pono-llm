#!/usr/bin/env python3
"""Task 86: Impact-guided closed-loop synthesis.

Selects top proof-relevant clusters from IC3IA dumps, builds prompt,
runs LLM, validates candidates, extracts CE feedback, runs one more
round if needed.
"""

import json, os, sys, time, re, shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smt_checker import BTOR2SMT, parse_btor2, lemma_to_smt
from reachable_filter import filter_candidates
from lemma_nontriviality import gate_repaired_lemma as gate

BTOR2_PATH = os.path.expanduser(
    "~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/"
    "qspiflash_dualflexpress_divfive-p040.btor2"
)
OUT_BASE = "logs/formal_yield/impact_guided_closed_loop"

# Top 3 resolved clusters from Task 85
TOP_CLUSTERS = [
    {"rank": 1, "vars": ["state15", "state886"],
     "frame_cooccur": 35, "cti_cooccur": 1974, "max_frame": 3,
     "predicates": ["(= state15 #b0)", "(= state886 #b0)"]},
    {"rank": 2, "vars": ["state15", "state785"],
     "frame_cooccur": 33, "cti_cooccur": 1974, "max_frame": 3,
     "predicates": ["(= state15 #b0)", "(= state785 #b0)"]},
    {"rank": 3, "vars": ["state1368", "state15"],
     "frame_cooccur": 32, "cti_cooccur": 1974, "max_frame": 3,
     "predicates": ["(= state1368 #b0)", "(= state15 #b0)"]},
]

BANNED = [
    "(<= 1-bit N)", "(>= w-bit 0)", "bitwidth tautology",
    "state2002=1 => state790=1",
]

PROMPT_TEMPLATE = """You are a proof-trace-directed lemma synthesis engine.

## Context

These variable clusters were selected because they co-occur frequently in IC3IA frame clauses and CTI cubes on the qspiflash_divfive-p040 benchmark. High co-occurrence in frame clauses means IC3IA is spending proof effort on these relations.

## Selected Clusters

{clusters}

## CRITICAL RULES

1. Synthesize lemmas ONLY over these variable clusters or closely related variables.
2. NEVER produce bitwidth tautologies (<= max_val, >= 0, any bound on 1-bit var).
3. NEVER exclude a known reachable sample.
4. DO NOT simply negate observed CTI values — think about causal transition relations.
5. Prior lesson: a valid lemma (r_pipe_req => o_wb_stall) was solver-verified but had ZERO proof-trace impact. This time, prefer lemmas that explain repeated frame/CTI patterns.
6. If no nontrivial lemma is plausible, use schema "reject".
7. Prefer SHORT lemmas: 1-2 variables, simple schema.

## Output Contract

Return ONLY valid JSON:
{{
  "round": 0,
  "candidates": [
    {{
      "candidate_id": "igcl_r0_001",
      "lemma": "(=> (= state15 #b0) (= state886 #b0))",
      "schema": "implication",
      "variables": ["state15", "state886"],
      "source_cluster": ["state15", "state886"],
      "proof_trace_rationale": "These vars co-occur in 35 frame clauses — suggesting a systematic relation IC3IA struggles with",
      "why_nontrivial": "Not a bitwidth tautology",
      "risk": "medium"
    }}
  ]
}}

Generate 3-5 candidates. Return ONLY JSON.
"""

FEEDBACK_BLOCK = """

## Feedback from Previous Round

The following candidates FAILED formal checks:

{feedbacks}

Do NOT repeat any falsified relation. Use the counterexamples to guide your search.
"""


def load_samples():
    with open("logs/formal_yield/reachable_samples.json") as f:
        return json.load(f)["samples"]


def build_prompt(clusters, feedbacks=None):
    cluster_text = ""
    for c in clusters:
        cluster_text += f"### Cluster {c['rank']}: {' + '.join(c['vars'])}\n"
        cluster_text += f"Frame co-occurrence: {c['frame_cooccur']} clauses\n"
        cluster_text += f"CTI co-occurrence: {c['cti_cooccur']}\n"
        cluster_text += f"Max frame: {c['max_frame']}\n"
        cluster_text += f"Predicates: {', '.join(c['predicates'])}\n\n"

    prompt = PROMPT_TEMPLATE.format(clusters=cluster_text.strip())
    if feedbacks:
        fb_text = "\n".join(f"  {fb}" for fb in feedbacks[:6])
        prompt += FEEDBACK_BLOCK.format(feedbacks=fb_text)
    return prompt


def call_llm(prompt):
    from deepseek_client import DeepSeekClient, get_api_key
    api_key = get_api_key()
    if not api_key: return None
    client = DeepSeekClient(api_key, model_name="deepseek-v4-pro")
    try:
        response_text, tokens, latency_ms = client.call(prompt)
        print(f"  LLM: {tokens} tokens, {latency_ms/1000:.0f}s")
    except Exception as e:
        print(f"  LLM error: {e}"); return None

    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if m:
            try: result = json.loads(m.group(1))
            except: print("  Parse failed"); return None
        else:
            print("  Parse failed"); return None
    return result, response_text, tokens, latency_ms


def validate_candidate(cid, lemma, cluster_vars, btor_smt, bz, opts, bitwidths, samples):
    tm = btor_smt.tm
    trans = btor_smt.get_transition_constraints()
    init_c = btor_smt.get_init_constraints()

    lt = lemma_to_smt(lemma, btor_smt.state_vars, tm)
    if lt is None:
        return {"verdict": "parse_failed"}, None

    f_rec = filter_candidates([{"candidate_id": cid, "lemma": lemma}], samples)[0]
    if f_rec["filter_result"] == "violates_reachable_sample":
        return {"verdict": "reachable_violation", "filter": f_rec}, None

    gated = gate(lemma=lemma, bitwidths=bitwidths, original_vars=cluster_vars,
                 solver_verdict="solver_verified_strong")
    if "trivial" in gated.get("gate_verdict", "") and not cluster_vars:
        pass  # skip trivial for empty cluster vars
    if "trivial" in gated.get("gate_verdict", ""):
        return {"verdict": "nontriviality_fail", "gate": gated}, None

    s = bz.Bitwuzla(tm, opts)
    for ic in init_c: s.assert_formula(ic)
    s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt]))
    t0 = time.time()
    ri = s.check_sat()
    init_ms = int((time.time() - t0) * 1000)
    if str(ri) == "sat":
        return {"verdict": "init_fail", "init_ms": init_ms}, None

    lt_next = lemma_to_smt(lemma, btor_smt.next_vars, tm)
    if not lt_next or not trans:
        return {"verdict": "blocked"}, None

    s = bz.Bitwuzla(tm, opts)
    for tc in trans: s.assert_formula(tc)
    s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
    t0 = time.time()
    ros = s.check_sat()
    if str(ros) == "sat":
        ce = _extract_ce_model(s, btor_smt, lemma)
        return {"verdict": "one_step_fail", "step_ms": int((time.time()-t0)*1000)}, ce

    s = bz.Bitwuzla(tm, opts)
    s.assert_formula(lt)
    for tc in trans: s.assert_formula(tc)
    s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
    t0 = time.time()
    ri2 = s.check_sat()
    if str(ri2) == "unsat":
        return {"verdict": "solver_verified", "init_ms": init_ms,
                "induction_ms": int((time.time()-t0)*1000)}, None
    return {"verdict": "induction_fail"}, None


def _extract_ce_model(solver, btor_smt, lemma):
    """Extract compact counterexample model."""
    nvs, cvs = {}, {}
    for v in ["state15", "state17", "state886", "state1368", "state785",
              "state1536", "state790", "state2002", "state79"]:
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
    return {
        "next_values": nvs, "current_values": cvs,
        "violated": f"one-step SAT for {lemma[:80]}",
    }


def summarize_feedback(lemma, ce):
    if not ce: return f"lemma: {lemma[:80]}\n  failure: one_step_fail"
    nvs = ce.get("next_values", {})
    vals = ", ".join(f"{k}={v}" for k, v in sorted(nvs.items())[:6])
    return f"lemma: {lemma[:80]}\n  failure: one_step_fail\n  ce values: {vals}"


def run_round(round_num, clusters, feedbacks, btor_smt, bz, opts, bitwidths, samples):
    out_dir = os.path.join(OUT_BASE, f"round_{round_num}")
    os.makedirs(out_dir, exist_ok=True)

    prompt = build_prompt(clusters, feedbacks)
    with open(os.path.join(out_dir, "prompt.txt"), "w") as f:
        f.write(prompt)
    print(f"  Prompt: {len(prompt)} chars")

    result = call_llm(prompt)
    if result is None:
        return None, feedbacks

    llm_result, response_text, tokens, latency_ms = result
    with open(os.path.join(out_dir, "raw_response.txt"), "w") as f:
        f.write(response_text)
    with open(os.path.join(out_dir, "parsed_candidates.json"), "w") as f:
        json.dump(llm_result, f, indent=2)
    metadata = {"tokens": tokens, "latency_ms": latency_ms,
                "prompt_chars": len(prompt)}
    with open(os.path.join(out_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    candidates = llm_result.get("candidates", [])
    print(f"  Candidates: {len(candidates)}")

    round_results = []
    found_verified = False

    for c in candidates:
        cid = c.get("candidate_id", "?")
        lemma = c.get("lemma", "")
        schema = c.get("schema", "?")

        if not lemma.strip() or lemma.strip().lower() == "reject" or schema == "reject":
            print(f"    {cid}: REJECTED")
            round_results.append({"candidate_id": cid, "lemma": "reject", "verdict": "rejected_by_llm"})
            continue

        info, ce = validate_candidate(cid, lemma, c.get("source_cluster", []),
                                     btor_smt, bz, opts, bitwidths, samples)
        rec = {"candidate_id": cid, "lemma": lemma[:150], "schema": schema, "verdict": info["verdict"]}

        print(f"    {cid}: {info['verdict']}")

        if info["verdict"] == "solver_verified":
            found_verified = True
            rec["verified"] = True

        if info["verdict"] in ("one_step_fail", "induction_fail"):
            fb = summarize_feedback(lemma, ce)
            feedbacks.append(fb)

        round_results.append(rec)

    with open(os.path.join(out_dir, "validation_results.json"), "w") as f:
        json.dump(round_results, f, indent=2, default=str)

    return round_results, feedbacks, found_verified


def main():
    import argparse
    parser = argparse.ArgumentParser()
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

    prompt = build_prompt(TOP_CLUSTERS, None)
    os.makedirs(os.path.join(OUT_BASE, "round_0"), exist_ok=True)
    with open(os.path.join(OUT_BASE, "round_0", "prompt.txt"), "w") as f:
        f.write(prompt)
    print(f"Prompt: {OUT_BASE}/round_0/prompt.txt ({len(prompt)} chars)")

    if args.no_llm:
        return 0

    feedbacks = []
    all_results = []
    found_any = False

    for rnd in range(2):
        print(f"\n{'='*50}\nROUND {rnd}\n{'='*50}")
        round_results, feedbacks, found = run_round(
            rnd, TOP_CLUSTERS, feedbacks, btor_smt, bz, opts, bitwidths, samples)
        if round_results is None:
            break
        all_results.extend(round_results)
        if found:
            found_any = True
            break

    from collections import Counter
    verdicts = Counter(r["verdict"] for r in all_results)
    print(f"\n{'='*50}\nSUMMARY\n{'='*50}")
    for v, c in verdicts.most_common():
        print(f"  {v}: {c}")

    verified = [r for r in all_results if r.get("verified")]
    print(f"\nSolver-verified: {len(verified)}")
    for v in verified:
        print(f"  {v['candidate_id']}: {v['lemma'][:100]}")

    # Save cluster config
    os.makedirs(OUT_BASE, exist_ok=True)
    with open(os.path.join(OUT_BASE, "selected_clusters.json"), "w") as f:
        json.dump(TOP_CLUSTERS, f, indent=2)

    with open(os.path.join(OUT_BASE, "summary.json"), "w") as f:
        json.dump({"verdicts": dict(verdicts), "found_verified": found_any,
                   "total_candidates": len(all_results)}, f, indent=2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
