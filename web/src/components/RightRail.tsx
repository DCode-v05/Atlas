import { ArrowRight, Check, EyeOff, ShieldAlert, X, Zap } from "lucide-react";
import { api } from "../api";
import { useStore } from "../store";
import { DeptMiniMap } from "./DeptMiniMap";
import { Brackets, IntentChip, SectionHead, SensitivityShield, toneColor } from "./ui";

export function RightRail() {
  return (
    <aside className="h-full panel rounded-lg flex flex-col overflow-hidden">
      <Brackets />
      <SectionHead idx="02">Comms Map</SectionHead>
      <DeptMiniMap />
      <ThrottleBanner />
      <div className="mx-3 border-t" style={{ borderColor: "var(--border)" }} />
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
    <div className="mx-2.5 mb-1 rounded-md px-3 py-2 flex items-start gap-2 animate-slide-in" style={{ background: "rgba(194,104,10,0.08)", border: "1px solid var(--gold)" }}>
      <Zap size={14} color="var(--gold)" className="animate-flicker shrink-0 mt-0.5" />
      <div className="min-w-0">
        <div className="text-[11px] font-semibold" style={{ color: "var(--gold)" }}>Bedrock rate-limited</div>
        <div className="text-[10px] text-muted leading-snug">{llm.reason || "pacing calls to stay within limits"}</div>
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

  const pending = hitl.length > 0;
  return (
    <div className="shrink-0 flex flex-col" style={{ maxHeight: pending ? "44%" : "auto" }}>
      <SectionHead
        idx="03"
        color="var(--violet)"
        right={<span className="mono text-[9.5px] uppercase tracking-wide" style={{ color: pending ? "var(--violet)" : "var(--faint)" }}>{hitl.length} pending</span>}
      >
        <span className="flex items-center gap-1.5"><ShieldAlert size={11} color="var(--violet)" /> Approvals</span>
      </SectionHead>
      {!pending && <div className="text-[10.5px] text-faint px-3.5 pb-2.5 leading-snug">No approvals pending. Sensitive shares that breach need-to-know surface here for your decision.</div>}
      {pending && (
        <div className="overflow-y-auto px-2.5 pb-2.5 flex flex-col gap-2 min-h-0">
          {hitl.map((h) => (
            <div key={h.request_id} className="relative rounded-md p-2.5 animate-slide-in" style={{ background: "rgba(109,40,217,0.05)", border: "1px solid rgba(109,40,217,0.32)" }}>
              <Brackets color="var(--violet)" />
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
                <button onClick={() => act(h.request_id, "share")} className="flex items-center justify-center gap-1 h-7 rounded-md text-[10px] font-bold text-white" style={{ background: "var(--ok)" }}>
                  <Check size={12} /> SHARE
                </button>
                <button onClick={() => act(h.request_id, "redact")} className="flex items-center justify-center gap-1 h-7 rounded-md text-[10px] font-bold" style={{ border: "1px solid var(--amber)", color: "var(--amber)", background: "rgba(185,113,10,0.06)" }}>
                  <EyeOff size={12} /> REDACT
                </button>
                <button onClick={() => act(h.request_id, "deny")} className="flex items-center justify-center gap-1 h-7 rounded-md text-[10px] font-bold" style={{ border: "1px solid var(--coral)", color: "var(--coral)", background: "rgba(209,42,58,0.06)" }}>
                  <X size={12} /> DENY
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ActivityFeed() {
  const feed = useStore((s) => s.feed);
  const selectContext = useStore((s) => s.selectContext);
  return (
    <div className="flex-1 flex flex-col min-h-0">
      <SectionHead idx="04" right={<span className="mono text-[9.5px] text-faint tnum">{feed.length}</span>}>Signals Log</SectionHead>
      <div className="flex-1 overflow-y-auto px-2 pb-2 min-h-0">
        {feed.map((f) => (
          <button key={f.id} onClick={() => f.contextId && selectContext(f.contextId)} className="w-full flex items-start gap-2 px-2 py-1.5 rounded-md hover:bg-[var(--inset)] text-left transition-colors">
            <span className="mt-1.5 w-1.5 h-1.5 rounded-full shrink-0" style={{ background: toneColor[f.tone] ?? toneColor.info }} />
            <span className="flex-1 min-w-0">
              <span className="text-[11px] text-ink leading-tight block truncate">{f.text}</span>
              <span className="mono text-[8.5px] text-faint">{fmtTime(f.ts)} · {f.kind.replace(".", " ")}</span>
            </span>
          </button>
        ))}
        {feed.length === 0 && <div className="text-[10.5px] text-faint px-2 py-5 text-center leading-relaxed">Awaiting signals.<br />Dispatch a prompt or start the simulation.</div>}
      </div>
    </div>
  );
}

function fmtTime(iso: string): string {
  try { return new Date(iso).toLocaleTimeString("en-GB", { hour12: false }); } catch { return ""; }
}
