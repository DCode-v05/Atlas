import { create } from "zustand";
import type {
  AgentNode,
  ChatMessage,
  ContextSharePayload,
  CrossOrgExchangePayload,
  EventEnvelope,
  FeedItem,
  GateRejectedPayload,
  GroupFormedPayload,
  HistoryConversation,
  HitlItem,
  LlmStatusPayload,
  MessageSentPayload,
  OrgSummary,
  OrgView,
  PushDeliveredPayload,
  ThreadCreatedPayload,
  TraceSpanPayload,
} from "./types";
import { KNOWN_EVENTS } from "./types";
import { api, setApiOrg } from "./api";

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
  taskId?: string;
  prompt?: string;
  routedTo?: string;
  routedToName?: string;
  state?: string;
  kind: "user" | "cron";
  ts: number;
  pending?: boolean; // optimistic: dispatched locally, not yet routed by the backend
}

let pendingSeq = 0; // monotonic temp-id counter for optimistic conversations

export type Decision = ContextSharePayload & { kind: string; ts: number };
export type PushDelivery = PushDeliveredPayload & { ts: number };

export interface NetworkState {
  enabled: boolean; // DB-backed authenticated network is on (the /api/network probe succeeded)
  loaded: boolean; // the initial probe has completed
  online: Record<string, true>; // agent_ids currently joined to the network
  busy: Record<string, true>; // a join/disconnect is in flight for this agent
}

type View = "convo" | "history" | "members" | "comms" | "roster" | "projects" | "federation";

export type CrossOrgExchange = CrossOrgExchangePayload & { id: number; ts: number };

interface State {
  conn: "connecting" | "live" | "down";
  org: OrgView | null;
  agents: Record<string, AgentNode>;
  status: Record<string, string>;
  links: LiveLink[];
  messagesByCtx: Record<string, ChatMessage[]>;
  decisionsByCtx: Record<string, Decision[]>;
  tracesByCtx: Record<string, TraceSpanPayload[]>;
  pushByCtx: Record<string, PushDelivery[]>;
  threads: Record<string, ThreadCreatedPayload>;
  groups: Record<string, GroupFormedPayload>;
  contexts: Record<string, ContextMeta>;
  contextOrder: string[]; // most-recent-activity first — drives the conversation timeline
  archived: Record<string, true>; // moved to History-only (hidden from the live timeline)
  hitl: HitlItem[];
  hitlResolvedCount: number;
  metricsTotals: Record<string, any>;
  metricsByCtx: Record<string, any>;
  cron: { running: boolean; elapsed: number; remaining: number; planned?: string | null; burst: number; mode: "burst" | "continuous" };
  feed: FeedItem[];
  gate: GateRejectedPayload | null;
  llm: LlmStatusPayload | null;
  network: NetworkState;
  // federation (multi-org)
  orgs: OrgSummary[];
  selectedOrg: string | null; // which org's structure the teams/roster/network/projects show
  orgViews: Record<string, OrgView>; // every org's structure, for the all-orgs Comms graph
  exchanges: CrossOrgExchange[]; // live cross-org boundary crossings (newest first)
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
  dismissGate: () => void;
  dispatch: (prompt: string) => Promise<void>;
  pendingPrompt: (prompt: string) => string;
  cancelPending: (tempId: string) => void;
  loadHistory: () => Promise<void>;
  seedHistory: (conversations: HistoryConversation[]) => void;
  clearHistory: () => Promise<void>;
  loadNetwork: (orgId?: string) => Promise<void>;
  joinAgent: (id: string) => Promise<void>;
  disconnectAgent: (id: string) => Promise<void>;
  joinAll: (ids: string[]) => Promise<void>;
  disconnectAll: () => Promise<void>;
  loadOrgs: () => Promise<void>;
  selectOrg: (orgId: string) => Promise<void>;
  loadAllOrgViews: () => Promise<void>;
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
  tracesByCtx: {},
  pushByCtx: {},
  threads: {},
  groups: {},
  contexts: {},
  contextOrder: [],
  archived: {},
  hitl: [],
  hitlResolvedCount: 0,
  metricsTotals: {},
  metricsByCtx: {},
  cron: { running: false, elapsed: 0, remaining: 0, planned: null, burst: 15, mode: "burst" },
  feed: [],
  gate: null,
  llm: null,
  network: { enabled: false, loaded: false, online: {}, busy: {} },
  orgs: [],
  selectedOrg: null,
  orgViews: {},
  exchanges: [],
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
  dismissGate: () => set({ gate: null }),

