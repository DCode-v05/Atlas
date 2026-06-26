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
  void useStore.getState().loadNetwork(); // probe the authenticated network (no-op/off if DB disabled)
  void useStore.getState().loadOrgs(); // discover the federation (≥2 orgs ⇒ the Federation tab appears)
  await useStore.getState().loadHistory(); // replay persisted conversations BEFORE the live stream starts
  connectSSE();
}

boot();

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
