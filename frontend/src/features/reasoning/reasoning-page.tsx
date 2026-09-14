import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, FormEvent } from "react";

import {
  ApiProblem,
  apiClient,
  type HumanInputCreate,
  type RealtimeEvent,
  type SessionResponse,
} from "../../api/client";
import { Icon } from "../../components/icon";

// trace: FR-101, FR-305
type Agent = {
  id: string;
  initials: string;
  name: string;
  role: string;
  color: string;
  status: "working" | "complete" | "waiting" | "unavailable";
};

const agents: Agent[] = [
  {
    id: "market",
    initials: "MA",
    name: "Market Analyst",
    role: "Domain expert",
    color: "#68b8ff",
    status: "working",
  },
  {
    id: "risk",
    initials: "RA",
    name: "Risk Assessor",
    role: "Risk specialist",
    color: "#f09b61",
    status: "complete",
  },
  {
    id: "operations",
    initials: "OS",
    name: "Operations",
    role: "Feasibility expert",
    color: "#c083ff",
    status: "working",
  },
  {
    id: "strategy",
    initials: "SS",
    name: "Strategy Synthesizer",
    role: "Consensus builder",
    color: "#56d9a0",
    status: "waiting",
  },
];

const timeline = [
  {
    time: "14:32:18",
    tone: "blue",
    agent: "Market Analyst",
    title: "Proposed claim",
    text: "The APAC market shows 23% YoY growth in our target segment, with particularly strong demand in Singapore and Japan.",
    tags: ["CLAIM", "CONFIDENCE: 0.78"],
  },
  {
    time: "14:32:15",
    tone: "violet",
    agent: "Operations",
    title: "Added evidence",
    text: "Current supply chain capacity can support initial expansion into 2 markets without significant capital expenditure.",
    tags: ["EVIDENCE", "VERIFIED"],
  },
  {
    time: "14:32:12",
    tone: "orange",
    agent: "Risk Assessor",
    title: "Identified risk",
    text: "Currency exposure and regulatory variance across APAC markets present material operational risk.",
    tags: ["RISK", "HIGH IMPACT"],
  },
  {
    time: "14:32:08",
    tone: "violet",
    agent: "Operations",
    title: "Proposed alternative",
    text: "Phased entry: Singapore first, followed by Japan after 6-month validation period.",
    tags: ["ALTERNATIVE", "FEASIBLE"],
  },
  {
    time: "14:31:55",
    tone: "green",
    agent: "System",
    title: "Round 2 started",
    text: "Agents are evaluating alternatives against objectives and constraints.",
    tags: [],
  },
] as const;

type LiveConnection = {
  session: SessionResponse;
  token: string;
};

type CommandEvent = {
  id: string;
  time: string;
  title: string;
  text: string;
  tag: string;
};

function realtimeCard(event: RealtimeEvent) {
  return {
    time: new Date(event.ts).toLocaleTimeString([], { hour12: false }),
    tone: event.actor_class === "HUMAN" ? "blue" : "green",
    agent:
      event.actor_class === "AGENT"
        ? "Agent"
        : event.actor_class === "HUMAN"
          ? "Operator"
          : "System",
    title: displayStatus(event.type),
    text: `Committed ${displayStatus(event.type)} event. Referenced resource IDs remain available under current permissions.`,
    tags: [`SEQ ${event.ledger_seq}`, `ROUND ${event.round}`],
  };
}

const terminalStatuses = new Set([
  "COMPLETED",
  "PARTIAL_CONSENSUS_STATE",
  "NO_CONSENSUS",
  "DEADLOCK",
  "FAILED",
  "CANCELLED",
]);

function idempotencyKey(scope: string): string {
  return `${scope}-${crypto.randomUUID()}`;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiProblem) return error.problem.detail;
  if (error instanceof Error) return error.message;
  return "Session command failed.";
}

function displayStatus(status: string): string {
  return status
    .toLowerCase()
    .split("_")
    .map((word) => word[0]?.toUpperCase() + word.slice(1))
    .join(" ");
}

function elapsedSince(startedAt: string | null): string {
  if (startedAt === null) return "Not started";
  const seconds = Math.max(
    0,
    Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000),
  );
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
}

function AgentAvatar({
  agent,
  small = false,
}: {
  agent: Agent;
  small?: boolean;
}) {
  return (
    <span
      className={`agent-avatar${small ? " agent-avatar--small" : ""}`}
      style={{ "--agent-color": agent.color } as CSSProperties}
    >
      {agent.initials}
      {!small && agent.status !== "unavailable" ? (
        <i className={`agent-presence agent-presence--${agent.status}`} />
      ) : null}
    </span>
  );
}

