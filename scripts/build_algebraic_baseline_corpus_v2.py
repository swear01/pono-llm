#!/usr/bin/env python3
"""Freeze the result-blind Gate 4B0-v2 natural C2 corpus."""
from __future__ import annotations
import argparse, hashlib, json, re
from dataclasses import dataclass
from pathlib import Path
import z3
import candidate_cert_check, cert_check

SCHEMA="pono-algebraic-baseline-c2-corpus-v2"; REVISION="1e5856db"
@dataclass(frozen=True)
class Case: slug:str; row:int; width:int; family:str; task:str
CASES=(Case("egcd-ll_unwindbound10-8befbcbebbb9",1,64,"egcd","egcd-ll.yml"),Case("hard-ll_valuebound20-747ddcb9567d",0,64,"hard","hard-ll.yml"),Case("lcm1_unwindbound2-b147f6cde698",0,32,"lcm","lcm1.yml"),Case("lcm1_valuebound100-f2f4ac7de038",4,32,"lcm","lcm1.yml"),Case("lcm2_unwindbound50-77f0c136907a",0,32,"lcm","lcm2.yml"),Case("prodbin-ll_unwindbound10-af1b669300cd",0,64,"prodbin","prodbin-ll.yml"))
def cbytes(x): return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()
def csha(x): return hashlib.sha256(cbytes(x)).hexdigest()
def fsha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def walk(a):
 yield a
 for x in a.get("args",[]): yield from walk(x)
def validate_ast(a):
 n=tuple(walk(a)); forms={x.get("form") for x in n}
 if a.get("form")!="eq" or not forms<={"eq","add","sub","mul","ref","const"}: raise ValueError("unsupported candidate grammar")
 def hasref(x): return any(y.get("form")=="ref" and re.fullmatch(r"state\d+",y.get("ref","")) for y in walk(x))
 if not any(x.get("form")=="mul" and len(x.get("args",[]))==2 and hasref(x["args"][0]) and hasref(x["args"][1]) for x in n): raise ValueError("candidate lacks genuine state multiplication")
 refs=sorted({x["ref"] for x in n if x.get("form")=="ref"})
 if not refs or any(not re.fullmatch(r"state\d+",r) for r in refs): raise ValueError("invalid refs")
 return refs
def validate_model(path,a,width):
 m=cert_check.parse_btor2(path); refs=validate_ast(a); ids=[int(r[5:]) for r in refs]
 if {cert_check.width_of(m,i) for i in ids}!={width}: raise ValueError("mixed or wrong width")
 if any(i not in m["nexts"] for i in ids): raise ValueError("incomplete next map")
 allowed={"state","input","zero","one","ones","const","constd","consth","add","sub","mul","neg"}; leaves={"state","input","zero","one","ones","const","constd","consth"}; pending=[m["nexts"][i] for i in ids]; seen=set(); ops=set()
 while pending:
  i=abs(pending.pop())
  if i in seen: continue
  seen.add(i); op,_=m["nodes"][i]; ops.add(op)
  if op not in allowed: raise ValueError(f"unsupported next-cone operator {op}")
  if op not in leaves: pending.extend(int(t) for t in m["raw"][i][3:] if re.fullmatch(r"-?\d+",t))
 base=candidate_cert_check.build_base_formulas(str(path)); candidate_cert_check.compile_asts([a],base)
 return {"width":width,"state_refs":refs,"next_operators":sorted(ops),"state_count":len(m["states"]),"input_count":sum(op=="input" for op,_ in m["nodes"].values()),"bad_count":len(m["bads"]),"constraint_count":len(m["constraints"])}
def formula(path,a):
 b=candidate_cert_check.build_base_formulas(str(path)); h=candidate_cert_check.compile_asts([a],b)[0]
 return z3.And(h,b["constraints"],b["constraints_next"],z3.Not(z3.substitute(h,*b["substitutions"])))
def smt2(f):
 s=z3.Solver(); s.add(f); t=s.to_smt2(); return (("(set-logic QF_BV)\n" if "(set-logic " not in t else "")+t).rstrip()+"\n"
def build(root,capture,out,timeout=20):
 if out.exists(): raise FileExistsError(f"refusing to overwrite {out}")
 src=capture/"manifest.json"; manifest=json.loads(src.read_text()); by={x["slug"]:x for x in manifest["benchmarks"]}; out.mkdir(parents=True); qs=[]
 for c in CASES:
  row=by[c.slug]; pred=capture/row["predicates_file"]; entries=[json.loads(x) for x in pred.read_text().splitlines() if x.strip()]; entry=entries[c.row]; a=entry["predicate_ast"]; bid=row["benchmark_id"]; model=root/bid; structure=validate_model(model,a,c.width); qname=f"{Path(bid).stem}.row{c.row}.c2.smt2"; qp=out/qname; qp.write_text(smt2(formula(model,a)))
  qs.append({"benchmark_id":bid,"benchmark_sha256":fsha(model),"candidate_source_file":pred.name,"candidate_source_file_sha256":fsha(pred),"candidate_row_index":c.row,"candidate_entry_sha256":csha(entry),"candidate_sha256":csha(a),"query":qname,"query_sha256":fsha(qp),"bit_width":c.width,"recurrence_family":c.family,"expected_safe_or_unsafe":"safe","expected_verdict":True,"expected_verdict_source":{"repository":"sosy-lab/benchmarking/sv-benchmarks","revision":REVISION,"task":f"c/nla-digbench/{c.task}","property":"unreach-call.prp"},"inclusion_reason":"lowest structurally eligible JSONL row","timeout_seconds":timeout,"role":"natural-primary","counts_toward_h5a":True,"structure":structure})
 d={"schema":SCHEMA,"corpus_version":"gate-4b0-v2-natural-c2-1","source_manifest":str(src),"source_manifest_sha256":fsha(src),"selection_result_blind":True,"uses_v1_kernel_or_results":False,"query_count":len(qs),"independent_family_count":len({q["recurrence_family"] for q in qs}),"queries":qs}; d["manifest_sha256"]=csha(d); (out/"manifest.json").write_text(json.dumps(d,indent=2,sort_keys=True)+"\n"); return d
def validate(directory):
 d=json.loads((directory/"manifest.json").read_text()); claim=d.pop("manifest_sha256")
 if d.get("schema")!=SCHEMA or claim!=csha(d): raise ValueError("manifest hash mismatch")
 d["manifest_sha256"]=claim
 for q in d["queries"]:
  if fsha(directory/q["query"])!=q["query_sha256"]: raise ValueError("query hash mismatch")
 return d
def main():
 p=argparse.ArgumentParser(); p.add_argument("root",type=Path); p.add_argument("capture",type=Path); p.add_argument("out",type=Path); p.add_argument("--timeout-seconds",type=int,default=20); a=p.parse_args()
 try: print(json.dumps(build(a.root,a.capture,a.out,a.timeout_seconds),indent=2,sort_keys=True))
 except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, z3.Z3Exception) as e: print(e); return 1
 return 0
if __name__=="__main__": raise SystemExit(main())
