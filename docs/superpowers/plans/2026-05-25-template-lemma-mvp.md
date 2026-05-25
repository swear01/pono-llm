# Template-Guided Semantic Lemma Generation — MVP v0 + v0.5

> **Goal:** Prove LLM can generate nontrivial, schema-valid, semantically plausible lemma candidates that are NOT merely CTI cube subsets.

> **Scope:** context dump → prompt → LLM candidates → cheap validation → manual inspection.
> NO automated BMC/induction gate yet. NO IC3IA loop integration yet.

**Architecture:** Offline MVP — Python scripts for context extraction, prompt building, candidate collection; LLM call via existing sidecar; manual evaluation.

**Tech Stack:** Python 3, DeepSeek V4 Pro API, Pono IC3IA engine

---
## Execution Status (2026-05-25)

### Completed
- [x] Task 1: `lemma_schema.py` — 8 lemma families, syntax/triviality/cube-subset validation
- [x] Task 2: `transition_slice.py` — hot variable extraction, CTI batch summarizer
- [x] Task 3: `clause_cluster.py` — predicate-label-based clause clustering
- [x] Task 4: `template_prompt.py` — full context bundle prompt builder
- [x] Task 5: `sidecar.py` — added `template-guided` candidate language mode
- [x] Task 6: `run_mvp.py` — MVP driver (context dump + LLM call + validation)

### Remaining
- [ ] Task 7: Fix import paths, run E2E with V4 Pro, inspect candidates
- [ ] Task 8: Record results in candidate report format
- [ ] Task 9: Manual rel_ind_check on top candidates

### Blocked by
- `template_prompt.py` has `from llm_worker.lemma_schema` (wrong import path — fixed to `from lemma_schema` but needs verification)
- `run_mvp.py` sidecar subprocess may not inherit Python path correctly

---
## File Structure (Actual)

```
llm_worker/
  lemma_schema.py       ← NEW+COMPLETED: 8 lemma family definitions + validation
  transition_slice.py   ← NEW+COMPLETED: hot variable extraction + CTI summary
  clause_cluster.py     ← NEW+COMPLETED: predicate-label-based clause clustering
  template_prompt.py    ← NEW+COMPLETED: full context bundle prompt builder
  run_mvp.py            ← NEW+COMPLETED: MVP driver (context → LLM → validate → report)
  sidecar.py            ← MODIFIED: added template-guided mode
```
---

## File Structure

```
llm_worker/
  clause_cluster.py     ← NEW: group frame clauses into clusters
  transition_slice.py   ← NEW: extract relevant transitions in pseudo-code
  lemma_schema.py       ← NEW: define allowed lemma schemas + validation
  template_prompt.py    ← NEW: build prompt for template-guided generation
  lemma_gate.py         ← NEW: syntax → BMC → induction validation (offline)
  sidecar.py            ← MODIFY: add template-prompt mode
```

---

### Task 1: Lemma Schema Definition + Validation

**Goal:** Define allowed lemma types and syntax-level validation.

**Files:**
- Create: `llm_worker/lemma_schema.py`

- [ ] **Step 1: Create lemma_schema.py with schema definitions**

```python
"""Lemma schema definitions and syntax-level validation for template-guided generation."""

from dataclasses import dataclass
from typing import List, Optional

LEMMA_SCHEMAS = {
    "range": {
        "template": "{lo} <= {var} <= {hi}",
        "fields": ["var", "lo", "hi"],
        "description": "Variable bounded by constant range"
    },
    "equality": {
        "template": "{lhs} = {rhs}",
        "fields": ["lhs", "rhs"],
        "description": "Two variables or expressions are equal"
    },
    "disequality": {
        "template": "{lhs} != {rhs}",
        "fields": ["lhs", "rhs"],
        "description": "Two variables or expressions differ"
    },
    "offset": {
        "template": "{lhs} = {rhs} + {offset}",
        "fields": ["lhs", "rhs", "offset"],
        "description": "One variable equals another plus constant offset"
    },
    "bitslice": {
        "template": "{var}[{hi}:{lo}] = {value}",
        "fields": ["var", "hi", "lo", "value"],
        "description": "Bit-slice of a variable equals a constant"
    },
    "mutual_exclusion": {
        "template": "!({a} && {b})",
        "fields": ["a", "b"],
        "description": "Two conditions cannot be simultaneously true"
    },
    "mode_implication": {
        "template": "({mode} = {value}) => {constraint}",
        "fields": ["mode", "value", "constraint"],
        "description": "A mode value implies a constraint"
    },
    "guarded_implication": {
        "template": "{guard} => {consequent}",
        "fields": ["guard", "consequent"],
        "description": "A guard condition implies a consequent relation"
    },
}

FORBIDDEN_KEYWORDS = ["forall", "exists", "select", "store", "Array"]


def validate_lemma_syntax(lemma: str) -> bool:
    """Check lemma doesn't use forbidden constructs."""
    for kw in FORBIDDEN_KEYWORDS:
        if kw in lemma:
            return False
    return True


def get_schema_list_for_prompt() -> str:
    """Generate a human-readable schema list for the LLM prompt."""
    lines = []
    for name, info in LEMMA_SCHEMAS.items():
        lines.append(f"- {name}: {info['template']}  ({info['description']})")
    return "\n".join(lines)
```

