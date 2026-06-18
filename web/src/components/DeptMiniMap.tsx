import { useMemo } from "react";
import { DEPARTMENT_LABEL, OUTCOME_META, deptColor, intentColor } from "../theme";
import { useStore } from "../store";

const CX = 150;
const CY = 148;
const R = 112;

export function DeptMiniMap() {
  const org = useStore((s) => s.org);
  const statusMap = useStore((s) => s.status);
  const links = useStore((s) => s.links);
  const agents = useStore((s) => s.agents);
  const deptFilter = useStore((s) => s.deptFilter);
  const setDeptFilter = useStore((s) => s.setDeptFilter);

  const depts = useMemo(
    () => (org ? Object.entries(org.departments).sort((a, b) => b[1].length - a[1].length) : []),
    [org],
  );

  const pos = useMemo(() => {
    const m: Record<string, { x: number; y: number }> = { operator: { x: CX, y: CY } };
    const ring = depts;
    ring.forEach(([dept], i) => {
      const a = (i / ring.length) * 2 * Math.PI - Math.PI / 2;
      m[dept] = { x: CX + Math.cos(a) * R, y: CY + Math.sin(a) * R };
    });
    return m;
  }, [depts]);

  if (!org) return <div className="h-full" />;

  const deptOf = (id: string) => (id === "operator" ? "operator" : agents[id]?.department ?? null);
  const activeIn = (ids: string[]) => ids.filter((id) => (statusMap[id] ?? "idle") !== "idle").length;
  const maxCount = Math.max(1, ...depts.map(([, ids]) => ids.length));
  const rOf = (n: number) => 9 + Math.sqrt(n / maxCount) * 16;

  // aggregate live agent→agent links to department pairs
  const deptLinks = new Map<string, { a: string; b: string; color: string }>();
  for (const l of links) {
    const da = deptOf(l.source);
    const db = deptOf(l.target);
    if (!da || !db || da === db || !pos[da] || !pos[db]) continue;
    const key = [da, db].sort().join("|");
    const color = l.outcome ? OUTCOME_META[l.outcome]?.color ?? "#5c6675" : intentColor(l.intent ?? undefined);
    deptLinks.set(key, { a: da, b: db, color });
  }

  return (
    <div className="px-2 pt-1 pb-2">
      <svg viewBox="0 0 300 300" className="w-full" style={{ maxHeight: 230 }}>
        {/* links */}
        {[...deptLinks.values()].map((dl, i) => {
          const pa = pos[dl.a];
          const pb = pos[dl.b];
          return <line key={i} x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke={dl.color} strokeWidth={1.6} opacity={0.55} />;
        })}

        {/* operator hub */}
        <circle cx={CX} cy={CY} r={9} fill="var(--accent)" />
        <text x={CX} y={CY + 20} textAnchor="middle" className="mono" fontSize="8" fill="var(--muted)">Operator</text>

        {/* department bubbles */}
        {depts.map(([dept, ids]) => {
          const p = pos[dept];
          const c = deptColor(dept);
          const active = activeIn(ids);
          const dim = deptFilter && deptFilter !== dept ? 0.32 : 1;
          const r = rOf(ids.length);
          return (
            <g key={dept} style={{ cursor: "pointer", opacity: dim }} onClick={() => setDeptFilter(deptFilter === dept ? null : dept)}>
              {active > 0 && <circle cx={p.x} cy={p.y} r={r + 5} fill="none" stroke={c} strokeWidth={1.5} opacity={0.5} className="animate-flicker" />}
              <circle cx={p.x} cy={p.y} r={r} fill={c} opacity={0.9} stroke="#fff" strokeWidth={1.5} />
              <text x={p.x} y={p.y + 3} textAnchor="middle" fontSize="9" fontWeight="700" fill="#fff" className="mono">{ids.length}</text>
              <text x={p.x} y={p.y + r + 9} textAnchor="middle" fontSize="7.5" fill="var(--text-2)" className="mono">
                {(DEPARTMENT_LABEL[dept] ?? dept).split(" ")[0]}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
