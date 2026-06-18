import { ShieldX, X } from "lucide-react";
import { useStore } from "../store";
import { Brackets } from "./ui";

export function GateBanner() {
  const gate = useStore((s) => s.gate);
  if (!gate) return null;
  return (
    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 w-[min(560px,92%)] animate-slide-in">
      <div className="relative panel rounded px-3.5 py-3 flex items-start gap-3" style={{ borderColor: "var(--coral)", boxShadow: "0 0 30px -8px rgba(255,77,94,0.55)" }}>
        <Brackets color="var(--coral)" />
        <div className="grid place-items-center w-9 h-9 rounded-sm shrink-0" style={{ background: "rgba(255,77,94,0.14)", border: "1px solid rgba(255,77,94,0.32)" }}>
          <ShieldX size={18} color="var(--coral)" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[12px] font-semibold mb-0.5 mono uppercase tracking-wide" style={{ color: "var(--coral)" }}>Out of scope · blocked at the gate</div>
          <div className="text-[11px] text-muted mb-1 mono truncate">“{gate.prompt}”</div>
          <div className="text-[11px] text-muted leading-snug">{gate.reason}</div>
        </div>
        <button onClick={() => useStore.setState({ gate: null })} className="text-faint hover:text-ink shrink-0"><X size={15} /></button>
      </div>
    </div>
  );
}
