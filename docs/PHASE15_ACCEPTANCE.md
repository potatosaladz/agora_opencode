# Phase 15 Acceptance Contract

**Version:** 1.0 · **Status:** T15-00 complete; T15-01…04 frozen and open · **Phase:** 15
**Frozen on:** 2026-09-15
**Baseline:** Phase 14 complete at `7c28597` · **Direction:** outbound MCP tool gateway only
**Requirements:** FR-1001…FR-1004, FR-201, FR-403, FR-408, NFR-006, NFR-009, NFR-010,
NFR-012, NFR-015, NFR-016 and NFR-020
**Decision:** [ADR-021](adr/ADR-021-mcp-streamable-http-gateway.md)

## 1. Authority and task order

Phase 15 creates one controlled outbound path from reasoning workers to registered external MCP servers.
It does not turn Agora into a general inbound MCP server and does not expose Graph, Audit, Replay,
Consensus or other internal services as MCP resources, prompts or tools.

1. T15-00 — Reconcile and Freeze MCP Authority
2. T15-01 — Gateway as Sole Tool Egress
3. T15-02 — Versioned Server Registry and Explicit Allowlist
4. T15-03 — Tool Policy, Approvals, Limits, and Audit
5. T15-04 — Untrusted Result and Injection Containment

T15-00 is complete. T15-01…04 remain open. Changing protocol, transport, trust boundaries, authority or
task ownership requires a superseding ADR and acceptance-contract revision before runtime code.

## 2. Frozen architecture and protocol

```text
reasoning worker (internal MCP client)
  → Streamable HTTP on application_internal
  → stateless mcp-gateway (internal MCP server + upstream MCP client)
  → Streamable HTTP on mcp_egress
  → registered external MCP server
```

- The protocol version is exactly `2025-06-18`; incompatible peers fail initialization closed.
- T15-01 selects and pins the official Python `mcp` SDK release that supports this version.
- Worker → gateway and gateway → server both use MCP Streamable HTTP.
- Legacy HTTP+SSE and stdio are not production transports. Browser SSE is unrelated.
- The gateway and fixture negotiate only tools capability. Workers use initialize, `tools/list` and
  `tools/call`; resources and prompts capabilities are absent.
- Gateway/upstream MCP sessions and connection pools are ephemeral. After restart, clients reconnect,
  initialize and rediscover tools. No domain or authorization state depends on transport-session continuity.
- Progress notifications may be forwarded when negotiated, but are non-authoritative.
- Unsupported methods, malformed protocol messages and upstream failures map to the closed failures in §4.

### 2.1 Timeout, cancellation and retry

- `timeout_s` is positive and capped at 30 seconds. Effective timeout is the minimum of the call value,
  30 seconds and the Temporal activity deadline remaining. The gateway owns upstream timeout enforcement.
- Timeout cancels and drains the upstream SDK operation and returns `TOOL_TIMEOUT`.
- Activity cancellation closes the worker request and the gateway propagates MCP cancellation when
  negotiated, then drains the operation. The structured outcome is `TOOL_CANCELLED` when return is possible.
- The caller allocates UUIDv7 `operation_id` and correlation id before execution. Temporal retries reuse the
  same operation id, canonical call and `args_hash`.
- T15-01 may use bounded ephemeral deduplication for its deterministic read fixture. Exact duplicates with
  the same result hash are accepted; changed reuse returns `OPERATION_CONFLICT`. Durable deduplication and
  idempotency for mutating tools belong to T15-03.

## 3. Trusted identity and authentication

Worker → gateway authentication uses a short-lived OIDC OAuth2 client-credentials bearer JWT representing a
workload identity. Its audience is exactly `mcp-gateway`; human/browser tokens and wrong audiences fail.
Verification remains behind an access-token-verifier port with a distinct workload principal. Production
mTLS is defense in depth, not workspace authority.

`MCPCallContext` contains authoritative `workload_subject`, `workspace_id`, `session_id`, exact
`agent_definition_id` and version, optional initiating human/service actor, UUIDv7 `operation_id`, correlation
id, round and deadline. Workspace/session/agent affinity is re-resolved from trusted platform state and never
taken from free-form tool arguments. Agents never inherit initiating-human admin, validation, promotion or
`audit:read` scopes. T15-01 verifies workload/context shape; T15-03 owns the full authorization conjunction.

