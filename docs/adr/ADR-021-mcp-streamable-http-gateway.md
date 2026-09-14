<!-- trace: FR-1001, NFR-010, NFR-012, NFR-015, NFR-016, NFR-020 -->
# ADR-021: MCP Streamable HTTP outbound gateway

**Status:** accepted · **Date:** 2026-09-15 · **Phase:** 15
**Requirements:** FR-1001, NFR-010, NFR-012, NFR-015, NFR-016, NFR-020

## Context

Reasoning workers need controlled access to external tools, but a worker that can connect directly to an MCP
server can bypass tool classification, workspace policy, approval, audit and output containment. Existing
architecture names a stateless `mcp-gateway`, but did not freeze the MCP version, transport, service identity
or network path. Browser SSE does not solve bidirectional MCP requests, lifecycle or cancellation.

## Decision

Agora uses MCP as an outbound tool gateway, never as a general inbound server for Agora domain services.
Protocol version is exactly `2025-06-18`. The official Python MCP SDK is pinned by T15-01. Both the internal
worker-to-gateway link and gateway-to-upstream link use MCP Streamable HTTP. The gateway exposes tools only;
resources and prompts are not advertised.

Worker calls authenticate with a short-lived OAuth2 client-credentials workload JWT whose audience is
`mcp-gateway`; mTLS may supplement but not replace this identity. Trusted call context binds workspace,
session, exact agent definition/version, initiating actor, operation and correlation identity. The gateway is
stateless: sessions/pools are ephemeral and restart requires initialize and discovery again.

Compose/Swarm separate `application_internal`, existing model `provider_egress`, and gateway-only
`mcp_egress` for self-hosted/test servers. Remote servers are reached through a gateway-only outbound
workload/network policy; workers cannot use that path. Tool results are untrusted content-hashed evidence
candidates and the gateway has no reasoning artifact or ledger commit port.

## Consequences

**Positive.** There is one enforceable MCP egress path, one protocol/transport contract, a testable workload
identity boundary, and no accidental coupling to browser SSE or Agora domain APIs. A stateless gateway can
replicate and restart without owning domain state.

**Negative.** The gateway is an additional network hop and availability dependency. Streamable HTTP excludes
stdio-only servers unless a separately approved adapter fronts them. Workload token issuance, private network
segmentation, cancellation forwarding and two MCP client/server roles increase operational complexity.

**Neutral.** Registry, approvals, limits, durable audit, injection quarantine and SSRF enforcement remain
T15-02…04. T15-01 uses only one deterministic fixture tool and no production allowlist.

## Alternatives considered

| Option | Why rejected |
| --- | --- |
| Direct MCP clients in workers | cannot enforce sole egress; every worker holds credentials and policy drifts |
| Agora as a public inbound MCP server | not required; exposes internal authority and reverses the Phase 15 direction |
| Browser SSE | one-way UI event delivery, not MCP lifecycle/invocation/cancellation |
| stdio production transport | unsuitable between separately deployed replicated services; process ownership and scaling couple |
| legacy HTTP+SSE MCP transport | superseded by Streamable HTTP and creates another lifecycle surface |
| Custom JSON-RPC implementation | duplicates the official SDK and increases protocol/security drift |

## Links

[PHASE15_ACCEPTANCE.md](../PHASE15_ACCEPTANCE.md) · [MCP_SECURITY.md](../MCP_SECURITY.md) ·
[SECURITY.md](../SECURITY.md) · [ARCHITECTURE.md](../ARCHITECTURE.md) ·
[DOCKER_SWARM.md](../DOCKER_SWARM.md) · [PORTS.md §11](../PORTS.md)

The pinned protocol specification is
[MCP 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18); dependency version pinning belongs
to T15-01 and cannot silently change the protocol contract.
