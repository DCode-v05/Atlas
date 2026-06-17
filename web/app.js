/* ===========================================================================
   ATLAS · A2A Trip Concierge — front-end logic
   - discovers agents, draws the live network, streams the A2A protocol log
   - talks ONLY to same-origin endpoints on the gateway
   =========================================================================== */
"use strict";

const EXAMPLES = [
  "Plan a 5-day food and temples trip to Kyoto",
  "A romantic 3-day weekend in Rome",
  "7 budget days backpacking Vietnam",
  "Luxury 4 days in Dubai for shopping and views",
];

// Graph node layout (percent of the canvas). Specialist keys must match the
// backend keys: destination / itinerary / budget.
const NODES = [
  { id: "you",         role: "Client",              name: "You",         x: 10, y: 50, cls: "you" },
  { id: "host",        role: "Orchestrator · 8100", name: "Host Agent",  x: 34, y: 50, cls: "host" },
  { id: "destination", role: "A2A Agent · 8101",    name: "Destination", x: 62, y: 13, cls: "spec" },
  { id: "itinerary",   role: "A2A Agent · 8102",    name: "Itinerary",   x: 62, y: 38, cls: "spec" },
  { id: "budget",      role: "A2A Agent · 8103",    name: "Budget",      x: 62, y: 63, cls: "spec" },
  { id: "weather",     role: "A2A Agent · 8104",    name: "Weather",     x: 62, y: 88, cls: "spec" },
  { id: "mcp",         role: "MCP Tool · 8200",     name: "Weather API", x: 88, y: 88, cls: "tool" },
];
const EDGES = [
  { id: "you",         from: "you",     to: "host" },
  { id: "destination", from: "host",    to: "destination" },
  { id: "itinerary",   from: "host",    to: "itinerary" },
  { id: "budget",      from: "host",    to: "budget" },
  { id: "weather",     from: "host",    to: "weather" },
  { id: "mcp",         from: "weather", to: "mcp", kind: "mcp" },   // MCP, not A2A
];

const SPECIALIST_KEYS = ["destination", "itinerary", "budget", "weather"];
const AGENTS = {};            // key -> {name, card, url}
const nodeEls = {};           // id -> element
const edgeEls = {};           // id -> {g, base, flow, packet}
const responseCards = {};     // key -> element

let CONTEXT_ID = null;         // the A2A contextId that identifies this conversation
let PREFERENCES = [];          // remembered user preferences (persist across trips)
let TURNS = [];                // [{request}] in this conversation

const $ = (sel) => document.querySelector(sel);

/* ----------------------------------------------------------------- helpers */
function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function now() {
  const d = new Date();
  return d.toLocaleTimeString([], { hour12: false }) + "." +
    String(d.getMilliseconds()).padStart(3, "0");
}

/* --------------------------------------------------- minimal markdown -> html */
function mdToHtml(md) {
  const lines = String(md || "").replace(/\r/g, "").split("\n");
  let html = "", list = null;
  const closeList = () => { if (list) { html += `</${list}>`; list = null; } };
  const inline = (t) => escapeHtml(t)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/(^|[^_])_([^_\n]+)_/g, "$1<em>$2</em>");

  for (let raw of lines) {
    const line = raw.trimEnd();
    let m;
    if (!line.trim()) { closeList(); continue; }
    if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
      closeList(); html += `<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`;
    } else if (/^\s*[-*]\s+/.test(line)) {
      if (list !== "ul") { closeList(); list = "ul"; html += "<ul>"; }
      html += `<li>${inline(line.replace(/^\s*[-*]\s+/, ""))}</li>`;
    } else if (/^\s*\d+\.\s+/.test(line)) {
      if (list !== "ol") { closeList(); list = "ol"; html += "<ol>"; }
      html += `<li>${inline(line.replace(/^\s*\d+\.\s+/, ""))}</li>`;
    } else if (/^\s*>\s?/.test(line)) {
      closeList(); html += `<blockquote>${inline(line.replace(/^\s*>\s?/, ""))}</blockquote>`;
    } else if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      closeList(); html += "<hr/>";
    } else {
      closeList(); html += `<p>${inline(line)}</p>`;
    }
  }
  closeList();
  return html;
}

