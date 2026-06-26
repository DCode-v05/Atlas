import { useEffect, useMemo, useState } from "react";
import { Loader2, Power, Search, ShieldCheck, Database, Plug, Radio } from "lucide-react";
import { useStore } from "../store";
import { LEVEL_LABEL, deptColor } from "../theme";
import type { AgentNode } from "../types";

/**
 * The authenticated network — agents prove an Ed25519 key to JOIN, after which
 * only members can communicate (the orchestrator/Router gate on membership). This
 * panel is the operator's control surface: who's online, one-click join/disconnect,
 * and the empty-network state that mirrors the backend's "authenticate first" gate.
 */
export function NetworkPanel() {
  const org = useStore((s) => s.org);
  const network = useStore((s) => s.network);
  const joinAll = useStore((s) => s.joinAll);
  const disconnectAll = useStore((s) => s.disconnectAll);
  const selectedOrg = useStore((s) => s.selectedOrg);
  const loadNetwork = useStore((s) => s.loadNetwork);
  const [q, setQ] = useState("");

  // Always reflect the org IN VIEW: re-fetch membership whenever the tab mounts or the selected
  // org changes — so returning to this tab after switching orgs never shows the previous org's
  // online/Join-all state. Passing the org explicitly avoids any stale module-level scope.
  useEffect(() => {
    void loadNetwork(selectedOrg ?? undefined);
  }, [selectedOrg, loadNetwork]);

  if (!org) return null;
  const nodes = org.nodes;
  const onlineCount = Object.keys(network.online).length;
  const total = nodes.length;
  const allBusy = Object.keys(network.busy).length > 0;

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = needle
      ? nodes.filter((n) => `${n.name} ${n.role} ${n.department} ${n.id}`.toLowerCase().includes(needle))
      : nodes.slice();
    return list.sort(
      (a, b) =>
        Number(!!network.online[b.id]) - Number(!!network.online[a.id]) ||
        b.level - a.level ||
        a.department.localeCompare(b.department),
    );
  }, [nodes, q, network.online]);

  // ── persistence/network off (in-memory mode) ──────────────────────────────
  if (network.loaded && !network.enabled) {
    return (
      <div className="h-full grid place-items-center p-6">
        <div className="panel-flat rounded-md max-w-md p-5 text-center" style={{ borderColor: "var(--border)" }}>
          <Database size={22} className="mx-auto mb-3" style={{ color: "var(--muted)" }} />
          <div className="text-[13px] font-semibold text-ink mb-1.5">Authenticated network is off</div>
          <div className="text-[11.5px] text-muted leading-relaxed">
            Atlas is running fully in-memory, so every agent can communicate without joining. Set{" "}
            <span className="mono text-[10.5px] px-1 py-0.5 rounded-sm" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
              ATLAS_DATABASE_URL
            </span>{" "}
            to enable Postgres persistence and the Ed25519 join-the-network flow, where only authenticated agents can talk.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* header */}
      <div className="flex items-center gap-2 px-3.5 h-9 shrink-0 border-b" style={{ borderColor: "var(--border)" }}>
        <Radio size={13} strokeWidth={2.4} style={{ color: "var(--accent)" }} />
        <span className="eyebrow" style={{ color: "var(--text-2)" }}>Authenticated Network</span>
        <span className="mono text-[9.5px]" style={{ color: onlineCount ? "var(--accent)" : "var(--muted)" }}>
          · {onlineCount} / {total} online
        </span>
        <span className="ml-auto flex items-center gap-1.5 mono text-[9px] text-faint">
          <ShieldCheck size={11} strokeWidth={2.3} /> Ed25519 · scoped JWT
        </span>
      </div>

      {/* toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 shrink-0 border-b" style={{ borderColor: "var(--border)" }}>
        <div className="relative flex-1 max-w-[260px]">
          <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2" style={{ color: "var(--faint)" }} />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="filter agents…"
            className="w-full pl-7 pr-2 h-7 rounded-sm text-[11.5px] bg-transparent outline-none"
            style={{ border: "1px solid var(--border)", color: "var(--text)" }}
          />
        </div>
        <span className="ml-auto" />
        <button
          onClick={() => joinAll(nodes.filter((n) => !network.online[n.id]).map((n) => n.id))}
          disabled={allBusy || onlineCount === total}
          className="flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[11px] font-semibold transition-all disabled:opacity-40"
          style={{ background: "var(--accent)", color: "#fff" }}
        >
          <Plug size={12} strokeWidth={2.4} /> Join all
        </button>
        <button
          onClick={() => disconnectAll()}
          disabled={allBusy || onlineCount === 0}
          className="flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[11px] font-semibold transition-all disabled:opacity-40"
          style={{ border: "1px solid var(--border)", color: "var(--muted)" }}
        >
          <Power size={12} strokeWidth={2.4} /> Disconnect all
        </button>
      </div>

      {/* empty-network banner — mirrors the backend gate */}
      {onlineCount === 0 && (
        <div className="mx-3 mt-2.5 px-3 py-2 rounded-sm text-[11px] leading-relaxed shrink-0"
          style={{ background: "rgba(185,113,10,0.10)", border: "1px solid rgba(185,113,10,0.35)", color: "var(--amber)" }}>
          No agents are in the network yet. <span style={{ color: "var(--text-2)" }}>Prompts are rejected until at least
          one agent joins</span> — authenticate an agent below so it can communicate.
        </div>
      )}

      {/* roster */}
      <div className="flex-1 overflow-y-auto p-3">
        <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(212px, 1fr))" }}>
          {filtered.map((n) => (
            <MemberCard key={n.id} node={n} />
          ))}
        </div>
      </div>
    </div>
  );
}

