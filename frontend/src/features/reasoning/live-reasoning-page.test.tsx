import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";

import {
  apiClient,
  type RealtimeEvent,
  type SessionResponse,
} from "../../api/client";
import { ReasoningPage } from "./reasoning-page";

function renderReasoningPage(page = <ReasoningPage />) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{page}</QueryClientProvider>,
  );
}

const draftSession: SessionResponse = {
  data: {
    id: `ses_${"1".repeat(32)}`,
    status: "DRAFT",
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
    request_id: "request-session",
    schema_version: 1,
    version: 1,
    workspace_id: `ws_${"4".repeat(32)}`,
    created_at: "2026-09-05T12:00:00Z",
    updated_at: "2026-09-05T12:00:00Z",
    owner: { id: `usr_${"5".repeat(32)}`, class: "HUMAN" },
    permissions: ["read", "write"],
    trace: null,
  },
};
const pinnedAgentId = `agt_${"2".repeat(32)}`;

describe("ReasoningPage live console", () => {
  beforeEach(() => {
    vi.spyOn(apiClient, "streamSessionEvents").mockImplementation(
      async function* (_sessionId, _token, _since, signal) {
        yield* await new Promise<RealtimeEvent[]>((resolve) => {
          if (signal?.aborted) resolve([]);
          else
            signal?.addEventListener("abort", () => resolve([]), {
              once: true,
            });
        });
      },
    );
  });
  afterEach(() => vi.restoreAllMocks());

  // req: FR-104
  it("supports session control and durable human guidance", () => {
    renderReasoningPage();

    expect(screen.getByText("Market expansion strategy")).toBeVisible();
    expect(screen.getByText("Running")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(screen.getByText("Paused")).toBeVisible();
    expect(screen.getByRole("button", { name: "Resume" })).toBeVisible();

    fireEvent.change(screen.getByLabelText("Human guidance"), {
      target: { value: "Prioritize regulatory evidence." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send guidance" }));
    expect(
      screen.getByText("Sent: Prioritize regulatory evidence."),
    ).toBeVisible();
  });

  // req: FR-305
  it("filters and expands timeline evidence", () => {
    renderReasoningPage();

    fireEvent.change(screen.getByLabelText("Filter timeline"), {
      target: { value: "Risk" },
    });
    expect(screen.getByText("Identified risk")).toBeVisible();
    expect(screen.queryByText("Proposed claim")).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /Risk Assessor Identified risk/ }),
    );
    expect(screen.getByText(/Ledger event verified/)).toBeVisible();
  });

  // req: FR-101, FR-105, FR-106
  it("starts and monitors an API-backed draft without showing sample evidence", async () => {
    vi.spyOn(apiClient, "getSession").mockResolvedValue(draftSession);
    const started: SessionResponse = {
      ...draftSession,
      data: {
        ...draftSession.data,
        status: "INITIALIZING",
        workflow_id: "session-workflow",
        run_id: "run-1",
        initialized_at: "2026-09-05T12:01:00Z",
      },
    };
    const startSession = vi
      .spyOn(apiClient, "startSession")
      .mockResolvedValue(started);

    renderReasoningPage(
      <ReasoningPage
        connection={{ session: draftSession, token: "live-token" }}
      />,
    );

    expect(screen.getByText(draftSession.data.problem_statement)).toBeVisible();
    expect(screen.getByText(pinnedAgentId)).toBeVisible();
    expect(
      screen.getByText(
        "Per-agent activity unavailable in current API projection.",
      ),
    ).toBeVisible();
    expect(screen.queryByText("Working")).not.toBeInTheDocument();
    expect(screen.queryByText("Proposed claim")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start" }));

    expect(await screen.findByText("Start accepted")).toBeVisible();
    expect(startSession).toHaveBeenCalledWith(
      draftSession.data.id,
      "live-token",
      expect.stringMatching(/^start-/),
    );
    expect(screen.getAllByText("Draft")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Start" })).toBeVisible();
  });

  // req: FR-104
  it("submits typed human guidance to a running API session", async () => {
    const running: SessionResponse = {
      ...draftSession,
      data: {
        ...draftSession.data,
        status: "RUNNING",
        workflow_id: "session-workflow",
        run_id: "run-1",
        initialized_at: "2026-09-05T12:01:00Z",
        started_at: "2026-09-05T12:01:01Z",
      },
    };
    vi.spyOn(apiClient, "getSession").mockResolvedValue(running);
    const submitHumanInput = vi
      .spyOn(apiClient, "submitHumanInput")
      .mockResolvedValue(running);

    renderReasoningPage(
      <ReasoningPage connection={{ session: running, token: "live-token" }} />,
    );
    fireEvent.change(screen.getByLabelText("Guidance type"), {
      target: { value: "ADD_CONSTRAINT" },
    });
    fireEvent.change(screen.getByLabelText("Human guidance"), {
      target: { value: "Prioritize protected cycle lanes." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send guidance" }));

    expect(
      await screen.findByText("Sent: Prioritize protected cycle lanes."),
    ).toBeVisible();
    expect(submitHumanInput).toHaveBeenCalledWith(
      running.data.id,
      {
        reason: "Operator directive submitted from live console",
        kind: "ADD_CONSTRAINT",
        instruction: "Prioritize protected cycle lanes.",
        artifact_ids: [],
      },
      "live-token",
      expect.stringMatching(/^human-input-/),
    );
  });

  // req: FR-106, FR-303
  it("renders ordered ledger events once and refreshes authoritative state", async () => {
    const completed = {
      ...draftSession,
      data: { ...draftSession.data, status: "COMPLETED" as const },
    };
    vi.spyOn(apiClient, "getSession").mockResolvedValue(completed);
    const event: RealtimeEvent = {
      event_id: "event-1",
      ledger_seq: 7,
      type: "SESSION_COMPLETED",
      ts: "2026-09-06T12:00:00Z",
      session_id: "session-1",
      actor_id: "service-1",
      actor_class: "SERVICE",
      round: 2,
      payload: {},
      schema_version: 1,
      code_version: "sha",
    };
    const streamSessionEvents = vi.spyOn(apiClient, "streamSessionEvents");
    streamSessionEvents.mockImplementation(
      async function* (_sessionId, _token, _since, signal) {
        yield event;
        yield event;
        await new Promise<void>((resolve) => {
          if (signal?.aborted) resolve();
          else
            signal?.addEventListener("abort", () => resolve(), { once: true });
        });
      },
    );

    renderReasoningPage(
      <ReasoningPage
        connection={{ session: draftSession, token: "live-token" }}
      />,
    );

    expect(await screen.findByText("Session Completed")).toBeVisible();
    expect(screen.getAllByText("SEQ 7")).toHaveLength(1);
  });
});
