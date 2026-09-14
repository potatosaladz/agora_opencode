# Reproducibility

**Version:** 1.1 · **Status:** design; T13-03 replay-mode contracts and orchestration implemented
**Requirements:** NFR-003, NFR-014, FR-905, FR-906 · **ADR:**
[ADR-001](adr/ADR-001-postgres-source-of-truth.md),
[ADR-019](adr/ADR-019-append-only-event-ledger.md)

## 1. The claim

**Re-running a session from its manifest, in `REPLAY_STRICT` mode, produces byte-identical
committed artifacts, events and metric values.**

If that is not true, the numbers in an experiment report describe an event that cannot be
examined twice, and the platform's research claim collapses. Reproducibility is a Phase 6
prerequisite for the experiment harness, not a later cleanup.

## 2. The manifest

Every session writes a manifest at creation and finalises it at termination:

```jsonc
{ "session_id": "ses_01H…", "manifest_version": 1,
  "code":    { "git_sha": "…", "image_digests": { "coordinator": "…", "agent-worker": "…" } },
  "schema":  { "migration_head": "0042", "artifact_schema_version": 3 },
  "config":  { "protocol": "deliberative", "rounds": 6, "budget": {…},
               "consensus_strategy": { "id": "constraint_aware", "version": "1.1.0",
                                       "parameters": {…} } },
  "agents":  [ { "definition_id": "ag_critic_v4", "definition_hash": "sha256:…",
                 "prompt_hash": "sha256:…", "model": "…", "model_version": "…",
                 "temperature": 0.0, "seed": 20260904 } ],
  "retrieval": { "namespaces": […], "index_versions": {…}, "embed_model": "…",
                 "reranker": "noop", "query_hashes": […] },
  "symbolic": { "engine": "z3", "engine_version": "4.13", "timeout_ms": 5000 },
  "simulation": { "engine_versions": {…}, "seeds": […] },
  "clock":  { "started_at": "…", "ordering": "ledger_seq" },
  "inputs": { "task_hash": "sha256:…", "source_hashes": […] },
  "randomness": [ { "use": "monte_carlo_sampling", "seed": 20260904, "stream": 1 } ] }
```

Anything that can influence an outcome and is not named here is a reproducibility hole. The list
is closed by the port registry: every port adapter declares its own manifest fields
([PORTS.md](PORTS.md)), so adding an adapter cannot silently escape the manifest.

## 3. Sources of nondeterminism

| Source | Control | Residual risk |
| --- | --- | --- |
| LLM sampling | `temperature = 0` plus recorded `seed`; provider version pinned | providers do not guarantee determinism even at 0 — hence replay modes (§4) |
| Wall-clock reads | no component reads the clock for logic; ordering is `ledger_seq` | timestamps are metadata only |
| Concurrency | the coordinator is the single writer; workers propose | none for committed state |
| Hash iteration order | `PYTHONHASHSEED=0`, sorted iteration enforced by lint | low |
| Floating point | fixed math libs, deterministic reduction, no cross-arch pooling in metrics | documented per engine |
| Retrieval index state | index version pinned in the manifest; re-index creates a new version | retracted sources stay resolvable for old sessions |
| Provider drift | responses cached by `request_hash` in object storage | cache eviction turns a strict replay into a tolerant one |
| Solver timeouts | timeout in the manifest; `UNKNOWN` is a recorded result | a faster machine may return `SAT` where the original said `UNKNOWN` — flagged `TIMING_SENSITIVE` |
| Migration order | schema head recorded; migrations are append-only | none |

<!-- trace: NFR-003, NFR-014 -->
## 4. Replay modes

| Mode | What it does | Use |
| --- | --- | --- |
| `REPLAY_STRICT` | no LLM, no retrieval, no solver: everything served from the recorded cache; asserts byte-identical output | CI gate, audit, "prove this number can be reproduced" |
| `REPLAY_TOLERANT` | re-runs inference with pinned seeds; compares artifact hashes and reports a diff | regression detection across code versions |
| `REPLAY_LIVE` | full re-execution against current providers | research comparison; **never** presented as reproducing the original |

A result produced in `REPLAY_LIVE` is a new session with a new id that links to the old one. It
does not overwrite, and it is never described as "the same experiment".

