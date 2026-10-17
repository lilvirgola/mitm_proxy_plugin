import uuid
import json
import asyncio
import threading
import os
import time
from typing import Optional
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from mitmproxy import http, ctx

from mitm_proxy_plugin.core import SeededRNG, ExecutionLogger, RequestValidator, extract_trace_id
from mitm_proxy_plugin.openapi.parser import OpenAPIMatcher
from mitm_proxy_plugin.openapi.loader import load_spec
from mitm_proxy_plugin.mutations.operators import apply_mutation


# --- HTTP Control Plane for Dynamic Swapping ---
class ControlPlaneHandler(BaseHTTPRequestHandler):
    addon: Optional["OpenAPIMutationAddon"] = None

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
            query = parse_qs(parsed.query)
            last_seq = int(query.get('seq', [0])[0])
            entry_type = query.get('type', [None])[0]  # Support filtering by "mutation" or "observation"
            
            logs = self.addon.logger.drain(last_seq, entry_type)
            self._send_json(200, {"logs": logs, "current_seq": self.addon.logger.seq})
        else:
            self.send_error(404)

    def _send_json(self, code, data):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        ctx.log.info(f"[Control Plane] {format % args}")


class OpenAPIMutationAddon:
    def __init__(self):
        self.rng = SeededRNG()
        self.logger = ExecutionLogger()
        self.validator = RequestValidator()
        self.matcher = None
        
        self.state_lock = threading.Lock()
        self.campaign = None
        self.active_mutant = None
        self.active_operation_id = None
        self.campaign_stats = {
            "matched_requests": 0,
            "mutated_responses": 0,
            "blocked_invalid_requests": 0,
        }
        self._observer_mode = False
        self.service_name = "unknown"
        self._interaction_counter = 0
        self._counter_lock = threading.Lock()

    def _next_interaction_id(self) -> int:
        with self._counter_lock:
            self._interaction_counter += 1
            return self._interaction_counter

    def load(self, loader):
        loader.add_option("openapi_spec", str, "", "Path to OpenAPI 3.0 JSON/YAML")
        loader.add_option("mutation_seed", int, 42, "Seed for deterministic RNG")
        loader.add_option("exec_log", str, "executions.jsonl", "Path to execution log")
        loader.add_option("campaign_file", str, "", "Path to initial campaign JSON file (optional)")
        loader.add_option("mutation_control_port", int, 8081, "Port for the dynamic mutation control plane API")
        loader.add_option("service_name", str, "unknown", "Name of the service this proxy is attached to")

    def configure(self, updated):
        self.rng.set_seed(ctx.options.mutation_seed)
        self.logger.open(ctx.options.exec_log)
        
        # Use mitmproxy option, fallback to environment variable
        self.service_name = ctx.options.service_name if ctx.options.service_name != "unknown" else os.environ.get("SERVICE_NAME", "unknown")
        ctx.log.info(f"Execution log will be written to: {ctx.options.exec_log} for service: {self.service_name}")
        
        spec_path = ctx.options.openapi_spec

        if not spec_path or not os.path.exists(spec_path):
            ctx.log.info(
                f"[Mutation Addon] No OpenAPI spec at '{spec_path}'. "
                f"Running in OBSERVER mode (passthrough, no mutations)."
            )
            self.matcher = None
            self.campaign = None
            self._observer_mode = True
            return

        self._observer_mode = False
        spec = load_spec(spec_path)
        self.matcher = OpenAPIMatcher(spec)
        ctx.log.info(f"Loaded OpenAPI spec and compiled routes for {self.service_name}.")

        if ctx.options.campaign_file:
            with open(ctx.options.campaign_file, "r") as f:
                initial_campaign = json.load(f)
                with self.state_lock:
                    self.campaign = initial_campaign
                    if initial_campaign.get("mode") == "single_mutant":
                        self.active_mutant = initial_campaign.get("mutant")
                        self.active_operation_id = initial_campaign.get("target", {}).get("operation_id")
            ctx.log.info(f"Loaded initial campaign: {self.campaign['campaign_id']}")

        ControlPlaneHandler.addon = self
        port = ctx.options.mutation_control_port
        
        def run_server():
            server = HTTPServer(("0.0.0.0", port), ControlPlaneHandler)
            ctx.log.info(f"[Control Plane] Listening on 0.0.0.0:{port}")
            server.serve_forever()
            
        threading.Thread(target=run_server, daemon=True).start()

    def request(self, flow: http.HTTPFlow):
        # 1. Extract the propagated trace ID FIRST
        trace_id = extract_trace_id(flow)
        flow.metadata["trace_id"] = trace_id
        
        # 2. Use the propagated header as request_id if it exists, otherwise generate one
        header_req_id = flow.request.headers.get("x-request-id")
        if header_req_id:
            flow.metadata["request_id"] = header_req_id
        else:
            flow.metadata["request_id"] = trace_id or str(uuid.uuid4())

        # Default role is observer
        flow.metadata["role"] = "observer"

        if self._observer_mode or not self.matcher:
            return
            
        op_id, operation = self.matcher.match(flow)
        if not op_id: 
            return 
            
        flow.metadata["op_id"] = op_id
        
        with self.state_lock:
            current_campaign = self.campaign
            active_op_id = self.active_operation_id
            active_mutant = self.active_mutant

        if not current_campaign or current_campaign.get("mode") == "baseline":
            return

        if current_campaign.get("mode") == "single_mutant":
            if active_op_id and op_id == active_op_id:
                flow.metadata["active_mutant"] = active_mutant
                flow.metadata["role"] = "mutator"

        # Sequential index of this interaction within the run (LOCAL to this proxy)
        flow.metadata["interaction_id"] = self._next_interaction_id()

    async def response(self, flow: http.HTTPFlow):
        if not flow.response: 
            return

        role = flow.metadata.get("role", "observer")
        
        # Check if this response contains mutation headers from a DOWNSTREAM service
        downstream_mutant_id = flow.response.headers.get("X-Mutant-Id")
        downstream_campaign_id = flow.response.headers.get("X-Campaign-Id")

        if downstream_mutant_id:
            # We observed a propagated mutation! Store it in metadata for the logger
            flow.metadata["observed_mutant_id"] = downstream_mutant_id
            flow.metadata["observed_campaign_id"] = downstream_campaign_id
            ctx.log.info(f"[{role.capitalize()}] Detected propagated mutation '{downstream_mutant_id}' in response to {flow.request.path} (Status: {flow.response.status_code})")
        
        # ALWAYS log the observation for this traffic (whether we mutated it or just observed it)
        self.logger.log_observation(flow, self.service_name, role)

        # If WE are the mutator, apply the mutation and stamp our headers
        mutant = flow.metadata.get("active_mutant")
        if mutant:
            await apply_mutation(flow, mutant)
            
            with self.state_lock:
                campaign_id = self.campaign["campaign_id"] if self.campaign else "unknown"
            
            # Stamp headers so upstream services can see OUR mutation
            flow.response.headers["X-Campaign-Id"] = campaign_id
            flow.response.headers["X-Mutant-Id"] = mutant["id"]

            # Log the specific execution details
            self.logger.log_execution(flow, mutant, campaign_id=campaign_id)

    def done(self):
        self.logger.close()

addons = [OpenAPIMutationAddon()]