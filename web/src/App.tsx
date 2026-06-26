import { MessagesSquare, Network, LayoutGrid, Boxes, History, Radio, Building2, ChevronDown } from "lucide-react";
import { TopBar } from "./components/TopBar";
import { TeamsPanel } from "./components/TeamsPanel";
import { ConversationTimeline } from "./components/ConversationTimeline";
import { HistoryView } from "./components/HistoryView";
import { CommsGraph } from "./components/CommsGraph";
import { NetworkPanel } from "./components/NetworkPanel";
import { CardGrid } from "./components/CardGrid";
import { ProjectsWorkspace } from "./components/ProjectsWorkspace";
import { MetricsStrip } from "./components/MetricsStrip";
import { RightRail } from "./components/RightRail";
import { ConversationDrawer, AgentCardDrawer } from "./components/Drawers";
import { GateBanner } from "./components/GateBanner";
import { Brackets } from "./components/ui";
import { useStore } from "./store";

const TABS = [
  { id: "convo", label: "Conversation", icon: MessagesSquare },
  { id: "history", label: "History", icon: History },
  { id: "members", label: "Network", icon: Radio },
  { id: "comms", label: "Comms", icon: Network },
  { id: "roster", label: "Roster", icon: LayoutGrid },
  { id: "projects", label: "Projects", icon: Boxes },
] as const;

/** Federation org switcher — replaces the old Federation tab. Picking an org scopes the left
 *  Teams panel, Network, Roster, Projects, and the top chat-bar dispatch to that sealed org. */
function OrgSwitcher() {
  const orgs = useStore((s) => s.orgs);
  const selectedOrg = useStore((s) => s.selectedOrg);
  const selectOrg = useStore((s) => s.selectOrg);
  if (orgs.length < 2) return null;
  return (
    <label className="ml-auto flex items-center gap-1.5 mr-1 cursor-pointer" title="Switch organisation (federation)">
      <Building2 size={13} strokeWidth={2.3} style={{ color: "var(--accent)" }} />
      <span className="eyebrow">ORG</span>
      <span className="relative inline-flex items-center">
        <select
          value={selectedOrg ?? ""}
          onChange={(e) => void selectOrg(e.target.value)}
          className="appearance-none h-7 pl-2 pr-6 rounded-md text-[12px] font-semibold mono bg-transparent border cursor-pointer"
          style={{ borderColor: "var(--accent)", color: "var(--accent)" }}
        >
          {orgs.map((o) => (
            <option key={o.org_id} value={o.org_id} style={{ color: "#181c22" }}>
              {o.org_name}{o.primary ? " (primary)" : ""}
            </option>
          ))}
        </select>
        <ChevronDown size={13} className="absolute right-1.5 pointer-events-none" style={{ color: "var(--accent)" }} />
      </span>
    </label>
  );
}

function CenterStage() {
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
  const org = useStore((s) => s.org);
  const multiOrg = useStore((s) => s.orgs.length > 1);
  const tabs = TABS;

  return (
    <section className="panel rounded-lg relative h-full min-h-0 min-w-0 flex flex-col overflow-hidden">
      <Brackets color="var(--accent)" />
      {/* tab strip */}
      <div className="flex items-center gap-1 px-2.5 h-11 shrink-0 border-b" style={{ borderColor: "var(--border)" }}>
        {tabs.map((t) => {
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
        {multiOrg ? (
          <OrgSwitcher />
        ) : (
          <span className="ml-auto eyebrow pr-1">{view === "convo" ? "live agent-to-agent" : view === "history" ? "completed goals" : view === "members" ? "authenticated membership" : view === "comms" ? "comms topology" : view === "projects" ? "cross-team workspace" : "100 agents"}</span>
        )}
      </div>

      <div className="flex-1 min-h-0 relative">
        {view === "convo" && <ConversationTimeline />}
        {view === "history" && <HistoryView />}
        {view === "members" && <NetworkPanel />}
        {view === "comms" && <CommsGraph />}
        {view === "roster" && <CardGrid />}
        {view === "projects" && <ProjectsWorkspace />}
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
        style={{ gridTemplateColumns: "250px 1fr 360px", gridTemplateRows: "minmax(0, 1fr)" }}
      >
        <div className="animate-rise min-h-0 overflow-hidden" style={{ animationDelay: "60ms" }}>
          <TeamsPanel />
        </div>
        <div className="animate-rise min-h-0 min-w-0 overflow-hidden" style={{ animationDelay: "120ms" }}>
          <CenterStage />
        </div>
        <div className="animate-rise min-h-0 overflow-hidden" style={{ animationDelay: "180ms" }}>
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
