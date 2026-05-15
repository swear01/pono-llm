"""
JSONL protocol for Pono <-> Python sidecar communication.

Request format (Pono -> Python):
    {"frame_idx": N, "property": "...", "literals": [...], "candidate_language": "..."}

Response format (Python -> Pono):
    {"type": "cube_subset", "frame_hint": N, "keep_literals": [...], "drop_literals": [...], ...}
"""

import json
import os
from typing import Optional, Tuple, Dict, Any, List

CTIContext = Dict[str, Any]
LLMCandidate = Dict[str, Any]


def read_request(path: str, last_position: int) -> Tuple[Optional[CTIContext], int]:
    """
    Read the next unprocessed request from the JSONL file.

    Args:
        path: Path to the JSONL request file.
        last_position: File position (bytes) to start reading from.

    Returns:
        Tuple of (CTIContext or None, new_position).
        Returns (None, position) if no new requests are available.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Request file not found: {path}")

    file_size = os.path.getsize(path)
    if file_size <= last_position:
        return None, last_position

    with open(path, "r") as f:
        f.seek(last_position)
        line = f.readline()
        new_position = f.tell()

    if line.strip():
        try:
            request = json.loads(line)
            return request, new_position
        except json.JSONDecodeError as e:
            print(f"[jsonl] Failed to parse request line: {e}")
            return None, new_position

    return None, last_position


def write_response(path: str, candidate: LLMCandidate):
    """Append a candidate lemma response to the JSONL file."""
    with open(path, "a") as f:
        f.write(json.dumps(candidate, ensure_ascii=False) + "\n")


def write_request_test(path: str, context: CTIContext):
    """Write a test CTI context request (for testing without Pono running)."""
    with open(path, "a") as f:
        f.write(json.dumps(context, ensure_ascii=False) + "\n")
