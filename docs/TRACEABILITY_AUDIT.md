<!-- trace: NFR-018 -->
# Traceability evidence-quality audit

**Task:** T10-03 · **Date:** 2026-09-11 · **Scope:** requirement-to-test semantics

This audit records the distinction between mapping coverage and behavioural verification. A row or
annotation says that repository evidence is associated with a requirement; it does not prove that the
requirement is complete, that its tests have run in every environment, or that a scientific claim is
correct.

## NFR-016 audit

The authoritative requirement is: **"Testability. Domain logic runs with zero network dependencies
using in-memory adapters."** Before this audit, 226 backend test nodes cited only `NFR-016`.

The mappings were introduced as per-test annotations during T10-03 rather than inherited from an older
generated matrix. Review therefore considered both the behaviour asserted by each test and the
production capability it exercises.

| Category | Count | Disposition |
| --- | ---: | --- |
| A — semantically correct | 77 | Retained. These tests exercise in-memory adapters, offline composition, or adapter doubles without live network services. |
| B — correct but overly broad | 0 | No test was left solely on `NFR-016` merely because it happened to run offline. |
| C — incorrect placeholder/inherited mapping | 149 | Reassigned to the behavioural FR/NFR asserted by the test. `NFR-016` was removed from these nodes. |
| D — ambiguous from repository evidence | 0 | No unresolved sole-`NFR-016` citation remains. |

The 77 retained annotations are supporting testability evidence, not claims that every individual test
implements all of NFR-016. Two live adapter tests remain: the MinIO test proves the object-store contract
also exercised by `InMemoryObjectStore`, and the Redis test proves the cache boundary does not become a
durable dependency. This is the residual evidence-quality limitation; their relationship is contract
parity rather than direct zero-network execution.

## Simulation audit

The Phase 8 contract suite had 36 tests, each citing all of `FR-701` through `FR-704`. The annotations
were narrowed per test:

- request, run-state, validation, and orchestration behaviour cites `FR-701`;
- result metadata, hashes, intervals, sensitivity, and validity-domain behaviour cites `FR-702`;
- model-evidence classification and required assumptions cite `FR-703`;
- sandbox port, no-network default, and bounded/terminated execution contracts cite `FR-704`.

Tests that genuinely assert more than one behaviour retain multiple IDs. No module-level requirement
marker remains in the production backend test suite.

## Consensus audit

Five Phase 9 tests previously cited all ten consensus/disagreement requirements. They were narrowed to
the outcomes and behaviours actually asserted. For example, no-alternative and no-evidence cases cite
the `FR-604` outcome taxonomy; unknown strategy selection cites `FR-608`; the weighted worked example
retains only dissent preservation, outcome classification, and explanation assertions. Existing focused
feasibility, Pareto, registry, and persistence mappings were retained.

## TR-1 / TR-2 interpretation

- **TR-1** requires every authoritative `FR-`/`NFR-` to have at least one design reference and one test,
  unless its lifecycle status is `planned` and it is not claimed complete. Planned rows may therefore
  have design-only evidence. Implemented rows must have design, code, test, and verification metadata.
- **TR-2** requires every backend Python test and every frontend Vitest/Jest test to cite at least one
  requirement. Python uses `@req(...)`, with module-level `pytestmark = req(...)` permitted only when
  every test in the module verifies the same requirement. Frontend tests use an immediately preceding
  `// req:` marker and deterministic file/line/column/title node IDs.
- Source markers are governed by the matrix definition and TR-3: they must identify a real requirement
  and target the next concrete symbol. Documentation trace comments
  annotations attach requirements to the next heading. These rules implement the repository
  specification without turning TR-1 into a claim that every planned requirement already has code.

This interpretation is deliberately neither weaker nor stricter than the normative text in
[`TRACEABILITY.md`](TRACEABILITY.md): TR-1 permits planned exceptions; TR-2 has no uncited-test
exception; and evidence citations must remain behaviourally honest.