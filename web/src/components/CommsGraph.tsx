import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { CHROME, DEPARTMENT_LABEL, OUTCOME_META, STATUS_COLORS, deptColor, intentColor, nodeRadius } from "../theme";
import { useStore } from "../store";
import type { OrgView } from "../types";

function computeLayout(org: OrgView): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>();
  const entries = Object.entries(org.departments).filter(([d]) => d !== "exec");
  const R = 480;
  const centers: Record<string, [number, number]> = { exec: [0, 0] };
  entries.forEach(([d], i) => {
    const a = (i / entries.length) * 2 * Math.PI - Math.PI / 2;
    centers[d] = [Math.cos(a) * R, Math.sin(a) * R];
  });
  for (const [dept, ids] of Object.entries(org.departments)) {
    const [cx, cy] = centers[dept] ?? [0, 0];
    const n = ids.length;
    const cols = Math.max(1, Math.ceil(Math.sqrt(n)));
    const rows = Math.ceil(n / cols);
    const sp = 28;
    ids.forEach((id, idx) => {
      const c = idx % cols;
      const r = Math.floor(idx / cols);
      pos.set(id, { x: cx + (c - (cols - 1) / 2) * sp, y: cy + (r - (rows - 1) / 2) * sp });
    });
  }
  return pos;
}

