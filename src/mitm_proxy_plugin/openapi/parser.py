import re
from urllib.parse import urlparse
from mitmproxy import http, ctx

def openapi_path_to_regex(spec_path: str) -> re.Pattern:
    """
    Converts an OpenAPI path template (e.g., /api/albums/{id}) into a strict regex.
    Allows an optional trailing slash.
    """
    # Replace {param} with a regex that matches any non-slash characters
    regex_str = re.sub(r'\{[^}]+\}', r'[^/]+', spec_path)
    # Anchor the regex to the start and end of the string
    return re.compile(f"^{regex_str}/?$")

def match_operation(spec: dict, flow: http.HTTPFlow):
    raw_path = flow.request.path
    
    # Safely extract the path, handling both relative (/api/albums) 
    # and absolute (http://127.0.0.1:8080/api/albums) URIs
    if raw_path.startswith("http://") or raw_path.startswith("https://"):
        path = urlparse(raw_path).path
    else:
        path = raw_path.split('?')[0]
        
    method = flow.request.method.lower()
    
    if not spec or 'paths' not in spec:
        ctx.log.error("match_operation: OpenAPI spec is empty or missing 'paths'!")
        return None, None

    # Sort paths by length descending to match more specific paths first
    # e.g., /api/albums/{id}/photos before /api/albums/{id} before /api/albums
    sorted_paths = sorted(spec.get('paths', {}).keys(), key=len, reverse=True)
    
    for spec_path in sorted_paths:
        path_item = spec['paths'][spec_path]
        
        # Case-insensitive method lookup (handles 'GET' vs 'get')
        method_key = next((k for k in path_item.keys() if k.lower() == method), None)
        if not method_key:
            continue
            
        path_regex = openapi_path_to_regex(spec_path)
        if path_regex.match(path):
            operation = path_item[method_key]
            op_id = operation.get('operationId', f"{method}_{spec_path}")
            return op_id, operation
            
    # NOTE: If we reach here, nothing matched. 
    # This will print exactly what it was looking for and what the spec actually contains.
    ctx.log.error(f" NO MATCH: method='{method}' path='{path}'. Spec has {len(sorted_paths)} paths. Sample paths: {sorted_paths[:5]}")
    
    return None, None