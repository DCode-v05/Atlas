import type { AgentCardView, CrossOrgExchangeResult, FederationItem, HistoryConversation, OrgSummary, OrgView, ProjectSummary, ProjectView, PushConfig, UserDirEntry } from "./types";

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

// The org the console is currently viewing (federation). When set, org-scoped calls carry it as
// `?org_id=` so org/teams/roster/network/projects/prompt/cron resolve to the selected sealed org.
let currentOrg: string | undefined;
export function setApiOrg(orgId: string | undefined): void {
  currentOrg = orgId;
}
function org(path: string): string {
  if (!currentOrg) return path;
  return path + (path.includes("?") ? "&" : "?") + "org_id=" + encodeURIComponent(currentOrg);
}

const jsonPost = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  // explicit orgId wins (used to fetch a SPECIFIC org, e.g. the federated comms graph); else the
  // currently-selected org is applied via org().
  org: (orgId?: string) => j<OrgView>(orgId ? `/org?org_id=${encodeURIComponent(orgId)}` : org("/org")),
  // Federation: the orgs in this deployment, a target org's items, and an operator-directed
  // cross-org request (only PUBLIC information may cross the boundary).
  orgs: () => j<{ count: number; orgs: OrgSummary[] }>("/orgs"),
  federationItems: (orgId: string) =>
    j<{ org_id: string; org_name: string; items: FederationItem[] }>(`/federation/items?org_id=${encodeURIComponent(orgId)}`),
  federationExchange: (body: { source_org_id: string; target_org_id: string; item_id: string; requester_id?: string }) =>
    j<CrossOrgExchangeResult>("/federation/exchange", jsonPost(body)),
  // Operator-directed cross-org request through the FULL pipeline (opens a Task, HITL-gated).
  federationRequest: (body: { source_org_id: string; target_org_id: string; prompt: string }) =>
    j<{ task_id: string; context_id: string; cross_org: boolean; routed_to_org_name?: string }>("/federation/request", jsonPost(body)),
  card: (id: string) => j<AgentCardView>(org(`/agents/${id}/card`)),
  // A2A discovery: the PUBLIC card (root well-known, no auth) and the AUTHENTICATED extended card.
  publicCard: (id: string) =>
    fetch(`/.well-known/agents/${id}/agent-card.json`).then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status))))),
  extendedCard: (id: string) => j<any>(org(`/agents/${id}/card/extended`)),
  metrics: () => j("/metrics"),
  hitl: () => j<{ pending: any[]; resolved_count: number }>("/hitl"),
  tasks: () => j("/tasks"),
  thread: (cid: string) => j(`/threads/${cid}`),
  projects: () => j<{ count: number; projects: ProjectSummary[] }>(org("/projects")),
  project: (id: string) => j<ProjectView>(org(`/projects/${id}`)),
  pushConfigs: (taskId: string) => j<{ taskId: string; configs: PushConfig[] }>(`/tasks/${taskId}/push-notification-configs`),
  pushAdd: (taskId: string, body: { url: string; token?: string }) =>
    j<{ taskId: string; pushNotificationConfig: PushConfig }>(`/tasks/${taskId}/push-notification-configs`, jsonPost(body)),
  pushDelete: (taskId: string, configId: string) =>
    j(`/tasks/${taskId}/push-notification-configs/${configId}`, { method: "DELETE" }),
  users: () => j<{ count: number; users: UserDirEntry[] }>(org("/users")),
  history: (limit = 30) => j<{ conversations: HistoryConversation[] }>(`/history?limit=${limit}`),
  clearHistory: () => j<{ ok: boolean; cleared: Record<string, number> }>("/history/clear", { method: "POST" }),
  // explicit orgId wins (the Network tab passes the selected org directly, bypassing the
  // module-level current-org so a tab/org switch can't fetch the wrong org's membership).
  network: (orgId?: string) =>
    j<{ count: number; members: { agent_id: string }[] }>(orgId ? `/network?org_id=${encodeURIComponent(orgId)}` : org("/network")),
  networkJoin: (id: string) => j<{ agent_id: string; token: string }>(org(`/network/agents/${id}/join`), { method: "POST" }),
  networkDisconnect: (id: string) => j<{ ok: boolean; agent_id: string; count: number }>(org(`/network/agents/${id}/disconnect`), { method: "POST" }),
  // the prompt dispatches to the SELECTED org's orchestrator (cross-org auto-fallback included).
  prompt: (prompt: string, opts: { human?: string; user_id?: string } = {}) =>
    j(org("/prompt"), jsonPost({ prompt, human: opts.human ?? "Operator", ...(opts.user_id ? { user_id: opts.user_id } : {}) })),
  cancelTask: (taskId: string) => j(`/tasks/${taskId}/cancel`, { method: "POST" }),
  cron: (on: boolean) => j(org("/cron"), jsonPost({ on })),
  approve: (id: string, outcome: "share" | "redact" = "share") =>
    j(`/hitl/${id}/approve?outcome=${outcome}`, { method: "POST" }),
  deny: (id: string) => j(`/hitl/${id}/deny`, { method: "POST" }),
  reset: () => j("/reset", { method: "POST" }),
};
