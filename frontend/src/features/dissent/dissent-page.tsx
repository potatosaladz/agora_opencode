import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import {
  ApiProblem,
  apiClient,
  type DissentResponse,
  type SessionResponse,
} from "../../api/client";

type DissentConnection = { session: SessionResponse; token: string };
type MinorityEntry = DissentResponse["data"]["minority"][number];
type CritiqueEntry = DissentResponse["data"]["critiques"][number];

function errorMessage(error: unknown): string {
  if (error instanceof ApiProblem) return error.problem.detail;
  if (error instanceof Error) return error.message;
  return "The dissent record could not be read.";
}

function words(value: string): string {
  return value.replaceAll("_", " ").toLowerCase();
}

function graphHref(nodeId: string): string {
  return `#/graph?root=${encodeURIComponent(nodeId)}`;
}

function artifactHref(artifactId: string): string {
  return `/api/v1/artifacts/${encodeURIComponent(artifactId)}/provenance`;
}

function EmptyReason({
  reason,
}: {
  reason: DissentResponse["data"]["empty_reason"];
}) {
  const content = {
    NO_CONSENSUS_RESULT: {
      title: "No consensus result",
      detail:
        "This session has not produced a consensus result, so dissent has not been evaluated.",
    },
    CONSENSUS_EXPLANATION_UNAVAILABLE: {
      title: "Dissent unavailable",
      detail:
        "A consensus result exists, but its explanation and minority record are unavailable.",
    },
    EVALUATED_NO_DISSENT: {
      title: "No dissent recorded",
      detail:
        "The result was evaluated and contains no minority positions or unresolved critiques.",
    },
  } as const;
  const message = reason ? content[reason] : content.EVALUATED_NO_DISSENT;
  return (
    <section className="dissent-empty" aria-labelledby="dissent-empty-title">
      <span aria-hidden="true">0</span>
      <div>
        <h2 id="dissent-empty-title">{message.title}</h2>
        <p>{message.detail}</p>
      </div>
    </section>
  );
}

function ArtifactLink({
  artifactId,
  href,
  label,
}: {
  artifactId: string;
  href?: string;
  label?: string | null;
}) {
  return (
    <a href={href ?? artifactHref(artifactId)}>
      {label ?? artifactId}
      <span className="sr-only">: open artifact provenance</span>
    </a>
  );
}