  // Optimistic dispatch: show the conversation the instant the operator hits send — the prompt as
  // a right-aligned "You" bubble + a routing… header — before the (slow) backend route returns.
  // The real context_id arrives via the `prompt.accepted` SSE event, which reconciles this temp one.
  pendingPrompt: (prompt) => {
    const s = get();
    const tempId = `pending-${++pendingSeq}-${now()}`;
    // a fresh dispatch retires any finished conversation to History-only (keeps the deck clean)
    const archived = { ...s.archived };
    for (const cid of s.contextOrder) {
      const st = s.contexts[cid]?.state;
      if (st === "completed" || st === "failed") archived[cid] = true;
    }
    const ctx: ContextMeta = { contextId: tempId, prompt, state: "routing", kind: "user", ts: now(), pending: true };
    const opMsg: ChatMessage = {
      id: `op-${tempId}`, contextId: tempId, sender: "operator", recipients: [], mode: "individual",
      role: "user", text: prompt, ts: now(),
    };
    set({
      archived,
      contexts: { ...s.contexts, [tempId]: ctx },
      messagesByCtx: { ...s.messagesByCtx, [tempId]: [opMsg] },
      contextOrder: [tempId, ...s.contextOrder].slice(0, CTX_CAP),
      gate: null,
    });
    return tempId;
  },
  cancelPending: (tempId) => {
    const s = get();
    const contexts = { ...s.contexts };
    delete contexts[tempId];
    const messagesByCtx = { ...s.messagesByCtx };
    delete messagesByCtx[tempId];
    set({ contexts, messagesByCtx, contextOrder: s.contextOrder.filter((x) => x !== tempId) });
  },
  dispatch: async (prompt) => {
    const p = prompt.trim();
    if (!p) return;
    const tempId = get().pendingPrompt(p); // render the conversation instantly
    try {
      const res = (await api.prompt(p)) as { rejected?: boolean } | undefined;
      if (res?.rejected) get().cancelPending(tempId); // out-of-scope → drop the optimistic card; gate banner shows
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error("[atlas] dispatch failed", e);
      get().cancelPending(tempId);
    }
  },

  loadHistory: async () => {
    try {
      const data = await api.history();
      get().seedHistory(data.conversations || []);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error("[atlas] history load failed", e);
    }
  },

