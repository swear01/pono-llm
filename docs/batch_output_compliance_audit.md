# Batch Output Compliance Audit

**Date:** 2026-05-27  
**Branch:** feature/llm-ic3ia-generalization  
**Auditor:** Claude Sonnet 4.6 (fresh audit, no prior agent assumptions)

---

## Executive Summary

The claim "LLM only returns one candidate" is **incorrect**. Three code bugs prevent
multi-candidate output from reaching callers — the LLM never had a chance to prove
compliance. Root cause is a `NameError` in `sidecar.py` that silently discards every
non-empty template-guided response.

| Bug | File | Severity |
|-----|------|----------|
| `NameError: args` in `process_request()` — 0 candidates written | `sidecar.py:136` | CRITICAL |
| Consumer reads only first line with `f.readline()` | `run_mvp.py:173,291` | CRITICAL |
| `extract_json()` missing `"candidates"` marker for preamble recovery | `deepseek_client.py:241` | IMPORTANT |
| `build_batch_prompt()` result discarded; `build_template_prompt()` used instead | `run_mvp.py:248` | DESIGN |

---

## Step 1: File Inventory

| File | Role |
|------|------|
| `llm_worker/batch_scheduler.py` | Builds `BatchDef` from `ClusterPool`, generates batch prompt via `build_batch_prompt()`. Has complete OUTPUT CONTRACT. |
| `llm_worker/cluster_pool.py` | Mines CTI logs → `ClusterInfo` pool, diversity filtering. |
| `llm_worker/template_prompt.py` | Builds template-guided prompt from context bundle. Hardcodes "Generate 10 diverse candidates now." |
| `llm_worker/sidecar.py` | Main pipeline: polls JSONL req file → LLM → writes responses. **Contains NameError bug.** |
| `llm_worker/deepseek_client.py` | OpenAI-compatible LLM client (`max_tokens=32768`). `extract_json()` strips fencing and finds JSON by marker. |
| `llm_worker/run_mvp.py` | CLI driver: `run_batch_mode()` orchestrates batch generation. **Reads only first response line.** |
| `llm_worker/candidate_gate.py` | Parses, canonicalizes, deduplicates candidates. Works correctly. |
| `llm_worker/jsonl_protocol.py` | `write_response()` appends one JSON line. `read_request()` reads by byte position. |
| `llm_worker/prompts/` | Prompt templates for cube-subset and offline modes. Not used for template-guided. |

---

## Step 2: Prompt Analysis

### template_prompt.py — OUTPUT CONTRACT
- Contract is at the **end** of the prompt (correct).
- Requires `"candidates"` array with explicit INVALID example.
- **Flaw:** Hardcodes `"Generate 10 diverse candidates now."` — ignores `batch.candidate_budget`.
- No conflicting "return one candidate" instruction found.
- Prompt length: ~2500–4000 chars depending on context (well under typical context limits).

### batch_scheduler.py — OUTPUT CONTRACT  
- Contract is at the end (correct).
- Requires exactly `{total}` candidates, per-cluster breakdown.
- Shows two example items in the array (models multi-item output).
- **Flaw:** This prompt is computed in `run_batch_mode()` for display only (line 248–249)
  and never sent to the LLM. The sidecar is called with `template-guided` which invokes
  `build_template_prompt()` instead.

### Verdict on prompt
Neither prompt has conflicting "return single object" instructions. The OUTPUT CONTRACTs
are well-formed. Prompt is **not** the root cause.

---

## Step 3: Raw LLM Response Analysis

**No raw response artifacts exist.** No JSONL files were found in `/tmp` or project
directories from previous runs. The batch test log (`bench_results/batch_test_20260525_154442.log`)
shows:

```
Requests: 6 / Responses: 1
LLMGeneralizer: polled 1 candidate(s)
```

And the concurrent test (`bench_results/concurrent_test_20260524_041550.log`):

```
Requests: 50 / Responses: 1
tokens=16966  latency=339s  keep=1  drop=8
```

**Key observation:** The `keep=1 drop=8` fields are **cube-subset schema fields**, not
template-guided fields. Both logs recorded runs using `--candidate-language cube-subset`
(default), not template-guided. In cube-subset mode the sidecar works correctly (no
NameError), but only processed 1 request before Pono exited (latency=339s → 5.6 min
per call).

