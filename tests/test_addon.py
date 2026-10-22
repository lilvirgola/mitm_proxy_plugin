import json
import socket
import urllib.request

import pytest
from mitmproxy import ctx

from mitm_proxy_plugin.addon import OpenAPIMutationAddon


class MockOptions:
    def __init__(self, **kwargs):
        self.mutation_seed = kwargs.get("mutation_seed", 42)
        self.exec_log = kwargs.get("exec_log", "executions.jsonl")
        self.openapi_spec = kwargs.get("openapi_spec", "")
        self.campaign_file = kwargs.get("campaign_file", "")
        self.mutation_control_port = kwargs.get("mutation_control_port", 8081)
        self.service_name = kwargs.get("service_name", "test-service")


class MockLoader:
    def __init__(self):
        self.options = {}

    def add_option(self, name, type, default, help):
        self.options[name] = {"type": type, "default": default, "help": help}


class FakeRequest:
    def __init__(self, method="GET", path="/api/items", headers=None, content=b""):
        self.method = method
        self.path = path
        self.headers = headers if headers is not None else {}
        self.query = {}
        self.content = content


class FakeResponse:
    def __init__(
        self, status_code=200, content=b'{"id": 1, "name": "item"}', headers=None
    ):
        self.status_code = status_code
        self.content = content
        self.headers = headers if headers is not None else {}


class FakeFlow:
    def __init__(self, request=None, response=None):
        self.request = request or FakeRequest()
        self.response = response or FakeResponse()
        self.metadata = {}
        self.killed = False

    def kill(self):
        self.killed = True


def get_free_port():
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def minimal_spec_file(tmp_path):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0"},
        "paths": {
            "/api/items": {
                "get": {
                    "operationId": "getItems",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"id": {"type": "integer"}},
                                    }
                                }
                            }
                        }
                    },
                },
                "post": {
                    "operationId": "createItem",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["name"],
                                    "properties": {"name": {"type": "string"}},
                                }
                            }
                        },
                    },
                    "responses": {"201": {"description": "Created"}},
                },
            }
        },
    }
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(spec))
    return str(path)


def test_addon_load():
    addon = OpenAPIMutationAddon()
    loader = MockLoader()
    addon.load(loader)
    assert "openapi_spec" in loader.options
    assert "mutation_seed" in loader.options
    assert "exec_log" in loader.options
    assert "mutation_control_port" in loader.options
    assert "service_name" in loader.options


def test_addon_configure_observer_mode(tmp_path):
    port = get_free_port()
    log_path = str(tmp_path / "observer_exec.jsonl")
    ctx.options = MockOptions(
        openapi_spec="",
        exec_log=log_path,
        mutation_control_port=port,
        service_name="observer-svc",
    )

    addon = OpenAPIMutationAddon()
    addon.configure(None)

    try:
        assert addon._observer_mode is True
        assert addon.matcher is None
        assert addon._server is not None

        # Verify control plane HTTP server responds even in observer mode
        req = urllib.request.Request(f"http://127.0.0.1:{port}/status")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            assert data["campaign_id"] is None
            assert data["active_mutant_id"] is None
    finally:
        addon.done()


def test_addon_configure_mutator_mode(tmp_path, minimal_spec_file):
    port = get_free_port()
    log_path = str(tmp_path / "mutator_exec.jsonl")
    campaign_file = tmp_path / "initial_campaign.json"
    campaign_file.write_text(
        json.dumps(
            {
                "campaign_id": "c_init",
                "mode": "single_mutant",
                "target": {"operation_id": "getItems"},
                "mutant": {"id": "m1", "operator": "Simulate502"},
            }
        )
    )

    ctx.options = MockOptions(
        openapi_spec=minimal_spec_file,
        campaign_file=str(campaign_file),
        exec_log=log_path,
        mutation_control_port=port,
        service_name="mutator-svc",
    )

    addon = OpenAPIMutationAddon()
    addon.configure(None)

    try:
        assert addon._observer_mode is False
        assert addon.matcher is not None
        assert addon.campaign["campaign_id"] == "c_init"
        assert addon.active_mutant["id"] == "m1"
        assert addon.active_operation_id == "getItems"
    finally:
        addon.done()


