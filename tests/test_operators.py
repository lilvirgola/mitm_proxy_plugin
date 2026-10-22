import json

import pytest

from mitm_proxy_plugin.mutations.operators import (
    OPERATOR_NAMES,
    apply_mutation,
)
from mitm_proxy_plugin.mutations.taxonomy import OPERATOR_TAXONOMY


class MockResponse:
    def __init__(
        self,
        status_code=200,
        content=b'{"id": 1, "name": "test", "required_field": "value", "status": "ACTIVE", "count": 5}',
        headers=None,
    ):
        self.status_code = status_code
        self.content = content
        self.headers = headers if headers is not None else {}


class MockFlow:
    def __init__(self, response=None):
        self.response = response or MockResponse()
        self.killed = False

    def kill(self):
        self.killed = True


def test_operator_names_matches_taxonomy():
    assert len(OPERATOR_NAMES) > 0
    assert OPERATOR_NAMES == set(OPERATOR_TAXONOMY.keys())


@pytest.mark.asyncio
async def test_simulate_502():
    flow = MockFlow()
    await apply_mutation(flow, {"operator": "Simulate502", "id": "m1"})
    assert flow.response.status_code == 502
    assert b"Bad Gateway" in flow.response.content


@pytest.mark.asyncio
async def test_simulate_status_codes():
    for op, code, expected_text in [
        ("Simulate500", 500, b"Internal Server Error"),
        ("Simulate503", 503, b"Service Unavailable"),
        ("Simulate404", 404, b"Not Found"),
        ("Simulate401", 401, b"Unauthorized"),
        ("Simulate403", 403, b"Forbidden"),
    ]:
        flow = MockFlow()
        await apply_mutation(flow, {"operator": op, "id": f"m_{op}"})
        assert flow.response.status_code == code
        assert expected_text in flow.response.content


@pytest.mark.asyncio
async def test_wrong_status_code():
    flow = MockFlow()
    await apply_mutation(
        flow, {"operator": "WrongStatusCode", "status_code": 418, "id": "m_tea"}
    )
    assert flow.response.status_code == 418


@pytest.mark.asyncio
async def test_malformed_json():
    flow = MockFlow()
    await apply_mutation(flow, {"operator": "MalformedJSON", "id": "m2"})
    with pytest.raises(json.JSONDecodeError):
        json.loads(flow.response.content)


@pytest.mark.asyncio
async def test_truncated_json():
    flow = MockFlow()
    await apply_mutation(flow, {"operator": "TruncatedJSON", "id": "m_trunc"})
    assert len(flow.response.content) > 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(flow.response.content)


@pytest.mark.asyncio
async def test_invalid_content_type():
    flow = MockFlow()
    await apply_mutation(
        flow,
        {"operator": "InvalidContentType", "content_type": "text/html", "id": "m_ct"},
    )
    assert flow.response.headers["Content-Type"] == "text/html"


@pytest.mark.asyncio
async def test_missing_required():
    flow = MockFlow()
    await apply_mutation(
        flow, {"operator": "MissingRequired", "target": "required_field", "id": "m3"}
    )
    body = json.loads(flow.response.content)
    assert "required_field" not in body
    assert body["id"] == 1


@pytest.mark.asyncio
async def test_type_mismatch():
    # Number to string
    flow = MockFlow(
        response=MockResponse(
            content=b'{"id": 42, "is_active": true, "label": "hello"}'
        )
    )
    await apply_mutation(
        flow, {"operator": "TypeMismatch", "target": "id", "id": "m_tm1"}
    )
    body = json.loads(flow.response.content)
    assert body["id"] == "mutated_string"

    # Bool to string
    flow2 = MockFlow(
        response=MockResponse(
            content=b'{"id": 42, "is_active": true, "label": "hello"}'
        )
    )
    await apply_mutation(
        flow2, {"operator": "TypeMismatch", "target": "is_active", "id": "m_tm2"}
    )
    body2 = json.loads(flow2.response.content)
    assert body2["is_active"] == "true"

    # String to int
    flow3 = MockFlow(
        response=MockResponse(
            content=b'{"id": 42, "is_active": true, "label": "hello"}'
        )
    )
    await apply_mutation(
        flow3, {"operator": "TypeMismatch", "target": "label", "id": "m_tm3"}
    )
    body3 = json.loads(flow3.response.content)
    assert body3["label"] == 99999


