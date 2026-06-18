import { TopBar } from "./components/TopBar";
import { LeftRail } from "./components/LeftRail";
import { CommsGraph } from "./components/CommsGraph";
import { CardGrid } from "./components/CardGrid";
import { MetricsStrip } from "./components/MetricsStrip";
import { RightRail } from "./components/RightRail";
import { ConversationDrawer, AgentCardDrawer } from "./components/Drawers";
import { GateBanner } from "./components/GateBanner";
import { useStore } from "./store";

export function App() {
  const view = useStore((s) => s.view);
  const org = useStore((s) => s.org);

  return (
    <div className="h-full w-full p-2.5 relative" style={{ zIndex: 2 }}>
      <div
        className="h-full grid gap-2.5"
        style={{
          gridTemplateRows: "58px 1fr 96px",
          gridTemplateColumns: "238px 1fr 356px",
        }}
      >
        <div style={{ gridColumn: "1 / 4", animationDelay: "0ms" }} className="animate-rise">
          <TopBar />
        </div>

        <div style={{ gridColumn: "1 / 2", gridRow: "2 / 3", animationDelay: "60ms" }} className="animate-rise min-h-0">
          <LeftRail />
        </div>

        <div
          style={{ gridColumn: "2 / 3", gridRow: "2 / 3", animationDelay: "120ms" }}
          className="animate-rise relative min-h-0 min-w-0 glass rounded-xl overflow-hidden"
        >
          {view === "cards" ? <CardGrid /> : <CommsGraph />}
          <GateBanner />
          {!org && (
            <div className="absolute inset-0 grid place-items-center">
              <div className="flex flex-col items-center gap-3">
                <div className="w-8 h-8 rounded-full animate-spin" style={{ border: "2px solid rgba(110,231,199,0.25)", borderTopColor: "var(--accent)" }} />
                <div className="mono text-[11px] text-faint tracking-wide">linking to atlas observatory…</div>
              </div>
            </div>
          )}
        </div>

        <div style={{ gridColumn: "3 / 4", gridRow: "2 / 3", animationDelay: "180ms" }} className="animate-rise min-h-0">
          <RightRail />
        </div>

        <div style={{ gridColumn: "1 / 4", gridRow: "3 / 4", animationDelay: "240ms" }} className="animate-rise min-w-0">
          <MetricsStrip />
        </div>
      </div>

      <ConversationDrawer />
      <AgentCardDrawer />
    </div>
  );
}
