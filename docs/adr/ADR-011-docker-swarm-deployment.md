<!-- trace: NFR-013 -->
# ADR-011: Docker Swarm deployment

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 1
**Requirements:** NFR-012, NFR-013, NFR-004

## Context

The system is roughly a dozen services plus five stateful dependencies, deployed to a single region
by a team of one to three. The real requirements are declarative services, rolling updates, secrets
and an overlay network. The cost of the platform choice is measured in engineering hours not spent
building the product.

## Decision

Docker Swarm with one compose file per stack layer, encrypted overlay networks, Swarm secrets, and
rolling updates with automatic rollback. Operational detail lives in
[DOCKER_SWARM.md](../DOCKER_SWARM.md).

## Consequences

**Positive.** The whole deployment model fits in a head, which matters when the same people build the
reasoning engine. Compose is readable to a new contributor on day one. Local `docker compose` and
production Swarm share images by digest ([DEPLOYMENT.md §1](../DEPLOYMENT.md)).

**Negative.** No autoscaling, no operators, no CRDs, weaker multi-tenant isolation than Kubernetes,
and Swarm's ecosystem is shrinking. Stateful services are runbooks rather than controllers, so failover
is manual ([ADR-020](ADR-020-stateful-ha-boundary.md)).

**Neutral.** The service boundary is compose-agnostic; a Kubernetes migration is a deployment change,
not an architecture change, provided no Swarm-specific assumption leaks into service code.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Kubernetes (K3s/EKS) | the control plane and conceptual surface exceed the problem; would consume the MVP |
| Bare systemd units | no declarative rollout, no secrets story, no overlay network |
| PaaS (Fly, Render, ECS) | reasonable, but couples the research deployment to a vendor and complicates the sandbox boundary |
| Single docker-compose host | no rolling updates, no replica failover — fails NFR-013 |

## Links

[ARCHITECTURE.md §1](../ARCHITECTURE.md) · [DOCKER_SWARM.md](../DOCKER_SWARM.md) ·
[DEPLOYMENT.md](../DEPLOYMENT.md) · [ADR-020](ADR-020-stateful-ha-boundary.md)
