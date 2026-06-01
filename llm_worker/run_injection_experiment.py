#!/usr/bin/env python3
"""WP2: Clean-run harness for repeated injection experiments.

Each run gets its own output directory. No stale logs.
"""

import json, os, sys, time, subprocess, shutil

BTOR2 = os.path.expanduser(
    "~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/"
    "qspiflash_dualflexpress_divfive-p040.btor2")

OUT_BASE = "logs/formal_yield/injection_experiments"


def run_one(cfg_name, lemma_list_path="", seed=None, k=5, timeout=600):
    """Run pono once and extract artifact counts."""
    run_id = f"{cfg_name}_{int(time.time())}"
    out_dir = os.path.join(OUT_BASE, run_id)
    dump_dir = os.path.join(out_dir, "dump")
    os.makedirs(dump_dir, exist_ok=True)

    env = os.environ.copy()
    env["PONO_LLM_DUMP_IC3IA"] = "1"
    env["PONO_LLM_DUMP_DIR"] = dump_dir

    cmd = ["build/pono", "-e", "ic3ia", "-k", str(k)]
    if seed is not None:
        cmd += ["--random-seed", str(seed)]
    cmd.append(BTOR2)

    if lemma_list_path and os.path.exists(lemma_list_path):
        env["PONO_LLM_ASSERT_LIFTED_LEMMAS"] = "1"
        env["PONO_LLM_LEMMA_LIST"] = lemma_list_path

    t0 = time.time()
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
        runtime = int(time.time() - t0)
    except subprocess.TimeoutExpired:
        runtime = -1

    # Count artifacts
    ctis = 0
    frames = 0
    preds = 0
    for f in os.listdir(dump_dir):
        fp = os.path.join(dump_dir, f)
        if not os.path.isfile(fp): continue
        try:
            count = sum(1 for _ in open(fp))
        except: count = 0
        if "ctis" in f: ctis = count
        elif "frames" in f: frames = count
        elif "predicates" in f: preds = count

    result = {
        "cfg": cfg_name, "run_id": run_id, "seed": seed, "k": k,
        "ctis": ctis, "frames": frames, "predicates": preds,
        "runtime_s": runtime,
    }
    with open(os.path.join(out_dir, "metadata.json"), "w") as f:
        json.dump(result, f, indent=2)

    status = f"CTIs:{ctis} frames:{frames} preds:{preds} time:{runtime}s"
    print(f"  {cfg_name}: {status}")
    return result


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--k", type=int, default=5)
    args = p.parse_args()

    os.makedirs(OUT_BASE, exist_ok=True)
    all_results = []

    for cfg, path in [
        ("baseline", ""),
        ("top_5", "logs/formal_yield/lemma_lists/top_5_by_score.txt"),
    ]:
        for rep in range(args.reps):
            print(f"\n{cfg} rep {rep+1}/{args.reps}:")
            r = run_one(cfg, path, seed=args.seed, k=args.k, timeout=600)
            all_results.append(r)

    # Summarize
    baseline = [r for r in all_results if r["cfg"] == "baseline"]
    injected = [r for r in all_results if r["cfg"] != "baseline"]

    if baseline:
        b_cti = [r["ctis"] for r in baseline if r["ctis"] > 0]
        b_frames = [r["frames"] for r in baseline if r["frames"] > 0]
        print(f"\nBaseline (n={len(b_cti)}): CTIs mean={sum(b_cti)/max(len(b_cti),1):.0f} range=[{min(b_cti)}-{max(b_cti)}]")
        print(f"  frames mean={sum(b_frames)/max(len(b_frames),1):.0f} range=[{min(b_frames)}-{max(b_frames)}]")

    if injected:
        i = injected[0]
        print(f"{i['cfg']}: CTIs={i['ctis']} frames={i['frames']} time={i['runtime_s']}s")

    out = {"results": all_results, "seed": args.seed, "reps": args.reps}
    with open(os.path.join(OUT_BASE, f"run_summary_s{args.seed}.json"), "w") as f:
        json.dump(out, f, indent=2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
