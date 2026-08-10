import re
from mitmproxy import http

def openapi_path_to_regex(spec_path: str) -> re.Pattern:
    # Replace {param} with a regex that matches any non-slash characters
    regex_str = re.sub(r'\{[^}]+\}', r'[^/]+', spec_path)
    # Anchor the regex to the start and end of the string, allowing optional trailing slash
    return re.compile(f"^{regex_str}/?$")

def match_operation(spec: dict, flow: http.HTTPFlow):
    path = flow.request.path.split('?')[0]
    method = flow.request.method.lower()
    
    # Sort paths by length descending to match more specific paths first
    # e.g., /api/todos/{id}/complete before /api/todos/{id} before /api/todos
    sorted_paths = sorted(spec.get('paths', {}).keys(), key=len, reverse=True)
    
    for spec_path in sorted_paths:
        path_item = spec['paths'][spec_path]
        if method not in path_item:
            continue
            
        path_regex = openapi_path_to_regex(spec_path)
        if path_regex.match(path):
            operation = path_item[method]
            op_id = operation.get('operationId', f"{method}_{spec_path}")
            return op_id, operation
            
    return None, None