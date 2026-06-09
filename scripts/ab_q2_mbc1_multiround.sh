#!/usr/bin/env bash
# Q2.2: compare max_block_clauses=3 vs 1 on HEAD (vgasim p040).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BTOR="${BTOR:-$HOME/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/vgasim_imgfifo-p040.btor2}"
ROUNDS="${ROUNDS:-5}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-3}"
STRICT="${STRICT:-0}"
OUT_BASE="${OUT_BASE:-/tmp/q2_mbc_ab_$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$OUT_BASE"

parse_stats() {
  python3 - <<'PY' "$1"
import json, sys
text = open(sys.argv[1]).read() if sys.argv[1] else ""
stats = {}
for line in text.splitlines():
    if line.startswith("LLM_STATS"):
        for part in line.split():
            if "=" in part:
                k, v = part.split("=", 1)
                try: stats[k] = int(v)
                except ValueError: stats[k] = v
print(json.dumps(stats))
PY
}

run_round() {
  local label="$1"
  local mbc="$2"
  local round="$3"
  local run_dir="$OUT_BASE/${label}_r${round}"
  mkdir -p "$run_dir"
  BTOR="$BTOR" MAX_ATTEMPTS="$MAX_ATTEMPTS" MAX_BLOCK_CLAUSES="$mbc" STRICT="$STRICT" \
    bash "$ROOT/scripts/smoke_p040.sh" 2>&1 | tee "$run_dir/smoke.log" || true
  local artifact
  artifact="$(grep -o 'RUN_DIR=/tmp/pono_smoke_[^ ]*' "$run_dir/smoke.log" | head -1 | cut -d= -f2-)"
  if [[ -n "$artifact" && -d "$artifact" ]]; then
    cp -a "$artifact" "$run_dir/artifacts"
    parse_stats "$run_dir/artifacts/pono_stderr.log" >"$run_dir/stats.json"
  fi
}

echo "OUT_BASE=$OUT_BASE ROUNDS=$ROUNDS"
for r in $(seq 1 "$ROUNDS"); do
  echo "=== Round $r: mbc=3 ==="
  run_round "A1_mbc3" 3 "$r"
  echo "=== Round $r: mbc=1 (Q2.2) ==="
  run_round "A2_mbc1" 1 "$r"
done

python3 - <<PY
import json
from pathlib import Path
from collections import defaultdict

out = Path("$OUT_BASE")
rows = []
for p in sorted(out.glob("*/stats.json")):
    name = p.parent.name
    label, rnd = name.rsplit("_r", 1)
    s = json.loads(p.read_text())
    req = s.get("requests", 0) or 1
    rows.append({
        "label": label, "round": int(rnd),
        "accepted": s.get("accepted", 0), "requests": req,
        "pct": 100 * s.get("accepted", 0) / req,
        "rejected_initial": s.get("rejected_initial", 0),
        "induction_fail": s.get("induction_fail", 0),
    })

agg = defaultdict(lambda: {"accepted": 0, "requests": 0, "rejected_initial": 0, "induction_fail": 0})
for r in rows:
    a = agg[r["label"]]
    a["accepted"] += r["accepted"]
    a["requests"] += r["requests"]
    a["rejected_initial"] += r["rejected_initial"]
    a["induction_fail"] += r["induction_fail"]

print("=== Per-round ===")
for r in rows:
    print(f"{r['label']:<10} r{r['round']} acc={r['accepted']}/{r['requests']} ({r['pct']:.1f}%) ri={r['rejected_initial']} ind={r['induction_fail']}")

print("\n=== Aggregate ===")
for label in sorted(agg):
    a = agg[label]
    pct = 100 * a["accepted"] / a["requests"] if a["requests"] else 0
    print(f"{label:<10} acc={a['accepted']}/{a['requests']} ({pct:.1f}%) ri={a['rejected_initial']} ind={a['induction_fail']}")

labels = sorted(agg)
if len(labels) == 2:
    p0 = 100 * agg[labels[0]]["accepted"] / agg[labels[0]]["requests"]
    p1 = 100 * agg[labels[1]]["accepted"] / agg[labels[1]]["requests"]
    print(f"\nDelta ({labels[1]} - {labels[0]}): {p1 - p0:+.1f} pp")
print(f"Artifacts: {out}")
PY
