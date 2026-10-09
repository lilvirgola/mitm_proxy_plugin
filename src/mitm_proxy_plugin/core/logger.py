"""
Execution logger for logging mutant executions, eg. save the execution details to a JSONL file for later analysis.
"""
import json
import threading
from datetime import datetime, timezone
from mitmproxy import ctx

class ExecutionLogger:
    def __init__(self):
        self.file = None
        self.buffer = []
        self.seq = 0
        self.lock = threading.Lock()

    def open(self, path: str):
        # Keep file writing as a fallback/local debug mechanism
        self.file = open(path, 'a')

    def log_execution(self, flow, mutant: dict, campaign_id: str | None = None):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
        }
        
        with self.lock:
            self.seq += 1
            entry["seq"] = self.seq
            self.buffer.append(entry)
            
            # Prevent memory leaks in long-running mesh pods (keep last 10,000)
            if len(self.buffer) > 10000:
                self.buffer = self.buffer[-5000:]

        # Also write to file for local debugging
        if self.file:
            self.file.write(json.dumps(entry) + '\n')
            self.file.flush()

    def drain(self, last_seq: int = 0) -> list:
        """Returns all log entries with seq > last_seq"""
        with self.lock:
            # Find where to start slicing
            start_idx = 0
            for i, entry in enumerate(self.buffer):
                if entry["seq"] > last_seq:
                    start_idx = i
                    break
            else:
                return [] # Nothing new
            
            return self.buffer[start_idx:]

    def close(self):
        if self.file:
            self.file.close()