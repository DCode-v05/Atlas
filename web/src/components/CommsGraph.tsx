import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { CHROME, OUTCOME_META, STATUS_COLORS, deptColor, intentColor, nodeRadius } from "../theme";
import { useStore } from "../store";
import type { OrgView } from "../types";

function computeLayout(org: OrgView): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>();
  const entries = Object.entries(org.departments).filter(([d]) => d !== "exec");
  const R = 480; // ring radius — wider so clusters don't crowd
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
  if (l.kind === "report") return "rgba(150,180,210,0.13)";
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
  const view = useStore((s) => s.view);
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

  const links = useMemo(() => {
    if (!org) return [];
    if (view === "hierarchy") return org.reporting_edges.map((e) => ({ source: e.source, target: e.target, kind: "report" }));
    return liveLinks.map((l) => ({ source: l.source, target: l.target, intent: l.intent, outcome: l.outcome, mode: l.mode }));
  }, [org, view, liveLinks]);

  const data = useMemo(() => ({ nodes, links }), [nodes, links]);

  useEffect(() => {
    if (nodes.length && fgRef.current) {
      const t = setTimeout(() => fgRef.current?.zoomToFit(600, 90), 280);
      return () => clearTimeout(t);
    }
  }, [nodes.length]);

  if (!org) return <div ref={wrapRef} className="h-full w-full" />;

  return (
    <div ref={wrapRef} className="h-full w-full relative overflow-hidden">
      <div className="absolute inset-0 pointer-events-none" style={{ background: "radial-gradient(60% 55% at 50% 42%, rgba(110,231,199,0.05), transparent 70%)" }} />
      <div className="absolute top-3.5 left-3.5 z-10 pointer-events-none flex items-center gap-2">
        <span className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--accent)", boxShadow: "0 0 8px var(--accent)" }} />
        <span className="eyebrow" style={{ color: "var(--text-2)" }}>{view === "hierarchy" ? "Reporting Hierarchy" : "Live Communication Map"}</span>
        <span className="mono text-[9.5px] text-faint">· {org.node_count} agents</span>
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
        linkWidth={(l: any) => (l.kind === "report" ? 0.5 : l.mode === "group" ? 2.4 : l.outcome === "hitl" ? 2.2 : 1.3)}
        linkDirectionalParticles={(l: any) => (l.kind === "report" || l.outcome === "denied" ? 0 : 2)}
        linkDirectionalParticleWidth={(l: any) => (l.mode === "group" ? 3 : 2.2)}
        linkDirectionalParticleColor={linkColor}
        linkDirectionalParticleSpeed={0.011}
        linkDirectionalArrowLength={(l: any) => (l.kind === "report" ? 2.4 : 0)}
        linkDirectionalArrowRelPos={1}
        nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D) => {
          const { x, y } = node;
          if (!Number.isFinite(x) || !Number.isFinite(y)) return;
          const isOp = node.id === "operator";
          const r = isOp ? 8 : nodeRadius(node.level);
          const status = isOp ? "idle" : statusMap[node.id] ?? "idle";
          const base = isOp ? CHROME.accent : deptColor(node.dept);
          const dim = deptFilter && !isOp && node.dept !== deptFilter ? 0.13 : 1;
          ctx.globalAlpha = dim;

          if (status !== "idle") {
            const sc = STATUS_COLORS[status];
            const g = ctx.createRadialGradient(x, y, 0, x, y, r + 9);
            g.addColorStop(0, sc + "66");
            g.addColorStop(1, "rgba(0,0,0,0)");
            ctx.fillStyle = g;
            ctx.beginPath();
            ctx.arc(x, y, r + 9, 0, 2 * Math.PI);
            ctx.fill();
            ctx.beginPath();
            ctx.arc(x, y, r + 3, 0, 2 * Math.PI);
            ctx.strokeStyle = sc;
            ctx.globalAlpha = dim * 0.9;
            ctx.lineWidth = 1.3;
            ctx.stroke();
            ctx.globalAlpha = dim;
          }
          if (!isOp && groupMembers.has(node.id)) {
            ctx.beginPath();
            ctx.arc(x, y, r + 6, 0, 2 * Math.PI);
            ctx.strokeStyle = "rgba(183,156,255,0.55)";
            ctx.lineWidth = 1;
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
          ctx.shadowColor = base;
          ctx.shadowBlur = isOp ? 14 : status !== "idle" ? 8 : 0;
          ctx.fill();
          ctx.shadowBlur = 0;
          if (node.level >= 4) {
            ctx.beginPath();
            ctx.arc(x, y, r + 1.7, 0, 2 * Math.PI);
            ctx.strokeStyle = "rgba(255,255,255,0.5)";
            ctx.lineWidth = 0.8;
            ctx.stroke();
          }
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
          // Labels drawn in a single decluttered pass: only operator / CEO /
          // dept-heads / the hovered node, never overlapping, on dark pills.
          const placed: { x0: number; y0: number; x1: number; y1: number }[] = [];
          const cands: { n: any; pr: number }[] = [];
          for (const n of nodes) {
            if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) continue;
            const isHover = n.id === hover;
            const isOp = n.id === "operator";
            if (!(isHover || isOp || n.level >= 4)) continue;
            cands.push({ n, pr: isHover ? 0 : isOp ? 1 : 7 - n.level });
          }
          cands.sort((a, b) => a.pr - b.pr);
          const fpx = Math.max(8.5, 11 / scale);
          ctx.font = `600 ${fpx}px "Spline Sans Mono", monospace`;
          ctx.textAlign = "center";
          ctx.textBaseline = "top";
          for (const { n } of cands) {
            const r = n.id === "operator" ? 8 : nodeRadius(n.level);
            const w = ctx.measureText(n.name).width;
            const cx = n.x;
            const ty = n.y + r + 3.5;
            const pad = 3.5;
            const box = { x0: cx - w / 2 - pad, y0: ty - 1.5, x1: cx + w / 2 + pad, y1: ty + fpx + 1.5 };
            const clash = placed.some((p) => box.x0 < p.x1 && box.x1 > p.x0 && box.y0 < p.y1 && box.y1 > p.y0);
            if (clash && n.id !== hover) continue;
            placed.push(box);
            ctx.fillStyle = "rgba(7,9,14,0.8)";
            roundRect(ctx, box.x0, box.y0, box.x1 - box.x0, box.y1 - box.y0, 3);
            ctx.fill();
            ctx.strokeStyle = "rgba(150,180,210,0.14)";
            ctx.lineWidth = 0.5;
            ctx.stroke();
            ctx.fillStyle = n.id === hover ? "#e8eef4" : "rgba(232,238,244,0.82)";
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
  return `rgb(${Math.min(255, ((n >> 16) & 255) + 60)},${Math.min(255, ((n >> 8) & 255) + 60)},${Math.min(255, (n & 255) + 60)})`;
}
