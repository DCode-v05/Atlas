import { AlertTriangle, Zap } from "lucide-react";
import { useStore } from "../store";
import { DeptMiniMap } from "./DeptMiniMap";
import { Brackets, SectionHead, toneColor } from "./ui";

export function RightRail() {
  return (
    <aside className="h-full panel rounded-lg flex flex-col overflow-hidden">
      <Brackets />
      <SectionHead idx="02">Comms Map</SectionHead>
      <DeptMiniMap />
      <ThrottleBanner />
      <div className="mx-3 border-t" style={{ borderColor: "var(--border)" }} />
      <ActivityFeed />
    </aside>
  );
}

function ThrottleBanner() {
  const llm = useStore((s) => s.llm);
  const errored = !!llm?.errored;
  const throttled = !!llm?.throttled;
  if (!errored && !throttled) return null;
  const c = errored ? "var(--coral)" : "var(--gold)";
  const bg = errored ? "rgba(209,42,58,0.07)" : "rgba(194,104,10,0.08)";
  const Icon = errored ? AlertTriangle : Zap;
  const title = errored ? "LLM unreachable — using templates" : "Bedrock rate-limited";
  const detail = errored
    ? (llm?.reason || "Bedrock calls are failing — messages fall back to deterministic templates.")
    : (llm?.reason || "pacing calls to stay within limits");
  return (
    <div className="mx-2.5 mb-1 rounded-md px-3 py-2 flex items-start gap-2 animate-slide-in" style={{ background: bg, border: `1px solid ${c}` }}>
      <Icon size={14} color={c} className="animate-flicker shrink-0 mt-0.5" />
      <div className="min-w-0">
        <div className="text-[11px] font-semibold" style={{ color: c }}>{title}</div>
        <div className="text-[10px] text-muted leading-snug">{detail}</div>
      </div>
    </div>
  );
}

function ActivityFeed() {
  const feed = useStore((s) => s.feed);
  const selectContext = useStore((s) => s.selectContext);
  return (
    <div className="flex-1 flex flex-col min-h-0">
      <SectionHead idx="03" right={<span className="mono text-[9.5px] text-faint tnum">{feed.length}</span>}>Signals Log</SectionHead>
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