- [ ] **Step 2: Test schema validation**

```bash
python3 -c "
from llm_worker.lemma_schema import validate_lemma_syntax, LEMMA_SCHEMAS, get_schema_list_for_prompt
# Valid
assert validate_lemma_syntax('(=> (= mode IDLE) (= valid 0))')
# Forbidden
assert not validate_lemma_syntax('forall x . x = 0')
assert not validate_lemma_syntax('(select mem addr)')
# Schema list
schema_text = get_schema_list_for_prompt()
assert 'mode_implication' in schema_text
print('All tests passed')
"
```

Expected: `All tests passed`

- [ ] **Step 5: Commit**

```bash
git add llm_worker/lemma_schema.py
git commit -m "feat: lemma schema definitions and syntax validation"
```

---

### Task 2: Transition Slice Extractor

**Goal:** Given a set of hot variable names, extract relevant transition equations from IC3IA's SMT and convert to pseudo-code.

**Files:**
- Create: `llm_worker/transition_slice.py`

- [ ] **Step 1: Create transition_slice.py**

```python
"""Extract transition slice pseudo-code from IC3IA SMT transition relation."""

import re
from typing import List, Dict


def extract_hot_variables(cti_literals: List[dict]) -> List[str]:
    """Extract state variable names from CTI literal varnames.
    Looks for patterns like 'stateNNN', 'inputNNN' in simplified SMT expressions.
    """
    seen = set()
    for lit in cti_literals:
        for match in re.finditer(r'\b(state\d+|input\d+)\b', lit.get("varname", "")):
            seen.add(match.group(1))
        for match in re.finditer(r'\b(state\d+|input\d+)\b', lit.get("expr", lit.get("varname", ""))):
            seen.add(match.group(1))
    return sorted(seen)


def smt_to_pseudocode(smt_text: str) -> str:
    """Convert simplified SMT transition text to pseudo-code.
    
    Input: 'next(state76) = ite((reset = #b1), #b0000000000000000, ite((en = #b1), (state76 + #b0000000000000001), state76))'
    Output: 'if (reset)  state76' = 0\nelse if (en)  state76' = state76 + 1\nelse  state76' = state76'
    """
    # Strip common prefixes
    text = smt_text.strip()
    
    # Replace wide zero_extend / bitvector constants with simpler forms
    text = re.sub(r'#b0+', '0', text)
    text = re.sub(r'#b1', '1', text)
    text = re.sub(r'zero_ext\(([^)]+)\)', r'zero_ext(\1)', text)
    
    # Handle ite chains
    # next(X) = ite(cond, true_val, false_val)
    lines = []
    remaining = text
    depth = 0
    current = ""
    
    # Simple approach: lexical tokenization
    tokens = re.split(r'(\s+|\(|\)|,)', text)
    tokens = [t for t in tokens if t.strip()]
    
    # For now, return the simplified SMT directly since full conversion
    # to pseudo-code requires proper SMT parsing which is in C++.
    # The sidecar will call simplify_cti_literal via pono for accurate conversion.
    return text


def build_transition_slice(
    transition_smt: List[str],
    hot_vars: List[str],
) -> str:
    """Build a pseudo-code transition slice for hot variables.
    
    Args:
        transition_smt: Raw SMT next-state equations from pono (one per variable)
        hot_vars: Variable names to include
    
    Returns:
        Human-readable transition slice text
    """
    lines = []
    for eq in transition_smt:
        # Extract variable name from 'next(X) = ...'
        match = re.match(r'next\((\w+)\)', eq)
        if match:
            var = match.group(1)
        else:
            continue
        
        # Include if it involves any hot variable
        include = False
        for hv in hot_vars:
            if hv in eq:
                include = True
                break
        
        if include:
            simplified = smt_to_pseudocode(eq)
            lines.append(simplified)
    
    if not lines:
        return "(transition slice: no relevant equations extracted)"
    
    return "\n".join(lines)
```

