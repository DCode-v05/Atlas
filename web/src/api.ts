import type { AgentCardView, HistoryConversation, OrgView, ProjectSummary, ProjectView, PushConfig, UserDirEntry } from "./types";

const BASE = "/api";

// Opt-in edge auth: when ATLAS_API_KEY is set, the backend injects the key into
// the served index.html for this first-party console; we send it on every call.
export const API_KEY: string | undefined = (window as any).__ATLAS_API_KEY__;

function withAuth(opts?: RequestInit): RequestInit {
  const headers: Record<string, string> = { ...(opts?.headers as Record<string, string> | undefined) };
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  return { ...opts, headers };
}

async function j<T = any>(path: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, withAuth(opts));
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
  pushConfigs: (taskId: string) => j<{ taskId: string; configs: PushConfig[] }>(`/tasks/${taskId}/push-notification-configs`),
  pushAdd: (taskId: string, body: { url: string; token?: string }) =>
    j<{ taskId: string; pushNotificationConfig: PushConfig }>(`/tasks/${taskId}/push-notification-configs`, jsonPost(body)),
  pushDelete: (taskId: string, configId: string) =>
    j(`/tasks/${taskId}/push-notification-configs/${configId}`, { method: "DELETE" }),
  users: () => j<{ count: number; users: UserDirEntry[] }>("/users"),
  history: (limit = 30) => j<{ conversations: HistoryConversation[] }>(`/history?limit=${limit}`),
  clearHistory: () => j<{ ok: boolean; cleared: Record<string, number> }>("/history/clear", { method: "POST" }),
  network: () => j<{ count: number; members: { agent_id: string }[] }>("/network"),
  networkJoin: (id: string) => j<{ agent_id: string; token: string }>(`/network/agents/${id}/join`, { method: "POST" }),
  networkDisconnect: (id: string) => j<{ ok: boolean; agent_id: string; count: number }>(`/network/agents/${id}/disconnect`, { method: "POST" }),
  prompt: (prompt: string, opts: { human?: string; user_id?: string } = {}) =>
    j("/prompt", jsonPost({ prompt, human: opts.human ?? "Operator", ...(opts.user_id ? { user_id: opts.user_id } : {}) })),
  cron: (on: boolean) => j("/cron", jsonPost({ on })),
  approve: (id: string, outcome: "share" | "redact" = "share") =>
    j(`/hitl/${id}/approve?outcome=${outcome}`, { method: "POST" }),
  deny: (id: string) => j(`/hitl/${id}/deny`, { method: "POST" }),
  reset: () => j("/reset", { method: "POST" }),
};
