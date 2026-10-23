import re
from urllib.parse import unquote, urlparse

from mitmproxy import ctx


def _log_info(msg: str):
    log = getattr(ctx, "log", None)
    if log and hasattr(log, "info"):
        log.info(msg)


def _log_warn(msg: str):
    log = getattr(ctx, "log", None)
    if log and hasattr(log, "warn"):
        log.warning(msg)


class OpenAPIMatcher:
    """
    Pre-compiles OpenAPI paths into regexes for high-performance matching.
    Designed to be instantiated once when the spec is loaded.
    """

    def __init__(self, spec: dict):
        self.spec = spec
        self.routes = []  # List of tuples: (compiled_regex, spec_path, path_item_dict, param_names)

        if not spec or "paths" not in spec:
            _log_warn("OpenAPI spec is empty or missing 'paths'.")
            return

        # 1. Extract base path from 'servers' (Crucial for Spring Boot / Train Ticket)
        # e.g., if servers[0].url is "http://localhost:8080/api/v1/orderservice", base_path becomes "/api/v1/orderservice"
        self.base_path = ""
        servers = spec.get("servers", [])
        if servers and isinstance(servers, list) and "url" in servers[0]:
            parsed_server = urlparse(servers[0]["url"])
            self.base_path = parsed_server.path.rstrip("/")

        # 2. Sort paths by length descending to match more specific paths first
        # e.g., /api/albums/{id}/photos before /api/albums/{id}
        sorted_paths = sorted(spec["paths"].keys(), key=len, reverse=True)

        # 3. Pre-compile all regexes
        for spec_path in sorted_paths:
            # Combine base_path and spec_path
            full_path = f"{self.base_path}{spec_path}" if self.base_path else spec_path

            # Extract parameter names in order and replace {param} with regex group ([^/]+)
            param_names = re.findall(r"\{([^}]+)\}", full_path)
            regex_str = re.sub(r"\{[^}]+\}", r"([^/]+)", full_path)
            pattern = re.compile(f"^{regex_str}/?$")

            self.routes.append(
                (pattern, spec_path, spec["paths"][spec_path], param_names)
            )

        _log_info(
            f"[OpenAPIMatcher] Compiled {len(self.routes)} routes (base_path='{self.base_path}')"
        )

    def match(self, flow):
        """Fast path matching using pre-compiled regexes."""
        request = getattr(flow, "request", None)
        if not request:
            return None, None

        raw_path = getattr(request, "path", "")
        if not raw_path:
            return None, None

        # Safely extract the path, handling both relative and absolute URIs
        if raw_path.startswith(("http://", "https://")):
            path = urlparse(raw_path).path
        else:
            path = raw_path.split("?")[0]

        method = getattr(request, "method", "get").lower()

        # Iterate through pre-compiled routes
        for pattern, spec_path, path_item, param_names in self.routes:
            m = pattern.match(path)
            if m:
                # Case-insensitive method lookup
                method_key = next((k for k in path_item if k.lower() == method), None)
                if method_key:
                    operation = path_item[method_key]
                    op_id = operation.get("operationId", f"{method}_{spec_path}")
                    if hasattr(flow, "metadata") and isinstance(flow.metadata, dict):
                        flow.metadata["path_params"] = {
                            k: unquote(v) for k, v in zip(param_names, m.groups(), strict=False)
                        }
                    return op_id, operation

        return None, None