- [ ] **Step 2: Test transition extraction**

```bash
python3 -c "
from llm_worker.transition_slice import extract_hot_variables, smt_to_pseudocode

# Test hot variable extraction
cti_lits = [
    {'varname': '(state76 = #b0000000000000000)', 'value': 'true'},
    {'varname': '((state5 | ~~state5) = #b1)', 'value': 'true'},
    {'varname': '((~(input4 ^ ...) = #b1)', 'value': 'true'},
]
hot = extract_hot_variables(cti_lits)
assert 'state76' in hot
assert 'state5' in hot
assert 'input4' in hot
print(f'Hot variables: {hot}')

# Test pseudocode conversion
smt = 'next(state76) = ite((reset = #b1), #b0000000000000000, ite((en = #b1), (state76 + #b0000000000000001), state76))'
pc = smt_to_pseudocode(smt)
print(f'Pseudocode: {pc}')
print('All tests passed')
"
```

Expected: hot variables extracted, pseudocode printed

- [ ] **Step 5: Commit**

```bash
git add llm_worker/transition_slice.py
git commit -m "feat: transition slice extraction for LLM context"
```

---

### Task 3: Clause Clustering

**Goal:** Group frame clauses by shared predicate labels. Identify clusters that LLM could subsume with a broader lemma.

**Files:**
- Create: `llm_worker/clause_cluster.py`

- [ ] **Step 1: Create clause_cluster.py**

```python
"""Group IC3 frame clauses into clusters for LLM generalization."""

from typing import List, Dict, Set, Tuple
from collections import defaultdict


def cluster_clauses(
    clauses: List[List[str]],  # each clause is list of predicate label names
    min_shared: int = 2,
    max_varying: int = 10,
) -> List[Dict]:
    """Group clauses that share common predicate labels.
    
    Returns clusters sorted by potential subsume value (more clauses = better).
    """
    # Build inverted index: predicate → set of clause indices
    pred_to_clauses: Dict[str, Set[int]] = defaultdict(set)
    for i, clause in enumerate(clauses):
        for pred in clause:
            pred_to_clauses[pred].add(i)
    
    # Find clusters: clauses sharing >= min_shared predicates
    clustered = set()
    results = []
    
    for i, clause in enumerate(clauses):
        if i in clustered:
            continue
        
        # Find other clauses sharing common predicates
        common_preds = set(clause)
        cluster = {i}
        
        for j, other in enumerate(clauses):
            if j <= i or j in clustered:
                continue
            shared = common_preds & set(other)
            if len(shared) >= min_shared:
                cluster.add(j)
                common_preds &= set(other)  # refine common core
        
        if len(cluster) >= 2:
            clustered.update(cluster)
            
            # Find common vs varying predicates
            all_preds = [set(clauses[j]) for j in cluster]
            core = set.intersection(*all_preds) if all_preds else set()
            varying = set()
            for pset in all_preds:
                varying.update(pset - core)
            
            if len(varying) <= max_varying:
                results.append({
                    "clause_indices": sorted(cluster),
                    "size": len(cluster),
                    "common_predicates": sorted(core),
                    "varying_predicates": sorted(varying),
                })
    
    results.sort(key=lambda r: r["size"], reverse=True)
    return results


def format_cluster_for_prompt(cluster: Dict, pred_labels: Dict[str, str]) -> str:
    """Format a clause cluster as human-readable text for LLM prompt.
    
    Args:
        cluster: Output from cluster_clauses()
        pred_labels: Map of predicate name → readable description
    """
    lines = [f"Cluster: {cluster['size']} similar clauses"]
    lines.append("  Common core predicates:")
    for p in cluster["common_predicates"][:5]:
        desc = pred_labels.get(p, p)
        lines.append(f"    {desc}")
    lines.append("  Varying detail predicates:")
    for p in cluster["varying_predicates"][:10]:
        desc = pred_labels.get(p, p)
        lines.append(f"    {desc}")
    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 2: Test clustering**

```bash
python3 -c "
from llm_worker.clause_cluster import cluster_clauses, format_cluster_for_prompt

