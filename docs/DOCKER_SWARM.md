# Docker Swarm Deployment

**Version:** 1.0 · **Status:** design
**ADR:** [ADR-011](adr/ADR-011-docker-swarm-deployment.md) · **Topology:**
[ARCHITECTURE.md §1](ARCHITECTURE.md) · **Ports:** [PORTS.md](PORTS.md) ·
**Requirements:** NFR-012, NFR-013, NFR-004

## 1. Why Swarm

Swarm delivers the four things actually needed — declarative services, rolling updates, secrets,
overlay networking — without operating a control plane that would consume more engineering time
than the product. Kubernetes is the eventual default for multi-region; it is not required for a
single-region research deployment
([ADR-011](adr/ADR-011-docker-swarm-deployment.md)).

The consequence to accept: no autoscaling, no CRDs, no operators. Needing those is a signal to
revisit the decision, not to hack around it.

<!-- trace: NFR-012 -->
## 2. Node layout

| Role | Count | Runs | Notes |
| --- | --- | --- | --- |
| manager | 3 | Swarm control plane, RAFT quorum | `--availability drain` for app workloads |
| app | 2+ | gateway, coordinator, agent-worker, web-ui | scale horizontally |
| data | 2 | Postgres primary + replica, MinIO, Temporal, NATS | labelled `role=data` |
| sandbox | 1+ | simulation and code-execution tasks | no overlay access to `data` |

```yaml
deploy:
  placement:
    constraints: [node.labels.role == app]
```

Placement constraints are declared in the stack files, never improvised.

## 3. Stack files

```text
deploy/
  stacks/
    00-infra.yml          postgres, pgbouncer, redis, minio, temporal, nats
    10-platform.yml       coordinator, agent-worker, api-gateway, realtime-gateway, web-ui
    20-integrations.yml   mcp-gateway, retrieval-service, symbolic-service, simulation-service
    30-observability.yml  prometheus, grafana, loki, alertmanager
  secrets/                secret *files*, never values
  config/                 per-environment .env (non-secret config only)
  scripts/                bootstrap.sh, deploy.sh, migrate.sh, backup.sh, restore-drill.sh
```

Deploy order matters: infra before platform, platform before integrations. `deploy.sh` enforces it
with a readiness wait, not a `sleep`.

## 4. Networks

| Network | Driver | Attached to |
| --- | --- | --- |
| `edge` | overlay, `attachable: false` | api-gateway, realtime-gateway, web-ui |
| `application_internal` | overlay, `internal: true` | platform services including reasoning-worker and mcp-gateway |
| `data` | overlay, encrypted | services plus data nodes only |
| `sandbox` | overlay, `internal: true`, no route to `data` | simulation-service, sandbox tasks |
| `mcp_egress` | overlay; no published ports | `mcp-gateway` plus approved MCP fixture/self-hosted servers only |

Published ports exist only on `edge`; the full table is [PORTS.md](PORTS.md), and CI asserts that
no stack file publishes a port absent from it.

Reasoning workers and `mcp-gateway` share `application_internal`, but workers do not attach to `mcp_egress`.
Existing approved LLM-provider egress is a separate path; Phase 15 proves only that workers cannot directly
reach MCP servers. Remote third-party servers do not attach to the overlay: the gateway's workload/network
policy is the only allowed outbound MCP path, while self-hosted/test servers share `mcp_egress` for executable
segmentation proof.
The deterministic fixture MCP server has no host-published port. See ADR-021 and
[PHASE15_ACCEPTANCE.md](PHASE15_ACCEPTANCE.md).

## 5. Secrets and config

```bash
# once per environment, from a file that never enters git
docker secret create llm_provider_key secrets/llm_provider_key.txt
```

- Secrets mount read-only at `/run/secrets/<name>`; nothing reads a secret from an environment
  variable ([ADR-017](adr/ADR-017-secret-provider-docker-secrets.md)).
- Rotation: create `<name>_v2`, then `docker service update --secret-rm <name>_v1 --secret-add
  <name>_v2`. No rebuild, no downtime.
- Non-secret config comes from `docker config` objects plus environment files. Every service prints
  its effective config at INFO on start — secret *names*, never values.

## 6. Rolling updates

```yaml
deploy:
  update_config:
    order: start-first        # stateless services only
    parallelism: 1
    delay: 20s
    failure_action: rollback
    monitor: 60s
    max_failure_ratio: 0.2
  rollback_config: { order: stop-first, parallelism: 1 }
```

