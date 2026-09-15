# Technical Context

**Version:** 1.0 · **Last reviewed:** 2026-09-04
Records the concrete technology environment the project targets, plus the tooling
commands that later phases must use.

---

## 1. Runtime targets

| Layer | Technology | Version target | Notes |
| --- | --- | --- | --- |
| Language | Python | 3.12+ | `match`, typed, `asyncio`-first |
| API framework | FastAPI | latest 0.1xx | OpenAPI must stay accurate |
| Validation/contracts | Pydantic | v2 | `schema_version` on persisted contracts |
| ORM | SQLAlchemy | 2.x | async engine, typed ORM style |
| Migrations | Alembic | latest | reversible migrations only |
| HTTP client | httpx | latest | used by OpenAI-compatible adapter |
| MCP | Official Python SDK | 1.30.0 / protocol 2025-06-18 | Streamable HTTP through the outbound-only gateway |
| Durable workflow | Temporal | Python SDK 1.32.x / server 1.29.1 | via `WorkflowEngine` port; exact versions locked in `backend/uv.lock` and Compose |
| Event bus | NATS JetStream | 2.10+ | via `EventBus` port |
| RDBMS | PostgreSQL | 16+ | system-of-record |
| Vectors | pgvector | 0.7+ | via `VectorStore` port |
| Document parsing | pypdf, python-docx, openpyxl, Beautiful Soup | 6.x, 1.x, 3.x, 4.x | format adapters only; normalized output enters typed ingestion domain |
| Object store | MinIO | RELEASE.2024+ | S3-compatible, via `ObjectStore` |
| Cache/coordination | Redis | 7.x | ephemeral only |
| Symbolic | Z3 (z3-solver) | 4.12+ | via `SymbolicReasoner` port |
| Observability | OpenTelemetry, Prometheus, Grafana, optional Loki | — | trace correlation end-to-end |
| Frontend | React + TypeScript + Vite | React 18/19, TS 5.x | no SSR requirement |
| Data fetching | TanStack Query | v5 | |
| Graph UI | React Flow | v12 | reasoning graph explorer |
| Math rendering | KaTeX | — | consensus formulas, formal explanations |
| Deployment | Docker Compose (dev) / Docker Swarm (prod-like) | Engine 25+ | `docker-stack.yml` |

## 2. Quality tooling

| Tool | Purpose | Command |
| --- | --- | --- |
| pytest | unit/integration/e2e | `pytest` |
| pytest-asyncio | async tests | configured `asyncio_mode = auto` |
| mypy | static typing | `mypy backend/app` |
| Ruff | lint + format | `ruff check backend frontend --fix` / `ruff format` |
| AST import-boundary gate | enforce ADR-012 dependency direction | `cd backend && pytest tests/test_layering.py` |
| ESLint + Prettier | frontend | `npm run lint` / `npm run format` |
| bandit / pip-audit | Python security | `pip-audit -r requirements.txt` |
| npm audit | frontend security | `npm audit` |
| hadolint | Dockerfile lint | `hadolint backend/Dockerfile` |
| Mermaid CLI (optional) | diagram validation | `npx @mermaid-js/mermaid-cli -i docs/ARCHITECTURE.md` |

## 3. Repository conventions

- **Layout:** `backend/app/{api,domain,application,ports,adapters,security,observability,common}`,
  `frontend/src/{app,features,components,lib,types}`. Guidance only; deviation requires an ADR.
- **Naming:** `snake_case` modules/functions, `PascalCase` classes, `UPPER_SNAKE` constants,
  `kebab-case` URL paths, `SCREAMING_SNAKE` event types (`CLAIM_PROPOSED`).
- **Imports:** absolute from `app.`; no cross-domain imports except through ports.
- **Async:** all I/O `async`; no blocking calls inside event loop or Temporal workflows.
- **Determinism:** Temporal workflow code must be deterministic — no network, no
  `random`, no wall-clock reads, no direct LLM calls. All such work is an Activity.
- **IDs:** UUIDv7 (time-ordered) for entity and event identifiers.
- **Time:** UTC everywhere; store `timestamptz`; serialize ISO-8601.
- **Versions:** entity `version` is an integer artifact revision; `schema_version` is the
  contract revision; `code_version` is the git commit recorded on events.
- **Errors:** typed domain exceptions; never bare `except:`; failures emit structured events.
- **Secrets:** never logged, never in URLs, always redacted in API responses.

## 4. Environment configuration

