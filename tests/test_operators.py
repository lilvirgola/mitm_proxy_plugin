import pytest
import json
from mitm_proxy_plugin.mutations.operators import apply_mutation

class MockResponse:
    def __init__(self, status_code=200, content=b'{"id": 1, "name": "test", "required_field": "value"}'):
        self.status_code = status_code
        self.content = content
        self.headers = {}

class MockFlow:
    def __init__(self, response=None):
        self.response = response or MockResponse()
        self.killed = False
        
    def kill(self):
        self.killed = True

@pytest.mark.asyncio
async def test_simulate_502():
    flow = MockFlow()
    await apply_mutation(flow, {"operator": "Simulate502", "id": "m1"})
    assert flow.response.status_code == 502
    assert b"Bad Gateway" in flow.response.content

@pytest.mark.asyncio
async def test_malformed_json():
    flow = MockFlow()
    await apply_mutation(flow, {"operator": "MalformedJSON", "id": "m2"})
    # Should not be valid JSON
    with pytest.raises(json.JSONDecodeError):
        json.loads(flow.response.content)

@pytest.mark.asyncio
async def test_missing_required():
    flow = MockFlow()
    await apply_mutation(flow, {"operator": "MissingRequired", "target": "required_field", "id": "m3"})
    
    body = json.loads(flow.response.content)
    assert "required_field" not in body
    assert body["id"] == 1 # Other fields remain

@pytest.mark.asyncio
async def test_connection_drop():
    flow = MockFlow()
    await apply_mutation(flow, {"operator": "ConnectionDrop", "id": "m4"})
    assert flow.killed is True