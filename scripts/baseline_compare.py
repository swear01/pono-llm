"""
LLM linear-predicate injection vs baseline (NO LLM) on the same corpus.

baseline (no LLM):  try_fast_engines (ind + interp, parallel 10s) → on miss,
                    plain `pono -e ic3ia` (no predicates) up to `timeout`.
LLM-linear:         LLM candidates → linear predicate injection
                    (predicate_workflow.workflow, mode="linear", rounds=3).

Prints baseline vs LLM verdict per circuit and marks LLM-only / baseline-only,
to quantify the incremental value of LLM predicate injection.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'llm_worker'))
import predicate_workflow as W
from invariant_arith import try_fast_engines


def baseline(path, timeout=70):
    """No-LLM baseline: portfolio fast engines, then plain ic3ia."""
    try:
        fe = try_fast_engines(path, k=50, timeout_s=10)
    except Exception:
        fe = None
    if fe:
        return f"solved/{fe}", 10.0
    return W.run_pono(['-e', 'ic3ia', path], timeout)


def _solved(v):
    return v == 'unsat' or str(v).startswith('solved')


if __name__ == "__main__":
    W.load_env()
    client = W.create_llm_client()
    paths = W.collect_circuits()
    print(f"{'Circuit':<30} {'baseline(no-LLM)':<20} {'LLM-linear':<16} note")
    print("-" * 78)
    b_n = l_n = llm_only = base_only = 0
    for path in paths:
        name = os.path.basename(path)
        try:
            if not W.detect_software_origin(W.parse_btor2(path)):
                continue
        except Exception:
            continue
        bv, bt = baseline(path)
        r = W.workflow(path, client, mode="linear", rounds=3)
        lv = r["verdict"]
        b_ok, l_ok = _solved(bv), _solved(lv)
        b_n += b_ok; l_n += l_ok
        note = ""
        if l_ok and not b_ok:
            note = "← LLM only"; llm_only += 1
        elif b_ok and not l_ok:
            note = "← baseline only"; base_only += 1
        print(f"{name:<30} {bv+' '+str(round(bt,1))+'s':<20} "
              f"{lv+' '+str(round(r['time'],1))+'s':<16} {note}", flush=True)
    print("-" * 78)
    print(f"baseline(no-LLM): {b_n}   LLM-linear: {l_n}   "
          f"LLM-only: {llm_only}   baseline-only: {base_only}")