function MemberCard({ node }: { node: AgentNode }) {
  const online = useStore((s) => !!s.network.online[node.id]);
  const busy = useStore((s) => !!s.network.busy[node.id]);
  const joinAgent = useStore((s) => s.joinAgent);
  const disconnectAgent = useStore((s) => s.disconnectAgent);
  const color = deptColor(node.department);

  return (
    <div
      className="panel-flat rounded-sm overflow-hidden relative transition-all"
      style={{ boxShadow: online ? `0 0 0 1px ${color}55, 0 8px 24px -18px rgba(0,0,0,0.8)` : "0 8px 24px -20px rgba(0,0,0,0.8)", opacity: online ? 1 : 0.82 }}
    >
      <div className="h-[3px]" style={{ background: online ? `linear-gradient(90deg, ${color}, transparent)` : "var(--border)" }} />
      <div className="p-2.5">
        <div className="flex items-start justify-between gap-1.5">
          <div className="min-w-0">
            <div className="text-[12px] font-semibold text-ink truncate">{node.name}</div>
            <div className="text-[10.5px] text-muted truncate">{node.role}</div>
          </div>
          <span
            className="shrink-0 inline-flex items-center gap-1 mono text-[8.5px] uppercase tracking-wide px-1.5 py-0.5 rounded-full"
            title={online ? "Joined — session active" : "Offline — not in the network"}
            style={
              online
                ? { color: "var(--accent)", background: "var(--accent-soft)", border: "1px solid rgba(182,242,74,0.4)" }
                : { color: "var(--faint)", background: "rgba(120,130,140,0.10)", border: "1px solid var(--border)" }
            }
          >
            <span className="w-1.5 h-1.5 rounded-full" style={{ background: online ? "var(--accent)" : "var(--faint)", boxShadow: online ? "0 0 6px var(--accent)" : "none" }} />
            {online ? "online" : "offline"}
          </span>
        </div>

        <div className="flex items-center justify-between mt-2.5">
          <span className="mono text-[9px] px-1.5 py-0.5 rounded-sm uppercase tracking-wide" style={{ color, background: `${color}18`, border: `1px solid ${color}33` }}>
            {LEVEL_LABEL[node.level]}
          </span>
          <span className="flex gap-0.5" title={`Clearance L${node.clearance}`}>
            {[1, 2, 3, 4, 5].map((i) => (
              <span key={i} className="w-1 h-2.5 rounded-[1px]" style={{ background: i <= node.clearance ? "var(--accent)" : "rgba(30,41,53,0.12)" }} />
            ))}
          </span>
        </div>

        <button
          onClick={() => (online ? disconnectAgent(node.id) : joinAgent(node.id))}
          disabled={busy}
          className="mt-2.5 w-full flex items-center justify-center gap-1.5 h-7 rounded-sm text-[11px] font-semibold transition-all disabled:opacity-50"
          style={
            online
              ? { border: "1px solid var(--border)", color: "var(--muted)" }
              : { background: "var(--accent)", color: "#fff" }
          }
        >
          {busy ? (
            <Loader2 size={12} className="animate-spin" />
          ) : online ? (
            <><Power size={12} strokeWidth={2.4} /> Disconnect</>
          ) : (
            <><Plug size={12} strokeWidth={2.4} /> Join network</>
          )}
        </button>

        <div className="mono text-[8px] text-faint mt-1.5 truncate">{node.id} · {node.department}</div>
      </div>
    </div>
  );
}
