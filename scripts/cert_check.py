"""
Certificate checker (SOUND):

給定 (1) 原始 btor2 電路  (2) IC3IA 在「含 hint constraint 的版本」上輸出的 INVAR，
在【原始電路】上獨立驗證 invariant 的三條件：

  C1  Init  ⟹ Inv            (初始狀態落在 Inv 內)
  C2  Inv ∧ Trans ⟹ Inv'     (Inv 對原始 transition 是 inductive)
  C3  Inv  ⟹ ¬BAD            (Inv 蘊含安全性)

三條件全 UNSAT(反例) → Inv 是原始電路的合法 safe inductive invariant
                       → 不論當初 hint 對錯，proof 100% sound。
任一條件出現反例     → 拒絕（hint 把證明帶歪了 = false positive 風險）。

完全不引用 hint constraint，所以結論獨立於 hint 是否正確。
"""
import sys, re
import z3


# ───────────────────────── btor2 → z3 encoder ─────────────────────────
def parse_btor2(path):
    sorts = {}          # id -> width (bitvec only)
    nodes = {}          # lineno -> (op, [int args/tokens])
    raw   = {}          # lineno -> full token list
    states = []         # [lineno]
    inits  = {}         # state_lineno -> value_lineno
    nexts  = {}         # state_lineno -> value_lineno
    constraints = []    # [node_lineno]   (原始電路自帶的)
    bad = None
    consts = {}         # lineno -> (kind, literal)
    with open(path) as f:
        for line in f:
            line = line.split(';')[0].strip()
            if not line:
                continue
            p = line.split()
            try:
                nid = int(p[0])
            except ValueError:
                continue
            op = p[1]
            raw[nid] = p
            if op == 'sort':
                if p[2] == 'bitvec':
                    sorts[nid] = int(p[3])
                # array sorts unsupported here
            elif op == 'input':
                nodes[nid] = ('input', [int(p[2])])
            elif op == 'state':
                states.append(nid)
                nodes[nid] = ('state', [int(p[2])])
            elif op == 'init':
                inits[int(p[3])] = int(p[4])
            elif op == 'next':
                nexts[int(p[3])] = int(p[4])
            elif op == 'bad':
                bad = int(p[2])
            elif op == 'constraint':
                constraints.append(int(p[2]))
            elif op in ('zero', 'one', 'ones'):
                consts[nid] = (op, p[2])           # p[2] = sort
                nodes[nid] = (op, [int(p[2])])
            elif op in ('const', 'constd', 'consth'):
                consts[nid] = (op, p[3])           # literal
                nodes[nid] = (op, [int(p[2]), p[3]])
            else:
                # generic op: args are remaining ints (skip sort at p[2])
                args = []
                for tok in p[2:]:
                    try:
                        args.append(int(tok))
                    except ValueError:
                        args.append(tok)
                nodes[nid] = (op, args)
    return dict(sorts=sorts, nodes=nodes, raw=raw, states=states,
                inits=inits, nexts=nexts, constraints=constraints,
                bad=bad, consts=consts)


def width_of(M, nid):
    """node nid 的 bitvec 寬度"""
    op, args = M['nodes'][nid]
    if op in ('input', 'state', 'zero', 'one', 'ones'):
        return M['sorts'][args[0]]
    if op in ('const', 'constd', 'consth'):
        return M['sorts'][args[0]]
    # ops 第一個 token 是 sort id
    raw = M['raw'][nid]
    return M['sorts'][int(raw[2])]


def b2bv(cond):
    """z3 Bool → 1-bit BitVec"""
    return z3.If(cond, z3.BitVecVal(1, 1), z3.BitVecVal(0, 1))


