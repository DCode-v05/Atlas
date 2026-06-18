import { useState } from "react";
import { Bell, Cpu, Radio, Send, Sparkles, SquareDashedBottom, Telescope, Triangle } from "lucide-react";
import { api } from "../api";
import { useStore } from "../store";

const SUGGESTED: { label: string; prompt: string }[] = [
  { label: "billing · secret", prompt: "Fix the billing Stripe payment integration and get the API credentials" },
  { label: "roadmap · redact", prompt: "What is the Q3 launch date and the product roadmap?" },
  { label: "incident · group", prompt: "Production incident on the auth service — coordinate the on-call response with the team" },
  { label: "out-of-scope", prompt: "What's the weather in Paris and a good pasta recipe?" },
];

export function TopBar() {
  const [text, setText] = useState("");
  const conn = useStore((s) => s.conn);
  const cron = useStore((s) => s.cron);
  const hitlCount = useStore((s) => s.hitl.length);
  const llm = useStore((s) => s.llm);

  const submit = async (p?: string) => {
    const prompt = (p ?? text).trim();
    if (!prompt) return;
    setText("");
    try { await api.prompt(prompt); } catch (e) { console.error(e); }
  };
  const toggleCron = async () => {
    try { await api.cron(!cron.running); } catch (e) { console.error(e); }
  };

  const connColor = conn === "live" ? "var(--accent)" : conn === "connecting" ? "var(--gold)" : "var(--coral)";

  return (
    <header className="h-full glass rounded-xl flex items-center gap-3 px-3.5">
      {/* brand */}
      <div className="flex items-center gap-2.5 shrink-0 pr-1">
        <div className="relative grid place-items-center w-8 h-8 rounded-lg" style={{ background: "radial-gradient(circle at 30% 25%, var(--accent-bright), var(--accent) 60%, #128b73)", boxShadow: "0 0 18px -2px var(--accent-glow), inset 0 1px 1px rgba(255,255,255,0.5)" }}>
          <Telescope size={16} strokeWidth={2.2} color="#04221c" />
        </div>
        <div className="leading-none">
          <div className="font-display font-extrabold tracking-[0.16em] text-[16px] brand-glow">ATLAS</div>
          <div className="eyebrow mt-1">Agent Observatory</div>
        </div>
      </div>

      <div className="w-px h-8 shrink-0" style={{ background: "linear-gradient(var(--border), transparent)" }} />

      {/* prompt */}
      <div className="flex items-center gap-2 flex-1 min-w-0">
        <div className="flex items-center gap-2 inset rounded-lg px-2.5 h-9 flex-1 min-w-0">
          <Send size={13} className="text-faint shrink-0" />
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="Task an agent…  e.g. “fix the billing integration and get the credentials”"
            className="bg-transparent outline-none text-ink text-[13px] flex-1 min-w-0"
          />
          <button
            onClick={() => submit()}
            className="flex items-center gap-1 text-[10.5px] font-bold tracking-wide px-2 py-1 rounded-md shrink-0 transition-transform hover:scale-[1.03]"
            style={{ background: "linear-gradient(180deg, var(--accent-bright), var(--accent))", color: "#04221c", boxShadow: "0 0 14px -4px var(--accent-glow)" }}
          >
            <Sparkles size={11} /> SEND
          </button>
        </div>
        <div className="hidden 2xl:flex items-center gap-1.5 shrink-0">
          {SUGGESTED.map((s) => (
            <button
              key={s.label}
              onClick={() => submit(s.prompt)}
              title={s.prompt}
              className="text-[10px] mono px-2 py-1.5 rounded-md border whitespace-nowrap text-muted hover:text-ink hover:border-edge-bright transition-colors"
              style={{ borderColor: "var(--border)", background: "rgba(255,255,255,0.015)" }}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {/* cron */}
      <button
        onClick={toggleCron}
        className="shrink-0 flex items-center gap-2 h-9 px-3 rounded-lg border transition-all"
        style={{
          borderColor: cron.running ? "var(--gold)" : "var(--border)",
          background: cron.running ? "rgba(243,182,100,0.12)" : "rgba(255,255,255,0.02)",
          color: cron.running ? "var(--gold)" : "var(--muted)",
          boxShadow: cron.running ? "0 0 16px -6px var(--gold)" : "none",
        }}
        title="Toggle the autonomous simulation burst"
      >
        {cron.running ? <Triangle size={12} fill="currentColor" className="rotate-90" /> : <Triangle size={12} fill="currentColor" className="rotate-90" />}
        <span className="text-[10.5px] font-bold tracking-wide">SIMULATE</span>
        {cron.running && <span className="mono text-[10px] tnum w-7 text-right">{cron.remaining.toFixed(0)}s</span>}
      </button>

      {/* llm status */}
      <LlmPill llm={llm} />

      {/* sse */}
      <div className="shrink-0 flex items-center gap-1.5 h-9 px-2.5 rounded-lg border" style={{ borderColor: "var(--border)", background: "rgba(255,255,255,0.02)" }}>
        <Radio size={12} color={connColor} className={conn !== "live" ? "animate-flicker" : ""} />
        <span className="mono text-[9.5px] uppercase tracking-wider" style={{ color: connColor }}>{conn}</span>
      </div>

      {/* hitl bell */}
      <div className="relative shrink-0 grid place-items-center w-9 h-9 rounded-lg border" style={{ borderColor: hitlCount ? "var(--violet)" : "var(--border)", background: hitlCount ? "rgba(183,156,255,0.1)" : "rgba(255,255,255,0.02)", boxShadow: hitlCount ? "0 0 16px -6px var(--violet)" : "none" }}>
        <Bell size={15} color={hitlCount ? "var(--violet)" : "var(--muted)"} className={hitlCount ? "animate-flicker" : ""} />
        {hitlCount > 0 && (
          <span className="absolute -top-1.5 -right-1.5 min-w-[16px] h-4 px-1 grid place-items-center rounded-full text-[10px] font-bold" style={{ background: "var(--violet)", color: "#1c0f33", boxShadow: "0 0 10px -2px var(--violet)" }}>
            {hitlCount}
          </span>
        )}
      </div>
    </header>
  );
}

function LlmPill({ llm }: { llm: any }) {
  const throttled = !!llm?.throttled;
  const offline = llm?.provider === "offline";
  const color = offline ? "var(--faint)" : throttled ? "var(--gold)" : "var(--accent)";
  const prov = (llm?.provider ?? "llm").toUpperCase();
  const label = throttled ? "THROTTLED" : prov;
  const title = llm
    ? `${prov} — ok ${llm.calls_ok} · throttled ${llm.calls_throttled} · 429 ${llm.calls_429}${llm.reason ? `\n${llm.reason}` : ""}`
    : "LLM status";
  return (
    <div
      className="shrink-0 flex items-center gap-1.5 h-9 px-2.5 rounded-lg border"
      style={{ borderColor: throttled ? "var(--gold)" : "var(--border)", background: throttled ? "rgba(243,182,100,0.1)" : "rgba(255,255,255,0.02)", boxShadow: throttled ? "0 0 16px -6px var(--gold)" : "none" }}
      title={title}
    >
      <Cpu size={12} color={color} className={throttled ? "animate-flicker" : ""} />
      <span className="mono text-[9.5px] uppercase tracking-wider" style={{ color }}>{label}</span>
    </div>
  );
}