## 4. Typed MCP contracts

T15-01 implements infrastructure-neutral frozen values in `app/domain/mcp.py` and `app/ports/mcp.py`:

- `MCPProtocolVersion`: exactly `2025-06-18`.
- `UpstreamServerRef`: server id, registry version, `STREAMABLE_HTTP`, manifest hash.
- `MCPCallContext`: trusted identities and operation/correlation/deadline fields from §3.
- `ToolDescriptor`: namespaced name (`server.tool`), description, closed input schema, optional output
  schema, class, derived permission and manifest hash.
- `ToolCall`: context, server ref, tool name, bounded JSON arguments, canonical `args_hash`, timeout and
  optional approval id.
- `ToolContent`: `TEXT | JSON | BLOB_REF`, bounded value and literal `untrusted=true`.
- `ToolResult`: operation/correlation ids, upstream/server/tool identity, untrusted content, content hash,
  source URI, retrieval time, `TOOL_UNTRUSTED | SYNTHETIC` trust class, optional object-store reference,
  truncation flag, original/returned byte counts and optional upstream request id.
- `MCPServerCapabilities`: negotiated protocol version, tools support, cancellation/progress flags; resources
  and prompts must be false.
- `ToolFailureCode`: `AUTH_REQUIRED`, `FORBIDDEN`, `SERVER_NOT_REGISTERED`, `TOOL_NOT_FOUND`,
  `MANIFEST_DRIFT`, `ARGUMENT_INVALID`, `APPROVAL_REQUIRED`, `RATE_LIMITED`, `BUDGET_EXCEEDED`,
  `TOOL_TIMEOUT`, `TOOL_CANCELLED`, `UPSTREAM_UNAVAILABLE`, `PROTOCOL_ERROR`, `RESULT_INVALID`,
  `RESULT_TOO_LARGE`, `INJECTION_SUSPECTED`, `OPERATION_CONFLICT`. Session budget breach maps through the
  coordinator to one durable `BUDGET_EXHAUSTED` termination; `BUDGET_EXCEEDED` is the activity-facing
  gateway failure before that authoritative transition.
- `MCPToolProvider`: async `initialize`, `list_tools`, `invoke` and `cancel` operations.

All JSON has explicit byte, depth and member limits and rejects unknown fields. Adapters map SDK values into
these contracts and never return ORM rows, SDK objects, raw exceptions or credentials.

Workload identity uses separate `WorkloadPrincipal` and `WorkloadTokenVerifier` port contracts containing
subject, audience, expiry and allowed service role. T15-01's verifier adapter validates issuer, signature,
audience and expiry; context affinity is then checked against existing workspace/session/agent authority.

## 5. Permission vocabulary

`ToolClass` is inherent risk classification owned by T15-02. `ToolPermission` is derived policy treatment
owned by T15-03; it is not a competing classification.

| `ToolClass` | Default `ToolPermission` | Rule |
| --- | --- | --- |
| `READ_SANE` | `READ` | still requires server/workspace/agent/resource/data-class checks |
| `READ_RISKY` | `READ` | same checks plus tighter scope/result limits |
| `WRITE` | `APPROVAL_REQUIRED` | exact rendered call requires approval |
| `EXECUTE` | `NONE` | denied in MVP; future sandbox opt-in requires a new decision |
| `EXTERNAL_NET` | `NONE` | denied until T15-04 destination controls pass |

An unclassified tool is treated as `WRITE` and cannot enter a production allowlist before explicit admin
classification. `SANDBOXED_WRITE` is removed: sandboxing is an execution boundary, not authorization.

## 6. Artifact safety, network and secrets

**Invariant:** `ToolResult != committed reasoning artifact`. The stateless gateway returns only an untrusted,
content-hashed evidence candidate and has no artifact-store, graph or reasoning-ledger write authority. Only
the existing coordinator/artifact commit path can commit an artifact, projection and event atomically.

Network paths are distinct:

| Path | Frozen rule |
| --- | --- |
| application traffic | `application_internal`, private/internal, no published ports |
| approved model provider | existing worker `provider_egress`; Phase 15 does not claim full worker isolation |
| MCP server | gateway-only outbound policy; self-hosted/test servers also share `mcp_egress` |
| arbitrary internet | denied by policy; destination/SSRF enforcement completes in T15-04 |

