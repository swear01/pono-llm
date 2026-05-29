#!/usr/bin/env python3
"""Apply nontriviality gate to repaired lemmas and report results.

Usage: python3 llm_worker/gate_repaired_lemmas.py
"""

import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smt_checker import parse_btor2
from lemma_nontriviality import gate_repaired_lemma

BTOR2_PATH = os.path.expanduser(
    "~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/"
    "qspiflash_dualflexpress_divfive-p040.btor2"
)

CE_DIR = "logs/formal_yield/counterexamples"

# Map source candidate to original candidate variables and CE
ORIGINAL_CANDIDATES = {
    "cand_007": {
        "vars": ["state1536", "state790"],
        "ce_file": os.path.join(CE_DIR, "cand_007_one_step_model.json"),
    },
    "cand_008": {
        "vars": ["state1536", "state1558"],
        "ce_file": os.path.join(CE_DIR, "cand_008_one_step_model.json"),
    },
    "cand_004": {
        "vars": ["state2002", "state1536"],
        "ce_file": os.path.join(CE_DIR, "cand_004_one_step_model.json"),
    },
}


def load_bitwidths(btor):
    """Extract {stateVar: bitwidth} from BTOR2 dict."""
    bw = {}
    for lid, p in btor.items():
        if p[0] == "state" and len(p) >= 2:
            bw[f"state{lid}"] = int(p[1])
    return bw


def load_parsed_repairs():
    """Load parsed repairs from LLM output."""
    with open("logs/formal_yield/repair_llm/parsed_repairs.json") as f:
        data = json.load(f)
    return data.get("repairs", [])


def load_validation_results():
    """Load solver validation results for repairs."""
    with open("logs/formal_yield/repaired_solver_validation_results.json") as f:
        return json.load(f)


def main():
    btor = parse_btor2(BTOR2_PATH)
    bitwidths = load_bitwidths(btor)
    print(f"Bitwidths: {len(bitwidths)} states")
    for var, w in sorted(bitwidths.items()):
        if var in ("state1536", "state790", "state1558", "state2002", "state79"):
            print(f"  {var}: {w}-bit")

    repairs = load_parsed_repairs()
    validations = load_validation_results()

    # Build validations lookup
    val_lookup = {}
    for v in validations:
        val_lookup[v["repair_id"]] = v

    # Load original CEs
    ce_lookup = {}
    for src_id, info in ORIGINAL_CANDIDATES.items():
        ce_file = info["ce_file"]
        if os.path.exists(ce_file):
            with open(ce_file) as f:
                ce_lookup[src_id] = json.load(f)
            print(f"  Loaded CE: {src_id} ({ce_file})")
        else:
            print(f"  No CE: {src_id}")

    gated_results = []
    for rep in repairs:
        rid = rep["repair_id"]
        src_id = rep["source_candidate_id"]
        lemma = rep["repaired_lemma"]

        val = val_lookup.get(rid, {})
        solver_verdict = val.get("verdict", "no_solver_data")

        orig_info = ORIGINAL_CANDIDATES.get(src_id, {})
        orig_vars = orig_info.get("vars", [])
        orig_ce = ce_lookup.get(src_id)

        gr = gate_repaired_lemma(
            lemma=lemma,
            bitwidths=bitwidths,
            original_vars=orig_vars,
            original_ce=orig_ce,
            solver_verdict=solver_verdict,
        )

        gr["repair_id"] = rid
        gr["source_candidate_id"] = src_id
        gr["repair_strategy"] = rep.get("repair_strategy", "unknown")
        gr["llm_risk"] = rep.get("risk", "unknown")

        gated_results.append(gr)

        print(f"\n--- {rid} ({rep.get('repair_strategy', '?')}) ---")
        print(f"  Lemma: {lemma[:80]}")
        print(f"  Solver: {solver_verdict}")
        print(f"  Gate:   {gr['gate_verdict']}")
        for issue in gr["issues"]:
            print(f"  Issue:  {issue}")

    # Save
    os.makedirs("logs/formal_yield", exist_ok=True)
    with open("logs/formal_yield/gated_repair_results.json", "w") as f:
        json.dump(gated_results, f, indent=2)
    print(f"\nSaved: logs/formal_yield/gated_repair_results.json")

    # Summary
    from collections import Counter
    verdict_counts = Counter(r["gate_verdict"] for r in gated_results)
    print(f"\n=== Gate Verdict Summary ===")
    for v, c in verdict_counts.most_common():
        print(f"  {v}: {c}")

    # Check downgrades
    downgraded = []
    for gr in gated_results:
        solver = gr.get("solver_verdict", "")
        gate = gr.get("gate_verdict", "")
        if solver in ("solver_verified_strong", "solver_inductive") and gate != "solver_verified_useful":
            downgraded.append(gr)

    print(f"\n=== Downgraded Repairs ===")
    for d in downgraded:
        print(f"  {d['repair_id']}: {d['solver_verdict']} → {d['gate_verdict']}")
        print(f"    Issues: {d['issues']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
