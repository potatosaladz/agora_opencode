import { describe, expect, it } from "vitest";

import { generatedSourcesMatch } from "./generated-comparison.mjs";

describe("generated API source comparison", () => {
  // req: NFR-013
  it("ignores line-ending-only differences", () => {
    expect(
      generatedSourcesMatch(
        Buffer.from("export type Api = {};\r\nexport type Id = string;\r"),
        Buffer.from("export type Api = {};\nexport type Id = string;\n"),
      ),
    ).toBe(true);
  });

  // req: NFR-013
  it("rejects semantic drift", () => {
    expect(
      generatedSourcesMatch(
        Buffer.from("export type Api = { id: string };\n"),
        Buffer.from("export type Api = { id: number };\n"),
      ),
    ).toBe(false);
  });

  // req: NFR-013
  it("rejects distinct non-UTF-8 bytes", () => {
    expect(
      generatedSourcesMatch(
        Buffer.from([0x80, 0x0a]),
        Buffer.from([0x81, 0x0a]),
      ),
    ).toBe(false);
  });
});
