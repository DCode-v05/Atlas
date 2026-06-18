import { useState } from "react";
import { ChevronDown, Users } from "lucide-react";
import { DEPARTMENT_COLORS, DEPARTMENT_LABEL, teamLabel } from "../theme";
import { useStore } from "../store";
import { Brackets, SectionHead } from "./ui";

export function TeamsPanel() {
  const org = useStore((s) => s.org);
  const statusMap = useStore((s) => s.status);
  const deptFilter = useStore((s) => s.deptFilter);
  const setDeptFilter = useStore((s) => s.setDeptFilter);
  const selectAgent = useStore((s) => s.selectAgent);
  const agents = useStore((s) => s.agents);
  const [open, setOpen] = useState<string | null>(null);

  if (!org) return <aside className="h-full panel rounded-lg" />;

  const depts = Object.entries(org.departments).sort((a, b) => b[1].length - a[1].length);
  const activeIn = (ids: string[]) => ids.filter((id) => (statusMap[id] ?? "idle") !== "idle").length;
  const teamsOf = (dept: string) =>
    Object.entries(org.teams)
      .filter(([tid]) => tid.startsWith(`${dept}-team-`))
      .sort((a, b) => a[0].localeCompare(b[0], undefined, { numeric: true }));

  return (
    <aside className="h-full panel rounded-lg flex flex-col overflow-hidden">
      <Brackets />
      <SectionHead idx="01" right={<span className="mono text-[9.5px] text-faint">{org.node_count} agents</span>}>
        Org · Teams
      </SectionHead>

      <div className="flex-1 overflow-y-auto px-2 pb-2 min-h-0">
        {depts.map(([dept, ids]) => {
          const c = DEPARTMENT_COLORS[dept] ?? "var(--muted)";
          const isOpen = open === dept;
          const filtered = deptFilter === dept;
          const active = activeIn(ids);
          return (
            <div key={dept} className="mb-0.5">
              <button
                onClick={() => {
                  setOpen(isOpen ? null : dept);
                  setDeptFilter(filtered ? null : dept);
                }}
                className="w-full flex items-center gap-2 px-2 h-9 rounded-md transition-colors text-left"
                style={{ background: filtered ? "var(--inset)" : "transparent", boxShadow: filtered ? `inset 2px 0 0 ${c}` : "none" }}
              >
                <span className="w-2.5 h-2.5 rounded-[3px] shrink-0" style={{ background: c }} />
                <span className="flex-1 min-w-0 text-[12px] font-semibold truncate" style={{ color: "var(--text)" }}>
                  {DEPARTMENT_LABEL[dept] ?? dept}
                </span>
                {active > 0 && (
                  <span className="flex items-center gap-1 mono text-[9px]" style={{ color: "var(--ok)" }} title={`${active} active now`}>
                    <span className="w-1.5 h-1.5 rounded-full animate-flicker" style={{ background: "var(--ok)" }} />
                    {active}
                  </span>
                )}
                <span className="mono text-[10px] tnum text-faint w-5 text-right">{ids.length}</span>
                <ChevronDown size={13} className="text-faint transition-transform shrink-0" style={{ transform: isOpen ? "none" : "rotate(-90deg)" }} />
              </button>

              {isOpen && (
                <div className="pl-3.5 pr-1 pb-1.5 flex flex-col gap-1 animate-msg">
                  {teamsOf(dept).map(([tid, members]) => {
                    const lead = agents[members[0]];
                    const liveT = activeIn(members);
                    return (
                      <div key={tid} className="rounded-md px-2 py-1.5" style={{ background: "var(--inset)", border: "1px solid var(--border)" }}>
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[11px] font-semibold truncate" style={{ color: "var(--text-2)" }}>{teamLabel(tid)}</span>
                          <span className="flex items-center gap-0.5 mono text-[9px] text-faint shrink-0"><Users size={10} /> {members.length}</span>
                        </div>
                        {lead && (
                          <button
                            onClick={() => selectAgent(lead.id)}
                            className="mt-0.5 text-[10px] text-muted hover:text-accent truncate block max-w-full text-left"
                            title={`Lead: ${lead.name}`}
                          >
                            lead · {lead.name}
                          </button>
                        )}
                        {liveT > 0 && <span className="mono text-[8.5px]" style={{ color: "var(--ok)" }}>{liveT} active</span>}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="px-3 py-2 border-t shrink-0 flex items-center justify-between" style={{ borderColor: "var(--border)" }}>
        <span className="eyebrow text-[8.5px]">click a team → filter map</span>
        {deptFilter && (
          <button onClick={() => setDeptFilter(null)} className="mono text-[9px] text-accent hover:underline">clear</button>
        )}
      </div>
    </aside>
  );
}
