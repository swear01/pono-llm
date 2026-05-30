#!/usr/bin/env python3
"""Task 88: State15 clause-family-guided synthesis analysis.

Phases A-C: Analyze state15 predicates, values, clause families.
Phases D-E: Generate candidate schema plan, build LLM prompt.
"""

import json, os, sys, re
from collections import Counter, defaultdict


def load_jsonl(path):
    records = []
    if not os.path.exists(path): return records
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try: records.append(json.loads(line))
                except: pass
    return records


def phase_a_analyze_predicates(pred_path):
    """Extract all predicate entries involving state15."""
    preds = load_jsonl(pred_path)
    state15_preds = [p for p in preds
                     if 'state15' in p.get('raw_expr', '')
                     or 'state15' in str(p.get('variables', []))]
    print(f"=== Phase A: state15 Predicates ===")
    print(f"Total predicates: {len(preds)}, involving state15: {len(state15_preds)}")
    for p in state15_preds:
        print(f"  label={p.get('label','?')} expr={p.get('raw_expr','')[:80]} "
              f"vars={p.get('variables',[])} vals={p.get('state_values',{})}")
    return state15_preds


def phase_b_analyze_values(frame_path, cti_path):
    """Analyze state15 values in CTIs and frame clauses."""
    frames = load_jsonl(frame_path)
    ctis = load_jsonl(cti_path)

    # Frame clause usage
    frame_vals = Counter()
    frame_polarity = Counter()
    frame_examples = []

    for clause in frames:
        for lit in clause.get("literals", []):
            sv = lit.get("state_values", {})
            if "state15" in sv:
                val = sv["state15"]
                pol = lit.get("polarity", "?")
                frame_vals[val] += 1
                frame_polarity[pol] += 1
                if len(frame_examples) < 5:
                    frame_examples.append({
                        "frame": clause.get("frame"),
                        "raw": lit.get("raw", "")[:80],
                        "state15_val": val,
                        "polarity": pol,
                        "clause_raw": clause.get("raw_smt", "")[:120],
                    })

    # CTI usage
    cti_vals = Counter()
    for cti in ctis:
        for lit in cti.get("cube", []):
            vn = lit.get("varname", "")
            val = lit.get("value", "")
            if "state15" in vn:
                # Parse the value from varname
                m = re.search(r'state15\s*=\s*(?:#b)?(\d+)', vn)
                if m:
                    cti_vals[m.group(1)] += 1
                elif "true" in val:
                    cti_vals["1"] += 1
                elif "false" in val:
                    cti_vals["0"] += 1

    print(f"\n=== Phase B: state15 Values ===")
    print(f"Frame clause values: {dict(frame_vals)}")
    print(f"Frame polarity: {dict(frame_polarity)}")
    print(f"CTI values: {dict(cti_vals)}")

    for ex in frame_examples[:3]:
        print(f"  Example: frame={ex['frame']} s15={ex['state15_val']} "
              f"pol={ex['polarity']} clause={ex['clause_raw'][:80]}")

    return {
        "frame_values": dict(frame_vals),
        "frame_polarity": dict(frame_polarity),
        "cti_values": dict(cti_vals),
        "examples": frame_examples,
    }