def test_trace_headers_injection_and_propagation():
    addon = OpenAPIMutationAddon()

    # Flow with missing headers
    flow = FakeFlow(request=FakeRequest(method="GET", path="/api/items"))
    addon.request(flow)

    req_headers = flow.request.headers
    assert "x-request-id" in req_headers
    assert "x-b3-traceid" in req_headers
    assert "traceparent" in req_headers
    assert flow.metadata["trace_id"] == req_headers["x-request-id"]
    assert flow.metadata["role"] == "observer"
    assert flow.metadata["interaction_id"] == 1

    # Flow with existing distributed tracing header
    existing_trace = "abcdef0123456789abcdef0123456789"
    flow2 = FakeFlow(
        request=FakeRequest(
            method="GET",
            path="/api/items",
            headers={"x-b3-traceid": existing_trace},
        )
    )
    addon.request(flow2)
    assert flow2.request.headers["x-b3-traceid"] == existing_trace
    assert flow2.metadata["trace_id"] == existing_trace
    assert flow2.metadata["interaction_id"] == 2


@pytest.mark.asyncio
async def test_full_mutator_flow(tmp_path, minimal_spec_file):
    port = get_free_port()
    log_path = str(tmp_path / "flow_exec.jsonl")
    ctx.options = MockOptions(
        openapi_spec=minimal_spec_file,
        exec_log=log_path,
        mutation_control_port=port,
        service_name="target-service",
    )

    addon = OpenAPIMutationAddon()
    addon.configure(None)

    # Set active campaign
    addon.campaign = {
        "campaign_id": "c001",
        "mode": "single_mutant",
        "target": {"operation_id": "getItems"},
        "mutant": {"id": "m_502", "operator": "Simulate502"},
        "policy": {"mutate_valid_requests_only": True},
    }
    addon.active_mutant = addon.campaign["mutant"]
    addon.active_operation_id = "getItems"

    flow = FakeFlow(request=FakeRequest(method="GET", path="/api/items"))
    addon.request(flow)

    assert flow.metadata["role"] == "mutator"
    assert flow.metadata["active_mutant"]["id"] == "m_502"
    assert flow.metadata["mutant_interaction_id"] == 1
    assert addon.campaign_stats["matched_requests"] == 1

    # Response hook applies mutation
    await addon.response(flow)
    assert flow.response.status_code == 502
    assert flow.response.headers["X-Campaign-Id"] == "c001"
    assert flow.response.headers["X-Mutant-Id"] == "m_502"
    assert addon.campaign_stats["mutated_responses"] == 1

    # Verify execution was logged
    drained = addon.logger.drain(0, entry_type="mutation")
    assert len(drained) == 1
    assert drained[0]["mutant_id"] == "m_502"
    assert drained[0]["campaign_id"] == "c001"

    addon.done()


@pytest.mark.asyncio
async def test_request_validation_blocks_mutation(tmp_path, minimal_spec_file):
    port = get_free_port()
    log_path = str(tmp_path / "val_exec.jsonl")
    ctx.options = MockOptions(
        openapi_spec=minimal_spec_file,
        exec_log=log_path,
        mutation_control_port=port,
    )

    addon = OpenAPIMutationAddon()
    addon.configure(None)

    addon.campaign = {
        "campaign_id": "c002",
        "mode": "single_mutant",
        "target": {"operation_id": "createItem"},
        "mutant": {"id": "m_drop", "operator": "ConnectionDrop"},
        "policy": {"mutate_valid_requests_only": True},
    }
    addon.active_mutant = addon.campaign["mutant"]
    addon.active_operation_id = "createItem"

    # Request has invalid body (missing required "name" field)
    flow = FakeFlow(
        request=FakeRequest(
            method="POST",
            path="/api/items",
            content=b'{"invalid_field": 123}',
        )
    )
    addon.request(flow)

    # Mutation should be blocked because request is invalid according to schema
    assert flow.metadata.get("role") == "observer"
    assert flow.metadata.get("active_mutant") is None
    assert addon.campaign_stats["blocked_invalid_requests"] == 1

    await addon.response(flow)
    assert flow.killed is False

    addon.done()


@pytest.mark.asyncio
async def test_observer_downstream_propagation_detection(tmp_path):
    port = get_free_port()
    log_path = str(tmp_path / "obs_exec.jsonl")
    ctx.options = MockOptions(
        openapi_spec="",
        exec_log=log_path,
        mutation_control_port=port,
        service_name="downstream-observer",
    )

    addon = OpenAPIMutationAddon()
    addon.configure(None)

    # Observer receives response containing upstream mutant headers
    flow = FakeFlow(
        request=FakeRequest(method="GET", path="/api/other"),
        response=FakeResponse(
            status_code=500,
            headers={"X-Mutant-Id": "upstream_m1", "X-Campaign-Id": "upstream_c1"},
        ),
    )
    addon.request(flow)
    await addon.response(flow)

    assert flow.metadata["observed_mutant_id"] == "upstream_m1"
    assert flow.metadata["observed_campaign_id"] == "upstream_c1"

    obs_logs = addon.logger.drain(0, entry_type="observation")
    assert len(obs_logs) == 1
    assert obs_logs[0]["observed_mutant_id"] == "upstream_m1"
    assert obs_logs[0]["service_name"] == "downstream-observer"

    addon.done()


