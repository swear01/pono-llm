#!/usr/bin/env python3
"""WP6: Parallel sampling runner with thinking/temperature config."""

import json, os, sys, time, glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--max-calls", type=int, default=4)
    p.add_argument("--thinking", type=str, default="none")
    p.add_argument("--temperature", type=float, default=0.8)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--parallelism", type=int, default=1)
    args = p.parse_args()

    payloads_dir = "logs/formal_yield/parallel_sampling/payloads"
    payloads = sorted(glob.glob(os.path.join(payloads_dir, "payload_*.json")))
    if not payloads:
        print("No payloads found. Run build_sampling_payloads.py first.")
        return 1

    payloads = payloads[:args.max_calls]
    run_id = f"run_{int(time.time())}"
    out_dir = f"logs/formal_yield/parallel_sampling/runs/{run_id}"
    for sub in ["raw", "metadata", "parsed"]:
        os.makedirs(os.path.join(out_dir, sub), exist_ok=True)

    print(f"Run ID: {run_id}")
    print(f"Payloads: {len(payloads)}")
    print(f"Thinking: {args.thinking}, Temperature: {args.temperature}")
    print(f"Dry-run: {args.dry_run}")

    if args.dry_run:
        print("DRY-RUN: prompts ready but no LLM calls made.")
        with open(os.path.join(out_dir, "summary.json"), "w") as f:
            json.dump({"run_id": run_id, "dry_run": True,
                       "payloads_count": len(payloads)}, f, indent=2)
        return 0

    from deepseek_client import DeepSeekClient, get_api_key
    api_key = get_api_key()
    if not api_key:
        print("No API key. Use --dry-run or set DEEPSEEK_API_KEY.")
        with open(os.path.join(out_dir, "summary.json"), "w") as f:
            json.dump({"run_id": run_id, "blocked": "no_api_key"}, f, indent=2)
        return 1

    client = DeepSeekClient(api_key, model_name="deepseek-v4-pro")
    results = []

    for i, ppath in enumerate(payloads):
        with open(ppath) as f:
            prec = json.load(f)
        prompt_path = prec["prompt_path"]
        if not os.path.exists(prompt_path):
            continue

        with open(prompt_path) as f:
            prompt = f.read()

        print(f"\n[{i+1}/{len(payloads)}] mode={prec['mode']} ({len(prompt)} chars)")

        raw_path = os.path.join(out_dir, "raw", f"response_{i:03d}.txt")
        meta_path = os.path.join(out_dir, "metadata", f"meta_{i:03d}.json")

        try:
            t0 = time.time()
            response_text, tokens, latency_ms = client.call(prompt)
            runtime = int(time.time() - t0)

            with open(raw_path, "w") as f:
                f.write(response_text)

            meta = {
                "index": i, "mode": prec["mode"], "seed": prec["diversity_seed"],
                "primer_hash": prec["primer_hash"], "payload_hash": prec["payload_hash"],
                "thinking": args.thinking, "temperature": args.temperature,
                "tokens": tokens, "latency_ms": latency_ms, "runtime_s": runtime,
            }
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)

            print(f"  {tokens} tokens, {latency_ms/1000:.1f}s")
            results.append(meta)
        except Exception as e:
            print(f"  ERROR: {e}")
            with open(meta_path, "w") as f:
                json.dump({"error": str(e)}, f)

    summary = {"run_id": run_id, "calls": len(results),
               "results": results, "thinking": args.thinking,
               "temperature": args.temperature}
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nCompleted: {len(results)}/{len(payloads)} calls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
