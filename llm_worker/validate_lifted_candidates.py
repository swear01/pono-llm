#!/usr/bin/env python3
"""Task 90: Validate lifted clause-family candidates.

Triages 372 candidates, validates top 50 through solver pipeline,
analyzes failures, and runs impact analysis on verified lemmas.
"""

import json, os, sys, time, re
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smt_checker import BTOR2SMT, parse_btor2, lemma_to_smt
from reachable_filter import filter_candidates
from lemma_nontriviality import gate_repaired_lemma as gate

BTOR2_PATH = os.path.expanduser(
    "~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/"
    "qspiflash_dualflexpress_divfive-p040.btor2"
)
OUT_DIR = "logs/formal_yield"


def load_candidates():
    with open(os.path.join(OUT_DIR, "state15_lifted_candidates.json")) as f:
        return json.load(f)


def triage(candidates):
    """Rank candidates for validation priority."""
    for c in candidates:
        score = 0
        # Prefer 2-variable antecedents
        if c.get("antecedent_count", 0) == 2:
            score += 30
        elif c.get("antecedent_count", 0) == 1:
            score += 20
        else:
            score += 5
        # Prefer state15 as consequent
        if c.get("consequent_var") == "state15":
            score += 15
        # Prefer higher coverage
        score += min(c.get("coverage_count", 1) * 5, 25)
        # Prefer common satellites
        top_sats = {"state785", "state483", "state469", "state17", "state886"}
        for v in c.get("antecedent_vars", []):
            if v in top_sats: score += 5
        c["_score"] = score

    candidates.sort(key=lambda c: -c["_score"])
    return candidates[:50]


def validate_candidates(candidates, btor_smt, bz, opts, bitwidths):
    """Validate each candidate through all gates."""
    tm = btor_smt.tm
    trans = btor_smt.get_transition_constraints()
    init_c = btor_smt.get_init_constraints()
    samples = _load_samples()
    results = []

    for c in candidates:
        lemma = c.get("lemma", "")
        cid = f"lift_{c.get('consequent_var','')}_{'_'.join(c.get('antecedent_vars',[])[:2])}"

        r = {"lemma": lemma[:150], "antecedent_count": c.get("antecedent_count", 0),
             "consequent": c.get("consequent_var", "?"),
             "antecedents": c.get("antecedent_vars", [])[:4],
             "coverage": c.get("coverage_count", 0)}

        # Gate 1: Parse
        lt = lemma_to_smt(lemma, btor_smt.state_vars, tm)
        if lt is None:
            r["verdict"] = "parse_failed"
            results.append(r)
            continue

        # Gate 2: Reachable filter
        fr = filter_candidates([{"candidate_id": cid, "lemma": lemma}], samples)[0]
        if fr["filter_result"] == "violates_reachable_sample":
            r["verdict"] = "reachable_violation"
            results.append(r)
            continue

        # Gate 3: Nontriviality
        gated = gate(lemma=lemma, bitwidths=bitwidths,
                     original_vars=[c.get("consequent_var","")] + c.get("antecedent_vars",[]),
                     solver_verdict="solver_verified_strong")
        if "trivial" in gated.get("gate_verdict", ""):
            r["verdict"] = "nontriviality_fail"
            r["gate_issues"] = gated.get("issues", [])
            results.append(r)
            continue

        # Gate 4: Init
        s = bz.Bitwuzla(tm, opts)
        for ic in init_c: s.assert_formula(ic)
        s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt]))
        t0 = time.time()
        ri = s.check_sat()
        r["init_ms"] = int((time.time() - t0) * 1000)
        if str(ri) == "sat":
            r["verdict"] = "init_fail"
            results.append(r)
            continue

        # Gate 5: One-step
        lt_next = lemma_to_smt(lemma, btor_smt.next_vars, tm)
        if lt_next and trans:
            s = bz.Bitwuzla(tm, opts)
            for tc in trans: s.assert_formula(tc)
            s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
            t0 = time.time()
            ros = s.check_sat()
            r["step_ms"] = int((time.time() - t0) * 1000)
            if str(ros) == "sat":
                r["verdict"] = "one_step_fail"
                results.append(r)
                continue

            # Gate 6: Induction
            s = bz.Bitwuzla(tm, opts)
            s.assert_formula(lt)
            for tc in trans: s.assert_formula(tc)
            s.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
            t0 = time.time()
            ri2 = s.check_sat()
            r["induction_ms"] = int((time.time() - t0) * 1000)
            r["verdict"] = "solver_verified" if str(ri2) == "unsat" else "induction_fail"
        else:
            r["verdict"] = "blocked"

        results.append(r)

    return results


def _load_samples():
    with open("logs/formal_yield/reachable_samples.json") as f:
        return json.load(f)["samples"]


def analyze_failures(results):
    """Classify failure modes."""
    counts = Counter(r["verdict"] for r in results)
    print(f"\n=== Validation Distribution ===")
    for v, c in counts.most_common():
        print(f"  {v}: {c}")

    verified = [r for r in results if r["verdict"] == "solver_verified"]
    print(f"\nSolver-verified: {len(verified)}")
    for v in verified:
        print(f"  {v['lemma'][:120]}")

    return {
        "distribution": dict(counts),
        "verified_count": len(verified),
        "verified": verified,
        "total_validated": len(results),
    }


def main():
    candidates = load_candidates()
    print(f"Loaded {len(candidates)} candidates")

    top50 = triage(candidates)
    print(f"Triaged to {len(top50)} candidates")

    import bitwuzla as bz
    btor = parse_btor2(BTOR2_PATH)
    btor_smt = BTOR2SMT(btor)
    bitwidths = {}
    for lid, p in btor.items():
        if p[0] == "state" and len(p) >= 2:
            bitwidths[f"state{lid}"] = int(p[1])
    opts = bz.Options(); opts.set(bz.Option.PRODUCE_MODELS, True)

    print(f"\nValidating {len(top50)} candidates...")
    results = validate_candidates(top50, btor_smt, bz, opts, bitwidths)

    with open(os.path.join(OUT_DIR, "state15_lifted_validation_top50.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)

    summary = analyze_failures(results)
    with open(os.path.join(OUT_DIR, "state15_lifted_triage.json"), "w") as f:
        json.dump({"triaged": len(top50), "total": len(candidates), "summary": summary}, f, indent=2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
