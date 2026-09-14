import { ApiClient, ApiProblem, type RealtimeEvent } from "./client";

describe("ApiClient", () => {
  // req: NFR-015
  it("returns contract-typed health data", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({ status: "ok", service: "api", version: "sha" }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    await expect(new ApiClient({ fetchImpl }).getHealth()).resolves.toEqual({
      status: "ok",
      service: "api",
      version: "sha",
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      "/health",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  // req: FR-109, NFR-010
  it("preserves problem details without exposing an untyped response", async () => {
    const problem = {
      type: "https://example.invalid/errors/forbidden",
      title: "Forbidden",
      status: 403,
      code: "FORBIDDEN" as const,
      detail: "Forbidden",
      retryable: false,
    };
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(problem), {
        status: 403,
        headers: { "Content-Type": "application/problem+json" },
      }),
    );

    await expect(new ApiClient({ fetchImpl }).getReadiness()).rejects.toEqual(
      new ApiProblem(problem),
    );
  });

  // req: FR-101, FR-102
  it("sends authenticated idempotent session creates", async () => {
    const response = {
      data: {
        id: `ses_${"1".repeat(32)}`,
        status: "DRAFT" as const,
        problem_statement: "How should the city cut transport emissions?",
        agent_definition_ids: [`agt_${"2".repeat(32)}`],
        objective_ids: [`art_${"3".repeat(32)}`],
        constraint_ids: [],
        budget: { max_rounds: 4, max_tokens: 10000, max_usd: "25" },
        round: 0,
        workflow_id: null,
        run_id: null,
        initialized_at: null,
        started_at: null,
        ended_at: null,
      },
      meta: {
        request_id: "request-1",
        schema_version: 1 as const,
        version: 1 as const,
        workspace_id: `ws_${"4".repeat(32)}`,
        created_at: "2026-09-05T12:00:00Z",
        updated_at: "2026-09-05T12:00:00Z",
        owner: { id: `usr_${"5".repeat(32)}`, class: "HUMAN" as const },
        permissions: ["read", "write"],
        trace: null,
      },
    };
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const input = {
      problem_statement: response.data.problem_statement,
      agent_definition_ids: response.data.agent_definition_ids,
      objectives: [],
      constraints: [],
      budget: response.data.budget,
    };

    await expect(
      new ApiClient({ fetchImpl }).createSession(input, "token", "session-key"),
    ).resolves.toEqual(response);
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/v1/sessions",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer token",
          "Idempotency-Key": "session-key",
        }) as Record<string, string>,
        body: JSON.stringify(input),
      }),
    );
  });

  // req: FR-105, FR-207
  it("starts a session without synthesizing a request body", async () => {
    const response = {
      data: {
        id: `ses_${"1".repeat(32)}`,
        status: "DRAFT" as const,
        problem_statement: "Problem",
        agent_definition_ids: [`agt_${"2".repeat(32)}`],
        objective_ids: [`art_${"3".repeat(32)}`],
        constraint_ids: [],
        budget: { max_rounds: 1, max_tokens: 1, max_usd: "1" },
        round: 0,
        workflow_id: "session-workflow",
        run_id: "run-1",
        initialized_at: null,
        started_at: null,
        ended_at: null,
      },
      meta: {
        request_id: "request-1",
        schema_version: 1 as const,
        version: 1 as const,
        workspace_id: `ws_${"4".repeat(32)}`,
        created_at: "2026-09-05T12:00:00Z",
        updated_at: "2026-09-05T12:00:00Z",
        owner: { id: `usr_${"5".repeat(32)}`, class: "HUMAN" as const },
        permissions: ["read", "write"],
        trace: null,
      },
    };
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      new ApiClient({ fetchImpl }).startSession(
        response.data.id,
        "token",
        "start-key",
      ),
    ).resolves.toEqual(response);
    const [, init] = fetchImpl.mock.calls[0] ?? [];
    expect(init).toMatchObject({
      method: "POST",
      headers: {
        Authorization: "Bearer token",
        "Idempotency-Key": "start-key",
      },
    });
    expect(init?.body).toBeUndefined();
  });

  // req: FR-106
  it("reads an authenticated session projection", async () => {
    const response = { data: { id: `ses_${"1".repeat(32)}` }, meta: {} };
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      new ApiClient({ fetchImpl }).getSession(response.data.id, "live-token"),
    ).resolves.toEqual(response);
    expect(fetchImpl).toHaveBeenCalledWith(
      `/api/v1/sessions/${response.data.id}`,
      expect.objectContaining({
        headers: {
          Accept: "application/json",
          Authorization: "Bearer live-token",
        },
      }),
    );
  });

  // req: FR-504, FR-505, FR-506, FR-609, FR-901, NFR-005, NFR-019
  it("reads authenticated session dissent", async () => {
    const response = {
      data: {
        session_id: `ses_${"1".repeat(32)}`,
        evaluated: true,
        empty_reason: "EVALUATED_NO_DISSENT",
        majority: null,
        minority: [],
        critiques: [],
      },
      meta: { request_id: "request", schema_version: 1, workspace_id: "ws_1" },
    };
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      new ApiClient({ fetchImpl }).getSessionDissent(
        response.data.session_id,
        "dissent-token",
      ),
    ).resolves.toEqual(response);
    expect(fetchImpl).toHaveBeenCalledWith(
      `/api/v1/sessions/${response.data.session_id}/dissent`,
      expect.objectContaining({
        headers: {
          Accept: "application/json",
          Authorization: "Bearer dissent-token",
        },
      }),
    );
  });

  // req: FR-805, NFR-004, NFR-010
  it("posts an authenticated graph read without idempotency", async () => {
    const response = {
      data: { nodes: [], edges: [], truncated: false, next_cursor: null },
      meta: { request_id: "request", workspace_id: `ws_${"2".repeat(32)}` },
    };
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const input = {
      session_id: `ses_${"1".repeat(32)}`,
      root_ids: [`gnd_${"3".repeat(32)}`],
      max_depth: 2,
      page_size: 100,
    };

    await expect(
      new ApiClient({ fetchImpl }).getGraphSubgraph(input, "graph-token"),
    ).resolves.toEqual(response);
    const [, init] = fetchImpl.mock.calls[0] ?? [];
    expect(init).toMatchObject({
      method: "POST",
      body: JSON.stringify(input),
      headers: {
        Accept: "application/json",
        Authorization: "Bearer graph-token",
        "Content-Type": "application/json",
      },
    });
    expect(init?.headers).not.toHaveProperty("Idempotency-Key");
  });

  // req: FR-805, NFR-010
  it("preserves graph problem responses", async () => {
    const problem = {
      type: "about:blank",
      title: "Invalid graph root",
      status: 422,
      code: "VALIDATION_FAILED" as const,
      detail: "The graph root is not visible in this session.",
      retryable: false,
    };
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(problem), {
        status: 422,
        headers: { "Content-Type": "application/problem+json" },
      }),
    );

    await expect(
      new ApiClient({ fetchImpl }).getGraphSubgraph(
        {
          session_id: "ses_1",
          root_ids: ["gnd_1"],
          max_depth: 2,
          page_size: 100,
        },
        "token",
      ),
    ).rejects.toEqual(new ApiProblem(problem));
  });

  // req: FR-104, FR-107
  it("maps legacy termination to its typed compatibility endpoint", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await new ApiClient({ fetchImpl }).terminateSession(
      `ses_${"1".repeat(32)}`,
      { reason: "Stop safely" },
      "token",
      "terminate-key",
    );

    expect(fetchImpl).toHaveBeenCalledWith(
      `/api/v1/sessions/ses_${"1".repeat(32)}/terminate`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ reason: "Stop safely" }),
      }),
    );
  });
});
describe("realtime stream", () => {
  // req: FR-106
  it("sends bearer auth and parses SSE frames split across chunks", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'id: 4\nevent: ROUND_STARTED\ndata: {"event_id":"e4","ledger_',
          ),
        );
        controller.enqueue(
          encoder.encode(
            'seq":4,"type":"ROUND_STARTED","ts":"2026-09-06T12:00:00Z","session_id":"s","actor_id":"a","actor_class":"SERVICE","round":1,"payload":{},"schema_version":1,"code_version":"sha"}\n\n',
          ),
        );
        controller.close();
      },
    });
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(body, {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      }),
    );
    const client = new ApiClient({ baseUrl: "https://api.example", fetchImpl });

    const events: RealtimeEvent[] = [];
    for await (const event of client.streamSessionEvents("ses_1", "token", 3)) {
      events.push(event);
    }

    expect(events).toHaveLength(1);
    expect(events[0]?.ledger_seq).toBe(4);
    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe(
      "https://api.example/api/v1/sessions/ses_1/events/stream?since=3",
    );
    expect(init?.headers).toMatchObject({ Authorization: "Bearer token" });
  });
});
