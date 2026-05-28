#!/usr/bin/env python3
"""Build repair prompt and optionally run LLM repair batch (Phases C/D)."""

import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT_DIR = "logs/formal_yield"

FAILED_CANDIDATES = [
    {
        "candidate_id": "cand_007",
        "lemma": "(=> (= state1536 10) (= state790 0))",
        "schema": "guarded_implication",
        "verilog": {"state1536": "o_dspi_mod", "state790": "o_wb_stall"},
        "failure_class": "overstrong_implication",
        "counterexample": {
            "current": {"state1536": "0", "state790": "0"},
            "next": {"state1536": "10", "state790": "1"},
            "inputs": {"i_reset": "0"},
            "interpretation": "antecedent holds (mode=10) but consequent fails (stall=1 not 0). In real design, o_wb_stall=1 when o_dspi_mod=10.",
        },
        "repair_hints": [
            "Try reversed implication: (=> (= state790 1) (= state1536 10))",
            "Try weakening consequent to match system: (=> (= state1536 10) (= state790 1))",
            "Consider if a guard on i_reset or other condition would make this true",
        ],
    },
    {
        "candidate_id": "cand_008",
        "lemma": "(=> (= state1536 0) (= state1558 0))",
        "schema": "guarded_implication",
        "verilog": {"state1536": "o_dspi_mod", "state1558": "cfg_speed"},
        "failure_class": "overstrong_implication",
        "counterexample": {
            "current": {"state1536": "0", "state1558": "0"},
            "next": {"state1536": "0", "state1558": "1"},
            "inputs": {"i_cfg_stb": "1", "i_reset": "0"},
            "interpretation": "cfg_speed=1 reached while mode stays 0. Config strobe (i_cfg_stb=1) drives cfg_speed change independent of mode.",
        },
        "repair_hints": [
            "Add guard: (=> (and (= state1536 0) (not i_cfg_stb)) (= state1558 0))",
            "Weak consequent: (=> (= state1536 0) (<= state1558 1))",
            "Consider rejecting if cfg_speed is truly independent of mode",
        ],
    },
    {
        "candidate_id": "cand_004",
        "lemma": "(=> (= state2002 1) (= state1536 0))",
        "schema": "guarded_implication",
        "verilog": {"state2002": "r_pipe_req", "state1536": "o_dspi_mod"},
        "failure_class": "overstrong_implication",
        "counterexample": {
            "current": {"state2002": "0", "state1536": "0"},
            "next": {"state2002": "1", "state1536": "15"},
            "inputs": {"i_reset": "0"},
            "interpretation": "r_pipe_req=1 AND mode=15 (not 0). Mode is non-zero when request is active.",
        },
        "repair_hints": [
            "Consequent != 0: (=> (= state2002 1) (not (= state1536 0)))",
            "Mode range: (=> (= state2002 1) (>= state1536 10))",
            "Consider if this is just correlation rather than causation",
        ],
    },
]

REPAIR_PROMPT_TEMPLATE = """You are a formal-methods repair engine. Below are 3 semantic lemma candidates that passed init checks but failed one-step transition checks. For each failed lemma, a SAT counterexample model is provided showing the exact next-state assignment that violates the lemma.

For each candidate, propose up to 3 repaired lemma variants. Use the failure model and repair hints to guide your repair strategy.

## Output contract

Return a JSON object with a "repairs" array:

```json
{{
  "repairs": [
    {{
      "source_candidate_id": "cand_007",
      "repair_id": "cand_007_repair_1",
      "repaired_lemma": "(=> (= state790 1) (= state1536 10))",
      "repair_strategy": "reverse_implication",
      "variables": ["state1536", "state790"],
      "rationale": "...",
      "risk": "medium"
    }}
  ]
}}
```

## Rules

- Use only variables present in the original lemma or counterexample context.
- Prefer SHORT lemmas (1-2 variables).
- Do NOT invent unrelated variables.
- Available repair strategies: add_guard, weaken, reverse_implication, schema_change, reject.
- If the counterexample shows the relation is merely correlation (not causation), use strategy "reject" with reasond "correlation, not causation".
- Use "risk" values: low (likely correct), medium (plausible), high (speculative).

## Failed Lemmas

{lemmas_section}

## Counterexample Models

{models_section}

Now generate repairs for all {num_candidates} candidates. Return only valid JSON.
"""


