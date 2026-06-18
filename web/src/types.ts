// ⚠️ This MIRRORS the backend contract in atlas/events/schema.py and
// atlas/api/viewmodels.py. If a payload changes there, change it here.
// The dev validator (see sse.ts) warns when a live event drifts from this set.

export interface IntentView {
  motivation: string;
  purpose_tag: string;
  requested_topic: string;
  declared_scope: string;
}

export interface CandidateView {
  agent_id: string;
  score: number;
  name: string;
  role: string;
  department: string;
}

export interface EventEnvelope<T = any> {
  event: string;
  id: number;
  ts: string;
  context_id?: string | null;
  data: T;
}

export interface AgentStatusPayload {
  agent_id: string;
  status: string;
  name: string;
  role: string;
  department: string;
}
export interface PromptAcceptedPayload {
  prompt: string;
  task_id: string;
  context_id: string;
  routed_to: string;
  routed_to_name: string;
}
export interface GateRejectedPayload {
  prompt: string;
  reason: string;
}
export interface DiscoveryMatchedPayload {
  level: number;
  query: string;
  candidates: CandidateView[];
  chosen?: string | null;
  requester?: string | null;
}
export interface TaskStatePayload {
  task_id: string;
  context_id: string;
  state: string;
  message?: string | null;
}
export interface ThreadCreatedPayload {
  thread_id: string;
  context_id: string;
  participants: string[];
  topic: string;
}
export interface GroupFormedPayload {
  group_id: string;
  context_id: string;
  team_id: string;
  members: string[];
  topic: string;
  initiator: string;
}
export interface MessageSentPayload {
  message_id: string;
  context_id: string;
  sender: string;
  recipients: string[];
  mode: "individual" | "group";
  role: "user" | "agent";
  text: string;
  intent?: IntentView | null;
  thread_id?: string | null;
  group_id?: string | null;
}
export interface ContextSharePayload {
  context_id: string;
  item_id: string;
  title: string;
  sender: string;
  recipient: string;
  sensitivity: string;
  rule_id: string;
  reason: string;
  summary?: string | null;
}
export interface HitlRequestedPayload {
  request_id: string;
  task_id: string;
  context_id: string;
  owner: string;
  requester: string;
  item_id: string;
  item_title: string;
  sensitivity: string;
  intent: IntentView;
  proposed_outcome: string;
  reason: string;
}
export interface HitlResolvedPayload {
  request_id: string;
  decision: string;
  outcome?: string | null;
  decided_by: string;
}
export interface MetricsUpdatedPayload {
  context_id?: string | null;
  metrics: Record<string, any>;
  derived: Record<string, number>;
  totals: Record<string, any>;
}
export interface CronTickPayload {
  elapsed: number;
  remaining: number;
  running: boolean;
  planned?: string | null;
}
export interface CronStatePayload {
  running: boolean;
  burst_seconds: number;
  mode?: "burst" | "continuous";
}
export interface LlmStatusPayload {
  provider: string;
  available: boolean;
  throttled: boolean;
  rpm: number;
  calls_ok: number;
  calls_throttled: number;
  calls_429: number;
  reason: string;
}

export const KNOWN_EVENTS = new Set<string>([
  "agent.status",
  "prompt.accepted",
  "gate.rejected",
  "discovery.matched",
  "task.state",
  "thread.created",
  "group.formed",
  "message.sent",
  "context.shared",
  "context.redacted",
  "context.denied",
  "context.reused",
  "hitl.requested",
  "hitl.resolved",
  "metrics.updated",
  "cron.tick",
  "cron.state",
  "llm.status",
]);

// ─── REST view models (atlas/api/viewmodels.py) ──────────────────────────────
export interface AgentNode {
  id: string;
  name: string;
  role: string;
  goal?: string;
  user_id?: string | null;
  department: string;
  level: number;
  clearance: number;
  reports_to?: string | null;
  manages: string[];
  teams: string[];
  projects: string[];
  security_cleared: boolean;
  status: string;
  skills: { name: string; tags: string[] }[];
  owns_sensitive: number;
  owns_total: number;
}
export interface OrgView {
  org_name: string;
  seed: number;
  node_count: number;
  nodes: AgentNode[];
  reporting_edges: { source: string; target: string }[];
  teams: Record<string, string[]>;
  projects: Record<string, string[]>;
  departments: Record<string, string[]>;
  ceo_id: string;
  llm: string;
  llm_status?: LlmStatusPayload | null;
}
export interface AgentCardView {
  card: any;
  status: string;
  goal?: string;
  user?: { user_id: string; name: string; email: string; agent_id: string; department: string; role_title: string } | null;
  owned_items: {
    item_id: string;
    title: string;
    sensitivity: string;
    scope: string;
    scope_ref?: string | null;
    min_clearance: number;
  }[];
  learned_count: number;
  manager?: string | null;
  manages: string[];
}

// ─── client-side derived shapes ──────────────────────────────────────────────
export interface ChatMessage {
  id: string;
  contextId: string;
  sender: string;
  recipients: string[];
  mode: "individual" | "group";
  role: string;
  text: string;
  intent?: IntentView | null;
  threadId?: string | null;
  groupId?: string | null;
  ts: number;
}
export interface FeedItem {
  id: number;
  kind: string;
  ts: string;
  text: string;
  tone: string;
  contextId?: string | null;
}
export interface HitlItem extends HitlRequestedPayload {}
