import { ArrowRight, Check, EyeOff, ShieldAlert, X, Zap } from "lucide-react";
import { api } from "../api";
import { useStore } from "../store";
import { IntentChip, SensitivityShield, toneColor } from "./ui";

export function RightRail() {
  return (
    <aside className="h-full glass rounded-xl flex flex-col overflow-hidden">
      <ThrottleBanner />
      <HitlQueue />
      <div className="mx-3 border-t" style={{ borderColor: "var(--border)" }} />
      <ActivityFeed />
    </aside>
  );
}

function ThrottleBanner() {
  const llm = useStore((s) => s.llm);
  if (!llm?.throttled) return null;
  return (
    <div className="m-2.5 mb-0 rounded-lg px-3 py-2 flex items-start gap-2 animate-slide-in" style={{ background: "rgba(243,182,100,0.1)", border: "1px solid var(--gold)", boxShadow: "0 0 18px -8px var(--gold)" }}>
      <Zap size={14} color="var(--gold)" className="animate-flicker shrink-0 mt-0.5" />
      <div className="min-w-0">
        <div className="text-[11px] font-semibold" style={{ color: "var(--gold)" }}>Bedrock rate-limited</div>
        <div className="text-[10px] text-muted leading-snug">{llm.reason || "throttling to stay within limits"}</div>
        <div className="mono text-[9px] text-faint mt-0.5">ok {llm.calls_ok} · throttled {llm.calls_throttled} · 429 {llm.calls_429}</div>
      </div>
    </div>
  );
}

function HitlQueue() {
  const hitl = useStore((s) => s.hitl);
  const agents = useStore((s) => s.agents);
  const removeHitl = useStore((s) => s.removeHitl);
  const nameOf = (id: string) => agents[id]?.name ?? id;

  const act = async (id: string, kind: "share" | "redact" | "deny") => {
    removeHitl(id);
    try {
      if (kind === "deny") await api.deny(id);
      else await api.approve(id, kind);
    } catch (e) { console.error(e); }
  };

  return (
    <div className="shrink-0 max-h-[46%] flex flex-col">
      <div className="flex items-center justify-between px-3.5 pt-3 pb-1.5">
        <span className="eyebrow flex items-center gap-1.5">
          <ShieldAlert size={12} color="var(--violet)" /> Approval Queue
        </span>
        <span className="mono text-[10px]" style={{ color: hitl.length ? "var(--violet)" : "var(--faint)" }}>{hitl.length} pending</span>
      </div>
      <div className="overflow-y-auto px-2.5 pb-2.5 flex flex-col gap-2 min-h-0">
        {hitl.length === 0 && <div className="text-[11px] text-faint px-1 py-4 text-center">No approvals pending.<br /><span className="text-[10px]">Sensitive shares surface here.</span></div>}
        {hitl.map((h) => (
          <div key={h.request_id} className="rounded-lg p-2.5 animate-slide-in" style={{ background: "linear-gradient(180deg, rgba(183,156,255,0.1), rgba(183,156,255,0.03))", border: "1px solid rgba(183,156,255,0.32)", boxShadow: "0 0 20px -10px var(--violet)" }}>
            <div className="flex items-center justify-between gap-2 mb-1.5">
              <span className="text-[12px] font-semibold text-ink truncate">{h.item_title}</span>
              <SensitivityShield level={h.sensitivity} withLabel />
            </div>
            <div className="flex items-center gap-1.5 text-[11px] text-muted mb-1.5">
              <span className="truncate max-w-[92px]" title={nameOf(h.requester)}>{nameOf(h.requester)}</span>
              <ArrowRight size={11} className="text-faint shrink-0" />
              <span className="truncate max-w-[92px]" title={nameOf(h.owner)}>{nameOf(h.owner)}</span>
            </div>
            <div className="mb-1.5"><IntentChip tag={h.intent?.purpose_tag} /></div>
            <div className="text-[10.5px] text-muted leading-snug mb-2 line-clamp-2" title={h.intent?.motivation}>“{h.intent?.motivation}”</div>
            <div className="grid grid-cols-3 gap-1.5">
              <button onClick={() => act(h.request_id, "share")} className="flex items-center justify-center gap-1 h-7 rounded-md text-[10px] font-bold transition-transform hover:scale-[1.03]" style={{ background: "linear-gradient(180deg, var(--accent-bright), var(--accent))", color: "#04221c" }}>
                <Check size={12} /> Share
              </button>
              <button onClick={() => act(h.request_id, "redact")} className="flex items-center justify-center gap-1 h-7 rounded-md text-[10px] font-bold border" style={{ borderColor: "var(--amber)", color: "var(--amber)", background: "rgba(242,179,102,0.08)" }}>
                <EyeOff size={12} /> Redact
              </button>
              <button onClick={() => act(h.request_id, "deny")} className="flex items-center justify-center gap-1 h-7 rounded-md text-[10px] font-bold border" style={{ borderColor: "var(--coral)", color: "var(--coral)", background: "rgba(255,107,129,0.08)" }}>
                <X size={12} /> Deny
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ActivityFeed() {
  const feed = useStore((s) => s.feed);
  const selectContext = useStore((s) => s.selectContext);
  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex items-center justify-between px-3.5 pt-3 pb-1.5">
        <span className="eyebrow">Activity Feed</span>
        <span className="mono text-[10px] text-faint">{feed.length}</span>
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-2 min-h-0">
        {feed.map((f) => (
          <button key={f.id} onClick={() => f.contextId && selectContext(f.contextId)} className="w-full flex items-start gap-2 px-2 py-1.5 rounded-md hover:bg-white/[0.03] text-left transition-colors">
            <span className="mt-1.5 w-1.5 h-1.5 rounded-full shrink-0" style={{ background: toneColor[f.tone] ?? toneColor.info, boxShadow: `0 0 7px ${toneColor[f.tone] ?? toneColor.info}` }} />
            <span className="flex-1 min-w-0">
              <span className="text-[11px] text-ink2 leading-tight block truncate">{f.text}</span>
              <span className="mono text-[8.5px] text-faint">{fmtTime(f.ts)} · {f.kind.replace(".", " ")}</span>
            </span>
          </button>
        ))}
        {feed.length === 0 && <div className="text-[11px] text-faint px-1 py-4 text-center">Awaiting activity…</div>}
      </div>
    </div>
  );
}

function fmtTime(iso: string): string {
  try { return new Date(iso).toLocaleTimeString("en-GB", { hour12: false }); } catch { return ""; }
}
