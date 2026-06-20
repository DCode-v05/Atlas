import type { A2AMethodInfo, AgentCardView, OrgView, ProjectSummary, ProjectView } from "./types";

const BASE = "/api";

async function j<T = any>(path: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, opts);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

const jsonPost = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  org: () => j<OrgView>("/org"),
  card: (id: string) => j<AgentCardView>(`/agents/${id}/card`),
  metrics: () => j("/metrics"),
  hitl: () => j<{ pending: any[]; resolved_count: number }>("/hitl"),
  tasks: () => j("/tasks"),
  thread: (cid: string) => j(`/threads/${cid}`),
  projects: () => j<{ count: number; projects: ProjectSummary[] }>("/projects"),
  project: (id: string) => j<ProjectView>(`/projects/${id}`),
  a2aMethods: () => j<{ methods: A2AMethodInfo[] }>("/a2a/methods"),
  prompt: (prompt: string, human = "Operator") => j("/prompt", jsonPost({ prompt, human })),
  cron: (on: boolean) => j("/cron", jsonPost({ on })),
  approve: (id: string, outcome: "share" | "redact" = "share") =>
    j(`/hitl/${id}/approve?outcome=${outcome}`, { method: "POST" }),
  deny: (id: string) => j(`/hitl/${id}/deny`, { method: "POST" }),
  reset: () => j("/reset", { method: "POST" }),
};