function EvidenceContext({
  title,
  relation,
  values,
}: {
  title: string;
  relation: "supporting" | "opposing";
  values: DissentResponse["data"]["evidence_context"]["supports_selected"];
}) {
  return (
    <section className="dissent-evidence" aria-label={`${title} evidence`}>
      <h3>{title}</h3>
      {values.length ? (
        <ul className="dissent-artifacts">
          {values.map((evidence) => (
            <li key={evidence.id}>
              <div>
                <span>{relation} evidence</span>
                <ArtifactLink
                  artifactId={evidence.id}
                  href={evidence.provenance_href}
                  label={evidence.label}
                />
              </div>
              <strong>{evidence.lifecycle}</strong>
              {evidence.graph_node_id ? (
                <a href={graphHref(evidence.graph_node_id)}>Open in graph</a>
              ) : (
                <span className="unavailable">Graph node unavailable</span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="dissent-absence">No {relation} evidence was recorded.</p>
      )}
    </section>
  );
}

function MinorityCard({
  entry,
  index,
  selected,
  onSelect,
  onMove,
  setRef,
}: {
  entry: MinorityEntry;
  index: number;
  selected: boolean;
  onSelect: () => void;
  onMove: (event: KeyboardEvent<HTMLElement>, index: number) => void;
  setRef: (element: HTMLElement | null) => void;
}) {
  return (
    <article
      aria-current={selected ? "true" : undefined}
      aria-label={`${entry.position} minority position by ${entry.agent_id}`}
      className={`dissent-entry${selected ? " dissent-entry--selected" : ""}`}
      data-kind="minority"
      onClick={onSelect}
      onFocus={onSelect}
      onKeyDown={(event) => onMove(event, index)}
      ref={setRef}
      tabIndex={selected || index === 0 ? 0 : -1}
    >
      <header>
        <span>Minority position {String(index + 1).padStart(2, "0")}</span>
        <strong>{entry.position}</strong>
      </header>
      <div className="dissent-entry__body">
        <dl>
          <div>
            <dt>Agent</dt>
            <dd>{entry.agent_id}</dd>
          </div>
          <div>
            <dt>Position</dt>
            <dd>{entry.position}</dd>
          </div>
        </dl>
        <h3>Warrant</h3>
        {entry.warrants.length ? (
          <ul className="dissent-artifacts">
            {entry.warrants.map((warrant) => (
              <li key={warrant.id}>
                <div>
                  <span>{warrant.kind} evidence</span>
                  <ArtifactLink
                    artifactId={warrant.id}
                    href={warrant.provenance_href}
                    label={warrant.label}
                  />
                </div>
                <strong
                  className={`artifact-state artifact-state--${warrant.lifecycle.toLowerCase()}`}
                >
                  {warrant.lifecycle}
                </strong>
                {warrant.graph_node_id ? (
                  <a href={graphHref(warrant.graph_node_id)}>
                    Open in graph
                    <span className="sr-only"> at {warrant.graph_node_id}</span>
                  </a>
                ) : (
                  <span className="unavailable">Graph node unavailable</span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="dissent-absence">
            No warrant was recorded for this minority position.
          </p>
        )}
        <div className="dissent-change">
          <span>What would change this position</span>
          <p>
            {entry.what_would_change ?? "No change condition was recorded."}
          </p>
        </div>
        {entry.disputed_proposition_ids.length ? (
          <div className="dissent-related">
            <span>Disputed propositions</span>
            {entry.disputed_proposition_ids.map((id) => (
              <ArtifactLink artifactId={id} key={id} />
            ))}
          </div>
        ) : null}
        {entry.unresolved_critique_ids.length ? (
          <div className="dissent-related">
            <span>Unresolved critique references</span>
            {entry.unresolved_critique_ids.map((id) => (
              <a href={`#dissent-${encodeURIComponent(id)}`} key={id}>
                {id}
              </a>
            ))}
          </div>
        ) : null}
      </div>
    </article>
  );
}

function CritiqueCard({ entry }: { entry: CritiqueEntry }) {
  return (
    <article
      id={`dissent-${entry.critique_id}`}
      className={`critique-entry critique-entry--${entry.resolution.toLowerCase()}`}
    >
      <header>
        <span>{entry.resolution} critique</span>
        <strong>{words(entry.critique_type)}</strong>
        <small>Severity {entry.severity}</small>
      </header>
      <p>{entry.argument ?? "Critique argument unavailable."}</p>
      <dl>
        <div>
          <dt>Target</dt>
          <dd>
            <ArtifactLink artifactId={entry.target_artifact_id} />
          </dd>
        </div>
        <div>
          <dt>Response</dt>
          <dd>
            {entry.response_disposition
              ? words(entry.response_disposition)
              : "No response recorded; unresolved."}
          </dd>
        </div>
        <div>
          <dt>Version</dt>
          <dd>{entry.version}</dd>
        </div>
      </dl>
      <div className="critique-links">
        <ArtifactLink
          artifactId={entry.critique_artifact_id}
          href={entry.provenance_href}
          label="Critique provenance"
        />
        {entry.graph_node_id ? (
          <a href={graphHref(entry.graph_node_id)}>Open critique in graph</a>
        ) : (
          <span className="unavailable">Graph node unavailable</span>
        )}
      </div>
      <div className="critique-warrants">
        <span>Critique warrants</span>
        {entry.warrant_artifact_ids.length ? (
          entry.warrant_artifact_ids.map((id) => (
            <ArtifactLink artifactId={id} key={id} />
          ))
        ) : (
          <p>No warrant was recorded for this critique.</p>
        )}
      </div>
      {entry.replacement_target_artifact_id ? (
        <p>
          Replacement target:{" "}
          <ArtifactLink artifactId={entry.replacement_target_artifact_id} />
        </p>
      ) : null}
    </article>
  );
}

export default function DissentPage({
  connection,
}: {
  connection?: DissentConnection;
}) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const entryRefs = useRef<(HTMLElement | null)[]>([]);
  const query = useQuery({
    enabled: connection !== undefined,
    queryKey: ["session-dissent", connection?.session.data.id],
    queryFn: ({ signal }) =>
      apiClient.getSessionDissent(
        connection!.session.data.id,
        connection!.token,
        signal,
      ),
  });

  function moveSelection(
    event: KeyboardEvent<HTMLElement>,
    index: number,
    count: number,
  ) {
    let next = index;
    if (event.key === "ArrowDown" || event.key === "ArrowRight")
      next = (index + 1) % count;
    else if (event.key === "ArrowUp" || event.key === "ArrowLeft")
      next = (index - 1 + count) % count;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = count - 1;
    else return;
    event.preventDefault();
    setSelectedIndex(next);
    entryRefs.current[next]?.focus();
  }

  return (
    <main className="dissent-page" id="main-content">
      <header className="dissent-header">
        <div>
          <p>Preserved disagreement / no suppression</p>
          <h1>Dissent view</h1>
        </div>
        <span
          className={
            connection ? "graph-session graph-session--live" : "graph-session"
          }
        >
          {connection
            ? `Session ${connection.session.data.id}`
            : "No restored session"}
        </span>
      </header>
      {!connection ? (
        <section
          className="dissent-empty"
          aria-labelledby="dissent-session-title"
        >
          <span aria-hidden="true">!</span>
          <div>
            <h2 id="dissent-session-title">A restored session is required</h2>
            <p>
              Start or restore a session to inspect its preserved minority and
              critique record.
            </p>
            <a href="#/new-session">Create a session</a>
          </div>
        </section>
      ) : query.isPending ? (
        <div className="dissent-state" role="status">
          <i />
          Reading minority positions and unresolved critiques...
        </div>
      ) : query.error ? (
        <div className="dissent-state dissent-state--error" role="alert">
          <strong>Dissent unavailable</strong>
          <span>{errorMessage(query.error)}</span>
        </div>
      ) : query.data ? (
        <div className="dissent-record">
          {query.data.data.majority ? (
            <section
              className="majority-context"
              aria-labelledby="majority-title"
            >
              <div>
                <span>Selected / majority context</span>
                <h2 id="majority-title">
                  {query.data.data.majority.selected_alternative_label ??
                    query.data.data.majority.selected_alternative_id ??
                    "No alternative selected"}
                </h2>
              </div>
              <dl>
                <div>
                  <dt>Outcome</dt>
                  <dd>{words(query.data.data.majority.outcome)}</dd>
                </div>
                <div>
                  <dt>Strategy</dt>
                  <dd>
                    {query.data.data.majority.strategy} v
                    {query.data.data.majority.strategy_version}
                  </dd>
                </div>
                <div>
                  <dt>Round</dt>
                  <dd>{query.data.data.majority.round}</dd>
                </div>
              </dl>
              {query.data.data.majority.selected_alternative_id ? (
                <div className="critique-links">
                  <ArtifactLink
                    artifactId={
                      query.data.data.majority.selected_alternative_id
                    }
                    {...(query.data.data.majority
                      .selected_alternative_provenance_href
                      ? {
                          href: query.data.data.majority
                            .selected_alternative_provenance_href,
                        }
                      : {})}
                    label="Selected alternative provenance"
                  />
                  {query.data.data.majority
                    .selected_alternative_graph_node_id ? (
                    <a
                      href={graphHref(
                        query.data.data.majority
                          .selected_alternative_graph_node_id,
                      )}
                    >
                      Open selected alternative in graph
                    </a>
                  ) : null}
                </div>
              ) : (
                <p className="dissent-absence">
                  No selected alternative is available for this outcome.
                </p>
              )}
            </section>
          ) : null}
          {query.data.data.majority ? (
            <div className="dissent-evidence-context">
              <EvidenceContext
                relation="supporting"
                title="Evidence supporting the selected position"
                values={query.data.data.evidence_context.supports_selected}
              />
              <EvidenceContext
                relation="opposing"
                title="Evidence opposing the selected position"
                values={query.data.data.evidence_context.opposes_selected}
              />
              <EvidenceContext
                relation="supporting"
                title="Evidence qualifying the selected position"
                values={query.data.data.evidence_context.qualifies_selected}
              />
            </div>
          ) : null}
          {!query.data.data.minority.length &&
          !query.data.data.critiques.length ? (
            <EmptyReason reason={query.data.data.empty_reason} />
          ) : (
            <>
              <section
                className="minority-section"
                aria-labelledby="minority-title"
              >
                <header>
                  <div>
                    <span>Minority record</span>
                    <h2 id="minority-title">Preserved positions</h2>
                  </div>
                  <p>
                    {query.data.data.minority.length} entries. Use arrow keys to
                    move between positions.
                  </p>
                </header>
                {query.data.data.minority.length ? (
                  <div
                    aria-label="Minority positions"
                    className="minority-list"
                  >
                    {query.data.data.minority.map((entry, index) => (
                      <MinorityCard
                        entry={entry}
                        index={index}
                        key={`${entry.agent_id}-${index}`}
                        onMove={(event, current) =>
                          moveSelection(
                            event,
                            current,
                            query.data.data.minority.length,
                          )
                        }
                        onSelect={() => setSelectedIndex(index)}
                        selected={index === selectedIndex}
                        setRef={(element) => {
                          entryRefs.current[index] = element;
                        }}
                      />
                    ))}
                  </div>
                ) : (
                  <p className="dissent-absence">
                    No minority positions were recorded; unresolved critiques
                    are shown separately below.
                  </p>
                )}
              </section>
              <section
                className="critiques-section"
                aria-labelledby="critiques-title"
              >
                <header>
                  <span>Live objections</span>
                  <h2 id="critiques-title">
                    Open, unresolved and disputed critiques
                  </h2>
                </header>
                {query.data.data.critiques.length ? (
                  <div className="critiques-grid">
                    {query.data.data.critiques.map((entry) => (
                      <CritiqueCard
                        entry={entry}
                        key={`${entry.critique_id}-${entry.version}`}
                      />
                    ))}
                  </div>
                ) : (
                  <p className="dissent-absence">
                    No open, unresolved or disputed critiques were recorded.
                  </p>
                )}
              </section>
            </>
          )}
        </div>
      ) : null}
    </main>
  );
}
