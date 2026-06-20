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


def _ast_has_var_mul(a):
    """True if AST has mul(non-const, non-const) — genuinely quadratic (expensive bvmul).
    mul(const, var) is a linear coefficient (cheap) and does NOT count."""
    if isinstance(a, dict):
        if a.get("form") == "mul":
            non_const = [x for x in a.get("args", []) if x.get("form") != "const"]
            if len(non_const) >= 2:
                return True
        return any(_ast_has_var_mul(x) for x in a.get("args", []))
    return False


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


def workflow(path, client, timeout=70, effort="none", rounds=1, cap=20, mode="full"):
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
    # Accumulate candidates over `rounds` LLM calls, dedup by canonical JSON.
    # Predicate injection is sound, so an extra/false candidate is harmless —
    # keep all of them (up to `cap`) to beat LLM nondeterminism.
    seen = {}  # key → (json_line, is_linear)
    for _ in range(rounds):
        try:
            text, _, _ = client.call(prompt, system_prompt=INVARIANT_SYSTEM_PROMPT,
                                     reasoning_effort=effort, max_tokens=4096)
        except Exception:
            continue
        for c in parse_invariant_response(text):
            ast = c.get("predicate_ast")
            if not ast:
                continue
            try:
                conv = ast_to_state_refs(ast, sym2ref)
                key = json.dumps(conv, sort_keys=True)
                if key not in seen:
                    seen[key] = (json.dumps({"predicate_ast": conv}),
                                 not _ast_has_var_mul(conv))
            except Exception:
                pass
    vals = list(seen.values())
    all_lines = [ln for ln, _ in vals][:cap]
    linear_lines = [ln for ln, is_lin in vals if is_lin][:cap]
    if not all_lines:
        return {"verdict": "no-candidates", "n_cand": 0, "time": 0}

    def _run(lines, t):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            f.write("\n".join(lines)); jf = f.name
        try:
            return run_pono(['-e', 'ic3ia', '--initial-predicates', jf, path], t)
        finally:
            os.unlink(jf)

    if mode == "linear":
        if not linear_lines:
            return {"verdict": "no-candidates", "n_cand": 0, "time": 0}
        v, el = _run(linear_lines, timeout)
        return {"verdict": v, "n_cand": len(linear_lines), "time": el}
    if mode == "two-tier":
        # tier 1: linear-only (cheap, no var*var bvmul); fall back to full on miss
        total = 0.0
        if linear_lines:
            v, el = _run(linear_lines, min(20, timeout)); total += el
            if v == "unsat":
                return {"verdict": v, "n_cand": len(linear_lines), "time": round(total, 1), "tier": 1}
        v, el = _run(all_lines, timeout); total += el
        return {"verdict": v, "n_cand": len(all_lines), "time": round(total, 1), "tier": 2}
    v, el = _run(all_lines, timeout)
    return {"verdict": v, "n_cand": len(all_lines), "time": el}


def find_circuit(name):
    hits = glob.glob(os.path.join(ROOT, "**", name), recursive=True)
    hits = [h for h in hits if h.endswith((".btor", ".btor2"))]
    return sorted(hits, key=len)[0] if hits else None


def collect_circuits():
    pats = ["**/arithmetic_circuits/**/*.btor2",
            "**/nla-digbench*/**/*.btor2",
            "**/crafted/paper_v3/*.btor2"]
    out = []
    for p in pats:
        out += glob.glob(os.path.join(ROOT, p), recursive=True)
    return sorted(set(out))


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    rounds = 1
    mode = "full"
    if "--linear" in sys.argv:
        mode = "linear"
    if "--two-tier" in sys.argv:
        mode = "two-tier"
    for a in sys.argv:
        if a.startswith("--rounds="):
            rounds = int(a.split("=", 1)[1])
    if not dry:
        load_env()
    client = None if dry else create_llm_client()
    paths = collect_circuits()
    print(f"{'Circuit':<30} {'verdict':<10} {'#cand':<6} {'time':<8}")
    print("-" * 58)
    n_sound = n_total = 0
    for path in paths:
        name = os.path.basename(path)
        if dry:
            ok = "sw" if detect_software_origin(parse_btor2(path)) else "non-sw"
            print(f"{name:<30} {ok}")
            continue
        r = workflow(path, client, rounds=rounds, mode=mode)
        if r["verdict"] not in ("not-software", "no-candidates"):
            n_total += 1
            if r["verdict"] == "unsat":
                n_sound += 1
        print(f"{name:<30} {r['verdict']:<10} {r['n_cand']:<6} {r['time']:.1f}s", flush=True)
    if not dry:
        print("-" * 58)
        print(f"SOUND: {n_sound}/{n_total} software-origin circuits proved")
