import React from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { App } from "./App";
import { api } from "./api";
import { connectSSE } from "./sse";
import { useStore } from "./store";

async function boot() {
  try {
    const org = await api.org();
    useStore.getState().setOrg(org);
  } catch (e) {
    // eslint-disable-next-line no-console
    console.error("[atlas] failed to load org", e);
  }
  connectSSE();
}

boot();

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
