import { Activity } from "lucide-react";
import { useStore } from "../store";
import { Brackets } from "./ui";

function Tile({ label, value, color, accent }: { label: string; value: number | string; color?: string; accent?: string }) {
  return (
    <div className="relative inset rounded-md px-3 py-1.5 flex flex-col justify-center min-w-[82px] overflow-hidden">
      {accent && <span className="absolute left-0 top-0 bottom-0 w-[3px]" style={{ background: accent }} />}
      <div className="eyebrow text-[8.5px]">{label}</div>
      <div className="font-display tnum text-[23px] leading-none font-bold mt-1" style={{ color: color ?? "var(--text)" }}>{value}</div>
    </div>
  );
}

export function MetricsStrip() {
  const t = useStore((s) => s.metricsTotals);
  const m = (k: string) => (t?.[k] ?? 0) as number;
  const derived = (t?.derived ?? {}) as Record<string, number>;
  const shared = m("items_shared");
  const redacted = m("items_redacted");
  const denied = m("items_denied");
  const total = Math.max(1, shared + redacted + denied);

  return (
    <div className="panel rounded-lg flex items-stretch gap-2 px-3 py-2 overflow-x-auto h-[84px]">
      <Brackets />
      <div className="flex items-center gap-2 pr-2 shrink-0">
        <Activity size={16} style={{ color: "var(--accent)" }} />
        <div className="leading-tight">
          <div className="idx">05</div>
          <div className="eyebrow text-[8.5px] leading-tight" style={{ color: "var(--text-2)" }}>Coordination<br />Efficiency</div>
        </div>
      </div>
      <Tile label="Messages" value={m("messages")} accent="var(--cyan)" />
      <Tile label="Agents" value={m("distinct_agents_contacted")} accent="var(--accent)" />
      <Tile label="Hops" value={m("hops")} accent="var(--violet)" />
      <Tile label="Shared" value={shared} color="var(--ok)" accent="var(--ok)" />
      <Tile label="Redacted" value={redacted} color="var(--amber)" accent="var(--amber)" />
      <Tile label="Withheld" value={denied} color="var(--coral)" accent="var(--coral)" />
      <Tile label="HITL" value={m("hitl_escalations")} color="var(--violet)" accent="var(--violet)" />
      <Tile label="Compliance" value={m("policy_overrides") + m("policy_pregates")} color="var(--coral)" accent="var(--coral)" />
      <Tile label="Reuse saved" value={m("redundant_contacts_avoided")} color="var(--ok)" accent="var(--ok)" />

      <div className="inset rounded-md px-3 py-1.5 flex flex-col justify-center flex-1 min-w-[210px]">
        <div className="flex items-center justify-between">
          <span className="eyebrow text-[8.5px]">Context disposition</span>
          <span className="mono text-[9.5px] text-faint">eff {(derived.efficiency ?? 0).toFixed(2)} · redact {((derived.redaction_ratio ?? 0) * 100).toFixed(0)}%</span>
        </div>
        <div className="flex h-2.5 rounded-full overflow-hidden mt-1.5" style={{ background: "var(--bg-2)" }}>
          <Seg v={shared} total={total} color="var(--ok)" />
          <Seg v={redacted} total={total} color="var(--amber)" />
          <Seg v={denied} total={total} color="var(--coral)" />
        </div>
        <div className="flex gap-3 mt-1 text-[9px] mono">
          <span style={{ color: "var(--ok)" }}>▪ shared {shared}</span>
          <span style={{ color: "var(--amber)" }}>▪ redacted {redacted}</span>
          <span style={{ color: "var(--coral)" }}>▪ withheld {denied}</span>
        </div>
      </div>
    </div>
  );
}

function Seg({ v, total, color }: { v: number; total: number; color: string }) {
  return <div style={{ width: `${(v / total) * 100}%`, background: color, transition: "width 0.45s ease" }} />;
}
