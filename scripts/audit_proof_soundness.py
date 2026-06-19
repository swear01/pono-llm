"""全量 cert_check：對 39 個宣稱 proof 跑 sound pipeline。
dry-run: 只解析路徑+signal。 full: 完整 IC3IA + cert_check。
"""
import subprocess, sys, os, tempfile, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/swear01/pono-llm/llm_worker")
import cert_check as CC
import z3
from btor2_reader import parse_btor2

PONO = "/home/swear01/pono-llm/build/pono"
ROOT = "/home/swear01/hwmcc_benchmarks"

# (glob_pattern, hint_x, hint_y, status, is_array)
MANIFEST = [
 # BEEM one-hot FSM
 ("frogs.5.prop1*","a_done","a_not_done","KNOWN",0),
 ("msmie.3.prop1*","a_error_state_slave_1","a_idle_slave_1","KNOWN",0),
 ("rushhour.4.prop1*","a_out","a_q_Red_car","KNOWN",0),
 ("brp2.3.prop2*","a_new_file","a_first_safe_frame","KNOWN",0),
 ("collision.1.prop1*","a_collision","a_wait_Medium","KNOWN",0),
 # Protocol
 ("pgm_protocol.7.prop1*","dve_valid","nexta_s0","KNOWN",0),
 ("pgm_protocol.7.prop2*","dve_valid","nexta_s0","STRONG",0),
 ("pgm_protocol.8.prop6*","a_r4","a_r0","STRONG",0),
 # RTL formal
 ("picorv32-check-p22*","CHECK_532$2","EN_532$2","KNOWN",0),
 ("ponylink-slaveTXlen-unsat*","CHECK_2951","EN_2951","KNOWN",0),
 ("picorv32-pcregs-p0*","EN_44$3","EN_39$1","STRONG",0),
 ("picorv32-pcregs-p2*","EN_42$2","EN_39$1","STRONG",0),
 ("zipcpu-zipmmu-p14*","EN_754$66","CHECK_677$59","KNOWN",0),
 ("zipcpu-zipmmu-p26*","CHECK_759$70","o_cyc","KNOWN",0),
 ("zipversa_composecrc_prf-p10*","tx.o_v","rx.f_past_valid","KNOWN",0),
 # f_past_valid
 ("qspiflash_dualflexpress_divthree-p012*","cfg_mode","f_past_valid","KNOWN",0),
 ("qspiflash_dualflexpress_divthree-p106*","o_dspi_cs_n","f_past_valid","KNOWN",0),
 ("qspiflash_qflexpress_divfive-p067*","o_qspi_cs_n","f_past_valid","KNOWN",0),
 ("vgasim_imgfifo-p036*","fifo.f_past_valid_gbl","CHECK_325","KNOWN",0),
 ("vgasim_imgfifo-p082*","fifo.f_past_valid_gbl","Y_305$275","KNOWN",0),
 ("vgasim_imgfifo-p089*","fifo.f_past_valid_gbl","CHECK_325","KNOWN",0),
 ("vgasim_imgfifo-p099*","fifo.f_past_valid_gbl","Y_305$275","KNOWN",0),
 ("vgasim_imgfifo-p105*","fifo.f_past_valid_gbl","Y_305$275","KNOWN",0),
 ("zipversa_composecrc_prf-p03*","rx.r_err","rx.f_past_valid","STRONG",0),
 # HLS handshake
 ("counter_bit_width_large.btor2","v1_buf","v2_buf","KNOWN",0),
 ("gcd.btor2","v1_buf","v2_buf","KNOWN",0),
 ("gcd_bit_width_large.btor2","v1_buf","v2_buf","KNOWN",0),
 ("kalman_bit_width_small.btor2","v1_buf","v2_buf","KNOWN",0),
 ("counter_bit_width_small.btor2","v1_buf","v2_buf","KNOWN",0),
 # Reset/valid
 ("hard-ll_valuebound20*","reset0","valid","KNOWN",0),
 ("sumt3.btor2","reset0","valid","KNOWN",0),
 ("zero_sum_const4*","reset0","valid","UNCERTAIN",1),
 ("zero_sum_const5*","reset0","valid","UNCERTAIN",1),
 ("standard_copy2_ground-2*","reset0","valid","UNCERTAIN",1),
 ("ifeqn5*","reset0","valid","UNCERTAIN",1),
 ("s32if*","reset0","valid","UNCERTAIN",1),
 ("flag_loopdep*","reset0","valid","UNCERTAIN",1),
 ("array7_pattern*","reset0","valid","UNCERTAIN",1),
 # mode
 ("pals_opt-floodmax.4*","valid","mode1","KNOWN",0),
]

