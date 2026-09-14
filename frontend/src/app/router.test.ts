import { hrefForRoute, routeFromHash } from "./router";

describe("hash router", () => {
  // req: FR-101
  it("falls back to the reasoning desk for unknown routes", () => {
    expect(routeFromHash("#/not-a-route")).toBe("reasoning");
  });

  // req: FR-101
  it("round-trips every known route", () => {
    expect(routeFromHash(hrefForRoute("observatory"))).toBe("observatory");
    expect(routeFromHash(hrefForRoute("architecture"))).toBe("architecture");
    expect(routeFromHash(hrefForRoute("new-session"))).toBe("new-session");
    expect(routeFromHash(hrefForRoute("dissent"))).toBe("dissent");
    expect(routeFromHash(hrefForRoute("assumptions"))).toBe("assumptions");
    expect(routeFromHash(hrefForRoute("graph"))).toBe("graph");
    expect(routeFromHash("#/graph?root=gnd_public")).toBe("graph");
    expect(routeFromHash(hrefForRoute("reasoning"))).toBe("reasoning");
  });
});
