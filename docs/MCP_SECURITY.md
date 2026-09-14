# MCP Security

**Version:** 1.0 · **Status:** design
**Service:** `mcp-gateway` ([ARCHITECTURE.md §2](ARCHITECTURE.md)) · **Port:** `MCPToolProvider`
([PORTS.md §11](PORTS.md)) · **Requirements:** FR-1001 … FR-1004 · **ADRs:**
[ADR-018](adr/ADR-018-sandbox-execution-boundary.md),
[ADR-021](adr/ADR-021-mcp-streamable-http-gateway.md)

## 1. Why this is a separate document

MCP is where the platform touches the world: it fetches documents, queries systems and can, for
some servers, write. It is also the only place where an **untrusted model** can cause an
**untrusted external program** to act. Both halves of that sentence are the problem, and no
amount of care on one side compensates for the other.

The gateway is therefore the sole egress for tool calls. An agent-worker that could call an MCP
server directly is a design defect, and the network policy makes it impossible rather than
improbable.

Agora is an outbound MCP tool consumer: reasoning worker → internal gateway → registered external server.
It is not a general inbound MCP server for internal Agora resources, prompts or services. Protocol
`2025-06-18`, Streamable HTTP, identity, retry and task ownership are frozen in
[PHASE15_ACCEPTANCE.md](PHASE15_ACCEPTANCE.md) and ADR-021.

## 2. Server registry

| Field | Rule |
| --- | --- |
| `server_id` | registered by an admin; nothing runs unregistered |
| `endpoint` | allowlisted host and port; no wildcard hosts |
| `image_digest` | for self-hosted servers, pinned by digest and verified at start |
| `capabilities` | declared tools, each with a classification (§3) |
| `data_class_max` | the highest data classification this server may receive |
| `tenant_scope` | workspace ids permitted to use it |
| `signing_key` | verifies the server's advertised tool manifest |

- **R-1** Adding a server is a configuration change plus a recorded decision in
  [../project/DECISIONS.md](../project/DECISIONS.md). It is never an agent action.
- **R-2** A tool manifest change on a registered server **fails closed**: the gateway compares the
  signed manifest hash to the registry and refuses the session until an admin re-approves.
  Silently accepting a new tool is the classic MCP supply-chain failure.
- **R-3** Tool names are namespaced (`jira.create_issue`), so two servers cannot collide into an
  ambiguous call.

<!-- trace: FR-1001 -->
## 3. Tool classification

| Class | Examples | Default policy |
| --- | --- | --- |
| `READ_SANE` | search, fetch document, read issue | allow, logged |
| `READ_RISKY` | query an internal DB, read a private repo | allow within scope, logged, size-capped |
| `WRITE` | create issue, post comment, update record | **require human approval** |
| `EXECUTE` | run code, deploy, send money, delete | denied in MVP; future enablement requires a new decision |
| `EXTERNAL_NET` | arbitrary URL fetch | denied; only allowlisted hosts (§7) |

Classification is per tool, not per server, and is stored in the registry. An unclassified tool is treated
as `WRITE` for pessimistic analysis but cannot enter a production allowlist before explicit classification.

`ToolClass` above is the registry-owned risk vocabulary. Runtime `ToolPermission` is only `NONE | READ |
APPROVAL_REQUIRED`: `READ_SANE`/`READ_RISKY → READ`, `WRITE → APPROVAL_REQUIRED`, and
`EXECUTE`/`EXTERNAL_NET → NONE` in the MVP. `SANDBOXED_WRITE` is not a permission; sandboxing is a separate
execution boundary. T15-02 owns classifications and T15-03 owns permission enforcement.

## 4. Policy evaluation

```text
allow = server_registered AND server_approved_for_workspace
        AND tool_class_allowed
        AND principal_may_call(principal, tool)
        AND args_valid AND args_in_resource_scope
        AND data_class_ok(prompt_context, tool)
        AND rate_ok AND budget_ok
        AND NOT injection_quarantined(context)
```

Every conjunct is evaluated server-side and every denial is an event naming the conjunct that
failed. "Denied" without a reason is useless for both audit and debugging.

## 5. Argument validation

- JSON Schema validation against the tool's declared schema; unknown parameters rejected.
- **Resource scoping:** identifiers must belong to the caller's workspace. A `project_key` or
  `document_id` supplied as free text by the model is checked against the registry, not trusted.