// trace: FR-104, FR-105, FR-106
export function ReasoningPage({ connection }: { connection?: LiveConnection }) {
  const [paused, setPaused] = useState(false);
  const [terminated, setTerminated] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState("market");
  const [eventFilter, setEventFilter] = useState("All events");
  const [expandedEvent, setExpandedEvent] = useState<number | null>(null);
  const [guidance, setGuidance] = useState("");
  const [sentGuidance, setSentGuidance] = useState("");
  const [directiveKind, setDirectiveKind] =
    useState<HumanInputCreate["kind"]>("REQUEST_CRITIQUE");
  const [commandPending, setCommandPending] = useState(false);
  const [commandError, setCommandError] = useState("");
  const [commandEvents, setCommandEvents] = useState<CommandEvent[]>([]);
  const [ledgerEvents, setLedgerEvents] = useState<RealtimeEvent[]>([]);
  const [streamState, setStreamState] = useState<
    "connecting" | "live" | "reconnecting"
  >("connecting");
  const connected = connection !== undefined;
  const sessionQuery = useQuery({
    enabled: connected,
    initialData: connection?.session,
    queryKey: ["session", connection?.session.data.id],
    queryFn: ({ signal }) =>
      apiClient.getSession(
        connection!.session.data.id,
        connection!.token,
        signal,
      ),
    refetchInterval: (query) =>
      query.state.data && terminalStatuses.has(query.state.data.data.status)
        ? false
        : 3_000,
  });
  const liveSession = sessionQuery.data;
  const terminalSession = terminalStatuses.has(liveSession?.data.status ?? "");
  const terminalSessionRef = useRef(terminalSession);
  terminalSessionRef.current = terminalSession;
  const connectionSessionId = connection?.session.data.id;
  const connectionToken = connection?.token;
  const refetchSession = sessionQuery.refetch;
  useEffect(() => {
    if (!connectionSessionId || connectionToken === undefined) return;
    const controller = new AbortController();
    let retry: ReturnType<typeof setTimeout> | undefined;
    let cursor = 0;
    const retryConnection = () => {
      if (controller.signal.aborted) return;
      if (terminalSessionRef.current) return;
      setStreamState("reconnecting");
      retry = setTimeout(() => void connect(), 1_000);
    };
    const connect = async () => {
      try {
        for await (const event of apiClient.streamSessionEvents(
          connectionSessionId,
          connectionToken,
          cursor,
          controller.signal,
        )) {
          cursor = Math.max(cursor, event.ledger_seq);
          setLedgerEvents((current) =>
            current.some((item) => item.ledger_seq === event.ledger_seq)
              ? current
              : [...current, event].sort((a, b) => a.ledger_seq - b.ledger_seq),
          );
          setStreamState("live");
          void refetchSession();
        }
        retryConnection();
      } catch {
        retryConnection();
      }
    };
    void connect();
    return () => {
      controller.abort();
      if (retry !== undefined) clearTimeout(retry);
    };
  }, [connectionSessionId, connectionToken, refetchSession]);

  const visibleEvents = useMemo(() => {
    const events = connected ? ledgerEvents.map(realtimeCard) : timeline;
    if (eventFilter === "All events") return events;
    return events.filter((event) =>
      event.tags.some((tag) => tag.startsWith(eventFilter.toUpperCase())),
    );
  }, [connected, eventFilter, ledgerEvents]);

  const sessionStatus =
    connected && liveSession
      ? displayStatus(liveSession.data.status)
      : terminated
        ? "Terminated"
        : paused
          ? "Paused"
          : "Running";
  const statusKey = connected
    ? (liveSession?.data.status.toLowerCase() ?? "running")
    : sessionStatus.toLowerCase();
  const isTerminal = connected
    ? terminalStatuses.has(liveSession?.data.status ?? "")
    : terminated;
  const canGuide = connected
    ? ["RUNNING", "WAITING_FOR_HUMAN", "PAUSED"].includes(
        liveSession?.data.status ?? "",
      )
    : !terminated;
  const canUsePrimaryControl = connected
    ? ["DRAFT", "RUNNING", "WAITING_FOR_HUMAN", "PAUSED"].includes(
        liveSession?.data.status ?? "",
      )
    : !terminated;
  const connectedAgents: Agent[] = (
    liveSession?.data.agent_definition_ids ?? []
  ).map((id, index) => ({
    id,
    initials: `A${String(index + 1).padStart(2, "0")}`,
    name: id,
    role: "Pinned agent definition",
    color: ["#68b8ff", "#f09b61", "#c083ff", "#56d9a0"][index % 4] ?? "#68b8ff",
    status: "unavailable",
  }));
  const displayedAgents = connected ? connectedAgents : agents;
  const primaryLabel = connected
    ? liveSession?.data.status === "DRAFT"
      ? "Start"
      : liveSession?.data.status === "PAUSED"
        ? "Resume"
        : "Pause"
    : paused
      ? "Resume"
      : "Pause";

  async function runConnectedCommand(
    label: string,
    command: () => Promise<SessionResponse>,
  ) {
    setCommandPending(true);
    setCommandError("");
    try {
      await command();
      setCommandEvents((events) => [
        {
          id: crypto.randomUUID(),
          time: new Date().toLocaleTimeString([], { hour12: false }),
          title: `${label} accepted`,
          text: "Workflow accepted command. The ledger stream will deliver the authoritative transition.",
          tag: "COMMAND",
        },
        ...events,
      ]);
      return true;
    } catch (error) {
      setCommandError(errorMessage(error));
      return false;
    } finally {
      setCommandPending(false);
    }
  }

  async function submitGuidance(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const instruction = guidance.trim();
    if (!instruction) return;
    if (connection && liveSession) {
      const sent = await runConnectedCommand("Human directive", () =>
        apiClient.submitHumanInput(
          liveSession.data.id,
          {
            reason: "Operator directive submitted from live console",
            kind: directiveKind,
            instruction,
            artifact_ids: [],
          },
          connection.token,
          idempotencyKey("human-input"),
        ),
      );
      if (!sent) return;
    }
    setSentGuidance(instruction);
    setGuidance("");
  }

  function primaryControl() {
    if (!connection || !liveSession) return;
    if (liveSession.data.status === "DRAFT") {
      void runConnectedCommand("Start", () =>
        apiClient.startSession(
          liveSession.data.id,
          connection.token,
          idempotencyKey("start"),
        ),
      );
    } else if (liveSession.data.status === "PAUSED") {
      void runConnectedCommand("Resume", () =>
        apiClient.resumeSession(
          liveSession.data.id,
          { reason: "Operator resumed session from live console" },
          connection.token,
          idempotencyKey("resume"),
        ),
      );
    } else {
      void runConnectedCommand("Pause", () =>
        apiClient.pauseSession(
          liveSession.data.id,
          { reason: "Operator paused session from live console" },
          connection.token,
          idempotencyKey("pause"),
        ),
      );
    }
  }

  return (
    <main id="main-content" className="live-page">
      <header className="session-bar">
        <div className="session-title">
          <a href="#/">Sessions</a>
          <Icon name="chevron" size={13} />
          <div>
            <h1>
              {connected
                ? liveSession?.data.problem_statement
                : "Market expansion strategy"}
            </h1>
            <p>
              {connected
                ? liveSession?.data.id
                : "Should we enter the APAC market in Q3 2026?"}
            </p>
          </div>
        </div>
        <div className="session-controls">
          <span className={`live-badge live-badge--${statusKey}`}>
            <i /> {sessionStatus}
          </span>
          <button
            disabled={!canUsePrimaryControl || commandPending}
            onClick={() => {
              if (connected) primaryControl();
              else setPaused((value) => !value);
            }}
            type="button"
          >
            <Icon
              name={primaryLabel === "Pause" ? "pause" : "activity"}
              size={14}
            />
            {primaryLabel}
          </button>
          <button
            className="danger-button"
            disabled={
              isTerminal ||
              commandPending ||
              liveSession?.data.status === "DRAFT"
            }
            onClick={() => {
              if (connection && liveSession) {
                void runConnectedCommand("Cancel", () =>
                  apiClient.cancelSession(
                    liveSession.data.id,
                    { reason: "Operator cancelled session from live console" },
                    connection.token,
                    idempotencyKey("cancel"),
                  ),
                );
              } else {
                setTerminated(true);
              }
            }}
            type="button"
          >
            <Icon name="stop" size={14} /> {connected ? "Cancel" : "Terminate"}
          </button>
          <button
            aria-label="Session actions"
            className="more-button"
            type="button"
          >
            •••
          </button>
        </div>
      </header>

      {commandError || sessionQuery.error ? (
        <p className="console-notice" role="alert">
          {commandError || errorMessage(sessionQuery.error)}
        </p>
      ) : connected ? (
        <p className="console-notice" role="status">
          Restored from PostgreSQL · ledger stream {streamState} · reconnects
          resume by sequence
        </p>
      ) : null}

      <section className="session-progress" aria-label="Session progress">
        <div>
          <span>Round</span>
          <strong>
            {connected ? liveSession?.data.round : 2}{" "}
            <small>
              of {connected ? liveSession?.data.budget.max_rounds : 5}
            </small>
          </strong>
        </div>
        <div>
          <span>Elapsed</span>
          <strong>
            <Icon name="clock" size={13} />{" "}
            {connected
              ? elapsedSince(liveSession?.data.started_at ?? null)
              : "12m 34s"}
          </strong>
        </div>
        <div>
          <span>Tokens</span>
          <strong>
            {connected ? "—" : "8,247"}{" "}
            <small>
              / {connected ? liveSession?.data.budget.max_tokens : "25,000"}
            </small>
          </strong>
        </div>
        <div>
          <span>Cost</span>
          <strong>
            {connected ? "—" : "$1.24"}{" "}
            <small>
              / ${connected ? liveSession?.data.budget.max_usd : "5.00"}
            </small>
          </strong>
        </div>
        <div className="round-phase">
          <span>Round progress</span>
          <strong>{connected ? sessionStatus : "Agent reasoning"}</strong>
          <span className="progress-track">
            <i
              style={
                connected && liveSession
                  ? {
                      width: `${Math.min(
                        100,
                        (liveSession.data.round /
                          Math.max(1, liveSession.data.budget.max_rounds)) *
                          100,
                      )}%`,
                    }
                  : undefined
              }
            />
          </span>
        </div>
      </section>

      <div className="reasoning-console">
        <aside className="agents-panel">
          <div className="panel-heading">
            <div>
              <Icon name="users" />
              <h2>Agents</h2>
              <span>{displayedAgents.length}</span>
            </div>
            <button
              aria-label="Agent settings"
              className="bare-button"
              type="button"
            >
              <Icon name="settings" />
            </button>
          </div>
          <div className="agent-list">
            {displayedAgents.map((agent) => (
              <button
                className={
                  selectedAgent === agent.id
                    ? "agent-row agent-row--selected"
                    : "agent-row"
                }
                key={agent.id}
                onClick={() => setSelectedAgent(agent.id)}
                type="button"
              >
                <AgentAvatar agent={agent} />
                <span className="agent-copy">
                  <strong>{agent.name}</strong>
                  <small>{agent.role}</small>
                </span>
                <span className="agent-chevron">
                  <Icon name="chevron" size={13} />
                </span>
              </button>
            ))}
          </div>
          {connected ? (
            <p className="agent-legend agent-legend--unavailable">
              Per-agent activity unavailable in current API projection.
            </p>
          ) : (
            <div className="agent-legend">
              <span>
                <i className="dot dot--working" /> Working
              </span>
              <span>
                <i className="dot dot--complete" /> Complete
              </span>
              <span>
                <i className="dot dot--waiting" /> Waiting
              </span>
            </div>
          )}
        </aside>

        <section className="timeline-panel" aria-labelledby="timeline-title">
          <div className="panel-heading timeline-heading">
            <div>
              <Icon name="radio" />
              <h2 id="timeline-title">Reasoning timeline</h2>
              <span className="live-pill">
                <i /> {connected ? displayStatus(streamState) : "Live"}
              </span>
            </div>
            {!connected ? (
              <label className="event-filter">
                <span className="sr-only">Filter timeline</span>
                <select
                  value={eventFilter}
                  onChange={(event) => setEventFilter(event.target.value)}
                >
                  <option>All events</option>
                  <option>Claim</option>
                  <option>Evidence</option>
                  <option>Risk</option>
                  <option>Alternative</option>
                </select>
              </label>
            ) : null}
          </div>
          <div className="timeline-stream">
            <div className="round-divider">
              <span>Round {connected ? liveSession?.data.round : 2}</span>
              <i />
              <small>
                {connected ? "Authoritative projection" : "Started 1m 23s ago"}
              </small>
            </div>
            {connected ? (
              <>
                {commandEvents.map((event) => (
                  <article
                    className="timeline-event timeline-event--green"
                    key={event.id}
                  >
                    <time>{event.time}</time>
                    <span className="timeline-node">
                      <Icon name="activity" size={13} />
                    </span>
                    <div className="event-card">
                      <div className="event-heading-static">
                        <strong>Operator</strong>
                        <small>{event.title}</small>
                      </div>
                      <p>{event.text}</p>
                      <div className="event-tags">
                        <span>{event.tag}</span>
                      </div>
                    </div>
                  </article>
                ))}
                {visibleEvents.map((event, index) => (
                  <article
                    className={`timeline-event timeline-event--${event.tone}`}
                    key={`${event.time}-${event.title}-${event.tags[0]}`}
                  >
                    <time>{event.time}</time>
                    <span className="timeline-node">
                      <Icon name="activity" size={13} />
                    </span>
                    <div className="event-card">
                      <button
                        aria-expanded={expandedEvent === index}
                        onClick={() =>
                          setExpandedEvent(
                            expandedEvent === index ? null : index,
                          )
                        }
                        type="button"
                      >
                        <span>
                          <strong>{event.agent}</strong>
                          <small>{event.title}</small>
                        </span>
                        <Icon name="chevron" size={13} />
                      </button>
                      <p>{event.text}</p>
                      <div className="event-tags">
                        {event.tags.map((tag) => (
                          <span key={tag}>{tag}</span>
                        ))}
                      </div>
                      {expandedEvent === index ? (
                        <div className="event-detail">
                          Restored from the authoritative ledger sequence
                        </div>
                      ) : null}
                    </div>
                  </article>
                ))}
                {visibleEvents.length === 0 ? (
                  <div className="timeline-empty">
                    <Icon name="radio" size={18} />
                    <strong>Waiting for the first committed event</strong>
                    <span>
                      Reconnects replay directly from the PostgreSQL ledger.
                    </span>
                  </div>
                ) : null}
              </>
            ) : (
              visibleEvents.map((event, index) => {
                const agent = agents.find((item) => item.name === event.agent);
                return (
                  <article
                    className={`timeline-event timeline-event--${event.tone}`}
                    key={`${event.time}-${event.title}`}
                  >
                    <time>{event.time}</time>
                    <span className="timeline-node">
                      {agent ? (
                        <AgentAvatar agent={agent} small />
                      ) : (
                        <Icon name="activity" size={13} />
                      )}
                    </span>
                    <div className="event-card">
                      <button
                        aria-expanded={expandedEvent === index}
                        onClick={() =>
                          setExpandedEvent(
                            expandedEvent === index ? null : index,
                          )
                        }
                        type="button"
                      >
                        <span>
                          <strong>{event.agent}</strong>
                          <small>{event.title}</small>
                        </span>
                        <Icon name="chevron" size={13} />
                      </button>
                      <p>{event.text}</p>
                      <div className="event-tags">
                        {event.tags.map((tag) => (
                          <span key={tag}>{tag}</span>
                        ))}
                      </div>
                      {expandedEvent === index ? (
                        <div className="event-detail">
                          Ledger event verified · provenance attached ·
                          available for challenge
                        </div>
                      ) : null}
                    </div>
                  </article>
                );
              })
            )}
            {!connected ? (
              <div className="thinking-row">
                <span className="thinking-dots">
                  <i />
                  <i />
                  <i />
                </span>
                <span>2 agents are reasoning</span>
              </div>
            ) : null}
          </div>
          <form
            className="guidance-box"
            onSubmit={(event) => void submitGuidance(event)}
          >
            <div className="guidance-heading">
              <label htmlFor="guidance">Human guidance</label>
              {connected ? (
                <select
                  aria-label="Guidance type"
                  onChange={(event) =>
                    setDirectiveKind(
                      event.target.value as HumanInputCreate["kind"],
                    )
                  }
                  value={directiveKind}
                >
                  <option value="REQUEST_CRITIQUE">Request critique</option>
                  <option value="INJECT_EVIDENCE">Inject evidence</option>
                  <option value="ADD_CONSTRAINT">Add constraint</option>
                  <option value="MODIFY_OBJECTIVE">Modify objective</option>
                  <option value="REQUEST_SIMULATION">Request simulation</option>
                  <option value="REQUEST_ANOTHER_ROUND">
                    Request another round
                  </option>
                  <option value="REJECT_RECOMMENDATION">
                    Reject recommendation
                  </option>
                  <option value="OVERRIDE_OUTCOME">Override outcome</option>
                </select>
              ) : null}
            </div>
            <div>
              <textarea
                disabled={!canGuide || commandPending}
                id="guidance"
                onChange={(event) => setGuidance(event.target.value)}
                placeholder="Provide guidance or ask a question to the agents..."
                rows={2}
                value={guidance}
              />
              <button
                aria-label="Send guidance"
                disabled={!guidance.trim() || !canGuide || commandPending}
                type="submit"
              >
                <Icon name="send" size={17} />
              </button>
            </div>
            <small>
              {sentGuidance
                ? `Sent: ${sentGuidance}`
                : canGuide
                  ? "Your input will be visible to all agents and recorded in the audit trail."
                  : "Human directives are accepted while running, waiting for human input, or paused."}
            </small>
          </form>
        </section>

        <aside className="state-panel">
          <div className="panel-heading">
            <div>
              <Icon name="activity" />
              <h2>Session state</h2>
            </div>
          </div>
          <section className="state-section">
            <h3>
              <Icon name="target" /> Objectives{" "}
              <span>
                {connected ? liveSession?.data.objective_ids.length : 2}
              </span>
            </h3>
            <ul>
              {connected ? (
                liveSession?.data.objective_ids.map((id) => (
                  <li key={id}>{id}</li>
                ))
              ) : (
                <>
                  <li>Assess APAC market opportunity</li>
                  <li>Identify optimal entry strategy</li>
                </>
              )}
            </ul>
          </section>
          <section className="state-section">
            <h3>
              <Icon name="network" /> Constraints{" "}
              <span>
                {connected ? liveSession?.data.constraint_ids.length : 3}
              </span>
            </h3>
            <ul>
              {connected ? (
                liveSession?.data.constraint_ids.length ? (
                  liveSession.data.constraint_ids.map((id) => (
                    <li key={id}>{id}</li>
                  ))
                ) : (
                  <li>No bound constraints</li>
                )
              ) : (
                <>
                  <li>Budget: $2M initial investment</li>
                  <li>Timeline: Launch by Q4 2026</li>
                  <li>Minimum 15% projected ROI</li>
                </>
              )}
            </ul>
          </section>
          <section className="state-section">
            <h3>
              <Icon name="grid" /> Artifacts <span>{connected ? "—" : 12}</span>
            </h3>
            {connected ? (
              <p className="state-unavailable">
                Artifact listing unavailable in current API contract.
              </p>
            ) : (
              <div className="artifact-counts">
                <span>
                  <i className="square square--blue" /> Claims <b>4</b>
                </span>
                <span>
                  <i className="square square--violet" /> Evidence <b>3</b>
                </span>
                <span>
                  <i className="square square--orange" /> Risks <b>2</b>
                </span>
                <span>
                  <i className="square square--green" /> Alternatives <b>3</b>
                </span>
              </div>
            )}
          </section>
          <section className="state-section">
            <h3>
              <Icon name="coins" /> Budget usage
            </h3>
            <div className="budget-line">
              <span>Tokens</span>
              <b>{connected ? "limit" : "33%"}</b>
              <i>
                <em style={{ width: connected ? "0%" : "33%" }} />
              </i>
            </div>
            <div className="budget-line">
              <span>Cost</span>
              <b>{connected ? "limit" : "25%"}</b>
              <i>
                <em style={{ width: connected ? "0%" : "25%" }} />
              </i>
            </div>
            <div className="budget-line">
              <span>Rounds</span>
              <b>
                {connected && liveSession
                  ? `${Math.round(
                      (liveSession.data.round /
                        Math.max(1, liveSession.data.budget.max_rounds)) *
                        100,
                    )}%`
                  : "40%"}
              </b>
              <i>
                <em
                  style={{
                    width:
                      connected && liveSession
                        ? `${Math.min(
                            100,
                            (liveSession.data.round /
                              Math.max(1, liveSession.data.budget.max_rounds)) *
                              100,
                          )}%`
                        : "40%",
                  }}
                />
              </i>
            </div>
            {connected ? (
              <p className="state-unavailable">
                Usage counters unavailable. Limits:{" "}
                {liveSession?.data.budget.max_tokens} tokens / $
                {liveSession?.data.budget.max_usd}.
              </p>
            ) : null}
          </section>
          <a className="audit-link" href="#/audit">
            <Icon name="history" /> View audit trail
          </a>
        </aside>
      </div>
    </main>
  );
}
