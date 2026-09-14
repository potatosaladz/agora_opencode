import { readFile, rm } from "node:fs/promises";

import { generatedSourcesMatch } from "./generated-comparison.mjs";

const generated = new URL("../src/api/types.check.ts", import.meta.url);
const committed = new URL("../src/api/types.ts", import.meta.url);

try {
  const [generatedSource, committedSource] = await Promise.all([
    readFile(generated),
    readFile(committed),
  ]);
  if (!generatedSourcesMatch(generatedSource, committedSource)) {
    console.error(
      "Generated API types are stale. Run `npm run generate:api` and commit the result.",
    );
    process.exitCode = 1;
  } else {
    console.log("Generated API types match contracts/openapi.yaml.");
  }
} finally {
  await rm(generated, { force: true });
}
