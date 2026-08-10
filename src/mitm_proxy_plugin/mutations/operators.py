import json
import time
from .taxonomy import enrich_mutant

"""
the main function that applies a mutation to a mitmproxy flow based on the operator and mutant details
NOTE:
The flow object needs:
    - flow.kill()
    - flow.response.status_code
    - flow.response.content
    - flow.response.headers
"""

def apply_mutation(flow, mutant: dict) -> None:

    mutant = enrich_mutant(mutant)
    operator = mutant.get("operator")
    
    # Connection / execution disruptions
    if operator == "ConnectionDrop":
        flow.kill()
        return

    if operator == "Timeout":
        time.sleep(float(mutant.get("delay", 10)))
        return

    if operator == "TimeoutThenDrop":
        time.sleep(float(mutant.get("delay", 5)))
        flow.kill()
        return

    if operator == "SlowResponse":
        time.sleep(float(mutant.get("delay", 2)))
        # Continue and mutate the response as well.

    # Response-based mutations
    mutate_response(flow.response, mutant)


"""
Applies a mutation to an HTTP response-like object.

NOTE:
The response object needs:
    - status_code
    - content
    - headers
"""
def mutate_response(response, mutant: dict) -> None:
    
    operator = mutant.get("operator")

    # Service Description Faults -> Format Faults
    if operator == "MalformedJSON":
        response.content = b'{"error": "broken json'
        return

    if operator == "TruncatedJSON":
        response.content = _truncate_bytes(response.content)
        return

    if operator == "InvalidContentType":
        _set_header(
            response,
            "Content-Type",
            mutant.get("content_type", "text/plain"),
        )
        return

    
    # Service Description Faults -> Content Faults
    if operator == "MissingRequired":
        target = mutant.get("target")

        def remove_required_field(body):
            if isinstance(body, dict) and target in body:
                del body[target]

        _mutate_json(response, remove_required_field)
        return

    if operator == "TypeMismatch":
        target = mutant.get("target")

        def change_type(body):
            if isinstance(body, dict) and target in body:
                old_value = body[target]

                if isinstance(old_value, bool):
                    body[target] = "true"
                elif isinstance(old_value, (int, float)):
                    body[target] = "mutated_string"
                else:
                    body[target] = 99999

        _mutate_json(response, change_type)
        return

    if operator == "NullViolation":
        target = mutant.get("target")

        def make_null(body):
            if isinstance(body, dict) and target in body:
                body[target] = None

        _mutate_json(response, make_null)
        return

    if operator == "EnumViolation":
        target = mutant.get("target")
        invalid_value = mutant.get("invalid_value", "__INVALID_ENUM__")

        def break_enum(body):
            if isinstance(body, dict) and target in body:
                body[target] = invalid_value

        _mutate_json(response, break_enum)
        return

    if operator == "BoundaryViolation":
        target = mutant.get("target")
        invalid_value = mutant.get("invalid_value", 999999)

        def break_boundary(body):
            if isinstance(body, dict) and target in body:
                body[target] = invalid_value

        _mutate_json(response, break_boundary)
        return

    
    # Service Description Faults -> Service/Description Mismatch
    if operator == "UndocumentedField":
        def add_undocumented_field(body):
            if isinstance(body, dict):
                body["__mutant_undocumented"] = True

        _mutate_json(response, add_undocumented_field)
        return

    if operator == "UndocumentedHeader":
        _set_header(
            response,
            mutant.get("header_name", "X-Undocumented-Interface"),
            mutant.get("header_value", "true"),
        )
        return

    
    # Execution Faults
    if operator == "WrongStatusCode":
        response.status_code = int(mutant.get("status_code", 500))
        return

    if operator == "IncorrectValue":
        target = mutant.get("target")
        invalid_value = mutant.get("invalid_value", "__INCORRECT_VALUE__")

        def set_incorrect_value(body):
            if isinstance(body, dict) and target in body:
                body[target] = invalid_value

        _mutate_json(response, set_incorrect_value)
        return

    if operator == "EmptyBody":
        response.content = b""
        return

    
    # Service Deployment Faults
    if operator == "Simulate503":
        response.status_code = 503
        response.content = b'{"error": "Service Unavailable"}'
        return

    if operator == "Simulate502":
        response.status_code = 502
        response.content = b'{"error": "Bad Gateway"}'
        return

    if operator == "Simulate500":
        response.status_code = 500
        response.content = b'{"error": "Internal Server Error"}'
        return

    
    # Discovery Faults
    if operator == "Simulate404":
        response.status_code = 404
        response.content = b'{"error": "Not Found"}'
        return

    if operator == "WrongVersionHeader":
        version = mutant.get("version", "0.0.0-mutated")
        _set_header(response, "X-API-Version", version)
        _set_header(response, "X-Service-Version", version)
        return

    if operator == "WrongResourceId":
        target = mutant.get("target", "id")
        invalid_value = mutant.get("invalid_value", 999999)

        def change_resource_id(body):
            if isinstance(body, dict) and target in body:
                body[target] = invalid_value

        _mutate_json(response, change_resource_id)
        return

    
    # Composition Faults
    if operator == "PaginationMismatch":
        def break_pagination(body):
            if not isinstance(body, dict):
                return

            for field in ("totalElements", "total", "totalCount"):
                if field in body:
                    body[field] = 999999

        _mutate_json(response, break_pagination)
        return

    if operator == "ArrayLengthMismatch":
        def break_array_length(body):
            if isinstance(body, dict):
                for field in ("content", "items", "data"):
                    if isinstance(body.get(field), list):
                        body[field].append({"__mutant_extra_item": True})
                        return

            elif isinstance(body, list):
                body.append({"__mutant_extra_item": True})

        _mutate_json(response, break_array_length)
        return

    
    # Connection Faults
    if operator == "Simulate401":
        response.status_code = 401
        response.content = b'{"error": "Unauthorized"}'
        return

    if operator == "Simulate403":
        response.status_code = 403
        response.content = b'{"error": "Forbidden"}'
        return

    if operator == "TooMuchData":
        size = int(mutant.get("size", 100_000))

        def add_large_payload(body):
            if isinstance(body, dict):
                body["__mutant_large_payload"] = "A" * size

        _mutate_json(response, add_large_payload)
        return



# Helpers

# Safely parses response.content as JSON, applies mutate_fn(body), and writes the mutated JSON back.
def _mutate_json(response, mutate_fn) -> None:
    
    try:
        body = json.loads(_as_bytes(response.content) or b"{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        # If the response is not JSON, skip this mutation safely.
        return

    mutate_fn(body)

    response.content = json.dumps(body).encode("utf-8")

# Cuts a response body to simulate a truncated message.
def _truncate_bytes(content) -> bytes:

    content = _as_bytes(content)

    if not content:
        return b'{"truncated":'

    if len(content) <= 3:
        return content[:1] or b"{"

    return content[: len(content) // 2]

# Converts response content to bytes defensively.
def _as_bytes(value) -> bytes:

    if value is None:
        return b""

    if isinstance(value, bytes):
        return value

    if isinstance(value, str):
        return value.encode("utf-8", errors="replace")

    return str(value).encode("utf-8", errors="replace")

# Sets a response header defensively.
def _set_header(response, name: str, value: str) -> None:

    headers = getattr(response, "headers", None)

    if headers is None:
        response.headers = {}
        headers = response.headers

    headers[name] = value