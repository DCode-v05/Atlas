import { useState } from "react";
import { Bell, Cpu, CornerDownLeft, Play, Radio, Search, Square } from "lucide-react";
import { api } from "../api";
import { useStore } from "../store";

export function TopBar() {
  const [text, setText] = useState("");
  const conn = useStore((s) => s.conn);
  const cron = useStore((s) => s.cron);
  const hitlCount = useStore((s) => s.hitl.length);
  const llm = useStore((s) => s.llm);
  const setView = useStore((s) => s.setView);

  const submit = async (p?: string) => {
    const prompt = (p ?? text).trim();
    if (!prompt) return;
    setText("");
    try { await api.prompt(prompt); } catch (e) { console.error(e); }
  };
  const toggleCron = async () => {
    try { await api.cron(!cron.running); } catch (e) { console.error(e); }
  };
  const connColor = conn === "live" ? "var(--ok)" : conn === "connecting" ? "var(--gold)" : "var(--coral)";

  return (
    <header className="panel rounded-lg flex items-center gap-3 px-3 h-[56px]">
      {/* brand */}
      <div className="flex items-center gap-2.5 shrink-0 pr-1">
        <div className="grid place-items-center w-9 h-9 rounded-lg" style={{ background: "var(--accent)", boxShadow: "0 4px 12px -4px var(--accent-glow)" }}>
          <span className="font-display font-extrabold text-[19px] text-white leading-none">A</span>
        </div>
        <div className="leading-none">
          <div className="font-display font-extrabold tracking-tight text-[19px] text-ink">Atlas</div>
          <div className="eyebrow mt-0.5 text-[8.5px]">Agent Operations Deck</div>
        </div>
      </div>

      <div className="w-px h-8 shrink-0" style={{ background: "var(--border)" }} />

      {/* prompt — the hero */}
      <div className="flex items-center gap-2 inset rounded-lg px-3 h-10 flex-1 min-w-0" style={{ boxShadow: "inset 0 0 0 1px var(--accent-soft)" }}>
        <Search size={15} className="shrink-0" style={{ color: "var(--accent)" }} />
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder="Task an agent…  e.g.  plan the Q3 launch with product, design, and marketing"
          className="bg-transparent outline-none text-ink text-[13px] flex-1 min-w-0"
        />
        <kbd className="hidden md:flex items-center gap-1 mono text-[9px] text-faint px-1.5 py-0.5 rounded" style={{ border: "1px solid var(--border)" }}>
          <CornerDownLeft size={9} /> ENTER
        </kbd>
        <button
          onClick={() => submit()}
          className="flex items-center gap-1 text-[11px] font-bold tracking-wide px-3 py-1.5 rounded-md shrink-0 transition-transform hover:scale-[1.03] text-white"
          style={{ background: "var(--accent)", boxShadow: "0 3px 10px -3px var(--accent-glow)" }}
        >
          DISPATCH
        </button>
      </div>

      {/* simulate */}
      <button
        onClick={toggleCron}
        className="shrink-0 flex items-center gap-2 h-10 px-3 rounded-md transition-all"
        style={{
          border: `1px solid ${cron.running ? "var(--gold)" : "var(--border)"}`,
          background: cron.running ? "rgba(194,104,10,0.08)" : "var(--surface)",
          color: cron.running ? "var(--gold)" : "var(--muted)",
        }}
        title={
          cron.mode === "continuous"
            ? "Toggle the autonomous simulation — agents launch goals continuously until stopped"
            : `Toggle the autonomous simulation — a ${cron.burst.toFixed(0)}s burst of agent goals, then auto-stops`
        }
      >
        {cron.running ? <Square size={12} fill="currentColor" /> : <Play size={13} fill="currentColor" />}
        <span className="text-[11px] font-bold tracking-wide">
          SIMULATE{cron.mode === "burst" ? ` ${cron.burst.toFixed(0)}s` : ""}
        </span>
        {cron.running && <span className="mono text-[10px] tnum w-7 text-right">{cron.remaining.toFixed(0)}s</span>}
      </button>

      <LlmPill llm={llm} />

      {/* connection */}
      <div className="shrink-0 hidden lg:flex items-center gap-1.5 h-10 px-2.5 rounded-md" style={{ border: "1px solid var(--border)", background: "var(--surface)" }} title={`Live feed: ${conn}`}>
        <Radio size={13} color={connColor} className={conn !== "live" ? "animate-flicker" : ""} />
        <span className="mono text-[9.5px] uppercase tracking-wide" style={{ color: connColor }}>{conn}</span>
      </div>

      {/* hitl bell — jumps to the conversation where approvals are handled inline */}
      <button
        onClick={() => setView("convo")}
        className="relative shrink-0 grid place-items-center w-10 h-10 rounded-md transition-transform hover:scale-[1.04]"
        style={{ border: `1px solid ${hitlCount ? "var(--violet)" : "var(--border)"}`, background: hitlCount ? "rgba(109,40,217,0.07)" : "var(--surface)" }}
        title={hitlCount ? `${hitlCount} approval(s) awaiting — review inline in the conversation` : "No approvals pending"}
      >
        <Bell size={16} color={hitlCount ? "var(--violet)" : "var(--muted)"} className={hitlCount ? "animate-flicker" : ""} />
        {hitlCount > 0 && (
          <span className="absolute -top-1.5 -right-1.5 min-w-[17px] h-[17px] px-1 grid place-items-center rounded-full text-[10px] font-bold mono text-white" style={{ background: "var(--violet)" }}>
            {hitlCount}
          </span>
        )}
      </button>
    </header>
  );
}

function LlmPill({ llm }: { llm: any }) {
  const errored = !!llm?.errored;
  const throttled = !!llm?.throttled;
  const offline = llm?.provider === "offline";
  const color = errored ? "var(--coral)" : offline ? "var(--faint)" : throttled ? "var(--gold)" : "var(--ok)";
  const prov = (llm?.provider ?? "llm").toUpperCase();
  const label = errored ? "LLM ERROR" : throttled ? "THROTTLED" : prov;
  const alert = errored || throttled;
  const accent = errored ? "var(--coral)" : "var(--gold)";
  const bg = errored ? "rgba(209,42,58,0.08)" : "rgba(194,104,10,0.08)";
  const title = llm
    ? `${prov} — ok ${llm.calls_ok} · paced ${llm.calls_throttled} · 429 ${llm.calls_429} · errors ${llm.calls_error ?? 0}${llm.reason ? `\n${llm.reason}` : ""}`
    : "LLM status";
  return (
    <div
      className="shrink-0 hidden sm:flex items-center gap-1.5 h-10 px-2.5 rounded-md"
      style={{ border: `1px solid ${alert ? accent : "var(--border)"}`, background: alert ? bg : "var(--surface)" }}
      title={title}
    >
      <Cpu size={13} color={color} className={alert ? "animate-flicker" : ""} />
      <span className="mono text-[9.5px] uppercase tracking-wide" style={{ color }}>{label}</span>
    </div>
  );
}
