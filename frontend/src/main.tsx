import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@fontsource/dm-mono/300.css";
import "@fontsource/dm-mono/400.css";
import "@fontsource/dm-mono/500.css";
import "@fontsource/newsreader/300.css";
import "@fontsource/newsreader/500.css";
import "@fontsource/newsreader/700.css";

import { App } from "./app/app";
import { queryClient } from "./app/query-client";
import "./styles.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("Agora root element is missing");
}

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