clauses = [
    ['p1', 'p2', 'p3', 'p5'],
    ['p1', 'p2', 'p3', 'p6'],
    ['p1', 'p2', 'p3', 'p7'],
    ['p1', 'p2', 'p4'],
    ['p8', 'p9'],
]
results = cluster_clauses(clauses, min_shared=2)
assert len(results) >= 2, f'Expected >=2 clusters, got {len(results)}'
for r in results[:2]:
    print(f'Cluster size={r[\"size\"]} common={r[\"common_predicates\"]} varying={r[\"varying_predicates\"]}')
    formatted = format_cluster_for_prompt(r, {})
    assert 'Cluster' in formatted
print('All tests passed')
"
```

Expected: 2+ clusters found, formatted output

- [ ] **Step 5: Commit**

```bash
git add llm_worker/clause_cluster.py
git commit -m "feat: clause clustering for LLM subsumption candidates"
```

---

### Task 4: Template-Guided Prompt Builder

**Goal:** Build LLM prompt with full context bundle (property + hot vars + transition + CTI batch + clause clusters + lemma memory + allowed schemas).

**Files:**
- Create: `llm_worker/template_prompt.py`

- [ ] **Step 1: Create template_prompt.py**

```python
"""Build prompts for template-guided semantic lemma generation."""

import json
from typing import List, Dict, Optional
from llm_worker.lemma_schema import get_schema_list_for_prompt


def build_template_prompt(
    context: Dict,
) -> str:
    """Build a complete prompt for the template-guided LLM call.
    
    Args:
        context: Dict with keys:
            target_property, hot_variables, transition_slice,
            cti_batch, clause_clusters, lemma_memory
    
    Returns:
        Complete prompt string
    """
    parts = []
    
    # Role
    parts.append(
        "You are assisting a hardware model checker (Pono IC3IA) with word-level "
        "predicate abstraction. Your task: generate NEW candidate lemmas that may "
        "hold for all reachable states and help compress multiple existing frame clauses."
    )
    
    # Rules
    parts.append(
        "Rules:\n"
        "- Do NOT generate a subset of a single CTI cube.\n"
        "- Do NOT merely list literals common across CTIs.\n"
        "- Generate semantic invariants over state variables.\n"
        "- Lemmas will be validated by SMT solvers; they must pass induction.\n"
        "- Use ONLY the lemma schemas listed below.\n"
        "- Return JSON only, no markdown, no explanation outside JSON."
    )
    
    # Target property
    parts.append(f"Target property (to prove unreachable):\n{context.get('target_property', '(unknown)')}")
    
    # Hot variables
    parts.append(f"Relevant state variables:\n{context.get('hot_variables', '(none)')}")
    
    # Transition slice
    parts.append(f"Transition slice (pseudo-code of relevant next-state logic):\n{context.get('transition_slice', '(unavailable)')}")
    
    # CTI batch
    parts.append(f"Current CTI batch (counterexamples from the same IC3 frame):\n{context.get('cti_batch', '(none)')}")
    
    # Clause clusters
    clusters_text = context.get('clause_clusters', '')
    if clusters_text:
        parts.append(f"Frame clause clusters (groups of similar clauses that could be subsumed):\n{clusters_text}")
    
    # Lemma memory
    accepted = context.get('lemma_memory', {}).get('accepted', [])
    rejected = context.get('lemma_memory', {}).get('rejected', [])
    if accepted or rejected:
        parts.append("Previously accepted lemmas:")
        for lem in accepted[:5]:
            parts.append(f"  ✓ {lem}")
        parts.append("Previously rejected lemmas (do NOT repeat):")
        for lem in rejected[:5]:
            parts.append(f"  ✗ {lem}")
    
    # Allowed schemas
    parts.append(f"Allowed lemma schemas:\n{get_schema_list_for_prompt()}")
    
    # Output format
    parts.append(
        "Return a JSON object with a 'candidates' array. Each candidate:\n"
        "{\n"
        '  "lemma": "(=> (= mode IDLE) (= valid 0))",\n'
        '  "lemma_type": "mode_implication",\n'
        '  "intuition": "brief reasoning",\n'
        '  "variables_used": ["mode", "valid"],\n'
        '  "expected_subsumed_cluster": "cluster_0 or none",\n'
        '  "risk_level": "low|medium|high"\n'
        "}\n\n"
        'Return JSON only: {"candidates": [...]}'
    )
    
    return "\n\n".join(parts)
