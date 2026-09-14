import type { components } from "./types";

export type HealthResponse = components["schemas"]["HealthResponse"];
export type ReadinessResponse = components["schemas"]["ReadinessResponse"];
export type ProblemDetails = components["schemas"]["ProblemDetails"];
export type SessionCreate = components["schemas"]["SessionCreate"];
export type SessionResponse = components["schemas"]["SessionResponse"];
export type SessionControlCreate =
  components["schemas"]["SessionControlCreate"];
export type HumanInputCreate = components["schemas"]["HumanInputCreate"];
export type ArtifactCreate = components["schemas"]["ArtifactCreate"];
export type ArtifactResponse = components["schemas"]["ArtifactResponse"];
export type GraphEdgeType = components["schemas"]["GraphEdgeType"];
export type GraphNode = components["schemas"]["ProvenanceGraphNode"];
export type GraphEdge = components["schemas"]["GraphSubgraphEdge"];
export type GraphSubgraphRequest =
  components["schemas"]["GraphSubgraphRequest"];
export type GraphSubgraphResponse =
  components["schemas"]["GraphSubgraphResponse"];

export type RealtimeEvent = {
  event_id: string;
  ledger_seq: number;
  type: string;
  ts: string;
  session_id: string;
  actor_id: string;
  actor_class: string;
  round: number;
  payload: Record<string, unknown>;
  schema_version: number;
  code_version: string;
};

export class ApiProblem extends Error {
  readonly problem: ProblemDetails;

  constructor(problem: ProblemDetails) {
    super(problem.detail);
    this.name = "ApiProblem";
    this.problem = problem;
  }
}

type ApiClientOptions = {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
};

