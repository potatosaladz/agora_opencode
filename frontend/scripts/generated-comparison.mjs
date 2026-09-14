export const normalizeLineEndings = (source) =>
  source.toString("latin1").replace(/\r\n?/g, "\n");

export const generatedSourcesMatch = (generatedSource, committedSource) =>
  normalizeLineEndings(generatedSource) ===
  normalizeLineEndings(committedSource);
