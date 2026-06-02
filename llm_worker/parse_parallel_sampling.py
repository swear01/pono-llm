#!/usr/bin/env python3
"""WP7: Parse parallel sampling responses. WP8: Validate. WP9: Rank."""

import json, os, sys, re, glob
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def find_latest_run():
    runs = sorted(glob.glob("logs/formal_yield/parallel_sampling/runs/run_*"))
    return runs[-1] if runs else None


def parse_responses(run_dir):
    raw_dir = os.path.join(run_dir, "raw")
    candidates = []
    fails = 0
    for fpath in sorted(glob.glob(os.path.join(raw_dir, "response_*.txt"))):
        with open(fpath) as f:
            text = f.read()
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
            if m:
                try: result = json.loads(m.group(1))
                except: fails += 1; continue
            else:
                fails += 1; continue
        for c in result.get("candidates", []):
            c["_source_file"] = os.path.basename(fpath)
            candidates.append(c)

    # Dedup
    seen = set()
    unique = []
    for c in candidates:
        key = c.get("lemma", "").replace(" ", "")
        if key and key not in seen:
            seen.add(key)
            unique.append(c)

    schemas = Counter(c.get("schema", "unknown") for c in unique)
    vars_set = Counter()
    for c in unique:
        for v in c.get("variables", []):
            vars_set[v] += 1

    report = {
        "total_raw": len(candidates) + fails,
        "parse_fails": fails,
        "parse_ok": len(candidates),
        "unique": len(unique),
        "schema_distribution": dict(schemas),
        "top_variables": vars_set.most_common(10),
    }
    with open(os.path.join(run_dir, "parsed_candidates.json"), "w") as f:
        json.dump(unique, f, indent=2, default=str)
    with open(os.path.join(run_dir, "candidate_parse_report.json"), "w") as f:
        json.dump(report, f, indent=2)

    print(f"Parsed: {len(candidates)} raw, {len(unique)} unique ({len(schemas)} schemas)")
    return unique, report


def main():
    run_dir = find_latest_run()
    if not run_dir:
        print("No runs found. Run run_parallel_sampling.py first.")
        return 1
    print(f"Run: {run_dir}")
    candidates, report = parse_responses(run_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
