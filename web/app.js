/* ATLAS // Signal Deck — front-end.
   A live org-chart graph (grows as agents are hired, with data packets flowing
   along the edges), a performative-tagged A2A signal feed, shared ledgers, live
   metrics and the final deliverable — all driven by the gateway's SSE telemetry.
   Topology is always GROUP (meetings). */
"use strict";

const $ = (s) => document.querySelector(s);
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SVGNS = "http://www.w3.org/2000/svg";
const nowt = () => { const d = new Date(); return d.toLocaleTimeString([], { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0"); };

const EXAMPLES = [
  "Design and spec a privacy-first smart doorbell",
  "Plan a weekend coffee festival for 5,000 attendees",
  "Write a go-to-market plan for an AI note-taking app",
  "Design a four-week beginner curriculum for learning Python",
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
    else { b.classList.add("mock"); b.textContent = "GROQ_API_KEY required"; }
    $("#caps").textContent =
      `caps · headcount ≤ ${s.caps.headcount} · depth ≤ ${s.caps.depth} · budget ${s.caps.tokenBudget.toLocaleString()} tokens · ${s.runtime} runtime`;
  } catch { $("#llm-badge").textContent = "gateway offline"; }
}

/* ---------- markdown + json highlight ---------- */
function mdToHtml(src) {
  const lines = String(src || "").replace(/\r/g, "").split("\n");
  let html = "", list = null;
  const close = () => { if (list) { html += `</${list}>`; list = null; } };
  const inl = (t) => esc(t)
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
  const json = esc(JSON.stringify(obj, null, 2));
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
  const m = members[id]; let c = "agent";
  if (id === "Board") c += " client";
  else if (m.parentId === "Board") c += " lead";
  const st = m.status;
  if (st === "working") c += " is-working";
  else if (st === "done") c += " is-done";
  else if (st === "error") c += " is-error";
  else if (st === "onboarded") c += " is-onboarded";
  return c;
}
function renderGraph() {
  relayout();
  const canvas = $("#canvas");
  for (const id of Object.keys(members)) {
    let node = nodeEls[id];
    if (!node) {
      node = el("div");
      node.innerHTML = `<div class="agent-top"><span class="agent-id"></span><span class="agent-tag"></span></div>
        <div class="agent-role"></div>
        <div class="agent-foot"><span class="pip"></span><span class="foot-txt"></span></div>`;
      canvas.appendChild(node); nodeEls[id] = node;
    }
    node.className = nodeClass(id);
    node.style.left = members[id].x + "%";
    node.style.top = members[id].y + "%";
    const tag = id === "Board" ? "YOU" : (members[id].parentId === "Board" ? "LEAD" : "");
    node.querySelector(".agent-id").textContent = id === "Board" ? "client" : id;
    node.querySelector(".agent-tag").textContent = tag;
    node.querySelector(".agent-tag").style.display = tag ? "" : "none";
    node.querySelector(".agent-role").textContent = members[id].role || id;
    node.querySelector(".foot-txt").textContent = members[id].status || "";
  }
  layoutEdges();
}
function center(id) { const c = $("#canvas"); return { x: (members[id].x / 100) * c.clientWidth, y: (members[id].y / 100) * c.clientHeight }; }
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
    e.packet.style.offsetPath = `path('${d}')`; e.packet.style.webkitOffsetPath = `path('${d}')`;
  }
}
function pulse(id) { const n = nodeEls[id]; if (!n) return; n.classList.remove("ping"); void n.offsetWidth; n.classList.add("ping"); setTimeout(() => n.classList.remove("ping"), 600); }

const EDGE_COLOR = { propose: "ember", "accept-proposal": "mint", inform: "mint", cfp: "violet", refuse: "rose" };
const PKT_COLOR = EDGE_COLOR;
function flowMessage(from, to, perf) {
  let childId = null, reverse = false;
  if (members[to] && members[to].parentId === from) childId = to;
  else if (members[from] && members[from].parentId === to) { childId = from; reverse = true; }
  if (childId && edgeEls[childId]) {
    const e = edgeEls[childId], ec = EDGE_COLOR[perf], pc = PKT_COLOR[perf];
    e.g.classList.remove("flowing", "ember", "violet", "mint", "rose"); void e.g.offsetWidth;
    e.g.classList.add("flowing"); if (ec) e.g.classList.add(ec);
    const p = e.packet;
    p.classList.remove("flowing", "ember", "violet", "mint", "rose"); void p.offsetWidth;
    p.style.animationDirection = reverse ? "reverse" : "normal";
    p.classList.add("flowing"); if (pc) p.classList.add(pc);
    setTimeout(() => { e.g.classList.remove("flowing", "ember", "violet", "mint", "rose"); p.classList.remove("flowing", "ember", "violet", "mint", "rose"); }, 1000);
  }
  pulse(to); if (members[from]) pulse(from);
}

