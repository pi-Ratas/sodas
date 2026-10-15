"use strict";
/* Vaivos dirbtuvės: a spectral study put together from parts (detalės) on a canvas.
 * The parts, their ports and data types come from the server (/api/vaiva/dirbtuves); a part is dragged from the list
 * on the left onto the canvas (or clicked: it is joined to the selected part), an output port is dragged to an input
 * port of the same type. „Tirti“ sends the setup to the server; its fruits are drawn by VIEWS[fruit.kind].
 * Uses the helpers of vaiva.js ($, esc, fmt, api, toast, tip, charts, V, follow, showRun). */

const W = {cat: null, parts: {}, types: {}, setup: {title: "", blocks: [], links: []}, sel: null, selLink: null,
  status: {}, view: {x: 30, y: 20, z: 1}, undo: [], redo: [], mode: "tyrimai", tab: "saranka", runId: null, n: 0};
// the canvas is kept on the server (sodas-duomenys/juodrasciai.json): it waits there for the next visit
const DRAFT_URL = "/api/vaiva/juodrastis";
const GROUP_CLASS = {"Šaltiniai": "g-src", "Matai": "g-measure", "Grafai": "g-graph", "Sietai": "g-filter",
  "Spektrinė analizė": "g-spec", "Rodikliai": "g-score", "Vaisiai": "g-view"};
const typeColor = t => `var(--t-${t && t !== "?" ? t : "any"})`;
const clone = o => JSON.parse(JSON.stringify(o));

// ---------------------------------------------------------------- types of ports
/** The type an output gives: declared, or for „=port“ the type of what feeds that input (unknown: "?"). */
function outType(blockId, port, seen = new Set()) {
  const b = W.setup.blocks.find(x => x.id === blockId), p = b && W.parts[b.type];
  const o = p && p.outputs.find(x => x.name === port);
  if (!o) return "?";
  const t = o.types[0];
  if (!t.startsWith("=")) return t;
  if (seen.has(blockId)) return "?";
  seen.add(blockId);
  const ln = W.setup.links.find(l => l.to[0] === blockId && l.to[1] === t.slice(1));
  return ln ? outType(ln.from[0], ln.from[1], seen) : "?";
}
function accepts(input, t) {
  if (t === "?") return true;
  if (input.types.includes("*")) return t !== "basket";
  return input.types.includes(t);
}
const typeName = t => t === "*" ? "bet kas su vienetais" : t === "?" ? "kaip įėjime" : (W.types[t]?.name || t);
const portTypes = p => p.types.map(t => t.startsWith("=") ? "kaip įėjime" : typeName(t)).join(" / ");

// ---------------------------------------------------------------- the setup: changes, undo, draft
function snapshot() { return clone({title: W.setup.title, blocks: W.setup.blocks, links: W.setup.links}); }
function change(fn, keepStatus = false) {
  W.undo.push(snapshot()); if (W.undo.length > 80) W.undo.shift();
  W.redo = [];
  fn();
  if (!keepStatus) W.status = {};
  saveDraft();
  draw();
}
function undo(back = true) {
  const from = back ? W.undo : W.redo, to = back ? W.redo : W.undo;
  if (!from.length) return;
  to.push(snapshot());
  W.setup = from.pop();
  W.status = {}; W.sel = null; W.selLink = null;
  saveDraft(); draw();
}
let draftTimer = null;
function saveDraft() { clearTimeout(draftTimer); draftTimer = setTimeout(sendDraft, 800); }
function sendDraft(keepalive = false) {
  clearTimeout(draftTimer); draftTimer = null;
  return fetch(DRAFT_URL, {method: "POST", keepalive, headers: {"Content-Type": "application/json"}, body: JSON.stringify({data: snapshot()})})
    .catch(() => {});
}
async function loadDraft() {
  try {
    const r = await fetch(DRAFT_URL);
    const d = r.ok ? (await r.json()).draft : null;
    if (d && d.data && Array.isArray(d.data.blocks)) return d.data;
  } catch (e) { /* server away: start from a ready setup */ }
  return null;
}
// a change made just before leaving the page still reaches the server
window.addEventListener("pagehide", () => { if (draftTimer) sendDraft(true); });
function setSetup(s, title) {
  const known = (s.blocks || []).filter(b => W.parts[b.type]);
  const ids = new Set(known.map(b => b.id));
  W.setup = {title: title ?? s.title ?? "", blocks: known.map(b => ({id: b.id, type: b.type, x: +b.x || 0, y: +b.y || 0,
      params: {...defaults(W.parts[b.type]), ...(b.params || {})}, note: b.note || ""})),
    links: (s.links || []).filter(l => ids.has(l.from[0]) && ids.has(l.to[0]))};
  W.n = Math.max(0, ...W.setup.blocks.map(b => +(String(b.id).match(/(\d+)$/) || [0, 0])[1]));
}
const defaults = p => Object.fromEntries(p.params.map(q => [q.name, q.default]));
function newId(type) { W.n += 1; let id = `${type}_${W.n}`; while (W.setup.blocks.some(b => b.id === id)) { W.n += 1; id = `${type}_${W.n}`; } return id; }

function addBlock(type, x, y, joinTo = null) {
  const p = W.parts[type];
  const id = newId(type);
  change(() => {
    W.setup.blocks.push({id, type, x: Math.round(x / 10) * 10, y: Math.round(y / 10) * 10, params: defaults(p), note: ""});
    if (joinTo) autoJoin(joinTo, id);
    W.sel = id; W.selLink = null;
  });
}
/** Joins a new part to the selected one: the first free input of the new part that takes one of its outputs. */
function autoJoin(fromId, toId) {
  const src = W.setup.blocks.find(b => b.id === fromId), dst = W.parts[W.setup.blocks.find(b => b.id === toId).type];
  if (!src) return;
  for (const inp of dst.inputs) {
    const out = W.parts[src.type].outputs.find(o => accepts(inp, outType(src.id, o.name)));
    if (out) { W.setup.links.push({from: [src.id, out.name], to: [toId, inp.name]}); return; }
  }
}
function removeBlock(id) {
  change(() => {
    W.setup.blocks = W.setup.blocks.filter(b => b.id !== id);
    W.setup.links = W.setup.links.filter(l => l.from[0] !== id && l.to[0] !== id);
    if (W.sel === id) W.sel = null;
  });
}
function connect(from, to) {
  change(() => {
    W.setup.links = W.setup.links.filter(l => !(l.to[0] === to[0] && l.to[1] === to[1]));
    W.setup.links.push({from, to});
  });
}

// ---------------------------------------------------------------- the page: modes and tabs
function setMode(mode, push = true) {
  W.mode = mode;
  document.body.classList.toggle("ws-mode", mode === "dirbtuves");
  $$(".mode-tabs [data-mode]").forEach(b => b.classList.toggle("on", b.dataset.mode === mode));
  if (mode === "dirbtuves") { setTab(W.tab); renderBasket(); }
  else { $("#workshop").hidden = true; $("#result").hidden = false; renderBasket(); }
  $("#barNote").textContent = mode === "dirbtuves" ? "Vaivos dirbtuvės – sąranka iš detalių" : `Vaivos dirbtuvės – ${currentStudy()?.title || ""}`;
  if (push) {
    const u = new URL(location.href);
    if (mode === "dirbtuves") u.searchParams.set("dirbtuves", "1"); else u.searchParams.delete("dirbtuves");
    history.replaceState(null, "", u);
  }
}
function setTab(tab) {
  W.tab = tab;
  $$("#wsTabs [data-tab]").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
  $("#workshop").hidden = tab !== "saranka";
  $("#result").hidden = tab !== "vaisiai";
  if (tab === "saranka") draw();
}