  // Rebuild the timeline + history from the persisted record (merge-safe: never clobbers
  // anything the live stream already produced; dedups by id; ts already in ms from the API).
  seedHistory: (conversations) => {
    const s = get();
    const contexts = { ...s.contexts };
    const messagesByCtx = { ...s.messagesByCtx };
    const decisionsByCtx = { ...s.decisionsByCtx };
    const archived = { ...s.archived };
    let order = [...s.contextOrder];
    for (const c of conversations) {
      const cid = c.context_id;
      // a replayed conversation is history — keep it out of the live deck (still shows in History)
      if (c.state === "completed" || c.state === "failed") archived[cid] = true;
      if (!contexts[cid]) {
        contexts[cid] = {
          contextId: cid, taskId: c.task_id ?? undefined, prompt: c.prompt,
          routedTo: c.routed_to, routedToName: c.routed_to_name, state: c.state, kind: c.kind, ts: c.ts,
        };
      }
      const existing = messagesByCtx[cid] || [];
      const seen = new Set(existing.map((m) => m.id));
      const seeded: ChatMessage[] = (c.messages || [])
        .filter((m) => !seen.has(m.message_id))
        .map((m) => ({
          id: m.message_id, contextId: cid, sender: m.sender, recipients: m.recipients, mode: m.mode,
          role: m.role, text: m.text, thinking: m.thinking ?? undefined,
          intent: (m.intent ?? undefined) as ChatMessage["intent"],
          threadId: m.thread_id ?? undefined, groupId: m.group_id ?? undefined, ts: m.ts,
        }));
      messagesByCtx[cid] = [...seeded, ...existing].sort((a, b) => a.ts - b.ts).slice(-160);

      const exD = decisionsByCtx[cid] || [];
      const keyOf = (d: any) => `${d.item_id}:${d.kind}:${d.sender}:${d.recipient}`;
      const seenD = new Set(exD.map(keyOf));
      const seededD = (c.decisions || []).filter((d) => !seenD.has(keyOf(d))) as unknown as Decision[];
      decisionsByCtx[cid] = [...seededD, ...exD].sort((a, b) => a.ts - b.ts).slice(-80);

      if (!order.includes(cid)) order.push(cid);
    }
    order = order.sort((a, b) => (contexts[b]?.ts || 0) - (contexts[a]?.ts || 0)).slice(0, CTX_CAP);
    set({ contexts, messagesByCtx, decisionsByCtx, archived, contextOrder: order });
  },

  clearHistory: async () => {
    try {
      await api.clearHistory();
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error("[atlas] clear history failed", e);
    }
    // wipe the conversation/history view (org, network membership + lifetime metrics stay)
    set({
      contexts: {}, contextOrder: [], archived: {}, messagesByCtx: {}, decisionsByCtx: {}, tracesByCtx: {},
      pushByCtx: {}, threads: {}, groups: {}, hitl: [], metricsByCtx: {}, feed: [],
      gate: null, selectedContext: null,
    });
  },

  // orgId (when given) is fetched explicitly so the result is always for the org in view — never
  // the previously-selected one. The online map is REPLACED with this org's members (so a peer
  // org's membership can never linger).
  loadNetwork: async (orgId?: string) => {
    try {
      const r = await api.network(orgId);
      const online: Record<string, true> = {};
      for (const m of r.members) online[m.agent_id] = true;
      set((s) => ({ network: { ...s.network, enabled: true, loaded: true, online, busy: {} } }));
    } catch {
      // 503 ⇒ no DB / network auth off; the panel shows an informative "off" state
      set((s) => ({ network: { ...s.network, enabled: false, loaded: true, online: {}, busy: {} } }));
    }
  },
  joinAgent: async (id) => {
    set((s) => ({ network: { ...s.network, busy: { ...s.network.busy, [id]: true } } }));
    try {
      await api.networkJoin(id);
      set((s) => ({ network: { ...s.network, online: { ...s.network.online, [id]: true } } }));
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error("[atlas] join failed", id, e);
    } finally {
      set((s) => { const busy = { ...s.network.busy }; delete busy[id]; return { network: { ...s.network, busy } }; });
    }
  },
  disconnectAgent: async (id) => {
    set((s) => ({ network: { ...s.network, busy: { ...s.network.busy, [id]: true } } }));
    try {
      await api.networkDisconnect(id);
      set((s) => { const online = { ...s.network.online }; delete online[id]; return { network: { ...s.network, online } }; });
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error("[atlas] disconnect failed", id, e);
    } finally {
      set((s) => { const busy = { ...s.network.busy }; delete busy[id]; return { network: { ...s.network, busy } }; });
    }
  },
  joinAll: async (ids) => { await runBatched(ids, (id) => get().joinAgent(id)); },
  disconnectAll: async () => { await runBatched(Object.keys(get().network.online), (id) => get().disconnectAgent(id)); },