/* ---------- signal feed ---------- */
function sigRow(inner, cls, ev) {
  const feed = $("#feed"); const e0 = feed.querySelector(".feed-empty"); if (e0) e0.remove();
  const row = el("div", "sig" + (cls ? " " + cls : ""));
  row.innerHTML = inner;
  if (ev) {
    row.style.cursor = "pointer";
    const jd = el("div", "sig-json"); jd.style.display = "none"; jd.innerHTML = highlightJson(ev);
    row.appendChild(jd);
    row.addEventListener("click", () => { jd.style.display = jd.style.display === "none" ? "block" : "none"; });
  }
  feed.appendChild(row); feed.scrollTop = feed.scrollHeight;
}
function logMessage(ev) {
  const perf = ev.performative || "sys";
  sigRow(`<div class="sig-head">
      <span class="sig-t">${nowt()}</span>
      <span class="sig-who">${esc(ev.fromRole || ev.from)}</span><span class="sig-arrow">→</span>
      <span class="sig-who">${esc(ev.toRole || ev.to)}</span>
      <span class="tag ${esc(perf)}">${esc(perf)}</span>
    </div>${ev.intent ? `<div class="sig-intent">${esc(ev.intent)}</div>` : ""}`, null, ev);
}
function logSys(text, cls) {
  sigRow(`<div class="sig-head"><span class="sig-t">${nowt()}</span>
    <span class="tag ${cls || "sys"}">${cls === "cap" ? "cap" : cls === "meet" ? "meeting" : "system"}</span>
    <span class="sig-msg">${text}</span></div>`, (cls || "sys"));
}

/* ---------- ledgers / metrics ---------- */
function renderLedgers(L) {
  if (!L) return;
  $("#ledger-panel").hidden = false;
  if (L.task) {
    $("#l-plan").textContent = L.task.plan || "—";
    $("#l-facts").innerHTML = (L.task.facts || []).map((f) => `<li>› ${esc(f)}</li>`).join("");
  }
  if (L.progress) {
    $("#l-steps").innerHTML = (L.progress.steps || []).map((s) =>
      `<li><span class="${s.status === "done" ? "ok" : "pend"}">${s.status === "done" ? "✓" : "…"}</span> ${esc(s.role)} — ${esc((s.task || "").slice(0, 44))}</li>`).join("");
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
      if (ev.phase === "started") logSys(`Mission deployed — <span class="k">${esc(ev.mission)}</span>`);
      else if (ev.phase === "done") {
        $("#final-panel").hidden = false; $("#final").innerHTML = mdToHtml(ev.final);
        if (ev.metrics) $("#m-elapsed").textContent = (ev.metrics.elapsedMs / 1000).toFixed(1) + "s";
        logSys("Mission complete ✓"); finish();
      } else if (ev.phase === "error") { logSys(esc(ev.message), "cap"); finish(); }
      break;
    case "hire":
      members[ev.agentId] = { role: ev.role, parentId: ev.parentId, depth: ev.depth, status: "hired" };
      tally.headcount++; renderGraph(); bumpMetrics();
      logSys(`hired <span class="k">${esc(ev.agentId)}</span> as ${esc(ev.role)} · depth ${ev.depth}`);
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
      if (ev.phase === "open") { if (nodeEls[ev.chair]) nodeEls[ev.chair].classList.add("meet");
        logSys(`meeting opened by <span class="k">${esc(ev.chair)}</span> · ${esc((ev.participants || []).join(", "))}`, "meet"); }
      else { if (nodeEls[ev.chair]) nodeEls[ev.chair].classList.remove("meet"); logSys("meeting closed", "meet"); }
      break;
    case "cap": logSys(`cap hit (${esc(ev.kind)}): ${esc(ev.message)}`, "cap"); break;
  }
}
async function fetchLedgers() { if (!RUN) return; try { const s = await (await fetch(`/api/run-state?run=${RUN}`)).json(); renderLedgers(s.ledgers); } catch {} }

/* ---------- run (always group) ---------- */
function resetView() {
  for (const k in members) delete members[k];
  for (const k in nodeEls) delete nodeEls[k];
  for (const k in edgeEls) delete edgeEls[k];
  tally.messages = tally.headcount = tally.depth = tally.tokens = 0;
  $("#canvas").querySelectorAll(".agent, .packet").forEach((n) => n.remove());
  $("#edges").innerHTML = "";
  $("#feed").innerHTML = ""; $("#final-panel").hidden = true;
  renderGraph(); bumpMetrics();
}
function finish() { running = false; const g = $("#go"); g.disabled = false; g.classList.remove("running"); g.querySelector(".go-label").textContent = "Deploy"; }

async function run(mission) {
  if (running) return; running = true; resetView();
  const g = $("#go"); g.disabled = true; g.classList.add("running"); g.querySelector(".go-label").textContent = "Running";
  const r = await (await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mission, topology: "group" }) })).json();
  RUN = r.runId;
  const es = new EventSource(`/api/stream?run=${RUN}`);
  es.onmessage = (m) => { try { handle(JSON.parse(m.data)); } catch {} };
  const t = setInterval(() => { if (!running) { es.close(); clearInterval(t); } }, 500);
}

/* ---------- init ---------- */
function init() {
  loadStatus();
  $("#legend").innerHTML = [
    ["var(--ice)", "request"], ["var(--mint)", "inform / accept"], ["var(--ember)", "propose"],
    ["var(--violet)", "cfp"], ["var(--rose)", "refuse"]
  ].map(([c, l]) => `<span><i style="background:${c}"></i>${l}</span>`).join("");
  const chips = $("#examples");
  EXAMPLES.forEach((ex) => {
    const c = el("button", "chip", esc(ex)); c.type = "button";
    c.addEventListener("click", () => { $("#mission").value = ex; $("#mission").focus(); });
    chips.appendChild(c);
  });
  renderGraph();
  window.addEventListener("resize", layoutEdges);
  setTimeout(layoutEdges, 120);
  $("#run-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const mission = $("#mission").value.trim() || $("#mission").placeholder.replace(/^.*?—\s*e\.g\.\s*/, "");
    run(mission);
  });
}
document.addEventListener("DOMContentLoaded", init);
