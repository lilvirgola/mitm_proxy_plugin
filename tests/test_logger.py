import pytest
from mitm_proxy_plugin.core.logger import ExecutionLogger

class MockRequest:
    def __init__(self):
        self.method = "GET"
        self.path = "/api/items?foo=bar"

class MockResponse:
    def __init__(self):
        self.status_code = 200

class MockFlow:
    def __init__(self):
        self.metadata = {"request_id": "req-1", "op_id": "getItems"}
        self.request = MockRequest()
        self.response = MockResponse()

def test_logger_buffer_and_drain(tmp_path):
    logger = ExecutionLogger()
    logger.open(str(tmp_path / "exec.jsonl"))
    
    flow = MockFlow()
    mutant = {"id": "m1", "operator": "Simulate502"}
    
    # 1. Log first execution
    logger.log_execution(flow, mutant, campaign_id="c1")
    
    # Drain from 0 should return 1 item
    logs = logger.drain(0)
    assert len(logs) == 1
    assert logs[0]["seq"] == 1
    assert logs[0]["mutant_id"] == "m1"
    assert logs[0]["path"] == "/api/items" # query params stripped
    
    # Drain from 1 should return empty (nothing new)
    logs2 = logger.drain(1)
    assert len(logs2) == 0
    
    # 2. Log second execution
    logger.log_execution(flow, {"id": "m2", "operator": "MalformedJSON"}, campaign_id="c1")
    
    # Drain from 1 should return ONLY the new item
    logs3 = logger.drain(1)
    assert len(logs3) == 1
    assert logs3[0]["seq"] == 2
    assert logs3[0]["mutant_id"] == "m2"
    
    logger.close()