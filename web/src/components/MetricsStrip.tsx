import { Gauge } from "lucide-react";
import { useStore } from "../store";

function Tile({ label, value, color, accent }: { label: string; value: number | string; color?: string; accent?: string }) {
  return (
    <div className="relative inset rounded-lg px-3 py-1.5 flex flex-col justify-center min-w-[88px] overflow-hidden">
      {accent && <span className="absolute left-0 top-0 bottom-0 w-[2px]" style={{ background: accent, boxShadow: `0 0 8px ${accent}` }} />}
      <div className="eyebrow">{label}</div>
      <div className="font-display tnum text-[21px] leading-none font-bold mt-0.5" style={{ color: color ?? "var(--text)" }}>
        {value}
      </div>
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
    <div className="h-full glass rounded-xl flex items-stretch gap-2 px-3 py-2 overflow-x-auto">
      <div className="flex items-center gap-2 pr-2 shrink-0">
        <Gauge size={16} className="text-accent" />
        <div className="eyebrow leading-tight" style={{ color: "var(--text-2)" }}>
          Coordination<br />Efficiency
        </div>
      </div>
      <Tile label="Messages" value={m("messages")} accent="#5ec9c0" />
      <Tile label="Agents" value={m("distinct_agents_contacted")} accent="#7aa8d8" />
      <Tile label="Hops" value={m("hops")} accent="#9a8cf0" />
      <Tile label="Shared" value={shared} color="var(--accent)" accent="var(--accent)" />
      <Tile label="Redacted" value={redacted} color="var(--amber)" accent="var(--amber)" />
      <Tile label="Withheld" value={denied} color="var(--coral)" accent="var(--coral)" />
      <Tile label="HITL" value={m("hitl_escalations")} color="var(--violet)" accent="var(--violet)" />
      <Tile label="Reuse saved" value={m("redundant_contacts_avoided")} color="var(--accent-bright)" accent="var(--accent)" />

      <div className="inset rounded-lg px-3 py-1.5 flex flex-col justify-center flex-1 min-w-[200px]">
        <div className="flex items-center justify-between">
          <span className="eyebrow">Context disposition</span>
          <span className="mono text-[9.5px] text-faint">eff {(derived.efficiency ?? 0).toFixed(2)} · redact {((derived.redaction_ratio ?? 0) * 100).toFixed(0)}%</span>
        </div>
        <div className="flex h-2.5 rounded-full overflow-hidden mt-1.5" style={{ background: "rgba(255,255,255,0.05)" }}>
          <Seg v={shared} total={total} color="var(--accent)" />
          <Seg v={redacted} total={total} color="var(--amber)" />
          <Seg v={denied} total={total} color="var(--coral)" />
        </div>
        <div className="flex gap-3 mt-1 text-[9px] mono">
          <span style={{ color: "var(--accent)" }}>● shared {shared}</span>
          <span style={{ color: "var(--amber)" }}>● redacted {redacted}</span>
          <span style={{ color: "var(--coral)" }}>● withheld {denied}</span>
        </div>
      </div>
    </div>
  );
}

function Seg({ v, total, color }: { v: number; total: number; color: string }) {
  return <div style={{ width: `${(v / total) * 100}%`, background: color, transition: "width 0.45s ease", boxShadow: `0 0 8px ${color}88` }} />;
}
