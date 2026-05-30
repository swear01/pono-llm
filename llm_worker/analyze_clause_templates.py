#!/usr/bin/env python3
"""Task 87: Clause-shape-guided impact selection.

Extracts clause templates from frame dumps and ranks synthesis targets
by which clause families can be most impactfully compressed or generalized.
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


def variable_activity_pattern(lit):
    """Describe what a literal is doing: setting a variable to 0, to 1, etc."""
    sv = lit.get("state_values", {})
    if not sv: return "no_values"
    patterns = []
    for var, val in sorted(sv.items()):
        if val == "0": patterns.append(f"{var}=0")
        elif val == "1": patterns.append(f"{var}=1")
        else: patterns.append(f"{var}={val}")
    return ", ".join(patterns)


def analyze_clause_templates(frame_path, predicate_path):
    frames = load_jsonl(frame_path)
    predicates = load_jsonl(predicate_path)

    # Template classification
    templates = defaultdict(list)  # template_key → list of clause records
    template_frames = defaultdict(set)  # template_key → set of frames

    for clause in frames:
        frm = clause.get("frame", 0)
        lit_count = clause.get("literal_count", 0)
        lits = clause.get("literals", [])

        # Determine template
        if lit_count == 1:
            tkey = "single_literal"
        elif lit_count == 2:
            # Check variable structure
            all_vars = set()
            all_vals = {}
            for lit in lits:
                sv = lit.get("state_values", {})
                all_vals.update(sv)
                all_vars.update(lit.get("variables", []))
                all_vars.update(sv.keys())
            tkey = f"binary_{len(all_vars)}vars"
        elif lit_count >= 3:
            tkey = f"multi_{lit_count}_literals"
        else:
            tkey = "unknown"

        # Build variable pattern
        var_pattern = variable_activity_pattern(lits[0]) if lits else "empty"

        rec = {
            "frame": frm,
            "lit_count": lit_count,
            "template": tkey,
            "var_pattern": var_pattern,
            "raw_smt": clause.get("raw_smt", "")[:150],
        }
        templates[tkey].append(rec)
        template_frames[tkey].add(frm)

    # Summarize templates
    template_summary = []
    for tkey, recs in sorted(templates.items(), key=lambda x: -len(x[1])):
        frames_set = template_frames[tkey]
        # Group by var pattern
        pattern_counts = Counter(r["var_pattern"] for r in recs)
        template_summary.append({
            "template": tkey,
            "count": len(recs),
            "num_frames": len(frames_set),
            "max_frame": max(r["frame"] for r in recs),
            "top_patterns": pattern_counts.most_common(5),
            "sample_clause": recs[0]["raw_smt"] if recs else "",
        })

    # Identify clause families: same variable, different values
    # e.g., (state15 = 0) appears in 391 clauses — could a lemma generalize these?
    single_var_clauses = [r for r in templates.get("single_literal", [])
                          if "state" in r["var_pattern"]]

    var_family = defaultdict(list)
    for r in single_var_clauses:
        m = re.search(r'(state\d+)=(\d+)', r["var_pattern"])
        if m:
            var_family[m.group(1)].append(r)

    family_rankings = []
    for var, recs in var_family.items():
        if len(recs) < 3: continue
        frames_seen = set(r["frame"] for r in recs)
        values = set()
        for r in recs:
            m = re.search(r'=(.*)$', r["var_pattern"])
            if m: values.add(m.group(1))
        family_rankings.append({
            "variable": var,
            "clause_count": len(recs),
            "num_frames": len(frames_seen),
            "max_frame": max(r["frame"] for r in recs),
            "values_seen": sorted(values),
            "type": "single_var_family",
        })

    # Binary clause families: pairs that share a common variable
    binary_clauses = templates.get("binary_2vars", [])
    binary_families = defaultdict(list)
    for r in binary_clauses:
        vars_found = re.findall(r'state\d+', r["var_pattern"])
        if len(vars_found) >= 2:
            binary_families[tuple(sorted(vars_found))].append(r)

    for pair, recs in binary_families.items():
        if len(recs) < 3: continue
        frames_seen = set(r["frame"] for r in recs)
        family_rankings.append({
            "variable_pair": list(pair),
            "clause_count": len(recs),
            "num_frames": len(frames_seen),
            "max_frame": max(r["frame"] for r in recs),
            "type": "binary_pair_family",
        })

    # Sort by clause_count descending
    family_rankings.sort(key=lambda x: -x["clause_count"])

    return {
        "template_summary": template_summary,
        "top_families": family_rankings[:20],
        "total_clauses": len(frames),
        "single_literal_clauses": len(templates.get("single_literal", [])),
        "binary_clauses": len(templates.get("binary_2vars", [])),
    }


def main():
    result = analyze_clause_templates(
        frame_path="logs/pono_frame_dump/qspiflash_p040_frames.jsonl",
        predicate_path="logs/pono_frame_dump/qspiflash_p040_predicates.jsonl",
    )

    os.makedirs("logs/formal_yield", exist_ok=True)
    with open("logs/formal_yield/clause_templates.json", "w") as f:
        json.dump(result, f, indent=2, default=str)

    print("=== Clause Template Distribution ===")
    for t in result["template_summary"]:
        print(f"  {t['template']}: {t['count']} clauses across {t['num_frames']} frames")
        print(f"    max_frame={t['max_frame']}, top_patterns={t['top_patterns'][:2]}")
        print(f"    sample: {t['sample_clause'][:100]}")

    print(f"\n=== Top Clause Families (largest groups to compress) ===")
    for i, f in enumerate(result["top_families"][:10]):
        tp = f["type"]
        if tp == "single_var_family":
            print(f"  {i+1}. {f['variable']}: {f['clause_count']} clauses, "
                  f"frames={f['num_frames']}, "
                  f"values={f['values_seen'][:5]}")
        else:
            print(f"  {i+1}. {f.get('variable_pair', '?')}: {f['clause_count']} clauses, "
                  f"frames={f['num_frames']}")

    print(f"\nSingle-literal: {result['single_literal_clauses']}")
    print(f"Binary: {result['binary_clauses']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
