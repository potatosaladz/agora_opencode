# Deployment Guide

**Version:** 1.0 · **Status:** design
**Runtime topology:** [DOCKER_SWARM.md](DOCKER_SWARM.md) · **Requirements:** NFR-012, NFR-013,
NFR-014

## 1. Environments

| Env | Purpose | Data | Providers | Access |
| --- | --- | --- | --- | --- |
| `local` | development, `docker compose` (not Swarm) | seeded fixture DB | mock provider by default | developer |
| `ci` | ephemeral, per-PR | throwaway Postgres/Redis, mock provider | mock | CI only |
| `staging` | release candidate, full stack on Swarm | synthetic corpus plus one anonymised real task | real, low limits | team |
| `prod` | the research deployment | real workspaces | real | operators, audited |

**E-1** `local` uses the same images as `prod`, built once and promoted by digest. A `docker
compose up --build` that recompiles for production is a defect.
**E-2** The mock LLM provider is deterministic and seeded, which is what makes `REPLAY_STRICT`
testable in CI ([REPRODUCIBILITY.md §4](REPRODUCIBILITY.md)).
**E-3** Staging runs the same migrations as prod, one release ahead of the gate.

## 2. Local development

```bash
cp .env.example .env                 # non-secret config only
make up            # compose: infra + services with the mock provider
make seed          # fixture workspace, sources, agents, one completed session
make test          # unit + integration against the compose stack
make e2e           # playwright against http://localhost:13000 (frontend host port)
make down -v
```

Real provider keys go in `.env.local`, which is gitignored; nothing reads them in CI. The
append-only ledger, RLS and the graph all work locally, so a bug that depends on them is
reproducible on a laptop — that property is deliberate and is a reason the stack is compose-first.

## 3. Configuration layering

Highest precedence wins:

```text
1. runtime docker config / secret mounts     (prod)
2. environment variables                      (staging, ci)
3. config/<env>.toml                          (committed, non-secret)
4. code defaults                              (must be safe: no credentials, mock adapters)
```

- Defaults are safe: adapters default to `mock`, budgets default low, debug default off.
- Any config key read by a service is declared in its `config.py` schema; an undeclared key is a
  startup error, which catches typos that would otherwise silently change behaviour.
- The effective configuration (names, not values) is logged at start and included in the session
  manifest where it can influence an outcome.

## 4. CI pipeline

| Stage | Runs | Gate |
| --- | --- | --- |
| lint | ruff, mypy, eslint, prettier, `hadolint`, markdownlint | blocking |
| unit | pytest, vitest | blocking |
| contract | OpenAPI validation, schema conformance, typegen diff | blocking |
| integration | Postgres + Redis + NATS + Temporal testcontainers | blocking |
| trace-check | `TRACEABILITY.csv` orphans, link check across `docs/` | blocking |
| replay | `REPLAY_STRICT` on the fixture session, byte-identical assertion | blocking |
| e2e | playwright on the compose stack | blocking |
| build | images by digest, SBOM, Trivy, sign | blocking on critical CVE |
| deploy:staging | on `main` after green | automatic |
| deploy:prod | on tag | manual approval |
| restore-drill | monthly scheduled job | reported, blocks the next release if failing |

The `replay` stage is the one most projects skip and the one that keeps the research claim honest.

## 5. Release checklist

1. `git tag` the release candidate; images built and signed.
2. Migration review: expand-only, backward-compatible, tested against a prod-sized copy.
3. Traceability: every requirement claimed done in `memory-bank/tasks.md` is `implemented` in a
   green CI run ([TRACEABILITY.md §7](TRACEABILITY.md)).
4. Docs: [README.md](README.md) index current, [../CHANGELOG.md](../CHANGELOG.md) updated, any new
   ADR linked.
5. Staging soak: ≥ 24 h with one real-shaped session, checking RB-05 and CE-04.
6. Announce the config and API deltas, with `Deprecation` headers where applicable.
7. Deploy prod: infra unchanged, platform rolling, integrations last.
8. Verify: `/ready` green, replay of the golden session passes against prod, ledger chain
   verification clean.
9. Record the release in [../project/CURRENT_STATE.md](../project/CURRENT_STATE.md).

## 6. Rollback

| Situation | Action |
| --- | --- |
| Bad image, no schema change | `docker service update --image-hashes-by-… <previous digest>` — seconds |
| Schema changed | roll back the **code**, keep the schema; expand-only migrations make this safe |
| Data written by the new version must be unreadable by the old | forward-fix instead of rollback; this is why NFR-014 requires a compatibility window |
| Migration itself is broken | `migrate downgrade` one step, only if the migration declares itself reversible; otherwise restore from the last verified backup |
| Config or secret wrong | update the config/secret object and restart the service; no image change |

A rollback is a recorded event with the reason, and the reason becomes a row in
[../project/ERRORS.md](../project/ERRORS.md).

## 7. Capacity planning

| Resource | Sizing rule at MVP scale |
| --- | --- |
| Postgres | 4 vCPU / 16 GB / NVMe for ≤ 50 concurrent sessions; the graph is the hot path, so index `graph_edges(src,dst,type)` and `artifacts(session,kind)` first |
| agent-worker | 1 vCPU / 2 GB per concurrent turn; bound by provider rate limits, not CPU |
| coordinator | 2 vCPU / 4 GB, single active replica |
| Temporal | 2 vCPU / 4 GB app server |
| MinIO | 200 GB per 10 k documents, versioned |
| Sandbox node | isolated, 4 vCPU / 8 GB, no secrets |

Scale `agent-worker` first; if that does not help, the bottleneck is a provider or the database,
and the traces will say which.

## 8. Related

[DOCKER_SWARM.md](DOCKER_SWARM.md) · [ARCHITECTURE.md §1](ARCHITECTURE.md) ·
[REPRODUCIBILITY.md](REPRODUCIBILITY.md) · [SECURITY.md](SECURITY.md) · [TESTING.md](TESTING.md) ·
[PORTS.md](PORTS.md)
