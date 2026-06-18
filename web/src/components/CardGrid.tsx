import { memo } from "react";
import { Lock } from "lucide-react";
import type { AgentNode } from "../types";
import { DEPARTMENT_LABEL, LEVEL_LABEL, deptColor } from "../theme";
import { useStore } from "../store";
import { StatusDot } from "./ui";

export function CardGrid() {
  const org = useStore((s) => s.org);
  const statusMap = useStore((s) => s.status);
  const deptFilter = useStore((s) => s.deptFilter);
  const selectAgent = useStore((s) => s.selectAgent);

  if (!org) return null;
  const nodes = org.nodes.filter((n) => !deptFilter || n.department === deptFilter);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-3.5 h-9 shrink-0 border-b" style={{ borderColor: "var(--border)" }}>
        <span className="w-1.5 h-1.5" style={{ background: "var(--accent)", boxShadow: "0 0 8px var(--accent)" }} />
        <span className="eyebrow" style={{ color: "var(--text-2)" }}>Agent Roster</span>
        <span className="mono text-[9.5px] text-faint">
          · {nodes.length} {deptFilter ? `in ${DEPARTMENT_LABEL[deptFilter] ?? deptFilter}` : "agents"}
        </span>
        <span className="ml-auto mono text-[9px] text-faint">click a card → A2A agent card</span>
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(188px, 1fr))" }}>
          {nodes
            .slice()
            .sort((a, b) => b.level - a.level || a.department.localeCompare(b.department))
            .map((n) => (
              <Card key={n.id} node={n} status={statusMap[n.id] ?? n.status} onClick={() => selectAgent(n.id)} />
            ))}
        </div>
      </div>
    </div>
  );
}

const Card = memo(function Card({ node, status, onClick }: { node: AgentNode; status: string; onClick: () => void }) {
  const color = deptColor(node.department);
  return (
    <button
      onClick={onClick}
      className="panel-flat rounded-sm text-left overflow-hidden transition-all hover:-translate-y-0.5 group relative"
      style={{ boxShadow: "0 8px 24px -18px rgba(0,0,0,0.8)" }}
    >
      <div className="h-[3px]" style={{ background: `linear-gradient(90deg, ${color}, transparent)`, boxShadow: `0 0 10px ${color}88` }} />
      <div className="p-2.5">
        <div className="flex items-start justify-between gap-1.5">
          <div className="min-w-0">
            <div className="text-[12px] font-semibold text-ink truncate">{node.name}</div>
            <div className="text-[10.5px] text-muted truncate">{node.role}</div>
          </div>
          <StatusDot status={status} />
        </div>
        <div className="flex items-center justify-between mt-2.5">
          <span className="mono text-[9px] px-1.5 py-0.5 rounded-sm uppercase tracking-wide" style={{ color, background: `${color}18`, border: `1px solid ${color}33` }}>
            {LEVEL_LABEL[node.level]}
          </span>
          <div className="flex items-center gap-1.5">
            <span className="flex gap-0.5" title={`Clearance L${node.clearance}`}>
              {[1, 2, 3, 4, 5].map((i) => (
                <span key={i} className="w-1 h-2.5 rounded-[1px]" style={{ background: i <= node.clearance ? "var(--accent)" : "rgba(30,41,53,0.12)" }} />
              ))}
            </span>
            {node.owns_sensitive > 0 && (
              <span className="flex items-center gap-0.5 mono text-[9px]" style={{ color: "var(--amber)" }} title={`${node.owns_sensitive} sensitive items`}>
                <Lock size={10} />{node.owns_sensitive}
              </span>
            )}
          </div>
        </div>
        <div className="mono text-[8px] text-faint mt-1.5 truncate">{node.id} · {node.department}</div>
      </div>
    </button>
  );
});
