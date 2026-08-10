"""
Shared pytest fixtures
"""
import pytest

class FakeResponse:
    def __init__(self, status_code: int = 200, content: bytes = b""):
        self.status_code = status_code
        self.content = content
        self.headers = {}


class FakeFlow:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.killed = False
        self.metadata = {}

    def kill(self):
        self.killed = True


@pytest.fixture
def fake_response():
    return FakeResponse()


@pytest.fixture
def fake_flow():
    return FakeFlow()


@pytest.fixture
def make_flow():
    def _make(content: bytes, status_code: int = 200):
        return FakeFlow(FakeResponse(status_code=status_code, content=content))
    return _make