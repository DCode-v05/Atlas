// Single source of truth for the semantic palettes — imported by both the
// canvas graph (needs hex) and the DOM badges. "Obsidian Observatory" palette:
// one aurora-mint signal accent + warm gold / violet / coral semantics, with the
// 12 departments harmonized to muted jewel tones so they never go rainbow.

export const CHROME = {
  accent: "#6ee7c7",
  accentBright: "#8af5d6",
  gold: "#f3b664",
  violet: "#b79cff",
  coral: "#ff6b81",
  amber: "#f2b366",
  idle: "#414c5a",
  text: "#e8eef4",
  muted: "#8794a3",
  faint: "#586472",
  panel: "#0e131a",
  border: "rgba(150,180,200,0.12)",
};

export const DEPARTMENT_COLORS: Record<string, string> = {
  exec: "#d9b15e",
  engineering: "#5ec9c0",
  product: "#9a8cf0",
  qa: "#7bc88a",
  devops: "#e0a05e",
  sales: "#e07a9e",
  design: "#c98ad6",
  data: "#5bb6c4",
  marketing: "#e08a8a",
  support: "#7aa8d8",
  security: "#e07070",
  hr: "#a9c06a",
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
  "task-context": { color: "#6ee7c7", icon: "Boxes", label: "Task context" },
  "status-check": { color: "#9aa7b5", icon: "Activity", label: "Status check" },
  handoff: { color: "#7fb0e8", icon: "ArrowRightLeft", label: "Handoff" },
  incident: { color: "#ff6b81", icon: "Siren", label: "Incident" },
  planning: { color: "#b79cff", icon: "GitBranch", label: "Planning" },
  social: { color: "#86d49b", icon: "MessageCircle", label: "Social" },
};

export const SENSITIVITY_META: Record<string, { color: string; rank: number; label: string }> = {
  public: { color: "#7b8696", rank: 0, label: "Public" },
  internal: { color: "#7fb0e8", rank: 1, label: "Internal" },
  confidential: { color: "#f2c879", rank: 2, label: "Confidential" },
  restricted: { color: "#f0a05e", rank: 3, label: "Restricted" },
  secret: { color: "#ff6b81", rank: 4, label: "Secret" },
};

export const STATUS_COLORS: Record<string, string> = {
  idle: "#414c5a",
  thinking: "#f3b664",
  speaking: "#6ee7c7",
  waiting_hitl: "#b79cff",
};

export const STATUS_LABEL: Record<string, string> = {
  idle: "Idle",
  thinking: "Thinking",
  speaking: "Communicating",
  waiting_hitl: "Awaiting approval",
};

// outcome of a context request → color
export const OUTCOME_META: Record<string, { color: string; label: string }> = {
  shared: { color: "#6ee7c7", label: "Shared" },
  redacted: { color: "#f2b366", label: "Redacted" },
  denied: { color: "#ff6b81", label: "Withheld" },
  hitl: { color: "#b79cff", label: "Approval" },
  reused: { color: "#8794a3", label: "Reused" },
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