T13-03 implements these three modes as the closed `ReplayMode` enum and
`SessionReplayService` (`app.domain.replay`, `app.application.replay`). `REPLAY_STRICT` first
verifies the authoritative ledger and exact recorded event set, verifies any nested Phase 12 MARL
bundles with their existing hermetic verifier, resolves exact implementation id/version pairs, rejects
external or nondeterministic implementations before invocation, and stops at the first output/status
mismatch. Recorded provider and retrieval outputs are reconstruction inputs, not calls.

`REPLAY_TOLERANT` re-executes only steps whose captured policy explicitly permits it. It never reports
`VERIFIED`: a matching comparison is `MATCHED`, while implementation, provider, model, configuration,
output, status and timing-sensitive `UNKNOWN` changes produce an ordered structured diff and
`DIFFERENT`. Missing selected versions fail closed instead of silently falling back.

`REPLAY_LIVE` delegates to a `LiveReplayLauncher` that must return a new source-linked session,
manifest, event and result identity set. The service rejects any historical identity reuse and labels
the result `LIVE_STARTED`, never byte-identical. T13-03 itself writes no replay record and never mutates
the historical session; durable manifest creation/finalization and database-backed live lineage remain
T13-04. This boundary allows T13-03 to consume a `ReplaySource` now without inventing the manifest
schema owned by the next task.

Phase 12 `verify_bundle()` remains the narrower MARL trajectory proof. Full-session replay may invoke
it for captured MARL bundles, but does not rename its outcomes, replace its two-file format, or treat it
as proof of the rest of a session.

## 5. Content addressing and digests

- Artifact immutable content is hashed exactly as specified in [DATA_MODEL.md §6.0](DATA_MODEL.md):
  UTF-8 RFC 8785 JCS followed by SHA-256 with the `sha256:` prefix. `content_hash` is stored on the row.
- Large payloads and raw provider responses live in object storage under their digest
  ([ADR-008](adr/ADR-008-minio-object-storage.md)), so a digest is also a location.
- `input_hash` on a consensus result covers the frozen `ConsensusContext`; `spec_hash` covers a
  simulation spec; `ast_hash` covers a formalization.
- A digest that cannot be resolved to bytes is an integrity incident, not a cache miss.

## 6. Versioning policy

| Thing | Versioned how | Bump rule |
| --- | --- | --- |
| Artifact schema | `artifact_schema_version` | additive within a major; new major on any semantic change |
| Prompt | `prompt_hash`, plus a human-readable `prompt_version` | any character change |
| Agent definition | immutable version rows | new version, never edit a used one |
| Consensus strategy | `version` in the registry | any change to arithmetic, thresholds or ordering |
| Metric plugin | `metric_version` | any change to formula, inputs or caveats |
| Port adapter | package version + `image_digest` | any change |
| API | path `/api/v1` | [API_CONTRACTS.md §7](API_CONTRACTS.md) |

**V-1** A used version is immutable. Editing a prompt, strategy or metric that any session
references is forbidden; create a new version and let the old sessions stand.

## 7. Procedure: reproduce a session

```bash
crp replay ses_01H… --mode strict     # asserts hashes, exits non-zero on any diff
crp replay ses_01H… --mode tolerant --diff artifacts,metrics
crp replay ses_01H… --export bundle.tar.zst
```

The replay tool reads only the manifest, the ledger and the object store — never the mutable
configuration of the current deployment. If it needs anything else, that is a bug in this
document or in the manifest, and is recorded in [../project/ERRORS.md](../project/ERRORS.md).

## 8. What is deliberately not reproducible

| Item | Why | How it is labelled |
| --- | --- | --- |
| Live web sources | the page changed | `STALE_CITATION` when the hash no longer resolves |
| Provider-side model updates | outside our control | `model_version` recorded; drift is a finding |
| Human intervention timing | it is a human | the event records the actor and the state observed |
| Cost | prices move | recorded per run, never compared across dates without saying so |

## 9. Related

[EXPERIMENTATION.md](EXPERIMENTATION.md) · [AUDITABILITY.md](AUDITABILITY.md) ·
[SIMULATION_ARCHITECTURE.md §10](SIMULATION_ARCHITECTURE.md) · [METRICS.md](METRICS.md) ·
[ARCHITECTURE.md §3](ARCHITECTURE.md)