def phase_c_extract_families(frame_path):
    """Group frame clauses involving state15 into families."""
    frames = load_jsonl(frame_path)

    families = defaultdict(list)
    for clause in frames:
        has_state15 = False
        for lit in clause.get("literals", []):
            if "state15" in lit.get("state_values", {}):
                has_state15 = True
                break
        if not has_state15:
            continue

        # Classify by clause structure
        lit_count = clause.get("literal_count", 0)
        lits = clause.get("literals", [])

        # Get all variable names
        all_vars = set()
        for lit in lits:
            all_vars.update(lit.get("variables", []))
            all_vars.update(lit.get("state_values", {}).keys())

        # Determine satellite variables (vars other than state15)
        satellites = sorted(all_vars - {"state15"})

        # Build family key
        if lit_count == 1:
            fkey = "single_state15"
        elif lit_count == 2 and len(satellites) == 1:
            fkey = f"binary_state15_{satellites[0]}" if satellites else "binary_state15_unknown"
        elif lit_count == 3:
            top_sats = satellites[:3] if satellites else ["?"]
            fkey = f"ternary_{len(satellites)}sats"
        else:
            fkey = f"multi_{lit_count}lits"

        families[fkey].append({
            "frame": clause.get("frame", 0),
            "lit_count": lit_count,
            "satellites": satellites,
            "raw_smt": clause.get("raw_smt", "")[:150],
        })

    print(f"\n=== Phase C: state15 Clause Families ===")
    print(f"Clauses involving state15: {sum(len(v) for v in families.values())}")

    summaries = []
    for fkey, recs in sorted(families.items(), key=lambda x: -len(x[1])):
        frames_seen = set(r["frame"] for r in recs)
        all_sats = Counter()
        for r in recs:
            for s in r["satellites"]:
                all_sats[s] += 1
        print(f"  {fkey}: {len(recs)} clauses, frames={sorted(frames_seen)}, "
              f"top_sats={all_sats.most_common(3)}")
        summaries.append({
            "family": fkey,
            "count": len(recs),
            "frames": sorted(frames_seen),
            "top_satellites": all_sats.most_common(10),
            "sample": recs[0]["raw_smt"] if recs else "",
        })

    return summaries


def phase_d_generate_schemas(preds, value_data, families):
    """Generate candidate lemma schemas for state15."""
    frame_vals = value_data.get("frame_values", {})
    cti_vals = value_data.get("cti_values", {})

    schemas = []

    # Schema 1: state15 is always 0 in frame clauses
    if "0" in frame_vals and frame_vals["0"] == sum(frame_vals.values()):
        schemas.append({
            "schema": "single_value_exclusion",
            "candidate_form": "(= state15 #b0)",
            "target_clause_family": "all state15 clauses",
            "expected_impact": "high",
            "risk": "overstrong",
            "needs_llm": False,
            "rationale": "All frame clause literals involve state15=0. state15=0 as an invariant would explain all clauses.",
        })

    # Schema 2: state15 appears to be a Boolean flag — 0 or 1 only
    cti_val_list = sorted(set(cti_vals.keys()))
    schemas.append({
        "schema": "mode_exclusion",
        "candidate_form": "(not (= state15 #b1))",
        "target_clause_family": "all 391 state15 clauses",
        "expected_impact": "high",
        "risk": "overstrong",
        "needs_llm": False,
        "rationale": f"CTIs show state15 ∈ {cti_val_list}. state15=1 is CTI-dominant (22534x). If state15=1 is BAD, lemma NOT(state15=1) could compress all clauses referencing it.",
    })

    # Schema 3: Clause-family compression via single-value lemma
    schemas.append({
        "schema": "clause_family_compression",
        "candidate_form": "(= state15 #b0)",
        "target_clause_family": "230+ clauses with NOT(state15=0)",
        "expected_impact": "high",
        "risk": "overstrong",
        "needs_llm": False,
        "rationale": "state15=0 as invariant would trivially satisfy all clauses containing NOT(state15=0). Must verify init/one-step/induction.",
    })

    # Schema 4: Guarded relation with most common satellite
    top_sat = None
    top_sat_count = 0
    for f in families:
        for s, c in f.get("top_satellites", []):
            if c > top_sat_count:
                top_sat = s
                top_sat_count = c

    if top_sat:
        schemas.append({
            "schema": "guarded_exclusion",
            "candidate_form": f"(=> (= {top_sat} #b0) (= state15 #b0))",
            "target_clause_family": f"clauses with {top_sat}",
            "expected_impact": "medium",
            "risk": "overstrong",
            "needs_llm": True,
            "rationale": f"{top_sat} is the most common satellite ({top_sat_count}x). A guarded relation may generalize clause patterns.",
        })

    print(f"\n=== Phase D: Candidate Schemas ===")
    for i, s in enumerate(schemas):
        print(f"  {i+1}. {s['schema']}: {s['candidate_form']}")
        print(f"     impact={s['expected_impact']} risk={s['risk']} rationale={s['rationale'][:80]}")

    return schemas