```

- [ ] **Step 2: Test prompt generation**

```bash
python3 -c "
from llm_worker.template_prompt import build_template_prompt
import json

ctx = {
    'target_property': 'bad = (mode == BAD && valid == 1)',
    'hot_variables': 'state76 (counter), state5 (mode FSM), input4 (request)',
    'transition_slice': 'if (reset) state76\\' = 0\\nelse if (en) state76\\' = state76 + 1',
    'cti_batch': 'CTI #1: state76=0, state5=IDLE, input4=1\\nCTI #2: state76=5, state5=IDLE, input4=1',
    'clause_clusters': 'Cluster 1: 5 clauses share mode=IDLE, input4=1. Varying: cnt>=0..5',
    'lemma_memory': {'accepted': [], 'rejected': ['cnt >= 0']},
}
prompt = build_template_prompt(ctx)
assert 'ILLE' in prompt or 'mode' in prompt
assert 'lemma_schema' not in prompt.lower()  # schemas are listed
assert 'candidates' in prompt
print(f'Prompt length: {len(prompt)} chars')
print(prompt[:500])
print('Test passed')
"
```

Expected: prompt generated with all sections, ~2-3K chars

- [ ] **Step 5: Commit**

```bash
git add llm_worker/template_prompt.py
git commit -m "feat: template-guided prompt builder with context bundle"
```

---

### Task 5: Sidecar Integration — Add Template-Prompt Mode

**Goal:** Integrate new prompt flow into sidecar.py.

**Files:**
- Modify: `llm_worker/sidecar.py`

- [ ] **Step 1: Add candidate_language option "template-guided"**

In `process_request()`, add a new branch before the existing ones:

```python
def process_request(
    client: DeepSeekClient,
    ctx: CTIContext,
    candidate_language: str,
    prompt_dir: str,
    default_model: str = "",
) -> LLMCandidate:
    """Process a CTI context through the LLM."""
    # Template-guided mode: expects context bundle in request
    if candidate_language == "template-guided":
        from llm_worker.template_prompt import build_template_prompt
        prompt = build_template_prompt(ctx)
        response_text, token_count, latency_ms = client.call(prompt, model_name=default_model or None)
        try:
            result = json.loads(response_text)
            candidates = result.get("candidates", [])
            # Return first candidate; multi-candidate support TBD
            candidate = candidates[0] if candidates else {}
            candidate.setdefault("type", "template_lemma")
        except (json.JSONDecodeError, KeyError, IndexError):
            candidate = {
                "type": "template_lemma",
                "lemma": "",
                "lemma_type": "unknown",
                "rationale": "LLM response was not valid JSON",
            }
        return candidate, token_count, latency_ms

    # Existing cube-subset / qf-smt paths...
    if candidate_language == "cube-subset":
        ...
```

Also update `argparse` choices to include `"template-guided"`:

```python
parser.add_argument(
    "--candidate-language",
    default="cube-subset",
    choices=["cube-subset", "qf-smt", "predicate-relation", "template-guided"],
    help="LLM output restriction level",
)
```

- [ ] **Step 2: Test sidecar with template-guided mode**

```bash
export DEEPSEEK_API_KEY="sk-..."
python3 -c "
import json, os, tempfile
# Write a context bundle
ctx = {
    'target_property': 'bad = (mode == BAD && valid == 1)',
    'hot_variables': 'state76, state5, input4',
    'transition_slice': '(no transition available)',
    'cti_batch': 'CTI #1: state76=0, state5=IDLE, input4=1',
    'clause_clusters': '',
    'lemma_memory': '{}',
    'candidate_language': 'template-guided',
}
td = tempfile.mkdtemp()
req = os.path.join(td, 'req.jsonl')
resp = os.path.join(td, 'resp.jsonl')
with open(req, 'w') as f:
    json.dump(ctx, f); f.write('\n')

