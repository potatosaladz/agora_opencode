# Extending the Platform

**Version:** 1.0 · **Status:** design
**Depends on:** [PORTS.md](PORTS.md), [ARCHITECTURE.md §2](ARCHITECTURE.md),
[STRUCTURED_REASONING.md](STRUCTURED_REASONING.md) · **Requirements:** NFR-014, FR-206, FR-608

## 1. The extension surface

Everything pluggable sits behind a port. If you find yourself editing the coordinator to add a
capability, the design has been violated — open an issue instead of shipping it.

| To add… | Implement | Register in | Tests required |
| --- | --- | --- | --- |
| an LLM provider | `LLMProvider` | composition root | contract suite + mock parity |
| a consensus strategy | `ConsensusStrategy` | strategy registry | formal doc + unit + property |
| a metric | `MetricPlugin` | metric registry | hand-computed value + M-4 property |
| a retrieval backend | `VectorStore` / `Retriever` | adapter registry | contract suite + pre-filter test |
| a symbolic engine | `SymbolicReasoner` | engine registry | SAT/UNSAT/UNKNOWN parity + determinism |
| a simulation engine | `SimulationEngine` | engine registry | spec validation + seed determinism |
| an external tool | MCP server + registry entry | gateway registry | policy matrix + injection suite |
| an agent role | agent definition (data, not code) | agent registry | envelope conformance |
| a protocol | `Protocol` | protocol registry | round invariants + sealed-round test |
| an artifact kind | taxonomy change (see §4) | schema + graph | migration + graph validator + docs |

## 2. Port discipline

- **P-1** A port is an interface plus its data contracts, defined in `core/ports/`. Adapters live
  in `adapters/`. Nothing in `core/` imports an adapter.
- **P-2** Ports declare their failure taxonomy: `TransientPortError` (retry), `PermanentPortError`
  (degrade), `BudgetPortError` (stop). An adapter raising a bare `Exception` breaks the
  coordinator's decision logic, so the contract suite rejects it.
- **P-3** Every adapter declares the manifest fields it needs
  ([REPRODUCIBILITY.md §2](REPRODUCIBILITY.md)). No declaration, no registration.
- **P-4** Adapters are selected by configuration at the composition root; runtime switching of a
  stateful adapter is forbidden.
- **P-5** Each port ships a `Fake*` used by tests and a `Mock*` used by local dev
  ([TESTING.md §3](TESTING.md)).

## 3. Adding a consensus strategy

The most consequential extension type, because a bad strategy silently corrupts the headline
output.

1. Write the formal document first, in `docs/consensus-formalism/<name>.md`: inputs, math, outcome
   mapping, invariants preserved, worked example, failure modes, and which of C-1 … C-8 it can
   violate. **FR-608 / S-1: no document, no registration.**
2. Implement `evaluate(ctx) -> ConsensusResult` as a pure function of `ConsensusContext` (S-4).
3. Implement `explain(result) -> Explanation` — total, never empty (C-3).
4. Register with an id, a semver `version`, and a parameter schema.
5. Tests: hand-computed example, property tests for monotonicity and the feasibility gate, a
   degenerate-input test, and a comparison run against `weighted` on the golden fixture.
6. Add the strategy to the registry table in [CONSENSUS_MODEL.md §7](CONSENSUS_MODEL.md) and to
   [MVP_BOUNDARY.md §2](MVP_BOUNDARY.md) if it is not research-only.

## 4. Changing the artifact taxonomy

The taxonomy is the platform's ontology; changing it is a schema migration, a graph migration and
a documentation change at once.

1. Propose the change with the requirement it serves and the confusion it removes.
2. Update [STRUCTURED_REASONING.md](STRUCTURED_REASONING.md) — the single definition site — and
   every table that enumerates kinds.
3. Bump `artifact_schema_version`; additive changes only within a major
   ([REPRODUCIBILITY.md §6](REPRODUCIBILITY.md)).
4. Write the migration: expand, backfill, then contract in a later release.
5. Update `REASONING_GRAPH.md` edge legality rules and the graph validator's test matrix.
6. Update the API contract, regenerate types, run the contract suite.
7. Record it in [../project/DECISIONS.md](../project/DECISIONS.md), and as an ADR if it changes who
   may author what.

## 5. Adding a metric

Follow §8 of [METRICS.md](METRICS.md). Short version: six fields, one caveat, a gaming row, a
hand-computed test, and a home in a profile dimension. A metric that fits no dimension is usually a
composite in disguise.

## 6. Plugins and third-party code

- Plugins load by entry point, are versioned, and run **inside the same sandbox boundary as
  generated code** — no database credentials in a plugin's environment.
- A plugin may read committed artifacts and propose new ones. It may not commit, transition status,
  or call `WRITE` tools: the same authority boundary as an agent, deliberately.
- Plugin failures degrade to `NOT_APPLICABLE` for metrics and to a labelled omission for retrieval;
  they never abort a round.

## 7. Research-track extensions

Anything in the *(research)* column of [MVP_BOUNDARY.md §2](MVP_BOUNDARY.md) uses the same mechanism
plus three rules: off by default, writes to an isolated namespace, and cannot be enabled in `prod`
without a recorded decision. Research must not leak into the product through configuration drift.

## 8. Review checklist for any extension PR

- [ ] Port implemented, no coordinator edit
- [ ] Failure taxonomy declared and mapped
- [ ] Manifest fields declared; strict replay still passes
- [ ] Formal doc or spec updated where required (strategies, metrics, taxonomy)
- [ ] Traceability row added; every new invariant id cited in code
- [ ] Docs cross-referenced both ways (no orphan documents)
- [ ] `docs/README.md` index updated
- [ ] Tests: unit, property, contract, and one failure-injection case
- [ ] Threat register row if a new boundary or input path appears
- [ ] CHANGELOG entry

## 9. Related

[PORTS.md](PORTS.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [CONSENSUS_MODEL.md](CONSENSUS_MODEL.md) ·
[METRICS.md](METRICS.md) · [MVP_BOUNDARY.md](MVP_BOUNDARY.md) · [ANTI_PATTERNS.md](ANTI_PATTERNS.md)