def phase_f_validate_obvious(bz, btor_smt, opts, bitwidths, schemas):
    """Validate obvious non-LLM candidates."""
    from smt_checker import lemma_to_smt
    from reachable_filter import filter_candidates
    from lemma_nontriviality import gate_repaired_lemma as gate
    import time

    tm = btor_smt.tm
    trans = btor_smt.get_transition_constraints()
    init_c = btor_smt.get_init_constraints()
    samples = load_jsonl("logs/formal_yield/reachable_samples.json")

    results = []
    for s in schemas:
        if s["needs_llm"]: continue
        lemma = s["candidate_form"]
        print(f"\n  Validating: {lemma[:80]}")

        lt = lemma_to_smt(lemma, btor_smt.state_vars, tm)
        if lt is None:
            results.append({"lemma": lemma, "verdict": "parse_failed"})
            continue

        s_ = bz.Bitwuzla(tm, opts)
        for ic in init_c: s_.assert_formula(ic)
        s_.assert_formula(tm.mk_term(bz.Kind.NOT, [lt]))
        t0 = time.time()
        ri = s_.check_sat()
        r = {"lemma": lemma, "init": str(ri), "init_ms": int((time.time()-t0)*1000)}

        if str(ri) == "sat":
            r["verdict"] = "init_fail"
        else:
            lt_next = lemma_to_smt(lemma, btor_smt.next_vars, tm)
            if lt_next and trans:
                s_ = bz.Bitwuzla(tm, opts)
                for tc in trans: s_.assert_formula(tc)
                s_.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
                t0 = time.time()
                ros = s_.check_sat()
                r["step"] = str(ros)
                if str(ros) == "sat":
                    r["verdict"] = "one_step_fail"
                else:
                    s_ = bz.Bitwuzla(tm, opts)
                    s_.assert_formula(lt)
                    for tc in trans: s_.assert_formula(tc)
                    s_.assert_formula(tm.mk_term(bz.Kind.NOT, [lt_next]))
                    ri2 = s_.check_sat()
                    r["induction"] = str(ri2)
                    r["verdict"] = "solver_verified" if str(ri2) == "unsat" else "induction_fail"

        print(f"    {r['verdict']}: init={r['init']} step={r.get('step','?')} ind={r.get('induction','?')}")
        results.append(r)

    return results


def main():
    pred_path = "logs/pono_frame_dump/qspiflash_p040_predicates.jsonl"
    frame_path = "logs/pono_frame_dump/qspiflash_p040_frames.jsonl"
    cti_path = "logs/pono_frame_dump/qspiflash_p040_ctis.jsonl"

    # Phases A-C
    preds = phase_a_analyze_predicates(pred_path)
    value_data = phase_b_analyze_values(frame_path, cti_path)
    families = phase_c_extract_families(frame_path)

    # Phase D
    schemas = phase_d_generate_schemas(preds, value_data, families)

    out_dir = "logs/formal_yield"
    os.makedirs(out_dir, exist_ok=True)

    # Save all outputs
    with open(os.path.join(out_dir, "state15_predicate_analysis.json"), "w") as f:
        json.dump(preds, f, indent=2, default=str)

    with open(os.path.join(out_dir, "state15_value_distribution.json"), "w") as f:
        json.dump(value_data, f, indent=2)

    with open(os.path.join(out_dir, "state15_clause_families.json"), "w") as f:
        json.dump(families, f, indent=2, default=str)

    with open(os.path.join(out_dir, "state15_candidate_schema_plan.json"), "w") as f:
        json.dump(schemas, f, indent=2, default=str)

    print(f"\nSaved: state15_*.json files in {out_dir}")

    # Phase F: Validate obvious candidates
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()

    if args.validate:
        import bitwuzla as bz
        from smt_checker import parse_btor2, BTOR2SMT

        btor_path = os.path.expanduser(
            "~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/"
            "qspiflash_dualflexpress_divfive-p040.btor2")
        btor = parse_btor2(btor_path)
        btor_smt = BTOR2SMT(btor)
        bitwidths = {}
        for lid, p in btor.items():
            if p[0] == "state" and len(p) >= 2:
                bitwidths[f"state{lid}"] = int(p[1])
        opts = bz.Options(); opts.set(bz.Option.PRODUCE_MODELS, True)

        results = phase_f_validate_obvious(bz, btor_smt, opts, bitwidths, schemas)
        with open(os.path.join(out_dir, "state15_schema_validation.json"), "w") as f:
            json.dump(results, f, indent=2)
        print(f"Saved: state15_schema_validation.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
