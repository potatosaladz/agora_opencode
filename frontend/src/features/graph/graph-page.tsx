import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";

import {
  ApiProblem,
  apiClient,
  type GraphEdge,
  type GraphEdgeType,
  type GraphNode,
  type GraphSubgraphRequest,
  type SessionResponse,
} from "../../api/client";

type GraphConnection = { session: SessionResponse; token: string };
type QueryInput = Omit<GraphSubgraphRequest, "cursor">;

const edgeKinds: GraphEdgeType[] = [
  "SUPPORTS",
  "OPPOSES",
  "CONTRADICTS",
  "ATTACKS",
  "DERIVED_FROM",
  "BASED_ON_ASSUMPTION",
  "FORMALIZES",
  "QUANTIFIES",
  "IMPACTS",
  "CONSTRAINS",
  "VIOLATES",
  "SATISFIES",
  "INFEASIBLE_UNKNOWN",
  "RESPONDS_TO",
  "SUPERSEDES",
  "ADVOCATES",
];

function uniqueById<T extends { id: string }>(items: T[]): T[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiProblem) return error.problem.detail;
  if (error instanceof Error) return error.message;
  return "The graph query failed.";
}

function edgeClass(kind: GraphEdgeType): string {
  if (["SUPPORTS", "OPPOSES", "CONTRADICTS", "ATTACKS"].includes(kind)) {
    return `graph-edge graph-edge--${kind.toLowerCase()}`;
  }
  return "graph-edge graph-edge--other";
}

function shortId(id: string): string {
  return id.length > 19 ? `${id.slice(0, 11)}…${id.slice(-5)}` : id;
}

