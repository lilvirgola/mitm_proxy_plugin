"""
Request validator for validating HTTP requests against OpenAPI operation schemas.
just a simple implementation, but i think it should be enough for our purposes...
"""
import json
import jsonschema
from mitmproxy import http

class RequestValidator:
    def validate(self, flow: http.HTTPFlow, operation: dict) -> str | None:
        # Validate Parameters
        for param in operation.get('parameters', []):
            name = param['name']
            location = param['in']
            required = param.get('required', False)
            
            value = flow.request.query.get(name) if location == 'query' else None
            
            if required and value is None:
                return f"Missing required {location} parameter: {name}"
                
            if value is not None:
                schema = param.get('schema', {})
                p_type = schema.get('type')
                if p_type == 'integer' and not value.isdigit():
                    return f"Invalid type for {location} parameter: {name}"

        # Validate Request Body
        if 'requestBody' in operation:
            try:
                body_schema = operation['requestBody']['content']['application/json']['schema']
                if flow.request.content:
                    jsonschema.validate(json.loads(flow.request.content), body_schema)
            except Exception as e:
                return f"Invalid Request Body: {str(e)}"
                
        return None