import pytest
import json
import threading
import urllib.request
from http.server import HTTPServer

# We import the handler and addon directly
from mitm_proxy_plugin.addon import ControlPlaneHandler, OpenAPIMutationAddon
from mitmproxy import ctx

# Mock ctx.log to prevent errors when running outside mitmproxy
class MockLog:
    def info(self, msg): pass
    def warn(self, msg): pass
    def error(self, msg): pass
ctx.log = MockLog()

@pytest.fixture
def running_control_plane():
    addon = OpenAPIMutationAddon()
    # Initialize state manually since we bypass mitmproxy's configure()
    addon.campaign = None
    addon.active_mutant = None
    addon.active_operation_id = None
    
    ControlPlaneHandler.addon = addon
    
    # Find a free port dynamically
    import socket
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    
    server = HTTPServer(("127.0.0.1", port), ControlPlaneHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    
    yield addon, port
    
    server.shutdown()

def test_swap_campaign_via_http(running_control_plane):
    addon, port = running_control_plane
    
    new_campaign = {
        "campaign_id": "c99",
        "mode": "single_mutant",
        "target": {"operation_id": "getItems"},
        "mutant": {"id": "m99", "operator": "Simulate502"}
    }
    
    # Send POST request to the control plane
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/campaign",
        data=json.dumps(new_campaign).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    
    with urllib.request.urlopen(req) as response:
        res_data = json.loads(response.read())
        
    assert res_data["status"] == "ok"
    assert res_data["campaign_id"] == "c99"
    
    # Verify the addon's internal state hot-swapped
    assert addon.campaign["campaign_id"] == "c99"
    assert addon.active_mutant["id"] == "m99"
    assert addon.active_operation_id == "getItems"

def test_get_status(running_control_plane):
    addon, port = running_control_plane
    
    # Set some state directly
    addon.campaign = {"campaign_id": "c1"}
    addon.active_mutant = {"id": "m1"}
    
    req = urllib.request.Request(f"http://127.0.0.1:{port}/status", method='GET')
    with urllib.request.urlopen(req) as response:
        res_data = json.loads(response.read())
        
    assert res_data["campaign_id"] == "c1"
    assert res_data["active_mutant_id"] == "m1"