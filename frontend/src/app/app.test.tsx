import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import axe from "axe-core";
import { render, screen } from "@testing-library/react";

import { App } from "./app";
import { apiClient, type SessionResponse } from "../api/client";

function renderApp() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

describe("App", () => {
  beforeEach(() => {
    localStorage.clear();
    window.location.hash = "#/observatory";
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((input) => {
        const url =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.href
              : input.url;
        const body = url.endsWith("/ready")
          ? {
              status: "ok",
              service: "api",
              version: "test-sha",
              components: { database: { status: "ok", details: {} } },
            }
          : { status: "ok", service: "api", version: "test-sha" };
        return Promise.resolve(
          new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );
  });

  afterEach(() => vi.unstubAllGlobals());

  // req: NFR-015
  it("renders observed API and dependency status", async () => {
    renderApp();
    expect(await screen.findByText("database")).toBeInTheDocument();
    expect(screen.getByText("release / test-sha")).toBeInTheDocument();
  });

  // req: NFR-017
  it("has no detectable critical accessibility violations", async () => {
    const { container } = renderApp();
    await screen.findByText("database");
    const result = await axe.run(container, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);
  });

  // req: FR-105, FR-106
  it("restores the active session after a browser close", async () => {
    const restored = {
      session: {
        data: {
          id: `ses_${"1".repeat(32)}`,
          status: "COMPLETED",
          problem_statement: "Restored finished deliberation",
          agent_definition_ids: [],
          objective_ids: [],
          constraint_ids: [],
          budget: { max_rounds: 2, max_tokens: 10, max_usd: "1" },
          round: 2,
          workflow_id: "workflow",
          run_id: "run",
          initialized_at: "2026-09-06T10:00:00Z",
          started_at: "2026-09-06T10:00:01Z",
          ended_at: "2026-09-06T10:01:00Z",
        },
        meta: {
          request_id: "request",
          schema_version: 1,
          version: 1,
          workspace_id: `ws_${"2".repeat(32)}`,
          created_at: "2026-09-06T10:00:00Z",
          updated_at: "2026-09-06T10:01:00Z",
          owner: { id: `usr_${"3".repeat(32)}`, class: "HUMAN" },
          permissions: ["read"],
          trace: null,
        },
      } as SessionResponse,
      token: "restored-token",
    };
    localStorage.setItem(
      "agora.live-session",
      JSON.stringify({
        sessionId: restored.session.data.id,
        token: restored.token,
      }),
    );
    window.location.hash = "#/";
    const getSession = vi
      .spyOn(apiClient, "getSession")
      .mockResolvedValue(restored.session);
    vi.spyOn(apiClient, "streamSessionEvents").mockImplementation(
      async function* (_sessionId, _token, _since, signal) {
        yield* await new Promise<never[]>((resolve) => {
          if (signal?.aborted) resolve([]);
          else
            signal?.addEventListener("abort", () => resolve([]), {
              once: true,
            });
        });
      },
    );

    renderApp();

    expect(
      await screen.findByText("Restored finished deliberation"),
    ).toBeVisible();
    expect(getSession).toHaveBeenCalledWith(
      restored.session.data.id,
      "restored-token",
    );
  });
});
