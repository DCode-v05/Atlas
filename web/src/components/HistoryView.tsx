import { Bot, CheckCircle2, Sparkles, Users } from "lucide-react";
import { useStore } from "../store";
import { deptColor } from "../theme";

export function HistoryView() {
  const order = useStore((s) => s.contextOrder);
  const contexts = useStore((s) => s.contexts);
  const done = order.filter((cid) => {
    const st = contexts[cid]?.state;
    return st === "completed" || st === "failed";
  });

  if (done.length === 0) {
    return (
      <div className="h-full grid place-items-center p-6">
        <div className="text-center max-w-[360px]">
          <CheckCircle2 size={30} className="mx-auto mb-3" style={{ color: "var(--faint)" }} />
          <div className="font-display text-[17px] font-bold text-ink mb-1">No completed goals yet</div>
          <div className="text-[12px] text-muted leading-relaxed">Finished conversations move here automatically. Live ones stay in the Conversation tab; click any card to replay it in full.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto px-3 py-3">
      <div className="flex items-center gap-2 mb-2.5 px-0.5">
        <CheckCircle2 size={13} style={{ color: "var(--ok)" }} />
        <span className="eyebrow">Completed goals</span>
        <span className="mono text-[9.5px] text-faint">· {done.length}</span>
        <span className="ml-auto mono text-[9px] text-faint">click any goal to replay it</span>
      </div>
      <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(290px, 1fr))" }}>
        {done.map((cid) => <HistoryCard key={cid} cid={cid} />)}
      </div>
    </div>
  );
}

function HistoryCard({ cid }: { cid: string }) {
  const ctx = useStore((s) => s.contexts[cid]);
  const messages = useStore((s) => s.messagesByCtx[cid]) ?? [];
  const decisions = useStore((s) => s.decisionsByCtx[cid]) ?? [];
  const agents = useStore((s) => s.agents);
  const selectContext = useStore((s) => s.selectContext);

  const isGroup = messages.some((m) => m.mode === "group");
  const isCron = ctx?.kind === "cron";
  const counts = { shared: 0, redacted: 0, denied: 0 };
  for (const d of decisions) {
    if (d.kind === "shared") counts.shared++;
    else if (d.kind === "redacted") counts.redacted++;
    else if (d.kind === "denied") counts.denied++;
  }
  const failed = ctx?.state === "failed";

  return (
    <button
      onClick={() => selectContext(cid)}
      className="panel-flat rounded-lg p-3 text-left transition-all hover:-translate-y-0.5"
      style={{ boxShadow: "0 8px 24px -18px rgba(0,0,0,0.5)" }}
    >
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 mono text-[8px] font-bold uppercase tracking-wider" style={{ color: isCron ? "var(--gold)" : "var(--accent)", background: isCron ? "rgba(194,104,10,0.1)" : "var(--accent-soft)" }}>
          {isCron ? <Bot size={9} /> : <Sparkles size={9} />} {isCron ? "Goal" : "Task"}
        </span>
        {isGroup && (
          <span className="inline-flex items-center gap-1 mono text-[8px] px-1.5 py-0.5 rounded" style={{ color: "var(--violet)", background: "rgba(109,40,217,0.08)" }}><Users size={9} /> GROUP</span>
        )}
        <span className="ml-auto mono text-[8.5px] uppercase" style={{ color: failed ? "var(--coral)" : "var(--ok)" }}>● {ctx?.state}</span>
      </div>
      <div className="text-[12px] font-semibold text-ink leading-snug line-clamp-2 mb-2 min-h-[2.4em]">{ctx?.prompt ?? "Autonomous task"}</div>
      <div className="flex items-center gap-2 text-[10px] text-muted">
        {ctx?.routedTo && (
          <span className="flex items-center gap-1 min-w-0">
            <span className="w-2 h-2 rounded-[2px] shrink-0" style={{ background: deptColor(agents[ctx.routedTo]?.department ?? "") }} />
            <span className="truncate">{ctx.routedToName}</span>
          </span>
        )}
        <span className="mono text-[9px] text-faint shrink-0">· {messages.length} msgs</span>
      </div>
      {(counts.shared || counts.redacted || counts.denied) > 0 && (
        <div className="flex gap-1.5 mt-2">
          {counts.shared > 0 && <Stat c="var(--ok)" n={counts.shared} l="shared" />}
          {counts.redacted > 0 && <Stat c="var(--amber)" n={counts.redacted} l="redacted" />}
          {counts.denied > 0 && <Stat c="var(--coral)" n={counts.denied} l="withheld" />}
        </div>
      )}
    </button>
  );
}

function Stat({ c, n, l }: { c: string; n: number; l: string }) {
  return (
    <span className="inline-flex items-center gap-1 mono text-[9px] px-1.5 py-0.5 rounded" style={{ color: c, background: `${c}14` }}>
      <span className="font-bold">{n}</span> {l}
    </span>
  );
}
