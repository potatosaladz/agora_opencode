# Observability

**Version:** 1.0 · **Last reviewed:** 2026-09-05 · **Status:** implemented; PostgreSQL acceptance pending
**Requirements:** NFR-015 · **Companions:** [ARCHITECTURE.md](ARCHITECTURE.md),
[SECURITY.md](SECURITY.md), [TESTING.md](TESTING.md)

## 1. Signal ownership and lifecycle

Each FastAPI application instance owns its own Prometheus `CollectorRegistry`, OpenTelemetry
`TracerProvider`, exporter, and SQLAlchemy event listeners. The app factory does not replace the
process-global tracer provider, so multiple applications can run in one test process without sharing
spans or metric samples. Lifespan cleanup removes FastAPI and SQLAlchemy instrumentation before
disposing adapters and shutting down the provider; cleanup is idempotent and also runs after startup
failure.

The service resource identifies `service.name`, `service.version`, and
`deployment.environment.name`. Configure export with `OTEL_EXPORTER_ENDPOINT`; the backend posts OTLP
HTTP traces to `<endpoint>/v1/traces`. With no endpoint, spans remain local and startup records that no
exporter is configured.

## 2. Structured logs

Production logs are JSON. Request logs include `correlation_id`, `session_id` when a verified session
has been bound, `code_version`, and the active `trace_id`/`span_id`. The correlation middleware accepts
an inbound `X-Request-Id` or generates one and echoes it in the response.

Redaction runs inside the structlog processor chain:

- keys matching password, secret, token, API/access key, authorization, or credential patterns are
  replaced with `[redacted]`;
- mappings, lists, and tuples are scrubbed recursively;
- secret literals registered by the composition root are removed even when interpolated into a
  message, URL, or nested value.

Callers must still avoid logging raw provider payloads. Redaction is a fail-safe, not permission to
collect sensitive data.

## 3. Traces

FastAPI emits server spans for application requests. `/health`, `/ready`, and `/metrics` are excluded
to prevent probe and scrape noise. Request spans carry `agora.correlation_id` and `service.version`.

SQLAlchemy instrumentation emits a child `CLIENT` span named `db <OPERATION>` for each database
execution. It records only:

- `db.system.name`;
- the bounded `db.operation.name` (`SELECT`, `INSERT`, `UPDATE`, `DELETE`, or `OTHER`);
- `agora.correlation_id` and `agora.session_id` when present;
- `service.version`.

SQL text, bind parameters, database URLs, and credentials are never attached to spans. The acceptance
suite also exercises a failed parameterized query; error spans record only the exception type, never
the driver's raw exception message. The PostgreSQL acceptance
test uses `InMemorySpanExporter` and verifies that authenticated API and PostgreSQL spans share a trace
and direct parent relationship without statement or parameter capture.

## 4. Prometheus metrics

`GET /metrics` exposes the application-owned registry in Prometheus' canonical text format. It
requires an authenticated `ADMIN` or `OPERATOR`; other roles receive `403` and missing credentials
receive `401`. The scrape itself is excluded from request metrics.

| Metric | Labels | Purpose |
| --- | --- | --- |
| `agora_http_requests_total` | `method`, route template, `status` | HTTP request rate and errors |
| `agora_http_request_duration_seconds` | `method`, route template | HTTP latency |
| `agora_db_query_duration_seconds` | bounded operation, `outcome` | database latency and errors |
| `agora_db_transactions_total` | `outcome` | commit/rollback counts |
| `agora_port_errors_total` | `port`, `kind` | adapter failures |
| `agora_event_publishes_total` | `subject`, `outcome` | event publication outcomes |
| `agora_ready` | none | aggregate readiness state |

HTTP labels always use the matched route template, never a raw path or identifier. Database labels use
bounded operation names; statements and table/user values are forbidden labels.

## 5. Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | standard Python log threshold |
| `LOG_FORMAT` | `json` | `json` or local-development `console` |
| `OTEL_SERVICE_NAME` | `agora-api` | OpenTelemetry service name |
| `OTEL_EXPORTER_ENDPOINT` | empty | OTLP HTTP collector base URL |
| `CODE_VERSION` | `dev` | resource, span, and log version correlation |

## 6. Verification

From `backend/`:

```bash
uv run ruff format --check app tests
uv run ruff check app tests
uv run mypy app tests
uv run pytest -m "not integration" -q
TEST_DATABASE_URL=postgresql+asyncpg://... \
  uv run pytest tests/integration/test_observability.py -q
```

The integration test registers an authenticated test-only route; no database probe route ships in the
production API. It skips explicitly when `TEST_DATABASE_URL` is absent. T1-12 may be closed only after
this test has run against PostgreSQL rather than skipped. That acceptance passed on 2026-09-05, followed
by the full six-test integration suite with no skips.