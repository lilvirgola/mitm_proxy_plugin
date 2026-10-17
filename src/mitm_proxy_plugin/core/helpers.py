"""Helper functions for the Mutation Addon."""

def extract_trace_id(flow) -> str | None:
        """Extract the propagated trace ID from request headers."""
        # 1. Prioritize standard distributed tracing headers (most likely to be propagated)
        trace_id = flow.request.headers.get("x-b3-traceid")
        if trace_id:
            return trace_id
            
        traceparent = flow.request.headers.get("traceparent")
        if traceparent:
            parts = traceparent.split("-")
            if len(parts) >= 2:
                return parts[1]
                
        uber_trace = flow.request.headers.get("uber-trace-id")
        if uber_trace:
            parts = uber_trace.split(":")
            if parts:
                return parts[0]
        
        # 2. Fallback to x-request-id (only if tracing headers are missing)
        req_id = flow.request.headers.get("x-request-id")
        if req_id:
            return req_id
            
        return None