/* ------------------------------------------------- JSON syntax highlighting */
function highlightJson(obj) {
  const json = escapeHtml(JSON.stringify(obj, null, 2));
  return json.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(\.\d+)?)/g,
    (match) => {
      let cls = "jn";
      if (/^"/.test(match)) cls = /:$/.test(match) ? "jk" : "js";
      else if (/true|false|null/.test(match)) cls = "jn";
      return `<span class="${cls}">${match}</span>`;
    });
}

/* ============================================================ GRAPH BUILDING */
function buildGraph() {
  const canvas = $("#canvas");
  const svg = $("#edges");

  EDGES.forEach((e) => {
    const isMcp = e.kind === "mcp";
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("class", "edge" + (isMcp ? " mcp-edge" : ""));
    g.id = "edge-" + e.id;
    const base = document.createElementNS("http://www.w3.org/2000/svg", "path");
    base.setAttribute("class", "edge-base");
    const flow = document.createElementNS("http://www.w3.org/2000/svg", "path");
    flow.setAttribute("class", "edge-flow");
    g.appendChild(base); g.appendChild(flow); svg.appendChild(g);

    const packet = el("div", "packet" + (isMcp ? " mcp" : ""));  // HTML "data packet" dot
    canvas.appendChild(packet);
    edgeEls[e.id] = { g, base, flow, packet };
  });

  NODES.forEach((n) => {
    const node = el("div", `node ${n.cls}`);
    node.style.left = n.x + "%";
    node.style.top = n.y + "%";
    node.innerHTML =
      `<div class="node-role">${escapeHtml(n.role)}</div>
       <div class="node-name">${escapeHtml(n.name)}</div>
       <div class="node-foot"><span class="pip"></span><span class="foot-txt">idle</span></div>`;
    canvas.appendChild(node);
    nodeEls[n.id] = node;
  });

  layoutEdges();
  window.addEventListener("resize", layoutEdges);
}