@pytest.mark.asyncio
async def test_null_violation():
    flow = MockFlow()
    await apply_mutation(
        flow, {"operator": "NullViolation", "target": "name", "id": "m_null"}
    )
    body = json.loads(flow.response.content)
    assert body["name"] is None


@pytest.mark.asyncio
async def test_enum_violation():
    flow = MockFlow()
    await apply_mutation(
        flow, {"operator": "EnumViolation", "target": "status", "id": "m_enum"}
    )
    body = json.loads(flow.response.content)
    assert body["status"] == "__INVALID_ENUM__"


@pytest.mark.asyncio
async def test_boundary_violation():
    flow = MockFlow()
    await apply_mutation(
        flow,
        {
            "operator": "BoundaryViolation",
            "target": "count",
            "invalid_value": -1,
            "id": "m_bv",
        },
    )
    body = json.loads(flow.response.content)
    assert body["count"] == -1


@pytest.mark.asyncio
async def test_undocumented_field_and_header():
    flow = MockFlow()
    await apply_mutation(flow, {"operator": "UndocumentedField", "id": "m_uf"})
    body = json.loads(flow.response.content)
    assert body["__mutant_undocumented"] is True

    await apply_mutation(
        flow,
        {
            "operator": "UndocumentedHeader",
            "header_name": "X-Custom",
            "header_value": "test",
            "id": "m_uh",
        },
    )
    assert flow.response.headers["X-Custom"] == "test"


@pytest.mark.asyncio
async def test_empty_body():
    flow = MockFlow()
    await apply_mutation(flow, {"operator": "EmptyBody", "id": "m_empty"})
    assert flow.response.content == b""


@pytest.mark.asyncio
async def test_version_and_resource_id():
    flow = MockFlow()
    await apply_mutation(
        flow, {"operator": "WrongVersionHeader", "version": "9.9.9", "id": "m_ver"}
    )
    assert flow.response.headers["X-API-Version"] == "9.9.9"
    assert flow.response.headers["X-Service-Version"] == "9.9.9"

    await apply_mutation(
        flow,
        {
            "operator": "WrongResourceId",
            "target": "id",
            "invalid_value": 777,
            "id": "m_res",
        },
    )
    body = json.loads(flow.response.content)
    assert body["id"] == 777


@pytest.mark.asyncio
async def test_pagination_and_array_mismatch():
    flow_pag = MockFlow(response=MockResponse(content=b'{"items": [1, 2], "total": 2}'))
    await apply_mutation(flow_pag, {"operator": "PaginationMismatch", "id": "m_pag"})
    body = json.loads(flow_pag.response.content)
    assert body["total"] == 999999

    flow_arr = MockFlow(response=MockResponse(content=b'{"items": [{"id": 1}]}'))
    await apply_mutation(flow_arr, {"operator": "ArrayLengthMismatch", "id": "m_arr"})
    body_arr = json.loads(flow_arr.response.content)
    assert len(body_arr["items"]) == 2
    assert body_arr["items"][1] == {"__mutant_extra_item": True}


@pytest.mark.asyncio
async def test_too_much_data():
    flow = MockFlow()
    await apply_mutation(flow, {"operator": "TooMuchData", "size": 500, "id": "m_big"})
    body = json.loads(flow.response.content)
    assert "__mutant_large_payload" in body
    assert len(body["__mutant_large_payload"]) == 500


@pytest.mark.asyncio
async def test_connection_drop_and_timeouts():
    flow_drop = MockFlow()
    await apply_mutation(flow_drop, {"operator": "ConnectionDrop", "id": "m_drop"})
    assert flow_drop.killed is True

    flow_todrop = MockFlow()
    await apply_mutation(
        flow_todrop, {"operator": "TimeoutThenDrop", "delay": 0.01, "id": "m_todrop"}
    )
    assert flow_todrop.killed is True

    flow_timeout = MockFlow()
    await apply_mutation(
        flow_timeout, {"operator": "Timeout", "delay": 0.01, "id": "m_to"}
    )
    assert flow_timeout.killed is False

    flow_slow = MockFlow()
    await apply_mutation(
        flow_slow, {"operator": "SlowResponse", "delay": 0.01, "id": "m_slow"}
    )
    assert flow_slow.killed is False


@pytest.mark.asyncio
async def test_non_json_response_handling():
    flow = MockFlow(response=MockResponse(content=b"not a valid json string"))
    # Should not raise exception, but gracefully pass through
    await apply_mutation(
        flow, {"operator": "MissingRequired", "target": "id", "id": "m_non_json"}
    )
    assert flow.response.content == b"not a valid json string"