T15-01 Compose proves the worker cannot resolve/connect to the fixture MCP server while the gateway can;
the fixture publishes no host port. Remote external MCP endpoints do not attach to an overlay: worker
workload/network policy denies their destination class while the gateway outbound role permits it. T15-04
adds connect-time destination enforcement. This is sole MCP egress, not a false claim that workers have no
model-provider route.

MCP credentials are references `secret://mcp/<server_id>/<credential_name>`. Only the gateway resolves and
mounts them through `SecretProvider`. Secret values never enter prompts, model-visible arguments, logs,
traces, results, object metadata, ledger payloads or manifests. T15-03 implements production injection.

## 7. Persistence ownership

| Task | Persistence |
| --- | --- |
| T15-01 | none; stateless gateway and ephemeral sessions/dedup; no migration |
| T15-02 | versioned server registry, workspace grants, decision ref, signed manifest/hash, classifications |
| T15-03 | approval/invocation/audit persistence only where existing ledger/access/object stores are insufficient |
| T15-04 | quarantine/result provenance only where existing object/provenance/citation stores are insufficient |

No task creates MCP shadow copies of sessions, artifacts, graph, audit, replay, manifests or authorization.

## 8. T15-00 — Reconcile and Freeze MCP Authority

**Dependencies:** Phase 14 complete; ADR-011, ADR-012, ADR-017 and ADR-018 accepted.

**IN SCOPE:** this contract, ADR-021, requirement-reference repair, port and permission reconciliation,
protocol/transport, identity, network, retry, persistence and exit ownership.

**OUT OF SCOPE:** runtime code, dependencies, migrations, services, MCP calls and runtime tests.

**Ownership:** documentation/architecture only; no persistence, network or runtime ownership.

**Acceptance criteria**

1. T15-01…04 have non-overlapping scope, acceptance, ownership and deployed evidence.
2. Protocol, transport, lifecycle, identity, permission, retry and network decisions are executable.
3. Only real requirement ids are cited; FR-1005 remains Phase 2 provider portability and is not used for MCP
   credential isolation.
4. Tasks, state, ADR, ports, security, architecture and network docs agree; traceability and links pass.

**Requirement mappings:** planning verification of FR-1001…FR-1004, NFR-010, NFR-012, NFR-015, NFR-016 and
NFR-020. It claims no runtime implementation.

<!-- trace: FR-1001, NFR-010, NFR-012, NFR-015, NFR-016, NFR-020 -->
## 9. T15-01 — Gateway as Sole Tool Egress

**Dependencies:** T15-00; existing activities, identity, SecretProvider, object store, observability and
Compose foundations.

**IN SCOPE:** stateless gateway process in the existing backend package; §4 contracts; authenticated
worker/gateway and gateway/fixture Streamable HTTP; initialize, tools capability/discovery/invocation,
timeout, cancellation, errors, correlation and restart; deterministic fixture server with one namespaced
read-only `fixture.read_echo` tool; health/readiness; network bypass proof; untrusted content-hashed result.

**OUT OF SCOPE:** durable registry/allowlist/signing, production catalogue, full authorization/approval/
rate/cost enforcement, durable invocation audit, quarantine, injection heuristics and SSRF controls.

**Ownership:** domain/ports — MCP and workload-principal/verifier contracts; application — gateway
orchestration and trusted context-affinity validation only; adapters — official
SDK Streamable HTTP client/server; persistence — none; networks — fixture `application_internal` and
`mcp_egress`; frontend — none.

**Acceptance criteria**

1. Worker and gateway negotiate `2025-06-18`, advertise tools only, list exactly `fixture.read_echo`, and
   return a schema-valid content-hashed untrusted result.
2. Wrong version, unsupported method, malformed payload, protocol/result error and upstream outage fail
   closed with structured failures and no secret/raw exception disclosure.
   Workload issuer, signature, audience, expiry and allowed reasoning-worker subject are verified; browser,
   agent and wrong-audience tokens fail. Workspace/session/agent affinity is re-resolved from platform state.
3. Timeout and cancellation stop/drain upstream work; retries reuse operation identity and changed duplicate
   calls fail `OPERATION_CONFLICT`.
