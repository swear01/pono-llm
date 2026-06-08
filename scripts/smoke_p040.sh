#!/usr/bin/env bash
# p040 IC3 Frame v1 smoke — isolated session (no shared /tmp/p040_*).
# Modes: default = batch + sync wait; full-async = NO_SYNC=1 (adds --no-llm-sync-after-flush).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BTOR="${BTOR:-$HOME/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/qspiflash_dualflexpress_divfive-p040.btor2}"
RUN_DIR="$(mktemp -d /tmp/pono_smoke_XXXXXX)"

REQ="$RUN_DIR/requests.jsonl"
RESP="$RUN_DIR/responses.jsonl"
LOG="$RUN_DIR/llm_log.jsonl"
SIDECAR_LOG="$RUN_DIR/sidecar.log"
PONO_OUT="$RUN_DIR/pono_stdout.log"
PONO_ERR="$RUN_DIR/pono_stderr.log"
MANIFEST="$RUN_DIR/manifest.json"

if ! python3 -c "
import sys
sys.path.insert(0, '$ROOT/llm_worker')
from env_config import load_env, any_llm_api_key_configured
load_env()
sys.exit(0 if any_llm_api_key_configured() else 1)
"; then
  echo "ERROR: set API keys in $ROOT/.env (see .env.sample)" >&2
  exit 1
fi
if [[ ! -x "$ROOT/build/pono" ]]; then
  echo "ERROR: build/pono missing — run cmake build in $ROOT/build" >&2
  exit 1
fi
if [[ ! -f "$BTOR" ]]; then
  echo "ERROR: benchmark not found: $BTOR" >&2
  exit 1
fi

SNAPSHOT_MAX="${SNAPSHOT_MAX:-0}"
PONO_TIMEOUT="${PONO_TIMEOUT:-600}"
PARALLEL_SAMPLES="${PARALLEL_SAMPLES:-1}"
MAX_INFLIGHT="${MAX_INFLIGHT:-8}"
DRAIN_SEC="${DRAIN_SEC:-600}"
BATCH_WAIT_SEC="${BATCH_WAIT_SEC:-300}"
STRICT="${STRICT:-1}"
NO_SYNC="${NO_SYNC:-0}"

echo "RUN_DIR=$RUN_DIR"
echo "snapshot_max_clauses=$SNAPSHOT_MAX parallel_samples=$PARALLEL_SAMPLES max_inflight=$MAX_INFLIGHT drain_sec=$DRAIN_SEC batch_wait_sec=$BATCH_WAIT_SEC strict=$STRICT"

SIDECAR_EXTRA=()
[[ -n "${LLM_PROVIDER:-}" ]] && SIDECAR_EXTRA+=(--provider "$LLM_PROVIDER")

python3 -u "$ROOT/llm_worker/sidecar.py" \
  --req-path "$REQ" \
  --resp-path "$RESP" \
  --log-path "$LOG" \
  --prompt-dir "$ROOT/llm_worker/prompts/" \
  --poll-interval 0.5 \
  --max-inflight-requests "$MAX_INFLIGHT" \
  --snapshot-max-clauses "$SNAPSHOT_MAX" \
  "${SIDECAR_EXTRA[@]}" \
  >"$SIDECAR_LOG" 2>&1 &
SIDECAR_PID=$!
sleep 2

PONO_EXTRA=()
if [[ "$NO_SYNC" == "1" ]]; then
  PONO_EXTRA+=(--no-llm-sync-after-flush)
fi

timeout "$PONO_TIMEOUT" "$ROOT/build/pono" -e ic3ia -k 5 \
  --llm-gen-mode async-cti \
  --llm-parallel-samples "$PARALLEL_SAMPLES" \
  --llm-reasoning-effort none \
  --llm-max-attempts 1 \
  --llm-accepted-budget 5 \
  --llm-batch-wait-sec "$BATCH_WAIT_SEC" \
  --llm-snapshot-max-clauses "$SNAPSHOT_MAX" \
  --llm-req-path "$REQ" \
  --llm-resp-path "$RESP" \
  --llm-log "$LOG" \
  "${PONO_EXTRA[@]}" \
  "$BTOR" >"$PONO_OUT" 2>"$PONO_ERR" || true

echo "--- draining sidecar (up to ${DRAIN_SEC}s) ---"
deadline=$((SECONDS + DRAIN_SEC))
while (( SECONDS < deadline )); do
  req_n=0
  log_n=0
  [[ -f "$REQ" ]] && req_n=$(wc -l <"$REQ" | tr -d ' ')
  [[ -f "$LOG" ]] && log_n=$(wc -l <"$LOG" | tr -d ' ')
  if (( req_n > 0 && log_n >= req_n )); then
    echo "sidecar caught up: requests=$req_n llm_log=$log_n"
    break
  fi
  echo "  waiting: requests=$req_n llm_log=$log_n"
  sleep 2
done

