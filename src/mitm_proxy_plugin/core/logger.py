"""
Execution logger for logging mutant executions, eg. save the execution details to a JSONL file for later analysis.
"""
import json
from datetime import datetime, timezone

class ExecutionLogger:
    def __init__(self):
        self.file = None

    def open(self, path: str):
        self.file = open(path, 'a')

    def log_execution(self, flow, mutant: dict, campaign_id: str | None = None):
        print(f"Logging execution for request_id={flow.metadata.get('request_id')}, mutant_id={mutant['id']}")
        if not self.file:
            return
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "campaign_id": campaign_id or flow.metadata.get("campaign_id"),
            "request_id": flow.metadata.get("request_id"),
            "operation_id": flow.metadata.get("op_id"),
            "method": flow.request.method,
            "path": flow.request.path.split("?")[0],
            "mutant_id": mutant.get("id"),
            "operator": mutant.get("operator"),
            "taxonomy": mutant.get("taxonomy"),
            "taxonomy_path": mutant.get("taxonomy_path"),
            "fault_leaf": mutant.get("fault_leaf"),
            "description": mutant.get("description"),
            "status": "EXECUTED",
            "response_status": (
                flow.response.status_code
                if flow.response is not None
                else "DROPPED"
            ),
        }
        self.file.write(json.dumps(entry) + '\n')
        self.file.flush()

    def close(self):
        if self.file:
            self.file.close()