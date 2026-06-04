"""
JSONL protocol for Pono <-> Python sidecar communication (IC3 Frame v1).

Request: ic3_frame_request (written by Pono C++)
Response: ic3_frame_response (written by sidecar, polled by Pono C++)
"""

import json
import os
from typing import Any, Dict, List, Optional, Tuple

FrameRequest = Dict[str, Any]
FrameResponse = Dict[str, Any]


def read_request(path: str, last_position: int) -> Tuple[Optional[FrameRequest], int]:
    requests, new_position = read_requests_batch(path, last_position, max_lines=1)
    if not requests:
        return None, new_position
    return requests[0], new_position


def read_requests_batch(
    path: str,
    last_position: int,
    max_lines: int = 16,
) -> Tuple[List[FrameRequest], int]:
    """Read up to max_lines new JSONL request entries from last_position."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Request file not found: {path}")

    file_size = os.path.getsize(path)
    if file_size <= last_position:
        return [], last_position

    requests: List[FrameRequest] = []
    new_position = last_position

    with open(path, "r") as f:
        f.seek(last_position)
        for _ in range(max_lines):
            line = f.readline()
            if not line:
                new_position = f.tell()
                break
            new_position = f.tell()
            if not line.strip():
                continue
            try:
                requests.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[jsonl] Failed to parse request line: {e}")

    return requests, new_position


def write_response(path: str, response: FrameResponse, lock=None):
    line = json.dumps(response, ensure_ascii=False) + "\n"
    if lock is not None:
        with lock:
            with open(path, "a") as f:
                f.write(line)
        return
    with open(path, "a") as f:
        f.write(line)


def append_log_line(path: str, entry: dict, lock=None):
    line = json.dumps(entry) + "\n"
    if lock is not None:
        with lock:
            with open(path, "a") as log_f:
                log_f.write(line)
        return
    with open(path, "a") as log_f:
        log_f.write(line)


def write_request_test(path: str, context: FrameRequest):
    with open(path, "a") as f:
        f.write(json.dumps(context, ensure_ascii=False) + "\n")
