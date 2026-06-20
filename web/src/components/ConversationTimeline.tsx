import { useEffect, useState } from "react";
import { ArrowRight, Bot, BrainCircuit, Check, EyeOff, Network, Radio, ShieldAlert, Sparkles, Users, X } from "lucide-react";
import type { A2AMethodInfo, AgentThought, ChatMessage, HitlItem } from "../types";
import type { Decision } from "../store";
import { DEPARTMENT_LABEL, deptColor } from "../theme";
import { api } from "../api";
import { useStore } from "../store";
import { IntentChip, OutcomeBadge, SensitivityShield } from "./ui";

const EXAMPLES = [
  "Plan the Q3 launch with product, design, and marketing aligned on go-to-market",
  "Production incident on the auth service — coordinate the on-call response with the team",
  "Fix the billing Stripe payment integration and pull the live API credentials",
  "What is the L3 compensation band for an offer I'm preparing?",
];

export function ConversationTimeline() {
  const order = useStore((s) => s.contextOrder);
  const cron = useStore((s) => s.cron);

  if (order.length === 0) return <EmptyState />;

  return (
    <div className="h-full overflow-y-auto px-3 py-3">
      <div className="flex items-center gap-2 mb-2.5 px-0.5">
        <Radio size={13} className={cron.running ? "animate-flicker" : ""} style={{ color: cron.running ? "var(--gold)" : "var(--ok)" }} />
        <span className="eyebrow">Live conversations</span>
        {cron.running && <span className="mono text-[9.5px]" style={{ color: "var(--gold)" }}>· simulation on · new goal {cron.remaining.toFixed(0)}s</span>}
        <A2AMethodsLegend />
      </div>
      <div className="flex flex-col gap-2.5">
        {order.map((cid) => <ConversationCard key={cid} cid={cid} />)}
      </div>
    </div>
  );
}

