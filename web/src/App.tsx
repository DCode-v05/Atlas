import { MessagesSquare, Network, LayoutGrid } from "lucide-react";
import { TopBar } from "./components/TopBar";
import { TeamsPanel } from "./components/TeamsPanel";
import { ConversationTimeline } from "./components/ConversationTimeline";
import { CommsGraph } from "./components/CommsGraph";
import { CardGrid } from "./components/CardGrid";
import { MetricsStrip } from "./components/MetricsStrip";
import { RightRail } from "./components/RightRail";
import { ConversationDrawer, AgentCardDrawer } from "./components/Drawers";
import { GateBanner } from "./components/GateBanner";
import { Brackets } from "./components/ui";
import { useStore } from "./store";

const TABS = [
  { id: "convo", label: "Conversation", icon: MessagesSquare },
  { id: "network", label: "Network", icon: Network },
  { id: "roster", label: "Roster", icon: LayoutGrid },
] as const;

function CenterStage() {
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
  const org = useStore((s) => s.org);

  return (
    <section className="panel rounded-lg relative min-h-0 min-w-0 flex flex-col overflow-hidden">
      <Brackets color="var(--accent)" />
      {/* tab strip */}
      <div className="flex items-center gap-1 px-2.5 h-11 shrink-0 border-b" style={{ borderColor: "var(--border)" }}>
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = view === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setView(t.id)}
              className="flex items-center gap-1.5 px-3 h-7 rounded-md text-[12px] font-semibold transition-all"
              style={{
                background: active ? "var(--accent)" : "transparent",
                color: active ? "#fff" : "var(--muted)",
                boxShadow: active ? "0 2px 8px -3px var(--accent-glow)" : "none",
              }}
            >
              <Icon size={14} strokeWidth={2.3} />
              {t.label}
            </button>
          );
        })}
        <span className="ml-auto eyebrow pr-1">{view === "convo" ? "live agent-to-agent" : view === "network" ? "comms topology" : "100 agents"}</span>
      </div>

      <div className="flex-1 min-h-0 relative">
        {view === "convo" && <ConversationTimeline />}
        {view === "network" && <CommsGraph />}
        {view === "roster" && <CardGrid />}
        <GateBanner />
        {!org && (
          <div className="absolute inset-0 grid place-items-center">
            <div className="flex flex-col items-center gap-3">
              <div className="w-7 h-7 animate-spin" style={{ border: "2px solid var(--accent-soft)", borderTopColor: "var(--accent)", borderRadius: "50%" }} />
              <div className="mono text-[10px] text-faint tracking-[0.18em] uppercase">connecting to atlas…</div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

export function App() {
  return (
    <div className="h-full w-full flex flex-col p-2.5 gap-2.5">
      <div className="animate-rise" style={{ animationDelay: "0ms" }}>
        <TopBar />
      </div>

      <div
        className="flex-1 grid gap-2.5 min-h-0"
        style={{ gridTemplateColumns: "250px 1fr 360px" }}
      >
        <div className="animate-rise min-h-0" style={{ animationDelay: "60ms" }}>
          <TeamsPanel />
        </div>
        <div className="animate-rise min-h-0 min-w-0" style={{ animationDelay: "120ms" }}>
          <CenterStage />
        </div>
        <div className="animate-rise min-h-0" style={{ animationDelay: "180ms" }}>
          <RightRail />
        </div>
      </div>

      <div className="animate-rise" style={{ animationDelay: "240ms" }}>
        <MetricsStrip />
      </div>

      <ConversationDrawer />
      <AgentCardDrawer />
    </div>
  );
}
