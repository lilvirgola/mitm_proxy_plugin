# mitm\_proxy\_plugin

A [mitmproxy](https://mitmproxy.org/) addon for **black-box mutation
testing of REST APIs**, driven by OpenAPI specifications. Designed to run as an
in-pod sidecar inside Kubernetes service meshes and controlled dynamically via an
HTTP Control Plane.

Built as part of a Master's thesis on evaluating REST API testing tools through
controlled fault injection in microservice systems

---

## How It Works

```text
                         ┌─────────────────────────────────────────────────┐
                         │                Kubernetes Pod                   │
                         │                                                 │
  Fuzzer / Tool ────────►│  ┌────────────┐         ┌───────────────────┐   │
  (external)    :9092    │  │ mitmproxy  │────────►│  SUT Application  │   │
                         │  │            │ :app    │  (Spring Boot,    │   │
                         │  │  addon.py  │◄────────│   FastAPI, etc.)  │   │
                         │  │            │         └───────────────────┘   │
                         │  │  ┌───────┐ │                                 │
                         │  │  │OpenAPI│ │         ┌───────────────────┐   │
                         │  │  │Matcher│ │  :8081  │   Orchestrator    │   │
                         │  │  └───────┘ │◄───────►│   (RESTberus      │   │
                         │  │  ┌──────┐  │  HTTP   │    RunManager)    │   │
                         │  │  │Mutate│  │ Control │                   │   │
                         │  │  │Ops   │  │ Plane   │  POST /campaign   │   │
                         │  │  └──────┘  │         │  GET  /drain      │   │
                         │  │  ┌──────┐  │         │  GET  /status     │   │
                         │  │  │Logger│  │         └───────────────────┘   │
                         │  │  └──────┘  │                                 │
                         │  └────────────┘                                 │
                         └─────────────────────────────────────────────────┘
```

1. **Matching** — Incoming requests are matched against the target service's
   OpenAPI specification using pre-compiled regex patterns (zero per-request
   compilation overhead).
2. **Validation** — Requests are validated against the spec's parameter
   constraints. Invalid requests are rejected before mutation.
3. **Mutation** — If the request matches the active campaign's target operation,
   the response is mutated in-place according to the active operator.
4. **Telemetry** — Every mutation activation is logged to an in-memory buffer
   with a monotonically increasing sequence number, drainable via HTTP.
5. **Dynamic Swapping** — The orchestrator can hot-swap the active campaign via
   the HTTP Control Plane without restarting the pod or losing state.

---

## Features

- **OpenAPI-driven targeting** — Mutations are applied only to requests matching
  a specific `operationId` from the spec. No wildcard, no guesswork.
- **HTTP Control Plane** — Swap campaigns, drain telemetry, and query status
  via a lightweight HTTP API. Designed for orchestrator integration.
- **Thread-safe state** — Campaign state is protected by a lock, safe for
  concurrent access from the control plane thread and mitmproxy's event loop.
- **Non-blocking mutations** — All operators use `async/await`. Timeout-based
  faults (`Timeout`, `SlowResponse`) never block the mitmproxy event loop.
- **Incremental telemetry** — The drain endpoint returns only records newer than
  a caller-supplied sequence number, enabling efficient polling.
- **Rich fault taxonomy** — Operators cover 6 taxonomy categories with 25+
  mutation operators (see [Mutation Taxonomy](#mutation-taxonomy)).
- **Campaign model** — Supports `baseline` (no mutations) and `single_mutant`
  (one targeted fault) modes with deterministic seeding.

---

## Installation

### From source (development)

```bash
git clone https://github.com/lilvirgola/mitm_proxy_plugin.git
cd mitm_proxy_plugin
pip install -e ".[dev]"
```

### As a Docker image (production / RESTberus)

The image is published to:

```
ghcr.io/lilvirgola/mitmproxy-mutation:main
```

---

## Usage

### Standalone (local testing)

```bash
mitmdump \
  -p 9092 \
  --mode reverse:http://localhost:8080/ \
  -s src/mitm_proxy_plugin/addon.py \
  --set openapi_spec=./openapi.json \
  --set campaign_file=./campaign.json \
  --set mutation_control_port=8081 \
  --set exec_log=/tmp/executions.jsonl
```

---

## HTTP Control Plane API

The control plane listens on the port specified by `--set mutation_control_port`
(default: `8081`). All endpoints accept and return JSON.

### `POST /campaign`

Hot-swap the active campaign. The new campaign takes effect on the very next
request.

**Request body:**

```json
{
  "campaign_id": "c0001",
  "mode": "single_mutant",
  "seed": 42,
  "spec_sha256": "abc123",
  "created_at": "2026-01-01T00:00:00Z",
  "target": {
    "operation_id": "login"
  },
  "mutant": {
    "id": "m1",
    "operator": "Simulate502",
    "taxonomy_path": "ServiceDeploymentFaults",
    "description": "Simulate a 502 Bad Gateway response"
  }
}
```

**Response:**

```json
{
  "status": "ok",
  "campaign_id": "c0001"
}
```

### `GET /status`

Return the currently active campaign and execution statistics.

**Response:**

```json
{
  "campaign_id": "c0001",
  "active_mutant_id": "m1",
  "target_op": "login",
  "stats": {
    "matched_requests": 42,
    "mutated_responses": 12,
    "blocked_invalid_requests": 3
  }
}
```

### `GET /drain?seq=N`

Return all telemetry records with sequence number greater than `N`. This is the
primary endpoint used by the RESTberus orchestrator to collect mutation
activations incrementally.

**Response:**

```json
{
  "logs": [
    {
      "seq": 13,
      "timestamp": 1735689600.123,
      "campaign_id": "c0001",
      "request_id": "550e8400-e29b-41d4-a716-446655440000",
      "operation_id": "login",
      "method": "POST",
      "path": "/api/v1/auth/login",
      "mutant_id": "m1",
      "operator": "Simulate502",
      "taxonomy_path": "ServiceDeploymentFaults",
      "status": "EXECUTED",
      "response_status": 502
    }
  ],
  "current_seq": 13
}
```

### `POST /clear`

Reset the addon to baseline mode (no mutations active).

**Response:**

```json
{
  "status": "cleared"
}
```

---

## Mutation Taxonomy

Operators are organized following the integration-test fault taxonomy from
Gregor et al., extended with deployment and discovery faults relevant to
microservice systems.

| Category | Operator | Effect |
|----------|----------|--------|
| **Format Faults** | `MalformedJSON` | Response body is syntactically invalid JSON |
| | `TruncatedJSON` | Response body is cut mid-stream |
| | `InvalidContentType` | `Content-Type` header is set to a wrong value |
| **Content Faults** | `MissingRequired` | A required field is removed from the body |
| | `TypeMismatch` | A field's type is changed (e.g., `int` → `string`) |
| | `NullViolation` | A non-nullable field is set to `null` |
| | `EnumViolation` | A field is set to a value outside its enum |
| | `BoundaryViolation` | A numeric field exceeds its min/max bounds |
| | `IncorrectValue` | A field is set to a semantically wrong value |
| **Undocumented** | `UndocumentedField` | An extra field not in the spec is added |
| | `UndocumentedHeader` | An extra response header is injected |
| **Execution Faults** | `WrongStatusCode` | HTTP status code is changed |
| | `EmptyBody` | Response body is emptied |
| **Deployment Faults** | `Simulate500` | Return `500 Internal Server Error` |
| | `Simulate502` | Return `502 Bad Gateway` |
| | `Simulate503` | Return `503 Service Unavailable` |
| **Discovery Faults** | `Simulate404` | Return `404 Not Found` |
| | `WrongVersionHeader` | API version headers are set to invalid values |
| | `WrongResourceId` | A resource ID field is set to a non-existent ID |
| **Composition Faults** | `PaginationMismatch` | Pagination counters are set to wrong values |
| | `ArrayLengthMismatch` | An array gets an unexpected extra element |
| **Connection Faults** | `Simulate401` | Return `401 Unauthorized` |
| | `Simulate403` | Return `403 Forbidden` |
| | `TooMuchData` | An oversized payload is injected |
| **Execution Disruption** | `ConnectionDrop` | TCP connection is killed mid-flight |
| | `Timeout` | Response is delayed by N seconds |
| | `TimeoutThenDrop` | Delay then kill the connection |
| | `SlowResponse` | Delay then deliver the (possibly mutated) response |

---

## Campaign Model

A **campaign** defines a single mutation experiment: one target operation, one
injected fault, one execution run.

```json
{
  "campaign_id": "c0001",
  "mode": "single_mutant",
  "seed": 42,
  "spec_sha256": "sha256-of-the-openapi-spec",
  "created_at": "2026-01-01T00:00:00Z",
  "target": {
    "operation_id": "login"
  },
  "mutant": {
    "id": "m1",
    "operator": "Simulate502",
    "taxonomy_path": "ServiceDeploymentFaults",
    "fault_leaf": "Simulate502",
    "description": "Return 502 Bad Gateway instead of the normal response"
  },
  "policy": {
    "max_one_mutant_per_operation": true,
    "mutate_valid_requests_only": true,
    "attribution": "direct_operation_or_request"
  }
}
```

### Modes

| Mode | Behaviour |
|------|-----------|
| `baseline` | No mutations are applied. Used as the control group. |
| `single_mutant` | Exactly one mutant is active, targeting one operation. |
| `multi_mutant` | *(reserved)* Multiple mutants assigned across operations. |

---

## Configuration Options

These are passed via `mitmdump --set key=value` or `--set key=value` in the
Helm chart.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `openapi_spec` | `str` | `""` | Path to the OpenAPI 3.x JSON/YAML spec (required). |
| `mutation_seed` | `int` | `42` | Seed for deterministic RNG. |
| `exec_log` | `str` | `/tmp/executions.jsonl` | Path to the execution log file. |
| `campaign_file` | `str` | `""` | Path to an initial campaign JSON (optional). |
| `mutation_control_port` | `int` | `8081` | Port for the HTTP Control Plane. |
| `disabled_operators` | `str` | `""` | Comma-separated operators to skip (e.g., `Timeout,ConnectionDrop`). |

---

## Generating Campaigns

Use the included script to generate a manifest of campaigns from an OpenAPI spec:

```bash
# Generate for a single spec
python scripts/generate_manifest.py \
  --spec path/to/openapi.json \
  --out manifests/ \
  --seed 42

# Generate for all APIs in a RESTberus directory
python scripts/generate_manifest.py \
  --restberus-dir /path/to/RESTberus \
  --api ts-auth-service \
  --max-per-operation 10

# Dry run (preview without writing)
python scripts/generate_manifest.py \
  --spec path/to/openapi.json \
  --dry-run

# Only specific operators
python scripts/generate_manifest.py \
  --spec path/to/openapi.json \
  --operators Simulate502,MalformedJSON,MissingRequired
```

Output is a `manifest.jsonl` file where each line is a self-contained campaign
JSON object, ready to be passed to the RESTberus client via `--manifest`.

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v -s --cov=src/mitm_proxy_plugin --cov-report=term-missing

# Run a specific test file
pytest tests/test_operators.py -v
```