function linkColor(l: any): string {
  if (l.outcome) return OUTCOME_META[l.outcome]?.color ?? CHROME.muted;
  return intentColor(l.intent) ?? CHROME.accent;
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

export function CommsGraph() {
  const org = useStore((s) => s.org);
  const liveLinks = useStore((s) => s.links);
  const statusMap = useStore((s) => s.status);
  const deptFilter = useStore((s) => s.deptFilter);
  const groups = useStore((s) => s.groups);
  const selectAgent = useStore((s) => s.selectAgent);

  const fgRef = useRef<any>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    if (!wrapRef.current) return;
    const ro = new ResizeObserver((e) => setSize({ w: e[0].contentRect.width, h: e[0].contentRect.height }));
    ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  const groupMembers = useMemo(() => {
    const s = new Set<string>();
    for (const g of Object.values(groups)) g.members.forEach((m) => s.add(m));
    return s;
  }, [groups]);

  const nodes = useMemo(() => {
    if (!org) return [];
    const pos = computeLayout(org);
    const arr: any[] = org.nodes.map((n) => {
      const p = pos.get(n.id)!;
      return { id: n.id, fx: p.x, fy: p.y, level: n.level, dept: n.department, name: n.name };
    });
    arr.push({ id: "operator", fx: 0, fy: -640, level: 6, dept: "operator", name: "Operator" });
    return arr;
  }, [org]);

  // centroid + top of each department cluster, for the team-name labels on the map
  const deptCentroids = useMemo(() => {
    const acc: Record<string, { sx: number; n: number; minY: number }> = {};
    for (const nd of nodes) {
      if (nd.id === "operator") continue;
      const a = acc[nd.dept] ?? (acc[nd.dept] = { sx: 0, n: 0, minY: Infinity });
      a.sx += nd.fx;
      a.n += 1;
      a.minY = Math.min(a.minY, nd.fy);
    }
    return Object.entries(acc).map(([dept, a]) => ({ dept, cx: a.sx / a.n, minY: a.minY, count: a.n }));
  }, [nodes]);

  const links = useMemo(
    () => liveLinks.map((l) => ({ source: l.source, target: l.target, intent: l.intent, outcome: l.outcome, mode: l.mode })),
    [liveLinks],
  );

  const data = useMemo(() => ({ nodes, links }), [nodes, links]);

  useEffect(() => {
    if (nodes.length && fgRef.current) {
      const t = setTimeout(() => fgRef.current?.zoomToFit(600, 80), 280);
      return () => clearTimeout(t);
    }
  }, [nodes.length, size.w, size.h]);

  if (!org) return <div ref={wrapRef} className="h-full w-full" />;

  return (
    <div ref={wrapRef} className="h-full w-full relative overflow-hidden">
      <div className="absolute top-3 left-3.5 z-10 pointer-events-none flex items-center gap-2">
        <span className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--accent)" }} />
        <span className="eyebrow">Live communication map</span>
        <span className="mono text-[9.5px] text-faint">· {org.node_count} agents · {liveLinks.length} active</span>
      </div>

      <ForceGraph2D
        ref={fgRef}
        width={size.w}
        height={size.h}
        graphData={data}
        backgroundColor="rgba(0,0,0,0)"
        cooldownTicks={0}
        warmupTicks={0}
        nodeRelSize={4}
        nodeId="id"
        onNodeHover={(n: any) => setHover(n?.id ?? null)}
        onNodeClick={(n: any) => n?.id !== "operator" && selectAgent(n.id)}
        linkColor={linkColor}
        linkWidth={(l: any) => (l.mode === "group" ? 2.4 : l.outcome === "hitl" ? 2.2 : 1.4)}
        linkDirectionalParticles={(l: any) => (l.outcome === "denied" ? 0 : 2)}
        linkDirectionalParticleWidth={(l: any) => (l.mode === "group" ? 3 : 2.2)}
        linkDirectionalParticleColor={linkColor}
        linkDirectionalParticleSpeed={0.011}
        nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D) => {
          const { x, y } = node;
          if (!Number.isFinite(x) || !Number.isFinite(y)) return;
          const isOp = node.id === "operator";
          const r = isOp ? 8 : nodeRadius(node.level);
          const status = isOp ? "idle" : statusMap[node.id] ?? "idle";
          const base = isOp ? CHROME.accent : deptColor(node.dept);
          const dim = deptFilter && !isOp && node.dept !== deptFilter ? 0.16 : 1;
          ctx.globalAlpha = dim;

          if (status !== "idle") {
            const sc = STATUS_COLORS[status];
            ctx.beginPath();
            ctx.arc(x, y, r + 3.5, 0, 2 * Math.PI);
            ctx.strokeStyle = sc;
            ctx.globalAlpha = dim * 0.9;
            ctx.lineWidth = 1.6;
            ctx.stroke();
            ctx.globalAlpha = dim;
          }
          if (!isOp && groupMembers.has(node.id)) {
            ctx.beginPath();
            ctx.arc(x, y, r + 6, 0, 2 * Math.PI);
            ctx.strokeStyle = "rgba(109,40,217,0.6)";
            ctx.lineWidth = 1.2;
            ctx.stroke();
          }
          if (isOp) {
            ctx.beginPath();
            ctx.moveTo(x, y - r);
            ctx.lineTo(x + r, y);
            ctx.lineTo(x, y + r);
            ctx.lineTo(x - r, y);
            ctx.closePath();
          } else {
            ctx.beginPath();
            ctx.arc(x, y, r, 0, 2 * Math.PI);
          }
          const grad = ctx.createRadialGradient(x - r * 0.35, y - r * 0.35, 0, x, y, r);
          grad.addColorStop(0, lighten(base));
          grad.addColorStop(1, base);
          ctx.fillStyle = grad;
          ctx.fill();
          ctx.strokeStyle = "rgba(255,255,255,0.85)";
          ctx.lineWidth = node.level >= 4 || isOp ? 1.4 : 0.8;
          ctx.stroke();
          ctx.globalAlpha = 1;
        }}
        nodePointerAreaPaint={(node: any, color: string, ctx: CanvasRenderingContext2D) => {
          if (!Number.isFinite(node.x)) return;
          const r = (node.id === "operator" ? 8 : nodeRadius(node.level)) + 3;
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
          ctx.fill();
        }}
        onRenderFramePost={(ctx: CanvasRenderingContext2D, scale: number) => {
          // 1) team / department name on each cluster (a colored pill above it)
          const dfpx = Math.max(10, 13 / scale);
          ctx.font = `700 ${dfpx}px "JetBrains Mono", monospace`;
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          for (const ce of deptCentroids) {
            if (!Number.isFinite(ce.cx) || !Number.isFinite(ce.minY)) continue;
            const label = `${(DEPARTMENT_LABEL[ce.dept] ?? ce.dept).toUpperCase()} · ${ce.count}`;
            const w = ctx.measureText(label).width;
            const pad = 5;
            const boxH = dfpx + 7;
            const py = ce.minY - 16;
            const c = deptColor(ce.dept);
            ctx.globalAlpha = deptFilter && deptFilter !== ce.dept ? 0.3 : 1;
            ctx.fillStyle = c;
            roundRect(ctx, ce.cx - w / 2 - pad, py - boxH / 2, w + pad * 2, boxH, 3);
            ctx.fill();
            ctx.fillStyle = "#fff";
            ctx.fillText(label, ce.cx, py);
            ctx.globalAlpha = 1;
          }

          // 2) operator + hovered agent name (white pill, dark text)
          const fpx = Math.max(8.5, 11 / scale);
          ctx.font = `600 ${fpx}px "JetBrains Mono", monospace`;
          ctx.textBaseline = "top";
          for (const n of nodes) {
            if (n.id !== "operator" && n.id !== hover) continue;
            if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) continue;
            const r = n.id === "operator" ? 8 : nodeRadius(n.level);
            const w = ctx.measureText(n.name).width;
            const cx = n.x;
            const ty = n.y + r + 3.5;
            const pad = 3.5;
            ctx.fillStyle = "rgba(255,255,255,0.95)";
            roundRect(ctx, cx - w / 2 - pad, ty - 1.5, w + pad * 2, fpx + 3, 2);
            ctx.fill();
            ctx.strokeStyle = "rgba(30,41,53,0.22)";
            ctx.lineWidth = 0.6;
            ctx.stroke();
            ctx.fillStyle = "#181c22";
            ctx.fillText(n.name, cx, ty);
          }
        }}
      />
    </div>
  );
}

function lighten(hex: string): string {
  const h = hex.replace("#", "");
  if (h.length !== 6) return hex;
  const n = parseInt(h, 16);
  return `rgb(${Math.min(255, ((n >> 16) & 255) + 55)},${Math.min(255, ((n >> 8) & 255) + 55)},${Math.min(255, (n & 255) + 55)})`;
}
