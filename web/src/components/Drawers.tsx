import { useEffect, useMemo, useState } from "react";
import { Activity, Brain, Lock, Sparkles, Users, X, Zap } from "lucide-react";
import { api } from "../api";
import type { AgentCardView, ChatMessage, PushConfig, TraceSpanPayload } from "../types";
import { LEVEL_LABEL, TRACE_KIND_META, deptColor } from "../theme";
import { useStore } from "../store";
import { IntentChip, ModeTag, OutcomeBadge, SensitivityShield, StatusDot } from "./ui";

function Drawer({ title, idx, onClose, children, accent, width = 452 }: { title: string; idx?: string; onClose: () => void; children: React.ReactNode; accent?: string; width?: number }) {
  return (
    <div className="fixed inset-0 z-30 flex justify-end" style={{ background: "rgba(24,28,34,0.38)", backdropFilter: "blur(2px)" }} onClick={onClose}>
      <div
        className="h-full panel flex flex-col animate-slide-in"
        style={{ width, maxWidth: "94vw", borderRadius: 0, borderLeft: `1px solid ${accent ?? "var(--border-bright)"}`, boxShadow: "-30px 0 60px -30px rgba(0,0,0,0.9)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 h-12 border-b shrink-0" style={{ borderColor: "var(--border)" }}>
          <span className="flex items-center gap-1.5">
            {idx && <span className="idx" style={accent ? { color: accent } : undefined}>{idx}</span>}
            <span className="eyebrow" style={{ color: accent ?? "var(--accent)" }}>{title}</span>
          </span>
          <button onClick={onClose} className="text-faint hover:text-ink"><X size={16} /></button>
        </div>
        <div className="flex-1 overflow-y-auto min-h-0">{children}</div>
      </div>
    </div>
  );
}

function Tabs({ tabs, tab, set }: { tabs: { id: string; label: string; n?: number }[]; tab: string; set: (t: string) => void }) {
  return (
    <div className="flex items-center gap-1 px-3 h-10 border-b shrink-0 sticky top-0 z-10" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
      {tabs.map((t) => {
        const active = tab === t.id;
        return (
          <button key={t.id} onClick={() => set(t.id)} className="flex items-center gap-1 px-2.5 h-7 rounded-md text-[11px] font-semibold transition-all"
            style={{ background: active ? "var(--accent)" : "transparent", color: active ? "#fff" : "var(--muted)" }}>
            {t.label}{t.n != null && <span className="mono text-[9px] opacity-80">{t.n}</span>}
          </button>
        );
      })}
    </div>
  );
}

function SpanRow({ s, nameOf }: { s: TraceSpanPayload; nameOf: (id: string) => string }) {
  const meta = TRACE_KIND_META[s.kind] ?? { color: "var(--muted)", label: s.kind };
  return (
    <div className="flex items-start gap-2 px-2.5 py-1.5 rounded-md" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
      <span className="mono text-[8px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded shrink-0 mt-0.5" style={{ color: meta.color, background: `${meta.color}16` }}>{meta.label}</span>
      <div className="min-w-0 flex-1">
        <div className="text-[11px] leading-snug" style={{ color: s.kind === "think" ? "var(--violet)" : "var(--text-2)", fontStyle: s.kind === "think" ? "italic" : "normal" }}>{s.summary}</div>
        {s.detail && <div className="text-[9.5px] text-faint leading-snug mt-0.5">{s.detail}</div>}
        <div className="mono text-[8px] text-faint mt-0.5">{nameOf(s.agent_id)}</div>
      </div>
      <span className="mono text-[8px] uppercase tracking-wide shrink-0 mt-0.5" style={{ color: s.live ? "var(--ok)" : "var(--faint)" }} title={s.live ? "real Mistral call" : "deterministic / fallback (no LLM)"}>
        {s.live ? "● live" : "○ det"}
      </span>
    </div>
  );
}

// ─── per-conversation detail ──────────────────────────────────────────────────
export function ConversationDrawer() {
  const cid = useStore((s) => s.selectedContext);
  const ctx = useStore((s) => (cid ? s.contexts[cid] : null));
  const messages = useStore((s) => (cid ? s.messagesByCtx[cid] : null)) ?? [];
  const decisions = useStore((s) => (cid ? s.decisionsByCtx[cid] : null)) ?? [];
  const spans = useStore((s) => (cid ? s.tracesByCtx[cid] : null)) ?? [];
  const agents = useStore((s) => s.agents);
  const [tab, setTab] = useState("thread");
  const close = () => useStore.getState().selectContext(null);
  if (!cid) return null;
  const nameOf = (id: string) => (id === "operator" ? "Operator (you)" : agents[id]?.name ?? id);
  const isGroup = messages.some((m) => m.mode === "group");
  const stateColor = ctx?.state === "completed" ? "var(--ok)" : ctx?.state === "input-required" ? "var(--violet)" : ctx?.state === "failed" ? "var(--coral)" : "var(--gold)";

  return (
    <Drawer title="Conversation" idx="◆" onClose={close} width={540}>
      <div className="p-3.5 border-b" style={{ borderColor: "var(--border)", background: "var(--surface-2)" }}>
        <div className="text-[13px] font-semibold text-ink mb-1.5 leading-snug">{ctx?.prompt ? `“${ctx.prompt}”` : "Autonomous task"}</div>
        <div className="flex items-center gap-2 flex-wrap">
          {ctx?.routedTo && (
            <span className="inline-flex items-center gap-1 text-[10.5px] text-ink">
              <span className="w-2 h-2 rounded-[2px]" style={{ background: deptColor(agents[ctx.routedTo]?.department ?? "") }} />{ctx.routedToName}
            </span>
          )}
          <span className="mono text-[9px] px-1.5 py-0.5 rounded" style={{ color: isGroup ? "var(--violet)" : "var(--accent)", background: isGroup ? "rgba(109,40,217,0.08)" : "var(--accent-soft)" }}>{isGroup ? "GROUP" : "1:1"}</span>
          {ctx?.state && <span className="mono text-[9px] uppercase tracking-wide" style={{ color: stateColor }}>● {ctx.state}</span>}
          <span className="mono text-[9px] text-faint">· {messages.length} msgs · {spans.length} ops</span>
        </div>
      </div>

      <Tabs tab={tab} set={setTab} tabs={[{ id: "thread", label: "Thread", n: messages.length }, { id: "trace", label: "Trace", n: spans.length }, { id: "push", label: "Push" }]} />

      {tab === "thread" && (
        <>
          <div className="p-3.5 flex flex-col gap-2">
            {messages.map((m) => <DrawerMsg key={m.id} m={m} agents={agents} nameOf={nameOf} />)}
            {messages.length === 0 && <div className="text-[11px] text-faint text-center py-5">No messages yet…</div>}
          </div>
          {decisions.length > 0 && (
            <div className="p-3.5 border-t" style={{ borderColor: "var(--border)" }}>
              <div className="eyebrow mb-2">Need-to-know decisions</div>
              <div className="flex flex-col gap-2">
                {decisions.map((d, i) => (
                  <div key={i} className="flex items-start gap-2 text-[11px]">
                    <OutcomeBadge kind={d.kind === "shared" ? "shared" : d.kind === "redacted" ? "redacted" : d.kind === "denied" ? "denied" : "reused"} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5"><span className="text-ink truncate">{d.title}</span><SensitivityShield level={d.sensitivity} /></div>
                      <div className="text-[10px] text-faint leading-snug">{d.reason}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {tab === "trace" && (
        <div className="p-3.5">
          <div className="flex items-center gap-1.5 mb-2 text-[10px] text-muted">
            <Activity size={12} style={{ color: "var(--accent)" }} />
            <span>Every operation in this goal — <span style={{ color: "var(--ok)" }}>● live</span> = real Mistral call, <span className="text-faint">○ det</span> = deterministic policy/fallback.</span>
          </div>
          <div className="flex flex-col gap-1.5">
            {spans.map((s) => <SpanRow key={s.span_id} s={s} nameOf={nameOf} />)}
            {spans.length === 0 && <div className="text-[11px] text-faint text-center py-5">No trace captured.</div>}
          </div>
        </div>
      )}

      {tab === "push" && <PushTab taskId={ctx?.taskId} contextId={cid} />}
    </Drawer>
  );
}

function PushTab({ taskId, contextId }: { taskId?: string; contextId: string | null }) {
  const [configs, setConfigs] = useState<PushConfig[]>([]);
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const deliveries = useStore((s) => (contextId ? s.pushByCtx[contextId] : null)) ?? [];

  const load = () => {
    if (taskId) api.pushConfigs(taskId).then((r) => setConfigs(r.configs)).catch(console.error);
  };
  useEffect(load, [taskId]);

  if (!taskId) return <div className="p-3.5 text-[11px] text-faint">No task yet for this conversation.</div>;

  const add = async () => {
    const u = url.trim();
    if (!u) return;
    setBusy(true);
    try {
      await api.pushAdd(taskId, { url: u, token: token.trim() || undefined });
      setUrl("");
      setToken("");
      load();
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(false);
    }
  };
  const del = async (id: string) => {
    try {
      await api.pushDelete(taskId, id);
      load();
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="p-3.5 flex flex-col gap-3">
      <div className="text-[10px] text-faint leading-snug">
        Register a webhook for this task — Atlas POSTs a status update to it on every task-state change (A2A push
        notifications). Tip: paste a <span className="mono">https://webhook.site</span> URL to watch deliveries land.
      </div>
      <div className="inset rounded-md p-2 flex flex-col gap-1.5">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
          placeholder="https://webhook.site/…"
          className="bg-transparent outline-none text-ink text-[12px]"
        />
        <div className="flex items-center gap-1.5">
          <input
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="validation token (optional)"
            className="bg-transparent outline-none text-muted text-[11px] flex-1 min-w-0"
          />
          <button
            onClick={add}
            disabled={busy || !url.trim()}
            className="text-[10px] font-bold tracking-wide px-2.5 py-1 rounded shrink-0 text-white disabled:opacity-40"
            style={{ background: "var(--accent)" }}
          >
            REGISTER
          </button>
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="eyebrow">Registered webhooks ({configs.length})</div>
        {configs.map((c) => (
          <div key={c.id} className="flex items-center justify-between gap-2 inset rounded-md px-2 py-1.5">
            <div className="min-w-0">
              <div className="text-[11px] text-ink truncate">{c.url}</div>
              <div className="mono text-[8.5px] text-faint">{c.id}{c.token ? " · token set" : ""}</div>
            </div>
            <button onClick={() => del(c.id)} title="Delete" className="text-faint hover:text-ink shrink-0"><X size={13} /></button>
          </div>
        ))}
        {configs.length === 0 && <div className="text-[11px] text-faint text-center py-3">No webhooks registered yet.</div>}
      </div>
      {deliveries.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="eyebrow">Deliveries ({deliveries.length})</div>
          {[...deliveries].reverse().map((dlv, i) => (
            <div key={i} className="flex items-center justify-between gap-2 text-[10.5px]">
              <span className="flex items-center gap-1.5 min-w-0">
                <span className="mono text-[8px] uppercase px-1 py-0.5 rounded shrink-0" style={{ color: dlv.ok ? "var(--ok)" : "var(--coral)", background: dlv.ok ? "rgba(31,143,90,0.10)" : "rgba(209,42,58,0.10)" }}>{dlv.ok ? "sent" : "fail"}</span>
                <span className="text-ink truncate">{dlv.state}{dlv.final ? " · final" : ""}</span>
              </span>
              <span className="mono text-[8.5px] text-faint shrink-0">{dlv.status_code ?? "—"}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DrawerMsg({ m, agents, nameOf }: { m: ChatMessage; agents: any; nameOf: (id: string) => string }) {
  const group = m.mode === "group";
  const c = deptColor(agents[m.sender]?.department ?? "");
  return (
    <div className="rounded-md p-2.5" style={{ background: group ? "rgba(109,40,217,0.05)" : "var(--surface-2)", border: `1px solid ${group ? "rgba(109,40,217,0.24)" : "var(--border)"}` }}>
      <div className="flex items-center justify-between gap-2 mb-1">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="w-2 h-2 shrink-0 rounded-[2px]" style={{ background: c }} />
          <span className="text-[11px] font-semibold text-ink truncate">{nameOf(m.sender)}</span>
          <span className="text-faint text-[10px]">→</span>
          <span className="text-[10px] text-muted truncate">{group ? `group · ${m.recipients.length}` : m.recipients.map(nameOf).join(", ")}</span>
        </div>
        <ModeTag mode={m.mode} />
      </div>
      {m.thinking && (
        <div className="flex items-start gap-1 mb-1.5 text-[10.5px] italic leading-snug px-2 py-1 rounded" style={{ color: "var(--violet)", background: "rgba(109,40,217,0.05)" }}>
          <Brain size={11} className="shrink-0 mt-0.5" />
          <span>{m.thinking}</span>
        </div>
      )}
      <div className="text-[11.5px] text-ink2 leading-snug">{m.text}</div>
      {m.intent && (
        <div className="mt-1.5 flex items-center gap-1.5">
          <IntentChip tag={m.intent.purpose_tag} />
          <span className="text-[9.5px] text-faint mono">scope: {m.intent.declared_scope}</span>
        </div>
      )}
    </div>
  );
}

// ─── agent inspection ─────────────────────────────────────────────────────────
export function AgentCardDrawer() {
  const id = useStore((s) => s.selectedAgent);
  const liveStatus = useStore((s) => (id ? s.status[id] : undefined));
  const agents = useStore((s) => s.agents);
  const [card, setCard] = useState<AgentCardView | null>(null);
  const [tab, setTab] = useState("overview");
  const close = () => useStore.getState().selectAgent(null);

  useEffect(() => {
    setCard(null);
    setTab("overview");
    if (id) api.card(id).then(setCard).catch(console.error);
  }, [id]);

  // refresh the trace/learned periodically while open (they grow as the agent acts)
  useEffect(() => {
    if (!id) return;
    const t = setInterval(() => api.card(id).then(setCard).catch(() => {}), 4000);
    return () => clearInterval(t);
  }, [id]);

  const nameOf = (x?: string | null) => (x ? agents[x]?.name ?? x : "—");
  const thoughts = useMemo(() => (card?.trace ?? []).filter((s) => s.kind === "think"), [card]);

  if (!id) return null;
  const node = agents[id];
  const color = deptColor(node?.department ?? "");

  return (
    <Drawer title="Agent" idx="◆" onClose={close} accent={color} width={500}>
      <div className="h-1" style={{ background: `linear-gradient(90deg, ${color}, transparent)` }} />
      <div className="px-4 pt-3 pb-2">
        <div className="flex items-start justify-between">
          <div>
            <div className="font-display text-[18px] font-bold text-ink leading-tight">{node?.name ?? id}</div>
            <div className="text-[12px] text-muted">{node?.role}</div>
          </div>
          <StatusDot status={liveStatus ?? node?.status ?? "idle"} size={10} />
        </div>
        <div className="flex flex-wrap gap-1.5 mt-2.5">
          <Tag color={color}>{node?.department}</Tag>
          <Tag>{LEVEL_LABEL[node?.level ?? 1]}</Tag>
          <Tag>clearance L{node?.clearance}</Tag>
          {node?.security_cleared && <Tag color="var(--coral)">security-cleared</Tag>}
          <span className="mono text-[9px] text-faint self-center">{id}</span>
        </div>
      </div>

      <Tabs tab={tab} set={setTab} tabs={[
        { id: "overview", label: "Overview" },
        { id: "thinking", label: "Thinking", n: thoughts.length },
        { id: "learned", label: "Learned", n: card?.learned?.length ?? card?.learned_count ?? 0 },
        { id: "trace", label: "Trace", n: card?.trace?.length ?? 0 },
      ]} />

      <div className="p-4">
        {tab === "overview" && (
          <>
            <A2ACardPanel id={id} />

            {(card?.goal ?? node?.goal) && (
              <Section label="Goal · responsibility"><div className="text-[12px] text-ink leading-snug">{card?.goal ?? node?.goal}</div></Section>
            )}
            <Section label="Reporting line">
              <Row k="Operated by" v={card?.user ? `${card.user.name}` : nameOf(id)} />
              <Row k="Reports to" v={nameOf(node?.reports_to)} />
              <Row k="Manages" v={node?.manages.length ? `${node.manages.length} report(s)` : "—"} />
              <Row k="Teams" v={node?.teams.join(", ") || "—"} />
              <Row k="Projects" v={node?.projects.join(", ") || "—"} />
            </Section>
            {card?.user && <TaskAsComposer user={card.user} accent={color} />}
            <Section label={`Skills (${card?.card?.skills?.length ?? 0})`}>
              <div className="flex flex-col gap-1.5">
                {card?.card?.skills?.map((s: any) => (
                  <div key={s.id} className="inset rounded-sm px-2 py-1.5">
                    <div className="text-[11px] text-ink">{s.name}</div>
                    <div className="flex flex-wrap gap-1 mt-1">{s.tags?.map((t: string) => <span key={t} className="mono text-[8.5px] px-1 py-0.5 rounded-sm" style={{ color: "var(--muted)", background: "var(--inset)" }}>{t}</span>)}</div>
                  </div>
                ))}
              </div>
            </Section>
            <Section label={`Sensitive context owned (${card?.owned_items?.length ?? 0})`}>
              {card?.owned_items?.length ? (
                <div className="flex flex-col gap-1.5">
                  {card.owned_items.map((it) => (
                    <div key={it.item_id} className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-1.5 min-w-0"><Lock size={11} className="text-faint shrink-0" /><span className="text-[11px] text-ink truncate">{it.title}</span></span>
                      <SensitivityShield level={it.sensitivity} withLabel />
                    </div>
                  ))}
                </div>
              ) : <div className="text-[11px] text-faint">Holds no sensitive items.</div>}
            </Section>
          </>
        )}

        {tab === "thinking" && (
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5 mb-1 text-[10px] text-muted"><Brain size={12} style={{ color: "var(--violet)" }} /> What this agent reasoned before acting (real Mistral).</div>
            {thoughts.map((s) => (
              <div key={s.span_id} className="rounded-md px-2.5 py-1.5 text-[11.5px] italic leading-snug" style={{ background: "rgba(109,40,217,0.05)", border: "1px solid rgba(109,40,217,0.22)", color: "var(--violet)" }}>💭 {s.summary}</div>
            ))}
            {thoughts.length === 0 && <div className="text-[11px] text-faint text-center py-5">No reasoning captured yet — task this agent to see it think.</div>}
          </div>
        )}

        {tab === "learned" && (
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5 mb-1 text-[10px] text-muted"><Sparkles size={12} style={{ color: "var(--cyan)" }} /> Facts learned from other agents — at the fidelity received.</div>
            {(card?.learned ?? []).map((f) => (
              <div key={f.item_id} className="rounded-md px-2.5 py-1.5" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] text-ink truncate">{f.title}</span>
                  <span className="flex items-center gap-1 shrink-0">
                    {f.redacted && <span className="mono text-[8px] uppercase px-1 py-0.5 rounded" style={{ color: "var(--amber)", background: "rgba(185,113,10,0.12)" }}>redacted</span>}
                    <SensitivityShield level={f.sensitivity} />
                  </span>
                </div>
                <div className="mono text-[8.5px] text-faint mt-0.5">from {f.source_name}{f.redacted ? " · safe summary only" : " · full"}</div>
              </div>
            ))}
            {(card?.learned?.length ?? 0) === 0 && <div className="text-[11px] text-faint text-center py-5">Hasn't learned anything from others yet.</div>}
          </div>
        )}

        {tab === "trace" && (
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5 mb-1 text-[10px] text-muted"><Zap size={12} style={{ color: "var(--accent)" }} /> Operations / function calls — <span style={{ color: "var(--ok)" }}>● live</span> Mistral vs <span className="text-faint">○ det</span> deterministic.</div>
            {(card?.trace ?? []).map((s) => <SpanRow key={s.span_id} s={s} nameOf={nameOf} />)}
            {(card?.trace?.length ?? 0) === 0 && <div className="text-[11px] text-faint text-center py-5">No operations recorded yet.</div>}
          </div>
        )}
      </div>
    </Drawer>
  );
}

function TaskAsComposer({ user, accent }: { user: NonNullable<AgentCardView["user"]>; accent: string }) {
  const [text, setText] = useState("");
  const submit = async () => {
    const p = text.trim();
    if (!p) return;
    setText("");
    try {
      await api.prompt(p, { user_id: user.user_id });
      useStore.getState().setView("convo"); // reveal the conversation timeline…
      useStore.getState().selectAgent(null); // …and close the drawer to watch it unfold
    } catch (e) {
      console.error(e);
    }
  };
  return (
    <Section label={`Task as ${user.name}`}>
      <div className="text-[10px] text-faint leading-snug mb-1.5">
        Dispatch a prompt attributed to {user.name} — the human who operates this agent. The org routes it as usual; the prompt is credited to this user.
      </div>
      <div className="flex items-center gap-1.5 inset rounded-md px-2 h-9" style={{ boxShadow: `inset 0 0 0 1px ${accent}33` }}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder="Prompt to dispatch as this user…"
          className="bg-transparent outline-none text-ink text-[12px] flex-1 min-w-0"
        />
        <button
          onClick={submit}
          disabled={!text.trim()}
          className="text-[10px] font-bold tracking-wide px-2.5 py-1 rounded shrink-0 text-white transition-opacity disabled:opacity-40"
          style={{ background: accent }}
        >
          TASK
        </button>
      </div>
    </Section>
  );
}

/** A2A discovery, shown in the UI: the PUBLIC card (served at the well-known URI,
 *  no auth) vs the AUTHENTICATED extended card (adds the internal org profile). */
function A2ACardPanel({ id }: { id: string }) {
  const [tab, setTab] = useState<"public" | "extended">("public");
  const [pub, setPub] = useState<any>(null);
  const [ext, setExt] = useState<any>(null);
  const [extErr, setExtErr] = useState<string | null>(null);

  useEffect(() => {
    setPub(null); setExt(null); setExtErr(null);
    api.publicCard(id).then(setPub).catch(() => {});
    api.extendedCard(id).then(setExt).catch((e) => setExtErr(String(e?.message ?? e)));
  }, [id]);

  const caps = pub?.capabilities ?? {};
  const capList = ["streaming", "pushNotifications", "extendedAgentCard"].filter((k) => caps[k]);
  const prof = (ext?.extensions ?? []).find((e: any) => String(e.uri).includes("org-profile"))?.metadata;

  const Pill = ({ k, label }: { k: "public" | "extended"; label: string }) => (
    <button onClick={() => setTab(k)} className="px-2 h-6 rounded text-[10px] font-bold mono transition-colors"
      style={{ background: tab === k ? (k === "extended" ? "var(--coral)" : "var(--accent)") : "var(--inset)",
               color: tab === k ? "#fff" : "var(--muted)" }}>{label}</button>
  );

  return (
    <Section label="A2A card · discovery">
      <div className="flex items-center gap-1 mb-2">
        <Pill k="public" label="🌐 Public" />
        <Pill k="extended" label="🔒 Extended" />
        <a href={tab === "public" ? `/.well-known/agents/${id}/agent-card.json` : `/api/agents/${id}/card/extended`}
           target="_blank" rel="noreferrer" className="ml-auto mono text-[9px] text-faint hover:text-accent">raw json ↗</a>
      </div>

      {tab === "public" ? (
        <div className="inset rounded-md p-2.5">
          <div className="text-[9.5px] text-faint mono mb-1.5">GET /.well-known/agents/{id.slice(0, 10)}…/agent-card.json · no auth</div>
          {pub ? (
            <>
              <Row k="Name" v={pub.name} />
              <Row k="Skills" v={String(pub.skills?.length ?? 0)} />
              <Row k="Capabilities" v={capList.join(" · ") || "—"} />
              <Row k="Security" v={Object.keys(pub.securitySchemes ?? {}).join(", ") || "—"} />
              <div className="mt-2 flex items-start gap-1.5 text-[10px] rounded px-2 py-1.5" style={{ background: "rgba(209,42,58,0.06)", color: "var(--coral)" }}>
                <Lock size={11} className="shrink-0 mt-0.5" />
                <span>Internal org profile (department · level · clearance · reporting line) is <b>withheld</b> from the public card.</span>
              </div>
            </>
          ) : <div className="text-[10.5px] text-faint">loading public card…</div>}
        </div>
      ) : (
        <div className="inset rounded-md p-2.5">
          <div className="text-[9.5px] text-faint mono mb-1.5">GET /api/agents/{id.slice(0, 10)}…/card/extended · authenticated</div>
          {prof ? (
            <>
              <div className="text-[10px] mb-1.5" style={{ color: "var(--ok)" }}>✓ Authenticated — the extended card reveals the org profile:</div>
              {[["Department", prof.department], ["Level", `L${prof.level}`], ["Clearance", `L${prof.clearance}`],
                ["Security cleared", prof.security_cleared ? "yes" : "no"], ["Goal", prof.goal]].map(([k, v]) => (
                <div key={k} className="flex items-center justify-between text-[11px] py-0.5 px-1.5 rounded my-0.5" style={{ background: "rgba(209,42,58,0.07)" }}>
                  <span className="text-faint">{k}</span>
                  <span className="text-ink truncate max-w-[62%] text-right" title={String(v)}>{String(v)}</span>
                </div>
              ))}
            </>
          ) : extErr ? (
            <div className="flex items-start gap-1.5 text-[10.5px]" style={{ color: "var(--coral)" }}>
              <Lock size={12} className="shrink-0 mt-0.5" />
              <span>Requires authentication (HTTP {extErr}). Set <span className="mono">ATLAS_API_KEY</span> and the console sends it automatically.</span>
            </div>
          ) : <div className="text-[10.5px] text-faint">loading extended card…</div>}
        </div>
      )}
    </Section>
  );
}

function Tag({ children, color }: { children: React.ReactNode; color?: string }) {
  return <span className="text-[10px] px-1.5 py-0.5 rounded-sm" style={{ color: color ?? "var(--muted)", background: color ? `${color}14` : "var(--inset)", border: `1px solid ${color ? `${color}33` : "var(--border)"}` }}>{children}</span>;
}
function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="mt-4 first:mt-0"><div className="eyebrow mb-2">{label}</div>{children}</div>;
}
function Row({ k, v }: { k: string; v: string }) {
  return <div className="flex items-center justify-between text-[11px] py-0.5"><span className="text-faint">{k}</span><span className="text-muted truncate max-w-[60%] text-right">{v}</span></div>;
}
