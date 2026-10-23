import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from mitmproxy import ctx, http

from mitm_proxy_plugin.core import (
    ExecutionLogger,
    RequestValidator,
    SeededRNG,
    extract_trace_id,
)
from mitm_proxy_plugin.mutations.operators import apply_mutation
from mitm_proxy_plugin.openapi.loader import load_spec
from mitm_proxy_plugin.openapi.parser import OpenAPIMatcher


def _log_info(msg: str):
    log = getattr(ctx, "log", None)
    if log and hasattr(log, "info"):
        log.info(msg)


def _log_warn(msg: str):
    log = getattr(ctx, "log", None)
    if log and hasattr(log, "warning") or log and hasattr(log, "warn"):
        log.warning(msg)


def _log_error(msg: str):
    log = getattr(ctx, "log", None)
    if log and hasattr(log, "error"):
        log.error(msg)


# --- HTTP Control Plane for Dynamic Swapping ---
class ControlPlaneHandler(BaseHTTPRequestHandler):
    addon: Optional["OpenAPIMutationAddon"] = None

    def do_POST(self):
        if self.addon is None:
            self.send_error(503, "Addon is not initialized")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length).decode("utf-8")

        if self.path == "/campaign":
            try:
                new_campaign = json.loads(post_data)
                with self.addon.state_lock:
                    self.addon.campaign = new_campaign
                    self.addon.campaign_stats = {
                        "matched_requests": 0,
                        "mutated_responses": 0,
                        "blocked_invalid_requests": 0,
                    }

                    if new_campaign.get("mode") == "single_mutant":
                        self.addon.active_mutant = new_campaign.get("mutant")
                        self.addon.active_operation_id = new_campaign.get(
                            "target", {}
                        ).get("operation_id")
                        self.addon._campaign_start_system_id = new_campaign.get(
                            "start_interaction_id", 0
                        )
                    else:
                        self.addon.active_mutant = None
                        self.addon.active_operation_id = None
                        self.addon._campaign_start_system_id = 0

                    # Reset mutant interaction counter for the new campaign
                    with self.addon._mutant_counter_lock:
                        self.addon.mutant_interaction_counter = 0

                self._send_json(
                    200,
                    {"status": "ok", "campaign_id": new_campaign.get("campaign_id")},
                )
                _log_info(
                    f"[Control Plane] Campaign swapped to: {new_campaign.get('campaign_id')}"
                )
            except Exception as e:  # noqa: BLE001
                self._send_json(400, {"error": str(e)})

        elif self.path == "/clear":
            with self.addon.state_lock:
                self.addon.campaign = None
                self.addon.active_mutant = None
                self.addon.active_operation_id = None
                self.addon._campaign_start_system_id = 0
                with self.addon._mutant_counter_lock:
                    self.addon.mutant_interaction_counter = 0
            self._send_json(200, {"status": "cleared"})
            _log_info("[Control Plane] Campaign cleared (baseline mode)")
        else:
            self.send_error(404)

    def do_GET(self):
        if self.addon is None:
            self.send_error(503, "Addon is not initialized")
            return

        parsed = urlparse(self.path)

        if parsed.path == "/status":
            with self.addon.state_lock:
                status = {
                    "campaign_id": self.addon.campaign.get("campaign_id")
                    if self.addon.campaign
                    else None,
                    "active_mutant_id": self.addon.active_mutant.get("id")
                    if self.addon.active_mutant
                    else None,
                    "target_op": self.addon.active_operation_id,
                    "stats": dict(self.addon.campaign_stats),
                }
            self._send_json(200, status)
        elif parsed.path == "/drain":
            query = parse_qs(parsed.query)
            last_seq = int(query.get("seq", [0])[0])
            entry_type = query.get("type", [None])[0]

            logs = self.addon.logger.drain(last_seq, entry_type)
            self._send_json(200, {"logs": logs, "current_seq": self.addon.logger.seq})
        else:
            self.send_error(404)

    def _send_json(self, code: int, data: dict):
        self.send_response(code)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, format, *args):
        _log_info(f"[Control Plane] {format % args}")


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
        self._server: HTTPServer | None = None

        # Local interaction counter (Service IFE)
        self._local_interaction_counter = 0
        self._local_counter_lock = threading.Lock()

        # System interaction counter (System IFE) - Only used if IS_EDGE_PROXY=true
        self._system_interaction_counter = 0
        self._system_counter_lock = threading.Lock()

        # Store the baseline provided by the RunManager
        self._campaign_start_system_id = 0

        # mutation-specific interaction counter (resets on new campaign)
        self.mutant_interaction_counter = 0
        self._mutant_counter_lock = threading.Lock()

    def _next_local_interaction_id(self) -> int:
        with self._local_counter_lock:
            self._local_interaction_counter += 1
            return self._local_interaction_counter

    def _next_system_interaction_id(self) -> int:
        with self._system_counter_lock:
            self._system_interaction_counter += 1
            return self._system_interaction_counter

    def _next_mutant_interaction_id(self) -> int:
        with self._mutant_counter_lock:
            self.mutant_interaction_counter += 1
            return self.mutant_interaction_counter

    def load(self, loader):
        loader.add_option("openapi_spec", str, "", "Path to OpenAPI 3.0 JSON/YAML")
        loader.add_option("mutation_seed", int, 42, "Seed for deterministic RNG")
        loader.add_option("exec_log", str, "executions.jsonl", "Path to execution log")
        loader.add_option(
            "campaign_file", str, "", "Path to initial campaign JSON file (optional)"
        )
        loader.add_option(
            "mutation_control_port",
            int,
            8081,
            "Port for the dynamic mutation control plane API",
        )
        loader.add_option(
            "service_name",
            str,
            "unknown",
            "Name of the service this proxy is attached to",
        )

    def configure(self, updated):
        seed = getattr(ctx.options, "mutation_seed", 42)
        exec_log = getattr(ctx.options, "exec_log", "executions.jsonl")
        spec_path = getattr(ctx.options, "openapi_spec", "")
        campaign_file = getattr(ctx.options, "campaign_file", "")
        port = getattr(ctx.options, "mutation_control_port", 8081)

        self.rng.set_seed(seed)
        self.logger.open(exec_log)

        opt_service = getattr(ctx.options, "service_name", "unknown")
        self.service_name = (
            opt_service
            if opt_service != "unknown"
            else os.environ.get("SERVICE_NAME", "unknown")
        )
        _log_info(
            f"Execution log will be written to: {exec_log} for service: {self.service_name}"
        )

        if not spec_path or not os.path.exists(spec_path):
            _log_info(
                f"[Mutation Addon] No OpenAPI spec at '{spec_path}'. "
                f"Running in OBSERVER mode (passthrough, no mutations)."
            )
            self.matcher = None
            self.campaign = None
            self._observer_mode = True
        else:
            self._observer_mode = False
            spec = load_spec(spec_path)
            self.matcher = OpenAPIMatcher(spec)
            self.validator.set_spec(spec)
            _log_info(
                f"Loaded OpenAPI spec and compiled routes for {self.service_name}."
            )

        if not campaign_file:
            campaign_file = os.environ.get("CAMPAIGN_CONFIG_PATH", "")

        if campaign_file and os.path.exists(campaign_file):
            try:
                with open(campaign_file, "r", encoding="utf-8") as f:
                    initial_campaign = json.load(f)
                    with self.state_lock:
                        self.campaign = initial_campaign
                        if initial_campaign.get("mode") == "single_mutant":
                            self.active_mutant = initial_campaign.get("mutant")
                            self.active_operation_id = initial_campaign.get(
                                "target", {}
                            ).get("operation_id")
                            self._campaign_start_system_id = initial_campaign.get(
                                "start_interaction_id", 0
                            )
                            with self._mutant_counter_lock:
                                self.mutant_interaction_counter = 0
                _log_info(
                    f"Loaded initial campaign: {self.campaign.get('campaign_id')}"
                )
            except Exception as e:  # noqa: BLE001
                _log_warn(
                    f"Failed to load initial campaign file '{campaign_file}': {e}"
                )


        # Ensure control plane HTTP server is started (in mutator AND observer modes)
        ControlPlaneHandler.addon = self
        if self._server is None:
            try:
                server = HTTPServer(("0.0.0.0", port), ControlPlaneHandler)
                self._server = server
                threading.Thread(target=server.serve_forever, daemon=True).start()
                _log_info(f"[Control Plane] Listening on 0.0.0.0:{port}")
            except Exception as e:  # noqa: BLE001
                _log_error(f"[Control Plane] Failed to bind to port {port}: {e}")

    def request(self, flow: http.HTTPFlow):
        request = getattr(flow, "request", None)
        if not request:
            return

        headers = getattr(request, "headers", None)
        if headers is None:
            request.headers = {}
            headers = request.headers

        # 1. Get existing trace ID or generate a new UUID if missing
        raw_corr_id = (
            extract_trace_id(flow) or headers.get("x-request-id") or str(uuid.uuid4())
        )

        # 2. Clean the ID to be a valid 32-char W3C trace-id
        clean_trace_id = raw_corr_id.replace("-", "")[:32].ljust(32, "0")

        # 3. Generate a new 16-char hex parent-id for this specific hop
        parent_id = uuid.uuid4().hex[:16]

        # 4. Inject trace headers if missing
        if "x-request-id" not in headers:
            headers["x-request-id"] = raw_corr_id
        if "x-b3-traceid" not in headers:
            headers["x-b3-traceid"] = clean_trace_id
        if "traceparent" not in headers:
            headers["traceparent"] = f"00-{clean_trace_id}-{parent_id}-01"

        # 5. Metadata for logging
        flow.metadata["trace_id"] = raw_corr_id
        flow.metadata["request_id"] = raw_corr_id
        flow.metadata["role"] = "observer"

        # Edge Proxy / System interaction ID handling
        is_edge = os.environ.get("IS_EDGE_PROXY", "false").lower() == "true"
        system_interaction_id = headers.get("x-restberus-system-interaction")

        if system_interaction_id and system_interaction_id.isdigit():
            # We are a downstream proxy, read the propagated global counter
            flow.metadata["system_interaction_id"] = int(system_interaction_id)
        elif is_edge:
            # We are the edge proxy, generate the global counter and stamp it
            sys_id = self._next_system_interaction_id()
            flow.metadata["system_interaction_id"] = sys_id
            headers["x-restberus-system-interaction"] = str(sys_id)
        else:
            flow.metadata["system_interaction_id"] = None

        # Sequential index of this interaction within the run (LOCAL to this service)
        flow.metadata["interaction_id"] = self._next_local_interaction_id()

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
            campaign_start_id = self._campaign_start_system_id

        if not current_campaign or current_campaign.get("mode") == "baseline":
            return

        if (
            current_campaign.get("mode") == "single_mutant"
            and active_op_id
            and op_id == active_op_id
        ):
            policy = current_campaign.get("policy", {}) or {}
            if policy.get("mutate_valid_requests_only", True) and operation:
                err = self.validator.validate(flow, operation)
                if err:
                    with self.state_lock:
                        self.campaign_stats["blocked_invalid_requests"] += 1
                    _log_info(f"Skipping mutation for invalid request: {err}")
                    return

            flow.metadata["active_mutant"] = active_mutant
            flow.metadata["role"] = "mutator"
            flow.metadata["campaign_start_system_id"] = campaign_start_id
            flow.metadata["mutant_interaction_id"] = self._next_mutant_interaction_id()
            with self.state_lock:
                self.campaign_stats["matched_requests"] += 1

    async def response(self, flow: http.HTTPFlow):
        response = getattr(flow, "response", None)
        if not response:
            return

        role = flow.metadata.get("role", "observer")
        headers = getattr(response, "headers", {}) or {}

        downstream_mutant_id = headers.get("X-Mutant-Id")
        downstream_campaign_id = headers.get("X-Campaign-Id")

        if downstream_mutant_id:
            flow.metadata["observed_mutant_id"] = downstream_mutant_id
            flow.metadata["observed_campaign_id"] = downstream_campaign_id
            req_path = (
                getattr(flow.request, "path", "")
                if getattr(flow, "request", None)
                else ""
            )
            status = getattr(response, "status_code", "")
            _log_info(
                f"[{role.capitalize()}] Detected propagated mutation '{downstream_mutant_id}' "
                f"in response to {req_path} (Status: {status})"
            )

        # Always log observation
        self.logger.log_observation(flow, self.service_name, role)

        # If mutator, apply mutation
        mutant = flow.metadata.get("active_mutant")
        if mutant:
            await apply_mutation(flow, mutant)

            with self.state_lock:
                self.campaign_stats["mutated_responses"] += 1
                campaign_id = (
                    self.campaign.get("campaign_id", "unknown")
                    if self.campaign
                    else "unknown"
                )

            resp_headers = getattr(response, "headers", None)
            if resp_headers is not None:
                resp_headers["X-Campaign-Id"] = campaign_id
                resp_headers["X-Mutant-Id"] = mutant.get("id", "")

            self.logger.log_execution(flow, mutant, campaign_id=campaign_id)

    def done(self):
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:  # noqa: BLE001, S110
                pass
            self._server = None
        self.logger.close()


addons = [OpenAPIMutationAddon()]