def build(M, nid, statevars, inputvars, cache):
    if nid in cache:
        return cache[nid]
    if nid < 0:                       # btor2: 負數 ref = 該 node 的 bitwise not
        r = ~build(M, -nid, statevars, inputvars, cache)
        cache[nid] = r
        return r
    op, args = M['nodes'][nid]

    if op == 'state':
        r = statevars[nid]
    elif op == 'input':
        w = M['sorts'][args[0]]
        if nid not in inputvars:
            inputvars[nid] = z3.BitVec(f"input{nid}", w)
        r = inputvars[nid]
    elif op == 'zero':
        r = z3.BitVecVal(0, M['sorts'][args[0]])
    elif op == 'one':
        r = z3.BitVecVal(1, M['sorts'][args[0]])
    elif op == 'ones':
        w = M['sorts'][args[0]]
        r = z3.BitVecVal((1 << w) - 1, w)
    elif op in ('const', 'constd', 'consth'):
        w = M['sorts'][args[0]]
        lit = args[1]
        if op == 'const':
            r = z3.BitVecVal(int(lit, 2), w)
        elif op == 'constd':
            r = z3.BitVecVal(int(lit, 10), w)
        else:
            r = z3.BitVecVal(int(lit, 16), w)
    else:
        raw = M['raw'][nid]
        w = M['sorts'][int(raw[2])]
        ops_args = args[1:]            # drop sort id; rest are operand nodes / params
        def sub(i):
            return build(M, ops_args[i], statevars, inputvars, cache)
        if   op == 'and':  r = sub(0) & sub(1)
        elif op == 'or':   r = sub(0) | sub(1)
        elif op == 'xor':  r = sub(0) ^ sub(1)
        elif op == 'nand': r = ~(sub(0) & sub(1))
        elif op == 'nor':  r = ~(sub(0) | sub(1))
        elif op == 'xnor': r = ~(sub(0) ^ sub(1))
        elif op == 'not':  r = ~sub(0)
        elif op == 'neg':  r = -sub(0)
        elif op == 'add':  r = sub(0) + sub(1)
        elif op == 'sub':  r = sub(0) - sub(1)
        elif op == 'mul':  r = sub(0) * sub(1)
        elif op == 'udiv': r = z3.UDiv(sub(0), sub(1))
        elif op == 'urem': r = z3.URem(sub(0), sub(1))
        elif op == 'sdiv': r = sub(0) / sub(1)
        elif op == 'srem': r = z3.SRem(sub(0), sub(1))
        elif op == 'sll':  r = sub(0) << sub(1)
        elif op == 'srl':  r = z3.LShR(sub(0), sub(1))
        elif op == 'sra':  r = sub(0) >> sub(1)
        elif op == 'eq':   r = b2bv(sub(0) == sub(1))
        elif op == 'neq':  r = b2bv(sub(0) != sub(1))
        elif op == 'ult':  r = b2bv(z3.ULT(sub(0), sub(1)))
        elif op == 'ulte': r = b2bv(z3.ULE(sub(0), sub(1)))
        elif op == 'ugt':  r = b2bv(z3.UGT(sub(0), sub(1)))
        elif op == 'ugte': r = b2bv(z3.UGE(sub(0), sub(1)))
        elif op == 'slt':  r = b2bv(sub(0) < sub(1))
        elif op == 'slte': r = b2bv(sub(0) <= sub(1))
        elif op == 'sgt':  r = b2bv(sub(0) > sub(1))
        elif op == 'sgte': r = b2bv(sub(0) >= sub(1))
        elif op == 'ite':  r = z3.If(sub(0) == z3.BitVecVal(1, 1), sub(1), sub(2))
        elif op == 'uext': r = z3.ZeroExt(int(ops_args[1]), sub(0))
        elif op == 'sext': r = z3.SignExt(int(ops_args[1]), sub(0))
        elif op == 'slice':
            hi, lo = int(ops_args[1]), int(ops_args[2])
            r = z3.Extract(hi, lo, sub(0))
        elif op == 'concat': r = z3.Concat(sub(0), sub(1))
        elif op == 'redor':  r = b2bv(sub(0) != 0)
        elif op == 'redand':
            x = sub(0); r = b2bv(x == z3.BitVecVal((1 << x.size()) - 1, x.size()))
        elif op == 'implies': r = b2bv(z3.Implies(sub(0) == 1, sub(1) == 1))
        else:
            raise NotImplementedError(f"op '{op}' (node {nid}) not handled")
    cache[nid] = r
    return r


# ───────────────────────── INVAR parsing ─────────────────────────
def parse_invar(invar_text, statevars, inputvars, M):
    """把 pono 的 INVAR s-expression 解析成 z3 Bool (在 statevars/inputvars 上)。"""
    expr = invar_text.split("INVAR:", 1)[1].strip()
    # 宣告所有 state<lineno> / input<lineno> 變數
    decls = []
    for ln in M['states']:
        decls.append(f"(declare-fun state{ln} () (_ BitVec {width_of(M, ln)}))")
    for ln, (op, args) in M['nodes'].items():
        if op == 'input':
            decls.append(f"(declare-fun input{ln} () (_ BitVec {M['sorts'][args[0]]}))")
    # pono 的 INVAR 最外層已是 Bool，直接 assert
    parsed = z3.parse_smt2_string("\n".join(decls) + f"\n(assert {expr})")
    inv_raw = parsed[0]
    # z3 parse 出來的變數是新建的；用名字對應替換成我們的 vars
    subs = []
    name2var = {f"state{ln}": statevars[ln] for ln in M['states']}
    name2var.update({f"input{ln}": inputvars[ln] for ln in inputvars})
    # 收集 inv_raw 中的自由變數
    seen = {}
    def collect(e):
        if z3.is_const(e) and e.decl().kind() == z3.Z3_OP_UNINTERPRETED:
            seen[e.decl().name()] = e
        for ch in e.children():
            collect(ch)
    collect(inv_raw)
    for nm, vexpr in seen.items():
        if nm in name2var:
            subs.append((vexpr, name2var[nm]))
    return z3.substitute(inv_raw, *subs)


