from mitm_proxy_plugin.core.logger import ExecutionLogger


class MockRequest:
    def __init__(self, method="GET", path="/api/items?foo=bar", headers=None):
        self.method = method
        self.path = path
        self.headers = headers if headers is not None else {}


class MockResponse:
    def __init__(self, status_code=200, content=b"hello"):
        self.status_code = status_code
        self.content = content


class MockFlow:
    def __init__(self, request=None, response=..., metadata=None):
        self.metadata = metadata or {"request_id": "req-1", "op_id": "getItems"}
        self.request = request if request is not None else MockRequest()
        self.response = MockResponse() if response is ... else response


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
    assert logs[0]["path"] == "/api/items"  # query params stripped

    # Drain from 1 should return empty (nothing new)
    logs2 = logger.drain(1)
    assert len(logs2) == 0

    # 2. Log second execution
    logger.log_execution(
        flow, {"id": "m2", "operator": "MalformedJSON"}, campaign_id="c1"
    )

    # Drain from 1 should return ONLY the new item
    logs3 = logger.drain(1)
    assert len(logs3) == 1
    assert logs3[0]["seq"] == 2
    assert logs3[0]["mutant_id"] == "m2"

    logger.close()


def test_logger_observation(tmp_path):
    logger = ExecutionLogger()
    logger.open(str(tmp_path / "obs.jsonl"))

    flow = MockFlow(
        metadata={
            "request_id": "req-obs",
            "campaign_id": "c1",
            "observed_mutant_id": "m_upstream",
            "interaction_id": 42,
        }
    )

    logger.log_observation(flow, service_name="order-service", role="observer")

    obs = logger.drain(0, entry_type="observation")
    assert len(obs) == 1
    assert obs[0]["type"] == "observation"
    assert obs[0]["service_name"] == "order-service"
    assert obs[0]["role"] == "observer"
    assert obs[0]["observed_mutant_id"] == "m_upstream"
    assert obs[0]["response_size"] == 5
    assert obs[0]["interaction_id"] == 42

    # Filtering by type 'mutation' should return empty
    mutations = logger.drain(0, entry_type="mutation")
    assert len(mutations) == 0

    logger.close()


def test_logger_dropped_flow_handling(tmp_path):
    logger = ExecutionLogger()
    logger.open(str(tmp_path / "dropped.jsonl"))

    # Dropped flow has response=None
    flow = MockFlow(response=None, metadata={"request_id": "req-drop"})
    logger.log_execution(flow, {"id": "m_drop", "operator": "ConnectionDrop"})
    logger.log_observation(flow, service_name="auth-service")

    entries = logger.drain(0)
    assert len(entries) == 2
    assert entries[0]["response_status"] == "DROPPED"
    assert entries[1]["request_status"] == "DROPPED"
    assert entries[1]["response_size"] == 0

    logger.close()


def test_logger_buffer_cap():
    logger = ExecutionLogger()
    flow = MockFlow()
    mutant = {"id": "m", "operator": "Simulate500"}

    # Append 10,005 items without a file
    for _ in range(10005):
        logger.log_execution(flow, mutant)

    assert logger.seq == 10005
    # When 10001st item is added, buffer trims to 5000. 4 more items are added -> 5004.
    assert len(logger.buffer) == 5004
    assert logger.buffer[-1]["seq"] == 10005
