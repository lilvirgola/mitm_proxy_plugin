"""
Execution logger for logging mutant executions and traffic observations.
"""

import json
import threading
import time
from pathlib import Path

from .helpers import extract_trace_id


class ExecutionLogger:
    def __init__(self):
        self.file = None
        self.buffer = []
        self.seq = 0
        self.lock = threading.Lock()

    def open(self, path: str):
        self.file = Path(path).open("a", encoding="utf-8")  # noqa: SIM115

    def log_execution(self, flow, mutant: dict, campaign_id: str | None = None):
        """Log a mutation execution."""
        request = getattr(flow, "request", None)
        response = getattr(flow, "response", None)
        path = ""
        method = ""
        if request:
            method = getattr(request, "method", "")
            req_path = getattr(request, "path", "")
            path = req_path.split("?")[0] if req_path else ""

        status_code = (
            getattr(response, "status_code", "DROPPED") if response else "DROPPED"
        )
        metadata = getattr(flow, "metadata", {}) or {}

        entry = {
            "type": "mutation",
            "timestamp": time.time(),
            "campaign_id": campaign_id or metadata.get("campaign_id"),
            "trace_id": extract_trace_id(flow),
            "request_id": metadata.get("request_id"),
            "operation_id": metadata.get("op_id"),
            "method": method,
            "path": path,
            "mutant_id": mutant.get("id"),
            "operator": mutant.get("operator"),
            "taxonomy_path": mutant.get("taxonomy_path"),
            "status": "EXECUTED",
            "response_status": status_code,
            "interaction_id": metadata.get("interaction_id"),
            "system_interaction_id": metadata.get("system_interaction_id"),
            "mutant_interaction_id": metadata.get("mutant_interaction_id"),
            "campaign_start_system_id": metadata.get("campaign_start_system_id"),
        }
        self._append(entry)

    def log_observation(self, flow, service_name: str, role: str = "observer"):
        """Log a traffic observation."""
        request = getattr(flow, "request", None)
        response = getattr(flow, "response", None)
        path = ""
        method = ""
        if request:
            method = getattr(request, "method", "")
            req_path = getattr(request, "path", "")
            path = req_path.split("?")[0] if req_path else ""

        status_code = (
            getattr(response, "status_code", "DROPPED") if response else "DROPPED"
        )
        content = getattr(response, "content", None)
        response_size = len(content) if content is not None else 0
        metadata = getattr(flow, "metadata", {}) or {}

        entry = {
            "type": "observation",
            "timestamp": time.time(),
            "service_name": service_name,
            "role": role,
            "request_id": metadata.get("request_id"),
            "trace_id": extract_trace_id(flow),
            "method": method,
            "path": path,
            "request_status": status_code,
            "response_size": response_size,
            "campaign_id": metadata.get("campaign_id"),
            "observed_mutant_id": metadata.get("observed_mutant_id"),
            "observed_campaign_id": metadata.get("observed_campaign_id"),
            "interaction_id": metadata.get("interaction_id"),
            "mutant_interaction_id": metadata.get("mutant_interaction_id"),
            "system_interaction_id": metadata.get("system_interaction_id"),
        }
        self._append(entry)

    def _append(self, entry: dict):
        """Thread-safe append to buffer + file."""
        with self.lock:
            self.seq += 1
            entry["seq"] = self.seq
            self.buffer.append(entry)

            if len(self.buffer) > 10000:
                self.buffer = self.buffer[-5000:]

        if self.file:
            self.file.write(json.dumps(entry) + "\n")
            self.file.flush()

    def drain(self, last_seq: int = 0, entry_type: str | None = None) -> list:
        """Returns all log entries with seq > last_seq."""
        with self.lock:
            start_idx = 0
            for i, entry in enumerate(self.buffer):
                if entry["seq"] > last_seq:
                    start_idx = i
                    break
            else:
                return []

            entries = self.buffer[start_idx:]

            if entry_type:
                entries = [e for e in entries if e.get("type") == entry_type]

            return list(entries)

    def close(self):
        if self.file:
            self.file.close()
            self.file = None
