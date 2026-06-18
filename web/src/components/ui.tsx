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

export function Panel({ children, className = "", glow = false }: { children: ReactNode; className?: string; glow?: boolean }) {
  return <div className={`glass rounded-xl ${glow ? "lume" : ""} ${className}`}>{children}</div>;
}

export function Eyebrow({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-center justify-between px-3.5 pt-3 pb-2">
      <span className="eyebrow">{children}</span>
      {right}
    </div>
  );
}

export function StatusDot({ status, size = 8 }: { status: string; size?: number }) {
  const color = STATUS_COLORS[status] ?? STATUS_COLORS.idle;
  const pulsing = status === "thinking" || status === "waiting_hitl";
  return (
    <span className="relative inline-flex" style={{ width: size, height: size }} title={STATUS_LABEL[status] ?? status}>
      {pulsing && <span className="absolute inset-0 rounded-full animate-pulse-ring" style={{ background: color, opacity: 0.5 }} />}
      <span className="relative rounded-full" style={{ width: size, height: size, background: color, boxShadow: `0 0 8px ${color}, 0 0 2px ${color}` }} />
    </span>
  );
}

export function DeptDot({ dept }: { dept: string }) {
  const c = deptColor(dept);
  return <span className="inline-block w-2 h-2 rounded-[3px]" style={{ background: c, boxShadow: `0 0 6px ${c}66` }} />;
}

function Pill({ color, children, title }: { color: string; children: ReactNode; title?: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md px-1.5 py-[3px] text-[10px] font-semibold leading-none"
      title={title}
      style={{ color, background: `${color}1a`, border: `1px solid ${color}33`, boxShadow: `inset 0 0 10px -6px ${color}` }}
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
      {!compact && <span className="tracking-wide">{meta.label}</span>}
    </Pill>
  );
}

export function SensitivityShield({ level, withLabel = false }: { level: string; withLabel?: boolean }) {
  const meta = SENSITIVITY_META[level];
  if (!meta) return null;
  return (
    <Pill color={meta.color} title={`Sensitivity: ${meta.label}`}>
      <Shield size={10} strokeWidth={2.4} fill={meta.rank >= 2 ? meta.color : "none"} />
      {withLabel && <span className="uppercase tracking-wider">{meta.label}</span>}
    </Pill>
  );
}

export function OutcomeBadge({ kind }: { kind: string }) {
  const meta = OUTCOME_META[kind] ?? OUTCOME_META.reused;
  return (
    <Pill color={meta.color}>
      <span className="uppercase tracking-wider">{meta.label}</span>
    </Pill>
  );
}

export function ModeTag({ mode }: { mode: string }) {
  const group = mode === "group";
  const c = group ? "#b79cff" : "#6ee7c7";
  return (
    <span
      className="inline-flex items-center rounded-md px-1.5 py-[3px] text-[9px] font-bold uppercase tracking-[0.12em] leading-none"
      style={{ color: c, background: `${c}14`, border: `1px solid ${c}40` }}
    >
      {group ? "Group" : "1 : 1"}
    </span>
  );
}

export const toneColor: Record<string, string> = {
  info: "#8794a3",
  accent: "#6ee7c7",
  ok: "#6ee7c7",
  warn: "#f3b664",
  danger: "#ff6b81",
  hitl: "#b79cff",
};
