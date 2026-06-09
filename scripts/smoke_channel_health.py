"""Channel health checks shared by smoke_p040.sh and unit tests."""

from __future__ import annotations

import json
from pathlib import Path


def evaluate_channel_health(
    *,
    req_path: Path | str,
    resp_path: Path | str,
    strict: bool = True,
    parallel: int = 1,
    sidecar_log_text: str = "",
    llm_stats: dict | None = None,
    max_request_bytes_limit: int = 500_000,
    max_requests_limit: int = 80,
) -> tuple[list[str], dict]:
    """Return (errors, summary) for smoke-style channel validation."""
    req_path = Path(req_path)
    resp_path = Path(resp_path)
    llm_stats = dict(llm_stats or {})
    errors: list[str] = []

    req_n = 0
    req_types: list[str] = []
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
            req_types.append(obj.get("type", ""))
            if obj.get("cti_digest"):
                digest_count += 1

    resp_n = 0
    if resp_path.exists():
        resp_n = sum(1 for ln in resp_path.read_text().splitlines() if ln.strip())

    parse_fails = sidecar_log_text.count("Failed to parse request line")

    if req_n and not all(t == "ic3_frame_batch_request" for t in req_types):
        errors.append(f"unexpected request types: {req_types[:5]}")
    if req_n >= max_requests_limit:
        errors.append(f"too many batch requests: {req_n}")
    if strict and req_n == 0:
        errors.append("no batch requests produced (pono may have crashed — rebuild build/pono)")
    if strict and req_n and resp_n != req_n * parallel:
        errors.append(f"responses {resp_n} != requests {req_n} * {parallel}")
    if strict and llm_stats.get("batch_timeouts", 0) != 0:
        errors.append(f"batch_timeouts={llm_stats.get('batch_timeouts')}")
    if strict and parse_fails:
        errors.append(f"sidecar parse failures: {parse_fails}")
    if strict and max_req_bytes > max_request_bytes_limit:
        errors.append(
            f"max request line {max_req_bytes} bytes > {max_request_bytes_limit}B (digest may be off)"
        )

    summary = {
        "requests": req_n,
        "responses": resp_n,
        "max_request_bytes": max_req_bytes,
        "digest_requests": digest_count,
        "sidecar_parse_fails": parse_fails,
        "strict_pass": not errors,
    }
    return errors, summary