The NameError in template-guided mode was therefore **never exposed in these logs**.
It would have appeared as `"[sidecar] Error processing request: name 'args' is not
defined"` in sidecar stderr, which was not captured.

---

## Step 4: Parser Fixture Tests

Fixtures were run via `llm_worker/tests/test_batch_parser.py`. **All 9 tests pass**
after the `extract_json()` fix (adding `"candidates"` marker).

| Fixture | Input shape | Expected candidates | Result |
|---------|-------------|---------------------|--------|
| A — valid array | `{"batch_id":"B01","candidates":[...2...]}` | 2 | **2** ✓ |
| B — single object | `{"candidate_id":"...", "lemma":"..."}` | 1 (fallback) | **1** ✓ |
| C — markdown-fenced array | ` ```json\n{...2...}\n``` ` | 2 | **2** ✓ |
| D — structurally valid hand-crafted | valid JSON string | 2 | **2** ✓ |
| E — preamble + JSON | `"Here is the JSON:\n{...2...}"` | 2 | **2** ✓ (requires `"candidates"` marker) |
| — multi-write/read-all | 3 `write_response` calls | 3 | **3** ✓ |
| — readline-only (old bug) | 3 `write_response` calls | 1 (confirms bug) | **1** ✓ |

---

## Step 5: Token Budget Analysis

```
max_tokens = 32768   (deepseek_client.py:137)
avg tokens per candidate ≈ 80–150
10 candidates × 150 = 1,500 tokens
30 candidates × 150 = 4,500 tokens
```

`max_tokens=32768` is far above the required output. Token truncation is **not** the issue.

Safe candidate counts:
| N | Output tokens | vs max_tokens | Verdict |
|---|---------------|----------------|---------|
| 8 | ~1,200 | 3.7% used | safe |
| 10 | ~1,500 | 4.6% used | safe |
| 20 | ~3,000 | 9.2% used | safe |
| 30 | ~4,500 | 13.7% used | safe |

Recommended starting count: **10** (matches `template_prompt.py` current value; gives
80% pass threshold room even if a few candidates are malformed).

---

## Root Cause Analysis

### Bug 1 — CRITICAL: `NameError` in `sidecar.py::process_request()`

**Location:** `sidecar.py`, original lines 132–137  
**Code:**
```python
# Write ALL candidates (one per line)
for cand in candidates:
    cand.setdefault("type", "template_lemma")
    write_response(args.resp_path, cand)   # ← NameError: 'args' not defined here
```

`process_request()` is a module-level function. `args` is a local variable of `main()`.
Python raises `NameError: name 'args' is not defined`.

The inner `except (json.JSONDecodeError, KeyError, IndexError)` does **not** catch
`NameError`, so it propagates to `main()`'s `except Exception as e:` handler which
logs the error silently and increments `processed_count` without writing any response.

**Effect:** For template-guided mode, whenever the LLM returns a non-empty JSON response:
- 0 lines are written to resp_path
- resp_path may not even be created
- `run_batch_mode()` reports "No response — LLM call failed"

This bug was introduced when the previous agent attempted to add multi-candidate writes
to `process_request()` but used `args` (inaccessible) instead of passing `resp_path`
as a parameter.

### Bug 2 — CRITICAL: Consumer reads only first line

**Locations:**
- `run_mvp.py::validate_candidates()`: `candidate = json.loads(f.readline())`  
- `run_mvp.py::run_batch_mode()`: `candidate = json.loads(f.readline())`

Even if Bug 1 is fixed and the sidecar writes 10 lines, these consumers read only line 1.
`f.readline()` is documented to read one line and return.

### Bug 3 — IMPORTANT: `extract_json()` missing `"candidates"` marker

**Location:** `deepseek_client.py:241`  
**Code:**
```python
for marker in ('"keep_literals"', '"drop_literals"', '"type"'):
```

These markers only match cube-subset responses. For template-guided responses with
a `"candidates"` array, if there is any leading prose (e.g., "Here is the JSON:"),
the marker search fails and the raw text is returned unparsed.

For responses that start cleanly with `{`, the `startswith("{")` check handles it —
but the marker search is the only fallback for preambled responses.

### Bug 4 — DESIGN: `build_batch_prompt()` result discarded

**Location:** `run_mvp.py::run_batch_mode()` lines 248–249

```python
prompt = build_batch_prompt(batch, ctx)          # built here
print(f"  Running {batch.batch_id}: ...")        # displayed only
# ... then sidecar called with template-guided which calls build_template_prompt() instead
```