# Run sidecar
import subprocess, sys
r = subprocess.run([
    sys.executable, 'llm_worker/sidecar.py',
    '--req-path', req, '--resp-path', resp,
    '--candidate-language', 'template-guided',
    '--max-requests', '1', '--model', 'deepseek-v4-pro',
], capture_output=True, text=True, timeout=300)
print(r.stdout[-500:])
if os.path.exists(resp):
    with open(resp) as f:
        d = json.loads(f.readline())
        print(f'Type: {d.get(\"type\")}, Lemma: {d.get(\"lemma\", \"\")[:100]}')
"
```

Expected: sidecar runs, response written with `type: template_lemma`

- [ ] **Step 3: Commit**

```bash
git add llm_worker/sidecar.py
git commit -m "feat: add template-guided candidate language to sidecar"
```

---

### Task 6: Context Dumper — Extract Bundle from IC3IA Run

**Goal:** Run pono IC3IA on a benchmark, capture frame clauses and CTIs, dump context bundle to files.

**Files:**
- Create: `llm_worker/context_dumper.py`

- [ ] **Step 1: Create context_dumper.py**

```python
#!/usr/bin/env python3
"""Dump LLM context bundle from a pono IC3IA run.

Usage:
  # Run pono with offline dump mode, then extract context
  build/pono -e ic3ia --llm-gen-mode offline-dump foo.btor2
  python3 llm_worker/context_dumper.py extract --replay-dir llm_replay/default

  # Manually build context from extracted data
  python3 llm_worker/context_dumper.py build-context --replay-dir llm_replay/default --output /tmp/context.json
"""

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List

from llm_worker.transition_slice import extract_hot_variables


def extract_frame_clauses(stderr_log: str) -> List[List[str]]:
    """Extract frame clause predicate labels from pono verbose output.
    Looks for patterns like 'constrained frame N with ... pred_0 pred_1 ...'
    """
    clauses = []
    for line in stderr_log.splitlines():
        # IC3IA predicate labels appear as distinct symbols
        preds = re.findall(r'\b(pred_\w+)\b', line)
        if preds and len(preds) >= 2:
            clauses.append(preds)
    return clauses


def extract_cti_literals(cti_dir: Path) -> List[Dict]:
    """Read CTI contexts from offline dump directory."""
    literals = []
    cti_file = cti_dir / "cti_contexts.jsonl"
    if cti_file.exists():
        with open(cti_file) as f:
            for line in f:
                data = json.loads(line.strip())
                literals.append(data)
    return literals


