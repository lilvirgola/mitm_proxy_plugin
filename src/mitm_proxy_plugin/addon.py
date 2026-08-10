import uuid
import json
from mitmproxy import http, ctx

from mitm_proxy_plugin.core import SeededRNG, ExecutionLogger, RequestValidator
from mitm_proxy_plugin.openapi import load_spec, match_operation
from mitm_proxy_plugin.mutations import MutantCatalog, apply_mutation

class OpenAPIMutationAddon:
    def __init__(self):
        self.spec = None
        self.rng = SeededRNG()
        self.logger = ExecutionLogger()
        self.validator = RequestValidator()
        self.catalog = None
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
        loader.add_option("disabled_operators", str, "", "Comma-separated list of mutation operators to disable (e.g., Timeout,ConnectionDrop)")
        loader.add_option("campaign_file", str, "", "Path to campaign JSON file")

    def configure(self, updated):
        self.rng.set_seed(ctx.options.mutation_seed)
        self.logger.open(ctx.options.exec_log)
        ctx.log.info(f"Execution log will be written to: {ctx.options.exec_log}")
        # if there's a campaign file, load it and set the active mutant and operation_id
        if ctx.options.campaign_file:
            with open(ctx.options.campaign_file, "r") as f:
                self.campaign = json.load(f)

            if self.campaign.get("mode") == "single_mutant":
                self.active_mutant = self.campaign["mutant"]
                self.active_operation_id = self.campaign.get("target", {}).get("operation_id")

            ctx.log.info(
                f"Campaign mode enabled: {self.campaign['campaign_id']} "
                f"mode={self.campaign.get('mode')}"
            )
            return

        # else load the OpenAPI spec and generate the mutant catalog
        disabled_operators = {
            op.strip() 
            for op in ctx.options.disabled_operators.split(",") 
            if op.strip()
        }
        
        if disabled_operators:
            ctx.log.info(f"Disabled operators: {sorted(disabled_operators)}")
        
        self.spec = load_spec(ctx.options.openapi_spec)
        
        # Pass the set to the MutantCatalog
        self.catalog = MutantCatalog(
            self.spec, 
            self.rng, 
            disabled_operators=disabled_operators
        )
        self.catalog.generate()
        
        ctx.log.info(f"Loaded spec and generated {self.catalog.total_mutants()} total mutants.")

    def request(self, flow: http.HTTPFlow):
        flow.metadata["request_id"] = str(uuid.uuid4())
        if self.campaign:
            flow.metadata["campaign_id"] = self.campaign["campaign_id"]

        if not self.spec or not self.catalog: # Spec or catalog not loaded
            return  
        
        # Match Request to OpenAPI Operation
        op_id, operation = match_operation(self.spec, flow)
        if not op_id or not operation:
            return  # Unknown endpoint, forward normally
            
        flow.metadata["op_id"] = op_id
        
        # Validate Request
        error = self.validator.validate(flow, operation)
        if error:
            flow.response = http.Response.make(
                400, 
                f'{{"error": "Invalid Request", "details": "{error}"}}'.encode(),
                {"Content-Type": "application/json"}
            )
            return
        # If campaign mode is active, check if the request matches the active operation_id
        if self.campaign:
            if self.campaign.get("mode") == "baseline":
                return

            if self.active_operation_id and op_id == self.active_operation_id:
                self.campaign_stats["matched_requests"] += 1

            return
        # else assign Mutant for the Response Phase
        mutant = self.catalog.get_next_mutant(op_id)
        if mutant is None:
            return
        flow.metadata["active_mutant"] = mutant

    def response(self, flow: http.HTTPFlow):
        if not flow.response:
            return

        # If campaign mode is active, check if the request matches the active operation_id
        if self.campaign:
            campaign_id = self.campaign["campaign_id"]

            flow.response.headers["X-Campaign-Id"] = campaign_id

            if self.campaign.get("mode") == "baseline":
                return

            # Mutate only the target operation
            if self.active_operation_id:
                if flow.metadata.get("op_id") != self.active_operation_id:
                    return

            mutant = self.active_mutant

            if not mutant:
                return

            flow.response.headers["X-Mutant-Id"] = mutant["id"]

            apply_mutation(flow, mutant)

            self.campaign_stats["mutated_responses"] += 1

            self.logger.log_execution(
                flow,
                mutant,
                campaign_id=campaign_id,
            )
            return

        # else mutate based on the assigned mutant in the metadata
        mutant = flow.metadata.get("active_mutant")

        if not mutant:
            return

        flow.response.headers["X-Mutant-Id"] = mutant["id"]

        apply_mutation(flow, mutant)

        self.logger.log_execution(flow, mutant)

    def done(self):
        self.logger.close()

# Mitmproxy requires this global variable to load the addon
addons = [OpenAPIMutationAddon()]