function center(id) {
  // Nodes are placed with left/top as a percentage point and visually centred
  // via transform: translate(-50%,-50%). Transforms don't affect offsetLeft/
  // offsetTop, so those values ALREADY are the node's visual centre — we must
  // NOT add half the width/height (doing so anchored edges at the corners).
  const n = nodeEls[id];
  return { x: n.offsetLeft, y: n.offsetTop };
}
function layoutEdges() {
  const canvas = $("#canvas");
  const w = canvas.clientWidth, h = canvas.clientHeight;
  const svg = $("#edges");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  EDGES.forEach((e) => {
    const a = center(e.from), b = center(e.to);
    const dx = (b.x - a.x) * 0.5;
    const d = `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
    edgeEls[e.id].base.setAttribute("d", d);
    edgeEls[e.id].flow.setAttribute("d", d);
    edgeEls[e.id].packet.style.offsetPath = `path('${d}')`;
    edgeEls[e.id].packet.style.webkitOffsetPath = `path('${d}')`;
  });
}

function setNode(id, state, footText) {
  const n = nodeEls[id];
  if (!n) return;
  n.classList.remove("is-contacted", "is-working", "is-done", "is-error");
  if (state) n.classList.add("is-" + state);
  if (footText) n.querySelector(".foot-txt").textContent = footText;
}
function setEdge(id, on, color) {
  const e = edgeEls[id];
  if (!e) return;
  e.g.classList.toggle("flowing", on);
  e.g.classList.toggle("amber", color === "amber");
  e.packet.classList.toggle("flowing", on);
  e.packet.classList.toggle("amber", color === "amber");
}

/* ============================================================= PROTOCOL LOG */
function logRow({ tag, tagClass, msg, json }) {
  const log = $("#log");
  const empty = log.querySelector(".log-empty");
  if (empty) empty.remove();
  const row = el("div", "log-row");
  row.innerHTML =
    `<div class="log-head">
       <span class="log-time">${now()}</span>
       ${tag ? `<span class="tag ${tagClass || "sys"}">${escapeHtml(tag)}</span>` : ""}
       <span class="log-msg">${msg}</span>
     </div>`;
  if (json !== undefined) {
    row.appendChild(el("div", "log-json", highlightJson(json)));
  }
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}

/* ============================================================ AGENT CARDS UI */
async function loadStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    const badge = $("#llm-badge");
    badge.classList.remove("loading");
    if (s.usingRealLLM) {
      badge.classList.add("live");
      badge.textContent = "Groq · " + s.model;
    } else {
      badge.classList.add("mock");
      badge.textContent = "offline mock (no GROQ_API_KEY)";
    }
    const mcp = $("#mcp-badge");
    mcp.classList.remove("loading");
    mcp.classList.add(s.mcpOnline ? "live" : "mock");
    mcp.textContent = s.mcpOnline ? "MCP tool ✓" : "MCP tool offline";
  } catch { $("#llm-badge").textContent = "gateway offline"; }
}

function renderAgentCard(a, isHost) {
  const c = a.card || {};
  const skills = (c.skills || []).map((s) =>
    `<span class="skill">${escapeHtml(s.name)}</span>`).join("");
  const card = el("div", "acard" + (isHost ? " host-card" : ""));
  card.innerHTML =
    `<div class="acard-top">
       <div class="acard-title">
         <h3>${escapeHtml(c.name || a.key)}</h3>
         ${isHost ? '<span class="role-badge">HOST</span>' : ""}
       </div>
       <span class="dot ${a.online ? "" : "off"}" title="${a.online ? "online" : "offline"}"></span>
     </div>
     <p>${escapeHtml(c.description || "(offline)")}</p>
     ${a.role ? `<div class="role-line">${escapeHtml(a.role)} — <span class="motiv">${escapeHtml(a.motivation || "")}</span></div>` : ""}
     <div class="skills">${skills}</div>
     <div class="url">${escapeHtml(a.url)}</div>
     <button class="view-json">▸ agent-card.json</button>
     <div class="card-json log-json">${highlightJson(c)}</div>`;
  card.querySelector(".view-json").addEventListener("click", () =>
    card.classList.toggle("open"));
  return card;
}

async function loadAgents() {
  const wrap = $("#agent-cards");
  try {
    const data = await (await fetch("/api/agents")).json();
    wrap.innerHTML = "";

    // The orchestrator is itself an A2A agent — show its card first, as HOST.
    if (data.orchestrator) {
      const o = data.orchestrator;
      AGENTS["orchestrator"] = { name: (o.card && o.card.name) || "Orchestrator",
                                 card: o.card || {}, url: o.url };
      const hn = nodeEls["host"];
      if (hn && o.card && o.card.name) hn.querySelector(".node-name").textContent = "Trip Concierge";
      wrap.appendChild(renderAgentCard(o, true));
    }

    (data.agents || []).forEach((a) => {
      const c = a.card || {};
      AGENTS[a.key] = { name: c.name || a.key, card: c, url: a.url };
      if (nodeEls[a.key]) {
        nodeEls[a.key].querySelector(".node-name").textContent =
          (c.name || a.key).replace(/ (Expert|Planner|Advisor|&.*)$/, "");
      }
      wrap.appendChild(renderAgentCard(a, false));
    });
  } catch (e) {
    wrap.innerHTML = `<p class="hint">Could not reach the gateway. Are the
      agents running? (start everything with <code>python launch.py</code>)</p>`;
  }
}

/* =================================================== CONVERSATION MEMORY UI */
function setContextId(id) {
  CONTEXT_ID = id || null;
  try { if (id) localStorage.setItem("atlasContextId", id); } catch {}
}
function showMemoryPanel() { $("#memory-panel").hidden = false; $("#new-trip").hidden = false; }

function renderGoal(intent) {
  if (intent && intent.goal) { $("#mem-goal").textContent = intent.goal; showMemoryPanel(); }
}
function renderBeliefs(b) {
  if (!b) return;
  const chips = [];
  if (b.destination) chips.push(["dest", b.destination]);
  if (b.days) chips.push(["days", b.days + " days"]);
  if (b.travelStyle) chips.push(["style", b.travelStyle]);
  (b.interests || []).forEach((i) => chips.push(["", i]));
  $("#mem-beliefs").innerHTML = chips.map(([k, v]) =>
    `<span class="mem-chip">${k ? `<span class="mem-k">${k}</span>` : ""}${escapeHtml(String(v))}</span>`).join("");
  if (b.destination) $("#bp-route").textContent = String(b.destination).toUpperCase();
  showMemoryPanel();
}
function renderPrefs(prefs) {
  PREFERENCES = prefs || [];
  const box = $("#mem-prefs");
  box.innerHTML = PREFERENCES.length
    ? PREFERENCES.map((p) => `<span class="mem-chip pref">${escapeHtml(p)}</span>`).join("")
    : '<span class="mem-empty">nothing yet</span>';
  if (PREFERENCES.length) showMemoryPanel();
}
function addPrefs(facts) {
  const set = new Set(PREFERENCES);
  (facts || []).forEach((f) => set.add(f));
  renderPrefs([...set]);
}
function renderTurns(turns) {
  TURNS = turns || [];
  $("#mem-turns").innerHTML = TURNS.map((t) => `<li>${escapeHtml(t.request)}</li>`).join("");
  if (TURNS.length) showMemoryPanel();
}

async function loadConversation() {
  let cid = null;
  try { cid = localStorage.getItem("atlasContextId"); } catch {}
  try {
    const data = await (await fetch("/api/conversation?contextId=" + encodeURIComponent(cid || ""))).json();
    renderPrefs(data.preferences);          // show remembered prefs even before any trip
    if (cid && data.exists) {
      setContextId(cid);
      renderBeliefs(data.beliefs);
      renderGoal(data.intent);
      renderTurns(data.turns);
      if (data.lastPlan) {
        $("#final-body").innerHTML = mdToHtml(data.lastPlan);
        $("#final").hidden = false;
      }
    }
  } catch { /* gateway not up yet — ignore */ }
}

async function newTrip() {
  try {
    const r = await (await fetch("/api/reset", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contextId: CONTEXT_ID }),
    })).json();
    setContextId(r.contextId);
  } catch { setContextId(null); }
  TURNS = []; renderTurns([]);
  $("#mem-goal").textContent = "—"; $("#mem-beliefs").innerHTML = "";
  resetRun();
  $("#final").hidden = true;
  $("#log").innerHTML = '<div class="log-empty">New trip — your remembered preferences are kept. Send a request.</div>';
  $("#request").value = ""; $("#request").focus();
  renderPrefs(PREFERENCES);                 // preferences persist across trips
}

/* ============================================================ RESPONSE CARDS */
function ensureResponseCard(key) {
  if (responseCards[key]) return responseCards[key];
  $("#responses").hidden = false;
  const name = (AGENTS[key] && AGENTS[key].name) || key;
  const card = el("div", "rcard working");
  card.innerHTML =
    `<div class="rcard-head">
       <h3>${escapeHtml(name)}</h3>
       <span class="rcard-state"><span class="pip"></span><span class="st">working</span></span>
     </div>
     <div class="rcard-body markdown">
       <div class="skeleton"></div><div class="skeleton s2"></div><div class="skeleton s3"></div>
     </div>`;
  $("#response-grid").appendChild(card);
  responseCards[key] = card;
  return card;
}
function fillResponseCard(key, text) {
  const card = ensureResponseCard(key);
  card.classList.remove("working"); card.classList.add("done");
  card.querySelector(".st").textContent = "completed";
  card.querySelector(".rcard-body").innerHTML = mdToHtml(text);
}

/* ================================================================ THE RUN */
let running = false;

function resetRun() {
  $("#log").innerHTML = "";
  $("#responses").hidden = true;
  $("#response-grid").innerHTML = "";
  $("#final").hidden = true;
  for (const k in responseCards) delete responseCards[k];
  NODES.forEach((n) => setNode(n.id, "", "idle"));
  EDGES.forEach((e) => setEdge(e.id, false));
}

function tagClassFor(key) {
  return SPECIALIST_KEYS.includes(key) ? key : "host";
}

function handleEvent(ev) {
  switch (ev.type) {
    case "start":
      if (ev.contextId) setContextId(ev.contextId);
      $("#new-trip").hidden = false;
      TURNS.push({ request: ev.request }); renderTurns(TURNS);
      logRow({ tag: "client", tagClass: "sys",
        msg: `Sent request to host agent: <span class="k">${escapeHtml(ev.request)}</span>` });
      setNode("host", "working", "thinking");
      setEdge("you", true, "amber");
      break;

    case "recall":
      renderPrefs(ev.preferences);
      if (!ev.isFirst) logRow({ tag: "host", tagClass: "host",
        msg: `Recalled this conversation (turn ${ev.turnCount + 1})${ev.preferences && ev.preferences.length ? ` &middot; ${ev.preferences.length} remembered preference(s)` : ""}` });
      break;

    case "understood":
      renderBeliefs(ev.beliefs);
      renderGoal(ev.intent);
      logRow({ tag: "host", tagClass: "host",
        msg: `Updated beliefs &rarr; goal: <span class="k">${escapeHtml(ev.intent.goal)}</span>${ev.changed && ev.changed.length ? ` &middot; changed: ${escapeHtml(ev.changed.join(", "))}` : ""}`,
        json: { beliefs: ev.beliefs, intent: ev.intent, changed: ev.changed } });
      setEdge("you", false);
      break;

    case "memory_added":
      addPrefs(ev.facts);
      logRow({ tag: "memory", tagClass: "host",
        msg: `Remembered for next time: <span class="k">${escapeHtml(ev.facts.join(", "))}</span>` });
      break;

    case "discovered":
      logRow({ tag: "host", tagClass: "host",
        msg: `Discovered ${ev.agents.length} agents via their <span class="k">/.well-known/agent-card.json</span>`,
        json: ev.agents.map((a) => ({ name: a.card.name, role: a.role, url: a.url,
          skills: (a.card.skills || []).map((s) => s.id) })) });
      ev.agents.forEach((a) => setNode(a.key, "contacted", "ready"));
      break;

    case "selection":
      logRow({ tag: "host", tagClass: "host",
        msg: `Coordination &rarr; running <span class="k">${escapeHtml(ev.selected.join(", ") || "(none — all cached)")}</span>${ev.reused.length ? ` &middot; reusing cached: ${escapeHtml(ev.reused.join(", "))}` : ""}`,
        json: { selected: ev.selected, reused: ev.reused, changed: ev.changed } });
      break;

    case "agent_reused": {
      setNode(ev.agent, "cached", "reused");
      setEdge(ev.agent, false);
      const card = ensureResponseCard(ev.agent);
      card.classList.remove("working"); card.classList.add("cached");
      card.querySelector(".st").textContent = "cached";
      if (ev.text) card.querySelector(".rcard-body").innerHTML = mdToHtml(ev.text);
      logRow({ tag: ev.agent, tagClass: tagClassFor(ev.agent),
        msg: "<em>unchanged this turn — reused cached result (no A2A call)</em>" });
      break;
    }

    case "agent_retry":
      logRow({ tag: ev.agent, tagClass: tagClassFor(ev.agent),
        msg: `<span style="color:var(--amber-soft)">transient error — retrying (attempt ${ev.attempt})…</span>` });
      break;

    case "delegate":
      setNode(ev.agent, "working", "working");
      setEdge(ev.agent, true, "teal");
      ensureResponseCard(ev.agent);
      logRow({ tag: ev.agent, tagClass: tagClassFor(ev.agent),
        msg: `Host &rarr; <strong>${escapeHtml(ev.agentName)}</strong> &nbsp; <span class="k">message/stream</span>${ev.intent ? ` &middot; <em>intent: ${escapeHtml(ev.intent)}</em>` : ""}` });
      break;

    case "a2a_event": {
      const e = ev.event, kind = e.kind;
      let msg = `<span class="k">${escapeHtml(kind)}</span>`;
      if (kind === "task") msg += ` &middot; state=${escapeHtml(e.status.state)}`;
      else if (kind === "status-update") {
        msg += ` &middot; state=${escapeHtml(e.status.state)}${e.final ? " &middot; final" : ""}`;
        if (e.status.message) {
          const t = e.status.message.parts.map((p) => p.text).join(" ");
          msg += ` &middot; <em>${escapeHtml(t)}</em>`;
          // The Weather agent narrates its MCP tool call — light up the tool hop.
          if (ev.agent === "weather") {
            const note = t.toLowerCase();
            if (note.includes("calling weather tool") || note.includes("calling")) {
              setNode("mcp", "working", "fetching"); setEdge("mcp", true);
            } else if (note.includes("received")) {
              setNode("mcp", "done", "data ✓");
            } else if (note.includes("unavailable") || note.includes("unreachable")) {
              setNode("mcp", "error", "offline");
            }
          }
        }
        if (e.status.state === "completed") setNode(ev.agent, "done", "done");
      } else if (kind === "artifact-update") {
        const text = e.artifact.parts.map((p) => p.text).join("");
        msg += ` &middot; ${text.length} chars`;
        fillResponseCard(ev.agent, text);
      }
      logRow({ tag: ev.agent, tagClass: tagClassFor(ev.agent), msg, json: e });
      break;
    }

    case "agent_done":
      setNode(ev.agent, "done", "done");
      setEdge(ev.agent, false);
      if (ev.agent === "weather") {
        setEdge("mcp", false);
        if (nodeEls.mcp.classList.contains("is-working")) setNode("mcp", "done", "data ✓");
      }
      if (ev.text) fillResponseCard(ev.agent, ev.text);
      break;

    case "agent_error":
      setNode(ev.agent, "error", "error");
      setEdge(ev.agent, false);
      logRow({ tag: ev.agent, tagClass: tagClassFor(ev.agent),
        msg: `<span style="color:var(--coral)">error: ${escapeHtml(ev.message)}</span>` });
      break;

    case "synthesis_start":
      setNode("host", "working", "synthesizing");
      EDGES.forEach((e) => { if (e.from === "host") setEdge(e.id, true, "amber"); });
      logRow({ tag: "host", tagClass: "host",
        msg: "Combining all agent responses into one trip plan…" });
      break;

    case "final":
      EDGES.forEach((e) => setEdge(e.id, false));
      setNode("host", "done", "done");
      $("#final-body").innerHTML = mdToHtml(ev.text);
      $("#final").hidden = false;
      $("#final").scrollIntoView({ behavior: "smooth", block: "start" });
      logRow({ tag: "host", tagClass: "host", msg: "Final trip plan ready ✓" });
      break;

    case "error":
      logRow({ tag: "error", tagClass: "budget",
        msg: `<span style="color:var(--coral)">${escapeHtml(ev.message)}</span>` });
      break;

    case "done":
      finishRun();
      break;
  }
}

function finishRun() {
  running = false;
  const go = $("#go");
  go.disabled = false;
  go.classList.remove("running");
  go.querySelector(".go-label").textContent = "Plan my trip";
}

async function runPlan(request) {
  if (running) return;
  running = true;
  resetRun();
  const go = $("#go");
  go.disabled = true; go.classList.add("running");
  go.querySelector(".go-label").textContent = "Planning…";

  try {
    const resp = await fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request, contextId: CONTEXT_ID || "" }),
    });
    if (!resp.ok || !resp.body) throw new Error("gateway error " + resp.status);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop();               // keep the incomplete tail
      for (const frame of frames) {
        const line = frame.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        try { handleEvent(JSON.parse(line.slice(5).trim())); }
        catch (e) { /* ignore malformed frame */ }
      }
    }
  } catch (e) {
    logRow({ tag: "error", tagClass: "budget",
      msg: `<span style="color:var(--coral)">${escapeHtml(e.message)}</span>` });
  } finally {
    finishRun();
  }
}

/* ==================================================================== INIT */
function init() {
  buildGraph();
  loadStatus();
  loadAgents();
  loadConversation();   // restore a conversation from a previous visit + preferences

  const chips = $("#examples");
  EXAMPLES.forEach((ex) => {
    const c = el("button", "chip", escapeHtml(ex));
    c.type = "button";
    c.addEventListener("click", () => { $("#request").value = ex; $("#request").focus(); });
    chips.appendChild(c);
  });

  $("#new-trip").addEventListener("click", newTrip);

  $("#plan-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const req = $("#request").value.trim();
    if (req) runPlan(req);
  });
  // Ctrl/Cmd+Enter to submit from the textarea
  $("#request").addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") $("#plan-form").requestSubmit();
  });

  // keep edges aligned once fonts/layout settle
  setTimeout(layoutEdges, 100);
  setTimeout(layoutEdges, 600);
}

document.addEventListener("DOMContentLoaded", init);