def extract_transition(ts_file: Path) -> List[str]:
    """Extract SMT transition equations from transition system dump."""
    equations = []
    if ts_file.exists():
        with open(ts_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith("next("):
                    equations.append(line)
    return equations


def build_context_bundle(
    replay_dir: Path,
) -> Dict:
    """Build complete context bundle for LLM."""
    cti_dir = replay_dir.parent if replay_dir.name == "default" else replay_dir
    
    # Get CTI literals from dump
    ctii = cti_dir / "cti_contexts.jsonl"
    ctis = []
    if ctii.exists():
        with open(ctii) as f:
            for line in f:
                ctis.append(json.loads(line.strip()))
    
    # Get hot variables from first batch of CTIs
    all_literals = []
    for cti in ctis[:15]:
        all_literals.extend(cti.get("literals", []))
    hot_vars = extract_hot_variables(all_literals)[:20]
    
    # Build CTI batch summary
    cti_lines = []
    for i, cti in enumerate(ctis[:15], 1):
        lit_strs = []
        for lit in cti.get("literals", [])[:10]:
            lit_strs.append(f"    {lit.get('varname', '?')[:100]} = {lit.get('value', '?')}")
        cti_lines.append(f"CTI #{i} (frame={cti.get('frame_idx','?')}, {len(cti.get('literals',[]))} literals):\n" + "\n".join(lit_strs))
    
    return {
        "target_property": "(extract from bad property in static context)",
        "hot_variables": ", ".join(hot_vars) if hot_vars else "(none extracted)",
        "transition_slice": "(run pono with --llm-req-path to capture transition)",
        "cti_batch": "\n\n".join(cti_lines) if cti_lines else "(none)",
        "clause_clusters": "(run with --llm-gen-mode offline-dump to capture clauses)",
        "lemma_memory": json.dumps({"accepted": [], "rejected": []}),
        "candidate_language": "template-guided",
        "model": "deepseek-v4-pro",
    }


def main():
    parser = argparse.ArgumentParser(description="LLM context bundle dumper")
    sub = parser.add_subparsers(dest="cmd")
    
    build = sub.add_parser("build-context")
    build.add_argument("--replay-dir", default="llm_replay/default")
    build.add_argument("--output", default="/tmp/llm_context.json")
    
    args = parser.parse_args()
    
    if args.cmd == "build-context":
        ctx = build_context_bundle(Path(args.replay_dir))
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(ctx, indent=2))
        print(f"Context written to {output}")
        print(f"  Hot variables: {ctx['hot_variables']}")
        print(f"  CTI count: {len(ctx['cti_batch'].split('CTI #'))-1}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test**

```bash
python3 llm_worker/context_dumper.py build-context --output /tmp/test_context.json 2>&1
cat /tmp/test_context.json | python3 -m json.tool 2>/dev/null | head -10
```

- [ ] **Step 5: Commit**

```bash
git add llm_worker/context_dumper.py
git commit -m "feat: context dumper for LLM bundle extraction"
```

---

### Task 7: End-to-End MVP Manual Test

**Goal:** Run the full MVP flow manually and record results.

**Files:**
- None (execution-only task)

- [ ] **Step 1: Generate context from benchmark**

```bash
# Pick the analog_estimation_convergence benchmark
BENCH="$HOME/hwmcc_benchmarks/2024/btor2/2019/mann/safe/analog_estimation_convergence.btor2"

# Run pono with CTI capture to get CTI contexts
timeout 60 ./build/pono -e ic3ia -k 100000 \
  --llm-gen-mode async-cti --llm-candidate-language cube-subset \
  --llm-model deepseek-v4-pro \
  --llm-req-path /tmp/mvp_context/req.jsonl \
  --llm-resp-path /tmp/mvp_context/dummy.jsonl \
  "$BENCH" >/dev/null 2>&1 &
sleep 30; kill %1 2>/dev/null
echo "Requests: $(wc -l < /tmp/mvp_context/req.jsonl)"
```

- [ ] **Step 2: Build manual context bundle**

```python
import json, subprocess

# Read first batch request
with open('/tmp/mvp_context/req.jsonl') as f:
    first = json.loads(f.readline())

# Build context manually
ctx = {
    "target_property": first.get("property", "(unknown)")[:500],
    "hot_variables": "(extract from CTI batch below)",
    "transition_slice": "(transition not yet extracted — manual)",
    "cti_batch": json.dumps(first.get("cti_contexts", [first]), indent=2)[:5000],
    "clause_clusters": "(clustering not yet implemented — manual)",
    "lemma_memory": {},
    "candidate_language": "template-guided",
    "model": "deepseek-v4-pro",
    "frame_idx": first.get("frame_idx", 1),
}

with open('/tmp/mvp_context/req_one.jsonl', 'w') as f:
    json.dump(ctx, f)
    f.write('\n')

print(f"Context: {len(json.dumps(ctx))} bytes")
```

- [ ] **Step 3: Run LLM with template-guided mode**

```bash
export DEEPSEEK_API_KEY="sk-..."

timeout 600 python3 -u llm_worker/sidecar.py \
  --req-path /tmp/mvp_context/req_one.jsonl \
  --resp-path /tmp/mvp_context/resp.jsonl \
  --log-path /tmp/mvp_context/log.jsonl \
  --candidate-language template-guided \
  --max-requests 1 --poll-interval 0.5 --model deepseek-v4-pro
```

- [ ] **Step 4: Inspect LLM output**

```bash
python3 -c "
import json
with open('/tmp/mvp_context/resp.jsonl') as f:
    d = json.loads(f.readline())
print(f'Type: {d.get(\"type\")}')
print(f'Lemma: {d.get(\"lemma\", \"\")}')
print(f'Lemma type: {d.get(\"lemma_type\", \"\")}')
print(f'Intuition: {d.get(\"intuition\", \"\")}')
"
```

- [ ] **Step 5: Record results**

Record: candidate count, valid JSON, lemma generated, lemma type, whether it matches the schema.

- [ ] **Step 6: Commit results as notes**

```bash
echo "# MVP E2E Test - $(date)" >> docs/superpowers/plans/mvp_results.md
cat >> docs/superpowers/plans/mvp_results.md << 'EOF'
## Results
- LLM model: V4 Pro
- Benchmark: analog_estimation_convergence.btor2
- Context: single CTI batch, target property, schema list
- See test output above
EOF
git add docs/superpowers/plans/mvp_results.md
git commit -m "docs: MVP test results placeholder"
```