  // Federation: discover the orgs in this deployment, and switch which org the console shows.
  loadOrgs: async () => {
    try {
      const r = await api.orgs();
      const primary = r.orgs.find((o) => o.primary) || r.orgs[0];
      const sel = get().selectedOrg ?? (primary ? primary.org_id : null);
      if (r.orgs.length > 1 && sel) setApiOrg(sel); // scope org-aware API calls to the selection
      set({ orgs: r.orgs, selectedOrg: sel });
      if (r.orgs.length > 1) void get().loadAllOrgViews(); // for the all-orgs Comms graph
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error("[atlas] orgs load failed", e);
    }
  },
  selectOrg: async (orgId) => {
    if (get().selectedOrg === orgId && get().org) return;
    setApiOrg(orgId); // BEFORE fetching: teams/roster/network/projects/prompt now scope to this org
    // clear the previous org's membership immediately so its online/Join-all state can't linger
    set((s) => ({ selectedOrg: orgId, selectedAgent: null, network: { ...s.network, online: {}, busy: {} } }));
    try {
      const o = await api.org(orgId); // the sealed org's own structure (disjoint agent ids)
      get().setOrg(o);
      void get().loadNetwork(orgId); // refresh membership for the newly-selected org (explicit)
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error("[atlas] selectOrg failed", orgId, e);
    }
  },
  // Every org's structure (immutable per seed) — the all-orgs hierarchical Comms graph draws these.
  loadAllOrgViews: async () => {
    const ids = get().orgs.map((o) => o.org_id);
    const views: Record<string, OrgView> = { ...get().orgViews };
    await Promise.all(
      ids.map(async (id) => {
        if (views[id]) return;
        try {
          views[id] = await api.org(id); // explicit id ⇒ that specific org, regardless of selection
        } catch (e) {
          // eslint-disable-next-line no-console
          console.error("[atlas] org view load failed", id, e);
        }
      }),
    );
    set({ orgViews: views });
  },

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
        const s2 = get();
        const contexts = { ...s2.contexts };
        const messagesByCtx = { ...s2.messagesByCtx };
        let order = [...s2.contextOrder];
        // reconcile the optimistic pending conversation (same prompt) → the real context_id,
        // carrying its operator "You" bubble across so the dispatch doesn't flicker.
        const pendingId = Object.keys(contexts).find((id) => contexts[id].pending && contexts[id].prompt === d.prompt);
        if (pendingId && pendingId !== d.context_id) {
          const opMsgs = (messagesByCtx[pendingId] || []).map((m) => ({ ...m, contextId: d.context_id, recipients: [d.routed_to] }));
          delete messagesByCtx[pendingId];
          messagesByCtx[d.context_id] = [...opMsgs, ...(messagesByCtx[d.context_id] || [])];
          delete contexts[pendingId];
          order = order.filter((x) => x !== pendingId);
        }
        contexts[d.context_id] = {
          contextId: d.context_id, taskId: d.task_id, prompt: d.prompt, routedTo: d.routed_to,
          routedToName: d.routed_to_name, state: "working", kind: isCron ? "cron" : "user", ts: now(), pending: false,
        };
        order = [d.context_id, ...order.filter((x) => x !== d.context_id)].slice(0, CTX_CAP);
        set({ contexts, messagesByCtx, contextOrder: order, gate: null });
        // only the operator "routes" interactive prompts; cron goals are self-initiated
        if (!isCron) upsertLink("operator", d.routed_to, { intent: "task-context", mode: "individual" });
        pushFeed(isCron ? `Goal launched · ${d.routed_to_name}` : `Prompt routed to ${d.routed_to_name}`, isCron ? "info" : "accent");
        break;
      }

      case "gate.rejected": {
        const gp = d as GateRejectedPayload;
        const st = get();
        // drop the optimistic card for this rejected prompt (so it doesn't linger till the HTTP reply)
        const pid = Object.keys(st.contexts).find((id) => st.contexts[id].pending && st.contexts[id].prompt === gp.prompt);
        if (pid) {
          const contexts = { ...st.contexts };
          delete contexts[pid];
          const messagesByCtx = { ...st.messagesByCtx };
          delete messagesByCtx[pid];
          set({ gate: gp, contexts, messagesByCtx, contextOrder: st.contextOrder.filter((x) => x !== pid) });
        } else {
          set({ gate: gp });
        }
        pushFeed(`Gate rejected an out-of-scope prompt`, "danger");
        break;
      }

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
            [d.context_id]: { ...(ctx || { contextId: d.context_id, kind: "cron", ts: now(), taskId: d.task_id }), state: d.state },
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
        if ((get().messagesByCtx[m.context_id] || []).some((x) => x.id === m.message_id)) break; // dedup vs seeded
        const msg: ChatMessage = {
          id: m.message_id,
          contextId: m.context_id,
          sender: m.sender,
          recipients: m.recipients,
          mode: m.mode,
          role: m.role,
          text: m.text,
          thinking: m.thinking,
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
        if (d.errored && !prev?.errored) pushFeed(`LLM error — running on templates · ${d.reason || ""}`, "danger");
        else if (d.throttled && !prev?.throttled) pushFeed(`Bedrock throttled — ${d.reason || "rate limited"}`, "warn");
        break;
      }

      case "trace.span": {
        const sp = d as TraceSpanPayload;
        if (sp.context_id) {
          const list = [...(get().tracesByCtx[sp.context_id] || []), sp].slice(-240);
          set({ tracesByCtx: { ...get().tracesByCtx, [sp.context_id]: list } });
        }
        break;
      }

      case "push.delivered": {
        const p = d as PushDeliveredPayload;
        if (p.context_id) {
          const list = [...(get().pushByCtx[p.context_id] || []), { ...p, ts: now() }].slice(-50);
          set({ pushByCtx: { ...get().pushByCtx, [p.context_id]: list } });
        }
        if (!p.ok || p.final) pushFeed(`Webhook ${p.ok ? "delivered" : "failed"} · ${p.state}`, p.ok ? "ok" : "danger");
        break;
      }

      case "network.joined": {
        const net = get().network;
        // apply only to the org currently in view (events are org-tagged; the broker is shared,
        // so a peer org's joins must not show up in this org's membership)
        const forThisOrg = !env.org_id || !get().selectedOrg || env.org_id === get().selectedOrg;
        if (forThisOrg) set({ network: { ...net, enabled: true, online: { ...net.online, [d.agent_id]: true } } });
        pushFeed(`${d.name} joined the network`, "ok");
        break;
      }

      case "network.left": {
        const net = get().network;
        const forThisOrg = !env.org_id || !get().selectedOrg || env.org_id === get().selectedOrg;
        if (forThisOrg) {
          const online = { ...net.online };
          delete online[d.agent_id];
          set({ network: { ...net, online } });
        }
        pushFeed(`${d.name} left the network`, "warn");
        break;
      }

      case "federation.exchange": {
        const x = d as CrossOrgExchangePayload;
        const ex: CrossOrgExchange = { ...x, id: env.id, ts: now() };
        set({ exchanges: [ex, ...get().exchanges].slice(0, 60) });
        pushFeed(
          x.crossed
            ? `Cross-org · ${x.target_org_name} → ${x.source_org_name}: "${x.item_title}" (public)`
            : `Cross-org blocked · ${x.target_org_name} withheld "${x.item_title}" from ${x.source_org_name}`,
          x.crossed ? "ok" : "danger",
        );
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

// run an async op over many ids with bounded concurrency (don't fire 100 POSTs at once)
async function runBatched<T>(ids: T[], op: (id: T) => Promise<void>, size = 12): Promise<void> {
  for (let i = 0; i < ids.length; i += size) {
    await Promise.all(ids.slice(i, i + size).map(op));
  }
}

function shorten(s: string, n = 28): string {
  return s && s.length > n ? s.slice(0, n) + "…" : s;
}
function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