function GraphCanvas({
  nodes,
  edges,
  selectedId,
  onSelect,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const nodeRefs = useRef(new Map<string, SVGGElement>());
  const width = 960;
  const height = Math.max(440, Math.ceil(nodes.length / 5) * 150 + 100);
  const columns = Math.min(5, Math.max(1, nodes.length));
  const positions = new Map(
    nodes.map((node, index) => [
      node.id,
      {
        x: ((index % columns) + 0.5) * (width / columns),
        y: Math.floor(index / columns) * 150 + 90,
      },
    ]),
  );

  function moveSelection(event: KeyboardEvent<SVGGElement>, index: number) {
    const direction =
      event.key === "ArrowRight" || event.key === "ArrowDown"
        ? 1
        : event.key === "ArrowLeft" || event.key === "ArrowUp"
          ? -1
          : 0;
    if (direction === 0) return;
    event.preventDefault();
    const next = nodes[(index + direction + nodes.length) % nodes.length];
    if (!next) return;
    onSelect(next.id);
    nodeRefs.current.get(next.id)?.focus();
  }

  return (
    <div className="graph-canvas-wrap">
      <svg
        aria-label="Reasoning graph. Use arrow keys to move between nodes."
        className="graph-canvas"
        role="group"
        viewBox={`0 0 ${width} ${height}`}
      >
        <defs>
          <pattern
            id="edge-other-pattern"
            width="8"
            height="8"
            patternUnits="userSpaceOnUse"
          >
            <path d="M0 8 8 0" stroke="currentColor" strokeWidth="1" />
          </pattern>
          <marker
            id="graph-arrow"
            markerHeight="8"
            markerWidth="8"
            orient="auto"
            refX="7"
            refY="4"
          >
            <path d="M0 0 8 4 0 8Z" fill="context-stroke" />
          </marker>
        </defs>
        <g aria-hidden="true">
          {edges.map((edge) => {
            const from = positions.get(edge.from_node);
            const to = positions.get(edge.to_node);
            if (!from || !to) return null;
            const labelX = (from.x + to.x) / 2;
            const labelY = (from.y + to.y) / 2 - 8;
            return (
              <g key={edge.id}>
                <line
                  className={edgeClass(edge.edge_type)}
                  markerEnd="url(#graph-arrow)"
                  x1={from.x}
                  x2={to.x}
                  y1={from.y}
                  y2={to.y}
                />
                <text
                  className="graph-edge-label"
                  textAnchor="middle"
                  x={labelX}
                  y={labelY}
                >
                  {edge.edge_type}
                </text>
              </g>
            );
          })}
        </g>
        {nodes.map((node, index) => {
          const position = positions.get(node.id)!;
          const selected = node.id === selectedId;
          return (
            <g
              aria-label={`${node.kind}: ${node.label}`}
              aria-pressed={selected}
              className={`graph-node${selected ? " graph-node--selected" : ""}`}
              key={node.id}
              onClick={() => onSelect(node.id)}
              onKeyDown={(event) => moveSelection(event, index)}
              ref={(element) => {
                if (element) nodeRefs.current.set(node.id, element);
                else nodeRefs.current.delete(node.id);
              }}
              role="button"
              tabIndex={
                selected || (selectedId === null && index === 0) ? 0 : -1
              }
              transform={`translate(${position.x} ${position.y})`}
            >
              <rect height="66" rx="4" width="152" x="-76" y="-33" />
              <text className="graph-node-kind" textAnchor="middle" y="-8">
                {node.kind}
              </text>
              <text className="graph-node-label" textAnchor="middle" y="13">
                {node.label.length > 21
                  ? `${node.label.slice(0, 20)}…`
                  : node.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export default function GraphPage({
  connection,
}: {
  connection?: GraphConnection;
}) {
  const [roots, setRoots] = useState("");
  const [depth, setDepth] = useState(2);
  const [pageSize, setPageSize] = useState(100);
  const [filter, setFilter] = useState<GraphEdgeType[]>([]);
  const [queryInput, setQueryInput] = useState<QueryInput | null>(null);
  const [queryRevision, setQueryRevision] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const query = useInfiniteQuery({
    enabled: connection !== undefined && queryInput !== null,
    initialPageParam: undefined as string | undefined,
    queryKey: [
      "graph-subgraph",
      connection?.session.data.id,
      queryInput,
      queryRevision,
    ],
    queryFn: ({ pageParam, signal }) =>
      apiClient.getGraphSubgraph(
        {
          ...queryInput!,
          ...(pageParam === undefined ? {} : { cursor: pageParam }),
        },
        connection!.token,
        signal,
      ),
    getNextPageParam: (lastPage) => lastPage.data.next_cursor ?? undefined,
  });

  const nodes = uniqueById(
    query.data?.pages.flatMap((page) => page.data.nodes) ?? [],
  );
  const edges = uniqueById(
    query.data?.pages.flatMap((page) => page.data.edges) ?? [],
  );
  const truncated =
    query.data?.pages.some((page) => page.data.truncated) ?? false;
  const selected = nodes.find((node) => node.id === selectedId) ?? null;

  useEffect(() => {
    if (nodes.length && !nodes.some((node) => node.id === selectedId)) {
      setSelectedId(nodes[0]!.id);
    }
  }, [nodes, selectedId]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!connection) return;
    const rootIds = roots
      .split(/[\s,]+/)
      .map((value) => value.trim())
      .filter(Boolean);
    if (!rootIds.length) return;
    setSelectedId(null);
    setQueryRevision((value) => value + 1);
    setQueryInput({
      session_id: connection.session.data.id,
      root_ids: rootIds,
      max_depth: depth,
      page_size: pageSize,
      ...(filter.length ? { edge_types: filter } : {}),
    });
  }

  return (
    <main className="graph-page" id="main-content">
      <header className="graph-header">
        <div>
          <p>Authoritative projection / bounded traversal</p>
          <h1>Reasoning graph</h1>
        </div>
        <span
          className={
            connection ? "graph-session graph-session--live" : "graph-session"
          }
        >
          {connection
            ? `Session ${shortId(connection.session.data.id)}`
            : "No restored session"}
        </span>
      </header>

      {!connection ? (
        <section
          className="graph-no-session"
          aria-labelledby="graph-session-title"
        >
          <span aria-hidden="true">∅</span>
          <div>
            <h2 id="graph-session-title">A live session is required</h2>
            <p>
              Start or restore a session first. Graph roots are public IDs, but
              the request still requires the session’s bearer token and tenant
              scope.
            </p>
            <a href="#/new-session">Create a session</a>
          </div>
        </section>
      ) : (
        <>
          <form className="graph-query" onSubmit={submit}>
            <label className="graph-query__roots" htmlFor="graph-roots">
              <span>Public graph root IDs</span>
              <textarea
                aria-describedby="root-help"
                aria-label="Public graph root IDs"
                id="graph-roots"
                onChange={(event) => setRoots(event.target.value)}
                placeholder="gnd_… (comma or line separated)"
                required
                rows={2}
                value={roots}
              />
              <small id="root-help">
                Roots are sent unchanged; the server resolves visibility and
                scope.
              </small>
            </label>
            <label>
              <span>Radius</span>
              <input
                max="5"
                min="0"
                onChange={(event) => setDepth(event.target.valueAsNumber)}
                type="number"
                value={depth}
              />
            </label>
            <label>
              <span>Page size</span>
              <input
                max="200"
                min="1"
                onChange={(event) => setPageSize(event.target.valueAsNumber)}
                type="number"
                value={pageSize}
              />
            </label>
            <fieldset>
              <legend>
                Relationship filters <small>(none = all)</small>
              </legend>
              <div>
                {edgeKinds.map((kind) => (
                  <label key={kind}>
                    <input
                      checked={filter.includes(kind)}
                      onChange={(event) =>
                        setFilter((current) =>
                          event.target.checked
                            ? [...current, kind]
                            : current.filter((item) => item !== kind),
                        )
                      }
                      type="checkbox"
                    />
                    <span>{kind.replaceAll("_", " ")}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <button disabled={query.isFetching || !roots.trim()} type="submit">
              {query.isFetching && !query.isFetchingNextPage
                ? "Querying…"
                : "Query graph"}
            </button>
          </form>

          {query.isPending && queryInput ? (
            <div className="graph-state" role="status">
              <i />
              Reading authoritative nodes and edges…
            </div>
          ) : null}
          {query.error ? (
            <div className="graph-state graph-state--error" role="alert">
              <strong>Graph unavailable</strong>
              <span>{errorMessage(query.error)}</span>
            </div>
          ) : null}
          {query.isSuccess && nodes.length === 0 ? (
            <div className="graph-state">
              <strong>No graph members returned</strong>
              <span>
                Try another visible root, a larger radius, or fewer relationship
                filters.
              </span>
            </div>
          ) : null}

          {nodes.length ? (
            <section
              className="graph-results"
              aria-labelledby="graph-results-title"
            >
              <div className="graph-results__bar">
                <div>
                  <h2 id="graph-results-title">Subgraph</h2>
                  <span>
                    {nodes.length} nodes / {edges.length} edges
                  </span>
                </div>
                <div
                  className="graph-legend"
                  aria-label="Relationship appearance legend"
                >
                  <span>
                    <i className="supports" /> SUPPORTS
                  </span>
                  <span>
                    <i className="opposes" /> OPPOSES
                  </span>
                  <span>
                    <i className="contradicts" /> CONTRADICTS
                  </span>
                  <span>
                    <i className="attacks" /> ATTACKS
                  </span>
                  <span>
                    <i className="other" /> OTHER
                  </span>
                </div>
              </div>
              {truncated ? (
                <p className="graph-disclosure" role="status">
                  <strong>Depth truncated.</strong> More connected members exist
                  beyond radius {queryInput?.max_depth}. This is independent of
                  pagination.
                </p>
              ) : null}
              <GraphCanvas
                edges={edges}
                nodes={nodes}
                onSelect={setSelectedId}
                selectedId={selectedId}
              />
              {selected ? (
                <aside className="graph-selection" aria-live="polite">
                  <span>Selected node</span>
                  <strong>{selected.label}</strong>
                  <code>{selected.id}</code>
                  <p>
                    {selected.kind} / artifact {selected.ref_id}
                  </p>
                </aside>
              ) : null}
              {query.hasNextPage ? (
                <div className="graph-pagination">
                  <p>Additional server-ordered members are available.</p>
                  <button
                    disabled={query.isFetchingNextPage}
                    onClick={() => void query.fetchNextPage()}
                    type="button"
                  >
                    {query.isFetchingNextPage
                      ? "Loading next page…"
                      : "Load more"}
                  </button>
                </div>
              ) : null}

              <section
                className="graph-text"
                aria-labelledby="graph-text-title"
              >
                <div>
                  <p>Textual equivalent</p>
                  <h2 id="graph-text-title">Nodes and relationships</h2>
                </div>
                <div className="graph-text__columns">
                  <div>
                    <h3>Nodes</h3>
                    <ol>
                      {nodes.map((node) => (
                        <li key={node.id}>
                          <button
                            aria-pressed={node.id === selectedId}
                            onClick={() => setSelectedId(node.id)}
                            type="button"
                          >
                            <strong>{node.label}</strong>
                            <span>
                              {node.kind} · {node.id}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ol>
                  </div>
                  <div>
                    <h3>Edges</h3>
                    {edges.length ? (
                      <ol>
                        {edges.map((edge) => (
                          <li key={edge.id}>
                            <strong>{edge.edge_type}</strong>
                            <span>
                              {edge.from_node} → {edge.to_node}
                            </span>
                            {edge.weight === null ? null : (
                              <small>Weight {edge.weight}</small>
                            )}
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <p>No relationships were returned for these nodes.</p>
                    )}
                  </div>
                </div>
              </section>
            </section>
          ) : null}
        </>
      )}
    </main>
  );
}
