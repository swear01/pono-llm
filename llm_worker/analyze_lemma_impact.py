#!/usr/bin/env python3
"""Lemma impact proxy analyzer.

Estimates whether a validated lemma is proof-relevant to IC3IA traces
by analyzing CTI cube and frame clause dumps.

Works with real Pono dumps or synthetic test fixtures.
"""

import json, os, sys, re
from typing import Dict, List, Optional, Set


class LemmaImpactAnalyzer:
    """Analyze lemma relevance from CTI and frame clause dumps."""

    def __init__(self, lemma: str = "(=> (= state2002 1) (= state790 1))"):
        self.lemma = lemma
        self.target_vars = {"state2002", "state790"}
        self.results = {}

    def load_jsonl(self, path: str) -> List[Dict]:
        records = []
        if not os.path.exists(path):
            return records
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return records

    def _var_in_record(self, record: Dict, var: str) -> bool:
        variables = record.get("variables", [])
        if var in variables:
            return True
        return self._var_in_text(json.dumps(record), var)

    def _var_in_text(self, text: str, var: str) -> bool:
        return var in text or (var.replace("state", "") in text)

    def _extract_variables(self, record: Dict) -> Set[str]:
        """Extract state variable names from a record."""
        vars_found = set()

        # From explicit variables list
        for v in record.get("variables", []):
            m = re.match(r'state\d+', v)
            if m:
                vars_found.add(m.group(0))

        # From literals
        for lit in record.get("cube", []) + record.get("literals", []):
            vn = lit.get("varname", "")
            expr = lit.get("expr", "")
            raw = lit.get("raw", "")
            for m in re.finditer(r'\b(state\d+)\b', vn + " " + expr + " " + raw):
                vars_found.add(m.group(1))

        # From raw SMT
        raw_smt = record.get("raw_smt", "")
        for m in re.finditer(r'\b(state\d+)\b', raw_smt):
            vars_found.add(m.group(1))

        return vars_found

    def _evaluate_lemma_on_cti(self, cti: Dict) -> Optional[bool]:
        """Check if the lemma holds on this CTI cube."""
        cube = cti.get("cube", [])
        vals = {}

        for lit in cube:
            vn = lit.get("varname", "")
            m = re.search(r'(state\d+)', vn)
            if not m:
                continue
            var = m.group(1)
            val = lit.get("value", "")
            if val in ("true", "1"):
                vals[var] = 1
            elif val in ("false", "0"):
                vals[var] = 0
            elif val.isdigit():
                vals[var] = int(val)

        # Check implication: state2002=1 => state790=1
        has_2002 = "state2002" in vals
        has_790 = "state790" in vals

        if not has_2002 and not has_790:
            return None  # not relevant
        if not has_2002:
            return None  # can't evaluate antecedent
        if not has_790:
            return None  # can't evaluate consequent

        ante_true = vals["state2002"] == 1
        cons_false = vals["state790"] == 0

        # Lemma violated when antecedent true AND consequent false
        return not (ante_true and cons_false)

    def analyze_ctis(self, cti_path: str) -> Dict:
        ctis = self.load_jsonl(cti_path)
        total = len(ctis)

        with_2002 = 0
        with_790 = 0
        with_both = 0
        violating = 0
        satisfying = 0
        ante_true = 0
        highest_frame = 0

        for cti in ctis:
            frm = cti.get("frame", cti.get("frame_idx", 0))
            if frm > highest_frame:
                highest_frame = frm

            has_2002 = self._var_in_record(cti, "state2002")
            has_790 = self._var_in_record(cti, "state790")

            if has_2002:
                with_2002 += 1
            if has_790:
                with_790 += 1
            if has_2002 and has_790:
                with_both += 1

            result = self._evaluate_lemma_on_cti(cti)
            if result is True:
                satisfying += 1
            elif result is False:
                violating += 1

            # Check antecedent satisfaction
            vals_for_ante = [
                lit.get("value")
                for lit in cti.get("cube", [])
                if re.search(r'state2002', lit.get("varname", ""))
                and lit.get("value") in ("true", "1")
            ]
            if vals_for_ante:
                ante_true += 1

        return {
            "total_ctis": total,
            "ctis_with_state2002": with_2002,
            "ctis_with_state790": with_790,
            "ctis_with_both": with_both,
            "ctis_violating_lemma": violating,
            "ctis_satisfying_lemma": satisfying,
            "ctis_antecedent_true": ante_true,
            "highest_frame_any_cti": highest_frame,
            "lemma_blocks": violating,
        }

    def analyze_frames(self, frame_path: str) -> Dict:
        frames = self.load_jsonl(frame_path)
        total = len(frames)

        with_2002 = 0
        with_790 = 0
        with_both = 0
        highest_frame = 0
        potentially_subsumeable = 0

        for clause in frames:
            frm = clause.get("frame", 0)
            if frm > highest_frame:
                highest_frame = frm

            has_2002 = self._var_in_record(clause, "state2002")
            has_790 = self._var_in_record(clause, "state790")

            if has_2002:
                with_2002 += 1
            if has_790:
                with_790 += 1
            if has_2002 and has_790:
                with_both += 1

            # Check potential subsumption: clauses with (NOT state2002 OR state790)
            # are implied by state2002 => state790
            raw = clause.get("raw_smt", "")
            if ("state2002" in raw or "2002" in raw) and ("state790" in raw or "790" in raw):
                if "not" in raw.lower():
                    potentially_subsumeable += 1

        return {
            "total_clauses": total,
            "clauses_with_state2002": with_2002,
            "clauses_with_state790": with_790,
            "clauses_with_both": with_both,
            "potential_subsumeable": potentially_subsumeable,
            "highest_frame_with_either": highest_frame,
        }

    def classify_impact(self, cti_results: Dict, frame_results: Dict) -> str:
        cti_violating = cti_results.get("ctis_violating_lemma", 0)
        cti_total = cti_results.get("total_ctis", 0)
        frame_both = frame_results.get("clauses_with_both", 0)
        frame_total = frame_results.get("total_clauses", 0)

        if cti_total == 0 and frame_total == 0:
            return "unknown_no_trace_data"

        violation_rate = cti_violating / max(cti_total, 1)
        frame_rate = frame_both / max(frame_total, 1)

        if violation_rate > 0.1 or frame_rate > 0.05:
            return "high_potential"
        elif violation_rate > 0 or frame_rate > 0:
            return "medium_potential"
        else:
            return "low_potential"

    def run(self, cti_path: Optional[str] = None,
            frame_path: Optional[str] = None,
            obligation_path: Optional[str] = None) -> Dict:

        cti_results = {}
        frame_results = {}
        obligation_results = {}

        if cti_path and os.path.exists(cti_path):
            cti_results = self.analyze_ctis(cti_path)

        if frame_path and os.path.exists(frame_path):
            frame_results = self.analyze_frames(frame_path)

        impact = self.classify_impact(cti_results, frame_results)

        missing = []
        if not cti_path or not os.path.exists(cti_path):
            missing.append("cti_path")
        if not frame_path or not os.path.exists(frame_path):
            missing.append("frame_path")

        return {
            "lemma": self.lemma,
            "target_variables": list(self.target_vars),
            "impact_classification": impact,
            "cti_analysis": cti_results,
            "frame_analysis": frame_results,
            "obligation_analysis": obligation_results,
            "missing_files": missing,
            "notes": self._generate_notes(impact, cti_results, frame_results, missing),
        }

    def _generate_notes(self, impact, cti, frames, missing):
        notes = []
        if missing:
            notes.append(f"Missing data: {', '.join(missing)}. Impact estimate based on partial data only.")

        cti_v = cti.get("ctis_violating_lemma", 0)
        cti_t = cti.get("total_ctis", 0)
        if cti_t > 0:
            notes.append(f"CTI violation rate: {cti_v}/{cti_t} ({100*cti_v//max(cti_t,1)}%)")

        frame_b = frames.get("clauses_with_both", 0)
        frame_t = frames.get("total_clauses", 0)
        if frame_t > 0:
            notes.append(f"Clauses with both vars: {frame_b}/{frame_t} ({100*frame_b//max(frame_t,1)}%)")

        if impact == "high_potential":
            notes.append("Lemma appears highly relevant to proof traces. Consider rel_ind_check integration.")
        elif impact == "low_potential":
            notes.append("Lemma is formally valid but may have limited proof-trace impact. Consider broader synthesis.")
        elif impact == "unknown_no_trace_data":
            notes.append("No trace data available. Need Pono IC3IA dump to estimate impact.")

        return notes


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Lemma impact proxy analyzer")
    parser.add_argument("--ctis", default="", help="Path to CTI JSONL file")
    parser.add_argument("--frames", default="", help="Path to frame clause JSONL file")
    parser.add_argument("--obligations", default="", help="Path to obligation JSONL file")
    parser.add_argument("--lemma", default="(=> (= state2002 1) (= state790 1))",
                        help="Lemma to analyze")
    parser.add_argument("--out", default="logs/formal_yield/lemma_impact_proxy.json",
                        help="Output JSON path")
    parser.add_argument("--report", default="", help="Output markdown report path")
    args = parser.parse_args()

    analyzer = LemmaImpactAnalyzer(args.lemma)
    result = analyzer.run(args.ctis, args.frames, args.obligations)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Saved: {args.out}")

    print(f"\nImpact: {result['impact_classification']}")
    for note in result["notes"]:
        print(f"  {note}")

    if args.report:
        write_report(result, args.report)

    return 0


def write_report(result: Dict, path: str):
    lines = [
        "# Lemma Impact Proxy",
        "",
        f"**Lemma**: `{result['lemma']}`",
        f"**Impact**: `{result['impact_classification']}`",
        "",
        "## CTI Analysis",
        "| Metric | Count |",
        "|---|---|",
    ]
    for k, v in result.get("cti_analysis", {}).items():
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "## Frame Analysis",
        "| Metric | Count |",
        "|---|---|",
    ]
    for k, v in result.get("frame_analysis", {}).items():
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "## Notes",
    ]
    for note in result.get("notes", []):
        lines.append(f"- {note}")
    lines += [
        "",
        "## Interpretation",
        f"Impact: `{result['impact_classification']}`",
    ]
    if result["impact_classification"] == "unknown_no_trace_data":
        lines.append("IC3IA frame/CTI data is not available. "
                     "Run Pono with `PONO_LLM_DUMP_IC3IA=1` to generate data.")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Report: {path}")


if __name__ == "__main__":
    sys.exit(main())