def find_path(pat):
    hits = glob.glob(os.path.join(ROOT, "**", pat), recursive=True)
    hits = [h for h in hits if h.endswith((".btor",".btor2"))]
    return sorted(hits, key=len)[0] if hits else None

import re
def find_lineno(path, sym):
    # 優先用 btor2_reader（含 demangle，sv.symbol 即 hint 名稱）
    try:
        info=parse_btor2(path)
        for sv in info.states:
            if sv.symbol==sym: return sv.lineno
        # demangled: hint 'KIND_LINE$N' ← state symbol '...:LINE$N_KIND'
        m=re.match(r'([A-Za-z]\w*?)_(\d+)(?:\$(\d+))?$', sym)
        if m:
            kind,line,n=m.groups()
            for sv in info.states:
                if not sv.symbol: continue
                mm=re.search(r':(\d+)\$(\d+)_(\w+)$', sv.symbol)
                if mm:
                    sl,sn,sk=mm.groups()
                    if sk==kind and sl==line and (n is None or sn==n):
                        return sv.lineno
    except Exception: pass
    # fallback: 原始文字掃描 (state / output 指向的 node)
    st=out=None
    with open(path) as f:
        for line in f:
            p=line.split(';')[0].split()
            if len(p)<3: continue
            if p[-1]==sym:
                if p[1]=='state': st=int(p[0])
                elif p[1]=='output': out=int(p[2])   # output: id output node [sym]
    return st or out

def sort1_max(path):
    s1=None; mx=0
    with open(path) as f:
        for line in f:
            p=line.split(';')[0].split()
            if not p: continue
            try: n=int(p[0])
            except: continue
            mx=max(mx,n)
            if len(p)>=4 and p[1]=='sort' and p[2]=='bitvec' and p[3]=='1' and s1 is None: s1=n
    return s1,mx

def run(args,t):
    try:
        r=subprocess.run([PONO]+args,capture_output=True,timeout=t)
        return (r.stdout+r.stderr).decode(errors='replace')
    except subprocess.TimeoutExpired: return "TIMEOUT"

def process(pat,sx,sy,status,is_array,dry):
    path=find_path(pat)
    name=pat.replace("*","")
    if not path: return f"{name:<34} {status:<9} ✗ path_not_found"
    if is_array: return f"{name:<34} {status:<9} ⊘ SKIP(array, parser 不支援)"
    lx,ly=find_lineno(path,sx),find_lineno(path,sy)
    if not lx or not ly:
        return f"{name:<34} {status:<9} ✗ signal_not_found ({sx}={lx},{sy}={ly})"
    if dry:
        return f"{name:<34} {status:<9} ok  lx={lx} ly={ly}  {os.path.relpath(path,ROOT)[:45]}"
    s1,mx=sort1_max(path)
    lines=open(path).readlines()
    lines+=[f"{mx+1} and {s1} {lx} {ly}\n",f"{mx+2} not {s1} {mx+1}\n",f"{mx+3} constraint {mx+2}\n"]
    with tempfile.NamedTemporaryFile('w',suffix='.btor2',delete=False) as f:
        f.write("".join(lines)); tmp=f.name
    try:
        out=run(['-e','ic3ia','--show-invar',tmp],45)
        if out=="TIMEOUT": return f"{name:<34} {status:<9} ⏱ IC3IA_timeout"
        if 'unsat' not in out.lower():
            return f"{name:<34} {status:<9} ? constrained 非 unsat"
        invar=[l for l in out.splitlines() if l.startswith("INVAR:")]
        if not invar: return f"{name:<34} {status:<9} ? unsat 但無 INVAR"
        try:
            res=CC.certify(path,invar[0],timeout_ms=15000)
        except Exception as e:
            return f"{name:<34} {status:<9} ⚠ cert_err: {type(e).__name__}:{str(e)[:40]}"
        allok=all(r==z3.unsat for _,r in res)
        det=" ".join(f"{n.split()[0]}={'U' if r==z3.unsat else ('S' if r==z3.sat else '?')}" for n,r in res)
        return f"{name:<34} {status:<9} {'✅SOUND' if allok else '❌REJECT'}  [{det}]"
    finally:
        os.unlink(tmp)

if __name__=="__main__":
    dry = "--dry" in sys.argv
    print(f"{'Circuit':<34} {'Status':<9} verdict")
    print("─"*88)
    for pat,sx,sy,status,arr in MANIFEST:
        print(process(pat,sx,sy,status,arr,dry),flush=True)
