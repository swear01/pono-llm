"""方向2: 擴 benchmark — 非 array software 類別，跑 two-tier linear，找 linear-solvable.
sosylab safety-func/safety-rel/loops/reducer + nla-digbench-scaling (非 array)."""
import sys, os, glob
sys.path.insert(0, 'scripts')
import predicate_workflow as W
ROOT = '/home/swear01/hwmcc_benchmarks'
PATS = ['**/reducercommutativity/**/*.btor2', '**/loops-crafted*/**/*.btor2',
        '**/sosylab/loops/**/*.btor2', '**/safety-func/**/*.btor2',
        '**/safety-rel/**/*.btor2']
CAP = int(os.environ.get('EXPAND_CAP', '20'))

def collect():
    out = []
    for pa in PATS:
        out += glob.glob(os.path.join(ROOT, pa), recursive=True)
    return sorted(set(out))

if __name__ == "__main__":
    dry = "--dry" in sys.argv
    paths = collect()
    sw = []
    for p in paths:
        if 'array' in p.lower():
            continue  # skip array circuits (invariant isn't scalar-linear)
        try:
            if W.detect_software_origin(W.parse_btor2(p)):
                sw.append(p)
        except Exception:
            pass
    sw = sw[:CAP]
    print(f"方向2 擴 benchmark: {len(paths)} candidates, {len(sw)} software-origin (cap {CAP})")
    if dry:
        for p in sw:
            print("  ", os.path.relpath(p, ROOT)[:60])
        sys.exit(0)
    W.load_env()
    c = W.create_llm_client()
    n_sound = 0
    for p in sw:
        r = W.workflow(p, c, mode='two-tier', rounds=3)
        if r['verdict'] == 'unsat':
            n_sound += 1
        print(f"  {os.path.basename(p):<38} {r['verdict']:<10} {r['time']:.1f}s", flush=True)
    print(f"NEW linear-solvable: {n_sound}/{len(sw)}")
