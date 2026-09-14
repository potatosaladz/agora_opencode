# Testing Strategy

**Version:** 1.0 · **Status:** design
**Requirements:** NFR-003, NFR-010, FR-506, FR-901, FR-1003 · **Traceability:**
[TRACEABILITY.md](TRACEABILITY.md) · **CI:** [DEPLOYMENT.md §4](DEPLOYMENT.md)

## 1. What is being tested

Not "does the code run" but "do the invariants hold". The platform's value is a set of negative
guarantees — no composite score, no suppressed dissent, no LLM-authored `FACT`, no feasibility
after ranking — and negative guarantees are only real if a test would fail when they break. Every
invariant id in `docs/` gets a named test.

| Invariant | Test name pattern |
| --- | --- |
| C-1 feasibility before ranking | `test_c1_feasibility_precedes_ranking` |
| C-7 deterministic result | `test_c7_same_input_hash_same_result` |
| E-2 no LLM path to `FACT` | `test_e2_fact_requires_human_or_symbolic` |
| FR-506 dissent cannot be omitted | `test_fr506_no_omit_parameter_exists` |
| FR-901 no composite score | `test_fr901_no_aggregate_field_anywhere` |
| FR-109 tenant isolation | `test_fr109_cross_workspace_denied` |
| NFR-003 replay | `test_replay_strict_byte_identical` |

## 2. Pyramid

| Layer | Scope | Speed | Notes |
| --- | --- | --- | --- |
| Unit | pure functions: strategies, normalization, metric formulas, DAG checks | ms | no I/O, no clocks, no randomness unless seeded |
| Property | invariants over generated inputs | ms | hypothesis; the workhorse for consensus and graph rules |
| Contract | schemas, OpenAPI, error taxonomy, event shapes | s | generated from `contracts/` |
| Integration | Postgres + Redis + NATS + Temporal via testcontainers | s–min | real adapters, mock LLM |
| End-to-end | full session to recommendation | min | golden task suite, mock provider |
| Replay | recorded session re-executed in `REPLAY_STRICT` | min | the CI gate that protects the research claim |
| Red-team | injection corpus, SSRF, scope matrix | s | blocking |
| Chaos | kill a worker mid-round, drop the vector store, stall the solver | min | asserts labelled degradation, not silence |

## 3. Mocking rules

- **Mock the LLM, never the reasoning.** The mock provider is deterministic and seeded; it returns
  fixture completions keyed by `request_hash`. What is under test is the platform's handling of
  structure, not model quality.
- **Never mock the database.** Postgres in a container, with pgvector and RLS enabled. RLS bugs are
  the highest-consequence bugs here and they are invisible to an ORM mock.
- **Never mock the ledger.** Append-only enforcement, hash chaining and sequence gaps are tested
  against the real table and its triggers.
- Ports are faked, not stubbed: each port has a `Fake*` implementation in `tests/fakes/` that
  records calls and can inject every failure mode in the relevant failure table
  ([RAG_ARCHITECTURE.md §6](RAG_ARCHITECTURE.md), [SIMULATION_ARCHITECTURE.md §9](SIMULATION_ARCHITECTURE.md)).

## 4. Fixtures

| Fixture | Contents |
| --- | --- |
| `session_golden` | a complete 4-agent, 3-round session with dissent, one blocking critique, one UNSAT constraint set |
| `session_degenerate` | one agent, one alternative — asserts the `degenerate_input` warning |
| `session_infeasible` | hard constraints with a known unsat core |
| `session_unknown_solver` | a constraint set that returns `UNKNOWN` — asserts it is never treated as satisfied |
| `corpus_poisoned` | documents containing injection payloads and a fabricated citation |
| `ledger_tampered` | a mutated event, asserting chain verification fails |

The golden fixture is the reference for golden-file API tests, metric expectations and the replay
gate. Changing it is a deliberate act: it invalidates stored expectations on purpose.

## 5. Coverage policy

Coverage is a floor, not a target: 80 % line on `core/`, 100 % branch on the consensus, graph and
authz modules. More important, CI reports **requirement coverage**: every `FR-`/`NFR-` marked done
must map to ≥ 1 test ([TRACEABILITY.md §4](TRACEABILITY.md)). A green coverage number with
untested requirements is the failure mode this policy exists to prevent.

## 6. Conventions

```python
@req("FR-602")
@invariant("C-1")
@given(consensus_contexts())
def test_c1_feasibility_precedes_ranking(ctx):
    # arrange: build a context whose hard constraints are UNSAT but whose scores are high
    ...
```

- Test names are `test_<invariant-or-req>_<behaviour>`; the id prefix is what the traceability
  generator scrapes.
- One behaviour per test. A test with "and" in its name is two tests.
- Deterministic by construction: no wall clock, no unseeded random, no ordering assumptions —
  `PYTHONHASHSEED=0` in CI makes ordering bugs surface as failures rather than as flakes.
- Flaky tests are quarantined with a ticket within one CI run, and a quarantined test does not
  count toward coverage. Two quarantines in a phase gate block it.

## 7. Frontend tests

| Type | Tool | Asserts |
| --- | --- | --- |
| Component | vitest + testing-library | the "why" affordance exists on every rendered value (X-1, §5 of [EXPLAINABILITY.md](EXPLAINABILITY.md)) |
| Contract | generated types + schema validator | no field read that is absent from the OpenAPI document |
| Accessibility | axe | the dissent panel is reachable and announced |
| E2E | playwright | a reviewer can trace a recommendation to a source in ≤ 4 clicks |
| Lint | custom rule | forbids "confidence"/"probability"/"score" next to a support value |

The four-click trace test is the one that keeps explainability honest; if it starts failing, the
explanation got worse even though every unit test still passes.

## 8. Related

[TRACEABILITY.md](TRACEABILITY.md) · [REPRODUCIBILITY.md](REPRODUCIBILITY.md) ·
[API_CONTRACTS.md](API_CONTRACTS.md) · [SECURITY.md](SECURITY.md) · [METRICS.md](METRICS.md)
