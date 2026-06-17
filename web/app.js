/* ATLAS — organisation of agents · front-end.
   A live org-chart graph (grows as agents are hired, with data packets flowing
   along the edges), a performative-tagged A2A protocol log, shared ledgers,
   metrics, the final result, and a topology comparison — all driven by the
   gateway's SSE telemetry. Design language ported from the original ATLAS UI. */
"use strict";

const $ = (s) => document.querySelector(s);
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };
const escapeHtml = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SVGNS = "http://www.w3.org/2000/svg";
const nowt = () => { const d = new Date(); return d.toLocaleTimeString([], { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0"); };

const EXAMPLES = [
  "Plan a 5-day food and temples trip to Kyoto",
  "Design and spec a privacy-first smart doorbell",
  "Organise a 7-day budget backpacking route through Vietnam",
  "Write a go-to-market plan for an AI note-taking app",
];

const members = {};          // id -> {role, parentId, depth, status, x, y}
const nodeEls = {};          // id -> div
const edgeEls = {};          // childId -> {g, base, flow, packet}
let RUN = null, running = false;
const tally = { messages: 0, headcount: 0, depth: 0, tokens: 0 };

/* ---------- status ---------- */
async function loadStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    const b = $("#llm-badge");
    if (s.usingRealLLM) { b.classList.add("live"); b.textContent = "Groq · " + s.model; }
    else { b.classList.add("mock"); b.textContent = "deterministic mock"; }
    $("#caps").textContent =
      `caps · headcount ≤ ${s.caps.headcount} · depth ≤ ${s.caps.depth} · budget ${s.caps.tokenBudget.toLocaleString()} tokens · ${s.runtime} runtime`;
  } catch { $("#llm-badge").textContent = "gateway offline"; }
}

/* ---------- markdown + json highlight ---------- */
function mdToHtml(src) {
  const lines = String(src || "").replace(/\r/g, "").split("\n");
  let html = "", list = null;
  const close = () => { if (list) { html += `</${list}>`; list = null; } };
  const inl = (t) => escapeHtml(t)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  for (const raw of lines) {
    const l = raw.trimEnd(); let m;
    if (!l.trim()) { close(); continue; }
    if ((m = l.match(/^(#{1,4})\s+(.*)$/))) { close(); html += `<h${m[1].length}>${inl(m[2])}</h${m[1].length}>`; }
    else if (/^\s*[-*]\s+/.test(l)) { if (list !== "ul") { close(); list = "ul"; html += "<ul>"; } html += `<li>${inl(l.replace(/^\s*[-*]\s+/, ""))}</li>`; }
    else if (/^\s*\d+\.\s+/.test(l)) { if (list !== "ol") { close(); list = "ol"; html += "<ol>"; } html += `<li>${inl(l.replace(/^\s*\d+\.\s+/, ""))}</li>`; }
    else { close(); html += `<p>${inl(l)}</p>`; }
  }
  close(); return html;
}
function highlightJson(obj) {
  const json = escapeHtml(JSON.stringify(obj, null, 2));
  return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(\.\d+)?)/g, (m) => {
    let cls = "jn";
    if (/^"/.test(m)) cls = /:$/.test(m) ? "jk" : "js";
    return `<span class="${cls}">${m}</span>`;
  });
}

/* ================= ORG GRAPH ================= */
function ensureBoard() { if (!members["Board"]) members["Board"] = { role: "You", parentId: null, depth: -1, status: "client" }; }
function relayout() {
  ensureBoard();
  const ids = Object.keys(members);
  const depths = [...new Set(ids.map((id) => members[id].depth))].sort((a, b) => a - b);
  const minD = depths[0], cols = depths.length;
  for (const id of ids) {
    const d = members[id].depth;
    const peers = ids.filter((x) => members[x].depth === d).sort();
    const i = peers.indexOf(id), n = peers.length;
    members[id].x = ((d - minD + 0.5) / cols) * 100;
    members[id].y = ((i + 1) / (n + 1)) * 100;
  }
}
function nodeClass(id) {
  const m = members[id]; let c = "node";
  if (id === "Board") c += " you";
  else if (m.role === "CEO") c += " host";
  const st = m.status;
  if (st === "working") c += " is-working";
  else if (st === "done") c += " is-done";
  else if (st === "error") c += " is-error";
  else if (st === "hired" || st === "onboarded") c += " is-contacted";
  return c;
}
function renderGraph() {
  relayout();
  const canvas = $("#canvas");
  for (const id of Object.keys(members)) {
    let node = nodeEls[id];
    if (!node) {
      node = el("div");
      node.innerHTML = `<div class="node-role"></div><div class="node-name"></div>
        <div class="node-foot"><span class="pip"></span><span class="foot-txt"></span></div>`;
      canvas.appendChild(node); nodeEls[id] = node;
    }
    node.className = nodeClass(id);
    node.style.left = members[id].x + "%";
    node.style.top = members[id].y + "%";
    node.querySelector(".node-role").textContent = id === "Board" ? "client" : "agent · " + id;
    node.querySelector(".node-name").textContent = members[id].role || id;
    node.querySelector(".foot-txt").textContent = members[id].status || "";
  }
  layoutEdges();
}
function center(id) {
  const c = $("#canvas");
  return { x: (members[id].x / 100) * c.clientWidth, y: (members[id].y / 100) * c.clientHeight };
}
function layoutEdges() {
  const svg = $("#edges"), canvas = $("#canvas"), w = canvas.clientWidth, h = canvas.clientHeight;
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  for (const id of Object.keys(members)) {
    const p = members[id].parentId;
    if (!p || !members[p]) continue;
    let e = edgeEls[id];
    if (!e) {
      const g = document.createElementNS(SVGNS, "g"); g.setAttribute("class", "edge");
      const base = document.createElementNS(SVGNS, "path"); base.setAttribute("class", "edge-base");
      const flow = document.createElementNS(SVGNS, "path"); flow.setAttribute("class", "edge-flow");
      g.appendChild(base); g.appendChild(flow); svg.appendChild(g);
      const packet = el("div", "packet"); canvas.appendChild(packet);
      e = edgeEls[id] = { g, base, flow, packet };
    }
    const a = center(p), b = center(id), dx = (b.x - a.x) * 0.5;
    const d = `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
    e.base.setAttribute("d", d); e.flow.setAttribute("d", d);
    e.packet.style.offsetPath = `path('${d}')`;
    e.packet.style.webkitOffsetPath = `path('${d}')`;
  }
}
function pulse(id) { const n = nodeEls[id]; if (!n) return; n.classList.remove("ping"); void n.offsetWidth; n.classList.add("ping"); setTimeout(() => n.classList.remove("ping"), 600); }

const EDGE_COLOR = { propose: "amber", "accept-proposal": "amber", cfp: "violet", "query-ref": "violet", refuse: "coral" };
const PKT_COLOR = { propose: "amber", "accept-proposal": "green", cfp: "violet", "query-ref": "violet", refuse: "coral", inform: "green" };
function flowMessage(from, to, perf) {
  let childId = null, reverse = false;
  if (members[to] && members[to].parentId === from) childId = to;
  else if (members[from] && members[from].parentId === to) { childId = from; reverse = true; }
  if (childId && edgeEls[childId]) {
    const e = edgeEls[childId], ec = EDGE_COLOR[perf], pc = PKT_COLOR[perf];
    e.g.classList.remove("flowing", "amber", "violet", "coral"); void e.g.offsetWidth;
    e.g.classList.add("flowing"); if (ec) e.g.classList.add(ec);
    const p = e.packet;
    p.classList.remove("flowing", "amber", "violet", "coral", "green"); void p.offsetWidth;
    p.style.animationDirection = reverse ? "reverse" : "normal";
    p.classList.add("flowing"); if (pc) p.classList.add(pc);
    setTimeout(() => { e.g.classList.remove("flowing", "amber", "violet", "coral"); p.classList.remove("flowing", "amber", "violet", "coral", "green"); }, 1000);
  }
  pulse(to); if (members[from]) pulse(from);
}

/* ---------- protocol log ---------- */
function logRow(inner, cls, ev) {
  const log = $("#log"); const e0 = log.querySelector(".log-empty"); if (e0) e0.remove();
  const row = el("div", "log-row" + (cls ? " " + cls : ""));
  row.innerHTML = inner;
  if (ev) {
    row.style.cursor = "pointer";
    const jd = el("div", "log-json"); jd.style.display = "none"; jd.innerHTML = highlightJson(ev);
    row.appendChild(jd);
    row.addEventListener("click", () => { jd.style.display = jd.style.display === "none" ? "block" : "none"; });
  }
  log.appendChild(row); log.scrollTop = log.scrollHeight;
}
function logMessage(ev) {
  const perf = ev.performative || "sys";
  logRow(`<div class="log-head">
      <span class="log-time">${nowt()}</span>
      <span class="who">${escapeHtml(ev.fromRole || ev.from)}</span><span class="arrow">→</span>
      <span class="who">${escapeHtml(ev.toRole || ev.to)}</span>
      <span class="tag ${escapeHtml(perf)}">${escapeHtml(perf)}</span>
    </div>${ev.intent ? `<div class="log-intent">${escapeHtml(ev.intent)}</div>` : ""}`, null, ev);
}
function logSys(text, cls) {
  logRow(`<div class="log-head"><span class="log-time">${nowt()}</span>
    <span class="tag ${cls || "sys"}">${cls === "cap" ? "cap" : cls === "meet" ? "meeting" : "system"}</span>
    <span class="log-msg">${text}</span></div>`, (cls || "sys"));
}

/* ---------- round-table ---------- */
const PERF_COLOR = { concern: "var(--coral)", counter: "var(--amber)", inform: "var(--teal)",
                     propose: "var(--green)", agree: "var(--violet)" };
function addRoundTableBubble(ev) {
  const thread = $("#rt-thread");
  $("#roundtable").hidden = false;
  const color = PERF_COLOR[ev.performative] || "var(--muted)";
  const b = el("div", "rt-bubble");
  b.style.borderLeftColor = color;
  b.innerHTML =
    `<div class="rt-meta">
       <span class="rt-name" style="color:${color}">${escapeHtml(ev.persona || "")} · ${escapeHtml(ev.role || "")}</span>
       <span class="rt-perf">${escapeHtml(ev.performative || "")}</span>
     </div>
     <div class="rt-text">${escapeHtml(ev.text || "")}</div>`;
  thread.appendChild(b);
  b.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
function addSummaryCard(ev) {
  $("#rt-summary").hidden = false;
  const color = PERSONA_COLOR_BY_ROLE(ev.role);
  const card = el("div", "rt-sum-card");
  card.style.borderTopColor = color;
  card.innerHTML =
    `<div class="rt-sum-name" style="color:${color}">${escapeHtml(ev.persona || "")}</div>
     <div class="rt-sum-role">${escapeHtml(ev.role || "")}</div>
     <div class="rt-sum-text">${escapeHtml(ev.text || "")}</div>`;
  $("#rt-summary-grid").appendChild(card);
}
// a stable accent colour per specialist (cycled), so cards look intentional
const _SUM_COLORS = ["var(--teal)", "var(--amber-soft)", "var(--coral)", "var(--violet)", "var(--green)"];
const _sumColorMap = {};
function PERSONA_COLOR_BY_ROLE(role) {
  if (!(role in _sumColorMap)) _sumColorMap[role] = _SUM_COLORS[Object.keys(_sumColorMap).length % _SUM_COLORS.length];
  return _sumColorMap[role];
}

/* ---------- ledgers / metrics ---------- */
function renderLedgers(L) {
  if (!L) return;
  $("#ledger-panel").hidden = false;
  if (L.task) {
    $("#l-plan").textContent = L.task.plan || "—";
    $("#l-facts").innerHTML = (L.task.facts || []).map((f) => `<li>› ${escapeHtml(f)}</li>`).join("");
  }
  if (L.progress) {
    $("#l-steps").innerHTML = (L.progress.steps || []).map((s) =>
      `<li><span class="${s.status === "done" ? "ok" : "pend"}">${s.status === "done" ? "✓" : "…"}</span> ${escapeHtml(s.role)} — ${escapeHtml((s.task || "").slice(0, 44))}</li>`).join("");
  }
}
function bumpMetrics() {
  $("#metrics").hidden = false;
  $("#m-messages").textContent = tally.messages;
  $("#m-headcount").textContent = tally.headcount;
  $("#m-depth").textContent = tally.depth;
  $("#m-tokens").textContent = tally.tokens.toLocaleString();
}

/* ---------- event handling ---------- */
function handle(ev) {
  switch (ev.type) {
    case "run":
      if (ev.phase === "started") logSys(`Mission started — <span class="k">${escapeHtml(ev.mission)}</span>`);
      else if (ev.phase === "done") {
        $("#final-panel").hidden = false; $("#final").innerHTML = mdToHtml(ev.final);
        if (ev.metrics) $("#m-elapsed").textContent = (ev.metrics.elapsedMs / 1000).toFixed(1) + "s";
        logSys("Mission complete ✓"); finish();
      } else if (ev.phase === "error") { logSys(escapeHtml(ev.message), "cap"); finish(); }
      break;
    case "hire":
      members[ev.agentId] = { role: ev.role, parentId: ev.parentId, depth: ev.depth, status: "hired" };
      tally.headcount++; renderGraph(); bumpMetrics();
      logSys(`hired <span class="k">${escapeHtml(ev.agentId)}</span> as ${escapeHtml(ev.role)} · depth ${ev.depth}`);
      break;
    case "onboard": {
      const m = members[ev.agentId] || (members[ev.agentId] = {});
      m.role = ev.role; m.depth = ev.depth; m.status = "onboarded"; if (ev.parentId) m.parentId = ev.parentId;
      renderGraph(); pulse(ev.agentId); break;
    }
    case "status": { const m = members[ev.agentId]; if (m) { m.status = ev.state; renderGraph(); } break; }
    case "message":
      tally.messages++; tally.depth = Math.max(tally.depth, ev.depth || 0);
      logMessage(ev); flowMessage(ev.from, ev.to, ev.performative); bumpMetrics(); break;
    case "llm": tally.tokens += ev.tokens || 0; bumpMetrics(); break;
    case "ledger": fetchLedgers(); break;
    case "meeting":
      if (ev.phase === "open") {
        if (nodeEls[ev.chair]) nodeEls[ev.chair].classList.add("meet");
        $("#roundtable").hidden = false;
        $("#rt-thread").innerHTML = "";
        $("#rt-sub").textContent =
          `${(ev.participants || []).join(", ")} — ${ev.rounds || 1} rounds of refinement over A2A`;
        logSys(`round-table opened by <span class="k">${escapeHtml(ev.chair)}</span> · ${escapeHtml((ev.participants || []).join(", "))}`, "meet");
      } else { if (nodeEls[ev.chair]) nodeEls[ev.chair].classList.remove("meet"); logSys("round-table closed", "meet"); }
      break;
    case "round":
      $("#roundtable").hidden = false;
      $("#rt-thread").appendChild(el("div", "rt-round", `Round ${ev.round} / ${ev.of}`));
      break;
    case "say":
      addRoundTableBubble(ev);
      break;
    case "summary":
      addSummaryCard(ev);
      break;
    case "cap": logSys(`cap hit (${escapeHtml(ev.kind)}): ${escapeHtml(ev.message)}`, "cap"); break;
  }
}
async function fetchLedgers() { if (!RUN) return; try { const s = await (await fetch(`/api/run-state?run=${RUN}`)).json(); renderLedgers(s.ledgers); } catch {} }

/* ---------- run ---------- */
function resetView() {
  for (const k in members) delete members[k];
  for (const k in nodeEls) delete nodeEls[k];
  for (const k in edgeEls) delete edgeEls[k];
  tally.messages = tally.headcount = tally.depth = tally.tokens = 0;
  $("#canvas").querySelectorAll(".node, .packet").forEach((n) => n.remove());
  $("#edges").innerHTML = "";
  $("#log").innerHTML = ""; $("#final-panel").hidden = true; $("#compare-panel").hidden = true;
  $("#roundtable").hidden = true; $("#rt-thread").innerHTML = "";
  $("#rt-summary").hidden = true; $("#rt-summary-grid").innerHTML = "";
  for (const k in _sumColorMap) delete _sumColorMap[k];
  renderGraph(); bumpMetrics();
}
function finish() { running = false; const g = $("#go"); g.disabled = false; g.classList.remove("running"); g.querySelector(".go-label").textContent = "Start mission"; }

async function run(mission, topology) {
  if (running) return; running = true; resetView();
  const g = $("#go"); g.disabled = true; g.classList.add("running"); g.querySelector(".go-label").textContent = "Running…";
  const r = await (await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mission, topology }) })).json();
  RUN = r.runId;
  const es = new EventSource(`/api/stream?run=${RUN}`);
  es.onmessage = (m) => { try { handle(JSON.parse(m.data)); } catch {} };
  const t = setInterval(() => { if (!running) { es.close(); clearInterval(t); } }, 500);
}

/* ---------- compare ---------- */
async function runCompare(mission) {
  if (running) return; running = true; resetView();
  $("#compare-panel").hidden = false;
  $("#compare-grid").innerHTML = '<p class="hint">Running the same mission under each topology…</p>';
  const g = $("#go"); g.disabled = true; g.classList.add("running"); g.querySelector(".go-label").textContent = "Comparing…";
  const cols = {};
  try {
    const r = await (await fetch("/api/compare", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mission }) })).json();
    r.runs.forEach((x) => { cols[x.topology] = { runId: x.runId, metrics: null, status: "queued" }; });
    renderCompare(cols);
    let done = false;
    while (!done) {
      done = true;
      for (const topo in cols) {
        if (cols[topo].status === "done") continue;
        const s = await (await fetch(`/api/run-state?run=${cols[topo].runId}`)).json();
        cols[topo].status = s.status || "running"; cols[topo].metrics = s.metrics;
        if (s.status !== "done") done = false;
      }
      renderCompare(cols);
      if (!done) await new Promise((z) => setTimeout(z, 700));
    }
  } catch (e) { $("#compare-grid").innerHTML = `<p class="hint">compare failed: ${escapeHtml(e.message)}</p>`; }
  finish();
}
function renderCompare(cols) {
  const order = ["hierarchical", "mesh", "group"].filter((t) => cols[t]);
  const labels = { hierarchical: "Hierarchical", mesh: "Mesh", group: "Group" };
  const rows = [["messages", "Messages"], ["tokens", "Tokens"], ["headcount", "Headcount"], ["maxDepth", "Max depth"], ["elapsedMs", "Elapsed"]];
  const best = {};
  ["messages", "elapsedMs"].forEach((k) => { let bt = null, bv = Infinity; order.forEach((t) => { const m = cols[t].metrics; if (m && m[k] < bv) { bv = m[k]; bt = t; } }); best[k] = bt; });
  let html = `<table class="ctable"><thead><tr><th></th>` +
    order.map((t) => `<th>${labels[t]} <span class="cst ${cols[t].status}">${cols[t].status}</span></th>`).join("") + `</tr></thead><tbody>`;
  for (const [k, lab] of rows) {
    html += `<tr><td class="ck">${lab}</td>` + order.map((t) => {
      const m = cols[t].metrics; if (!m) return "<td>–</td>";
      const v = (k === "elapsedMs") ? (m.elapsedMs / 1000).toFixed(1) + "s" : (typeof m[k] === "number" ? m[k].toLocaleString() : m[k]);
      return `<td class="${best[k] === t ? "win" : ""}">${v}</td>`;
    }).join("") + "</tr>";
  }
  html += `</tbody></table><p class="chint">Fewest <strong>messages</strong> = least coordination overhead; lowest <strong>elapsed</strong> = fastest. Same team throughout — only the wiring changed.</p>`;
  $("#compare-grid").innerHTML = html;
}

/* ---------- init ---------- */
function init() {
  loadStatus();
  $("#legend").innerHTML = [
    ["var(--teal)", "request"], ["var(--green)", "inform / accept"], ["var(--amber)", "propose"],
    ["var(--violet)", "cfp / query-ref"], ["var(--coral)", "refuse"]
  ].map(([c, l]) => `<span><i style="background:${c}"></i>${l}</span>`).join("");
  const chips = $("#examples");
  EXAMPLES.forEach((ex) => {
    const c = el("button", "chip", escapeHtml(ex)); c.type = "button";
    c.addEventListener("click", () => { $("#mission").value = ex; $("#mission").focus(); });
    chips.appendChild(c);
  });
  renderGraph();
  window.addEventListener("resize", layoutEdges);
  setTimeout(layoutEdges, 120);
  $("#run-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const mission = $("#mission").value.trim() || $("#mission").placeholder.replace(/^e\.g\.\s*/, "");
    const topo = $("#topology").value;
    if (topo === "compare") runCompare(mission); else run(mission, topo);
  });
}
document.addEventListener("DOMContentLoaded", init);
