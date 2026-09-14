import { lazy, Suspense, useEffect, useState } from "react";

import { apiClient, type SessionResponse } from "../api/client";
import { Icon } from "../components/icon";
import { Wordmark } from "../components/wordmark";
import { ArchitecturePage } from "../features/architecture/architecture-page";
import { ObservatoryPage } from "../features/observability/observatory-page";
import { NewSessionPage } from "../features/reasoning/new-session-page";
import { ReasoningPage } from "../features/reasoning/reasoning-page";
import { hrefForRoute } from "./router";
import { useHashRoute } from "./use-hash-route";

const GraphPage = lazy(() => import("../features/graph/graph-page"));
const DissentPage = lazy(() => import("../features/dissent/dissent-page"));
const AssumptionRegisterPage = lazy(
  () => import("../features/assumptions/assumption-register-page"),
);

const navigation = [
  {
    route: "reasoning" as const,
    label: "Live reasoning",
    icon: "activity" as const,
  },
  {
    route: "dissent" as const,
    label: "Dissent view",
    icon: "message" as const,
  },
  {
    route: "assumptions" as const,
    label: "Assumption register",
    icon: "archive" as const,
  },
  {
    route: "graph" as const,
    label: "Graph view",
    icon: "network" as const,
  },
  {
    route: "observatory" as const,
    label: "Observatory",
    icon: "grid" as const,
  },
  {
    route: "architecture" as const,
    label: "Architecture",
    icon: "network" as const,
  },
];

export function App() {
  const route = useHashRoute();
  const [liveSession, setLiveSession] = useState<{
    session: SessionResponse;
    token: string;
  }>();
  useEffect(() => {
    let active = true;
    try {
      const stored = localStorage.getItem("agora.live-session");
      if (stored === null) return;
      const recovery = JSON.parse(stored) as {
        sessionId: string;
        token: string;
      };
      void apiClient
        .getSession(recovery.sessionId, recovery.token)
        .then((session) => {
          if (active) setLiveSession({ session, token: recovery.token });
        })
        .catch(() => localStorage.removeItem("agora.live-session"));
    } catch {
      localStorage.removeItem("agora.live-session");
    }
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="console-shell">
      <header className="console-topbar">
        <a className="console-brand" href={hrefForRoute("reasoning")}>
          <Wordmark />
          <span>Collective Reasoning</span>
        </a>
        <div className="console-topbar__actions">
          <div className="system-indicator">
            <i /> <span>All systems operational</span>
          </div>
          <button
            aria-label="Notifications"
            className="icon-button"
            type="button"
          >
            <Icon name="bell" size={17} />
            <span className="notification-dot" />
          </button>
          <span
            className="operator-badge"
            aria-label="Signed in as Alex Morgan"
          >
            AM
          </span>
        </div>
      </header>

      <aside className="console-sidebar">
        <nav aria-label="Primary navigation">
          <p className="nav-label">Workspace</p>
          {navigation.map((item) => (
            <a
              aria-current={route === item.route ? "page" : undefined}
              href={hrefForRoute(item.route)}
              key={item.route}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </a>
          ))}
          <p className="nav-label nav-label--second">Manage</p>
          <a
            aria-current={route === "new-session" ? "page" : undefined}
            href="#/new-session"
          >
            <Icon name="plus" />
            <span>New session</span>
          </a>
          <a href="#/">
            <Icon name="users" />
            <span>Agents</span>
          </a>
          <a href="#/">
            <Icon name="book" />
            <span>Knowledge base</span>
          </a>
          <a href="#/">
            <Icon name="flask" />
            <span>Experiments</span>
          </a>
        </nav>
        <div className="sidebar-foot">
          <a href="#/">
            <Icon name="settings" />
            <span>Settings</span>
          </a>
          <span className="build-id">AGORA / BUILD 0.4.5</span>
        </div>
      </aside>

      <div className="console-content">
        {route === "architecture" ? (
          <ArchitecturePage />
        ) : route === "observatory" ? (
          <ObservatoryPage />
        ) : route === "new-session" ? (
          <NewSessionPage
            onMonitorSession={(session, token) => {
              const connection = { session, token };
              localStorage.setItem(
                "agora.live-session",
                JSON.stringify({ sessionId: session.data.id, token }),
              );
              setLiveSession(connection);
              window.location.hash = hrefForRoute("reasoning");
            }}
          />
        ) : route === "dissent" ? (
          <Suspense
            fallback={
              <main
                className="dissent-page dissent-page--loading"
                id="main-content"
              >
                <p role="status">Loading dissent workspace...</p>
              </main>
            }
          >
            <DissentPage
              {...(liveSession ? { connection: liveSession } : {})}
            />
          </Suspense>
        ) : route === "assumptions" ? (
          <Suspense
            fallback={
              <main
                className="assumption-page assumption-page--loading"
                id="main-content"
              >
                <p role="status">Loading assumption register...</p>
              </main>
            }
          >
            <AssumptionRegisterPage
              {...(liveSession ? { connection: liveSession } : {})}
            />
          </Suspense>
        ) : route === "graph" ? (
          <Suspense
            fallback={
              <main
                className="graph-page graph-page--loading"
                id="main-content"
              >
                <p role="status">Loading graph workspace…</p>
              </main>
            }
          >
            <GraphPage {...(liveSession ? { connection: liveSession } : {})} />
          </Suspense>
        ) : (
          <ReasoningPage
            {...(liveSession ? { connection: liveSession } : {})}
          />
        )}
      </div>
    </div>
  );
}
