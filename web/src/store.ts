import { create } from "zustand";
import type {
  AgentNode,
  ChatMessage,
  ContextSharePayload,
  EventEnvelope,
  FeedItem,
  GateRejectedPayload,
  GroupFormedPayload,
  HitlItem,
  LlmStatusPayload,
  MessageSentPayload,
  OrgView,
  ThreadCreatedPayload,
} from "./types";
import { KNOWN_EVENTS } from "./types";

export interface LiveLink {
  id: string;
  source: string;
  target: string;
  intent?: string | null;
  outcome?: string | null; // shared | redacted | denied | hitl | reused
  mode: "individual" | "group";
  born: number;
}

export interface ContextMeta {
  contextId: string;
  prompt?: string;
  routedTo?: string;
  routedToName?: string;
  state?: string;
  kind: "user" | "cron";
  ts: number;
}

export type Decision = ContextSharePayload & { kind: string; ts: number };

type View = "convo" | "network" | "roster" | "projects";

interface State {
  conn: "connecting" | "live" | "down";
  org: OrgView | null;
  agents: Record<string, AgentNode>;
  status: Record<string, string>;
  links: LiveLink[];
  messagesByCtx: Record<string, ChatMessage[]>;
  decisionsByCtx: Record<string, Decision[]>;
  threads: Record<string, ThreadCreatedPayload>;
  groups: Record<string, GroupFormedPayload>;
  contexts: Record<string, ContextMeta>;
  contextOrder: string[]; // most-recent-activity first — drives the conversation timeline
  hitl: HitlItem[];
  hitlResolvedCount: number;
  metricsTotals: Record<string, any>;
  metricsByCtx: Record<string, any>;
  cron: { running: boolean; elapsed: number; remaining: number; planned?: string | null; burst: number; mode: "burst" | "continuous" };
  feed: FeedItem[];
  gate: GateRejectedPayload | null;
  llm: LlmStatusPayload | null;
  // ui
  view: View;
  deptFilter: string | null;
  selectedContext: string | null;
  selectedAgent: string | null;

  setConn: (c: State["conn"]) => void;
  setOrg: (o: OrgView) => void;
  applyEvent: (env: EventEnvelope) => void;
  pruneLinks: () => void;
  setView: (v: View) => void;
  setDeptFilter: (d: string | null) => void;
  selectContext: (c: string | null) => void;
  selectAgent: (a: string | null) => void;
  removeHitl: (id: string) => void;
}

const FEED_CAP = 220;
const CTX_CAP = 30;
const LINK_TTL = 2600;
const now = () => Date.now();

