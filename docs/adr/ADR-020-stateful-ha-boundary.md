<!-- trace: NFR-004 -->
# ADR-020: Accept a manual high-availability boundary for stateful services

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 1
**Requirements:** NFR-004, NFR-012, NFR-013

## Context

Automatic failover for Postgres, MinIO and Temporal is a large operational surface: consensus agents,
fencing, split-brain handling, and a testing burden that never ends. The MVP is a single-region
research deployment where a five-minute interruption is an inconvenience and a corrupted ledger is fatal
to the project's purpose.

## Decision

Accept manual failover for stateful services and spend the saved effort on data safety instead:
streaming replica with a written promotion runbook, continuous WAL archiving to two locations, monthly
tested restore drills, and automatic failover only for stateless services
([DOCKER_SWARM.md §8, §9](../DOCKER_SWARM.md)).

## Consequences

**Positive.** RPO stays tight (≤ 5 min) while RTO is a documented human action rather than an
undocumented hope. The restore drill is the control that makes "we have backups" mean something.
Complexity is spent where a failure is unrecoverable — the ledger — and not where it is merely
annoying.

**Negative.** Availability is lower than an automated system could provide, and a failover requires
someone who has read the runbook to be awake. That is an honest trade, stated rather than hidden.

**Neutral.** The upgrade path is a Kubernetes operator or a managed database, and it is triggered by
measured downtime, not by taste.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Patroni + automatic promotion | right answer at scale; here it adds a consensus system to debug |
| Managed cloud Postgres | reasonable, but couples the research deployment to a vendor (ADR-011) |
| Multi-region active-active | far beyond MVP need, and distributed consensus is not the research question |
| No replica at all | unacceptable: WAL archiving without a warm replica makes RTO hours |

## Links

[DOCKER_SWARM.md §8](../DOCKER_SWARM.md) · [ARCHITECTURE.md §1](../ARCHITECTURE.md) ·
[ADR-011](ADR-011-docker-swarm-deployment.md) · [MVP_BOUNDARY.md §2](../MVP_BOUNDARY.md)
