#!/usr/bin/env python3
"""WP7: Build generalization payloads from selected artifacts and modes."""

import json, os, sys, hashlib


def compute_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=6)
    args = p.parse_args()

    primer = open("prompts/pono_generalization_primer_v1.md").read()
    payload_tpl = open("prompts/pono_generalization_payload_template.md").read()
    modes = json.load(open("prompts/pono_generalization_modes.json"))["modes"]
    artifacts = json.load(
        open("logs/formal_yield/generalization_artifacts/selected_artifacts.json"))

    known_failures = [
        "state15=0 (one-step fails)",
        "(=> (not (and ...)) ...) — unsupported syntax",
        "(=> (or ...) ...) — unsupported syntax",
        "duplicate/contradictory antecedents fail nontriviality",
    ]

    primer_hash = compute_hash(primer)

    out = "logs/formal_yield/generalization_sampling"
    for sub in ["payloads", "prompts"]:
        os.makedirs(os.path.join(out, sub), exist_ok=True)

    batch_size = max(1, len(artifacts) // args.n)
    payloads = []

    for i in range(args.n):
        mode = modes[i % len(modes)]
        start = (i * batch_size) % len(artifacts)
        batch = artifacts[start:start + batch_size]

        artifacts_text = ""
        for a in batch:
            artifacts_text += f"- [{a['artifact_id']}] {a['artifact_type']}: "
            artifacts_text += f"{str(a.get('raw', a.get('lemma', '')))[:120]}\n"

        ops_text = ", ".join(mode["operators"])

        payload_text = payload_tpl.format(
            artifacts=artifacts_text,
            allowed_operators=ops_text,
            known_failures="\n".join(f"- {f}" for f in known_failures),
            requested_candidates=mode["candidate_count"],
        )

        full_prompt = primer + "\n\n" + payload_text
        payload_hash = compute_hash(payload_text)

        pp = os.path.join(out, "prompts", f"prompt_{i:03d}.txt")
        with open(pp, "w") as f:
            f.write(full_prompt)

        rec = {"index": i, "mode": mode["name"], "primer_hash": primer_hash,
               "payload_hash": payload_hash, "prompt_path": pp,
               "prompt_chars": len(full_prompt),
               "artifact_ids": [a["artifact_id"] for a in batch]}
        payloads.append(rec)
        pal_path = os.path.join(out, "payloads", f"payload_{i:03d}.json")
        with open(pal_path, "w") as f:
            json.dump(rec, f, indent=2)

    with open(os.path.join(out, "primer_hash.txt"), "w") as f:
        f.write(primer_hash + "\n")

    summary = {"n": args.n, "primer_hash": primer_hash,
               "primer_chars": len(primer), "payloads": payloads}
    with open(os.path.join(out, "payloads_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Generated {args.n} payloads (primer hash: {primer_hash})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
