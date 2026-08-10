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