4. Gateway restart requires reinitialize/rediscovery and loses no domain state.
5. Worker-to-fixture connectivity fails; gateway-to-fixture succeeds; fixture has no published port.
6. Gateway/result adapters have no artifact or ledger writer; a tool result cannot commit reasoning state.
7. Gateway readiness, real MCP client discovery/invocation and focused protocol/security/topology tests pass.

**Focused tests:** frozen value validation; SDK adapter contract; initialize/version/capabilities; list/call;
argument/result schemas; errors; timeout; cancellation; retry identity/conflict; correlation; restart;
secret non-disclosure; worker bypass; no-write dependency/layering.

**Deployed acceptance:** Compose build/`--wait`; migration exits 0 with unchanged head; API and gateway ready;
real client discovers/calls fixture tool through gateway; direct worker call fails; logs are clean.

**Requirement mappings:** FR-1001 sole-path portion; NFR-010, NFR-012, NFR-015, NFR-016, NFR-020.

<!-- trace: FR-1001, NFR-010, NFR-012, NFR-015, NFR-016 -->
## 10. T15-02 — Versioned Server Registry and Explicit Allowlist

**Dependencies:** T15-01 protocol/provider contracts.

**IN SCOPE:** durable versioned server registry; exact endpoints/image digests; workspace grants; explicit
recorded server decision reference; signed manifest/hash authority; drift/reapproval; namespaced tool names;
production classification; data-class ceilings.

**OUT OF SCOPE:** invocation approval, runtime rate/budget policy, result quarantine and SSRF enforcement.

**Ownership:** application/domain — registry and manifest policy; persistence — tenant-safe PostgreSQL schema
and repositories owned here; network — approved upstream endpoint metadata, not routing enforcement;
security — registration/manifest supply-chain authority; frontend — none by default.

**Acceptance criteria**

1. Only admin-approved, workspace-granted, versioned servers with non-wildcard endpoints resolve.
2. Each server version links an explicit decision, secret reference, data ceiling and signed manifest hash.
3. Tool names are unique/namespaced and each tool has one `ToolClass`; unclassified tools fail closed.
4. Live discovery exactly matches the approved manifest; drift blocks listing/invocation until reapproval.
5. Forced RLS, tenant-safe references, immutable history and deterministic ordering pass.

**Focused tests:** registry lifecycle/versioning; RLS; grants; decision refs; endpoint/image constraints;
signature/hash; namespacing; duplicate tools; unclassified tools; manifest drift/reapproval.

**Deployed acceptance:** migrate cleanly; register one fixture server/version; grant one workspace; discovery
succeeds; altered manifest and cross-workspace access fail; restart retains registry authority.

**Requirement mappings:** FR-1001 registry/allowlist portion; NFR-010, NFR-012, NFR-015, NFR-016.

<!-- trace: FR-201, FR-1003, FR-1004, NFR-006, NFR-009, NFR-010, NFR-015, NFR-016, NFR-020 -->
## 11. T15-03 — Tool Policy, Approvals, Limits, and Audit

**Dependencies:** T15-02 registry/classifications; existing agent definitions, budgets, identity, cache,
ledger, access audit and object storage.

**IN SCOPE:** policy conjunction over workload/workspace/session/agent/human context; agent `tool_perms`;
roles/scopes; exact-call approvals; rate/concurrency/call/token/cost limits; Temporal retry, durable dedup and
idempotency; gateway-only credential injection; `TOOL_INVOKED`/`TOOL_APPROVED` schemas; denial conjuncts.

**OUT OF SCOPE:** injection detection/quarantine, synthetic restrictions and SSRF destination controls.

**Ownership:** application — policy/approval/invocation orchestration; persistence — only approval/invocation
facts not representable by existing ledger/access/object stores; security — authorization, limits and secret
injection; network — none; frontend — approval UI only if the accepted API requires it.

**Acceptance criteria**

1. Every policy conjunct is server-side, deny-by-default and reports the failed conjunct.
2. `READ_SANE`/`READ_RISKY` obey grants and resource/data scope; `WRITE` requires an unexpired approval bound
   to exact operation/server/tool/args hash; editing invalidates approval; `EXECUTE`/`EXTERNAL_NET` deny.