kill -TERM "$SIDECAR_PID" 2>/dev/null || true
wait "$SIDECAR_PID" 2>/dev/null || true

python3 - <<PY
import json, re, sys
from pathlib import Path

run_dir = Path("$RUN_DIR")
strict = int("$STRICT")
parallel = int("$PARALLEL_SAMPLES")
req_path = Path("$REQ")
resp_path = Path("$RESP")
log_path = Path("$LOG")
pono_err = Path("$PONO_ERR")
sidecar_log = Path("$SIDECAR_LOG")

errors = []
llm_stats = {}
for line in pono_err.read_text().splitlines() if pono_err.exists() else []:
    if line.strip().startswith("LLM_STATS"):
        for part in line.split():
            if "=" in part:
                k, v = part.split("=", 1)
                try:
                    llm_stats[k] = int(v)
                except ValueError:
                    llm_stats[k] = v

req_n = 0
req_types = []
max_req_bytes = 0
digest_count = 0
if req_path.exists():
    for line in req_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        req_n += 1
        max_req_bytes = max(max_req_bytes, len(line.encode()))
        obj = json.loads(line)
        req_types.append(obj.get("type"))
        if obj.get("cti_digest"):
            digest_count += 1

resp_n = 0
if resp_path.exists():
    resp_n = sum(1 for ln in resp_path.read_text().splitlines() if ln.strip())

sidecar_text = sidecar_log.read_text() if sidecar_log.exists() else ""
parse_fails = sidecar_text.count("Failed to parse request line")

if req_n and not all(t == "ic3_frame_batch_request" for t in req_types):
    errors.append(f"unexpected request types: {req_types[:5]}")
if req_n >= 80:
    errors.append(f"too many batch requests: {req_n}")
if strict and req_n == 0:
    errors.append("no batch requests produced (pono may have crashed — rebuild build/pono)")
if strict and req_n and resp_n != req_n * parallel:
    errors.append(f"responses {resp_n} != requests {req_n} * {parallel}")
if strict and llm_stats.get("batch_timeouts", 0) != 0:
    errors.append(f"batch_timeouts={llm_stats.get('batch_timeouts')}")
if strict and parse_fails:
    errors.append(f"sidecar parse failures: {parse_fails}")
if strict and max_req_bytes > 500_000:
    errors.append(f"max request line {max_req_bytes} bytes > 500KB (digest may be off)")

timing = {}
if log_path.exists():
    try:
        import subprocess
        out = subprocess.check_output(
            ["python3", "$ROOT/scripts/report_llm_timing.py", str(log_path), "--json"],
            text=True,
        )
        timing = json.loads(out)
    except Exception as exc:
        timing = {"error": str(exc)}

manifest = {
    "run_dir": str(run_dir),
    "sidecar_pid": $SIDECAR_PID,
    "req_path": "$REQ",
    "resp_path": "$RESP",
    "btor": "$BTOR",
    "snapshot_max_clauses": int("$SNAPSHOT_MAX"),
    "max_inflight": int("$MAX_INFLIGHT"),
    "batch_wait_sec": int("$BATCH_WAIT_SEC"),
    "requests": req_n,
    "responses": resp_n,
    "max_request_bytes": max_req_bytes,
    "digest_requests": digest_count,
    "llm_stats": llm_stats,
    "llm_timing": timing,
    "sidecar_parse_fails": parse_fails,
    "strict_pass": not errors,
    "errors": errors,
}
(run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("manifest:", run_dir / "manifest.json")
print(f"requests={req_n} responses={resp_n} max_req_bytes={max_req_bytes} digest_reqs={digest_count}")
if llm_stats:
    print("llm_stats:", llm_stats)
if timing and timing.get("count"):
    lat = timing.get("latency_ms", {})
    ub = timing.get("user_prompt_bytes", {})
    print(f"llm_timing: n={timing['count']} latency_ms_mean={lat.get('mean', 0):.0f} "
          f"user_bytes_mean={ub.get('mean', 0)}")
if errors:
    print("SMOKE CHECK FAILED:")
    for e in errors:
        print(" ", e)
    if strict:
        sys.exit(1)
else:
    print("SMOKE CHECK PASSED (channel health)")
PY

echo "--- pono result ---"
cat "$PONO_OUT" || true
echo "--- LLM_STATS ---"
grep LLM_STATS "$PONO_ERR" || true
echo "--- sidecar tail ---"
tail -8 "$SIDECAR_LOG" || true
echo "--- counts ---"
echo "requests: $(wc -l <"$REQ" 2>/dev/null || echo 0)"
echo "responses: $(wc -l <"$RESP" 2>/dev/null || echo 0)"
echo "llm_log: $(wc -l <"$LOG" 2>/dev/null || echo 0)"
echo "--- llm_log sample ---"
head -1 "$LOG" 2>/dev/null | python3 -m json.tool 2>/dev/null || true
echo "Artifacts kept in $RUN_DIR"
