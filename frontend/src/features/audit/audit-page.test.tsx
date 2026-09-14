import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import axe from "axe-core";

import {
  apiClient,
  type AuditResponse,
  type SessionResponse,
} from "../../api/client";
import AuditPage from "./audit-page";

const connection = {
  session: {
    data: {
      id: "ses_public",
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
      workspace_id: "ws_public",
      created_at: "2026-09-14T10:00:00Z",
      updated_at: "2026-09-14T10:01:00Z",
      owner: { id: "usr_public", class: "HUMAN" },
      permissions: ["audit:read"],
      trace: null,
    },
  } as SessionResponse,
  token: "token",
};

function response(
  overrides: Partial<AuditResponse["data"]> = {},
): AuditResponse {
  return {
    data: {
      question: "Q1",
      question_text: "Why is this claim in the record?",
      parameters: { session_id: "ses_public", artifact_id: "art_public" },
      answer: {
        kind: "ARTIFACT_RATIONALE",
        artifact_id: "art_public",
        provenance: null,
        committed_by_event: null,
        originating_turn_event: null,
      },
      evidence: [
        { ledger_seq: 1, event_type: "AGENT_TURN_COMPLETED" },
        { ledger_seq: 2, event_type: "ARTIFACT_COMMITTED" },
      ],
      state: {
        completeness: "COMPLETE",
        completeness_reasons: [],
        integrity: "NOT_APPLICABLE",
        integrity_reasons: [],
      },
      pagination: { truncated: false, next_cursor: null },
      links: {
        session: "#/",
        graph: "#/graph",
        dissent: "#/dissent",
        assumptions: "#/assumptions",
        explanation: "#/explanation",
        replay: "#/replay",
      },
      ...overrides,
    },
    meta: {
      request_id: "request",
      schema_version: 1,
      workspace_id: "ws_public",
    },
  };
}

function renderPage(page = <AuditPage connection={connection} />) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {page}
    </QueryClientProvider>,
  );
}