3. Agent permissions cannot inherit initiating-human scopes; cross-workspace calls remain hidden/denied.
4. Per-tool/session rates, concurrency, call/result-token/cost budgets and duplicate/retry behavior are
   deterministic; a tool budget breach returns `BUDGET_EXCEEDED` and commits the existing one
   `BUDGET_EXHAUSTED` session termination through coordinator authority.
5. Credentials resolve only inside gateway transport and never appear in any exposed/persisted content.
6. Every allowed/denied/failed call records actor, server, tool, class, safely redacted canonical arguments,
   arguments hash, result hash, latency, operation/correlation identity and decision; approvals record
   approver and exact rendered call. Secret-bearing fields are omitted/redacted before persistence.

**Focused tests:** exhaustive class × principal × grant matrix; approval lifecycle/edit/replay; scope/RLS;
resource/data class; rate/concurrency/budget; retry/dedup/conflict; secret isolation; audit completeness/order.

**Deployed acceptance:** authorized read succeeds; unauthorized/cross-tenant fail; write blocks then succeeds
only after exact approval; limits trip; retries do not duplicate effects; audit answers the tool-call history.

**Requirement mappings:** FR-1003 approval portion, FR-1004, FR-201, NFR-006, NFR-009, NFR-010, NFR-015,
NFR-016, NFR-020.

<!-- trace: FR-403, FR-408, FR-1002, FR-1003, NFR-010, NFR-015, NFR-016, NFR-020 -->
## 12. T15-04 — Untrusted Result and Injection Containment

**Dependencies:** T15-03 authorized invocation/audit; existing object storage, provenance, citation and source
impact authority; ADR-018 sandbox boundary.

**IN SCOPE:** untrusted data envelope; provenance bridge; quarantine; instruction-pattern containment;
synthetic classification/restrictions; exclusion from future prompt context; hostile corpus; result limits;
SSRF deny list; redirect revalidation; DNS-rebinding defense; external destination enforcement; phase exit.

**OUT OF SCOPE:** new artifact authority, automatic evidence commitment, general web proxy, production
`EXECUTE` enablement and broad inbound Agora MCP capabilities.

**Ownership:** application/domain — containment decisions and provenance mapping; persistence — only missing
quarantine/provenance facts, reusing existing stores first; network — destination/connect-time controls;
security — injection/SSRF/synthetic restrictions; frontend — approval/quarantine visibility only if required.

**Acceptance criteria**

1. Tool output is always framed untrusted data, never instructions, and cannot authorize another call.
2. Imperative/role-forgery/encoded hostile fixtures quarantine with `INJECTION_SUSPECTED`, remain excluded
   from future context and cannot widen scope or cause unapproved writes.
3. Result content hash, server/tool/args identity, retrieval time, trust class, source URI, raw object ref and
   truncation survive provenance; synthetic model text can never be evidence.
4. RFC1918, loopback, link-local/metadata, platform sockets, disallowed IPv6, redirects and DNS rebinding fail
   at connect time; only registered destinations pass.
5. Phase exit proves worker cannot directly reach external MCP servers, gateway can reach only authorized
   servers, results cannot directly write artifacts and hostile output cannot expand agent scope.

**Focused tests:** adversarial result corpus; boundary framing; quarantine/context exclusion; privilege
non-escalation; provenance/retraction; synthetic rejection; byte/depth truncation; SSRF IPv4/IPv6; redirects;
DNS rebinding; destination allowlist; full phase security exit.

**Deployed acceptance:** hostile external fixture is invoked through the authorized gateway; content is
quarantined and audited; no second tool or artifact commit occurs; SSRF targets fail; clean result provenance
resolves; complete Phase 15 topology/security checks pass.

**Requirement mappings:** FR-1002, FR-1003 containment portion, FR-403, FR-408, NFR-010, NFR-015, NFR-016,
NFR-020.

## 13. Phase exit

Phase 15 exits only when all tasks pass and deployed evidence proves:

1. Worker containers cannot directly reach external MCP servers — owned by T15-01 topology and rechecked by
   T15-04 destination controls.
2. Tool results cannot directly write artifacts — structural proof in T15-01 and full result path in T15-04.
3. Hostile tool output cannot expand agent scope — owned by T15-03 authorization and T15-04 containment.

Quality, contracts, traceability, links, Compose, migrations, readiness, real-client discovery/invocation,
tenant isolation, clean logs and exact-SHA remote CI are required. Phase 15 remains open until T15-01…04 pass.
