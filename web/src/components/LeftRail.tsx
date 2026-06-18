import { Grid3x3, Network, Share2 } from "lucide-react";
import {
  DEPARTMENT_COLORS,
  DEPARTMENT_LABEL,
  INTENT_META,
  OUTCOME_META,
  SENSITIVITY_META,
  STATUS_COLORS,
  STATUS_LABEL,
} from "../theme";
import { useStore } from "../store";
import { Eyebrow } from "./ui";

const VIEWS = [
  { id: "comms", label: "Comms Map", icon: Share2 },
  { id: "hierarchy", label: "Org Chart", icon: Network },
  { id: "cards", label: "Agent Cards", icon: Grid3x3 },
] as const;

export function LeftRail() {
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
  const org = useStore((s) => s.org);
  const deptFilter = useStore((s) => s.deptFilter);
  const setDeptFilter = useStore((s) => s.setDeptFilter);

  const depts = org ? Object.entries(org.departments).sort((a, b) => b[1].length - a[1].length) : [];
  const maxDept = depts.reduce((m, [, ids]) => Math.max(m, ids.length), 1);

  return (
    <aside className="h-full glass rounded-xl flex flex-col overflow-hidden">
      {/* view switch — segmented */}
      <div className="p-2.5">
        <div className="inset rounded-lg p-1 flex flex-col gap-1">
          {VIEWS.map((v) => {
            const Icon = v.icon;
            const active = view === v.id;
            return (
              <button
                key={v.id}
                onClick={() => setView(v.id)}
                className="flex items-center gap-2.5 px-2.5 h-8 rounded-md text-[12px] font-semibold transition-all"
                style={{
                  background: active ? "linear-gradient(180deg, rgba(110,231,199,0.16), rgba(110,231,199,0.06))" : "transparent",
                  color: active ? "var(--accent-bright)" : "var(--muted)",
                  boxShadow: active ? "inset 0 0 0 1px var(--accent-soft), 0 0 14px -8px var(--accent-glow)" : "none",
                }}
              >
                <Icon size={14} strokeWidth={2.2} />
                {v.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        {/* departments with bars */}
        <Eyebrow right={deptFilter && <button className="text-[10px] text-accent hover:text-accent-bright" onClick={() => setDeptFilter(null)}>clear</button>}>
          Departments
        </Eyebrow>
        <div className="px-2.5 pb-2 flex flex-col gap-1">
          {depts.map(([dept, ids]) => {
            const active = deptFilter === dept;
            const c = DEPARTMENT_COLORS[dept];
            return (
              <button
                key={dept}
                onClick={() => setDeptFilter(active ? null : dept)}
                className="group flex items-center gap-2 px-2 h-7 rounded-md transition-colors"
                style={{ background: active ? "rgba(255,255,255,0.04)" : "transparent" }}
              >
                <span className="w-2 h-2 rounded-[3px] shrink-0" style={{ background: c, boxShadow: active ? `0 0 8px ${c}` : `0 0 4px ${c}55` }} />
                <span className="flex-1 min-w-0 text-left text-[11px] truncate" style={{ color: active ? "var(--text)" : "var(--muted)" }}>
                  {DEPARTMENT_LABEL[dept] ?? dept}
                </span>
                <span className="h-1 rounded-full overflow-hidden w-9 shrink-0" style={{ background: "rgba(255,255,255,0.06)" }}>
                  <span className="block h-full rounded-full" style={{ width: `${(ids.length / maxDept) * 100}%`, background: c, opacity: active ? 1 : 0.6 }} />
                </span>
                <span className="mono text-[9.5px] tnum text-faint w-4 text-right">{ids.length}</span>
              </button>
            );
          })}
        </div>

        {/* legend */}
        <Eyebrow>Intent</Eyebrow>
        <div className="px-3.5 pb-2 grid grid-cols-2 gap-x-2 gap-y-1.5">
          {Object.entries(INTENT_META).map(([k, m]) => <LegendRow key={k} color={m.color} label={m.label} />)}
        </div>
        <Eyebrow>Context outcome</Eyebrow>
        <div className="px-3.5 pb-2 grid grid-cols-2 gap-x-2 gap-y-1.5">
          {["shared", "redacted", "denied", "hitl"].map((k) => (
            <LegendRow key={k} color={OUTCOME_META[k].color} label={OUTCOME_META[k].label} dashed={k === "redacted"} pulse={k === "hitl"} />
          ))}
        </div>
        <Eyebrow>Sensitivity</Eyebrow>
        <div className="px-3.5 pb-2 grid grid-cols-2 gap-x-2 gap-y-1.5">
          {Object.entries(SENSITIVITY_META).map(([k, m]) => <LegendRow key={k} color={m.color} label={m.label} />)}
        </div>
        <Eyebrow>Agent status</Eyebrow>
        <div className="px-3.5 pb-3 grid grid-cols-2 gap-x-2 gap-y-1.5">
          {Object.keys(STATUS_COLORS).map((k) => <LegendRow key={k} color={STATUS_COLORS[k]} label={STATUS_LABEL[k]} round />)}
        </div>
      </div>
    </aside>
  );
}

function LegendRow({ color, label, dashed, pulse, round }: { color: string; label: string; dashed?: boolean; pulse?: boolean; round?: boolean }) {
  return (
    <div className="flex items-center gap-1.5 text-[10px] min-w-0" style={{ color: "var(--muted)" }}>
      <span
        className="shrink-0"
        style={{
          width: round ? 7 : 13,
          height: round ? 7 : 0,
          borderRadius: round ? "50%" : 0,
          background: round ? color : "transparent",
          borderTop: round ? "none" : `2px ${dashed ? "dashed" : "solid"} ${color}`,
          boxShadow: pulse || round ? `0 0 6px ${color}` : "none",
        }}
      />
      <span className="truncate">{label}</span>
    </div>
  );
}
