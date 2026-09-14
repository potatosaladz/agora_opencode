export type AppRoute =
  "reasoning" | "new-session" | "observatory" | "architecture";

export function routeFromHash(hash: string): AppRoute {
  if (hash === "#/architecture") return "architecture";
  if (hash === "#/observatory") return "observatory";
  if (hash === "#/new-session") return "new-session";
  return "reasoning";
}

export function hrefForRoute(route: AppRoute): string {
  if (route === "architecture") return "#/architecture";
  if (route === "observatory") return "#/observatory";
  if (route === "new-session") return "#/new-session";
  return "#/";
}
