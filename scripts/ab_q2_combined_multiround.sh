#!/usr/bin/env bash
# Combined Q2 A/B: A0 baseline vs A3 (Q2.1+Q2.2+Q2.3, max_block_clauses=1).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BTOR="${BTOR:-$HOME/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/vgasim_imgfifo-p040.btor2}"
ROUNDS="${ROUNDS:-5}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-3}"
MAX_BLOCK_CLAUSES="${MAX_BLOCK_CLAUSES:-1}"
STRICT="${STRICT:-0}"
OUT_BASE="${OUT_BASE:-/tmp/q2_combined_ab_$(date +%Y%m%d_%H%M%S)}"

mkdir -p "$OUT_BASE"
head_ref="$(git -C "$ROOT" rev-parse HEAD)"
trap 'git -C "$ROOT" checkout -f "$head_ref" --quiet 2>/dev/null; git -C "$ROOT" restore scripts/smoke_p040.sh 2>/dev/null || true' EXIT

ensure_smoke_env() {
  local smoke="$ROOT/scripts/smoke_p040.sh"
  if ! grep -q 'MAX_ATTEMPTS=' "$smoke"; then
    sed -i 's/PARALLEL_SAMPLES="${PARALLEL_SAMPLES:-1}"/PARALLEL_SAMPLES="${PARALLEL_SAMPLES:-1}"\nMAX_ATTEMPTS="${MAX_ATTEMPTS:-1}"/' "$smoke"
    sed -i 's/--llm-max-attempts 1/--llm-max-attempts "$MAX_ATTEMPTS"/' "$smoke"
  fi
  if ! grep -q 'MAX_BLOCK_CLAUSES=' "$smoke"; then
    sed -i 's/MAX_ATTEMPTS="${MAX_ATTEMPTS:-1}"/MAX_ATTEMPTS="${MAX_ATTEMPTS:-1}"\nMAX_BLOCK_CLAUSES="${MAX_BLOCK_CLAUSES:-3}"/' "$smoke"
    sed -i 's/--llm-max-attempts "$MAX_ATTEMPTS" \\/--llm-max-attempts "$MAX_ATTEMPTS" \\\n  --llm-max-block-clauses "$MAX_BLOCK_CLAUSES" \\/' "$smoke"
  fi
}

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

run_smoke() {
  local label="$1"
  local git_ref="$2"
  local mbc="$3"
  local round="$4"
  local run_dir="$OUT_BASE/${label}_r${round}"
  mkdir -p "$run_dir"

  git -C "$ROOT" checkout -f "$git_ref" --quiet
  git -C "$ROOT" restore scripts/smoke_p040.sh 2>/dev/null || true
  ensure_smoke_env
  make -C "$ROOT/build" -j"$(nproc)" pono >/dev/null 2>&1

  BTOR="$BTOR" MAX_ATTEMPTS="$MAX_ATTEMPTS" MAX_BLOCK_CLAUSES="$mbc" STRICT="$STRICT" \
    bash "$ROOT/scripts/smoke_p040.sh" 2>&1 | tee "$run_dir/smoke.log" || true

  local artifact
  artifact="$(grep -o 'RUN_DIR=/tmp/pono_smoke_[^ ]*' "$run_dir/smoke.log" | head -1 | cut -d= -f2-)"
  if [[ -n "$artifact" && -d "$artifact" ]]; then
    cp -a "$artifact" "$run_dir/artifacts"
    parse_stats "$run_dir/artifacts/pono_stderr.log" >"$run_dir/stats.json"
  fi
  git -C "$ROOT" restore scripts/smoke_p040.sh 2>/dev/null || true
}

echo "OUT_BASE=$OUT_BASE"
echo "A0=pre-q2-clause-quality  A3=HEAD Q2.1+Q2.2+Q2.3 mbc=$MAX_BLOCK_CLAUSES max_attempts=$MAX_ATTEMPTS rounds=$ROUNDS"

for r in $(seq 1 "$ROUNDS"); do
  echo "=== Round $r/$ROUNDS ==="
  run_smoke "A0_baseline" "pre-q2-clause-quality" 3 "$r"
  run_smoke "A3_combined" "$head_ref" "$MAX_BLOCK_CLAUSES" "$r"
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

print("\n=== Per-round (A0 baseline vs A3 combined) ===")
print(f"{'label':<14} {'rnd':>3} {'acc':>4} {'api':>4} {'%':>7} {'rej_init':>9} {'ind':>5}")
for r in rows:
    print(f"{r['label']:<14} {r['round']:>3} {r['accepted']:>4} {r['requests']:>4} {r['pct']:>6.1f}% {r['rejected_initial']:>9} {r['induction_fail']:>5}")

print("\n=== Aggregate ===")
print(f"{'label':<14} {'acc':>5} {'api':>5} {'%':>8} {'rej_init':>9} {'ind':>5}")
for label in sorted(agg):
    a = agg[label]
    pct = 100 * a["accepted"] / a["requests"] if a["requests"] else 0
    print(f"{label:<14} {a['accepted']:>5} {a['requests']:>5} {pct:>7.1f}% {a['rejected_initial']:>9} {a['induction_fail']:>5}")

labels = sorted(agg)
if len(labels) == 2:
    p0 = 100 * agg[labels[0]]["accepted"] / agg[labels[0]]["requests"]
    p1 = 100 * agg[labels[1]]["accepted"] / agg[labels[1]]["requests"]
    print(f"\nDelta accept/api (A3 - A0): {p1 - p0:+.1f} pp")
    ri_delta = agg[labels[1]]["rejected_initial"] - agg[labels[0]]["rejected_initial"]
    print(f"Delta rejected_initial: {ri_delta:+d}")
print(f"\nArtifacts: {out}")
PY
