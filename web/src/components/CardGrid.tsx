import { memo } from "react";
import { Lock } from "lucide-react";
import type { AgentNode } from "../types";
import { LEVEL_LABEL, deptColor } from "../theme";
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
    <div className="h-full overflow-y-auto p-3">
      <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))" }}>
        {nodes
          .slice()
          .sort((a, b) => b.level - a.level || a.department.localeCompare(b.department))
          .map((n) => (
            <Card key={n.id} node={n} status={statusMap[n.id] ?? n.status} onClick={() => selectAgent(n.id)} />
          ))}
      </div>
    </div>
  );
}

const Card = memo(function Card({ node, status, onClick }: { node: AgentNode; status: string; onClick: () => void }) {
  const color = deptColor(node.department);
  return (
    <button
      onClick={onClick}
      className="glass-flat rounded-lg text-left overflow-hidden transition-all hover:-translate-y-0.5 group"
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
          <span className="mono text-[9px] px-1.5 py-0.5 rounded-md" style={{ color, background: `${color}18`, border: `1px solid ${color}33` }}>
            {LEVEL_LABEL[node.level]}
          </span>
          <div className="flex items-center gap-1.5">
            <span className="flex gap-0.5" title={`Clearance L${node.clearance}`}>
              {[1, 2, 3, 4, 5].map((i) => (
                <span key={i} className="w-1 h-2.5 rounded-[1px]" style={{ background: i <= node.clearance ? "var(--accent)" : "rgba(255,255,255,0.1)", boxShadow: i <= node.clearance ? "0 0 5px var(--accent-glow)" : "none" }} />
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
