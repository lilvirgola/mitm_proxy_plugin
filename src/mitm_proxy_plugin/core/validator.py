"""
Request validator for validating HTTP requests against OpenAPI operation schemas.
"""

import json

import jsonschema


class RequestValidator:
    def validate(self, flow, operation: dict) -> str | None:
        request = getattr(flow, "request", None)
        if not request or not operation:
            return None

        # Validate Parameters
        query = getattr(request, "query", {}) or {}
        for param in operation.get("parameters", []):
            name = param.get("name")
            location = param.get("in")
            required = param.get("required", False)

            value = query.get(name) if location == "query" else None

            if required and value is None:
                return f"Missing required {location} parameter: {name}"

            if value is not None:
                schema = param.get("schema", {})
                p_type = schema.get("type")
                if p_type == "integer":
                    try:
                        int(value)
                    except (ValueError, TypeError):
                        return f"Invalid type for {location} parameter: {name}"

        # Validate Request Body
        if "requestBody" in operation:
            try:
                content_spec = operation["requestBody"].get("content", {})
                json_spec = content_spec.get("application/json", {})
                body_schema = json_spec.get("schema")
                if body_schema:
                    content = getattr(request, "content", None)
                    if content:
                        if isinstance(content, bytes):
                            content = content.decode("utf-8")
                        jsonschema.validate(json.loads(content), body_schema)
            except Exception as e:  # noqa: BLE001
                return f"Invalid Request Body: {e!s}"

        return None
