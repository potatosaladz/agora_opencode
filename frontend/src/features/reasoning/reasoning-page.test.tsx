import axe from "axe-core";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  apiClient,
  type ArtifactResponse,
  type SessionResponse,
} from "../../api/client";
import { NewSessionPage } from "./new-session-page";

const session: SessionResponse = {
  data: {
    id: `ses_${"1".repeat(32)}`,
    status: "DRAFT",
    problem_statement: "How should the city cut transport emissions?",
    agent_definition_ids: [`agt_${"2".repeat(32)}`],
    objective_ids: [`art_${"3".repeat(32)}`],
    constraint_ids: [`art_${"4".repeat(32)}`],
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
    workspace_id: `ws_${"5".repeat(32)}`,
    created_at: "2026-09-05T12:00:00Z",
    updated_at: "2026-09-05T12:00:00Z",
    owner: { id: `usr_${"6".repeat(32)}`, class: "HUMAN" },
    permissions: ["read", "write"],
    trace: null,
  },
};

function artifact(
  idDigit: string,
  kind: "PROPOSITION" | "CLAIM",
  attributes: Record<string, unknown>,
): ArtifactResponse {
  return {
    data: {
      id: `art_${idDigit.repeat(32)}`,
      kind,
      attributes,
      source_references: [],
      parent_relationships: [],
      confidence: null,
      metadata: {},
      content_hash: `sha256:${idDigit.repeat(64)}`,
    },
    meta: {
      request_id: `request-${kind.toLowerCase()}`,
      schema_version: 1,
      version: 1,
      workspace_id: session.meta.workspace_id,
      session_id: session.data.id,
      logical_id: `art_${idDigit.repeat(32)}`,
      created_at: session.meta.created_at,
      updated_at: session.meta.updated_at,
      owner: session.meta.owner,
      lifecycle_status: "ACTIVE",
      supersedes_id: null,
      provenance: {
        origin: "HUMAN",
        reference: "reasoning-desk",
        complete: true,
        missing: [],
      },
      permissions: ["read", "write"],
      trace: null,
    },
  };
}

describe("NewSessionPage", () => {
  afterEach(() => vi.restoreAllMocks());

  // req: FR-101, FR-305
  it("walks through FR-101 and visibly flags an unsupported FR-305 claim", async () => {
    const onMonitorSession = vi.fn();
    const createSession = vi
      .spyOn(apiClient, "createSession")
      .mockResolvedValue(session);
    const createArtifact = vi
      .spyOn(apiClient, "createArtifact")
      .mockResolvedValueOnce(
        artifact("7", "PROPOSITION", {
          statement_original: session.data.problem_statement,
          statement_normalized: "how should the city cut transport emissions?",
        }),
      )
      .mockResolvedValueOnce(
        artifact("8", "CLAIM", {
          statement: `Candidate response needed for: ${session.data.problem_statement}`,
          supporting_evidence_ids: [],
          opposing_evidence_ids: [],
          unsupported: true,
        }),
      );
    render(<NewSessionPage onMonitorSession={onMonitorSession} />);

    fireEvent.change(screen.getByLabelText(/^Access token/), {
      target: { value: "local-token" },
    });
    fireEvent.change(screen.getByLabelText("Complex problem"), {
      target: { value: session.data.problem_statement },
    });
    fireEvent.change(screen.getByLabelText("Pinned agent definition ID"), {
      target: { value: session.data.agent_definition_ids[0] },
    });
    fireEvent.change(screen.getByLabelText("Primary objective"), {
      target: { value: "Minimize transport emissions" },
    });
    fireEvent.change(screen.getByLabelText(/Hard constraint/), {
      target: { value: "Stay within the approved budget" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Open reasoning session" }),
    );

    expect(await screen.findByText("UNSUPPORTED / NO EVIDENCE")).toBeVisible();
    expect(screen.getByText(session.data.id)).toBeVisible();
    expect(screen.getByText("PROPOSITION / STRUCTURED")).toBeVisible();
    expect(screen.getAllByText("1", { selector: "dd" })).toHaveLength(3);
    await waitFor(() => expect(createArtifact).toHaveBeenCalledTimes(2));
    expect(createSession).toHaveBeenCalledWith(
      expect.objectContaining({
        problem_statement: session.data.problem_statement,
        agent_definition_ids: session.data.agent_definition_ids,
        constraints: [expect.objectContaining({ kind: "CONSTRAINT" })],
      }),
      "local-token",
      expect.stringMatching(/^session-/),
    );
    fireEvent.change(screen.getByLabelText(/^Access token/), {
      target: { value: "different-token" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Monitor live session" }),
    );
    expect(onMonitorSession).toHaveBeenCalledWith(session, "local-token");
  });

  // req: NFR-017
  it("has no detectable WCAG A or AA violations", async () => {
    const { container } = render(<NewSessionPage />);
    const result = await axe.run(container, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);
  });
});
