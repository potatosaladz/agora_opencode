<!-- trace: FR-801 -->
# ADR-018: Sandbox execution boundary for generated and third-party code

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 8
**Requirements:** FR-801 … FR-806, FR-1001 … FR-1007, NFR-010

## Context

Simulation models, agent-authored analysis code and MCP tool servers all execute code the platform did
not write. Running any of it in a service process means one bad model can read the database
credentials of a service that can write the ledger.

## Decision

All execution of generated or third-party code goes through the `SandboxExecutionProvider` port into
an isolated container: no network egress, read-only input mounts, CPU / memory / pid / wall-clock caps,
byte-limited stdout, and results returned as digests plus a schema-validated payload. Sandbox nodes
carry no secrets and have no route to the `data` overlay
([DOCKER_SWARM.md §4](../DOCKER_SWARM.md)).

## Consequences

**Positive.** The threat model can assume hostile code inside the sandbox rather than hoping it is
benign ([THREAT_MODEL.md §2](../THREAT_MODEL.md)). Resource caps make cost exhaustion a bounded event.
The same boundary serves simulation, code execution and future plugin loading
([EXTENDING.md §6](../EXTENDING.md)).

**Negative.** Container startup latency per run, and a real operational burden: image supply chain,
kernel exposure, escape risk. Caps mean some legitimate heavy models simply fail, and must be
re-scoped.

**Neutral.** gVisor or Firecracker is a stronger isolation answer and is the planned upgrade if
agent-authored code ever runs by default rather than on request.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Run in-process with a timeout | no memory, filesystem or network isolation; a timeout is not a boundary |
| Separate VMs per run | strongest isolation, unacceptable latency and ops cost for this scale |
| Trust model-generated code behind review | the code is generated per session; review does not scale to the threat |
| WebAssembly sandbox | attractive future option; the Python scientific stack we need is not WASM-shaped today |

## Links

[SIMULATION_ARCHITECTURE.md §5](../SIMULATION_ARCHITECTURE.md) · [MCP_SECURITY.md](../MCP_SECURITY.md) ·
[SECURITY.md §8](../SECURITY.md) · [PORTS.md §11](../PORTS.md)
