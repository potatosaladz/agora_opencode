# Agora backend

One Python package, `app/`, that is deployed under several roles (`api`,
`workflow-worker`, `reasoning-worker`, `rag-worker`, `simulation-worker`, `mcp-gateway`).
The roles share one import tree, one lockfile and one test suite — see
[../project/DECISIONS.md](../project/DECISIONS.md) D-15.

The normative design lives in [../docs/](../docs/README.md). This file covers only how to
work on the code.

## Layout and its enforcement

```text
app/
  domain/         entities and invariants. imports: ports, common
  application/    use cases.                    imports: domain, ports, common
  ports/          typing.Protocol contracts.    imports: common
  adapters/       SDKs live here and nowhere else
  composition/    the only package allowed to import adapters
  api/            FastAPI: routes, middleware, problem+json
  security/  observability/  db/  config/  common/
```

The import direction is not a convention. `tests/test_layering.py` walks the AST of every
module and fails the build on a forbidden edge, and it is itself tested with a deliberately
illegal fixture so the check cannot silently stop checking (T1-03).

## Commands

```bash
uv sync --extra dev --frozen
uv run ruff check app tests          # style lint
uv run pytest tests/test_layering.py # import-boundary lint (includes its mutation self-test)
uv run ruff format --check app tests # formatting gate
uv run mypy app tests                # types
uv run pytest                        # unit + contract; integrations skip without TEST_* vars
uv run pytest -m integration         # needs the compose stack and TEST_* vars
TEST_DATABASE_URL=postgresql+asyncpg://... uv run pytest tests/integration/test_observability.py -q
```

On Windows, after starting the root Compose stack, `powershell -File scripts/run-integration.ps1`
from the repository root loads the ignored `.env` values and runs every live adapter test without
printing credentials.

Tests never require network, a provider key, or a running database. Anything that would
need one is marked `integration` and skipped by default
([../memory-bank/techContext.md](../memory-bank/techContext.md) §4).

## Configuration

`app/config/settings.py` defines every knob; [../.env.example](../.env.example) documents the local
Compose credentials. Adapter selection is by name (`EVENT_BUS=nats|inmemory`), never by inline
construction, so the composition root is the only place that knows a class exists.

From the repository root, `docker compose up --build --wait` builds the locked image, runs Alembic and
bucket initialization, and waits for Postgres, Redis, MinIO, NATS, Temporal, and `/ready` to become
healthy. Temporal UI is available at `http://127.0.0.1:8080`. The `workflow-worker` service registers
the deterministic T4-02 session bootstrap workflow and its PostgreSQL lifecycle activity on the
`session-bootstrap` task queue.

## Observability

The app exposes authenticated Prometheus metrics to `ADMIN` and `OPERATOR` at `/metrics`, emits
application-owned OpenTelemetry traces, and uses recursively redacted structured logs. See
[../docs/OBSERVABILITY.md](../docs/OBSERVABILITY.md) for signal fields, cardinality rules, configuration,
and the PostgreSQL trace acceptance command.
