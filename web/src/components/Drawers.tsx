import { useEffect, useState } from "react";
import { Lock, Users, X } from "lucide-react";
import { api } from "../api";
import type { AgentCardView } from "../types";
import { LEVEL_LABEL, deptColor } from "../theme";
import { useStore } from "../store";
import { IntentChip, ModeTag, OutcomeBadge, SensitivityShield, StatusDot } from "./ui";

function Drawer({ title, idx, onClose, children, accent }: { title: string; idx?: string; onClose: () => void; children: React.ReactNode; accent?: string }) {
  return (
    <div className="fixed inset-0 z-30 flex justify-end" style={{ background: "rgba(24,28,34,0.38)", backdropFilter: "blur(2px)" }} onClick={onClose}>
      <div
        className="h-full w-[452px] max-w-[94vw] panel flex flex-col animate-slide-in"
        style={{ borderRadius: 0, borderLeft: `1px solid ${accent ?? "var(--border-bright)"}`, boxShadow: "-30px 0 60px -30px rgba(0,0,0,0.9)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 h-12 border-b shrink-0" style={{ borderColor: "var(--border)" }}>
          <span className="flex items-center gap-1.5">
            {idx && <span className="idx" style={accent ? { color: accent } : undefined}>{idx}</span>}
            <span className="eyebrow" style={{ color: accent ?? "var(--accent)" }}>{title}</span>
          </span>
          <button onClick={onClose} className="text-faint hover:text-ink"><X size={16} /></button>
        </div>
        <div className="flex-1 overflow-y-auto min-h-0">{children}</div>
      </div>
    </div>
  );
}

export function ConversationDrawer() {
  const cid = useStore((s) => s.selectedContext);
  const ctx = useStore((s) => (cid ? s.contexts[cid] : null));
  const messages = useStore((s) => (cid ? s.messagesByCtx[cid] : null)) ?? [];
  const decisions = useStore((s) => (cid ? s.decisionsByCtx[cid] : null)) ?? [];
  const agents = useStore((s) => s.agents);
  const close = () => useStore.getState().selectContext(null);
  if (!cid) return null;
  const nameOf = (id: string) => (id === "operator" ? "Operator (you)" : agents[id]?.name ?? id);

  return (
    <Drawer title="Conversation" idx="◆" onClose={close}>
      <div className="p-3.5 border-b" style={{ borderColor: "var(--border)" }}>
        <div className="text-[12px] text-ink mb-1.5 leading-snug">{ctx?.prompt ? `“${ctx.prompt}”` : "Autonomous task"}</div>
        <div className="flex items-center gap-2 mono text-[10px] text-faint">
          <span>{cid}</span>
          {ctx?.state && (
            <span className="px-1.5 py-0.5 rounded-sm uppercase tracking-wide" style={{ background: "var(--inset)", color: ctx.state === "completed" ? "var(--ok)" : ctx.state === "input-required" ? "var(--violet)" : "var(--gold)" }}>{ctx.state}</span>
          )}
        </div>
      </div>

      <div className="p-3.5 flex flex-col gap-2">
        {messages.map((m) => {
          const group = m.mode === "group";
          return (
            <div key={m.id} className="rounded-sm p-2.5" style={{ background: group ? "rgba(109,40,217,0.05)" : "var(--surface-2)", border: `1px solid ${group ? "rgba(109,40,217,0.24)" : "var(--border)"}` }}>
              <div className="flex items-center justify-between gap-2 mb-1">
                <div className="flex items-center gap-1.5 min-w-0">
                  <span className="w-2 h-2 shrink-0" style={{ background: deptColor(agents[m.sender]?.department ?? ""), boxShadow: `0 0 6px ${deptColor(agents[m.sender]?.department ?? "")}55` }} />
                  <span className="text-[11px] font-semibold text-ink truncate">{nameOf(m.sender)}</span>
                  <span className="text-faint text-[10px]">→</span>
                  <span className="text-[10px] text-muted truncate">{group ? `group · ${m.recipients.length}` : m.recipients.map(nameOf).join(", ")}</span>
                </div>
                <ModeTag mode={m.mode} />
              </div>
              <div className="text-[11.5px] text-ink2 leading-snug">{m.text}</div>
              {m.intent && (
                <div className="mt-1.5 flex items-center gap-1.5">
                  <IntentChip tag={m.intent.purpose_tag} />
                  <span className="text-[9.5px] text-faint mono">scope: {m.intent.declared_scope}</span>
                </div>
              )}
            </div>
          );
        })}
        {messages.length === 0 && <div className="text-[11px] text-faint text-center py-5">No messages yet…</div>}
      </div>

      {decisions.length > 0 && (
        <div className="p-3.5 border-t" style={{ borderColor: "var(--border)" }}>
          <div className="eyebrow mb-2">Context disposition</div>
          <div className="flex flex-col gap-2">
            {decisions.map((d, i) => (
              <div key={i} className="flex items-start gap-2 text-[11px]">
                <OutcomeBadge kind={d.kind === "shared" ? "shared" : d.kind === "redacted" ? "redacted" : d.kind === "denied" ? "denied" : "reused"} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-ink truncate">{d.title}</span>
                    <SensitivityShield level={d.sensitivity} />
                  </div>
                  <div className="text-[10px] text-faint leading-snug">{d.reason}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Drawer>
  );
}

export function AgentCardDrawer() {
  const id = useStore((s) => s.selectedAgent);
  const liveStatus = useStore((s) => (id ? s.status[id] : undefined));
  const agents = useStore((s) => s.agents);
  const [card, setCard] = useState<AgentCardView | null>(null);
  const close = () => useStore.getState().selectAgent(null);

  useEffect(() => {
    setCard(null);
    if (id) api.card(id).then(setCard).catch(console.error);
  }, [id]);

  if (!id) return null;
  const node = agents[id];
  const color = deptColor(node?.department ?? "");
  const nameOf = (x?: string | null) => (x ? agents[x]?.name ?? x : "—");

  return (
    <Drawer title="Agent Card" idx="◆" onClose={close} accent={color}>
      <div className="h-1" style={{ background: `linear-gradient(90deg, ${color}, transparent)`, boxShadow: `0 0 12px ${color}` }} />
      <div className="p-4">
        <div className="flex items-start justify-between">
          <div>
            <div className="font-display text-[18px] font-bold text-ink leading-tight">{node?.name ?? id}</div>
            <div className="text-[12px] text-muted">{node?.role}</div>
          </div>
          <StatusDot status={liveStatus ?? node?.status ?? "idle"} size={10} />
        </div>
        <div className="flex flex-wrap gap-1.5 mt-3">
          <Tag color={color}>{node?.department}</Tag>
          <Tag>{LEVEL_LABEL[node?.level ?? 1]}</Tag>
          <Tag>clearance L{node?.clearance}</Tag>
          {node?.security_cleared && <Tag color="var(--coral)">security-cleared</Tag>}
          <span className="mono text-[9px] text-faint self-center">{id}</span>
        </div>

        {(card?.goal ?? node?.goal) && (
          <Section label="Goal · responsibility">
            <div className="text-[12px] text-ink leading-snug">{card?.goal ?? node?.goal}</div>
          </Section>
        )}

        <Section label="Reporting line">
          <Row k="Operated by" v={card?.user ? `${card.user.name} · ${card.user.email}` : nameOf(id)} />
          <Row k="Reports to" v={nameOf(node?.reports_to)} />
          <Row k="Manages" v={node?.manages.length ? `${node.manages.length} report(s)` : "—"} />
          <Row k="Teams" v={node?.teams.join(", ") || "—"} />
          <Row k="Projects" v={node?.projects.join(", ") || "—"} />
        </Section>

        <Section label={`Skills (${card?.card?.skills?.length ?? 0})`}>
          <div className="flex flex-col gap-1.5">
            {card?.card?.skills?.map((s: any) => (
              <div key={s.id} className="inset rounded-sm px-2 py-1.5">
                <div className="text-[11px] text-ink">{s.name}</div>
                <div className="flex flex-wrap gap-1 mt-1">
                  {s.tags?.map((t: string) => (
                    <span key={t} className="mono text-[8.5px] px-1 py-0.5 rounded-sm" style={{ color: "var(--muted)", background: "var(--inset)" }}>{t}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Section>

        <Section label={`Sensitive context held (${card?.owned_items?.length ?? 0})`}>
          {card?.owned_items?.length ? (
            <div className="flex flex-col gap-1.5">
              {card.owned_items.map((it) => (
                <div key={it.item_id} className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 min-w-0">
                    <Lock size={11} className="text-faint shrink-0" />
                    <span className="text-[11px] text-ink truncate">{it.title}</span>
                  </span>
                  <SensitivityShield level={it.sensitivity} withLabel />
                </div>
              ))}
            </div>
          ) : (
            <div className="text-[11px] text-faint">Holds no sensitive items.</div>
          )}
          <div className="text-[10px] text-faint mono mt-2 flex items-center gap-1.5"><Users size={11} /> learned {card?.learned_count ?? 0} fact(s) from others</div>
        </Section>
      </div>
    </Drawer>
  );
}

function Tag({ children, color }: { children: React.ReactNode; color?: string }) {
  return (
    <span className="text-[10px] px-1.5 py-0.5 rounded-sm" style={{ color: color ?? "var(--muted)", background: color ? `${color}14` : "var(--inset)", border: `1px solid ${color ? `${color}33` : "var(--border)"}` }}>
      {children}
    </span>
  );
}
function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="mt-4"><div className="eyebrow mb-2">{label}</div>{children}</div>;
}
function Row({ k, v }: { k: string; v: string }) {
  return <div className="flex items-center justify-between text-[11px] py-0.5"><span className="text-faint">{k}</span><span className="text-muted truncate max-w-[60%] text-right">{v}</span></div>;
}
