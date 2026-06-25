import { useEffect } from "react";
import { ShieldX, X } from "lucide-react";
import { useStore } from "../store";
import { Brackets } from "./ui";

export function GateBanner() {
  const gate = useStore((s) => s.gate);
  const dismissGate = useStore((s) => s.dismissGate);

  // Dismiss on Esc, and auto-dismiss after a few seconds so the bar can never get stuck.
  useEffect(() => {
    if (!gate) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") dismissGate();
    };
    window.addEventListener("keydown", onKey);
    const t = window.setTimeout(dismissGate, 8000);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.clearTimeout(t);
    };
  }, [gate, dismissGate]);

  if (!gate) return null;
  // fixed + mx-auto centering (NOT -translate-x-1/2): slide-in animates `transform`, which would
  // override a translate-based center and push the bar off the panel's clipped right edge.
  return (
    <div className="fixed top-[70px] left-0 right-0 mx-auto z-50 w-[min(560px,90vw)] animate-slide-in">
      <div
        className="relative panel rounded pl-3.5 pr-2 py-3 flex items-start gap-3"
        style={{ borderColor: "var(--coral)", boxShadow: "0 0 30px -8px rgba(255,77,94,0.55)" }}
      >
        <Brackets color="var(--coral)" />
        <div
          className="grid place-items-center w-9 h-9 rounded-sm shrink-0"
          style={{ background: "rgba(255,77,94,0.14)", border: "1px solid rgba(255,77,94,0.32)" }}
        >
          <ShieldX size={18} color="var(--coral)" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[12px] font-semibold mb-0.5 mono uppercase tracking-wide" style={{ color: "var(--coral)" }}>
            Out of scope · blocked at the gate
          </div>
          <div className="text-[11px] text-muted mb-1 mono truncate">“{gate.prompt}”</div>
          <div className="text-[11px] text-muted leading-snug">{gate.reason}</div>
        </div>
        <button
          onClick={dismissGate}
          title="Dismiss (Esc)"
          aria-label="Dismiss"
          className="shrink-0 grid place-items-center w-7 h-7 rounded-sm text-faint transition-colors hover:text-ink"
          style={{ background: "rgba(255,77,94,0.10)" }}
        >
          <X size={16} strokeWidth={2.4} />
        </button>
      </div>
    </div>
  );
}