/** Small reference explaining the A2A protocol methods behind every hop. */
function A2AMethodsLegend() {
  const [open, setOpen] = useState(false);
  const [methods, setMethods] = useState<A2AMethodInfo[]>([]);
  useEffect(() => {
    if (open && methods.length === 0) api.a2aMethods().then((r) => setMethods(r.methods)).catch(console.error);
  }, [open]);
  return (
    <div className="ml-auto relative">
      <button onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 mono text-[9px] px-1.5 py-0.5 rounded transition-colors"
        style={{ color: open ? "#fff" : "var(--accent)", background: open ? "var(--accent)" : "var(--accent-soft)" }}>
        <Network size={10} /> A2A methods
      </button>
      {open && (
        <div className="absolute right-0 top-6 z-30 w-[330px] rounded-md p-2.5 flex flex-col gap-1.5"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border)", boxShadow: "0 12px 30px -12px rgba(0,0,0,0.5)" }}>
          <div className="eyebrow pb-0.5">A2A protocol methods · how Atlas uses each</div>
          {methods.map((m) => (
            <div key={m.method} className="rounded-sm px-2 py-1.5" style={{ background: "var(--inset)" }}>
              <div className="flex items-center gap-1.5">
                <span className="mono text-[10px] font-bold text-ink">{m.method}</span>
                <span className="mono text-[8px] px-1 rounded-sm" style={{
                  color: m.active === "yes" ? "var(--ok)" : "var(--faint)",
                  background: m.active === "yes" ? "rgba(46,160,67,0.12)" : "var(--surface)",
                }}>{m.active === "yes" ? "active" : "spec"}</span>
              </div>
              <div className="text-[10px] text-muted mt-0.5">{m.summary}</div>
              <div className="text-[9px] text-faint mt-0.5">↳ {m.atlas}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ConversationCard({ cid }: { cid: string }) {
  const ctx = useStore((s) => s.contexts[cid]);
  const messages = useStore((s) => s.messagesByCtx[cid]) ?? [];
  const decisions = useStore((s) => s.decisionsByCtx[cid]) ?? [];
  const thoughts = useStore((s) => s.thoughtsByCtx[cid]) ?? [];
  const agents = useStore((s) => s.agents);
  const selectContext = useStore((s) => s.selectContext);
  // NOTE: select the stable array and filter in render — returning a freshly
  // .filter()'d array from the selector makes useSyncExternalStore loop/crash.
  const hitl = useStore((s) => s.hitl);
  const pending = hitl.filter((h) => h.context_id === cid);

  const nameOf = (id: string) => (id === "operator" ? "Operator" : agents[id]?.name ?? id);
  const isGroup = messages.some((m) => m.mode === "group");
  const isCron = ctx?.kind === "cron";

  type Row = { ts: number; m?: ChatMessage; d?: Decision; t?: AgentThought };
  const rows: Row[] = [
    ...messages.map((m) => ({ ts: m.ts, m })),
    ...decisions.filter((d) => d.kind !== "reused").map((d) => ({ ts: d.ts, d })),
    ...thoughts.map((t) => ({ ts: t.ts, t })),
  ].sort((a, b) => a.ts - b.ts);
  // Show enough to keep a full group thread legible (opening + member replies +
  // the need-to-know exchange ≈ 14); longer threads collapse behind the drawer.
  const CAP = 20;
  const shown = rows.slice(-CAP);
  const hidden = rows.length - shown.length;

  const state = ctx?.state;
  const stateColor = state === "completed" ? "var(--ok)" : state === "input-required" ? "var(--violet)" : "var(--gold)";

  return (
    <div
      className="panel-flat rounded-lg overflow-hidden animate-msg"
      style={pending.length ? { boxShadow: "0 0 0 1.5px var(--violet), 0 8px 24px -18px rgba(0,0,0,0.4)", borderColor: "var(--violet)" } : undefined}
    >
      {/* header */}
      <div className="px-3 py-2.5 border-b" style={{ borderColor: "var(--border)", background: pending.length ? "rgba(109,40,217,0.05)" : "var(--surface-2)" }}>
        <div className="flex items-start gap-2">
          <span
            className="shrink-0 mt-0.5 inline-flex items-center gap-1 rounded px-1.5 py-0.5 mono text-[8.5px] font-bold uppercase tracking-wider"
            style={{ color: isCron ? "var(--gold)" : "var(--accent)", background: isCron ? "rgba(194,104,10,0.1)" : "var(--accent-soft)" }}
          >
            {isCron ? <Bot size={10} /> : <Sparkles size={10} />} {isCron ? "Goal" : "Task"}
          </span>
          <div className="flex-1 min-w-0">
            <button onClick={() => selectContext(cid)} className="text-[12.5px] font-semibold text-ink leading-snug text-left hover:text-accent line-clamp-2">
              {ctx?.prompt ?? "Autonomous task"}
            </button>
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              {ctx?.routedTo && <Agent id={ctx.routedTo} name={nameOf(ctx.routedTo)} agents={agents} />}
              {isGroup ? (
                <span className="inline-flex items-center gap-1 mono text-[9px] px-1.5 py-0.5 rounded" style={{ color: "var(--violet)", background: "rgba(109,40,217,0.08)" }}><Users size={9} /> GROUP</span>
              ) : (
                <span className="mono text-[9px] px-1.5 py-0.5 rounded" style={{ color: "var(--accent)", background: "var(--accent-soft)" }}>1:1</span>
              )}
              {state && <span className="mono text-[9px] uppercase tracking-wide" style={{ color: stateColor }}>● {state}</span>}
            </div>
          </div>
        </div>
      </div>

      {/* transcript */}
      <div className="px-3 py-2 flex flex-col gap-1.5">
        {hidden > 0 && (
          <button onClick={() => selectContext(cid)} className="text-[10px] mono text-faint hover:text-accent self-center">+{hidden} earlier — open full thread</button>
        )}
        {shown.map((r, i) =>
          r.m ? <MsgRow key={i} m={r.m} agents={agents} nameOf={nameOf} />
          : r.t ? <ThoughtRow key={i} t={r.t} agents={agents} />
          : <DecisionRow key={i} d={r.d!} nameOf={nameOf} />,
        )}
        {shown.length === 0 && <div className="text-[11px] text-faint py-1">opening…</div>}
        {pending.map((h) => <InlineApproval key={h.request_id} h={h} nameOf={nameOf} />)}
      </div>
    </div>
  );
}

function InlineApproval({ h, nameOf }: { h: HitlItem; nameOf: (id: string) => string }) {
  const removeHitl = useStore((s) => s.removeHitl);
  const act = async (kind: "share" | "redact" | "deny") => {
    removeHitl(h.request_id); // optimistic; backend resumes the conversation
    try {
      if (kind === "deny") await api.deny(h.request_id);
      else await api.approve(h.request_id, kind);
    } catch (e) { console.error(e); }
  };
  return (
    <div className="rounded-md p-2.5 mt-0.5 animate-msg" style={{ background: "rgba(109,40,217,0.06)", border: "1px solid rgba(109,40,217,0.42)" }}>
      <div className="flex items-center gap-1.5 mb-1.5">
        <ShieldAlert size={13} color="var(--violet)" className="animate-flicker" />
        <span className="mono text-[9px] font-bold uppercase tracking-wider" style={{ color: "var(--violet)" }}>Awaiting your approval</span>
        <span className="ml-auto"><SensitivityShield level={h.sensitivity} withLabel /></span>
      </div>
      <div className="text-[11.5px] leading-snug mb-1.5" style={{ color: "var(--text-2)" }}>
        <span className="font-semibold text-ink">{nameOf(h.requester)}</span> is requesting{" "}
        <span className="font-semibold text-ink">‘{h.item_title}’</span> from{" "}
        <span className="font-semibold text-ink">{nameOf(h.owner)}</span>.
      </div>
      <div className="flex items-center gap-1.5 mb-2 flex-wrap">
        <IntentChip tag={h.intent?.purpose_tag} />
        <span className="text-[10px] text-muted italic truncate max-w-[280px]">“{h.intent?.motivation}”</span>
      </div>
      <div className="grid grid-cols-3 gap-1.5">
        <button onClick={() => act("share")} className="flex items-center justify-center gap-1 h-7 rounded-md text-[10px] font-bold text-white" style={{ background: "var(--ok)" }}>
          <Check size={12} /> SHARE
        </button>
        <button onClick={() => act("redact")} className="flex items-center justify-center gap-1 h-7 rounded-md text-[10px] font-bold" style={{ border: "1px solid var(--amber)", color: "var(--amber)", background: "rgba(185,113,10,0.06)" }}>
          <EyeOff size={12} /> REDACT
        </button>
        <button onClick={() => act("deny")} className="flex items-center justify-center gap-1 h-7 rounded-md text-[10px] font-bold" style={{ border: "1px solid var(--coral)", color: "var(--coral)", background: "rgba(209,42,58,0.06)" }}>
          <X size={12} /> DENY
        </button>
      </div>
      <div className="mono text-[8.5px] text-faint mt-1.5">the conversation continues based on your decision</div>
    </div>
  );
}

function Agent({ id, name, agents }: { id: string; name: string; agents: any }) {
  const dept = agents[id]?.department;
  const c = dept ? deptColor(dept) : "var(--muted)";
  return (
    <span className="inline-flex items-center gap-1 min-w-0" title={dept ? DEPARTMENT_LABEL[dept] : ""}>
      <span className="w-2 h-2 rounded-[2px] shrink-0" style={{ background: c }} />
      <span className="text-[11px] font-medium text-ink truncate max-w-[120px]">{name}</span>
    </span>
  );
}

function MsgRow({ m, agents, nameOf }: { m: ChatMessage; agents: any; nameOf: (id: string) => string }) {
  const group = m.mode === "group";
  const recip = group ? `group · ${m.recipients.length}` : m.recipients.map(nameOf).join(", ");
  return (
    <div className="rounded-md px-2.5 py-1.5" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
      <div className="flex items-center gap-1.5 flex-wrap mb-0.5">
        <Agent id={m.sender} name={nameOf(m.sender)} agents={agents} />
        <ArrowRight size={11} className="text-faint shrink-0" />
        <span className="text-[10.5px] text-muted truncate max-w-[150px]">{recip}</span>
        {m.intent && <IntentChip tag={m.intent.purpose_tag} compact />}
        {m.method && (
          <span className="ml-auto inline-flex items-center gap-1 mono text-[8.5px] px-1.5 py-0.5 rounded shrink-0"
            title="A2A protocol method for this hop"
            style={{ color: "var(--accent)", background: "var(--accent-soft)" }}>
            <Network size={9} /> {m.method}
          </span>
        )}
      </div>
      <div className="text-[11.5px] leading-snug" style={{ color: "var(--text-2)" }}>{m.text}</div>
    </div>
  );
}

const PHASE_LABEL: Record<string, string> = {
  plan: "planning", discover: "discovering", policy: "weighing need-to-know",
  coordinate: "coordinating", reasoning: "thinking",
};

function ThoughtRow({ t, agents }: { t: AgentThought; agents: any }) {
  const dept = agents[t.agentId]?.department;
  const c = dept ? deptColor(dept) : "var(--muted)";
  return (
    <div className="flex items-start gap-1.5 px-2.5 py-1 rounded-md italic"
      style={{ background: "transparent", borderLeft: `2px dashed ${c}66` }}>
      <BrainCircuit size={11} className="shrink-0 mt-0.5" style={{ color: c }} />
      <span className="text-[10.5px] leading-snug" style={{ color: "var(--muted)" }}>
        <span className="font-semibold not-italic" style={{ color: "var(--text-2)" }}>{t.name}</span>
        <span className="mono text-[8px] not-italic px-1 ml-1 rounded-sm" style={{ background: "var(--inset)", color: "var(--faint)" }}>{PHASE_LABEL[t.phase] ?? t.phase}</span>
        <span className="ml-1">“{t.thought}”</span>
      </span>
    </div>
  );
}

function DecisionRow({ d, nameOf }: { d: Decision; nameOf: (id: string) => string }) {
  const outcome = d.kind === "shared" ? "shared" : d.kind === "redacted" ? "redacted" : d.kind === "denied" ? "denied" : "reused";
  return (
    <div className="flex items-center gap-2 px-2.5 py-1 rounded-md" style={{ background: "var(--inset)" }} title={d.reason}>
      <OutcomeBadge kind={outcome} />
      <span className="text-[11px] text-ink truncate flex-1 min-w-0">{d.title}</span>
      <SensitivityShield level={d.sensitivity} />
      <span className="mono text-[9px] text-faint shrink-0 hidden lg:inline truncate max-w-[120px]">{nameOf(d.sender)}→{nameOf(d.recipient)}</span>
    </div>
  );
}

function EmptyState() {
  const fire = (p: string) => api.prompt(p).catch(console.error);
  const toggleCron = () => api.cron(true).catch(console.error);
  return (
    <div className="h-full grid place-items-center p-6">
      <div className="max-w-[480px] w-full text-center">
        <div className="font-display text-[26px] font-bold text-ink leading-tight mb-2">Watch 100 agents talk, like humans.</div>
        <div className="text-[12.5px] text-muted leading-relaxed mb-5">
          Dispatch a task and follow it live — routed to the right agent, who discovers others, then
          shares, redacts, withholds, or escalates each piece of context by need-to-know. Or start the
          simulation and the org launches a new goal every 30 seconds on its own.
        </div>
        <button
          onClick={toggleCron}
          className="mb-5 inline-flex items-center gap-2 px-4 py-2 rounded-md text-[12px] font-bold text-white"
          style={{ background: "var(--gold)" }}
        >
          ▶ Start the simulation
        </button>
        <div className="eyebrow mb-2">or try a prompt</div>
        <div className="flex flex-col gap-1.5 text-left">
          {EXAMPLES.map((e) => (
            <button
              key={e}
              onClick={() => fire(e)}
              className="group flex items-center gap-2.5 px-3 py-2 rounded-md transition-colors hover:bg-[var(--inset)]"
              style={{ border: "1px solid var(--border)", background: "var(--surface)" }}
            >
              <span className="text-[11.5px] text-text-2 flex-1" style={{ color: "var(--text-2)" }}>{e}</span>
              <ArrowRight size={14} className="text-faint group-hover:text-accent shrink-0" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
