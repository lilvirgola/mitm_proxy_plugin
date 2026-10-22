"""Helper functions for the Mutation Addon."""


def extract_trace_id(flow) -> str | None:
    """Extract the propagated trace ID from request headers."""
    request = getattr(flow, "request", None)
    if not request:
        return None
    headers = getattr(request, "headers", None)
    if not headers:
        return None

    # 1. Prioritize standard distributed tracing headers (most likely to be propagated)
    trace_id = headers.get("x-b3-traceid")
    if trace_id:
        return trace_id

    traceparent = headers.get("traceparent")
    if traceparent:
        parts = traceparent.split("-")
        if len(parts) >= 2 and parts[1]:
            return parts[1]

    uber_trace = headers.get("uber-trace-id")
    if uber_trace:
        parts = uber_trace.split(":")
        if parts and parts[0]:
            return parts[0]

    # 2. Fallback to x-request-id (only if tracing headers are missing)
    req_id = headers.get("x-request-id")
    if req_id:
        return req_id

    return None
