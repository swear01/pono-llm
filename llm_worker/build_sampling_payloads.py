#!/usr/bin/env python3
"""WP5: Build cached primer + dynamic payloads for parallel lemma sampling."""

import json, os, sys, hashlib, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


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


def compute_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def build_payloads(n=16, mode_cycle=None, target="state15"):
    primer = open("prompts/pono_sampler_primer_v1.md").read()
    payload_tpl = open("prompts/pono_sampler_payload_template.md").read()
    modes_data = json.load(open("prompts/pono_sampler_modes.json"))
    modes = modes_data["modes"]
    if not mode_cycle:
        mode_cycle = [m["name"] for m in modes]

    frame_clauses = load_jsonl("logs/pono_frame_dump/qspiflash_p040_frames.jsonl")
    ctis = load_jsonl("logs/pono_frame_dump/qspiflash_p040_ctis.jsonl")

    # Get representative frame clauses containing target variable
    target_clauses = []
    for cl in frame_clauses:
        raw = cl.get("raw_smt", "")
        if target in raw or any(target in v for lit in cl.get("literals", [])
                                 for v in lit.get("variables", [])):
            target_clauses.append(raw[:120])
            if len(target_clauses) >= 5: break

    # Get representative CTIs
    target_ctis = []
    for cti in ctis:
        cube_str = str(cti.get("cube", []))
        if target in cube_str:
            target_ctis.append(cube_str[:120])
            if len(target_ctis) >= 3: break

    known_failures = [
        "state15=0 (one-step fails)",
        "state15!=1 (equivalent, fails)",
        "state2002=>state790 (verified but low impact)",
        "pairwise implications without guards (one-step fails)",
    ]

    primer_hash = compute_hash(primer)
    os.makedirs("logs/formal_yield/parallel_sampling/prompts", exist_ok=True)
    os.makedirs("logs/formal_yield/parallel_sampling/payloads", exist_ok=True)

    payloads = []
    for i in range(n):
        mode = mode_cycle[i % len(mode_cycle)]
        mode_info = next((m for m in modes if m["name"] == mode), modes[0])

        ctx = f"Target frontier variable: {target}. Sampling mode: {mode}. Generate {mode_info['candidate_count']} lemmas."
        payload_text = payload_tpl.format(
            sampling_mode=mode,
            diversity_seed=i,
            requested_candidates=mode_info["candidate_count"],
            target_context=ctx,
            frame_clauses="\n".join(f"- {c}" for c in target_clauses[:4]),
            cti_examples="\n".join(f"- {c}" for c in target_ctis[:2]),
            known_failures="\n".join(f"- {f}" for f in known_failures[:3]),
        )

        payload_hash = compute_hash(payload_text)
        full_prompt = primer + "\n\n" + payload_text

        prompt_path = f"logs/formal_yield/parallel_sampling/prompts/prompt_{i:03d}.txt"
        payload_path = f"logs/formal_yield/parallel_sampling/payloads/payload_{i:03d}.json"

        with open(prompt_path, "w") as f:
            f.write(full_prompt)

        rec = {
            "index": i, "mode": mode, "diversity_seed": i,
            "primer_hash": primer_hash, "payload_hash": payload_hash,
            "prompt_path": prompt_path, "payload_path": payload_path,
            "prompt_chars": len(full_prompt),
        }
        with open(payload_path, "w") as f:
            json.dump(rec, f, indent=2)
        payloads.append(rec)

    # Save summary
    with open("logs/formal_yield/parallel_sampling/primer_hash.txt", "w") as f:
        f.write(primer_hash + "\n")

    summary = {"n": n, "primer_hash": primer_hash, "primer_chars": len(primer),
               "payloads": payloads}
    with open("logs/formal_yield/parallel_sampling/payloads_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Generated {n} payloads (primer={primer_hash}, {len(primer)} chars)")
    for p in payloads[:5]:
        print(f"  [{p['index']}] mode={p['mode']} hash={p['payload_hash']} "
              f"chars={p['prompt_chars']}")
    if n > 5:
        print(f"  ... and {n-5} more")
    return 0


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=8)
    p.add_argument("--target", default="state15")
    args = p.parse_args()
    return build_payloads(n=args.n, target=args.target)


if __name__ == "__main__":
    sys.exit(main())
