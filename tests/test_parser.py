from typing import cast

from mitmproxy.http import HTTPFlow

from mitm_proxy_plugin.openapi.parser import OpenAPIMatcher


class MockRequest:
    def __init__(self, method="GET", path="/api/items"):
        self.method = method
        self.path = path


class MockFlow:
    def __init__(self, method="GET", path="/api/items"):
        self.request = MockRequest(method, path)
        self.metadata = {}


def make_spec_with_base():
    return {
        "servers": [{"url": "http://localhost:8080/api/v1/orderservice"}],
        "paths": {
            "/orders/{id}": {"get": {"operationId": "getOrder"}},
            "/orders": {"post": {"operationId": "createOrder"}},
        },
    }


def make_spec_no_base():
    return {"paths": {"/items/{id}": {"get": {"operationId": "getItem"}}}}


def test_matcher_with_base_path():
    spec = make_spec_with_base()
    matcher = OpenAPIMatcher(spec)

    # Flow has the full base path + spec path
    flow = MockFlow("GET", "http://localhost:8080/api/v1/orderservice/orders/123")
    op_id, _ = matcher.match(cast(HTTPFlow, flow))
    assert op_id == "getOrder"
    assert flow.metadata.get("path_params") == {"id": "123"}


def test_matcher_relative_path():
    spec = make_spec_no_base()
    matcher = OpenAPIMatcher(spec)

    flow = MockFlow("GET", "/items/456")
    op_id, _ = matcher.match(cast(HTTPFlow, flow))
    assert op_id == "getItem"
    assert flow.metadata.get("path_params") == {"id": "456"}


def test_matcher_no_match():
    spec = make_spec_no_base()
    matcher = OpenAPIMatcher(spec)

    flow = MockFlow("GET", "/users/123")
    op_id, _ = matcher.match(cast(HTTPFlow, flow))
    assert op_id is None


def test_matcher_method_mismatch():
    spec = make_spec_no_base()
    matcher = OpenAPIMatcher(spec)

    # Spec has GET, flow is DELETE
    flow = MockFlow("DELETE", "/items/123")
    op_id, _ = matcher.match(cast(HTTPFlow, flow))
    assert op_id is None


def test_matcher_multiple_path_params():
    spec = {
        "paths": {
            "/api/v1/order/{orderId}/status/{statusCode}": {
                "get": {"operationId": "getOrderStatus"}
            }
        }
    }
    matcher = OpenAPIMatcher(spec)
    flow = MockFlow("GET", "/api/v1/order/ord-999/status/200")
    op_id, _ = matcher.match(cast(HTTPFlow, flow))
    assert op_id == "getOrderStatus"
    assert flow.metadata.get("path_params") == {"orderId": "ord-999", "statusCode": "200"}
