import {
  Activity,
  ArrowRightLeft,
  Boxes,
  GitBranch,
  MessageCircle,
  Shield,
  Siren,
} from "lucide-react";
import type { ReactNode } from "react";
import {
  INTENT_META,
  OUTCOME_META,
  SENSITIVITY_META,
  STATUS_COLORS,
  STATUS_LABEL,
  deptColor,
} from "../theme";

const ICONS: Record<string, any> = { Boxes, Activity, ArrowRightLeft, Siren, GitBranch, MessageCircle };

/* Four L-shaped corner brackets — the signature framing detail. */
export function Brackets({ color, inset = 0 }: { color?: string; inset?: number }) {
  const style = color ? ({ ["--bracket-c" as any]: color } as React.CSSProperties) : undefined;
  const off = inset ? { margin: inset } : undefined;
  return (
    <span aria-hidden style={style} className="pointer-events-none">
      <span className="bracket bracket-tl" style={off} />
      <span className="bracket bracket-tr" style={off} />
      <span className="bracket bracket-bl" style={off} />
      <span className="bracket bracket-br" style={off} />
    </span>
  );
}

export function Panel({ children, className = "", glow = false }: { children: ReactNode; className?: string; glow?: boolean }) {
  return (
    <div className={`panel rounded ${glow ? "lume" : ""} ${className}`}>
      <Brackets />
      {children}
    </div>
  );
}

/* Numbered section header — "01 — LIVE COMMS" in instrument mono. */
export function SectionHead({ idx, children, right, color }: { idx?: string; children: ReactNode; right?: ReactNode; color?: string }) {
  return (
    <div className="flex items-center justify-between px-3 pt-3 pb-2">
      <span className="flex items-center gap-1.5 min-w-0">
        {idx && <span className="idx" style={color ? { color } : undefined}>{idx}</span>}
        {idx && <span className="text-faint text-[9px]">—</span>}
        <span className="eyebrow truncate">{children}</span>
      </span>
      {right}
    </div>
  );
}

// Back-compat alias used across panels.
export function Eyebrow({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return <SectionHead right={right}>{children}</SectionHead>;
}

export function StatusDot({ status, size = 8 }: { status: string; size?: number }) {
  const color = STATUS_COLORS[status] ?? STATUS_COLORS.idle;
  const pulsing = status === "thinking" || status === "waiting_hitl";
  return (
    <span className="relative inline-flex" style={{ width: size, height: size }} title={STATUS_LABEL[status] ?? status}>
      {pulsing && <span className="absolute inset-0 animate-pulse-ring" style={{ background: color, opacity: 0.5 }} />}
      <span className="relative" style={{ width: size, height: size, background: color, boxShadow: `0 0 8px ${color}, 0 0 2px ${color}` }} />
    </span>
  );
}

export function DeptDot({ dept }: { dept: string }) {
  const c = deptColor(dept);
  return <span className="inline-block w-2 h-2" style={{ background: c, boxShadow: `0 0 6px ${c}66` }} />;
}

function Pill({ color, children, title }: { color: string; children: ReactNode; title?: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-sm px-1.5 py-[3px] text-[10px] font-semibold leading-none mono"
      title={title}
      style={{ color, background: `${color}1c`, border: `1px solid ${color}3a`, boxShadow: `inset 0 0 10px -6px ${color}` }}
    >
      {children}
    </span>
  );
}

export function IntentChip({ tag, compact = false }: { tag?: string | null; compact?: boolean }) {
  if (!tag) return null;
  const meta = INTENT_META[tag];
  if (!meta) return null;
  const Icon = ICONS[meta.icon] ?? Boxes;
  return (
    <Pill color={meta.color} title={`Intent: ${meta.label}`}>
      <Icon size={11} strokeWidth={2.3} />
      {!compact && <span className="tracking-wide uppercase text-[9px]">{meta.label}</span>}
    </Pill>
  );
}

export function SensitivityShield({ level, withLabel = false }: { level: string; withLabel?: boolean }) {
  const meta = SENSITIVITY_META[level];
  if (!meta) return null;
  return (
    <Pill color={meta.color} title={`Sensitivity: ${meta.label}`}>
      <Shield size={10} strokeWidth={2.4} fill={meta.rank >= 2 ? meta.color : "none"} />
      {withLabel && <span className="uppercase tracking-wider text-[9px]">{meta.label}</span>}
    </Pill>
  );
}

export function OutcomeBadge({ kind }: { kind: string }) {
  const meta = OUTCOME_META[kind] ?? OUTCOME_META.reused;
  return (
    <Pill color={meta.color}>
      <span className="uppercase tracking-wider text-[9px]">{meta.label}</span>
    </Pill>
  );
}

export function ModeTag({ mode }: { mode: string }) {
  const group = mode === "group";
  const c = group ? "var(--violet)" : "var(--accent)";
  return (
    <span
      className="inline-flex items-center rounded-sm px-1.5 py-[3px] text-[9px] font-bold uppercase tracking-[0.14em] leading-none mono"
      style={{ color: c, background: `${group ? "rgba(155,140,255,0.14)" : "var(--accent-soft)"}`, border: `1px solid ${group ? "rgba(155,140,255,0.42)" : "rgba(182,242,74,0.4)"}` }}
    >
      {group ? "GROUP" : "1:1"}
    </span>
  );
}

export const toneColor: Record<string, string> = {
  info: "#5c6675",
  accent: "#2f4bdb",
  ok: "#0a8f5b",
  warn: "#b9710a",
  danger: "#d12a3a",
  hitl: "#6d28d9",
};