def build_prompt(output_dir):
    lemmas_section = ""
    models_section = ""

    for i, cand in enumerate(FAILED_CANDIDATES):
        lemmas_section += f"\n### Candidate {i+1}: {cand['candidate_id']}\n"
        lemmas_section += f"Lemma: {cand['lemma']}\n"
        lemmas_section += f"Schema: {cand['schema']}\n"
        lemmas_section += f"Verilog: {json.dumps(cand['verilog'])}\n"
        lemmas_section += f"Failure class: {cand['failure_class']}\n"

        ce = cand["counterexample"]
        models_section += f"\n### Candidate {i+1}: {cand['candidate_id']}\n"
        models_section += "Current state: " + ", ".join(f"{k}={v}" for k, v in ce["current"].items()) + "\n"
        models_section += "Next state: " + ", ".join(f"{k}={v}" for k, v in ce["next"].items()) + "\n"
        models_section += "Inputs: " + ", ".join(f"{k}={v}" for k, v in ce["inputs"].items()) + "\n"
        models_section += f"Interpretation: {ce['interpretation']}\n"
        models_section += "Repair hints: " + "; ".join(cand["repair_hints"]) + "\n"

    prompt = REPAIR_PROMPT_TEMPLATE.format(
        lemmas_section=lemmas_section.strip(),
        models_section=models_section.strip(),
        num_candidates=len(FAILED_CANDIDATES),
    )

    os.makedirs(output_dir, exist_ok=True)

    prompt_file = os.path.join(output_dir, "repair_batch_prompt.txt")
    with open(prompt_file, "w") as f:
        f.write(prompt)
    print(f"Prompt: {prompt_file} ({len(prompt)} chars)")

    lemmas_record = {
        "num_candidates": len(FAILED_CANDIDATES),
        "candidates": FAILED_CANDIDATES,
    }
    record_file = os.path.join(output_dir, "repair_prompt_candidates.json")
    with open(record_file, "w") as f:
        json.dump(lemmas_record, f, indent=2)
    print(f"Record: {record_file}")

    return prompt


def run_llm_repair(prompt):
    from deepseek_client import DeepSeekClient, get_api_key

    api_key = get_api_key()
    if not api_key:
        print("ERROR: No API key — set DEEPSEEK_API_KEY or OPENROUTER_API_KEY")
        return None

    client = DeepSeekClient(api_key, model_name="deepseek-v4-pro")
    print(f"Calling LLM ({len(prompt)} char prompt)...")

    try:
        response_text, tokens, latency_ms = client.call(prompt)
        print(f"  Tokens: {tokens}, Latency: {latency_ms:.0f}ms")
    except Exception as e:
        print(f"  LLM error: {e}")
        return None

    out_dir = os.path.join(OUT_DIR, "repair_llm")
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "prompt.txt"), "w") as f:
        f.write(prompt)
    with open(os.path.join(out_dir, "raw_response.txt"), "w") as f:
        f.write(response_text)

    # Parse response
    try:
        # Try direct JSON
        result = json.loads(response_text)
    except json.JSONDecodeError:
        # Try extracting JSON from markdown
        import re
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if m:
            try:
                result = json.loads(m.group(1))
            except json.JSONDecodeError:
                print("  Parse failed: could not extract JSON")
                return None
        else:
            # Try to find any JSON object
            m = re.search(r'\{(?:[^{}]|\{[^{}]*\})*\}', response_text)
            if m:
                try:
                    result = json.loads(m.group(0))
                except json.JSONDecodeError:
                    print("  Parse failed: no valid JSON found")
                    return None
            else:
                print("  Parse failed: no JSON found")
                return None

    repairs = result.get("repairs", [])
    if not repairs:
        print("  No repairs in response")
        return None

    with open(os.path.join(out_dir, "parsed_repairs.json"), "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Parsed {len(repairs)} repairs")

    metadata = {
        "model": "deepseek-v4-pro",
        "tokens": tokens,
        "latency_ms": latency_ms,
        "prompt_chars": len(prompt),
        "num_candidates": len(FAILED_CANDIDATES),
        "num_repairs": len(repairs),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(os.path.join(out_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build repair prompt and optionally run LLM")
    parser.add_argument("--no-llm", action="store_true", help="Only build prompt, skip LLM")
    parser.add_argument("--output-dir", default=OUT_DIR, help="Output directory")
    args = parser.parse_args()

    prompt = build_prompt(args.output_dir)
    print(f"\nPrompt first 500 chars:\n{prompt[:500]}\n")

    if args.no_llm:
        print("--no-llm: skipping LLM call")
        return 0

    result = run_llm_repair(prompt)
    if result:
        print(f"\nRepair summary: {len(result.get('repairs', []))} repairs generated")
    else:
        print("\nRepair failed or no results")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