| Service class | Order | Reason |
| --- | --- | --- |
| api-gateway, web-ui, realtime-gateway | `start-first` | keep the socket listening |
| agent-worker | `start-first` | stateless; drains its in-flight turn before exit |
| coordinator | `stop-first`, one active replica | two writers would break the ledger's total order |
| Temporal, Postgres, MinIO, NATS | manual, one at a time, replica first | stateful |

A failed update rolls back automatically and the incident is recorded in
[../project/ERRORS.md](../project/ERRORS.md).

## 7. Migrations

Migrations run as a one-shot service before the platform stack updates
(`deploy/scripts/migrate.sh`) and must be backward-compatible for one release: expand → migrate →
contract. NFR-014 forbids a deploy that breaks a running session mid-round; the coordinator drains
open rounds before restart and a session resumes from its workflow state.

<!-- trace: NFR-004 -->
## 8. Stateful services and the HA boundary

Per [ADR-020](adr/ADR-020-stateful-ha-boundary.md), the MVP accepts:

| Service | MVP posture | Failure behaviour |
| --- | --- | --- |
| Postgres | primary + streaming replica, manual promotion | replica promoted by runbook, ≤ 5 min RTO |
| MinIO | single node, versioned bucket, off-host sync | uploads fail loudly; retrieval serves from cache |
| Temporal | 1 app server on managed Postgres | workflow tasks pause, resume on recovery |
| NATS | 3-node cluster | fan-out continues on surviving nodes |
| Redis | single instance, no persistence | working state rebuilt from the ledger; cost only |

Multi-region and automatic failover are deferred; the runbook is the control.

## 9. Backup and restore

| What | How | Cadence | RPO |
| --- | --- | --- | --- |
| Postgres | `pg_basebackup` plus WAL archive to MinIO and an off-site bucket | continuous WAL, daily base | ≤ 5 min |
| MinIO objects | `mc mirror` off-site | hourly | ≤ 1 h |
| Secrets and configs | encrypted export in the operator vault, never in git | on change | — |
| Stack definitions | git, tagged per release | every release | — |

A restore that has not been tested is not a backup. `restore-drill.sh` rebuilds a stack from the
previous night's artefacts on a scratch host **monthly**, and the drill result is a recorded event.
The MVP gate requires one successful drill.

## 10. Health and observability

- Every service exposes `/health` (liveness) and `/ready` (dependency-checked readiness); Swarm
  `healthcheck` drives restarts and gates deploys.
- Prometheus for metrics, Loki for logs, OpenTelemetry for traces, with `trace_id` propagated into
  the ledger so a session and a request correlate ([AUDITABILITY.md](AUDITABILITY.md)).
- Alerts that matter: ledger chain verification failure, cross-tenant `404` spike, coordinator
  leader flapping, replication lag > 30 s, `agent-worker` queue depth, budget burn rate, retrieval
  degradation rate (RB-05).

## 11. Scaling

```bash
docker service scale platform_agent-worker=8      # the only horizontal lever in MVP
```

`agent-worker` scales with queue depth; the coordinator does not scale out (single writer).
Provider rate limits, not CPU, are the usual ceiling — the budget guard
([ARCHITECTURE.md §9](ARCHITECTURE.md)) protects the deployment from its own scale-out.

## 12. Troubleshooting runbook

| Symptom | First checks | Likely cause |
| --- | --- | --- |
| Session stuck in `RUNNING` | coordinator leader, Temporal task-queue backlog | lost leader or a poisoned activity |
| SSE not updating | realtime-gateway → NATS subscription, is `ledger_seq` advancing | dropped subscription; client must reconnect with `Last-Event-ID` |
| Rounds slow, no errors | provider latency, retrieval p95, reranker timeouts | provider or index, not the platform |
| `PORT_UNAVAILABLE` 503s | which port, circuit-breaker state | adapter down; degradation is expected and labelled |
| Task restart loop | `docker service logs --tail 200`, the `/ready` body | dependency not up, or a missing secret mount |
| Disk pressure on a data node | WAL archive lag, MinIO version pile-up | retention job not running |

## 13. Related

[DEPLOYMENT.md](DEPLOYMENT.md) · [ARCHITECTURE.md §1](ARCHITECTURE.md) · [PORTS.md](PORTS.md) ·
[SECURITY.md](SECURITY.md) · [adr/ADR-011](adr/ADR-011-docker-swarm-deployment.md)