- **No secrets in arguments.** The gateway holds credentials referenced as
  `secret://mcp/<server_id>/<credential_name>` and T15-03 injects them at the transport layer; a model that
  could pass a header could pass someone else's (NFR-010).
- Size and depth caps on every argument; a 2 MB string in a `query` field is a bug or an attack.
- Destructive verbs (`delete`, `retract`, `close`) require an explicit `reason` and map to `WRITE`
  or above regardless of what the server declares.

<!-- trace: FR-1002, FR-1003 -->
## 6. Prompt-injection handling

Two-channel discipline: **instructions come from the platform, data comes from everywhere.**

- Retrieved chunks, tool results and uploaded text are wrapped in a data envelope with a boundary
  marker, and the artifact schema forbids a tool call that was not in the platform-authored plan.
- A tool result containing imperative instruction patterns ("ignore previous", "call tool X",
  role-marker forgery, base64 blobs) is quarantined: the content is stored, flagged
  `INJECTION_SUSPECTED`, and excluded from the next context window (FR-1003).
- **The decisive control is not detection.** It is that a model's output cannot raise its own
  privileges: `WRITE` and above require a human approval bound to a specific, already-rendered
  call. Editing the call after approval invalidates the approval.
- Detection is a heuristic and will miss things; the approval boundary is structural. The design
  relies on the second.

## 7. Egress and SSRF

Outbound fetches are resolved and re-checked at connect time against a deny list: RFC1918,
link-local `169.254.0.0/16` including the cloud metadata endpoint, `localhost`, the Swarm overlay
network, and any socket the platform itself listens on. Redirects are re-validated hop by hop, and
DNS rebinding is closed by connecting to the validated IP.

## 8. Result handling

- Results are `EVIDENCE` candidates, never committed artifacts. An agent must cite them into a
  claim, which puts them in the provenance chain ([RAG_ARCHITECTURE.md §5](RAG_ARCHITECTURE.md)).
- Byte caps and truncation flags; a truncated result says it is truncated.
- `content_hash`, `server_id`, `tool`, `args_hash` and `retrieved_at` are recorded, so a later
  source retraction finds every artifact that used it (FR-408).
- Model-generated text returned by a tool (a summarising server, say) is classified `SYNTHETIC`
  and can never be evidence (FR-403).

## 9. Budgets and abuse control

| Control | Value |
| --- | --- |
| Calls per session | per-tool ceiling, counted in the ledger |
| Tokens per result | ≤ 8 k, truncation flagged |
| Concurrency per server | capped, so one slow server cannot stall a round |
| Wall-clock per call | ≤ 30 s, then `TOOL_TIMEOUT` |
| Cost | gateway returns `BUDGET_EXCEEDED`; coordinator commits one `BUDGET_EXHAUSTED` termination |
| Repeated identical call | deduplicated within a round by `args_hash` |

<!-- trace: FR-1004 -->
## 10. Audit

Every call emits `TOOL_INVOKED` with principal, server, tool, class, safely redacted canonical arguments,
args hash, result hash, latency, decision and — for denials — the failing conjunct. Approvals emit
`TOOL_APPROVED` with the approver and the exact
rendered call. `audit:read` answers "what did this session do outside the platform" for any
session, which is the question an incident always starts with ([AUDITABILITY.md §5](AUDITABILITY.md)).

## 11. Tests

- Registry: unregistered server refused; manifest hash drift fails closed (R-2).
- Policy: every class × principal combination, including the approval path for `WRITE`.
- Injection: a fixture corpus of adversarial tool results; assert no unapproved `WRITE` occurs and
  that quarantine fires (FR-1003).
- SSRF: every deny-listed target, with redirect and DNS-rebinding variants.
- Credential isolation: assert no secret appears in any prompt, log or tool argument.
- Budget: exhaustion mid-round leaves the session consistent and the ledger complete.

## 12. Related

[SECURITY.md](SECURITY.md) · [THREAT_MODEL.md](THREAT_MODEL.md) · [PORTS.md §11](PORTS.md) ·
[AGENT_PROTOCOLS.md](AGENT_PROTOCOLS.md) · [RAG_ARCHITECTURE.md](RAG_ARCHITECTURE.md)
