"""
Execution logger for logging mutant executions and traffic observations.
"""
import json
import threading
import time
from mitmproxy import ctx


class ExecutionLogger:
    def __init__(self):
        self.file = None
        self.buffer = []
        self.seq = 0
        self.lock = threading.Lock()

    def open(self, path: str):
        self.file = open(path, 'a')

    def log_execution(self, flow, mutant: dict, campaign_id: str | None = None):
        """Log a mutation execution."""
        entry = {
            "type": "mutation",
            "timestamp": time.time(),
            "campaign_id": campaign_id or flow.metadata.get("campaign_id"),
            "request_id": flow.metadata.get("request_id"),
            "operation_id": flow.metadata.get("op_id"),
            "method": flow.request.method,
            "path": flow.request.path.split("?")[0],
            "mutant_id": mutant.get("id"),
            "operator": mutant.get("operator"),
            "taxonomy_path": mutant.get("taxonomy_path"),
            "status": "EXECUTED",
            "response_status": flow.response.status_code if flow.response else "DROPPED",
            "interaction_id": flow.metadata.get("interaction_id"),
        }
        self._append(entry)

    def log_observation(self, flow, service_name: str, role: str = "observer"):
        """Log a traffic observation."""
        entry = {
            "type": "observation",
            "timestamp": time.time(),
            "service_name": service_name,
            "role": role,
            "request_id": flow.metadata.get("request_id"),
            "trace_id": flow.metadata.get("trace_id"),
            "method": flow.request.method,
            "path": flow.request.path.split("?")[0],
            "request_status": flow.response.status_code if flow.response else "DROPPED",
            "response_size": len(flow.response.content) if flow.response else 0,
            "campaign_id": flow.metadata.get("campaign_id"),
            "observed_mutant_id": flow.metadata.get("observed_mutant_id"),
            "observed_campaign_id": flow.metadata.get("observed_campaign_id"),
            "interaction_id": flow.metadata.get("interaction_id"),
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
            self.file.write(json.dumps(entry) + '\n')
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
            
            return entries

    def close(self):
        if self.file:
            self.file.close()