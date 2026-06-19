"""
掃描每個 hint 的「真假」：X&&Y 在 BTOR2 是否真的不可達？
- BMC(X&&Y) sat        → HINT FALSE (X&&Y 可達) → 無望
- ind 證 !(X&&Y) unsat → HINT TRUE → sound 候選！(且若 ind 證得了就不需 LLM)
- 都沒結論            → UNKNOWN
這直接回答「剩餘 sound 方向 (b)」有沒有任何電路有希望。
"""
import sys, os, tempfile
sys.path.insert(0, "/home/swear01/pono-llm/scripts")
import audit_proof_soundness as A

def truth(pat, sx, sy, arr):
    name = pat.replace("*", "")
    if arr:
        return f"{name:<34} ⊘ array (skip)"
    path = A.find_path(pat)
    if not path:
        return f"{name:<34} path_not_found"
    lx, ly = A.find_lineno(path, sx), A.find_lineno(path, sy)
    if not lx or not ly:
        return f"{name:<34} signal_not_found"
    s1, mx = A.sort1_max(path)
    lines = open(path).readlines()
    new = [l for l in lines if not (l.split() and len(l.split()) > 1 and l.split()[1] == 'bad')]
    new += [f"{mx+1} and {s1} {lx} {ly}\n", f"{mx+2} bad {mx+1}\n"]
    with tempfile.NamedTemporaryFile('w', suffix='.btor2', delete=False) as f:
        f.write("".join(new)); tmp = f.name
    try:
        bmc = A.run(['-e', 'bmc', '--bound=80', tmp], 25)
        if bmc != "TIMEOUT" and ('\nsat' in '\n'+bmc.lower() or bmc.lower().startswith('sat')):
            return f"{name:<34} ❌ HINT FALSE  (X&&Y reachable @BMC)"
        # BMC 沒找到淺反例 → 試 ind 證 !(X&&Y) 為 invariant
        ind = A.run(['-e', 'ind', tmp], 12)
        if 'unsat' in ind.lower():
            return f"{name:<34} ✅ HINT TRUE   (!(X&&Y) proved invariant by ind!)"
        if ind != "TIMEOUT" and ('\nsat' in '\n'+ind.lower() or ind.lower().startswith('sat')):
            return f"{name:<34} ❌ HINT FALSE  (ind found cex)"
        return f"{name:<34} ❓ UNKNOWN     (BMC≤80 clean, ind inconclusive)"
    finally:
        os.unlink(tmp)

print(f"{'Circuit':<34} hint truth (X&&Y reachable in BTOR2?)")
print("─" * 80)
for pat, sx, sy, status, arr in A.MANIFEST:
    print(truth(pat, sx, sy, arr), flush=True)
