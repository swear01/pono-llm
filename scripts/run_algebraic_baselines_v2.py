#!/usr/bin/env python3
"""Run the frozen Gate 4B0-v2 generic C2 baseline matrix."""
from __future__ import annotations
import argparse,json,os,re,resource,subprocess,tempfile,time
from pathlib import Path
import z3
import build_algebraic_baseline_corpus_v2 as corpus
import candidate_cert_check

def timed_cli(command,timeout):
 with tempfile.NamedTemporaryFile(delete=False) as h: metrics=Path(h.name)
 wrapped=["/usr/bin/time","-v","-o",str(metrics),"--","/usr/bin/timeout","--kill-after=2s",f"{timeout}s",*command]; start=time.perf_counter(); p=subprocess.run(wrapped,capture_output=True,text=True,check=False); wall=time.perf_counter()-start; text=metrics.read_text(); metrics.unlink(missing_ok=True); rss=None
 for line in text.splitlines():
  if "Maximum resident set size" in line: rss=int(line.rsplit(":",1)[1])
 result=next((x.strip() for x in p.stdout.splitlines() if x.strip() in {"sat","unsat","unknown"}),"timeout" if p.returncode==124 else "error")
 return {"result":result,"returncode":p.returncode,"wall_time_sec":wall,"max_rss_kib":rss,"stdout":p.stdout,"stderr":p.stderr}
def run(corpus_dir,capture,root,out,local_z3,polysat_z3,polysat_source,trials=5,timeout=20):
 if out.exists(): raise FileExistsError(f"refusing to overwrite {out}")
 m=corpus.validate(corpus_dir); rows=[]; version=subprocess.run([str(local_z3),"--version"],capture_output=True,text=True,check=True).stdout.strip(); arms=[{"id":"candidate-cert-check","version":z3.get_version_string(),"options":{"timeout_ms":timeout*1000}},{"id":"local-z3-default","version":version,"options":["-st"]},{"id":"local-z3-intblast","version":version,"options":["sat.smt=true","tactic.default_tactic=smt","smt.bv.solver=2","-st"]}]
 unavailable=None
 if not polysat_z3.is_file() or not polysat_source.is_dir(): unavailable=f"solver executable is unavailable: {polysat_z3}"
 for q in m["queries"]:
  source=capture/q["candidate_source_file"]; a=candidate_cert_check.load_predicate_entries(str(source))[q["candidate_row_index"]]["predicate_ast"]; f=corpus.formula(root/q["benchmark_id"],a); qp=corpus_dir/q["query"]
  for trial in range(trials):
   start=time.perf_counter(); solver,res=candidate_cert_check.solve_formula(f,timeout*1000); wall=time.perf_counter()-start; rows.append({"benchmark_id":q["benchmark_id"],"benchmark_sha256":q["benchmark_sha256"],"candidate_sha256":q["candidate_sha256"],"query_sha256":q["query_sha256"],"arm":"candidate-cert-check","trial":trial,"result":str(res),"wall_time_sec":wall,"peak_memory_process_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,"unknown_reason":solver.reason_unknown() if res==z3.unknown else ""})
   for aid,opts in (("local-z3-default",["-st"]),("local-z3-intblast",["sat.smt=true","tactic.default_tactic=smt","smt.bv.solver=2","-st"])):
    outcome=timed_cli([str(local_z3),*opts,f"timeout={timeout*1000}",str(qp)],timeout+5); rows.append({"benchmark_id":q["benchmark_id"],"benchmark_sha256":q["benchmark_sha256"],"candidate_sha256":q["candidate_sha256"],"query_sha256":q["query_sha256"],"arm":aid,"trial":trial,"command":[str(local_z3),*opts,f"timeout={timeout*1000}",str(qp)],**outcome})
   if unavailable:
    for aid in ("pinned-z3-default","pinned-z3-polysat","pinned-z3-intblast"): rows.append({"benchmark_id":q["benchmark_id"],"benchmark_sha256":q["benchmark_sha256"],"candidate_sha256":q["candidate_sha256"],"query_sha256":q["query_sha256"],"arm":aid,"trial":trial,"result":"unavailable","unknown_reason":unavailable})
 report={"schema":"pono-algebraic-baseline-solver-matrix-v2","corpus_manifest_file_sha256":corpus.fsha(corpus_dir/"manifest.json"),"trials":trials,"timeout_seconds":timeout,"arms":arms,"pinned_polysat":{"source":str(polysat_source),"executable":str(polysat_z3),"status":"unavailable" if unavailable else "available","error":unavailable or ""},"rows":rows}; report["report_sha256"]=corpus.csha(report); out.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n"); return report
def main():
 p=argparse.ArgumentParser(); p.add_argument("corpus",type=Path); p.add_argument("capture",type=Path); p.add_argument("root",type=Path); p.add_argument("out",type=Path); p.add_argument("--local-z3",type=Path,required=True); p.add_argument("--polysat-z3",type=Path,required=True); p.add_argument("--polysat-source",type=Path,required=True); p.add_argument("--trials",type=int,default=5); p.add_argument("--timeout",type=int,default=20); a=p.parse_args()
 try: r=run(a.corpus,a.capture,a.root,a.out,a.local_z3,a.polysat_z3,a.polysat_source,a.trials,a.timeout)
 except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, subprocess.SubprocessError, z3.Z3Exception) as e: print(e); return 1
 counts={};
 for x in r["rows"]: counts.setdefault(x["arm"],{}); counts[x["arm"]][x["result"]]=counts[x["arm"]].get(x["result"],0)+1
 print(json.dumps(counts,indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
