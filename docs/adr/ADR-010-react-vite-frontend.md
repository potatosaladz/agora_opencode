# ADR-010: React + Vite single-page frontend

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 14
**Requirements:** FR-501 … FR-506, NFR-007, NFR-019

## Context

The UI's job is interrogation: a graph explorer, a provenance drill-down, a dissent panel and a live
session view. That is a stateful, interactive client, not a document server. It must consume the
generated API types so that a contract change breaks the build rather than a user's understanding
([API_CONTRACTS.md §2](../API_CONTRACTS.md)).

## Decision

React 18 with TypeScript under Vite, TanStack Query for server state, a thin SSE client for the event
stream, and a canvas/SVG graph view. No Next.js, no client-side data store that duplicates the
backend, no UI-computed metrics.

## Consequences

**Positive.** Typegen plus strict mode means the UI cannot read a field the contract does not define.
Vite keeps the loop fast. Server-state caching by query key maps cleanly onto immutable artifacts.

**Negative.** A SPA needs its own accessibility and performance discipline; the initial bundle for
the graph view must be code-split. No server rendering, so first paint on a cold session is the weak
point.

**Neutral.** The boundary contract is framework-agnostic; a rewrite would reuse `contracts/` intact.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Next.js / SSR | the app is behind auth with no SEO requirement; SSR adds a runtime to operate |
| HTMX plus templating | excellent for forms, wrong for a live graph explorer |
| Svelte | pleasant, but the team's typegen and component-test tooling is React-shaped |
| Retool / admin frameworks | cannot express the explanation-first UI this project exists for |

## Links

[ARCHITECTURE.md §2](../ARCHITECTURE.md) · [EXPLAINABILITY.md](../EXPLAINABILITY.md) ·
[TESTING.md §7](../TESTING.md)