describe("AuditPage", () => {
  afterEach(() => vi.restoreAllMocks());

  // req: FR-802, FR-807, NFR-006, NFR-019
  it("exposes all eight authored audit questions", () => {
    renderPage();
    const group = screen.getByRole("group", {
      name: "Choose one authored audit question",
    });
    expect(within(group).getAllByRole("radio")).toHaveLength(8);
    for (const id of ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8"])
      expect(within(group).getByText(id)).toBeVisible();
  });

  // req: FR-802, NFR-010
  it("constructs only the selected question's required inputs", async () => {
    const query = vi
      .spyOn(apiClient, "querySessionAudit")
      .mockResolvedValue(response());
    renderPage();
    fireEvent.change(screen.getByLabelText("Artifact public ID"), {
      target: { value: "art_public" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run Q1" }));
    expect(
      await screen.findByText("Persisted structured answer"),
    ).toBeVisible();
    expect(screen.getByText("Submitted parameters")).toBeVisible();
    expect(query).toHaveBeenCalledWith(
      "ses_public",
      { question: "Q1", artifact_id: "art_public", max_depth: 8, limit: 50 },
      "token",
    );
    fireEvent.click(screen.getByRole("radio", { name: /Q7/ }));
    fireEvent.change(screen.getByLabelText("Recommendation public ID"), {
      target: { value: "rec_public" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run Q7" }));
    expect(query).toHaveBeenLastCalledWith(
      "ses_public",
      { question: "Q7", recommendation_id: "rec_public", limit: 100 },
      "token",
    );
  });

  // req: FR-802, FR-807, NFR-006
  it("continues a paginated result with the server cursor", async () => {
    const query = vi
      .spyOn(apiClient, "querySessionAudit")
      .mockResolvedValueOnce(
        response({
          pagination: { truncated: true, next_cursor: "next-page" },
        }),
      )
      .mockResolvedValueOnce(response());
    renderPage();
    fireEvent.change(screen.getByLabelText("Artifact public ID"), {
      target: { value: "art_public" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run Q1" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Load next evidence page" }),
    );
    expect(query).toHaveBeenLastCalledWith(
      "ses_public",
      {
        question: "Q1",
        artifact_id: "art_public",
        max_depth: 8,
        limit: 50,
        cursor: "next-page",
      },
      "token",
    );
  });

  // req: FR-802, FR-807, NFR-006
  it("renders evidence in server order and separates completeness from integrity", async () => {
    vi.spyOn(apiClient, "querySessionAudit").mockResolvedValue(
      response({
        question: "Q8",
        question_text: "Has anything been altered since it was written?",
        evidence: [
          { anchor_day: "2026-09-13", head_seq: 2 },
          { anchor_day: "2026-09-14", head_seq: 5 },
        ],
        state: {
          completeness: "INCOMPLETE",
          completeness_reasons: ["NO_EXTERNAL_WORM_ANCHOR"],
          integrity: "VERIFIED_UNALTERED",
          integrity_reasons: [],
        },
      }),
    );
    renderPage();
    fireEvent.click(screen.getByRole("radio", { name: /Q8/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run Q8" }));
    const evidence = await screen.findByRole("heading", {
      name: "Ordered evidence",
    });
    const list = evidence.nextElementSibling as HTMLElement;
    expect(within(list).getAllByRole("listitem")[0]).toHaveTextContent(
      "2026-09-13",
    );
    expect(within(list).getAllByRole("listitem")[1]).toHaveTextContent(
      "2026-09-14",
    );
    expect(screen.getByText("INCOMPLETE")).toBeVisible();
    expect(screen.getByText("VERIFIED_UNALTERED")).toBeVisible();
    expect(screen.getByText("no external worm anchor")).toBeVisible();
  });

  // req: FR-802, NFR-006
  it("renders integrity failure independently from the audit answer", async () => {
    vi.spyOn(apiClient, "querySessionAudit").mockResolvedValue(
      response({
        question: "Q8",
        question_text: "Has anything been altered since it was written?",
        answer: {
          kind: "CHAIN_VERIFICATION",
          event_count: 1,
          ledger_valid: false,
          ledger_reason: "event hash mismatch",
          ledger_head_hash: `sha256:${"a".repeat(64)}`,
          chain_valid: false,
          first_invalid_day: "2026-09-14",
          anchors: [{ anchor_day: "2026-09-14", valid: false }],
        },
        evidence: [{ anchor_day: "2026-09-14", valid: false }],
        state: {
          completeness: "COMPLETE",
          completeness_reasons: [],
          integrity: "ALTERED",
          integrity_reasons: ["anchor head does not match the stored day-head"],
        },
      }),
    );
    renderPage();
    fireEvent.click(screen.getByRole("radio", { name: /Q8/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run Q8" }));
    expect(await screen.findByText("ALTERED")).toBeVisible();
    expect(screen.getByText("COMPLETE")).toBeVisible();
    expect(
      screen.getByText("anchor head does not match the stored day-head"),
    ).toBeVisible();
  });

  // req: FR-802, NFR-010
  it("renders no-session and loading states", () => {
    const missing = renderPage(<AuditPage />);
    expect(screen.getByText("A restored session is required")).toBeVisible();
    missing.unmount();
    vi.spyOn(apiClient, "querySessionAudit").mockReturnValue(
      new Promise(() => undefined),
    );
    const loading = renderPage();
    fireEvent.click(screen.getByRole("radio", { name: /Q8/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run Q8" }));
    expect(screen.getByRole("status")).toHaveTextContent(
      "Reading authoritative audit facts",
    );
    loading.unmount();
  });

  // req: FR-802, NFR-010, NFR-019
  it("provides keyboard controls, evidence focus, links, and no color-only statuses", async () => {
    vi.spyOn(apiClient, "querySessionAudit").mockResolvedValue(response());
    const { container } = renderPage();
    const first = screen.getByRole("radio", { name: /Q1/ });
    first.focus();
    expect(first).toHaveFocus();
    fireEvent.change(screen.getByLabelText("Artifact public ID"), {
      target: { value: "art_public" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run Q1" }));
    expect((await screen.findAllByText("COMPLETE"))[0]).toBeVisible();
    expect(screen.getByRole("link", { name: "graph" })).toHaveAttribute(
      "href",
      "#/graph",
    );
    expect(screen.getByRole("link", { name: "replay" })).toHaveAttribute(
      "href",
      "#/replay",
    );
    const evidenceItems = screen
      .getAllByText(/Evidence [12]/)
      .map((item) => item.closest("li"));
    expect(evidenceItems[0]).toHaveAttribute("tabindex", "0");
    const result = await axe.run(container, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);
  });

  it.each([390, 1280])(
    "keeps audit evidence available at %ipx",
    async (width) => {
      Object.defineProperty(window, "innerWidth", {
        configurable: true,
        value: width,
      });
      vi.spyOn(apiClient, "querySessionAudit").mockResolvedValue(response());
      renderPage();
      fireEvent.change(screen.getByLabelText("Artifact public ID"), {
        target: { value: "art_public" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Run Q1" }));
      expect(
        await screen.findByRole("heading", { name: "Ordered evidence" }),
      ).toBeVisible();
    },
  );
});
