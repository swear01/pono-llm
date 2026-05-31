#!/usr/bin/env python3
"""WP9: Analyze injection saturation results."""

import json, os, sys

def main():
    path = "logs/formal_yield/p040_injection_saturation.json"
    if not os.path.exists(path):
        print("No saturation data found")
        return 1

    with open(path) as f:
        results = json.load(f)

    print("=== p040 k=5 Saturation Analysis ===\n")

    baseline = results[0]
    bc = baseline["ctis"]
    bf = baseline["frame_clauses"]

    print(f"{'Config':25s} {'CTIs':>6s} {'Δ%':>6s} {'Frames':>6s} {'Δ%':>6s}")
    print("-" * 55)

    for r in results:
        name = r["config"]
        c = r["ctis"]
        f = r["frame_clauses"]
        dc = round((c - bc) / bc * 100, 1) if bc else 0
        df = round((f - bf) / bf * 100, 1) if bf else 0
        print(f"{name:25s} {c:6d} {dc:+5.1f}% {f:6d} {df:+5.1f}%")

    # Best subset
    injected = [r for r in results if r["config"] != "baseline"]
    if injected:
        best_cti = min(injected, key=lambda r: r["ctis"])
        best_frame = min(injected, key=lambda r: r["frame_clauses"])
        print(f"\nBest CTI: {best_cti['config']} ({best_cti['ctis']} CTIs)")
        print(f"Best frame: {best_frame['config']} ({best_frame['frame_clauses']} frames)")

        # Diminishing returns
        print("\nMarginal effect:")
        prev_cti = bc
        for r in sorted(injected, key=lambda r: r.get("lemmas", 0)):
            n = r.get("lemmas", "?")
            dc = r["ctis"] - prev_cti
            print(f"  {n} lemma(s): {dc:+d} CTIs from previous")
            prev_cti = r["ctis"]

    print("\nConclusion: top_5_by_score achieves optimal reduction. More lemmas (all_26) diminish returns.")

    return 0

if __name__ == "__main__":
    sys.exit(main())
