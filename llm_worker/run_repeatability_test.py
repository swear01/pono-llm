#!/usr/bin/env python3
"""Phase B: Closed-loop repeatability test. 3 fresh trials."""

import json, os, sys, time, subprocess

OUT_DIR = "logs/formal_yield/closed_loop_repeatability"

TRIAL_CONFIGS = {
    "trial_1": {"out_dir": os.path.join(OUT_DIR, "trial_1")},
    "trial_2": {"out_dir": os.path.join(OUT_DIR, "trial_2")},
    "trial_3": {"out_dir": os.path.join(OUT_DIR, "trial_3")},
}

LEMMA_TARGET = "(=> (= state2002 1) (= state790 1))"


def find_lemma_in_candidates(candidates):
    """Check if the target lemma appears in any candidate."""
    for c in candidates:
        lemma = c.get("lemma", "")
        # Normalize spacing
        norm = lemma.replace(" ", "")
        target_norm = LEMMA_TARGET.replace(" ", "")
        if norm == target_norm:
            return True, c.get("candidate_id", "?")
    return False, None


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    all_results = []

    for trial_name, config in TRIAL_CONFIGS.items():
        trial_dir = config["out_dir"]
        os.makedirs(trial_dir, exist_ok=True)

        print(f"\n{'='*70}")
        print(f"TRIAL: {trial_name}")
        print(f"{'='*70}")

        # Run closed-loop synthesis command with --max-rounds 2 --candidates-per-round 3
        # We do this via subprocess but redirect output
        t0 = time.time()

        cmd = [
            sys.executable, "-u",
            "llm_worker/run_closed_loop_synthesis.py",
            "--max-rounds", "2",
            "--candidates-per-round", "3",
        ]
        env = os.environ.copy()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=900,
                env=env, cwd=os.getcwd()
            )
            elapsed = int(time.time() - t0)
            print(f"  Completed in {elapsed}s")
            if proc.stdout:
                # Extract key lines
                for line in proc.stdout.strip().split("\n"):
                    if any(kw in line for kw in ["SOLVER VERIFIED", "ROUND", "SUMMARY", "Verdict", "candidates"]):
                        print(f"  {line.strip()[:120]}")
            if proc.stderr:
                print(f"  stderr: {proc.stderr[:200]}")

            # Copy relevant outputs to trial dir
            import shutil
            src = "logs/formal_yield/closed_loop_synthesis"
            for rnd_dir in ["round_0", "round_1"]:
                src_path = os.path.join(src, rnd_dir)
                if os.path.exists(src_path):
                    # Read and save key files
                    for fname in ["parsed_candidates.json", "validation_results.json", "counterexamples.json"]:
                        spath = os.path.join(src_path, fname)
                        if os.path.exists(spath):
                            with open(spath) as f:
                                trial_data = json.load(f)
                            trial_out = os.path.join(trial_dir, f"{rnd_dir}_{fname}")
                            with open(trial_out, "w") as f:
                                json.dump(trial_data, f, indent=2)

            # Check results
            trial_result = {"trial": trial_name, "elapsed_s": elapsed, "verdict": "unknown",
                            "found_target_lemma": False, "found_other_useful": False}

            # Check round 0 candidates
            r0_path = os.path.join(src, "round_0", "parsed_candidates.json")
            r0_val_path = os.path.join(src, "round_0", "validation_results.json")
            if os.path.exists(r0_path):
                with open(r0_path) as f:
                    r0_cands = json.load(f).get("candidates", [])
                found, cid = find_lemma_in_candidates(r0_cands)
                trial_result["round_0_candidates"] = len(r0_cands)
                trial_result["round_0_has_target"] = found
                if found:
                    trial_result["target_found_round"] = 0
                    trial_result["target_found_as"] = cid

            # Check round 1 if it exists
            r1_path = os.path.join(src, "round_1", "parsed_candidates.json")
            r1_val_path = os.path.join(src, "round_1", "validation_results.json")
            if os.path.exists(r1_path) and os.path.exists(r1_val_path):
                with open(r1_path) as f:
                    r1_cands = json.load(f).get("candidates", [])
                with open(r1_val_path) as f:
                    r1_vals = json.load(f)
                found, cid = find_lemma_in_candidates(r1_cands)
                trial_result["round_1_candidates"] = len(r1_cands)
                trial_result["round_1_has_target"] = found
                if found:
                    trial_result["target_found_round"] = 1
                    trial_result["target_found_as"] = cid

                # Check for solver_verified_useful
                for v in r1_vals:
                    if v.get("verdict") == "solver_verified_useful":
                        trial_result["found_other_useful"] = True
                        trial_result["useful_lemma"] = v.get("lemma", "")[:150]
                        trial_result["verdict"] = "solver_verified_useful"
                        trial_result["useful_candidate_id"] = v.get("candidate_id", "?")

                if trial_result.get("round_1_has_target") and not trial_result.get("found_other_useful"):
                    # Check if target is the verified one
                    for v in r1_vals:
                        if v.get("lemma", "").replace(" ", "") == LEMMA_TARGET.replace(" ", ""):
                            if v.get("verdict") == "solver_verified_useful":
                                trial_result["verdict"] = "solver_verified_useful"
                                trial_result["target_verified"] = True

            print(f"  Result: target_lemma_found={trial_result.get('found_target_lemma') or trial_result.get('round_0_has_target') or trial_result.get('round_1_has_target')}, verdict={trial_result['verdict']}")

            all_results.append(trial_result)

        except subprocess.TimeoutExpired:
            print(f"  TIMEOUT after 900s")
            trial_result = {"trial": trial_name, "verdict": "timeout"}
            all_results.append(trial_result)
        except Exception as e:
            print(f"  ERROR: {e}")
            trial_result = {"trial": trial_name, "verdict": "error", "error": str(e)}
            all_results.append(trial_result)

    # Save results
    summary = {
        "trials": len(all_results),
        "results": all_results,
        "target_lemma": LEMMA_TARGET,
    }
    with open(os.path.join(OUT_DIR, "results.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved: {OUT_DIR}/results.json")

    # Print summary
    print(f"\n{'='*70}")
    print(f"REPEATABILITY SUMMARY")
    print(f"{'='*70}")
    for r in all_results:
        target_found = r.get("found_target_lemma") or r.get("round_0_has_target") or r.get("round_1_has_target")
        print(f"  {r['trial']}: found_target={target_found}, useful={r.get('found_other_useful')}, verdict={r['verdict']}")

    target_count = sum(1 for r in all_results
                       if r.get("found_target_lemma") or r.get("round_0_has_target") or r.get("round_1_has_target"))
    useful_count = sum(1 for r in all_results if r.get("verdict") == "solver_verified_useful")
    print(f"\n  Target lemma found in: {target_count}/{len(all_results)} trials")
    print(f"  Solver-verified useful in: {useful_count}/{len(all_results)} trials")

    return 0


if __name__ == "__main__":
    sys.exit(main())
