// Single source of truth for the semantic palettes — imported by both the
// canvas/SVG graph (needs raw hex; it cannot resolve CSS vars) and the DOM
// badges. "Command Deck" (light) palette: every hue is saturated/dark enough to
// read on a near-white field. Departments stay as distinct jewel tones.

export const CHROME = {
  accent: "#2f4bdb",       // cobalt — brand / active / operator
  accentBright: "#4f6bff",
  ok: "#0a8f5b",           // shared
  cyan: "#0e8fa8",         // info / handoff
  amber: "#b9710a",        // redact / caution
  gold: "#c2680a",         // cron
  violet: "#6d28d9",       // human-in-the-loop
  red: "#d12a3a",          // deny / alert
  idle: "#aab2bf",
  text: "#181c22",
  muted: "#5c6675",
  faint: "#98a1ad",
  panel: "#ffffff",
  border: "rgba(30,41,53,0.16)",
};

export const DEPARTMENT_COLORS: Record<string, string> = {
  exec: "#b5891f",
  engineering: "#0f9b8e",
  product: "#4f46e5",
  qa: "#2f9e44",
  devops: "#c2680a",
  sales: "#c2255c",
  design: "#9333ea",
  data: "#0e7490",
  marketing: "#d9480f",
  support: "#1d6fd1",
  security: "#d12a3a",
  hr: "#5c8a1e",
};

export const DEPARTMENT_LABEL: Record<string, string> = {
  exec: "Executive",
  engineering: "Engineering",
  product: "Product",
  qa: "QA",
  devops: "DevOps / SRE",
  sales: "Sales",
  design: "Design",
  data: "Data / ML",
  marketing: "Marketing",
  support: "Support",
  security: "Security",
  hr: "People",
};

// purpose_tag → color + lucide icon name
export const INTENT_META: Record<string, { color: string; icon: string; label: string }> = {
  "task-context": { color: "#2f4bdb", icon: "Boxes", label: "Task context" },
  "status-check": { color: "#5c6675", icon: "Activity", label: "Status check" },
  handoff: { color: "#0e8fa8", icon: "ArrowRightLeft", label: "Handoff" },
  incident: { color: "#d12a3a", icon: "Siren", label: "Incident" },
  planning: { color: "#6d28d9", icon: "GitBranch", label: "Planning" },
  social: { color: "#0a8f5b", icon: "MessageCircle", label: "Social" },
};

export const SENSITIVITY_META: Record<string, { color: string; rank: number; label: string }> = {
  public: { color: "#6b7280", rank: 0, label: "Public" },
  internal: { color: "#0e8fa8", rank: 1, label: "Internal" },
  confidential: { color: "#b9710a", rank: 2, label: "Confidential" },
  restricted: { color: "#d9480f", rank: 3, label: "Restricted" },
  secret: { color: "#d12a3a", rank: 4, label: "Secret" },
};

export const STATUS_COLORS: Record<string, string> = {
  idle: "#aab2bf",
  thinking: "#c2680a",
  speaking: "#2f4bdb",
  waiting_hitl: "#6d28d9",
};

export const STATUS_LABEL: Record<string, string> = {
  idle: "Idle",
  thinking: "Thinking",
  speaking: "Communicating",
  waiting_hitl: "Awaiting approval",
};

// outcome of a context request → color
export const OUTCOME_META: Record<string, { color: string; label: string }> = {
  shared: { color: "#0a8f5b", label: "Shared" },
  redacted: { color: "#b9710a", label: "Redacted" },
  denied: { color: "#d12a3a", label: "Withheld" },
  hitl: { color: "#6d28d9", label: "Approval" },
  reused: { color: "#5c6675", label: "Reused" },
};

// trace span kind → color + label (agent observability)
export const TRACE_KIND_META: Record<string, { color: string; label: string }> = {
  route: { color: "#2f4bdb", label: "Route" },
  think: { color: "#6d28d9", label: "Think" },
  judge_scope: { color: "#0e8fa8", label: "Gate" },
  judge_group: { color: "#9333ea", label: "Group?" },
  phrase: { color: "#0a8f5b", label: "Message" },
  decide_share: { color: "#b9710a", label: "Decide" },
  reason_share: { color: "#b9710a", label: "Share review" },
  policy: { color: "#5c6675", label: "Policy" },
};

export const LEVEL_LABEL: Record<number, string> = {
  1: "IC",
  2: "Lead",
  3: "Manager",
  4: "Dept Head",
  5: "CEO",
};

export function nodeRadius(level: number): number {
  return 3.2 + level * 1.45; // IC≈4.6 … CEO≈10.4
}
export function deptColor(dept: string): string {
  return DEPARTMENT_COLORS[dept] ?? CHROME.muted;
}
export function intentColor(tag?: string): string {
  return (tag && INTENT_META[tag]?.color) || CHROME.muted;
}
export function sensitivityColor(s?: string): string {
  return (s && SENSITIVITY_META[s]?.color) || CHROME.muted;
}

// Pretty team label: "engineering-team-2" → "Engineering · Squad 2"
export function teamLabel(teamId: string): string {
  const m = teamId.match(/^(.*)-team-(\d+)$/);
  if (!m) return teamId;
  const dept = DEPARTMENT_LABEL[m[1]] ?? (m[1].charAt(0).toUpperCase() + m[1].slice(1));
  return `${dept} · Squad ${m[2]}`;
}
