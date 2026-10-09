import re
from urllib.parse import urlparse
from mitmproxy import http, ctx

class OpenAPIMatcher:
    """
    Pre-compiles OpenAPI paths into regexes for high-performance matching.
    Designed to be instantiated once when the spec is loaded.
    """
    def __init__(self, spec: dict):
        self.spec = spec
        self.routes = []  # List of tuples: (compiled_regex, spec_path, path_item_dict)
        
        if not spec or 'paths' not in spec:
            ctx.log.warn("OpenAPI spec is empty or missing 'paths'.")
            return

        # 1. Extract base path from 'servers' (Crucial for Spring Boot / Train Ticket)
        # e.g., if servers[0].url is "http://localhost:8080/api/v1/orderservice", base_path becomes "/api/v1/orderservice"
        self.base_path = ""
        servers = spec.get('servers', [])
        if servers and isinstance(servers, list) and 'url' in servers[0]:
            parsed_server = urlparse(servers[0]['url'])
            self.base_path = parsed_server.path.rstrip('/')

        # 2. Sort paths by length descending to match more specific paths first
        # e.g., /api/albums/{id}/photos before /api/albums/{id}
        sorted_paths = sorted(spec['paths'].keys(), key=len, reverse=True)
        
        # 3. Pre-compile all regexes
        for spec_path in sorted_paths:
            # Combine base_path and spec_path
            full_path = f"{self.base_path}{spec_path}" if self.base_path else spec_path
            
            # Replace {param} with a regex that matches any non-slash characters
            regex_str = re.sub(r'\{[^}]+\}', r'[^/]+', full_path)
            pattern = re.compile(f"^{regex_str}/?$")
            
            self.routes.append((pattern, spec_path, spec['paths'][spec_path]))
            
        ctx.log.info(f"[OpenAPIMatcher] Compiled {len(self.routes)} routes (base_path='{self.base_path}')")

    def match(self, flow: http.HTTPFlow):
        """Fast path matching using pre-compiled regexes."""
        raw_path = flow.request.path
        
        # Safely extract the path, handling both relative and absolute URIs
        if raw_path.startswith("http://") or raw_path.startswith("https://"):
            path = urlparse(raw_path).path
        else:
            path = raw_path.split('?')[0]
            
        method = flow.request.method.lower()
        
        # Iterate through pre-compiled routes
        for pattern, spec_path, path_item in self.routes:
            if pattern.match(path):
                # Case-insensitive method lookup
                method_key = next((k for k in path_item.keys() if k.lower() == method), None)
                if method_key:
                    operation = path_item[method_key]
                    op_id = operation.get('operationId', f"{method}_{spec_path}")
                    return op_id, operation
                    
        # Optional: uncomment for debugging unmatched internal mesh traffic
        # ctx.log.debug(f"NO MATCH: {method.upper()} {path}")
        
        return None, None