def test_control_plane_endpoints(tmp_path):
    port = get_free_port()
    log_path = str(tmp_path / "cp_exec.jsonl")
    ctx.options = MockOptions(
        openapi_spec="",
        exec_log=log_path,
        mutation_control_port=port,
        service_name="api-gateway",
    )

    addon = OpenAPIMutationAddon()
    addon.configure(None)

    try:
        # 1. Hot swap to a single mutant campaign
        payload = json.dumps(
            {
                "campaign_id": "c_dynamic",
                "mode": "single_mutant",
                "target": {"operation_id": "getItem"},
                "mutant": {"id": "m_test", "operator": "MalformedJSON"},
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/campaign",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            assert data["status"] == "ok"
            assert data["campaign_id"] == "c_dynamic"

        assert addon.campaign["campaign_id"] == "c_dynamic"
        assert addon.active_mutant["id"] == "m_test"
        assert addon.active_operation_id == "getItem"

        # 2. Check /status
        req_status = urllib.request.Request(f"http://127.0.0.1:{port}/status")
        with urllib.request.urlopen(req_status) as resp:
            status_data = json.loads(resp.read().decode())
            assert status_data["campaign_id"] == "c_dynamic"
            assert status_data["active_mutant_id"] == "m_test"
            assert status_data["target_op"] == "getItem"
            assert status_data["stats"]["matched_requests"] == 0

        # 3. Clear campaign (switch to baseline)
        req_clear = urllib.request.Request(
            f"http://127.0.0.1:{port}/clear",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_clear) as resp:
            clear_data = json.loads(resp.read().decode())
            assert clear_data["status"] == "cleared"

        assert addon.campaign is None
        assert addon.active_mutant is None
        assert addon.active_operation_id is None

        # 4. Check /drain
        req_drain = urllib.request.Request(f"http://127.0.0.1:{port}/drain?seq=0")
        with urllib.request.urlopen(req_drain) as resp:
            drain_data = json.loads(resp.read().decode())
            assert "logs" in drain_data
            assert "current_seq" in drain_data

    finally:
        addon.done()


def test_edge_and_downstream_system_interaction(
    monkeypatch, tmp_path, minimal_spec_file
):
    port = get_free_port()
    log_path = str(tmp_path / "system_int_exec.jsonl")
    ctx.options = MockOptions(
        openapi_spec=minimal_spec_file,
        exec_log=log_path,
        mutation_control_port=port,
    )

    addon = OpenAPIMutationAddon()
    addon.configure(None)

    addon.campaign = {
        "campaign_id": "c_sys",
        "mode": "single_mutant",
        "target": {"operation_id": "getItems"},
        "mutant": {"id": "m1", "operator": "Simulate502"},
        "start_interaction_id": 100,
    }
    addon.active_mutant = addon.campaign["mutant"]
    addon.active_operation_id = "getItems"
    addon._campaign_start_system_id = 100

    # 1. Edge Proxy behavior (IS_EDGE_PROXY=true)
    monkeypatch.setenv("IS_EDGE_PROXY", "true")
    edge_flow = FakeFlow(request=FakeRequest(method="GET", path="/api/items"))
    addon.request(edge_flow)

    assert edge_flow.metadata["system_interaction_id"] == 1
    assert edge_flow.request.headers["x-restberus-system-interaction"] == "1"
    assert edge_flow.metadata["campaign_start_system_id"] == 100

    # 2. Downstream Proxy behavior (IS_EDGE_PROXY=false, propagated header present)
    monkeypatch.setenv("IS_EDGE_PROXY", "false")
    downstream_flow = FakeFlow(
        request=FakeRequest(
            method="GET",
            path="/api/items",
            headers={"x-restberus-system-interaction": "42"},
        )
    )
    addon.request(downstream_flow)

    assert downstream_flow.metadata["system_interaction_id"] == 42
    assert downstream_flow.metadata["campaign_start_system_id"] == 100

    addon.done()
