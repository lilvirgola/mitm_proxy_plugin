from mitmproxy import http

def match_operation(spec: dict, flow: http.HTTPFlow):
    path = flow.request.path.split('?')[0]
    method = flow.request.method.lower()
    
    for spec_path, path_item in spec.get('paths', {}).items():
        if method in path_item:
            # Simple exact or prefix match for path parameters (e.g., /api/albums/1 matches /api/albums/{id})
            if path == spec_path or path.startswith(spec_path.split('{')[0]):
                operation = path_item[method]
                op_id = operation.get('operationId', f"{method}_{path}")
                return op_id, operation
    return None, None