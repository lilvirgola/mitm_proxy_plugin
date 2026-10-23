import json
import warnings
from typing import Any

import jsonschema


class RequestValidator:
    def __init__(self, spec: dict[str, Any] | None = None) -> None:
        self.spec: dict[str, Any] | None = None
        self._resolver: jsonschema.RefResolver | None = None
        if spec:
            self.set_spec(spec)

    def set_spec(self, spec: dict[str, Any]) -> None:
        """Store the root OpenAPI spec and compile a RefResolver for internal $ref pointers."""
        self.spec = spec
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._resolver = jsonschema.RefResolver(base_uri="", referrer=spec)

    def validate(self, flow, operation: dict) -> str | None:
        request = getattr(flow, "request", None)
        if not request or not operation:
            return None

        # Validate Parameters
        query = getattr(request, "query", {}) or {}
        headers = getattr(request, "headers", {}) or {}
        path_params = {}
        if hasattr(flow, "metadata") and isinstance(flow.metadata, dict):
            path_params = flow.metadata.get("path_params", {}) or {}

        for param in operation.get("parameters", []):
            name = param.get("name")
            location = param.get("in")
            required = param.get("required", False)

            if location == "query":
                value = query.get(name)
            elif location == "path":
                # If path_params has the value, use it.
                # If path_params is empty (e.g. standalone test or unparsed), but request has a path, don't flag as missing
                if path_params:
                    value = path_params.get(name)
                else:
                    value = getattr(request, "path", None)
            elif location == "header":
                value = headers.get(name)
                if value is None and hasattr(headers, "get_all"):
                    value = headers.get(name.lower())
            else:
                value = None

            if required and value is None:
                return f"Missing required {location} parameter: {name}"

            if value is not None and value != getattr(request, "path", None):
                schema = param.get("schema", {})
                p_type = schema.get("type")
                if p_type == "integer":
                    try:
                        int(value)
                    except (ValueError, TypeError):
                        return f"Invalid type for {location} parameter: {name}"
                elif p_type == "number":
                    try:
                        float(value)
                    except (ValueError, TypeError):
                        return f"Invalid type for {location} parameter: {name}"
                elif (
                    p_type == "boolean"
                    and str(value).lower() not in ("true", "false", "0", "1")
                ):
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
                        payload = json.loads(content)
                        if self._resolver is not None:
                            with warnings.catch_warnings():
                                warnings.simplefilter("ignore")
                                validator = jsonschema.Draft4Validator(
                                    body_schema, resolver=self._resolver
                                )
                                validator.validate(payload)
                        else:
                            jsonschema.validate(payload, body_schema)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                return f"Invalid JSON in Request Body: {e!s}"
            except jsonschema.ValidationError as e:
                return f"Invalid Request Body: {e.message}"
            except Exception:  # noqa: BLE001
                # Non-validation errors (e.g. unknown reference lookup failure) shouldn't block mutations
                return None

        return None