// ---------------------------------------------------------------- palette and recipes (left)
function renderPalette() {
  const q = ($("#partFilter").value || "").trim().toLowerCase();
  const parts = W.cat.parts.filter(p => !q || `${p.title} ${p.summary} ${p.group}`.toLowerCase().includes(q));
  $("#palette").innerHTML = W.cat.groups.map(g => {
    const mine = parts.filter(p => p.group === g);
    if (!mine.length) return "";
    return `<details class="pal-group ${GROUP_CLASS[g]}" ${q || g === "Šaltiniai" ? "open" : ""}><summary>${esc(g)} <span class="muted">${mine.length}</span></summary>
      ${mine.map(p => `<div class="pal-item" draggable="true" data-part="${esc(p.id)}" title="${esc(p.summary)}">
        <span class="pal-t">${esc(p.title)}</span>
        <span class="pal-io">${p.inputs.map(i => `<i class="tdot ${i.optional ? "opt" : ""}" style="--t:${typeColor(i.types[0].startsWith("=") ? "?" : i.types[0] === "*" ? "any" : i.types[0])}"></i>`).join("")}${p.outputs.length ? "→" : ""}${p.outputs.map(o => `<i class="tdot" style="--t:${typeColor(o.types[0].startsWith("=") ? "?" : o.types[0])}"></i>`).join("")}</span></div>`).join("")}
    </details>`;
  }).join("") || `<p class="muted small">Nieko nerasta.</p>`;
  $$("#palette .pal-item").forEach(el => {
    el.addEventListener("dragstart", ev => { ev.dataTransfer.setData("text/vaiva-part", el.dataset.part); ev.dataTransfer.effectAllowed = "copy"; });
    el.addEventListener("click", () => addNear(el.dataset.part));
  });
}
/** Click in the list: next to the selected part (and joined to it), else in the middle of the view. */
function addNear(type) {
  if (W.mode !== "dirbtuves") setMode("dirbtuves");
  setTab("saranka");
  const sel = W.setup.blocks.find(b => b.id === W.sel);
  if (sel) {
    let x = sel.x + 260, y = sel.y;
    while (W.setup.blocks.some(b => Math.abs(b.x - x) < 200 && Math.abs(b.y - y) < 90)) y += 100;
    addBlock(type, x, y, sel.id);
  } else {
    const r = $("#wsCanvas").getBoundingClientRect();
    const x = (r.width / 2 - W.view.x) / W.view.z - 100;
    let y = (r.height / 4 - W.view.y) / W.view.z;
    while (W.setup.blocks.some(b => Math.abs(b.x - x) < 220 && Math.abs(b.y - y) < 100)) y += 110;
    addBlock(type, x, y);
  }
}
function renderRecipes() {
  $("#recipes").innerHTML = W.cat.recipes.map(r => `<div class="recipe" data-r="${esc(r.id)}" title="${esc(r.summary)}">
      <span class="t">${esc(r.title)}</span><span class="m">${esc(r.summary)}</span></div>`).join("");
  $$("#recipes [data-r]").forEach(el => el.onclick = () => {
    const r = W.cat.recipes.find(x => x.id === el.dataset.r);
    setMode("dirbtuves"); setTab("saranka");
    change(() => { setSetup(r.setup, r.title); W.sel = null; });
    fitView();
    toast(`Įkelta sąranka „${r.title}“. Ctrl+Z – grąžinti ankstesnę.`);
  });
}

// ---------------------------------------------------------------- the canvas
const canvas = () => $("#wsCanvas"), world = () => $("#wsWorld");
function applyView() {
  world().style.transform = `translate(${W.view.x}px, ${W.view.y}px) scale(${W.view.z})`;
  $("#wsZoom").textContent = `${Math.round(W.view.z * 100)} %`;
  canvas().style.backgroundPosition = `${W.view.x}px ${W.view.y}px`;
  canvas().style.backgroundSize = `${20 * W.view.z}px ${20 * W.view.z}px`;
}
function toWorld(cx, cy) { const r = canvas().getBoundingClientRect(); return [(cx - r.left - W.view.x) / W.view.z, (cy - r.top - W.view.y) / W.view.z]; }
function fitView() {
  const bs = W.setup.blocks;
  if (!bs.length) { W.view = {x: 30, y: 20, z: 1}; applyView(); return; }
  const r = canvas().getBoundingClientRect();
  const x0 = Math.min(...bs.map(b => b.x)), y0 = Math.min(...bs.map(b => b.y)), x1 = Math.max(...bs.map(b => b.x)) + 230, y1 = Math.max(...bs.map(b => b.y)) + 140;
  const z = Math.max(.35, Math.min(1.2, Math.min((r.width - 40) / (x1 - x0), (r.height - 40) / (y1 - y0))));
  W.view = {z, x: 20 - x0 * z + Math.max(0, (r.width - 40 - (x1 - x0) * z) / 2), y: 20 - y0 * z};
  applyView();
}
function zoomAt(f, cx, cy) {
  const r = canvas().getBoundingClientRect(), z = Math.max(.3, Math.min(1.8, W.view.z * f));
  const px = (cx ?? r.left + r.width / 2) - r.left, py = (cy ?? r.top + r.height / 2) - r.top;
  W.view.x = px - (px - W.view.x) * z / W.view.z; W.view.y = py - (py - W.view.y) * z / W.view.z; W.view.z = z;
  applyView(); drawLinks();
}

