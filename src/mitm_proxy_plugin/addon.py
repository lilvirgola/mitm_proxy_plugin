import uuid
import json
import asyncio
import threading
from typing import Optional
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from mitmproxy import http, ctx

from mitm_proxy_plugin.core import SeededRNG, ExecutionLogger, RequestValidator
from mitm_proxy_plugin.openapi.parser import OpenAPIMatcher
from mitm_proxy_plugin.openapi.loader import load_spec
from mitm_proxy_plugin.mutations.operators import apply_mutation


# --- HTTP Control Plane for Dynamic Swapping ---
class ControlPlaneHandler(BaseHTTPRequestHandler):
    addon: Optional["OpenAPIMutationAddon"] = None  # Will be injected with the addon instance

    def do_POST(self):
        if self.addon is None:
            self.send_error(503, "Addon is not initialized")
            return

        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        
        if self.path == '/campaign':
            try:
                new_campaign = json.loads(post_data)
                with self.addon.state_lock:
                    self.addon.campaign = new_campaign
                    self.addon.campaign_stats = {"matched_requests": 0, "mutated_responses": 0, "blocked_invalid_requests": 0}
                    
                    if new_campaign.get("mode") == "single_mutant":
                        self.addon.active_mutant = new_campaign.get("mutant")
                        self.addon.active_operation_id = new_campaign.get("target", {}).get("operation_id")
                    elif new_campaign.get("mode") == "baseline":
                        self.addon.active_mutant = None
                        self.addon.active_operation_id = None
                
                self._send_json(200, {"status": "ok", "campaign_id": new_campaign.get("campaign_id")})
                ctx.log.info(f"[Control Plane] Campaign swapped to: {new_campaign.get('campaign_id')}")
            except Exception as e:
                self._send_json(400, {"error": str(e)})
                
        elif self.path == '/clear':
            with self.addon.state_lock:
                self.addon.campaign = None
                self.addon.active_mutant = None
                self.addon.active_operation_id = None
            self._send_json(200, {"status": "cleared"})
            ctx.log.info("[Control Plane] Campaign cleared (baseline mode)")
        else:
            self.send_error(404)

    def do_GET(self):
        if self.addon is None:
            self.send_error(503, "Addon is not initialized")
            return

        parsed = urlparse(self.path)

        if parsed.path == '/status':
            with self.addon.state_lock:
                status = {
                    "campaign_id": self.addon.campaign.get("campaign_id") if self.addon.campaign else None,
                    "active_mutant_id": self.addon.active_mutant.get("id") if self.addon.active_mutant else None,
                    "target_op": self.addon.active_operation_id,
                    "stats": self.addon.campaign_stats
                }
            self._send_json(200, status)
        elif parsed.path == '/drain':
            # RESTberus will call: GET /drain?seq=42
            query = parse_qs(parsed.query)
            last_seq = int(query.get('seq', [0])[0])
            
            logs = self.addon.logger.drain(last_seq)
            self._send_json(200, {"logs": logs, "current_seq": self.addon.logger.seq})
            
        else:
            self.send_error(404)

    def _send_json(self, code, data):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        # Route HTTP server logs to mitmproxy's logger
        ctx.log.info(f"[Control Plane] {format % args}")


class OpenAPIMutationAddon:
    def __init__(self):
        self.rng = SeededRNG()
        self.logger = ExecutionLogger()
        self.validator = RequestValidator()
        self.matcher = None
        
        # State variables (protected by lock for thread safety)
        self.state_lock = threading.Lock()
        self.campaign = None
        self.active_mutant = None
        self.active_operation_id = None
        self.campaign_stats = {
            "matched_requests": 0,
            "mutated_responses": 0,
            "blocked_invalid_requests": 0,
        }

    def load(self, loader):
        loader.add_option("openapi_spec", str, "", "Path to OpenAPI 3.0 JSON/YAML")
        loader.add_option("mutation_seed", int, 42, "Seed for deterministic RNG")
        loader.add_option("exec_log", str, "executions.jsonl", "Path to execution log")
        loader.add_option("campaign_file", str, "", "Path to initial campaign JSON file (optional)")
        loader.add_option("mutation_control_port", int, 8081, "Port for the dynamic mutation control plane API")

    def configure(self, updated):
        self.rng.set_seed(ctx.options.mutation_seed)
        self.logger.open(ctx.options.exec_log)
        ctx.log.info(f"Execution log will be written to: {ctx.options.exec_log}")

        # Load OpenAPI spec and compile routes (Required for fast matching)
        if ctx.options.openapi_spec:
            spec = load_spec(ctx.options.openapi_spec)
            self.matcher = OpenAPIMatcher(spec)
            ctx.log.info(f"Loaded OpenAPI spec and compiled routes.")
        else:
            ctx.log.warn("No OpenAPI spec provided. Mutation matching will be disabled.")

        # Load initial campaign from file (if provided at startup)
        if ctx.options.campaign_file:
            with open(ctx.options.campaign_file, "r") as f:
                initial_campaign = json.load(f)
                with self.state_lock:
                    self.campaign = initial_campaign
                    if initial_campaign.get("mode") == "single_mutant":
                        self.active_mutant = initial_campaign.get("mutant")
                        self.active_operation_id = initial_campaign.get("target", {}).get("operation_id")
            ctx.log.info(f"Loaded initial campaign: {self.campaign['campaign_id']}")

        # Start the HTTP Control Plane in a background thread
        ControlPlaneHandler.addon = self
        port = ctx.options.mutation_control_port
        
        def run_server():
            server = HTTPServer(("0.0.0.0", port), ControlPlaneHandler)
            ctx.log.info(f"[Control Plane] Listening on 0.0.0.0:{port}")
            server.serve_forever()
            
        threading.Thread(target=run_server, daemon=True).start()

    def request(self, flow: http.HTTPFlow):
        flow.metadata["request_id"] = str(uuid.uuid4())
        if not self.matcher: return
            
        op_id, operation = self.matcher.match(flow)
        if not op_id: return 
            
        flow.metadata["op_id"] = op_id
        
        with self.state_lock:
            current_campaign = self.campaign
            active_op_id = self.active_operation_id
            active_mutant = self.active_mutant

        if not current_campaign or current_campaign.get("mode") == "baseline":
            return

        # Validate Request
        error = self.validator.validate(flow, operation)
        if error:
            flow.response = http.Response.make(400, b'{"error": "Invalid Request"}', {"Content-Type": "application/json"})
            return

        if current_campaign.get("mode") == "single_mutant":
            if active_op_id and op_id == active_op_id:
                flow.metadata["active_mutant"] = active_mutant

    async def response(self, flow: http.HTTPFlow):
        if not flow.response: return

        mutant = flow.metadata.get("active_mutant")
        if not mutant: return

        # Apply the mutation asynchronously
        await apply_mutation(flow, mutant)
        
        with self.state_lock:
            campaign_id = self.campaign["campaign_id"] if self.campaign else "unknown"
            
        flow.response.headers["X-Campaign-Id"] = campaign_id
        flow.response.headers["X-Mutant-Id"] = mutant["id"]

        # Log to the in-memory buffer
        self.logger.log_execution(flow, mutant, campaign_id=campaign_id)

    def done(self):
        self.logger.close()

addons = [OpenAPIMutationAddon()]