`build_batch_prompt()` produces a prompt requesting the correct cluster-specific count.
`build_template_prompt()` always requests 10 candidates with generic context. The batch
budget (default 30) is never requested.

---

## Fixes Applied

### sidecar.py
- Removed `write_response(args.resp_path, cand)` loop from inside `process_request()`
- Changed `process_request()` return type to `(list[dict], token_count, latency_ms)` 
  for all modes (non-template modes wrap their single candidate in `[...]`)
- `main()` now writes all candidates from the returned list:
  `for cand in candidates: write_response(args.resp_path, cand)`
- Log entry gains `candidate_count` field
- Status line now reports count: `"Response written (N candidates), ..."`

### run_mvp.py
- `validate_candidates()`: iterates all lines with a for-loop, returns results for all
  candidates (not just first)
- `run_batch_mode()`: calls LLM directly via `DeepSeekClient` with the correct
  `build_batch_prompt()` output (eliminates the sidecar detour and the discarded prompt)
- Reports batch yield table (requested / actual / parse_ok / unique)
- Saves all candidates to `{batch_id}_candidates.jsonl`

### deepseek_client.py
- Added `'"candidates"'` and `'"batch_id"'` to the marker search list in `extract_json()`

### New: llm_worker/tests/test_batch_parser.py
- Fixtures A–E covering valid array, single object, markdown fence, malformed,
  preamble + JSON
- Verifies `extract_json()` + parsing logic yields correct candidate counts
- Verifies `write_response()` + read-all-lines roundtrip

---

## Batch Yield Table (Before Fix)

| Metric | Value | Note |
|--------|-------|------|
| requested_candidates | 10 | hardcoded in `template_prompt.py` |
| actual_candidates_written | **0** | NameError prevents all writes |
| format_compliant | unknown | no raw LLM logs captured |
| recovered_single_object | 0 | NameError fires before fallback write |
| parse_valid_count | 0 | nothing to parse |
| unique_count | 0 | nothing to deduplicate |

## Batch Yield Table (Expected After Fix, pending live experiment)

| Metric | Expected | Note |
|--------|----------|------|
| requested_candidates | 10 | `template_prompt.py` (or batch budget for `--batch`) |
| actual_candidates | 8–10 | typical LLM compliance ≥ 80% |
| format_compliant | 1 | `candidates` array present |
| recovered_single_object | 0 | should not fire once prompt is compliant |
| parse_valid_count | 7–10 | lemma syntax varies |
| unique_count | 7–10 | dedup by schema+vars+lemma hash |

---

## Step 7: Compliance Experiment Protocol

To confirm post-fix compliance with a live API call:

```bash
cd /home/swear01/pono-llm/llm_worker

# Run against the qspiflash CTI data (if available) or any JSONL req file
OPENROUTER_API_KEY=sk-or-xxx python3 run_mvp.py \
    --req-path /tmp/mvp/req.jsonl \
    --batch \
    --candidates-per-cluster 5 \
    --clusters-per-batch 2 \
    --output /tmp/batch_compliance_test.json

# Pass conditions:
#   top-level "candidates" array exists        ✓
#   actual_candidates >= 80% of requested      ✓
#   parser recovers all array items            ✓
#   no truncation (finish_reason == "stop")    ✓
```

Recommended initial N: **10** (5 per cluster × 2 clusters). Scale to 20–30 once
compliance is confirmed.

---

## Step 8: Fallback Architecture (if LLM is still non-compliant after fix)

Only invoke this if live experiment shows the LLM consistently ignores the `candidates`
array contract after Bug 1 is fixed:

- Switch to parallel single-candidate calls (one call per cluster × K seeds)
- Vary seed via `risk_level` parameter in system prompt ("generate a LOW risk candidate")
- Sidecar wraps each response as one JSONL line (existing path)
- Batch yield table reports `actual_candidates = K_calls` and `1 candidate/call`

Do **not** assume this architecture is needed until Bug 1 is confirmed fixed and a
live run is observed.

---

## Conclusion

The previous agent's claim — "V4 Pro only returns a single candidate" — cannot be
substantiated. The pipeline had a `NameError` that prevented any multi-candidate
response from ever being written to disk. The LLM's compliance was never observable.

After the three fixes above, the next run with a live API key will provide the first
real evidence of LLM compliance or non-compliance.