- `pydantic-settings` reads layered config: defaults → `.env` (dev) → Docker Secrets
  (swarm) → runtime overrides per workspace.
- Every external dependency is selected by an env var naming an adapter
  (e.g. `LLM_PROVIDER=openai_compatible|mock`, `VECTOR_STORE=pgvector`,
  `EVENT_BUS=nats|inmemory`, `WORKFLOW_ENGINE=temporal|inmemory`).
- `.env.example` is committed; `.env` is not. No secret literal in tracked files.
- Tests must run fully offline against `MockLLMProvider` and in-memory adapters.

## 5. Local development commands (Phase 1+)

```bash
# full Phase 1 development stack (copy .env.example to .env and fill values first)
# Compose project name is `agora_opencode`; host ports default to the 1xxxx range
# (POSTGRES_HOST_PORT=15432, BACKEND_HOST_PORT=18000, FRONTEND_HOST_PORT=13000, ...)
# so this stack can run side-by-side with the original `agora` development stack.
docker compose up --build --wait
curl http://127.0.0.1:18000/ready

# backend on the host
cd backend
uv sync --extra dev --frozen
uv run uvicorn app.api:create_app --factory --reload
temporal server start-dev          # local temporal (or via compose)
pytest -q
# PostgreSQL migration/RLS and pgvector integration proofs
TEST_DATABASE_URL=postgresql+asyncpg://... pytest tests/integration/test_postgres_migrations.py tests/integration/test_pgvector_store.py -q
# Redis ephemeral-only integration proof (server persistence must be disabled)
TEST_REDIS_URL=redis://... pytest tests/integration/test_redis_cache.py -q
# MinIO object integrity and list-denial integration proof
TEST_MINIO_ENDPOINT=... TEST_MINIO_ACCESS_KEY=... TEST_MINIO_SECRET_KEY=... pytest tests/integration/test_minio_object_store.py -q

# frontend
cd frontend && npm ci && npm run dev

# stop the stack (add -v only when intentionally deleting local data)
docker compose down
```

## 6. Development host context (verified 2026-09-04, T1-00)

- OS: Windows (win32), PowerShell shell. Paths in this repository are relative; no
  absolute path may appear in code, config or docs.
- Workspace root is a shared chat workspace; this project is self-contained in its own
  folder with its own Git repository.

### 6.1 Measured toolchain

| Tool | Version | Status | Note |
| --- | --- | --- | --- |
| Python | 3.13.12 | ✅ | exceeds the 3.12+ target; `requires-python = ">=3.12"` |
| pip | 25.3 | ✅ | `uv` is preferred for local work |
| uv | 0.10.12 | ✅ | used for venv + install; lockfile is `uv.lock` |
| Node.js | 24.14.0 | ✅ | exceeds the 20+ target |
| npm | 11.9.0 | ⚠️ | works only as **`npm.cmd`** — see 6.2 |
| Docker Engine | 29.7.2 | ✅ | daemon running |
| Docker Compose | v5.4.0 | ✅ | `docker compose` (v2 syntax) |
| Git | 2.53.0 | ✅ | identity is a placeholder — see [../project/ERRORS.md](../project/ERRORS.md) E-06 |
| ruff | not installed globally | ✅ expected | it is a dev dependency, run from the venv |
| PyPI reachability | HTTP 200 | ✅ | dependency install and test execution are possible on this host |

### 6.2 Windows shell constraints (real, and they will bite again)

- **`npm` fails under PowerShell.** The shell resolves `npm` to `npm.ps1`, and script
  execution is disabled on this host (`UnauthorizedAccess`). Use `npm.cmd` / `npx.cmd`,
  or run from `cmd.exe`. CI uses `cmd`-free Linux runners and is unaffected.
- **PowerShell mangles multi-line and parallel command output** into the terminal capture; prefer one
  command per invocation, or redirect each command to a separate file, when a result must be exact.
- **No `&&` in PowerShell 5.x-compatible contexts**; sequence with `;` and check `$LASTEXITCODE`.

## 7. Dependency policy

- Prefer the standard library; add a dependency only when it removes real complexity.
- Every dependency is pinned via lockfiles (`uv.lock`/`requirements.lock`,
  `package-lock.json`).
- No framework may leak into the domain layer — specifically no LangChain-style
  orchestration dependency in `app/domain` or `app/ports`.
- Plugin extension points are Python `Protocol`/ABC, not a bespoke plugin framework,
  until at least two real implementations exist (see ADR-012 §Consequences).