function blockHtml(b) {
  const p = W.parts[b.type], st = W.status[b.id];
  const linked = new Set(W.setup.links.filter(l => l.to[0] === b.id).map(l => l.to[1]));
  const ins = p.inputs.map(i => `<div class="wb-port in ${linked.has(i.name) ? "linked" : !i.optional ? "need" : ""}" data-port="${esc(i.name)}"
      title="${esc(`${i.label}: ${portTypes(i)}${i.optional ? " (nebūtina)" : ""}${i.help ? " – " + i.help : ""}`)}">
      <i class="dot" style="--t:${typeColor(i.types[0] === "*" ? "any" : i.types[0])}"></i><span>${esc(i.label)}${i.optional ? " <em>·</em>" : ""}</span></div>`).join("");
  const outs = p.outputs.map(o => { const t = outType(b.id, o.name);
    return `<div class="wb-port out" data-port="${esc(o.name)}" title="${esc(`${o.label}: ${typeName(t)}`)}"><span>${esc(o.label)}</span><i class="dot" style="--t:${typeColor(t)}"></i></div>`; }).join("");
  const sum = st ? (st.status === "ok" ? `${st.summary || ""}${st.dropped ? ` · neįtraukta ${st.dropped}` : ""}${st.cached ? " · iš atminties" : ""}`
    : st.status === "skipped" ? "praleista: laukia nepavykusios detalės" : st.error) : (p.view && b.note ? b.note : "");
  return `<div class="wb-block ${GROUP_CLASS[p.group]} ${W.sel === b.id ? "sel" : ""} ${st ? "st-" + st.status : ""}" data-id="${esc(b.id)}"
      style="left:${b.x}px;top:${b.y}px">
    <div class="wb-head"><span class="wb-title">${esc(p.title)}</span><button class="wb-x" title="Pašalinti detalę">×</button></div>
    <div class="wb-ports">${ins}${outs}</div>
    ${sum ? `<div class="wb-sum" title="${esc(sum)}">${esc(sum)}</div>` : ""}</div>`;
}
function draw() {
  if (!W.cat || W.mode !== "dirbtuves") return;
  const w = world();
  w.querySelectorAll(".wb-block").forEach(el => el.remove());
  w.insertAdjacentHTML("beforeend", W.setup.blocks.map(blockHtml).join(""));
  $("#wsEmpty").hidden = W.setup.blocks.length > 0;
  $("#wsTitle").value = W.setup.title || "";
  $("#wsUndo").disabled = !W.undo.length;
  applyView();
  drawLinks();
  renderInspector();
}
function dotCenter(blockId, port, side) {
  const el = world().querySelector(`.wb-block[data-id="${CSS.escape(blockId)}"] .wb-port.${side}[data-port="${CSS.escape(port)}"] .dot`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return toWorld(r.left + r.width / 2, r.top + r.height / 2);
}
const curve = ([x1, y1], [x2, y2]) => { const dx = Math.max(40, Math.abs(x2 - x1) / 2); return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`; };
function drawLinks() {
  const svg = $("#wsLinks");
  svg.innerHTML = W.setup.links.map((l, i) => {
    const a = dotCenter(l.from[0], l.from[1], "out"), b = dotCenter(l.to[0], l.to[1], "in");
    if (!a || !b) return "";
    const d = curve(a, b), t = outType(l.from[0], l.from[1]);
    return `<path class="wl-hit" d="${d}" data-l="${i}"/><path class="wl ${W.selLink === i ? "sel" : ""}" d="${d}" style="--t:${typeColor(t)}" data-l="${i}"/>`;
  }).join("") + `<path id="wsTemp" class="wl temp" d=""/>`;
  svg.querySelectorAll("[data-l]").forEach(p => p.addEventListener("pointerdown", ev => {
    ev.stopPropagation(); W.selLink = +p.dataset.l; W.sel = null; drawLinks(); renderInspector();
    world().querySelectorAll(".wb-block.sel").forEach(e => e.classList.remove("sel"));
  }));
}

/** Pointer gestures on the canvas: pan the empty canvas, move a part by its head, draw a link from an output. */
function bindCanvas() {
  const cv = canvas();
  let drag = null;
  cv.addEventListener("pointerdown", ev => {
    if (ev.button !== 0) return;
    const blockEl = ev.target.closest(".wb-block"), port = ev.target.closest(".wb-port");
    if (ev.target.closest(".wb-x")) { removeBlock(blockEl.dataset.id); return; }
    if (port && blockEl && ev.target.classList.contains("dot") || port && port.classList.contains("out")) {
      const id = blockEl.dataset.id;
      if (port.classList.contains("in")) {           // pick up an existing link at its end
        const ln = W.setup.links.find(l => l.to[0] === id && l.to[1] === port.dataset.port);
        if (!ln) return;
        change(() => { W.setup.links = W.setup.links.filter(l => l !== ln); }, true);
        drag = {kind: "link", from: ln.from};
      } else drag = {kind: "link", from: [id, port.dataset.port]};
      drag.t = outType(drag.from[0], drag.from[1]);
      markTargets(drag);
      cv.setPointerCapture(ev.pointerId);
      ev.preventDefault();
      return;
    }
    if (blockEl) {
      const id = blockEl.dataset.id;
      if (W.sel !== id) { W.sel = id; W.selLink = null; world().querySelectorAll(".wb-block").forEach(e => e.classList.toggle("sel", e.dataset.id === id)); drawLinks(); renderInspector(); }
      if (!ev.target.closest(".wb-head")) return;
      const b = W.setup.blocks.find(x => x.id === id), [wx, wy] = toWorld(ev.clientX, ev.clientY);
      drag = {kind: "move", id, dx: wx - b.x, dy: wy - b.y, before: snapshot(), moved: false};
      cv.setPointerCapture(ev.pointerId);
      return;
    }
    W.sel = null; W.selLink = null;
    world().querySelectorAll(".wb-block.sel").forEach(e => e.classList.remove("sel"));
    drawLinks(); renderInspector();
    drag = {kind: "pan", x: ev.clientX - W.view.x, y: ev.clientY - W.view.y};
    cv.setPointerCapture(ev.pointerId);
    cv.classList.add("panning");
  });
  cv.addEventListener("pointermove", ev => {
    if (!drag) return;
    if (drag.kind === "pan") { W.view.x = ev.clientX - drag.x; W.view.y = ev.clientY - drag.y; applyView(); return; }
    const [wx, wy] = toWorld(ev.clientX, ev.clientY);
    if (drag.kind === "move") {
      const b = W.setup.blocks.find(x => x.id === drag.id);
      b.x = Math.round((wx - drag.dx) / 10) * 10; b.y = Math.round((wy - drag.dy) / 10) * 10;
      drag.moved = true;
      const el = world().querySelector(`.wb-block[data-id="${CSS.escape(drag.id)}"]`);
      el.style.left = b.x + "px"; el.style.top = b.y + "px";
      drawLinks();
    } else if (drag.kind === "link") {
      const a = dotCenter(drag.from[0], drag.from[1], "out");
      if (a) $("#wsTemp").setAttribute("d", curve(a, [wx, wy]));
      $("#wsTemp").style.setProperty("--t", typeColor(drag.t));
    }
  });
  const end = ev => {
    if (!drag) return;
    const d = drag; drag = null;
    cv.classList.remove("panning");
    if (d.kind === "move" && d.moved) {
      W.undo.push(d.before); W.redo = []; saveDraft(); $("#wsUndo").disabled = false;
    } else if (d.kind === "link") {
      clearTargets();
      $("#wsTemp")?.setAttribute("d", "");
      const el = document.elementFromPoint(ev.clientX, ev.clientY)?.closest(".wb-port.in");
      const blockEl = el?.closest(".wb-block");
      if (el && blockEl && blockEl.dataset.id !== d.from[0]) {
        const p = W.parts[W.setup.blocks.find(b => b.id === blockEl.dataset.id).type], inp = p.inputs.find(i => i.name === el.dataset.port);
        if (accepts(inp, d.t)) connect(d.from, [blockEl.dataset.id, inp.name]);
        else toast(`Į „${inp.label}“ tinka ${portTypes(inp)}, o čia – ${typeName(d.t)}.`, "warning");
      } else draw();
    }
  };
  cv.addEventListener("pointerup", end);
  cv.addEventListener("pointercancel", end);
  cv.addEventListener("wheel", ev => { ev.preventDefault(); zoomAt(ev.deltaY < 0 ? 1.1 : 1 / 1.1, ev.clientX, ev.clientY); }, {passive: false});
  cv.addEventListener("dragover", ev => { if (ev.dataTransfer.types.includes("text/vaiva-part")) { ev.preventDefault(); ev.dataTransfer.dropEffect = "copy"; } });
  cv.addEventListener("drop", ev => {
    const type = ev.dataTransfer.getData("text/vaiva-part");
    if (!type || !W.parts[type]) return;
    ev.preventDefault();
    const [x, y] = toWorld(ev.clientX, ev.clientY);
    addBlock(type, x - 20, y - 15);
  });
  document.addEventListener("keydown", ev => {
    if (W.mode !== "dirbtuves" || W.tab !== "saranka" || ev.target.closest("input, textarea, select")) return;
    if ((ev.key === "Delete" || ev.key === "Backspace") && (W.sel || W.selLink != null)) {
      ev.preventDefault();
      if (W.sel) removeBlock(W.sel);
      else change(() => { W.setup.links.splice(W.selLink, 1); W.selLink = null; });
    } else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z") { ev.preventDefault(); undo(!ev.shiftKey); }
    else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "y") { ev.preventDefault(); undo(false); }
    else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "d" && W.sel) { ev.preventDefault(); duplicate(W.sel); }
  });
}
function markTargets(d) {
  world().querySelectorAll(".wb-port.in").forEach(el => {
    const bid = el.closest(".wb-block").dataset.id, p = W.parts[W.setup.blocks.find(b => b.id === bid).type];
    const inp = p.inputs.find(i => i.name === el.dataset.port);
    el.classList.toggle("target", bid !== d.from[0] && accepts(inp, d.t));
    el.classList.toggle("nope", bid === d.from[0] || !accepts(inp, d.t));
  });
  canvas().classList.add("linking");
}
function clearTargets() {
  world().querySelectorAll(".wb-port.in").forEach(el => el.classList.remove("target", "nope"));
  canvas().classList.remove("linking");
}
function duplicate(id) {
  const b = W.setup.blocks.find(x => x.id === id);
  if (!b) return;
  const nid = newId(b.type);
  change(() => { W.setup.blocks.push({...clone(b), id: nid, x: b.x + 30, y: b.y + 40}); W.sel = nid; });
}

// ---------------------------------------------------------------- inspector (right)
function renderInspector() {
  const box = $("#wsInspector");
  if (W.selLink != null && W.setup.links[W.selLink]) {
    const l = W.setup.links[W.selLink], t = outType(l.from[0], l.from[1]);
    const name = id => W.parts[W.setup.blocks.find(b => b.id === id)?.type]?.title || id;
    box.innerHTML = `<h3>Jungtis</h3><p class="small">${esc(name(l.from[0]))} → ${esc(name(l.to[0]))}</p>
      <p class="small"><i class="tdot" style="--t:${typeColor(t)}"></i> <span>${esc(typeName(t))}</span> – <span>${esc(W.types[t]?.explain || "")}</span></p>
      <button id="wsDelLink">Pašalinti jungtį</button><p class="muted small">Arba klavišas Delete.</p>`;
    $("#wsDelLink").onclick = () => change(() => { W.setup.links.splice(W.selLink, 1); W.selLink = null; });
    return;
  }
  const b = W.setup.blocks.find(x => x.id === W.sel);
  if (!b) {
    box.innerHTML = `<h3>Kaip dirbti</h3>
      <ol class="small guide"><li>Nutempkite detalę iš sąrašo kairėje į drobę (arba spustelėkite: ji bus prijungta prie pažymėtos).</li>
        <li>Sujunkite: tempkite nuo išėjimo taškelio dešinėje iki tos pačios spalvos įėjimo kairėje. Tinkami įėjimai paryškinami.</li>
        <li>Spustelėję detalę, dešinėje nustatykite jos parametrus.</li>
        <li>Prijunkite bent vieną vaisių ir spauskite „Tirti“.</li></ol>
      <p class="muted small">Pradėti paprasčiausia nuo paruoštos sąrankos kairėje. Tempiant tuščią drobę – stumdoma, pelės ratukas – mastelis,
        Delete – pašalinti, Ctrl+Z – atšaukti, Ctrl+D – kopija.</p>
      <h3>Duomenų tipai</h3>
      <div class="types">${Object.entries(W.types).map(([k, t]) => `<div class="small"><i class="tdot" style="--t:${typeColor(k)}"></i><b>${esc(t.name)}</b> – <span>${esc(t.explain)}</span></div>`).join("")}</div>`;
    return;
  }
  const p = W.parts[b.type], st = W.status[b.id];
  box.innerHTML = `<h3>${esc(p.title)}</h3><p class="muted small">${esc(p.group)}</p><p class="small">${esc(p.summary)}</p>
    ${p.help ? `<p class="param-help">${esc(p.help)}</p>` : ""}
    ${st ? `<div class="ws-status st-${st.status} small">${st.status === "ok" ? `✓ ${esc(st.summary || "")}${st.seconds != null ? ` · ${fmt(st.seconds, 1)} s` : ""}${st.cached ? " · iš atminties" : ""}`
      : st.status === "skipped" ? "Praleista: laukia nepavykusios detalės." : `✗ ${esc(st.error)}`}
      ${st.dropped ? `<br>Neįtraukta vienetų: ${st.dropped} (žr. vaisių apačioje)` : ""}
      ${(st.notes || []).map(n => `<br>${esc(n)}`).join("")}
      ${st.trace ? `<details><summary>Techninė informacija</summary><pre>${esc(st.trace)}</pre></details>` : ""}</div>` : ""}
    <div id="wsParams">${p.params.map(q => paramRow(q, b.params[q.name])).join("")}</div>
    ${p.view ? `<label class="param">Antraštė vaisiui<input type="text" id="wsNote" value="${esc(b.note || "")}" placeholder="${esc(p.title)}"></label>` : ""}
    <h4>Įėjimai</h4>${p.inputs.length ? p.inputs.map(i => `<div class="small io"><i class="tdot" style="--t:${typeColor(i.types[0] === "*" ? "any" : i.types[0])}"></i>
      <b>${esc(i.label)}</b> – <span>${esc(portTypes(i))}</span>${i.optional ? ` <span>(nebūtina)</span>` : ""}${i.help ? `<br><span class="muted">${esc(i.help)}</span>` : ""}</div>`).join("") : `<p class="muted small">nėra</p>`}
    ${p.outputs.length ? `<h4>Išėjimai</h4>${p.outputs.map(o => { const t = outType(b.id, o.name);
      return `<div class="small io"><i class="tdot" style="--t:${typeColor(t)}"></i><b>${esc(o.label)}</b> – <span>${esc(typeName(t))}</span></div>`; }).join("")}` : ""}
    <div class="ws-actions"><button id="wsDup" title="Ctrl+D">Kopija</button><button id="wsDel">Pašalinti</button></div>`;
  box.querySelectorAll("[data-wp]").forEach(el => el.onchange = () => {
    const q = p.params.find(x => x.name === el.dataset.wp);
    const v = el.type === "checkbox" ? el.checked : q.type === "number" ? (el.value === "" ? null : Number(el.value)) : el.value;
    change(() => { b.params[q.name] = v; });
  });
  box.querySelectorAll("[data-help]").forEach(btn => btn.onclick = () => {
    const h = box.querySelector(`[data-help-of="${btn.dataset.help}"]`);
    h.hidden = !h.hidden; btn.classList.toggle("on", !h.hidden);
  });
  if ($("#wsNote")) $("#wsNote").onchange = e => change(() => { b.note = e.target.value.trim(); }, true);
  $("#wsDup").onclick = () => duplicate(b.id);
  $("#wsDel").onclick = () => removeBlock(b.id);
}
function paramRow(q, v) {
  const input = q.type === "bool" ? `<label class="param bool"><input type="checkbox" data-wp="${q.name}" ${v ? "checked" : ""}> ${esc(q.label)}</label>`
    : q.type === "select" ? `<label class="param">${esc(q.label)}<select data-wp="${q.name}">${q.options.map(([o, t]) =>
        `<option value="${esc(o)}" ${o === v ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`
    : q.type === "text" ? `<label class="param">${esc(q.label)}<input type="text" data-wp="${q.name}" value="${esc(v ?? "")}" placeholder="${esc(q.hint || "")}"></label>`
    : `<label class="param">${esc(q.label)}<input type="number" data-wp="${q.name}" min="${q.min ?? ""}" max="${q.max ?? ""}" step="any" value="${v ?? ""}" placeholder="${esc(q.hint || "")}"></label>`;
  return `<div class="param-row"><div class="pl">${input}${q.help ? `<button type="button" class="help-btn" data-help="${q.name}" title="Ką reiškia šis parametras">?</button>` : ""}</div>
    ${q.help ? `<div class="param-help" data-help-of="${q.name}" hidden>${paramHelp(q)}</div>` : ""}</div>`;
}

// ---------------------------------------------------------------- running
function problems() {
  const out = [];
  if (!W.setup.blocks.some(b => W.parts[b.type].view)) out.push("Prijunkite bent vieną vaisių (grupė „Vaisiai“).");
  for (const b of W.setup.blocks) {
    const p = W.parts[b.type];
    const miss = p.inputs.filter(i => !i.optional && !W.setup.links.some(l => l.to[0] === b.id && l.to[1] === i.name));
    if (miss.length) out.push(`„${p.title}“: neprijungta ${miss.map(i => `„${i.label}“`).join(", ")}.`);
  }
  return out;
}
async function runSetup() {
  const bad = problems();
  if (bad.length) {
    toast(bad[0] + (bad.length > 1 ? ` (ir dar ${bad.length - 1})` : ""), "warning", 7000);
    world().querySelectorAll(".wb-port.need").forEach(el => el.classList.add("blink"));
    setTimeout(() => world().querySelectorAll(".blink").forEach(el => el.classList.remove("blink")), 1600);
    if (!W.setup.blocks.some(b => W.parts[b.type].view)) return;
  }
  const title = W.setup.title.trim();
  const nodes = V.basket.filter(b => b.on).map(({label, key, display_name}) => ({label, key, display_name}));
  const r = await api("/api/vaiva/run", {study: "dirbtuves", nodes, name: title || "Dirbtuvių sąranka",
    params: {title: title || null, setup: {blocks: W.setup.blocks, links: W.setup.links}}});
  W.runId = r.id;
  W.status = {};
  draw();
  follow(r.id);
}

// ---------------------------------------------------------------- a run of the workshop: its fruits
function renderWorkshopRun(run, root) {
  const R = run.result;
  setMode("dirbtuves");
  const same = JSON.stringify(normal(R.setup)) === JSON.stringify(normal(W.setup));
  const keep = W.keepDraft && !same;      // opened by itself when the page loads: the unsaved setup on the canvas stays
  W.keepDraft = false;
  if (!same && !keep) { W.undo.push(snapshot()); setSetup(R.setup, run.name); saveDraft(); }
  W.status = keep ? {} : R.blocks || {};
  W.runId = run.id;
  setTab(R.fruits.length ? "vaisiai" : "saranka");     // first: the maps measure their box when drawn
  const date = (run.finished_at || run.started_at || "").slice(0, 16).replace("T", " ");
  const errs = Object.entries(R.blocks || {}).filter(([, s]) => s.status !== "ok");
  const name = id => { const b = R.setup.blocks.find(x => x.id === id); return b ? W.parts[b.type]?.title || b.type : id; };
  root.innerHTML = `<div class="viz-root">
    <div class="r-head"><h1>${esc(run.name)}</h1>
      <div class="sub">Vaivos dirbtuvės · ${esc(date)} · ${R.summary.blocks} detalių, ${R.summary.fruits} vaisių
        ${run.nodes?.length ? ` · krepšys: ${run.nodes.slice(0, 4).map(n => esc(n.display_name || n.key)).join(", ")}${run.nodes.length > 4 ? "…" : ""}` : " · be krepšio"}</div></div>
    ${errs.length ? `<div class="finding warn"><h4>${errs.length} detalės nepavyko ar praleistos</h4><p>${errs.slice(0, 8).map(([id, s]) =>
      `<b>${esc(name(id))}</b>: ${esc(s.error || "laukia nepavykusios detalės")}`).join("<br>")}</p>
      <p><button data-goto="saranka">Atverti sąranką</button></p></div>` : ""}
    ${R.fruits.length ? `<nav class="fruit-nav">${R.fruits.map(f => `<a href="#fruit-${esc(f.block)}">${esc(f.title)}</a>`).join("")}</nav>` : ""}
    <div id="fruits"></div>
    ${R.dropped?.length ? `<div class="block"><h2>Kas neįtraukta (${R.dropped.length})</h2>
      <div class="toolbar"><input type="search" id="dropFilter" placeholder="filtruoti: vienetas, priežastis, detalė…"></div>
      <div class="tablebox" id="dropTable"></div></div>` : ""}
  </div>`;
  const box = root.querySelector("#fruits");
  for (const f of R.fruits) {
    const el = document.createElement("div");
    el.className = "block fruit";
    el.id = `fruit-${f.block}`;
    el.innerHTML = `<h2>${esc(f.title)} <button class="link-btn small" data-show="${esc(f.block)}" title="Parodyti šią detalę sąrankoje">⚙</button></h2>
      ${f.tiles?.length ? `<div class="tiles">${f.tiles.map(t => `<div class="tile"><div class="v">${esc(t.v)}</div><div class="l">${esc(t.l)}</div></div>`).join("")}</div>` : ""}
      <div class="fruit-body"></div>
      ${(f.notes || []).map(n => `<div class="finding">${n.title ? `<h4>${esc(n.title)}</h4>` : ""}<p>${sentences(n.text)}</p></div>`).join("")}`;
    box.append(el);
    const draw = VIEWS[f.kind];
    try { if (draw) draw(f.data, el.querySelector(".fruit-body"), f, run); else el.querySelector(".fruit-body").innerHTML = `<p class="muted">Šio vaisiaus piešimo nėra (${esc(f.kind)}).</p>`; }
    catch (e) { el.querySelector(".fruit-body").innerHTML = `<p class="neg">Nepavyko nupiešti: ${esc(e.message)}</p>`; console.error(e); }
  }
  if (R.dropped?.length) {
    const rows = R.dropped.map(d => ({t: [d.name, d.reason, d.part, d.detail].join(" ").toLowerCase(),
      r: [cell(esc(d.name), d.name), cell(esc(d.reason), d.reason), cell(esc(d.part), d.part), cell(`<span class="muted">${esc(d.detail || "")}</span>`, d.detail || "")]}));
    const head = [{t: "vienetas"}, {t: "priežastis"}, {t: "detalė"}, {t: "paaiškinimas"}];
    const drawDrop = q => sortableTable(root.querySelector("#dropTable"), head, rows.filter(x => !q || x.t.includes(q)).map(x => x.r));
    drawDrop("");
    root.querySelector("#dropFilter").oninput = e => drawDrop(e.target.value.trim().toLowerCase());
  }
  root.querySelectorAll("[data-show]").forEach(b => b.onclick = () => { W.sel = b.dataset.show; setTab("saranka"); });
  root.querySelectorAll("[data-goto]").forEach(b => b.onclick = () => setTab("saranka"));
  bindTips(root);
}
/** A note's text: one text or a list of sentences, each its own element (so each is translated as a whole). */
const sentences = t => (Array.isArray(t) ? t : [t]).filter(Boolean).map(x => `<span>${esc(x)}</span>`).join(" ");
const normal = s => ({blocks: (s.blocks || []).map(b => ({id: b.id, type: b.type, params: b.params})), links: s.links || []});
RENDERERS.dirbtuves = renderWorkshopRun;

// ---------------------------------------------------------------- views of fruits
const gColor = g => g == null ? cssVar("--series-other") : clusterColor(g);
const gChip = (g, groups) => g == null ? "" : `<span class="num" style="--c:${gColor(g)}">${g + 1}</span>`;
function legendHtml(groups, cls = "") {
  return `<div class="chips ${cls}">${groups.slice(0, 40).map((g, i) => `<span class="chip" data-g="${i}">${gChip(i)} ${esc(g.name)} · ${g.size}</span>`).join("")}
    ${groups.length > 40 ? `<span class="muted small">dar ${groups.length - 40}</span>` : ""}</div>`;
}

const VIEWS = {
  zemelapis(D, el, f) {
    const canGarden = D.points.some(p => p.label);
    el.innerHTML = `<div class="toolbar">${canGarden ? `<button class="toGarden">Atverti sode</button>` : ""}
        ${D.edges.length ? `<label class="small"><input type="checkbox" class="nn" checked> artimiausio kaimyno ryšiai</label>` : ""}
        <label class="small"><input type="checkbox" class="lb" ${D.points.length <= 300 ? "checked" : ""}> užrašai</label>
        <span class="muted small">${esc(D.layout || "")}${D.grouping ? ` · spalvos: ${esc(D.grouping)}` : ""}</span></div>
      ${D.groups.length ? legendHtml(D.groups) : ""}<div class="map"></div>`;
    const ink = cssVar("--ink") || "#222", bg = cssVar("--graph-bg") || "#fff", line = cssVar("--line") || "#ccc", scale = 420;
    const els = D.points.map((p, i) => ({group: "nodes", data: {id: "p" + i, i, name: p.name, g: p.g, color: gColor(p.g)}, position: {x: p.x * scale, y: -p.y * scale}}));
    D.edges.forEach(([a, b], k) => els.push({group: "edges", data: {id: "e" + k, source: "p" + a, target: "p" + b}}));
    const cy = cytoscape({container: el.querySelector(".map"), elements: els, layout: {name: "preset", fit: true, padding: 30}, wheelSensitivity: .25,
      style: [{selector: "node", style: {"background-color": "data(color)", width: 12, height: 12, "border-width": 2, "border-color": bg, label: "data(name)",
          "font-size": 9, color: ink, "text-valign": "top", "text-margin-y": -3, "text-background-color": bg, "text-background-opacity": .7, "text-background-padding": 1}},
        {selector: "edge", style: {width: 1, "line-color": line, "curve-style": "straight", opacity: .8}},
        {selector: ".dim", style: {opacity: .12}}, {selector: ".nolabel", style: {label: ""}}]});
    if (D.points.length > 300) cy.nodes().addClass("nolabel");
    cy.on("mouseover", "node", e => { const p = D.points[e.target.data("i")];
      tip(`<b>${esc(p.name)}</b>${p.g != null ? ` · ${esc(D.groups[p.g].name)}` : ""}<br>${Object.entries(p.info).slice(0, 8).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join("<br>")}`, e.originalEvent); });
    cy.on("mousemove", "node", e => tip($("#tip").innerHTML, e.originalEvent));
    cy.on("mouseout", "node", () => tip(null));
    let focus = null;
    el.querySelectorAll("[data-g]").forEach(ch => ch.onclick = () => {
      const g = +ch.dataset.g; focus = focus === g ? null : g;
      el.querySelectorAll("[data-g]").forEach(x => x.classList.toggle("off", focus != null && +x.dataset.g !== focus));
      cy.nodes().forEach(n => n.toggleClass("dim", focus != null && n.data("g") !== focus));
      cy.edges().forEach(e => e.toggleClass("dim", focus != null && (e.source().data("g") !== focus || e.target().data("g") !== focus)));
    });
    el.querySelector(".nn")?.addEventListener("change", e => cy.edges().style("display", e.target.checked ? "element" : "none"));
    el.querySelector(".lb").onchange = e => cy.nodes().toggleClass("nolabel", !e.target.checked);
    el.querySelector(".toGarden")?.addEventListener("click", () => mapToGarden(D, f));
  },

  savosios(D, el) {
    const vals = D.values.slice(0, 16);
    el.innerHTML = `<div class="charts"><div class="chart card"><p class="cap">Didelis šuolis po k-osios reikšmės rodo, kad grafas skyla į k grupių.${D.k ? " Oranžinė – pasirinktas k." : ""}</p>
      ${dotChart({values: vals, xLabel: "eilės nr.", yMax: Math.max(1, ...vals), mark: D.k ? D.k - 1 : -1,
        label: i => `<b>${i + 1}-oji savoji reikšmė</b><br>${fmt(vals[i], 3)}${i ? `<br>šuolis nuo ankstesnės: ${fmt(vals[i] - vals[i - 1], 3)}` : ""}`})}</div></div>`;
  },

  k_perziura(D, el, f, run) {
    const series = [];
    if (D.rows.some(r => r.silhouette != null)) series.push({name: "siluetas", color: cssVar("--series-1"), values: D.rows.map(r => r.silhouette ?? null)});
    if (D.rows.some(r => r.ari != null)) series.push({name: `ARI su „${D.reference}“`, color: cssVar("--series-2"), values: D.rows.map(r => r.ari ?? null)});
    series.push({name: "savųjų reikšmių tarpas", color: cssVar("--series-3"), values: D.rows.map(r => r.gap)});
    const source = chosenSource(run, f.block);
    el.innerHTML = `<div class="charts"><div class="chart card"><p class="cap">Tie patys savieji vektoriai, suskirstyti į k grupių.${source ? " Spustelėkite k, kad perskaičiuotumėte su tiek grupių." : ""}</p>
      ${lineChart({xs: D.rows.map(r => r.k), chosen: D.chosen, series, clickable: !!source})}
      <div class="legend">${series.map(s => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")}</div></div></div>`;
    if (source) el.querySelectorAll("[data-k]").forEach(r => r.addEventListener("click", () => {
      const k = +r.dataset.k;
      if (k === D.chosen) return;
      change(() => { W.setup.blocks.find(b => b.id === source).params.k = k; });
      toast(`Perskaičiuojama su ${k} grupėmis…`);
      runSetup();
    }));
  },

  matrica(D, el) {
    const n = D.names.length, strip = Math.max(3, Math.round(n / 40)), sim = D.type === "sim";
    el.innerHTML = `<div class="card"><p class="cap muted small">${esc(D.label)}. Tamsiau – ${sim ? "panašiau" : "arčiau"}; tušti langeliai – nežinoma.
      ${D.groups.length ? "Spalvota juosta – grupės." : ""}</p><canvas class="heatc"></canvas>
      <div class="legend"><span>${sim ? fmt(D.hi) : fmt(D.lo)}</span><span style="flex:0 0 160px;height:10px;border-radius:3px;background:linear-gradient(90deg,${cssVar("--seq-700")},${cssVar("--seq-400")},${cssVar("--seq-100")})"></span><span>${sim ? fmt(D.lo) : fmt(D.hi)}</span></div></div>`;
    const c = el.querySelector("canvas");
    c.width = n + strip; c.height = n + strip;
    const ctx = c.getContext("2d"), img = ctx.createImageData(n, n);
    const hex = h => { const m = h.replace("#", ""); return [0, 2, 4].map(i => parseInt(m.slice(i, i + 2), 16)); };
    const stops = [cssVar("--seq-700"), cssVar("--seq-400"), cssVar("--seq-100")].map(hex);
    const ramp = t => { const u = Math.min(1, Math.max(0, t)) * 2, k = Math.min(1, Math.floor(u)), fr = u - k;
      return stops[k].map((x, i) => Math.round(x + (stops[k + 1][i] - x) * fr)); };
    const span = (D.hi - D.lo) || 1;
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
      const v = D.m[i][j], p = 4 * (i * n + j);
      if (v == null) { img.data[p + 3] = 0; continue; }
      const t = (v - D.lo) / span, [r, g, b] = ramp(sim ? 1 - t : t);
      img.data[p] = r; img.data[p + 1] = g; img.data[p + 2] = b; img.data[p + 3] = 255;
    }
    ctx.putImageData(img, strip, strip);
    D.g.forEach((g, k) => { if (g == null) return; ctx.fillStyle = gColor(g); ctx.fillRect(0, strip + k, strip - 1, 1); ctx.fillRect(strip + k, 0, 1, strip - 1); });
    c.onmousemove = ev => {
      const r = c.getBoundingClientRect(), s = c.width / r.width;
      const j = Math.floor((ev.clientX - r.left) * s) - strip, i = Math.floor((ev.clientY - r.top) * s) - strip;
      if (i < 0 || j < 0 || i >= n || j >= n) return tip(null);
      tip(`<b>${esc(D.names[i])}</b> ↔ <b>${esc(D.names[j])}</b><br>${D.m[i][j] == null ? "nežinoma" : fmt(D.m[i][j], 3)}${D.g[i] != null ? `<br>${esc(D.groups[D.g[i]].name)} · ${esc(D.groups[D.g[j]]?.name ?? "")}` : ""}`, ev);
    };
    c.onmouseleave = () => tip(null);
  },

  dendrograma(D, el) {
    const n = D.names.length, row = 12, labelW = 190, w = 760, T = 8, h = n * row + T * 2;
    const pos = new Map(D.order.map((leaf, i) => [leaf, i]));
    const maxH = Math.max(...D.merges.map(t => t[2]), 1e-6);
    const X = v => labelW + 10 + (w - labelW - 20) * v / maxH;
    const node = new Map();
    for (let i = 0; i < n; i++) node.set(i, {x: X(0), y: T + pos.get(i) * row + row / 2, g: D.g[i]});
    let lines = "";
    D.merges.forEach(([a, b, height], t) => {
      const A = node.get(a), B = node.get(b), xh = X(height), g = A.g != null && A.g === B.g ? A.g : null;
      lines += `<path d="M${A.x},${A.y}H${xh}M${B.x},${B.y}H${xh}M${xh},${A.y}V${B.y}" stroke="${g != null ? gColor(g) : "var(--muted)"}" stroke-width="${g != null ? 1.6 : 1}" fill="none"/>`;
      node.set(n + t, {x: xh, y: (A.y + B.y) / 2, g});
    });
    const labels = D.order.map((leaf, i) => `<g data-tip="${esc(`<b>${D.names[leaf]}</b>${D.g[leaf] != null ? `<br>${D.groups[D.g[leaf]].name}` : ""}`)}">
      ${D.g[leaf] != null ? `<rect x="${labelW - 2}" y="${T + i * row + 2}" width="8" height="8" rx="2" fill="${gColor(D.g[leaf])}"/>` : ""}
      <text class="lab ink" x="${labelW - 6}" y="${T + i * row + row / 2 + 4}" text-anchor="end" style="font-size:10px">${esc(D.names[leaf])}</text></g>`).join("");
    el.innerHTML = `${D.groups.length ? legendHtml(D.groups, "static") : ""}<div class="dendro card"><svg viewBox="0 0 ${w} ${h + 22}" style="width:100%;height:auto">${lines}${labels}
      ${[0, .5, 1].map(t => `<text class="lab" x="${X(t * maxH)}" y="${h + 14}" text-anchor="middle">${fmt(t * maxH, 2)}</text>`).join("")}</svg>
      <p class="muted small">${esc(D.label)}; ašis – jungimo aukštis (atstumas).</p></div>
      ${D.fit.length ? `<div class="tablebox" style="margin-top:10px"><table class="t"><thead><tr><th>grupė</th><th class="n">vienetų</th><th>vientisa</th><th>įsiterpia</th></tr></thead><tbody>
        ${D.fit.map(x => `<tr><td>${gChip(x.group)} ${esc(D.groups[x.group].name)}</td><td class="n">${x.size}</td><td>${x.whole ? "taip" : "<span class='neg'>ne</span>"}</td>
          <td class="muted">${esc(x.intruders.join(", "))}${x.more ? ` … (+${x.more})` : ""}</td></tr>`).join("")}</tbody></table></div>` : ""}`;
  },

  lentele(D, el) {
    el.innerHTML = `<div class="toolbar"><input type="search" class="flt" placeholder="filtruoti…"> <span class="muted small">${D.rows.length} eil.</span></div><div class="tablebox"></div>`;
    const head = [{t: "vienetas"}, ...D.columns.filter(c => c.key !== "name").map(c => ({t: c.label, n: c.num}))];
    const ni = D.columns.findIndex(c => c.key === "name");
    const rows = D.rows.map(r => {
      const text = r.map(v => v ?? "").join(" ").toLowerCase();
      const cells = [cell(esc(ni >= 0 ? r[ni] : ""), ni >= 0 ? r[ni] : "")];
      D.columns.forEach((c, i) => {
        if (c.key === "name") return;
        const v = r[i];
        cells.push(c.group ? cell(v == null ? "" : `${gChip(v)} ${esc(D.groups[v].name)}`, v ?? 1e9)
          : c.percentile && v != null ? cell(`<span class="pbar"><i style="width:${Math.round(v * 100)}%"></i></span> ${Math.round(v * 100)}`, v)
          : typeof v === "number" ? cell(fmt(v, Number.isInteger(v) ? 0 : 3), v) : cell(esc(v ?? ""), v ?? ""));
      });
      return {text, cells};
    });
    const drawT = q => sortableTable(el.querySelector(".tablebox"), head, rows.filter(r => !q || r.text.includes(q)).map(r => r.cells));
    drawT("");
    el.querySelector(".flt").oninput = e => drawT(e.target.value.trim().toLowerCase());
  },

  kryzmine(D, el) {
    const max = Math.max(1, ...D.table.flat());
    el.innerHTML = `<p class="muted small">Eilutės – ${esc(D.a)}, stulpeliai – ${esc(D.b)}${D.more_rows || D.more_cols ? ` (rodomos didžiausios grupės)` : ""}.</p>
      <div class="tablebox"><table class="t heat"><thead><tr><th></th>${D.columns.map(c => `<th class="n">${esc(c)}</th>`).join("")}</tr></thead><tbody>
      ${D.table.map((row, i) => `<tr><td>${esc(D.rows[i])}</td>${row.map(v => `<td class="n" style="background:${v
        ? `color-mix(in srgb, ${cssVar("--seq-400")} ${Math.round(12 + 60 * v / max)}%, transparent)` : "transparent"}">${v || ""}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  },

  grupes(D, el) {
    el.innerHTML = `<div class="comp-grid">${D.cards.map(c => `<div class="card gcard" style="--c:${gColor(c.g)}">
      <h4>${gChip(c.g)} ${esc(c.name)} <span class="muted">· ${c.size}</span></h4>
      ${c.medoid ? `<p class="small">Tipiškiausias: <b>${esc(c.medoid)}</b>${c.intra != null ? ` · viduje ${fmt(c.intra)}, iki kitų ${fmt(c.inter)}` : ""}</p>` : ""}
      <p class="small muted">${c.examples.map(esc).join(", ")}</p>
      ${c.composition ? `<div class="bar">${c.composition.map(([k, v], i) => `<span style="flex:${v};background:${clusterColor(i)}" data-tip="${esc(`${k}: ${v}`)}"></span>`).join("")}</div>
        <p class="small">${c.composition.map(([k, v]) => `${esc(k)} ${v}`).join(" · ")}</p>` : ""}
      <details class="members"><summary>visi (${c.size})</summary><p class="small">${c.members.map(esc).join(", ")}</p></details></div>`).join("")}</div>
      ${D.more ? `<p class="muted small">Dar ${D.more} mažesnių grupių.</p>` : ""}`;
  },

  mantel(D, el) {
    const w = 420, h = 220, L = 40, B = 30, T = 8, R = 8;
    let body;
    if (D.boxes.length) {
      const lo = Math.min(...D.boxes.map(b => b.min)), hi = Math.max(...D.boxes.map(b => b.max)), n = D.boxes.length;
      const x = i => L + (w - L - R) * (i + .5) / n, y = v => T + (h - T - B) * (1 - (v - lo) / ((hi - lo) || 1)), bw = Math.min(26, (w - L - R) / n * .6);
      body = D.boxes.map((b, i) => `<g data-tip="${esc(`<b>${fmt(b.x, Number.isInteger(b.x) ? 0 : 2)}</b>: ${b.n} porų<br>mediana ${fmt(b.med, 3)} (${fmt(b.q1, 3)}–${fmt(b.q3, 3)})`)}">
        <line x1="${x(i)}" x2="${x(i)}" y1="${y(b.min)}" y2="${y(b.max)}" stroke="var(--muted)"/>
        <rect x="${x(i) - bw / 2}" y="${y(b.q3)}" width="${bw}" height="${Math.max(1, y(b.q1) - y(b.q3))}" fill="${cssVar("--series-1")}" opacity=".75" rx="2"/>
        <line x1="${x(i) - bw / 2}" x2="${x(i) + bw / 2}" y1="${y(b.med)}" y2="${y(b.med)}" stroke="var(--ink)" stroke-width="2"/>
        <text class="lab" x="${x(i)}" y="${h - 10}" text-anchor="middle">${fmt(b.x, Number.isInteger(b.x) ? 0 : 1)}</text></g>`).join("")
        + [lo, hi].map(t => `<text class="lab" x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${fmt(t, 2)}</text>`).join("");
    } else {
      const xs = D.points.map(p => p[0]), ys = D.points.map(p => p[1]);
      const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
      const x = v => L + (w - L - R) * (v - x0) / ((x1 - x0) || 1), y = v => T + (h - T - B) * (1 - (v - y0) / ((y1 - y0) || 1));
      body = D.points.map(p => `<circle cx="${x(p[0]).toFixed(1)}" cy="${y(p[1]).toFixed(1)}" r="2" fill="${cssVar("--series-1")}" opacity=".35"/>`).join("")
        + [[x0, "start"], [x1, "end"]].map(([v, a]) => `<text class="lab" x="${x(v)}" y="${h - 10}" text-anchor="${a}">${fmt(v, 2)}</text>`).join("")
        + [y0, y1].map(t => `<text class="lab" x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${fmt(t, 2)}</text>`).join("");
    }
    el.innerHTML = `<div class="charts"><div class="chart card"><h3>${esc(D.a)} pagal ${esc(D.b)}</h3>
      <p class="cap">Kiekviena ${D.boxes.length ? "dėžė – visos poros su ta B reikšme" : "taškas – pora (iki 3000 atsitiktinių)"}.</p>
      <svg viewBox="0 0 ${w} ${h}" role="img">${body}<text class="lab" x="${w - R}" y="${h - 22}" text-anchor="end">${esc(D.b)}</text></svg></div></div>`;
  },

  poros(D, el) {
    const t = (rows, cap) => `<h3 class="small">${cap}</h3><div class="tablebox"><table class="t"><thead><tr><th>pora</th><th>grupės</th>
      <th class="n">panašumas</th><th class="n">tikėtina</th><th class="n">skirtumas</th><th class="n">atstumas</th></tr></thead><tbody>
      ${rows.map(r => `<tr><td><b>${esc(r.a)}</b> – <b>${esc(r.b)}</b></td><td class="muted">${esc(r.ga)}${r.ga !== r.gb ? ` · ${esc(r.gb)}` : ""}</td>
        <td class="n">${fmt(r.sim, 3)}</td><td class="n">${fmt(r.expected, 3)}</td><td class="n ${r.residual < 0 ? "neg" : ""}">${r.residual > 0 ? "+" : ""}${fmt(r.residual, 3)}</td>
        <td class="n">${fmt(r.dist, Number.isInteger(r.dist) ? 0 : 2)}</td></tr>`).join("") || `<tr><td colspan="6" class="muted">nėra</td></tr>`}</tbody></table></div>`;
    el.innerHTML = `<p class="muted small">Panašumas – ${esc(D.sim)}, atstumas – ${esc(D.dist)}, grupės – ${esc(D.groups)}.</p>
      <div class="split"><div>${t(D.closer, "Skirtingų grupių, bet panašesnės nei tikėtina (galimi kontaktai, skoliniai)")}</div>
      <div>${t(D.farther, "Tos pačios grupės, bet mažiau panašios nei tikėtina")}</div></div>`;
  },

  lygiai(D, el) {
    el.innerHTML = `<div class="split"><div class="charts"><div class="chart card"><p class="cap">ARI su Glottolog šakomis kiekviename lygyje žemiau „${esc(D.ancestor)}“.</p>
      ${lineChart({xs: D.levels.map(l => l.level), chosen: null, clickable: false, yMin: Math.min(0, ...D.levels.map(l => l.ari)) < -0.05 ? -0.25 : 0, yMax: 1,
        xTip: k => `${k}-as lygis`, series: [{name: "ARI", color: cssVar("--series-1"), values: D.levels.map(l => l.ari)}]})}</div></div>
      <div class="tablebox"><table class="t"><thead><tr><th class="n">lygis</th><th class="n">šakų</th><th class="n">ARI</th><th>pvz.</th></tr></thead><tbody>
      ${D.levels.map(l => `<tr><td class="n">${l.level}</td><td class="n">${l.clades}</td><td class="n">${fmt(l.ari)}</td><td class="muted small">${esc(l.examples.join(", "))}</td></tr>`).join("")}</tbody></table></div></div>`;
  },

  koreliacijos(D, el) {
    el.innerHTML = `<div class="tablebox"><table class="t heat"><thead><tr><th></th>${D.labels.map(l => `<th class="n">${esc(l)}</th>`).join("")}</tr></thead><tbody>
      ${D.corr.map((row, i) => `<tr><td>${esc(D.labels[i])}</td>${row.map(v => `<td class="n" style="background:${v == null ? "transparent"
        : `color-mix(in srgb, ${cssVar(v >= 0 ? "--series-1" : "--series-2")} ${Math.round(Math.abs(v) * 60)}%, transparent)`}">${fmt(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
      ${D.pca ? `<h3 class="small">Pagrindinės komponentės (${D.pca.units} vienetų)</h3><div class="tablebox"><table class="t"><thead><tr><th>Rodiklis</th><th class="n">1-osios krūvis</th></tr></thead><tbody>
        ${D.labels.map((l, i) => `<tr><td>${esc(l)}</td><td class="n">${fmt(D.pca.loadings[i])}</td></tr>`).join("")}
        <tr><td class="muted">paaiškina (1, 2, 3 …)</td><td class="n">${D.pca.explained.slice(0, 4).map(pct).join(", ")}</td></tr></tbody></table></div>` : ""}`;
  },

  grupiu_testas(D, el) {
    el.innerHTML = `<div class="tablebox"><table class="t"><thead><tr><th>${esc(D.grouping)}</th><th class="n">vienetų</th>${D.keys.map(k => `<th class="n">${esc(D.labels[k])}</th>`).join("")}</tr></thead><tbody>
      ${D.groups.map(g => `<tr><td>${esc(g.group)}</td><td class="n">${g.size}</td>${D.keys.map(k => { const t = g.tests[k];
        if (!t) return `<td class="n muted">–</td>`;
        const p = Math.min(t.p_high, t.p_low), sig = p < D.alpha;
        return `<td class="n" style="${sig ? `background:color-mix(in srgb, ${cssVar(t.p_high < t.p_low ? "--series-1" : "--series-2")} 35%, transparent)` : ""}"
          data-tip="${esc(`<b>${g.group}</b>: ${D.labels[k]}<br>vidurkis ${fmt(t.mean, 3)} (visų ${fmt(t.all, 3)})<br>p (daugiau) ${fmt(t.p_high, 3)}, p (mažiau) ${fmt(t.p_low, 3)}`)}">${fmt(t.mean)}${sig ? (t.p_high < t.p_low ? " ▲" : " ▼") : ""}</td>`; }).join("")}</tr>`).join("")}</tbody></table></div>
      <p class="muted small">▲ – grupės vidurkis reikšmingai didesnis, ▼ – mažesnis (p &lt; ${String(D.alpha).replace(".", ",")}).</p>`;
  },

  sklaida(D, el) {
    const w = 460, h = 320, L = 40, B = 30, T = 8, R = 8, P = D.points;
    const xs = P.map(p => p.x), ys = P.map(p => p.y);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const x = v => L + (w - L - R) * (v - x0) / ((x1 - x0) || 1), y = v => T + (h - T - B) * (1 - (v - y0) / ((y1 - y0) || 1));
    const q = (k, cap) => `<div class="card"><h4 class="small">${cap}</h4><p class="small muted">${D.quadrants[k].map(esc).join(", ") || "–"}</p></div>`;
    el.innerHTML = `${D.groups.length ? legendHtml(D.groups, "static") : ""}<div class="split"><div class="chart card"><svg viewBox="0 0 ${w} ${h}" role="img">
      <line x1="${x(D.mx)}" x2="${x(D.mx)}" y1="${T}" y2="${h - B}" stroke="var(--line)" stroke-dasharray="4 3"/>
      <line x1="${L}" x2="${w - R}" y1="${y(D.my)}" y2="${y(D.my)}" stroke="var(--line)" stroke-dasharray="4 3"/>
      ${P.map(p => `<circle cx="${x(p.x).toFixed(1)}" cy="${y(p.y).toFixed(1)}" r="4" fill="${gColor(p.g)}" stroke="var(--panel)" stroke-width="1"
        data-tip="${esc(`<b>${p.name}</b><br>${D.x}: ${fmt(p.x, 3)}<br>${D.y}: ${fmt(p.y, 3)}`)}"/>`).join("")}
      <text class="lab" x="${w - R}" y="${h - 8}" text-anchor="end">${esc(D.x)} →</text>
      <text class="lab" x="${L + 4}" y="${T + 10}">↑ ${esc(D.y)}</text></svg></div>
      <div class="comp-grid">${q("hh", `abu dideli`)}${q("hl", `didelis ${esc(D.x)}, mažas ${esc(D.y)}`)}${q("lh", `mažas ${esc(D.x)}, didelis ${esc(D.y)}`)}${q("ll", "abu maži")}</div></div>`;
  },

  uzrasas(D, el) { el.innerHTML = `<p class="note-text">${esc(D.text)}</p>`; },
};

/** The spektrinės grupės block whose groups this „Kiek grupių?“ shows as chosen: clicking k sets its k. */
function chosenSource(run, viewId) {
  const s = run.result.setup, ln = s.links.find(l => l.to[0] === viewId && l.to[1] === "pasirinkta");
  const b = ln && s.blocks.find(x => x.id === ln.from[0]);
  return b && b.type === "spektrines_grupes" && W.setup.blocks.some(x => x.id === b.id) ? b.id : null;
}

/** A new garden with the map's nodes where they are drawn, coloured by group; opened in a new tab. */
async function mapToGarden(D, f) {
  const tab = window.open("about:blank", "_blank");
  const {new_id} = await api("/api/sodas/gardens");
  const pts = D.points.filter(p => p.label);
  const nodes = pts.map(p => ({data: {id: `${p.label}|${p.key}`, label: p.label, key: p.key, display_name: p.name, dataset: p.dataset,
    caption: `${p.name.length > 36 ? p.name.slice(0, 35) + "…" : p.name}${p.g != null ? ` · ${p.g + 1}` : ""}`, color: gColor(p.g), size: 30, degree: null, props: {},
    vaiva_cluster: p.g != null ? p.g + 1 : null}, position: {x: p.x * 900, y: -p.y * 900}, classes: []}));
  const name = `Vaiva · ${f.title}`;
  await api(`/api/sodas/gardens/${new_id}`, {name, nodes, edges: [], basket: [], typeVis: {}, labelHidden: {}, unmerged: [], untwinned: []});
  if (tab) tab.location.href = `/?sodas=${new_id}`;
  toast(`Sukurtas sodas „${name}“`);
}

// ---------------------------------------------------------------- files
function download() {
  const blob = new Blob([JSON.stringify({format: "vaivos-saranka/1", ...snapshot()}, null, 1)], {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${(W.setup.title || "saranka").replace(/[^\p{L}\p{N}]+/gu, "_")}.vaiva.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function upload(file) {
  const r = new FileReader();
  r.onload = () => {
    try {
      const s = JSON.parse(r.result);
      if (!Array.isArray(s.blocks)) throw new Error("ne sąranka");
      const unknown = s.blocks.filter(b => !W.parts[b.type]).map(b => b.type);
      change(() => setSetup(s));
      fitView();
      toast(unknown.length ? `Įkelta; nežinomos detalės praleistos: ${unknown.join(", ")}` : "Sąranka įkelta.", unknown.length ? "warning" : "info");
    } catch (e) { toast(`Netinkamas failas: ${e.message}`, "error"); }
  };
  r.readAsText(file);
}

// ---------------------------------------------------------------- start
const Workshop = {
  async init() {
    W.cat = await api("/api/vaiva/dirbtuves");
    W.parts = Object.fromEntries(W.cat.parts.map(p => [p.id, p]));
    W.types = W.cat.types;
    renderPalette();
    renderRecipes();
    const draft = await loadDraft();
    if (draft) setSetup(draft); else setSetup(W.cat.recipes[0].setup, W.cat.recipes[0].title);
    bindCanvas();
    $("#partFilter").oninput = renderPalette;
    $$(".mode-tabs [data-mode]").forEach(b => b.onclick = () => { setMode(b.dataset.mode); if (b.dataset.mode === "dirbtuves") requestAnimationFrame(draw); });
    $$("#wsTabs [data-tab]").forEach(b => b.onclick = () => setTab(b.dataset.tab));
    $("#wsRun").onclick = runSetup;
    $("#wsUndo").onclick = () => undo(true);
    $("#wsClear").onclick = () => { if (!W.setup.blocks.length) return; change(() => { W.setup.blocks = []; W.setup.links = []; W.setup.title = ""; W.sel = null; }); W.view = {x: 30, y: 20, z: 1}; applyView(); toast("Drobė išvalyta. Ctrl+Z – grąžinti."); };
    $("#wsFit").onclick = fitView;
    $("#wsZoomIn").onclick = () => zoomAt(1.15);
    $("#wsZoomOut").onclick = () => zoomAt(1 / 1.15);
    $("#wsSave").onclick = download;
    $("#wsLoad").onclick = () => $("#wsFile").click();
    $("#wsFile").onchange = e => { if (e.target.files[0]) upload(e.target.files[0]); e.target.value = ""; };
    $("#wsTitle").onchange = e => change(() => { W.setup.title = e.target.value.trim(); }, true);
    if (new URLSearchParams(location.search).get("dirbtuves")) { setMode("dirbtuves", false); requestAnimationFrame(fitView); }
    window.addEventListener("resize", () => { if (W.mode === "dirbtuves") drawLinks(); });
  },
  ws: W,
};