export const useStore = create<State>((set, get) => ({
  conn: "connecting",
  org: null,
  agents: {},
  status: {},
  links: [],
  messagesByCtx: {},
  decisionsByCtx: {},
  threads: {},
  groups: {},
  contexts: {},
  contextOrder: [],
  hitl: [],
  hitlResolvedCount: 0,
  metricsTotals: {},
  metricsByCtx: {},
  cron: { running: false, elapsed: 0, remaining: 0, planned: null, burst: 15, mode: "burst" },
  feed: [],
  gate: null,
  llm: null,
  view: "convo",
  deptFilter: null,
  selectedContext: null,
  selectedAgent: null,

  setConn: (c) => set({ conn: c }),
  setView: (v) => set({ view: v }),
  setDeptFilter: (d) => set({ deptFilter: d }),
  selectContext: (c) => set({ selectedContext: c }),
  selectAgent: (a) => set({ selectedAgent: a }),
  removeHitl: (id) => set((s) => ({ hitl: s.hitl.filter((h) => h.request_id !== id) })),

  setOrg: (o) => {
    const agents: Record<string, AgentNode> = {};
    const status: Record<string, string> = {};
    for (const n of o.nodes) {
      agents[n.id] = n;
      status[n.id] = n.status;
    }
    set({ org: o, agents, status, llm: o.llm_status ?? null });
  },

  pruneLinks: () => {
    const t = now();
    const links = get().links.filter((l) => t - l.born < LINK_TTL);
    if (links.length !== get().links.length) set({ links });
  },

  applyEvent: (env) => {
    const type = env.event;
    if (type === "ready" || type === "ping") return;
    if (!KNOWN_EVENTS.has(type)) {
      // eslint-disable-next-line no-console
      console.warn("[atlas] unknown SSE event (contract drift?):", type, env);
      return;
    }
    const d = env.data || {};
    const s = get();

    const pushFeed = (text: string, tone: string) => {
      const item: FeedItem = { id: env.id, kind: type, ts: env.ts, text, tone, contextId: env.context_id };
      const feed = [item, ...s.feed].slice(0, FEED_CAP);
      set({ feed });
    };

    // move a context to the front of the timeline order
    const touch = (cid?: string | null) => {
      if (!cid) return;
      const order = [cid, ...get().contextOrder.filter((x) => x !== cid)].slice(0, CTX_CAP);
      set({ contextOrder: order });
    };

    const upsertLink = (source: string, target: string, opts: Partial<LiveLink>) => {
      const id = `${source}->${target}`;
      const arr = [...get().links];
      const i = arr.findIndex((l) => l.id === id);
      const link: LiveLink = {
        id,
        source,
        target,
        mode: opts.mode || "individual",
        intent: opts.intent ?? (i >= 0 ? arr[i].intent : null),
        outcome: opts.outcome ?? (i >= 0 ? arr[i].outcome : null),
        born: now(),
      };
      if (i >= 0) arr[i] = link;
      else arr.push(link);
      set({ links: arr });
    };

    switch (type) {
      case "agent.status":
        set({ status: { ...get().status, [d.agent_id]: d.status } });
        break;

      case "prompt.accepted": {
        const isCron = String(d.context_id).startsWith("cron-");
        set({
          contexts: {
            ...get().contexts,
            [d.context_id]: {
              contextId: d.context_id,
              prompt: d.prompt,
              routedTo: d.routed_to,
              routedToName: d.routed_to_name,
              state: "working",
              kind: isCron ? "cron" : "user",
              ts: now(),
            },
          },
          gate: null,
        });
        touch(d.context_id);
        // only the operator "routes" interactive prompts; cron goals are self-initiated
        if (!isCron) upsertLink("operator", d.routed_to, { intent: "task-context", mode: "individual" });
        pushFeed(isCron ? `Goal launched · ${d.routed_to_name}` : `Prompt routed to ${d.routed_to_name}`, isCron ? "info" : "accent");
        break;
      }

      case "gate.rejected":
        set({ gate: d as GateRejectedPayload });
        pushFeed(`Gate rejected an out-of-scope prompt`, "danger");
        break;

      case "discovery.matched":
        if (d.level === 1 && d.chosen) {
          const isCron = String(env.context_id).startsWith("cron-");
          if (!isCron) upsertLink("operator", d.chosen, { intent: "task-context", mode: "individual" });
        }
        pushFeed(
          d.level === 1
            ? `Discovery → routed "${shorten(d.query)}"`
            : `Discovery → ${d.requester} sourcing "${shorten(d.query)}"`,
          "info",
        );
        break;

      case "task.state": {
        const ctx = get().contexts[d.context_id];
        set({
          contexts: {
            ...get().contexts,
            [d.context_id]: { ...(ctx || { contextId: d.context_id, kind: "cron", ts: now() }), state: d.state },
          },
        });
        if (d.state === "input-required") pushFeed(`Task awaiting approval`, "hitl");
        if (d.state === "completed") pushFeed(`Task completed`, "ok");
        break;
      }

      case "thread.created":
        set({ threads: { ...get().threads, [d.thread_id]: d as ThreadCreatedPayload } });
        break;

      case "group.formed":
        set({ groups: { ...get().groups, [d.group_id]: d as GroupFormedPayload } });
        touch(d.context_id);
        pushFeed(`Group formed · ${d.members.length} agents · ${d.topic}`, "accent");
        break;

      case "message.sent": {
        const m = d as MessageSentPayload;
        const msg: ChatMessage = {
          id: m.message_id,
          contextId: m.context_id,
          sender: m.sender,
          recipients: m.recipients,
          mode: m.mode,
          role: m.role,
          text: m.text,
          intent: m.intent,
          threadId: m.thread_id,
          groupId: m.group_id,
          ts: now(),
        };
        const list = [...(get().messagesByCtx[m.context_id] || []), msg].slice(-160);
        set({ messagesByCtx: { ...get().messagesByCtx, [m.context_id]: list } });
        touch(m.context_id);
        for (const r of m.recipients) {
          if (r === "operator") continue;
          upsertLink(m.sender, r, { intent: m.intent?.purpose_tag, mode: m.mode });
        }
        break;
      }

      case "context.shared":
      case "context.redacted":
      case "context.denied":
      case "context.reused": {
        const c = d as ContextSharePayload;
        const kind = type.split(".")[1];
        const list = [...(get().decisionsByCtx[c.context_id] || []), { ...c, kind, ts: now() }].slice(-80);
        set({ decisionsByCtx: { ...get().decisionsByCtx, [c.context_id]: list } });
        touch(c.context_id);
        const outcome = kind === "shared" ? "shared" : kind === "redacted" ? "redacted" : kind === "denied" ? "denied" : "reused";
        upsertLink(c.sender, c.recipient, { outcome });
        const tone = kind === "shared" ? "ok" : kind === "redacted" ? "warn" : kind === "denied" ? "danger" : "info";
        pushFeed(`${cap(kind)} · ${c.title}`, tone);
        break;
      }

      case "hitl.requested": {
        const h = d as HitlItem;
        set({ hitl: [h, ...get().hitl] });
        upsertLink(h.requester, h.owner, { outcome: "hitl" });
        touch(h.context_id);
        pushFeed(`Approval needed · ${h.item_title}`, "hitl");
        break;
      }

      case "hitl.resolved":
        get().removeHitl(d.request_id);
        set({ hitlResolvedCount: get().hitlResolvedCount + 1 });
        pushFeed(`Approval ${d.decision} (${d.outcome})`, d.decision === "approved" ? "ok" : "danger");
        break;

      case "metrics.updated":
        set({ metricsTotals: d.totals || get().metricsTotals });
        if (d.context_id) set({ metricsByCtx: { ...get().metricsByCtx, [d.context_id]: { ...d.metrics, derived: d.derived } } });
        break;

      case "llm.status": {
        const prev = get().llm;
        set({ llm: d as LlmStatusPayload });
        if (d.throttled && !prev?.throttled) pushFeed(`Bedrock throttled — ${d.reason || "rate limited"}`, "warn");
        break;
      }

      case "cron.tick":
        set({ cron: { ...get().cron, running: true, elapsed: d.elapsed, remaining: d.remaining, planned: d.planned } });
        break;

      case "cron.state":
        set({ cron: { ...get().cron, running: d.running, burst: d.burst_seconds || get().cron.burst, mode: d.mode ?? get().cron.mode } });
        pushFeed(d.running ? "Cron simulation started" : "Cron simulation stopped", "warn");
        break;
    }
  },
}));

function shorten(s: string, n = 28): string {
  return s && s.length > n ? s.slice(0, n) + "…" : s;
}
function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
