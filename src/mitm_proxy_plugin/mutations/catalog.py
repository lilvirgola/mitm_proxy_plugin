"""
this class is used for managing the catalog of mutants for the MITM Proxy plugin. 
"""
from .taxonomy import enrich_mutant
import re


def _sanitize_id(raw: str) -> str:
    sanitized = raw.replace("/", "_")
    sanitized = sanitized.replace("{", "")
    sanitized = sanitized.replace("}", "")
    sanitized = sanitized.replace(" ", "_")
    sanitized = sanitized.replace(":", "_")
    sanitized = sanitized.replace("?", "_")
    sanitized = sanitized.replace("&", "_")
    sanitized = sanitized.replace("=", "_")
    # Collapse multiple underscores
    sanitized = re.sub(r"_+", "_", sanitized)
    # Remove leading/trailing underscores
    sanitized = sanitized.strip("_")
    return sanitized


class MutantCatalog:
    def __init__(self, spec: dict, rng, disabled_operators=None):
        self.spec = spec
        self.rng = rng
        self.catalog = {}
        self.queues = {}
        self.disabled_operators = disabled_operators or set()

    # just a helper to get the total number of mutants across all operations
    def total_mutants(self) -> int:
        return sum(len(v) for v in self.catalog.values())

    # This method generates mutants for each operation in the OpenAPI spec and populates the catalog
    def generate(self):
        # foreach path
        for path, path_item in self.spec.get("paths", {}).items():
            # foreach operation
            for method, operation in path_item.items():
                # we only care about standard HTTP methods, or at least i think #TODO: maybe we should also consider "head", "options", "trace" etc. but for now let's just focus on the main ones
                if method not in ["get", "post", "put", "delete", "patch"]:
                    continue
                # get the operationId, or generate one if missing
                raw_op_id = operation.get("operationId", f"{method}_{path}")
                op_id = _sanitize_id(raw_op_id)
                self.catalog[op_id] = []

                # let's add generic taxonomy mutants for every operation
                self._add_common_mutants(op_id)

                # then schema-specific mutants
                schema = self._get_response_schema(operation)
                if schema:
                    self._add_schema_mutants(op_id, schema)

                # finnaly initialize deterministic shuffled queue                
                queue = self.catalog[op_id].copy()
                self.rng.shuffle(queue)
                self.queues[op_id] = queue

    
    # Common mutants

    def _add_common_mutants(self, op_id: str):
        
        ## Service Description Fault > Description Incorrect > Format Fault
        ### Malformed JSON
        self._add_mutant(
            op_id,
            {
                "id": f"{op_id}_Desc_Format_MalformedJSON",
                "operator": "MalformedJSON",
            },
        )
        ### Invalid Content-Type
        self._add_mutant(
            op_id,
            {
                "id": f"{op_id}_Desc_Format_InvalidContentType",
                "operator": "InvalidContentType",
                "content_type": "text/plain",
            },
        )

        
        ## Service Description Fault > Service/Description Mismatch
        ### Undocumented Field
        self._add_mutant(
            op_id,
            {
                "id": f"{op_id}_Desc_Mismatch_UndocumentedField",
                "operator": "UndocumentedField",
            },
        )
        ### Undocumented Header
        self._add_mutant(
            op_id,
            {
                "id": f"{op_id}_Desc_Mismatch_UndocumentedHeader",
                "operator": "UndocumentedHeader",
            },
        )

        
        ## Execution Fault > Incorrect Result > Wrong Result Code
        ### Wrong Status Code
        self._add_mutant(
            op_id,
            {
                "id": f"{op_id}_Exec_WrongStatusCode",
                "operator": "WrongStatusCode",
                "status_code": 400,
            },
        )

        
        ## Execution Fault > Incorrect Result > Service Faulty
        ### Internal Server Error
        self._add_mutant(
            op_id,
            {
                "id": f"{op_id}_Exec_InternalServerError",
                "operator": "Simulate500",
            },
        )

        
        ## Execution Fault > Incorrect Result > Data Incomplete
        ### Empty Body
        self._add_mutant(
            op_id,
            {
                "id": f"{op_id}_Exec_EmptyBody",
                "operator": "EmptyBody",
            },
        )

        
        ## Service Deployment Fault > Required Resource Missing
        ### Simulate 503 Service Unavailable
        self._add_mutant(
            op_id,
            {
                "id": f"{op_id}_Deploy_503",
                "operator": "Simulate503",
            },
        )

        
        ## Service Deployment Fault > Wrong Configuration
        ### Simulate 502 Bad Gateway
        self._add_mutant(
            op_id,
            {
                "id": f"{op_id}_Deploy_502",
                "operator": "Simulate502",
            },
        )

        
        ## Discovery Fault > No Service Found
        ### Simulate 404 Not Found
        self._add_mutant(
            op_id,
            {
                "id": f"{op_id}_Disc_404",
                "operator": "Simulate404",
            },
        )

        
        ## Discovery Fault > Wrong Service Found > Wrong Version
        ### Simulate Wrong Version Header
        self._add_mutant(
            op_id,
            {
                "id": f"{op_id}_Disc_WrongVersion",
                "operator": "WrongVersionHeader",
                "version": "0.0.0-mutated",
            },
        )

        
        ## Connection Fault > Connection Disruption > Connection Interrupted
        ### Drop Connection
        self._add_mutant(
            op_id,
            {
                "id": f"{op_id}_Conn_Drop",
                "operator": "ConnectionDrop",
            },
        )

        
        ## Connection Fault > Timed Out
        ### add a mutant that simulates a timeout by delaying the response
        self._add_mutant(
            op_id,
            {
                "id": f"{op_id}_Conn_Timeout",
                "operator": "Timeout",
                "delay": 10,
            },
        )

        
        ## Connection Fault > Connection Performance > Data Transmission Too Slow
        ### add a mutant that simulates a slow response by delaying the response
        self._add_mutant(
            op_id,
            {
                "id": f"{op_id}_Conn_SlowResponse",
                "operator": "SlowResponse",
                "delay": 2,
            },
        )

        
        ## Connection Fault > Connection Performance > Too Much Data
        ### add a mutant that simulates sending too much data (100000 is arbitrary, but should be enough to trigger issues in most cases)
        self._add_mutant(
            op_id,
            {
                "id": f"{op_id}_Conn_TooMuchData",
                "operator": "TooMuchData",
                "size": 100_000,
            },
        )

    
    # Schema-specific mutants
    def _add_schema_mutants(self, op_id: str, schema: dict):
        if schema.get("type") != "object":
            return

        props = schema.get("properties", {})
        required = schema.get("required", [])

        
        ## Service Description Fault > Description Incorrect > Content Fault
        ### Missing required field
        
        for field in required:
            self._add_mutant(
                op_id,
                {
                    "id": f"{op_id}_Desc_Content_MissingRequired_{field}",
                    "operator": "MissingRequired",
                    "target": field,
                },
            )

        if not props:
            return

        first_prop = next(iter(props))

        
        ## Service Description Fault > Description Incorrect > Content Fault
        ### Wrong type
        
        self._add_mutant(
            op_id,
            {
                "id": f"{op_id}_Desc_Content_TypeMismatch_{first_prop}",
                "operator": "TypeMismatch",
                "target": first_prop,
            },
        )

        
        ## Execution Fault > Incorrect Result > Data Incomplete
        ### Null where null is *probably* not expected ( we don't have a perfect way to know if null is expected or not, but we can check the "nullable" property in the schema if it exists )
        
        first_prop_schema = props.get(first_prop, {})
        if not first_prop_schema.get("nullable", False):
            self._add_mutant(
                op_id,
                {
                    "id": f"{op_id}_Exec_DataIncomplete_NullViolation_{first_prop}",
                    "operator": "NullViolation",
                    "target": first_prop,
                },
            )

        
        ## Discovery Fault > Routing Faulty
        ### Wrong resource id
        
        if "id" in props:
            self._add_mutant(
                op_id,
                {
                    "id": f"{op_id}_Disc_Routing_WrongResourceId",
                    "operator": "WrongResourceId",
                    "target": "id",
                    "invalid_value": 999999,
                },
            )

            if first_prop != "id":
                self._add_mutant(
                    op_id,
                    {
                        "id": f"{op_id}_Desc_Content_TypeMismatch_id",
                        "operator": "TypeMismatch",
                        "target": "id",
                    },
                )

        
        ## Schema-aware content faults
        
        for field, field_schema in props.items():
            if not isinstance(field_schema, dict):
                continue

            # Enum violation
            if field_schema.get("enum"):
                self._add_mutant(
                    op_id,
                    {
                        "id": f"{op_id}_Desc_Content_EnumViolation_{field}",
                        "operator": "EnumViolation",
                        "target": field,
                        "invalid_value": "__INVALID_ENUM__",
                    },
                )

            ### Numeric boundary violation
            if field_schema.get("type") in {"integer", "number"}:
                # let's try to generate a value that is outside the defined boundaries if they exist
                if "minimum" in field_schema: # eg. if mininum is defined, we can generate a value that is less than minimum
                    invalid_value = field_schema["minimum"] - 1
                    self._add_mutant(
                        op_id,
                        {
                            "id": f"{op_id}_Desc_Content_BoundaryViolation_{field}",
                            "operator": "BoundaryViolation",
                            "target": field,
                            "invalid_value": invalid_value,
                        },
                    )

                elif "maximum" in field_schema: # eg. if maximum is defined, we can generate a value that is greater than maximum
                    invalid_value = field_schema["maximum"] + 1
                    self._add_mutant(
                        op_id,
                        {
                            "id": f"{op_id}_Desc_Content_BoundaryViolation_{field}",
                            "operator": "BoundaryViolation",
                            "target": field,
                            "invalid_value": invalid_value,
                        },
                    )

        
        ## Composition Fault > Combined Functionality Faulty
        ### Pagination mismatch
        
        total_fields = {"totalElements", "total", "totalCount"}
        array_fields = [
            field
            for field, field_schema in props.items()
            if isinstance(field_schema, dict) and field_schema.get("type") == "array"
        ]

        has_total_field = any(field in props for field in total_fields)

        if has_total_field and array_fields:
            self._add_mutant(
                op_id,
                {
                    "id": f"{op_id}_Comp_PaginationMismatch",
                    "operator": "PaginationMismatch",
                },
            )

        
        ## Composition Fault > Combined Functionality Faulty
        ### Array length mismatch
        
        if array_fields:
            self._add_mutant(
                op_id,
                {
                    "id": f"{op_id}_Comp_ArrayLengthMismatch",
                    "operator": "ArrayLengthMismatch",
                },
            )

    
    # Helper to add mutants safely

    def _add_mutant(self, op_id: str, mutant: dict):
        # Make a copy so we do not mutate the caller's dict unexpectedly
        mutant = dict(mutant)

        # Add taxonomy metadata from operators.py
        mutant = enrich_mutant(mutant)

        # Skip disabled operators
        if mutant.get("operator") in self.disabled_operators:
            return

        # Keep backward-compatible "type" field if you still use it
        if "type" not in mutant:
            mutant["type"] = mutant.get("fault_leaf", "Unknown")

        # Avoid duplicate IDs
        existing_ids = {m["id"] for m in self.catalog[op_id]}
        base_id = mutant["id"]
        counter = 1

        while mutant["id"] in existing_ids:
            mutant["id"] = f"{base_id}_{counter}"
            counter += 1

        self.catalog[op_id].append(mutant)

    
    # OpenAPI helpers
    
    def _get_response_schema(self, operation: dict) -> dict:
        for status, resp in operation.get("responses", {}).items():
            if str(status).startswith("2"):
                content = resp.get("content", {})
                if "application/json" in content:
                    return content["application/json"].get("schema", {})
        return {}

    
    # Mutant selection
    
    def get_next_mutant(self, op_id: str) -> dict | None:
        # If no mutants were generated for this operation, return None
        if not self.catalog.get(op_id):
            return None

        # If queue is empty or missing, reshuffle
        if not self.queues.get(op_id):
            queue = self.catalog[op_id].copy()
            self.rng.shuffle(queue)
            self.queues[op_id] = queue

        if not self.queues[op_id]:
            return None

        return self.queues[op_id].pop(0)