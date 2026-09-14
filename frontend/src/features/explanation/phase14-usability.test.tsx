import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";

import { apiClient, type SessionResponse } from "../../api/client";
import { explanationFixture } from "./explanation.fixture";
import ExplanationPage from "./explanation-page";

const connection = {
  session: {
    data: {
      id: "ses_phase14_fixture",
      status: "COMPLETED",
      problem_statement: "Choose a transit plan",
      agent_definition_ids: [],
      objective_ids: [],
      constraint_ids: [],
      budget: { max_rounds: 3, max_tokens: 100, max_usd: "2" },
      round: 3,
      workflow_id: "wf",
      run_id: "run",
      initialized_at: null,
      started_at: null,
      ended_at: null,
    },
    meta: {
      request_id: "request",
      schema_version: 1,
      version: 1,
      workspace_id: "ws_fixture",
      created_at: "2026-09-14T10:00:00Z",
      updated_at: "2026-09-14T10:01:00Z",
      owner: { id: "usr_reviewer", class: "HUMAN" },
      permissions: ["read", "audit:read"],
      trace: null,
    },
  } as SessionResponse,
  token: "reviewer-token",
};

function renderFixture() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ExplanationPage connection={connection} />
    </QueryClientProvider>,
  );
}

describe("frozen Phase 14 scripted usability fixture", () => {
  afterEach(() => vi.restoreAllMocks());

  // req: FR-504, FR-505, FR-605, FR-804, FR-805, NFR-005, NFR-019
  it("reveals the minority position and weakest evidence from the initial UI", async () => {
    vi.spyOn(apiClient, "getSessionExplanation").mockResolvedValue(
      explanationFixture,
    );
    renderFixture();

    const minority = (
      await screen.findByRole("heading", { name: "Minority / dissent" })
    ).closest("section")!;
    expect(
      within(minority).getAllByText("Prefer the rail alternative")[0],
    ).toBeVisible();
    expect(within(minority).getByText("agt_equity")).toBeVisible();
    expect(within(minority).getByText("art_equity")).toBeVisible();

    const weakest = screen
      .getByRole("heading", { name: "Weakest evidence" })
      .closest("section")!;
    expect(
      within(weakest).getAllByText("Winter range degradation report")[0],
    ).toBeVisible();
    expect(
      within(weakest).getAllByText(/verification=DISPUTED/)[0],
    ).toBeVisible();
    expect(within(weakest).getByText("Open in graph")).toHaveAttribute(
      "href",
      "#/graph?root=gnd_winter",
    );
    expect(within(weakest).getByText("Open provenance")).toHaveAttribute(
      "href",
      "/api/v1/artifacts/art_winter/provenance",
    );
    expect(within(minority).queryByRole("button")).not.toBeInTheDocument();
    expect(within(weakest).queryByRole("button")).not.toBeInTheDocument();
  });

  // req: FR-705, FR-708, NFR-005
  it("keeps assumption, UNKNOWN, replay, and audit navigation visible", async () => {
    vi.spyOn(apiClient, "getSessionExplanation").mockResolvedValue(
      explanationFixture,
    );
    renderFixture();
    await screen.findAllByText("Prefer the rail alternative");
    expect(
      screen.getAllByRole("link", { name: "Open related view" }).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("UNKNOWN")).toBeVisible();
    expect(screen.getByText("DEFER")).toBeVisible();
    expect(
      screen
        .getAllByRole("link", { name: "Open related view" })
        .some((link) => link.getAttribute("href") === "#/assumptions"),
    ).toBe(true);
  });
});