// trace: FR-101, FR-102, FR-104, FR-105, FR-106, FR-107, FR-109, FR-207, NFR-010, NFR-015
export class ApiClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor({ baseUrl = "", fetchImpl }: ApiClientOptions = {}) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.fetchImpl =
      fetchImpl ?? ((input, init) => globalThis.fetch(input, init));
  }

  getHealth(signal?: AbortSignal): Promise<HealthResponse> {
    return this.getJson<HealthResponse>("/health", signal);
  }

  getReadiness(signal?: AbortSignal): Promise<ReadinessResponse> {
    return this.getJson<ReadinessResponse>("/ready", signal);
  }

  createSession(
    input: SessionCreate,
    token: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SessionResponse> {
    return this.sendJson<SessionResponse>("/api/v1/sessions", input, {
      token,
      idempotencyKey,
      ...(signal === undefined ? {} : { signal }),
    });
  }

  getSession(
    sessionId: string,
    token: string,
    signal?: AbortSignal,
  ): Promise<SessionResponse> {
    return this.getJson<SessionResponse>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}`,
      signal,
      token,
    );
  }

  getGraphSubgraph(
    input: GraphSubgraphRequest,
    token: string,
    signal?: AbortSignal,
  ): Promise<GraphSubgraphResponse> {
    return this.sendJson<GraphSubgraphResponse>(
      "/api/v1/graph/subgraph",
      input,
      { token, ...(signal === undefined ? {} : { signal }) },
    );
  }

  startSession(
    sessionId: string,
    token: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SessionResponse> {
    return this.sendJson<SessionResponse>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/start`,
      undefined,
      { token, idempotencyKey, ...(signal === undefined ? {} : { signal }) },
    );
  }

  pauseSession(
    sessionId: string,
    input: SessionControlCreate,
    token: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SessionResponse> {
    return this.controlSession(
      sessionId,
      "pause",
      input,
      token,
      idempotencyKey,
      signal,
    );
  }

  resumeSession(
    sessionId: string,
    input: SessionControlCreate,
    token: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SessionResponse> {
    return this.controlSession(
      sessionId,
      "resume",
      input,
      token,
      idempotencyKey,
      signal,
    );
  }

  cancelSession(
    sessionId: string,
    input: SessionControlCreate,
    token: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SessionResponse> {
    return this.controlSession(
      sessionId,
      "cancel",
      input,
      token,
      idempotencyKey,
      signal,
    );
  }

  /** @deprecated Use cancelSession. This compatibility operation preserves history. */
  terminateSession(
    sessionId: string,
    input: SessionControlCreate,
    token: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SessionResponse> {
    return this.controlSession(
      sessionId,
      "terminate",
      input,
      token,
      idempotencyKey,
      signal,
    );
  }

  submitHumanInput(
    sessionId: string,
    input: HumanInputCreate,
    token: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SessionResponse> {
    return this.controlSession(
      sessionId,
      "human-input",
      input,
      token,
      idempotencyKey,
      signal,
    );
  }

  async *streamSessionEvents(
    sessionId: string,
    token: string,
    since: number,
    signal?: AbortSignal,
  ): AsyncGenerator<RealtimeEvent> {
    const response = await this.fetchImpl(
      `${this.baseUrl}/api/v1/sessions/${encodeURIComponent(sessionId)}/events/stream?since=${since}`,
      {
        headers: {
          Accept: "text/event-stream",
          Authorization: `Bearer ${token}`,
        },
        ...(signal === undefined ? {} : { signal }),
      },
    );
    if (!response.ok) await this.throwProblem(response);
    if (response.body === null)
      throw new Error("Realtime response body is unavailable.");
    const reader = response.body
      .pipeThrough(new TextDecoderStream())
      .getReader();
    let buffer = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += value;
        let boundary = buffer.indexOf("\n\n");
        while (boundary >= 0) {
          const frame = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const data = frame
            .split("\n")
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trimStart())
            .join("\n");
          if (data) yield JSON.parse(data) as RealtimeEvent;
          boundary = buffer.indexOf("\n\n");
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  createArtifact(
    sessionId: string,
    input: ArtifactCreate,
    token: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ArtifactResponse> {
    return this.sendJson<ArtifactResponse>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/artifacts`,
      input,
      { token, idempotencyKey, ...(signal === undefined ? {} : { signal }) },
    );
  }

  private async getJson<T>(
    path: string,
    signal?: AbortSignal,
    token?: string,
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (token !== undefined) headers.Authorization = `Bearer ${token}`;
    const init: RequestInit = { headers };
    if (signal !== undefined) {
      init.signal = signal;
    }
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, init);
    if (response.ok) {
      return (await response.json()) as T;
    }
    if (
      response.headers.get("content-type")?.includes("application/problem+json")
    ) {
      throw new ApiProblem((await response.json()) as ProblemDetails);
    }
    throw new Error(`Agora API returned HTTP ${response.status}`);
  }

  private async throwProblem(response: Response): Promise<never> {
    if (
      response.headers.get("content-type")?.includes("application/problem+json")
    ) {
      throw new ApiProblem((await response.json()) as ProblemDetails);
    }
    throw new Error(`Agora API returned HTTP ${response.status}`);
  }

  private controlSession(
    sessionId: string,
    control: "pause" | "resume" | "cancel" | "terminate" | "human-input",
    input: SessionControlCreate | HumanInputCreate,
    token: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SessionResponse> {
    return this.sendJson<SessionResponse>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/${control}`,
      input,
      { token, idempotencyKey, ...(signal === undefined ? {} : { signal }) },
    );
  }

  private async sendJson<T>(
    path: string,
    body: unknown,
    options: {
      token: string;
      idempotencyKey?: string;
      signal?: AbortSignal;
    },
  ): Promise<T> {
    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: `Bearer ${options.token}`,
      "Content-Type": "application/json",
    };
    if (options.idempotencyKey !== undefined) {
      headers["Idempotency-Key"] = options.idempotencyKey;
    }
    const init: RequestInit = {
      method: "POST",
      headers,
    };
    if (body !== undefined) init.body = JSON.stringify(body);
    if (options.signal !== undefined) init.signal = options.signal;
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, init);
    if (response.ok) return (await response.json()) as T;
    if (
      response.headers.get("content-type")?.includes("application/problem+json")
    ) {
      throw new ApiProblem((await response.json()) as ProblemDetails);
    }
    throw new Error(`Agora API returned HTTP ${response.status}`);
  }
}

const apiBaseUrl: string = import.meta.env.VITE_API_BASE_URL ?? "";
export const apiClient = new ApiClient({ baseUrl: apiBaseUrl });