# ───────────────────────── 三條件驗證 ─────────────────────────
def certify(orig_path, invar_text, timeout_ms=20000):
    M = parse_btor2(orig_path)
    statevars = {ln: z3.BitVec(f"state{ln}", width_of(M, ln)) for ln in M['states']}
    # 預建所有 input 變數 (current step)
    inputvars = {ln: z3.BitVec(f"input{ln}", M['sorts'][args[0]])
                 for ln, (op, args) in M['nodes'].items() if op == 'input'}
    cache = {}

    Inv = parse_invar(invar_text, statevars, inputvars, M)

    # Init: AND (state == init_value)
    init_terms = []
    for s_ln, v_ln in M['inits'].items():
        val = build(M, v_ln, statevars, inputvars, cache)
        init_terms.append(statevars[s_ln] == val)
    Init = z3.And(*init_terms) if init_terms else z3.BoolVal(True)

    # 原始電路自帶 constraint（屬於模型定義，必須假設）
    cons_terms = [build(M, c, statevars, inputvars, cache) == 1 for c in M['constraints']]
    Cons = z3.And(*cons_terms) if cons_terms else z3.BoolVal(True)

    # BAD
    BAD = build(M, M['bad'], statevars, inputvars, cache) == 1

    # next-state 表達式
    next_expr = {}
    for s_ln in M['states']:
        if s_ln in M['nexts']:
            next_expr[s_ln] = build(M, M['nexts'][s_ln], statevars, inputvars, cache)
        else:
            next_expr[s_ln] = statevars[s_ln]   # 無 next = 保持
    # next-step：state 換成 next_expr，input 換成 fresh（每步 input 自由）
    input_next = {ln: z3.BitVec(f"input{ln}_n", v.size()) for ln, v in inputvars.items()}
    subs = ([(statevars[s_ln], next_expr[s_ln]) for s_ln in M['states']] +
            [(inputvars[ln], input_next[ln]) for ln in inputvars])
    Inv_next = z3.substitute(Inv, *subs)
    Cons_next = z3.substitute(Cons, *subs)

    def check(name, formula):
        s = z3.Solver(); s.set("timeout", timeout_ms)
        s.add(formula)
        r = s.check()
        return name, r

    results = []
    # C1: Init ∧ Cons ∧ ¬Inv   應 UNSAT
    results.append(check("C1 Init⟹Inv",  z3.And(Init, Cons, z3.Not(Inv))))
    # C2: Inv ∧ Cons ∧ Trans ∧ ¬Inv'  應 UNSAT
    results.append(check("C2 inductive", z3.And(Inv, Cons, Cons_next, z3.Not(Inv_next))))
    # C3: Inv ∧ Cons ∧ BAD   應 UNSAT
    results.append(check("C3 Inv⟹¬BAD",  z3.And(Inv, Cons, BAD)))
    return results


if __name__ == "__main__":
    orig, invar_file = sys.argv[1], sys.argv[2]
    invar_text = open(invar_file).read()
    if "INVAR:" not in invar_text:
        print("NO INVAR (engine produced none) → 無法驗證"); sys.exit(2)
    print(f"原始電路: {orig}")
    print(f"INVAR: {invar_text.split('INVAR:',1)[1].strip()[:90]}...")
    print("-" * 60)
    ok = True
    for name, r in certify(orig, invar_text):
        verdict = "✓ UNSAT(無反例)" if r == z3.unsat else (
                  "✗ SAT(有反例!)" if r == z3.sat else f"? {r}")
        if r != z3.unsat:
            ok = False
        print(f"  {name:<16} {verdict}")
    print("-" * 60)
    print("結論:", "✅ SOUND PROOF — invariant 在原始電路成立" if ok
          else "❌ REJECT — invariant 在原始電路不成立 (hint 把證明帶歪了)")
