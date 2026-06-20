"""
Sound predicate-injection workflow.

Unlike the (unsound) constraint pipeline, this injects LLM-generated invariant
candidates as IC3IA abstraction PREDICATES (over-approximation), so:
  - the verdict is sound regardless of whether the hints are true
  - NO verify step is needed (a false predicate is harmless, just unhelpful)

Flow per circuit:
  LLM candidates -> ast refs (symbol -> state<lineno>) -> predicate JSON
  -> pono -e ic3ia --initial-predicates -> verdict + time

Because predicate injection does not change the model, an `unsat` verdict is a
sound proof of the ORIGINAL circuit (no cert_check needed).
"""
import sys, os, json, time, subprocess, tempfile, glob

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'llm_worker'))
from btor2_reader import parse_btor2
from invariant_arith import build_software_prompt, detect_software_origin
from invariant_prompt import INVARIANT_SYSTEM_PROMPT, parse_invariant_response
from llm_client import create_llm_client
from env_config import load_env

PONO = "/home/swear01/pono-llm/build/pono"
ROOT = "/home/swear01/hwmcc_benchmarks"


def ast_to_state_refs(ast, sym2ref):
    """Recursively rewrite ref nodes (symbol or state<lineno>) to state<lineno>."""
    a = dict(ast)
    if a.get("form") == "ref":
        r = a.get("ref", "")
        a["ref"] = sym2ref.get(r, r)
    if "args" in a and isinstance(a["args"], list):
        a["args"] = [ast_to_state_refs(x, sym2ref) for x in a["args"]]
    return a


def run_pono(args, t):
    t0 = time.time()
    try:
        r = subprocess.run([PONO] + args, capture_output=True, timeout=t)
        o = (r.stdout + r.stderr).decode(errors='replace').lower()
        el = time.time() - t0
        if '\nunsat' in '\n' + o or o.startswith('unsat'):
            return 'unsat', el
        if '\nsat' in '\n' + o or o.startswith('sat'):
            return 'sat', el
        return 'unknown', el
    except subprocess.TimeoutExpired:
        return 'timeout', t


def workflow(path, client, timeout=70):
    info = parse_btor2(path)
    if not detect_software_origin(info):
        return {"verdict": "not-software", "n_cand": 0, "time": 0}
    sym2ref = {}
    for sv in info.states:
        sym2ref[sv.ref] = sv.ref
        if sv.symbol:
            sym2ref[sv.symbol] = sv.ref
    req = {"benchmark": os.path.basename(path), "btor2_path": path}
    prompt = build_software_prompt(req, info)
    try:
        text, _, _ = client.call(prompt, system_prompt=INVARIANT_SYSTEM_PROMPT,
                                 reasoning_effort="none", max_tokens=2048)
    except Exception as e:
        return {"verdict": f"llm-fail:{type(e).__name__}", "n_cand": 0, "time": 0}
    cands = parse_invariant_response(text)
    asts = [c.get("predicate_ast") for c in cands if c.get("predicate_ast")]
    lines = []
    for ast in asts:
        try:
            lines.append(json.dumps({"predicate_ast": ast_to_state_refs(ast, sym2ref)}))
        except Exception:
            pass
    if not lines:
        return {"verdict": "no-candidates", "n_cand": 0, "time": 0}
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        f.write("\n".join(lines)); jf = f.name
    try:
        v, el = run_pono(['-e', 'ic3ia', '--initial-predicates', jf, path], timeout)
        return {"verdict": v, "n_cand": len(lines), "time": el}
    finally:
        os.unlink(jf)


def find_circuit(name):
    hits = glob.glob(os.path.join(ROOT, "**", name), recursive=True)
    hits = [h for h in hits if h.endswith((".btor", ".btor2"))]
    return sorted(hits, key=len)[0] if hits else None


CIRCUITS = [
    "fib_23.btor2", "fib_30.btor2", "fib_37.btor2",
    "fib_05.btor2", "paper_v3.btor2",
]

if __name__ == "__main__":
    dry = "--dry" in sys.argv
    if not dry:
        load_env()
    client = None if dry else create_llm_client()
    print(f"{'Circuit':<18} {'verdict':<10} {'#cand':<6} {'time':<8}")
    print("-" * 46)
    for name in CIRCUITS:
        path = find_circuit(name)
        if not path:
            print(f"{name:<18} NOT_FOUND")
            continue
        if dry:
            ok = "sw" if detect_software_origin(parse_btor2(path)) else "non-sw"
            print(f"{name:<18} {ok}  {os.path.relpath(path, ROOT)[:40]}")
            continue
        r = workflow(path, client)
        print(f"{name:<18} {r['verdict']:<10} {r['n_cand']:<6} {r['time']:.1f}s", flush=True)
