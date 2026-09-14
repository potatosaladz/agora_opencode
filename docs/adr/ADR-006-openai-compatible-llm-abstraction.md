# ADR-006: OpenAI-compatible LLM abstraction

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 1
**Requirements:** FR-206, NFR-014, NFR-011

## Context

The platform must run heterogeneous agents across different models, and must not be rewritten when a
provider changes, prices up, or disappears. Vendor SDKs leak their own types, retry semantics and
streaming shapes into application code, which is precisely how lock-in becomes architectural.

## Decision

One internal `LLMProvider` port with an OpenAI-compatible chat-completions shape as the lingua franca.
Adapters: OpenAI, Anthropic (translated), local engines behind an OpenAI-compatible server
(vLLM / Ollama), and a deterministic `mock` used in CI. Provider-specific capabilities are declared
in a capability descriptor rather than exposed as extra methods.

## Consequences

**Positive.** Model heterogeneity is configuration. The mock provider makes `REPLAY_STRICT` and
deterministic CI possible. Capability negotiation (structured output, tool calling, context length)
is explicit, so an agent definition cannot silently assume a feature the model lacks.

**Negative.** The lowest-common-denominator interface loses provider-specific strengths — Anthropic's
cache control, OpenAI's reasoning parameters — unless modelled as declared capabilities, which takes
discipline. "OpenAI-compatible" is a de facto standard, not a specification, so adapters carry
compatibility quirks.

**Neutral.** Where a capability genuinely has no common shape, the port grows a capability-gated
method rather than leaking the SDK.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Vendor SDKs directly | lock-in in every call site; untestable without live credentials |
| A gateway product (LiteLLM, OpenRouter) | a reasonable adapter target, but not an excuse to skip our own port; adds a dependency in the critical path |
| LangChain / LlamaIndex abstractions | opinionated about orchestration we already own; their interfaces are not our invariants |

## Links

[PORTS.md §4](../PORTS.md) · [AGENT_MODEL.md](../AGENT_MODEL.md) ·
[REPRODUCIBILITY.md §3](../REPRODUCIBILITY.md)
