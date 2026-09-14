import { useState } from "react";
import type { FormEvent } from "react";

import {
  ApiProblem,
  apiClient,
  type ArtifactCreate,
  type ArtifactResponse,
  type SessionCreate,
  type SessionResponse,
} from "../../api/client";

const emptyArtifact = {
  provenance: { origin: "HUMAN" as const, reference: "reasoning-desk" },
  source_references: [],
  parent_relationships: [],
  metadata: {},
};

function idempotencyKey(scope: string): string {
  return `${scope}-${crypto.randomUUID()}`;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiProblem) return error.problem.detail;
  if (error instanceof Error) return error.message;
  return "Reasoning request failed.";
}

type NewSessionPageProps = {
  onMonitorSession?: (session: SessionResponse, token: string) => void;
};

// trace: FR-101, FR-102, FR-305
export function NewSessionPage({ onMonitorSession }: NewSessionPageProps = {}) {
  const [token, setToken] = useState("");
  const [problem, setProblem] = useState("");
  const [agentId, setAgentId] = useState("");
  const [objective, setObjective] = useState("");
  const [constraint, setConstraint] = useState("");
  const [maxRounds, setMaxRounds] = useState(4);
  const [maxTokens, setMaxTokens] = useState(10000);
  const [maxUsd, setMaxUsd] = useState("25.00");
  const [sessionConnection, setSessionConnection] = useState<{
    session: SessionResponse;
    token: string;
  }>();
  const [proposition, setProposition] = useState<ArtifactResponse>();
  const [claim, setClaim] = useState<ArtifactResponse>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function openSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    setSessionConnection(undefined);
    setProposition(undefined);
    setClaim(undefined);

    const objectiveArtifact: SessionCreate["objectives"][number] = {
      ...emptyArtifact,
      kind: "OBJECTIVE",
      payload: {
        name: objective,
        objective_type: "UTILITY",
        direction: "MAXIMIZE",
        weight: "1",
        weight_rationale: "Primary user objective",
        time_horizon: "session",
        conflicts_with_ids: [],
      },
    };
    const constraints: SessionCreate["constraints"] = constraint.trim()
      ? [
          {
            ...emptyArtifact,
            kind: "CONSTRAINT",
            payload: {
              name: "User boundary",
              statement: constraint,
              constraint_type: "HARD",
              category: "USER_DEFINED",
              evaluation_expression: {
                language: "json-logic",
                ast: { acknowledged: true },
              },
              formal_status: "PROPOSED",
            },
          },
        ]
      : [];
    const sessionInput: SessionCreate = {
      problem_statement: problem,
      agent_definition_ids: [agentId],
      objectives: [objectiveArtifact],
      constraints,
      budget: { max_rounds: maxRounds, max_tokens: maxTokens, max_usd: maxUsd },
    };

    const requestToken = token;
    try {
      const created = await apiClient.createSession(
        sessionInput,
        requestToken,
        idempotencyKey("session"),
      );
      const propositionInput: ArtifactCreate = {
        ...emptyArtifact,
        kind: "PROPOSITION",
        payload: {
          statement_original: problem,
          statement_normalized: problem
            .trim()
            .replace(/\s+/g, " ")
            .toLowerCase(),
          canonicalizer_version: "ui-literal@1",
          proposition_kind: "USER_DEFINED",
          modality: "QUESTION",
          normalization_status: "PROPOSED",
        },
      };
      const claimInput: ArtifactCreate = {
        ...emptyArtifact,
        kind: "CLAIM",
        payload: {
          statement: `Candidate response needed for: ${problem}`,
          claim_type: "HYPOTHESIS",
          direction: "SUPPORTS",
          strength: "WEAK",
          supporting_evidence_ids: [],
          opposing_evidence_ids: [],
          review_status: "PROPOSED",
        },
      };
      const createdProposition = await apiClient.createArtifact(
        created.data.id,
        propositionInput,
        requestToken,
        idempotencyKey("proposition"),
      );
      const createdClaim = await apiClient.createArtifact(
        created.data.id,
        claimInput,
        requestToken,
        idempotencyKey("claim"),
      );
      setSessionConnection({ session: created, token: requestToken });
      setProposition(createdProposition);
      setClaim(createdClaim);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setPending(false);
    }
  }

  return (
    <main id="main-content" className="page reasoning-desk">
      <header className="reasoning-intro">
        <p className="eyebrow">Reasoning desk / Phase 3</p>
        <h1>
          Frame problem.
          <em> Expose gaps.</em>
        </h1>
        <p>
          Open fully bound draft. Preserve question as structured proposition.
          Treat missing evidence as visible result, never hidden confidence.
        </p>
      </header>

      <div className="reasoning-grid">
        <form
          className="session-form"
          onSubmit={(event) => void openSession(event)}
        >
          <div className="form-heading">
            <span>01</span>
            <div>
              <p className="label">Session manifest</p>
              <h2>Define inquiry</h2>
            </div>
          </div>
          <label>
            Access token
            <input
              required
              type="password"
              autoComplete="off"
              value={token}
              onChange={(event) => setToken(event.target.value)}
            />
            <small>Held in page memory only.</small>
          </label>
          <label>
            Complex problem
            <textarea
              required
              rows={5}
              value={problem}
              onChange={(event) => setProblem(event.target.value)}
              placeholder="How should our city…"
            />
          </label>
          <label>
            Pinned agent definition ID
            <input
              required
              pattern="agt_[0-9a-f]{32}"
              value={agentId}
              onChange={(event) => setAgentId(event.target.value)}
              placeholder="agt_…"
            />
          </label>
          <label>
            Primary objective
            <input
              required
              value={objective}
              onChange={(event) => setObjective(event.target.value)}
            />
          </label>
          <label>
            Hard constraint <span className="optional">optional</span>
            <input
              value={constraint}
              onChange={(event) => setConstraint(event.target.value)}
            />
          </label>
          <fieldset>
            <legend>Resource budget</legend>
            <label>
              Rounds
              <input
                required
                type="number"
                min={1}
                max={50}
                value={maxRounds}
                onChange={(event) =>
                  setMaxRounds(event.currentTarget.valueAsNumber)
                }
              />
            </label>
            <label>
              Tokens
              <input
                required
                type="number"
                min={1}
                value={maxTokens}
                onChange={(event) =>
                  setMaxTokens(event.currentTarget.valueAsNumber)
                }
              />
            </label>
            <label>
              USD
              <input
                required
                inputMode="decimal"
                pattern="(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,2})?"
                value={maxUsd}
                onChange={(event) => setMaxUsd(event.target.value)}
              />
            </label>
          </fieldset>
          <button type="submit" disabled={pending}>
            {pending ? "Committing manifest…" : "Open reasoning session"}
          </button>
          {error ? (
            <p className="form-error" role="alert">
              {error}
            </p>
          ) : null}
        </form>

        <section
          className="reasoning-output"
          aria-labelledby="output-title"
          aria-live="polite"
        >
          <div className="form-heading">
            <span>02</span>
            <div>
              <p className="label">Committed record</p>
              <h2 id="output-title">Evidence field</h2>
            </div>
          </div>
          {sessionConnection && proposition && claim ? (
            <div className="session-record">
              <div className="record-status">
                <i /> {sessionConnection.session.data.status} / ROUND 00
              </div>
              <h3>{sessionConnection.session.data.problem_statement}</h3>
              <dl>
                <div>
                  <dt>Session</dt>
                  <dd>{sessionConnection.session.data.id}</dd>
                </div>
                <div>
                  <dt>Agent pins</dt>
                  <dd>
                    {sessionConnection.session.data.agent_definition_ids.length}
                  </dd>
                </div>
                <div>
                  <dt>Objectives</dt>
                  <dd>{sessionConnection.session.data.objective_ids.length}</dd>
                </div>
                <div>
                  <dt>Constraints</dt>
                  <dd>
                    {sessionConnection.session.data.constraint_ids.length}
                  </dd>
                </div>
                <div>
                  <dt>Budget</dt>
                  <dd>
                    {sessionConnection.session.data.budget.max_rounds} rounds /{" "}
                    {sessionConnection.session.data.budget.max_tokens} tokens /
                    ${sessionConnection.session.data.budget.max_usd}
                  </dd>
                </div>
              </dl>
              {onMonitorSession ? (
                <button
                  className="monitor-session-button"
                  onClick={() =>
                    onMonitorSession(
                      sessionConnection.session,
                      sessionConnection.token,
                    )
                  }
                  type="button"
                >
                  Monitor live session
                </button>
              ) : null}
              <article className="artifact-card">
                <span>PROPOSITION / STRUCTURED</span>
                <h3>
                  {String(proposition.data.attributes.statement_original)}
                </h3>
                <p>
                  {String(proposition.data.attributes.statement_normalized)}
                </p>
              </article>
              <article className="artifact-card artifact-card--unsupported">
                <span>CLAIM / HYPOTHESIS</span>
                <strong role="status">UNSUPPORTED / NO EVIDENCE</strong>
                <h3>{String(claim.data.attributes.statement)}</h3>
                <p>
                  Supporting references: 0. Claim remains visible and
                  challengeable.
                </p>
              </article>
            </div>
          ) : (
            <div className="empty-reasoning">
              <span aria-hidden="true">∅</span>
              <p>No reasoning record committed.</p>
              <small>Complete manifest to expose structured output here.</small>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
