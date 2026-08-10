# Taxonomy metadata
# This dictionary maps mutation operators to their taxonomy metadata, including category, path, leaf, and description.
# This is used to enrich mutants with additional information for reporting and analysis.
OPERATOR_TAXONOMY = {

    # Service Description Faults
    "MalformedJSON": {
        "category": "Service Description Fault",
        "path": "Service Description Fault > Description Incorrect > Format Fault",
        "leaf": "Format Fault",
        "description": "Breaks JSON syntax so the response cannot be parsed.",
    },
    "TruncatedJSON": {
        "category": "Connection Fault",
        "path": "Connection Fault > Connection Disruption > Message Lost",
        "leaf": "Message Lost",
        "description": "Cuts the response body, simulating a lost or truncated message.",
    },
    "InvalidContentType": {
        "category": "Service Description Fault",
        "path": "Service Description Fault > Description Incorrect > Format Fault",
        "leaf": "Format Fault",
        "description": "Returns a wrong Content-Type header for the response.",
    },
    "MissingRequired": {
        "category": "Service Description Fault",
        "path": "Service Description Fault > Description Incorrect > Content Fault",
        "leaf": "Content Fault",
        "description": "Removes a required field from the response payload.",
    },
    "TypeMismatch": {
        "category": "Service Description Fault",
        "path": "Service Description Fault > Description Incorrect > Content Fault",
        "leaf": "Content Fault",
        "description": "Changes a field to an incorrect JSON type.",
    },
    "NullViolation": {
        "category": "Execution Fault",
        "path": "Execution Fault > Incorrect Result > Data Incomplete",
        "leaf": "Data Incomplete",
        "description": "Sets a non-nullable field to null.",
    },
    "EnumViolation": {
        "category": "Service Description Fault",
        "path": "Service Description Fault > Description Incorrect > Content Fault",
        "leaf": "Content Fault",
        "description": "Sets a field to a value outside its allowed enum.",
    },
    "BoundaryViolation": {
        "category": "Service Description Fault",
        "path": "Service Description Fault > Description Incorrect > Content Fault",
        "leaf": "Content Fault",
        "description": "Sets a numeric field outside its allowed boundary.",
    },
    "UndocumentedField": {
        "category": "Service Description Fault",
        "path": "Service Description Fault > Service/Description Mismatch > Description Incomplete",
        "leaf": "Description Incomplete",
        "description": "Adds a field that is not documented in the OpenAPI specification.",
    },
    "UndocumentedHeader": {
        "category": "Service Description Fault",
        "path": "Service Description Fault > Service/Description Mismatch > Implicit Interface",
        "leaf": "Implicit Interface",
        "description": "Adds an undocumented HTTP header.",
    },

    # Execution Faults
    "WrongStatusCode": {
        "category": "Execution Fault",
        "path": "Execution Fault > Incorrect Result > Wrong Result Code",
        "leaf": "Wrong Result Code",
        "description": "Returns an incorrect HTTP status code.",
    },
    "IncorrectValue": {
        "category": "Execution Fault",
        "path": "Execution Fault > Incorrect Result > Service Faulty",
        "leaf": "Service Faulty",
        "description": "Returns an incorrect value for a specific field.",
    },
    "EmptyBody": {
        "category": "Execution Fault",
        "path": "Execution Fault > Incorrect Result > Data Incomplete",
        "leaf": "Data Incomplete",
        "description": "Returns an empty response body when content is expected.",
    },

    # Service Deployment Faults
    "Simulate503": {
        "category": "Service Deployment Fault",
        "path": "Service Deployment Fault > Required Resource Missing",
        "leaf": "Required Resource Missing",
        "description": "Simulates an unavailable service or missing required resource.",
    },
    "Simulate502": {
        "category": "Service Deployment Fault",
        "path": "Service Deployment Fault > Wrong Configuration",
        "leaf": "Wrong Configuration",
        "description": "Simulates a bad gateway or misconfigured upstream service.",
    },
    "Simulate500": {
        "category": "Execution Fault",
        "path": "Execution Fault > Incorrect Result > Service Faulty",
        "leaf": "Service Faulty",
        "description": "Simulates an internal server error.",
    },

    # Discovery Faults
    "Simulate404": {
        "category": "Discovery Fault",
        "path": "Discovery Fault > No Service Found > Required Service Not Existing",
        "leaf": "Required Service Not Existing",
        "description": "Simulates a missing endpoint or non-existing service.",
    },
    "WrongVersionHeader": {
        "category": "Discovery Fault",
        "path": "Discovery Fault > Wrong Service Found > Wrong Version",
        "leaf": "Wrong Version",
        "description": "Returns a wrong service/version header.",
    },
    "WrongResourceId": {
        "category": "Discovery Fault",
        "path": "Discovery Fault > Routing Faulty",
        "leaf": "Routing Faulty",
        "description": "Returns an incorrect resource identifier, simulating wrong routing.",
    },

    # Composition Faults
    "PaginationMismatch": {
        "category": "Composition Fault",
        "path": "Composition Fault > Combined Functionality Faulty",
        "leaf": "Combined Functionality Faulty",
        "description": "Breaks consistency between pagination metadata and page content.",
    },
    "ArrayLengthMismatch": {
        "category": "Composition Fault",
        "path": "Composition Fault > Combined Functionality Faulty",
        "leaf": "Combined Functionality Faulty",
        "description": "Adds or changes array elements inconsistently with the expected composition.",
    },

    # Connection Faults
    "Simulate401": {
        "category": "Connection Fault",
        "path": "Connection Fault > Connection Denied > Authentication Failed",
        "leaf": "Authentication Failed",
        "description": "Simulates failed authentication.",
    },
    "Simulate403": {
        "category": "Connection Fault",
        "path": "Connection Fault > Connection Denied > Authorization Denied",
        "leaf": "Authorization Denied",
        "description": "Simulates denied authorization.",
    },
    "ConnectionDrop": {
        "category": "Connection Fault",
        "path": "Connection Fault > Connection Disruption > Connection Interrupted",
        "leaf": "Connection Interrupted",
        "description": "Abruptly closes the connection.",
    },
    "Timeout": {
        "category": "Connection Fault",
        "path": "Connection Fault > Timed Out",
        "leaf": "Timed Out",
        "description": "Delays the response to simulate a timeout.",
    },
    "TimeoutThenDrop": {
        "category": "Execution Fault",
        "path": "Execution Fault > Timed Out > Service Crashed > temporarily",
        "leaf": "Service Crashed",
        "description": "Delays the response and then drops the connection.",
    },
    "SlowResponse": {
        "category": "Connection Fault",
        "path": "Connection Fault > Connection Performance > Data Transmission Too Slow",
        "leaf": "Data Transmission Too Slow",
        "description": "Delays the response but eventually returns it.",
    },
    "TooMuchData": {
        "category": "Connection Fault",
        "path": "Connection Fault > Connection Performance > Too Much Data",
        "leaf": "Too Much Data",
        "description": "Injects a large payload into the response.",
    },
}

# Adds taxonomy metadata to a mutant if it is missing.
def enrich_mutant(mutant: dict) -> dict:
    operator_value = mutant.get("operator")
    operator = operator_value if isinstance(operator_value, str) else ""
    meta = OPERATOR_TAXONOMY.get(operator, {})

    mutant.setdefault("taxonomy", meta.get("category", "Unknown"))
    mutant.setdefault("taxonomy_path", meta.get("path", "Unknown"))
    mutant.setdefault("fault_leaf", meta.get("leaf", "Unknown"))
    mutant.setdefault("description", meta.get("description", ""))

    return mutant