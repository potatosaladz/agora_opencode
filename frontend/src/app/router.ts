export type AppRoute =
  | "reasoning"
  | "new-session"
  | "dissent"
  | "graph"
  | "observatory"
  | "architecture";

export function routeFromHash(hash: string): AppRoute {
  if (hash === "#/architecture") return "architecture";
  if (hash === "#/observatory") return "observatory";
  if (hash === "#/new-session") return "new-session";
  if (hash === "#/dissent") return "dissent";
  if (hash === "#/graph" || hash.startsWith("#/graph?")) return "graph";
  return "reasoning";
}

export function hrefForRoute(route: AppRoute): string {
  if (route === "architecture") return "#/architecture";
  if (route === "observatory") return "#/observatory";
  if (route === "new-session") return "#/new-session";
  if (route === "dissent") return "#/dissent";
  if (route === "graph") return "#/graph";
  return "#/";
}
