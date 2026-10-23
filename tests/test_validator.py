from mitmproxy.http import HTTPFlow

from mitm_proxy_plugin.core.validator import RequestValidator


class FakeRequest:
    def __init__(self, method="GET", path="/api/items", query=None, content=b""):
        self.method = method
        self.path = path
        self.query = query or {}
        self.content = content
        self.headers = {}


class FakeFlow(HTTPFlow):
    def __init__(self, request, metadata=None):
        self.request = request
        self.metadata = metadata or {}


def make_operation():
    return {
        "parameters": [
            {
                "name": "page",
                "in": "query",
                "required": False,
                "schema": {"type": "integer"},
            }
        ],
    }


def test_valid_request():
    validator = RequestValidator()
    flow = FakeFlow(FakeRequest(query={"page": "0"}))
    error = validator.validate(flow, make_operation())
    assert error is None


def test_invalid_query_param():
    validator = RequestValidator()
    flow = FakeFlow(FakeRequest(query={"page": "abc"}))
    error = validator.validate(flow, make_operation())
    assert error is not None
    assert "page" in error


def test_valid_request_body_with_ref():
    spec = {
        "openapi": "3.0.0",
        "components": {
            "schemas": {
                "UserDto": {
                    "type": "object",
                    "properties": {
                        "username": {"type": "string"},
                        "password": {"type": "string"},
                    },
                    "required": ["username"],
                }
            }
        },
    }
    operation = {
        "operationId": "login",
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/UserDto"}
                }
            }
        },
    }
    validator = RequestValidator(spec=spec)
    flow = FakeFlow(
        FakeRequest(
            method="POST",
            path="/login",
            content=b'{"username": "alice", "password": "secret"}',
        )
    )
    error = validator.validate(flow, operation)
    assert error is None


def test_invalid_request_body_with_ref():
    spec = {
        "openapi": "3.0.0",
        "components": {
            "schemas": {
                "UserDto": {
                    "type": "object",
                    "properties": {
                        "username": {"type": "string"},
                    },
                    "required": ["username"],
                }
            }
        },
    }
    operation = {
        "operationId": "login",
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/UserDto"}
                }
            }
        },
    }
    validator = RequestValidator(spec=spec)
    flow = FakeFlow(
        FakeRequest(
            method="POST",
            path="/login",
            content=b'{"email": "alice@example.com"}',
        )
    )
    error = validator.validate(flow, operation)
    assert error is not None
    assert "username" in error


def test_invalid_json_body():
    validator = RequestValidator()
    operation = {
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"type": "object"}
                }
            }
        }
    }
    flow = FakeFlow(FakeRequest(method="POST", path="/test", content=b"not json"))
    error = validator.validate(flow, operation)
    assert error is not None
    assert "Invalid JSON" in error


def test_valid_path_param_from_metadata():
    validator = RequestValidator()
    operation = {
        "operationId": "verifyCode",
        "parameters": [
            {
                "name": "verifyCode",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            }
        ],
    }
    flow = FakeFlow(
        FakeRequest(method="GET", path="/api/v1/verifycode/verify/ABCD"),
        metadata={"path_params": {"verifyCode": "ABCD"}},
    )
    error = validator.validate(flow, operation)
    assert error is None


def test_invalid_path_param_type():
    validator = RequestValidator()
    operation = {
        "operationId": "getOrder",
        "parameters": [
            {
                "name": "orderId",
                "in": "path",
                "required": True,
                "schema": {"type": "integer"},
            }
        ],
    }
    flow = FakeFlow(
        FakeRequest(method="GET", path="/api/v1/orders/not_an_int"),
        metadata={"path_params": {"orderId": "not_an_int"}},
    )
    error = validator.validate(flow, operation)
    assert error is not None
    assert "Invalid type for path parameter: orderId" in error


def test_header_param_validation():
    validator = RequestValidator()
    operation = {
        "parameters": [
            {
                "name": "X-API-Key",
                "in": "header",
                "required": True,
                "schema": {"type": "string"},
            }
        ],
    }
    req_missing = FakeRequest(method="GET", path="/test")
    flow_missing = FakeFlow(req_missing)
    error = validator.validate(flow_missing, operation)
    assert error is not None
    assert "Missing required header parameter: X-API-Key" in error

    req_valid = FakeRequest(method="GET", path="/test")
    req_valid.headers = {"X-API-Key": "secret123"}
    flow_valid = FakeFlow(req_valid)
    assert validator.validate(flow_valid, operation) is None

