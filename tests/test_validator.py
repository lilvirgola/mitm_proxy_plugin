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
    def __init__(self, request):
        self.request = request


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

