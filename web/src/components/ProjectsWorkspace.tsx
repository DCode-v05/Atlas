import { useEffect, useState } from "react";
import { Boxes, Users2, Lock, MessagesSquare, UsersRound } from "lucide-react";
import { api } from "../api";
import { useStore } from "../store";
import { deptColor, DEPARTMENT_LABEL } from "../theme";
import { SensitivityShield, StatusDot } from "./ui";
import type { ProjectSummary, ProjectView } from "../types";

/**
 * Projects Workspace — a project-centric lens on the org. Purely additive and
 * read-only: it reads /api/projects + /api/projects/{id}. Nothing in the live
 * flow is touched.
 */
export function ProjectsWorkspace() {
  const [list, setList] = useState<ProjectSummary[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [view, setView] = useState<ProjectView | null>(null);
  const selectAgent = useStore((s) => s.selectAgent);

  useEffect(() => {
    api.projects().then((r) => {
      setList(r.projects);
      if (r.projects.length && !active) setActive(r.projects[0].project_id);
    }).catch(console.error);
  }, []);

  useEffect(() => {
    if (!active) return;
    setView(null);
    api.project(active).then(setView).catch(console.error);
  }, [active]);

  return (
    <div className="absolute inset-0 flex min-h-0">
      {/* project rail */}
      <div className="w-[200px] shrink-0 border-r overflow-y-auto p-2.5 flex flex-col gap-1.5" style={{ borderColor: "var(--border)" }}>
        <div className="eyebrow px-1 pb-1">Projects</div>
        {list.map((p) => {
          const on = p.project_id === active;
          return (
            <button
              key={p.project_id}
              onClick={() => setActive(p.project_id)}
              className="text-left rounded-md px-2.5 py-2 transition-all"
              style={{
                background: on ? "var(--accent)" : "var(--surface)",
                color: on ? "#fff" : "var(--ink)",
                border: `1px solid ${on ? "var(--accent)" : "var(--border)"}`,
              }}
            >
              <div className="flex items-center gap-1.5">
                <Boxes size={13} strokeWidth={2.2} />
                <span className="text-[12px] font-bold mono">{p.project_id}</span>
              </div>
              <div className="text-[10px] mt-1 opacity-80">
                {p.members} people · {p.departments} depts · {p.secrets} secrets
              </div>
            </button>
          );
        })}
      </div>

      {/* detail */}
      <div className="flex-1 min-w-0 overflow-y-auto p-4">
        {!view ? (
          <div className="h-full grid place-items-center text-faint mono text-[11px]">loading project…</div>
        ) : (
          <div className="flex flex-col gap-4">
            {/* header + stats */}
            <div>
              <div className="font-display text-[20px] font-bold text-ink leading-tight mono">{view.project_id}</div>
              <div className="flex flex-wrap gap-2 mt-2">
                <Stat icon={<Users2 size={12} />} label="members" value={view.stats.members} />
                <Stat icon={<UsersRound size={12} />} label="departments" value={view.stats.departments} />
                <Stat icon={<Lock size={12} />} label="secrets" value={view.stats.secrets} />
                <Stat icon={<MessagesSquare size={12} />} label="live convos" value={view.stats.active_conversations} />
              </div>
            </div>

            {/* department breakdown */}
            <Section label="Cross-department team">
              <div className="flex flex-wrap gap-1.5">
                {view.departments.map((d) => (
                  <span key={d.department} className="flex items-center gap-1.5 rounded-sm px-2 py-1 text-[10px]"
                    style={{ background: "var(--inset)", border: `1px solid ${deptColor(d.department)}55` }}>
                    <span className="w-2 h-2 rounded-full" style={{ background: deptColor(d.department) }} />
                    <span className="text-ink">{DEPARTMENT_LABEL[d.department] ?? d.department}</span>
                    <span className="mono text-faint">{d.count}</span>
                  </span>
                ))}
              </div>
            </Section>

            {/* members */}
            <Section label={`Members (${view.members.length})`}>
              <div className="grid gap-1" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))" }}>
                {view.members.map((m) => (
                  <button key={m.agent_id} onClick={() => selectAgent(m.agent_id)}
                    className="flex items-center gap-2 rounded-sm px-2 py-1.5 text-left transition-colors hover:brightness-110"
                    style={{ background: "var(--inset)" }}>
                    <span className="w-1.5 h-6 rounded-full shrink-0" style={{ background: deptColor(m.department) }} />
                    <span className="min-w-0 flex-1">
                      <span className="text-[11px] text-ink truncate block">{m.name}</span>
                      <span className="text-[9.5px] text-muted truncate block">{m.role}</span>
                    </span>
                    <span className="mono text-[8.5px] text-faint shrink-0">{m.level_label} · L{m.clearance}</span>
                  </button>
                ))}
              </div>
            </Section>

            {/* secrets */}
            <Section label={`Project secrets (${view.secrets.length})`}>
              {view.secrets.length ? (
                <div className="flex flex-col gap-1.5">
                  {view.secrets.map((s) => (
                    <div key={s.item_id} className="flex items-center justify-between gap-2 rounded-sm px-2 py-1.5" style={{ background: "var(--inset)" }}>
                      <span className="flex items-center gap-1.5 min-w-0">
                        <Lock size={11} className="text-faint shrink-0" />
                        <span className="text-[11px] text-ink truncate">{s.title}</span>
                        <span className="text-[9.5px] text-faint shrink-0">· {s.owner_name}</span>
                      </span>
                      <SensitivityShield level={s.sensitivity} withLabel />
                    </div>
                  ))}
                </div>
              ) : <Empty>no project-scoped secrets</Empty>}
            </Section>

            {/* live coordination */}
            <Section label={`Coordination on this project (${view.conversations.threads.length + view.conversations.groups.length})`}>
              {view.conversations.groups.length === 0 && view.conversations.threads.length === 0 ? (
                <Empty>no coordination yet — run a prompt or the simulation</Empty>
              ) : (
                <div className="flex flex-col gap-1.5">
                  {view.conversations.groups.map((g) => (
                    <div key={g.group_id} className="rounded-sm px-2 py-1.5" style={{ background: "var(--inset)", borderLeft: "2px solid rgba(109,40,217,0.7)" }}>
                      <div className="flex items-center gap-2">
                        <span className="mono text-[8.5px] px-1 py-0.5 rounded-sm" style={{ background: "rgba(109,40,217,0.15)", color: "#a78bfa" }}>GROUP</span>
                        <span className="text-[11px] text-ink truncate">{g.topic || "coordination"}</span>
                        <StatusDot status={g.active ? "speaking" : "idle"} size={7} />
                      </div>
                      <div className="text-[9.5px] text-muted mt-0.5">
                        {g.initiator} · {g.members_in_project}/{g.members} in project · {g.messages} msgs
                      </div>
                    </div>
                  ))}
                  {view.conversations.threads.map((t) => (
                    <div key={t.thread_id} className="rounded-sm px-2 py-1.5" style={{ background: "var(--inset)", borderLeft: "2px solid var(--accent)" }}>
                      <div className="flex items-center gap-2">
                        <span className="mono text-[8.5px] px-1 py-0.5 rounded-sm" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>1:1</span>
                        <span className="text-[11px] text-ink truncate">{t.topic || "exchange"}</span>
                      </div>
                      <div className="text-[9.5px] text-muted mt-0.5">{t.participants.join(" ↔ ")} · {t.messages} msgs</div>
                    </div>
                  ))}
                </div>
              )}
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <span className="flex items-center gap-1.5 rounded-sm px-2 py-1" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
      <span className="text-accent">{icon}</span>
      <span className="mono text-[13px] font-bold text-ink tnum">{value}</span>
      <span className="text-[9.5px] text-faint uppercase tracking-wide">{label}</span>
    </span>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="eyebrow pb-1.5">{label}</div>
      {children}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="text-[10.5px] text-faint mono py-1">{children}</div>;
}
