/* Sodas – research garden over the Neo4j graph (the program „Sodas“). */
"use strict";
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const GARDEN_ID = /^[a-z0-9]{4,32}$/;
/** A whole sentence in the interface's language (i18n.js), with values put in: for sentences with markup inside. */
const tx = (text, ...values) => SodasI18n.t(text, ...values);

const S = {
  settings: null, schema: {labels: [], types: []}, cy: null,
  garden: {id: null, name: "", excluded: null, basket: [], typeVis: {}, labelHidden: {}, unmerged: [], untwinned: [], manual: []},
  selOrder: [], search: {q: "", groups: [], types: [], cursor: -1, fillTimer: null},
  lastPath: null, neo4j: null, hover: null, previewDark: undefined, restoring: false,
  map: {l: null, tiles: null, on: false, offset: {x: 0, y: 0}, k: 1, anchor: null, arrangedAt: null, view: null}, boxing: false,
  lexMap: null,  // the map of a merged node (Ctrl + 🗺): {snapshot, view, points, …} – the garden as it was, what is shown
};

// ---------------------------------------------------------------- logging & api
function toast(msg, level = "info", ms = 4500) {
  const el = document.createElement("div");
  el.className = "toast " + level;
  el.textContent = msg;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), ms);
}
function report(level, message, detail) {
  fetch("/api/sodas/log", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({level, source: "naršyklė", message: String(message).slice(0, 2000), detail: detail ? String(detail).slice(0, 8000) : null})}).catch(() => {});
}
window.addEventListener("error", e => report("error", e.message, `${e.filename}:${e.lineno}\n${e.error && e.error.stack || ""}`));
window.addEventListener("unhandledrejection", e => report("error", "Neapdorota klaida: " + (e.reason && e.reason.message || e.reason), e.reason && e.reason.stack));

async function api(path, body) {
  const opts = body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)};
  let r;
  try { r = await fetch(path, opts); } catch (e) { toast("Serveris nepasiekiamas", "error"); throw e; }
  const j = await r.json().catch(() => ({error: r.statusText}));
  if (!r.ok) {
    const err = new Error(j.error || r.statusText);
    err.status = r.status;
    toast(err.message, r.status >= 500 ? "error" : "warning");
    if (r.status < 500) report("warning", `${path}: ${err.message}`);  // server logs its own 5xx
    throw err;
  }
  return j;
}

// ---------------------------------------------------------------- settings helpers
const cloneJson = o => JSON.parse(JSON.stringify(o));
/** Settings as the server gave them. A change is sent with the settings it started from (``_from``): the server saves
 *  only what changed here, so a tab (or a computer) left open with older settings does not undo a change made elsewhere. */
function adoptSettings(s) { S.settings = s; S.settingsFrom = cloneJson(s); return s; }
async function postSettings(value = S.settings) {
  const sent = cloneJson(value), r = await api("/api/sodas/settings", {...value, _from: S.settingsFrom || sent});
  S.settingsFrom = sent;
  return r;
}
const saveSettingsNow = () => postSettings().catch(() => {});
const saveSettings = debounce(saveSettingsNow, 600);
function settingsChanged(what = "style") {
  KalbaTheme.apply(S.settings, S.previewDark);
  if (what === "sizes" || what === "all") updateSizes();
  restyle();
  refreshOverlay();
  saveSettings();
  renderStatus();
}
const nodeType = label => S.settings.nodeTypes[label] || {};
/** What a relationship is called: its type, or – a CUSTOM one (a user's own name) – its ``label``. */
const edgeName = e => { const d = e.data ? e.data() : e, p = d.props || {}; return d.type === "CUSTOM" && p.label ? String(p.label) : String(d.type || ""); };
const edgeType = type => S.settings.edgeTypes[type] || {};
function paletteColor(label) {
  let h = 0; for (const c of label) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h}, 45%, 48%)`;
}
const typeColor = label => nodeType(label).color || paletteColor(label);
const cssVar = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ---------------------------------------------------------------- graph
function buildStyle() {
  const st = S.settings, ink = cssVar("--ink") || "#222", bg = cssVar("--graph-bg") || "#fff", accent = cssVar("--accent") || "#2f5d8a";
  const muted = cssVar("--muted") || "#777", line = cssVar("--line") || "#ccc";
  // on the map nodes keep their on-screen size (the size set in the settings) while the map zooms: lengths × k = 1 / zoom
  const k = S.map.on ? S.map.k : 1, size = k === 1 ? "data(size)" : n => (n.data("size") || 30) * k;
  // label sizes (Ctrl+Alt+Numpad ±): node labels ``labelSize`` px, the rest in proportion (edge labels 8 : 11)
  const t = (Number(st.graph.labelSize) || 11) / 11;
  // relationship widths (Ctrl+Shift + mouse wheel): every width, of every type, times ``edgeWidth``
  const ew = (Number(st.graph.edgeWidth) || 1) * k;
  // Cytoscape draws an arrowhead max((13.37 × width)^0.9, 29) graph units wide: never under 29, so on a zoomed-in map
  // (small k) it would outgrow the nodes. "arrow-scale" gives it the on-screen size it has without the map.
  const arrowW = w => Math.max(Math.pow(13.37 * w, .9), 29);
  const arrow = w => k === 1 ? {} : {"arrow-scale": k * arrowW(w / k) / arrowW(w)};
  const style = [
    {selector: "node", style: {"background-color": "data(color)", width: size, height: size,
      label: st.ui.nodeLabels ? "data(caption)" : "", color: ink, "font-size": 11 * t * k, "text-valign": "bottom", "text-margin-y": 3 * t * k,
      "text-background-color": bg, "text-background-opacity": .75, "text-background-padding": 1 * t * k, "text-wrap": "ellipsis", "text-max-width": 160 * t * k,
      "border-width": 1 * k, "border-color": line, opacity: .78}},
    {selector: "edge", style: {width: 1.4 * ew, ...arrow(1.4 * ew), "line-color": line, "target-arrow-color": line, "target-arrow-shape": "triangle", "curve-style": "bezier",
      label: st.ui.edgeLabels ? edgeName : "", "font-size": 8 * t * k, color: muted, "text-rotation": "autorotate",
      "text-background-color": bg, "text-background-opacity": .75}},
  ];
  for (const [label, t] of Object.entries(st.nodeTypes)) {
    const s = {};
    if (t.color) s["background-color"] = t.color;
    if (t.shape) s.shape = t.shape;
    // a node with its own picture is drawn as the picture only: no disc, and a ring only while selected (below)
    if (t.image) Object.assign(s, {"background-image": t.image, "background-fit": "contain", "background-clip": "none",
      "background-opacity": 0, "background-image-opacity": 1, "border-width": 0, "background-image-containment": "over", "bounds-expansion": 2});
    style.push({selector: `node[label = "${label}"]`, style: s});
  }
  // forms placed by a Vaiva study: the colour of their sound group wins over the type's picture
  style.push({selector: "node[vaiva_cluster]", style: {"background-color": "data(color)", "background-image": "none", "background-opacity": 1,
    "border-width": 1 * k}});
  for (const [type, t] of Object.entries(st.edgeTypes)) {
    const s = {};
    if (t.width) Object.assign(s, {width: Number(t.width) * ew, ...arrow(Number(t.width) * ew)});
    if (t.style) s["line-style"] = t.style;
    if (t.color) Object.assign(s, {"line-color": t.color, "target-arrow-color": t.color});
    style.push({selector: `edge[type = "${type}"]`, style: s});
  }
  style.push(
    // touched (pačiupinėti) nodes: full strength and a ring, so the researcher sees what was already looked at
    {selector: "node[?touched]", style: {opacity: 1, "border-width": 2.5 * k, "border-color": muted}},
    {selector: "node.temp", style: {opacity: .4}},
    {selector: "node.more", style: {shape: "round-tag", "background-color": cssVar("--accent-soft"), "border-color": accent, "border-style": "dashed",
      "border-width": 1 * k, width: 18 * k, height: 18 * k, label: "data(caption)", "font-size": 10 * t * k, color: accent, opacity: 1}},
    {selector: "edge.more", style: {"line-style": "dashed", "line-color": accent, "target-arrow-shape": "none", label: "", opacity: .6}},
    {selector: "edge[type = 'source_record_key']", style: {"line-style": "dotted"}},
    {selector: "node.path", style: {"border-width": 3 * k, "border-color": accent, opacity: 1, "z-index": 9}},
    {selector: "edge.path", style: {"line-color": accent, "target-arrow-color": accent, width: 3.2 * ew, ...arrow(3.2 * ew), "z-index": 9}},
    {selector: ".dim", style: {opacity: .15}},
    {selector: ".hidden, .type-hidden, .merged, .lexmap-off, .map-hidden, .ds-off", style: {display: "none"}},
    // node types switched off in "Rodinys" (👁) (with the "+N" nodes of such nodes)
    ...Object.keys(S.garden.labelHidden || {}).flatMap(l => [{selector: `node[label = "${l}"]`, style: {display: "none"}},
      {selector: `node.more[parent_label = "${l}"]`, style: {display: "none"}}]),
    // one node standing for several forms of the same name: a double ring
    {selector: "node.multi, node.bundle", style: {"border-width": 5 * k, "border-style": "double", "border-color": ink, opacity: 1}},
    // two datasets' nodes shown as one: a thick dashed ring in the accent colour (and the ⧉ badge)
    {selector: "node.twin", style: {"border-width": 3.5 * k, "border-style": "dashed", "border-color": accent, opacity: 1}},
    // a node drawn as its own picture has a ring only while selected (not for touched, merged, twin or path)
    ...Object.entries(st.nodeTypes).filter(([, t]) => t.image).map(([label]) => ({selector: `node[label = "${label}"]:unselected`, style: {"border-width": 0}})),
    {selector: ":selected", style: {"border-width": 3 * k, "border-color": accent, "line-color": accent, "target-arrow-color": accent, opacity: 1}},
  );
  return style;
}
function restyle() { if (S.cy) S.cy.style(buildStyle()); }

function caption(d) {
  const text = String(d.display_name ?? d.key ?? "");
  return text.length > 42 ? text.slice(0, 41) + "…" : text;
}
function nodeData(n) {
  const d = {...n, caption: caption(n), color: typeColor(n.label), size: S.settings.graph.nodeSize};
  if (n.kind === "bundle") d.caption = `${caption(n)} ×${n.count}`;
  return d;
}
/** Shown relationships: not hidden themselves, not of a hidden type and not ending in a hidden node. */
const realEdges = () => sizeEdges().filter(e => labelShown(e.source()) && labelShown(e.target()));
/** Relationships a node's size counts. Node types switched off in "Rodinys" (👁) only hide nodes from view: their
 *  relationships still count, so hiding senses does not shrink the lexemes to the smallest size. */
const sizeEdges = () => S.cy.edges().not(".more").not(".virtual").not(".hidden").not(".type-hidden").not(".lexmap-off")
  .filter(e => !e.source().is(".hidden, .ds-off") && !e.target().is(".hidden, .ds-off"));
/** Size from visible relationships (default) or all relationships in the database; or one size for all. */
function updateSizes() {
  if (!S.cy) return;
  const g = S.settings.graph;
  const nodes = S.cy.nodes().not(".more").not(".virtual");
  const vis = sizeEdges();
  const deg = n => g.sizeSource === "db" ? (n.data("degree") || 0) : n.connectedEdges().intersection(vis).length;
  // a twin has the relationships of both of its nodes (but not the one between them)
  const twinDeg = t => members(t).reduce((a, m) => a + deg(m), 0) - (g.sizeSource === "db" ? 2 : 2 * members(t).edgesWith(members(t)).intersection(vis).length);
  const sizeOf = d => g.minNodeSize + (g.maxNodeSize - g.minNodeSize) * Math.log1p(d) / Math.log1p(maxDeg);
  // "visi mazgai vienodo dydžio": one size for ordinary nodes; merged ones (twins, multi) stay a little bigger
  const grown = (base, ms) => base + 5 * Math.log2(Math.max(1, ms.length));
  const maxDeg = g.sizeByDegree ? Math.max(1, ...nodes.map(deg), ...S.cy.nodes(".twin").map(twinDeg)) : 1;
  if (!g.sizeByDegree) {
    const same = Number(g.nodeSize) || 30;
    S.cy.nodes().not(".more, .multi").forEach(n => n.data("size", same));
    S.cy.nodes(".twin").forEach(t => t.data("size", grown(same, members(t))));
  } else {
    nodes.forEach(n => n.data("size", sizeOf(deg(n))));
    S.cy.nodes(".twin").forEach(t => t.data("size", sizeOf(Math.max(0, twinDeg(t)))));
  }
  // a bundle grows a little with the number of nodes it stands for
  S.cy.nodes(".bundle").forEach(b => b.data("size", grown(b.data("size") || g.nodeSize, {length: Math.min(1024, b.data("count") || 1)})));
  // a multi node grows a little with the number of nodes it stands for
  S.cy.nodes(".multi").forEach(m => {
    const ms = members(m);
    if (ms.nonempty()) m.data("size", grown(Math.max(...ms.map(f => f.data("size"))), ms));
  });
}
const updateSizesSoon = debounce(updateSizes, 60);

function touch(n) {
  if (!n || n.empty() || n.hasClass("more") || n.hasClass("virtual") || n.data("touched")) return;
  n.data("touched", true);
  saveGardenSoon();
}

function initCy() {
  S.cy = cytoscape({container: $("#cy"), style: buildStyle(), minZoom: .05, maxZoom: 4,
    boxSelectionEnabled: true, selectionType: "single"});
  const cy = S.cy;
  // Cytoscape emits "boxend" just before it selects the boxed nodes; a group selection does not touch them.
  // Ctrl + drag takes the boxed nodes out of the selection (Shift + drag adds them)
  cy.on("boxstart", e => {
    S.boxing = true;
    const ev = e.originalEvent || {};
    S.unboxing = (ev.ctrlKey || ev.metaKey) && !ev.shiftKey ? cy.$(":selected") : null;
    S.boxed = [];
  });
  cy.on("box", "node", e => { if (S.unboxing) S.boxed.push(e.target.id()); });
  cy.on("boxend", () => {
    S.boxing = true;
    setTimeout(() => {
      if (S.unboxing) {
        const out = new Set(S.boxed);
        cy.$(":selected").unselect();
        S.unboxing.filter(el => !out.has(el.id())).select();
        S.unboxing = null;
      }
      S.boxing = false;
    }, 0);
  });
  cy.on("select", "node", e => {
    S.selOrder = S.selOrder.filter(id => id !== e.target.id()).concat(e.target.id());
    if (e.target.hasClass("temp")) promoteTemp(e.target);
    if (!S.boxing) touch(e.target);
    if (!e.target.hasClass("more") && cy.$("node:selected").length === 1) showNodeInfo(e.target);
    syncSelectionButtons();
  });
  cy.on("unselect", "node", e => { S.selOrder = S.selOrder.filter(id => id !== e.target.id()); syncSelectionButtons(); });
  cy.on("select", "edge", e => showEdgeInfo(e.target));
  cy.on("grab", "node", e => touch(e.target));
  cy.on("tap", "node.more", e => loadMore(e.target));
  cy.on("dbltap", "node", e => !e.target.hasClass("more") && expand(e.target, "semantic"));
  cy.on("cxttap", "node", e => openCtx(e, "node"));
  cy.on("cxttap", "edge", e => openCtx(e, "edge"));
  cy.on("cxttap", e => { if (e.target === cy) openCtx(e, "bg"); });
  cy.on("tap", e => { closeMenus(); if (e.target === cy) S.cy.elements().removeClass("dim"); });
  cy.on("mouseover", "node, edge", e => { S.hover = e.target; });
  cy.on("mouseout", "node, edge", () => { S.hover = null; });
  cy.on("render", scheduleOverlay);
  cy.on("add remove", () => { $("#empty").hidden = cy.nodes().length > 0; renderStatus(); updateSizesSoon(); updateMapSoon(); updateMergesSoon(); });
  cy.on("position", "node.twin", e => members(e.target).positions(() => ({...e.target.position()})));
  cy.on("dragfree", "node", e => { rebind(e.target.union(S.cy.nodes(":selected"))); saveGardenSoon(); });
  cy.on("viewport", () => { syncMapView(); saveGardenSoon(); });
  $("#cy").addEventListener("mousedown", e => {
    if (e.button !== 1) return;
    e.preventDefault();  // no autoscroll
    if (S.hover && S.hover.inside()) openElementPanel(S.hover, e);
    else closeMenus();  // background: nothing to control
  });
  $("#cy").addEventListener("contextmenu", e => e.preventDefault());
  $("#stage").addEventListener("wheel", onModifiedWheel, {capture: true, passive: false});
}

// Hidden nodes (and their relationships) do not count against the limits: hiding makes room for other nodes.
const semanticCount = () => S.cy.nodes().not(".more, .virtual, .hidden, .lexmap-off, .lexmap, .ds-off").filter(labelShown).length;

// ---------------------------------------------------------------- datasets switched off (⚙ → Duomenynai)
/** The dataset of a node as the server tells it (Graph.ok): its dataset, else its authority, else its key's prefix. */
function dsOf(d) {
  if (d.dataset) return String(d.dataset);
  if (d.props && d.props.authority) return String(d.props.authority);
  return d.key ? String(d.key).split("@")[0].split(":")[0] : "";
}
const datasetsOff = () => new Set((S.settings && S.settings.datasetsOff) || []);
/** Nodes of switched-off datasets are hidden in the garden, not removed: switched on again, they are back at once
 *  (with their "+N" nodes). The server does not look for them at all meanwhile. */
function applyDatasetsOff() {
  if (!S.cy) return;
  const off = datasetsOff(), cy = S.cy;
  cy.batch(() => {
    cy.nodes().not(".more, .virtual").forEach(n => n.toggleClass("ds-off", off.size > 0 && off.has(dsOf(n.data()))));
    cy.nodes(".more").forEach(m => m.toggleClass("ds-off", cy.getElementById(m.data("parent_node")).hasClass("ds-off")));
  });
}
const edgeCount = () => realEdges().length;

// ---------------------------------------------------------------- free places for new nodes
/** Visible nodes (circles) and relationships (segments) a new node must not be drawn on. */
function obstacles(except) {
  const ex = except || S.cy.collection();
  return {
    nodes: S.cy.nodes(":visible").not(ex).map(n => ({x: n.position("x"), y: n.position("y"), r: Math.max(n.width(), n.height()) / 2})),
    edges: S.cy.edges(":visible").filter(e => !ex.contains(e.source()) && !ex.contains(e.target()))
      .map(e => [e.source().position(), e.target().position()]).filter(([a, b]) => a.x !== b.x || a.y !== b.y),
  };
}
function segDist(p, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y, t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(p.x - a.x - t * dx, p.y - a.y - t * dy);
}
const GAP = 14;  // room for the label under a node, too
const isFree = (p, r, obs, gap = GAP * unit()) => obs.nodes.every(o => Math.hypot(p.x - o.x, p.y - o.y) >= o.r + r + gap) &&
  obs.edges.every(([a, b]) => segDist(p, a, b) >= r + gap / 2);
/** The free place nearest to ``p`` (rings around it); the chosen place becomes an obstacle for the next node. */
function freeSpot(p, r, obs) {
  let best = p;
  search: if (!isFree(p, r, obs)) {
    const step = r + GAP * unit();
    for (let k = 1; k <= 30; k++) for (let i = 0, m = 6 * k; i < m; i++) {
      const a = 2 * Math.PI * i / m + k, q = {x: p.x + k * step * Math.cos(a), y: p.y + k * step * Math.sin(a)};
      if (isFree(q, r, obs)) { best = q; break search; }
    }
  }
  obs.nodes.push({...best, r});
  return best;
}

/** Add nodes/edges honouring the global limits; new nodes are placed on a ring around ``center``, each on a free place.
 *  ``force``: the researcher asked for exactly these (expand, a search result, a path) – the limits do not apply. */
function addGraph(payload, {center = null, temp = false, force = false} = {}) {
  const cy = S.cy, lim = S.settings.limits;
  const fresh = payload.nodes.filter(n => cy.getElementById(n.id).empty());
  const room = force ? fresh.length : Math.max(0, lim.maxNodes - semanticCount());
  const adding = fresh.slice(0, room);
  const dropped = fresh.length - adding.length;
  const c = center && cy.getElementById(center).nonempty() ? cy.getElementById(center).position()
    : {x: (cy.width() / 2 - cy.pan().x) / cy.zoom(), y: (cy.height() / 2 - cy.pan().y) / cy.zoom()};
  const u = unit(), radius = (90 + adding.length * 9) * u, obs = obstacles();
  const els = adding.map((n, i) => {
    const data = nodeData(n), a = 2 * Math.PI * i / Math.max(1, adding.length);
    const position = freeSpot({x: c.x + radius * Math.cos(a), y: c.y + radius * Math.sin(a)}, data.size / 2 * u, obs);
    return {group: "nodes", data, classes: [temp ? "temp" : "", n.kind === "bundle" ? "bundle" : ""].join(" ").trim(), position};
  });
  cy.add(els);
  for (const n of payload.nodes) {
    const el = cy.getElementById(n.id);
    if (el.nonempty() && !el.hasClass("more") && n.degree != null) el.data("degree", n.degree);
    if (el.nonempty() && n.kind === "bundle" && el.data("count") !== n.count) el.data({count: n.count, caption: nodeData(n).caption});
  }
  let edgeRoom = force ? Infinity : Math.max(0, lim.maxEdges - edgeCount()), edgesDropped = 0;
  const edgeEls = [];
  for (const e of payload.edges || []) {
    if (cy.getElementById(e.id).nonempty() || cy.getElementById(e.source).empty() || cy.getElementById(e.target).empty()) continue;
    if (edgeRoom <= 0) { edgesDropped++; continue; }
    edgeEls.push({group: "edges", data: {...e}, classes: S.garden.typeVis[e.type] === false ? "type-hidden" : ""});
    edgeRoom--;
  }
  cy.add(edgeEls);
  absorbIntoBundles(payload.nodes.filter(n => n.kind === "bundle").map(n => n.id));
  if (datasetsOff().size) applyDatasetsOff();
  if (dropped || edgesDropped) {
    const msg = `Pasiekta riba (${lim.maxNodes} mazgų / ${lim.maxEdges} ryšių): neparodyta ${dropped} mazgų, ${edgesDropped} ryšių.`;
    toast(msg, "warning"); report("warning", msg);
  }
  updateSizes();
  const newIds = els.map(e => e.data.id);
  fetchComputed(newIds);
  fetchGeo(newIds);
  saveGardenSoon();
  return newIds;
}

/** Relationships of one type and direction of ``node`` that are in the garden (merged ones included; a bundle's
 *  edge counts as all the relationships it stands for). */
const relWeight = e => Number((e.data("props") || {}).count) || 1;
const presentRels = (node, type, out) => node.connectedEdges(`[type = "${type}"]`).not(".more, .virtual")
  .filter(e => (e.source().id() === node.id()) === !!out).reduce((a, e) => a + relWeight(e), 0);

// ---------------------------------------------------------------- bundles ("skin ×10963")
// The server sends a neighbour name with many nodes (⚙ → Ribos: „Pluoštas nuo“) as one bundle node: its members are
// not loaded, the garden shows how many there are. A bundle is expanded, listed and shown on the map by the server
// (``data.bundle`` describes it: {source, type, out, name, label}); it is saved with the garden like any node.
const BUNDLE_SPLIT_MAX = 200;   // "Rodyti atskirai": a bundle this small may be loaded node by node
/** Nodes already in the garden that a new bundle stands for (the same name and label, related to the same source the
 *  same way) and that nothing else holds there go into it: the garden shows them once, in the bundle's number. */
function absorbIntoBundles(ids) {
  const cy = S.cy, basket = new Set(S.garden.basket);
  let gone = cy.collection();
  for (const id of ids) {
    const b = cy.getElementById(id), d = b.data("bundle"), src = cy.getElementById(b.data("center") || "");
    if (b.empty() || !d || src.empty()) continue;
    src.connectedEdges(`[type = "${d.type}"]`).not(".more, .virtual").forEach(e => {
      const fromSrc = e.source().same(src), other = fromSrc ? e.target() : e.source();
      if (fromSrc !== !!d.out || other.same(b) || other.hasClass("bundle") || other.hasClass("virtual") || other.hasClass("more")) return;
      if (other.data("label") !== d.label || String(other.data("display_name")) !== String(d.name)) return;
      if (other.data("touched") || basket.has(other.id())) return;
      if (other.connectedEdges().not(".more, .virtual").some(x => !x.same(e))) return;   // something else holds it here
      gone = gone.union(other);
    });
  }
  if (gone.empty()) return 0;
  gone.union(cy.nodes(".more").filter(m => gone.getElementById(m.data("parent_node")).nonempty())).remove();
  return gone.length;
}
/** What the server needs to know of a node to expand it or page its neighbours. */
const sourceOf = n => n.hasClass("bundle") ? {bundle: n.data("bundle")} : {label: n.data("label"), key: n.data("key")};
/** The group a merged node stands for, as the server can find it whole: a bundle as it is; a multi node ("rain ×12")
 *  by the node all its members are related to the same way. Null: only the loaded members are known. */
function bundleOf(node) {
  if (node.hasClass("bundle")) return node.data("bundle");
  if (!node.hasClass("multi")) return null;
  const ms = members(node), f0 = ms[0];
  if (!f0) return null;
  const name = f0.data("display_name"), label = f0.data("label");
  if (ms.some(f => f.data("display_name") !== name || f.data("label") !== label)) return null;
  for (const e of f0.connectedEdges().not(".more, .virtual").toArray()) {
    const out = e.target().same(f0), c = out ? e.source() : e.target(), type = e.data("type");
    if (c.hasClass("virtual") || c.hasClass("more") || (!c.hasClass("bundle") && !c.data("key"))) continue;
    if (!ms.every(f => f.edgesWith(c).some(x => x.data("type") === type && x.target().same(f) === out))) continue;
    return {source: sourceOf(c), type, out, name, label};
  }
  return null;
}
/** A bundle's panel: how many, its relationships by type, its members page by page (with their languages). */
async function showBundleInfo(b) {
  const panel = $("#info"), d = b.data(), src = S.cy.getElementById(d.center || "");
  S.infoFor = b.id();
  panel.hidden = false;
  const canSplit = d.count <= BUNDLE_SPLIT_MAX && !(d.bundle.source || {}).bundle;
  panel.innerHTML = `<button class="close" onclick="this.parentNode.hidden=true">×</button>
    <div class="title-row">${nodePicture(d)}<div><h3 translate="no">${esc(d.display_name)} <span class="muted">×${d.count}</span></h3>
    <div class="muted">${d.count} ${esc(d.label)} mazgų tuo pačiu pavadinimu${src.nonempty() ? ` · <span translate="no">${esc(src.data("display_name"))}</span>` : ""}</div></div></div>
    <div style="margin-top:8px;display:flex;gap:4px;flex-wrap:wrap">
      <button data-mode="core">Svarbiausia</button><button data-mode="semantic">Išskleisk</button><button data-mode="all">Viskas</button>
      <button data-collapse>Suskleisk</button>${canSplit ? "<button data-split>Rodyti atskirai</button>" : ""}
      ${mapAllowed() ? "<button data-geo>📍 Visi žemėlapyje</button>" : ""}</div>
    <p class="muted" style="font-size:.85em">Pluošto mazgai neįkelti į sodą, todėl jis lieka lengvas. Išskleidus rodomi visų jų kaimynai
      (iš šio mazgo); žemėlapyje – visi jo mazgai (Sense – jų leksemos), artinant – tos srities.</p>
    <section><h4>Ryšiai</h4><div data-rels><span class="muted">kraunama…</span></div></section>
    <section><h4>${esc(d.label)}</h4><table data-members></table><div data-more></div></section>`;
  panel.querySelectorAll("[data-mode]").forEach(x => x.onclick = () => expand(b, x.dataset.mode));
  panel.querySelector("[data-collapse]").onclick = () => collapse(b);
  if (panel.querySelector("[data-split]")) panel.querySelector("[data-split]").onclick = () => unbundle(b);
  if (panel.querySelector("[data-geo]")) panel.querySelector("[data-geo]").onclick = () => groupMap(b);
  let loaded = 0;
  const page = async () => {
    let r;
    try { r = await api("/api/sodas/bundle", {bundle: d.bundle, skip: loaded, take: 50}); } catch (e) { return; }
    if (S.infoFor !== b.id() || !b.inside()) return;
    if (!loaded) {
      panel.querySelector("[data-rels]").innerHTML = r.relationship_counts.map((c, i) => `<div class="rel-row"><span>${c.out ? "→" : "←"} <span class="mono">${esc(c.type)}</span></span>
        <span class="n">${c.count}</span><button data-exp="${i}">rodyti</button></div>`).join("") || '<span class="muted">kitų ryšių nėra</span>';
      panel.querySelectorAll("[data-exp]").forEach(x => x.onclick = () => expand(b, "all", [r.relationship_counts[x.dataset.exp].type]));
    }
    loaded += r.members.length;
    const table = panel.querySelector("[data-members]");
    table.insertAdjacentHTML("beforeend", r.members.map(m => `<tr data-m="${esc(m.id)}"><td translate="no">${esc(m.display_name)}</td>
      <td class="muted" data-lang translate="no"></td><td class="muted">${esc(m.dataset || "")}</td>
      <td><button data-add title="Įkelti šį mazgą į sodą">＋</button></td></tr>`).join(""));
    for (const m of r.members) {
      const tr = table.querySelector(`tr[data-m="${CSS.escape(m.id)}"]`);
      if (tr) tr.querySelector("[data-add]").onclick = async () => {
        const el = await addNode({id: m.id, label: m.label, key: m.key});
        if (el) toast(`${m.display_name}: įkeltas į sodą`);
      };
    }
    const more = panel.querySelector("[data-more]");
    more.innerHTML = loaded < d.count ? `<button>Rodyti dar (${loaded} iš ${d.count})</button>` : "";
    if (more.firstChild) more.firstChild.onclick = page;
    // the languages of the members just listed (the computed property "language")
    const labels = new Set(S.settings.computed.filter(c => c.name === "language").map(c => c.label));
    const refs = r.members.filter(m => labels.has(m.label)).map(m => ({label: m.label, key: m.key}));
    if (!refs.length) return;
    try {
      const c = await api("/api/sodas/computed", {nodes: refs});
      for (const [id, vals] of Object.entries(c)) {
        const cell = table.querySelector(`tr[data-m="${CSS.escape(id)}"] [data-lang]`);
        if (cell && vals.language) cell.textContent = vals.language.map(v => v.name).join(", ");
      }
    } catch (e) { /* toast shown */ }
  };
  page();
}
/** "Rodyti atskirai": a small bundle's members come into the garden node by node (and their relationships with it). */
async function unbundle(b) {
  const d = b.data();
  if (d.count > BUNDLE_SPLIT_MAX) return toast(`Per daug mazgų (${d.count}) – naudokite sąrašą ar žemėlapį`, "warning");
  let r;
  try { r = await api("/api/sodas/bundle", {bundle: d.bundle, skip: 0, take: d.count}); } catch (e) { return; }
  const pos = {...b.position()}, center = d.center;
  b.remove();
  const ids = addGraph({nodes: r.members, edges: []}, {center, force: true});
  S.cy.collection(ids.map(id => S.cy.getElementById(id))).forEach(n => { n.position({...pos}); n.data("touched", true); });
  await connectToGarden(ids, [d.type], true);
  relayoutAround(ids);
  toast(`${d.display_name}: sode ${ids.length} mazgų`);
}
/** New nodes around one place spread out (only they move). */
function relayoutAround(ids) {
  const ns = S.cy.collection(ids.map(id => S.cy.getElementById(id))).filter(n => n.nonempty());
  if (ns.empty()) return;
  const obs = obstacles(ns);
  ns.forEach(n => n.position(freeSpot({...n.position()}, n.width() / 2, obs)));
  saveGardenSoon();
}
/** "+N" nodes for what is still not in the garden. What is shown is counted in the garden, not taken from the
 *  server: expanding a node again must not offer relationships that "+N" already brought in. */
function addMore(centerId, more) {
  const cy = S.cy;
  const center = cy.getElementById(centerId);
  for (const m0 of more || []) {
    const m = {...m0, shown: Math.max(m0.shown, presentRels(center, m0.type, m0.out))};
    const id = `more|${centerId}|${m.type}|${m.out ? "out" : "in"}`;
    const rest = m.total - m.shown;
    const existing = cy.getElementById(id);
    if (rest <= 0) { existing.remove(); continue; }
    const data = {id, kind: "more", parent_node: centerId, parent_label: center.data("label"), type: m.type, out: m.out, total: m.total, shown: m.shown,
      caption: `+${rest} ${m.type}${m.out ? " →" : " ←"}`};
    if (existing.nonempty()) { existing.data(data); continue; }
    const p = center.position(), u = unit();
    const position = freeSpot({x: p.x + (Math.random() - .5) * 160 * u, y: p.y + (70 + Math.random() * 50) * u}, 9 * u, obstacles());
    cy.add([{group: "nodes", data, classes: "more", position},
            {group: "edges", data: {id: id + "|e", source: centerId, target: id, type: ""}, classes: "more"}]);
  }
}

async function expand(node, mode, types, quiet = false) {
  if (S.lexMap) { toast("Žemėlapio vaizde mazgai neišskleidžiami – grįžkite į sodą (🗺)", "warning"); return 0; }
  if (node.hasClass("virtual")) {  // every node behind it, from where the merged node stands (a few requests at a time)
    const ms = members(node), pos = {...node.position()}, queue = [...ms];
    let shown = 0;
    if (ms.length > 3) toast(`${node.data("caption")}: išskleidžiama ${ms.length} mazgų…`, "info", 2500);
    const worker = async () => {
      for (let m; (m = queue.shift());) {
        m.position({...pos});
        try { const n = await expand(m, mode, types, true); shown += n; } catch (e) { /* toast shown */ }
      }
    };
    await Promise.all(Array.from({length: Math.min(6, ms.length)}, worker));
    toast(`${node.data("caption")}: parodyta ${shown} ryšių`);
    return shown;
  }
  if (node.hasClass("temp")) promoteTemp(node);
  touch(node);
  const d = node.data();
  if (!quiet && !node.hasClass("bundle") && await lkezdbMissing(d)) return 0;
  const r = await api("/api/sodas/expand", {...sourceOf(node), mode, types});
  if (types) for (const t of types) if (S.garden.typeVis[t] === false) { delete S.garden.typeVis[t]; S.cy.edges(`[type = "${t}"]`).removeClass("type-hidden"); }
  addGraph(r, {center: d.id, force: true});
  addMore(d.id, r.more);
  const shown = r.edges.length, rest = (r.more || []).reduce((a, m) => a + Math.max(0, m.total - Math.max(m.shown, presentRels(node, m.type, m.out))), 0);
  if (quiet) return shown;
  toast(`${d.display_name}: parodyta ${shown} ryšių${rest ? `, dar ${rest} – spauskite „+“ mazgus` : ""}`);
}

/** An LKEŽDB word (Entry) whose articles are not in Neo4j yet – often only named by a "žr." of another word – has
 *  nothing to expand: Žemė → LKEŽDB opens at that word, where it can be explained by the language model and included.
 *  True when the word was missing. */
async function lkezdbMissing(d) {
  if (d.label !== "Entry" || d.dataset !== "lkezdb" || !String(d.key).startsWith("lkezdb:entry:")) return false;
  const guid = String(d.key).slice("lkezdb:entry:".length);
  let w;
  try {
    const r = await fetch(`/api/lkezdb/word/${encodeURIComponent(guid)}`);
    if (!r.ok) return false;  // no LKEŽDB store here: expand as any other node
    w = await r.json();
  } catch (e) { return false; }
  if (w.word && w.word.itraukta) return false;
  await saveGardenNow();
  location.href = `/zeme?skiltis=lkezdb&guid=${encodeURIComponent(guid)}&truksta=1&sodas=${S.garden.id}`;
  return true;
}

async function loadMore(moreNode) {
  const m = moreNode.data();
  const parent = S.cy.getElementById(m.parent_node);
  if (parent.empty()) { moreNode.remove(); return; }
  const take = Math.min(20, S.settings.limits.maxPerNode);
  // ``take`` names: same-named neighbours come together and are drawn as one merged node
  const r = await api("/api/sodas/page", {...sourceOf(parent), type: m.type, out: m.out, skip: m.shown, take, by_name: true});
  addGraph(r, {center: parent.id(), force: true});
  // the server tells where the next page begins (bundles stand for many relationships)
  const added = r.edges.filter(e => S.cy.getElementById(e.id).nonempty()).reduce((a, e) => a + (Number((e.props || {}).count) || 1), 0);
  addMore(parent.id(), [{type: m.type, out: m.out, total: m.total, shown: r.next != null ? r.next : m.shown + added}]);
}

/** Hide one relationship type of a node, but keep touched neighbours (and basket nodes) with their edges. */
function hideRelType(node, type, out) {
  const cy = S.cy, keep = new Set(S.garden.basket);
  const edges = node.connectedEdges(`[type = "${type}"]`).filter(e => out === undefined || (e.source().id() === node.id()) === out);
  let hidden = 0, kept = 0;
  const others = [];
  edges.forEach(e => {
    const other = e.source().id() === node.id() ? e.target() : e.source();
    if (other.data("touched") || keep.has(other.id())) { kept++; return; }
    e.remove(); hidden++; others.push(other);
  });
  for (const o of others) if (o.inside() && o.connectedEdges().not(".more").empty() && !o.data("touched")) o.remove();
  cy.remove(cy.getElementById(`more|${node.id()}|${type}|out`).union(cy.getElementById(`more|${node.id()}|${type}|in`)));
  toast(`${type}: paslėpta ${hidden}${kept ? `, palikta ${kept} paliestų` : ""}`);
  saveGardenSoon();
}

async function addNode(item, {select = true} = {}) {
  let el = S.cy.getElementById(item.id);
  if (el.empty()) {
    const r = await api("/api/sodas/nodes", {nodes: [{label: item.label, key: item.key}]});
    if (!r.nodes.length) { toast("Mazgas nerastas", "warning"); return null; }
    addGraph({nodes: r.nodes, edges: []}, {force: true});
    el = S.cy.getElementById(item.id);
    connectToGarden([item.id], undefined, true);
  } else if (el.hasClass("temp")) promoteTemp(el);
  el.removeClass("hidden");
  touch(el);
  if (select) { S.cy.$(":selected").unselect(); el.select(); centerOn(el); }
  return el;
}

async function connectToGarden(ids, types, force = false) {
  const all = S.cy.nodes().not(".more, .virtual, .bundle, .lexmap").map(n => n.id());
  if (all.length < 2) return 0;
  // only the relationships of the nodes just added are asked for (not of every pair in a large garden)
  const r = await api("/api/sodas/edges-between", ids ? {ids: all, types, focus: ids} : {ids: all, types});
  const mine = ids ? new Set(ids) : null;
  const before = edgeCount();
  addGraph({nodes: [], edges: r.edges.filter(e => !mine || mine.has(e.source) || mine.has(e.target))}, {force});
  return edgeCount() - before;
}

// ---------------------------------------------------------------- temp search results
function promoteTemp(node) {
  node.removeClass("temp");
  clearTimeout(S.search.fillTimer);
  setTimeout(removeTemps, 5000);  // others fade away so the garden stays focused
  saveGardenSoon();
}
function removeTemps() { S.cy.nodes(".temp").remove(); }

// ---------------------------------------------------------------- computed properties & overlay
async function fetchComputed(ids) {
  const labels = new Set(S.settings.computed.map(c => c.label));
  const refs = ids.map(id => S.cy.getElementById(id)).filter(n => n.nonempty() && n.data("key") && labels.has(n.data("label")))
    .map(n => ({label: n.data("label"), key: n.data("key")}));
  if (!refs.length) { refreshOverlay(); return; }
  try {
    // the answer is keyed by label|key; a node on the map of a merged node has its own id (lm|label|key)
    const r = await api("/api/sodas/computed", {nodes: refs});
    for (const id of ids) {
      const n = S.cy.getElementById(id), vals = n.nonempty() && r[`${n.data("label")}|${n.data("key")}`];
      if (vals) { n.data("computed", vals); if (S.lexMap && n.hasClass("lexmap")) S.lexMap.computed.set(n.id(), vals); }
    }
  } catch (e) { /* toast already shown */ }
  refreshOverlay(); updateMergesSoon();
  saveGardenSoon();
}

function ruleForValue(label, property, value) {
  return S.settings.valueImages.find(v => v.image && (v.label === "*" || v.label === label) && v.property === property && String(v.value) === String(value));
}
function imageForValue(label, property, value) {
  const r = ruleForValue(label, property, value);
  return r && r.image;
}
/** The hint over a picture: the rule's title (a flag: its country or region) and the value it stands for. */
const ruleHint = (rule, value) => rule.title ? (String(rule.title) === String(value) ? rule.title : `${rule.title} · ${value}`) : String(value);
/** Pictures beside a node: [{url, title}] – by its own values and by its computed ones (a form: its language's flag). */
function badgesFor(d) {
  const out = [];
  for (const rule of S.settings.valueImages) {
    if (!rule.image || !(rule.label === "*" || rule.label === d.label)) continue;
    const v = rule.property === "display_name" ? d.display_name : rule.property === "dataset" ? d.dataset : d.props && d.props[rule.property];
    const vals = Array.isArray(v) ? v.map(String) : [String(v ?? "")];
    if (vals.includes(String(rule.value))) out.push({url: rule.image, title: ruleHint(rule, rule.value)});
  }
  for (const [name, vals] of Object.entries(d.computed || {})) {
    const def = S.settings.computed.find(c => c.name === name && c.label === d.label);
    for (const v of vals) {
      const own = ruleForValue(d.label, name, v.name);
      const target = !own && def && def.image_from_target ? ruleForValue(v.label, "display_name", v.name) : null;
      if (own || target) out.push({url: (own || target).image, title: `${ruleHint(own || target, v.name)}${name === "language" ? " (kalba)" : ""}`});
      else if (def && def.image_from_target && nodeType(v.label).image) out.push({url: nodeType(v.label).image, title: v.name});
    }
  }
  const seen = new Set();
  return out.filter(b => !seen.has(b.url) && seen.add(b.url)).slice(0, 4);
}

let overlayQueued = false;
function scheduleOverlay() { if (!overlayQueued) { overlayQueued = true; requestAnimationFrame(() => { overlayQueued = false; drawOverlay(); }); } }
function refreshOverlay() { if (S.cy) { S.cy.nodes().forEach(n => n.scratch("_badges", badgesFor(n.data()))); scheduleOverlay(); } }
function drawOverlay() {
  const ov = $("#overlay"), size = S.settings.graph.badgeSize, cy = S.cy;
  const seen = new Set();
  const w = cy.width(), h = cy.height();
  cy.nodes(":visible").forEach(n => {
    const badges = n.scratch("_badges");
    if (!badges || !badges.length) return;
    const p = n.renderedPosition(), r = n.renderedWidth() / 2;
    if (p.x < -50 || p.y < -50 || p.x > w + 50 || p.y > h + 50) return;
    const id = "b:" + n.id();
    seen.add(id);
    let box = ov.querySelector(`[data-id="${CSS.escape(id)}"]`);
    if (!box) { box = document.createElement("div"); box.className = "badges"; box.dataset.id = id; ov.append(box); }
    const sig = badges.map(b => b.url + "#" + b.title).join("|") + size;
    if (box.dataset.sig !== sig) {
      // the pointer resting on a picture tells what it stands for (a flag: the country or region)
      box.innerHTML = badges.map(b => `<img src="${esc(b.url)}" style="width:${size}px;height:${size}px" alt="${esc(b.title)}" title="${esc(b.title)}">`).join("");
      box.dataset.sig = sig;
    }
    box.style.left = (p.x + r * .7) + "px";
    box.style.top = (p.y - r * .7 - size) + "px";
    box.style.opacity = n.hasClass("temp") || n.hasClass("dim") ? .4 : 1;
  });
  // 📍 beside nodes with latitude/longitude; a click on it offers "Rodyti žemėlapyje" (on the map they are in place already)
  // only nodes with coordinates of their own (a form placed by its language would flood the garden with pins)
  (S.map.on ? S.cy.collection() : geoNodes().filter(":visible").filter(n => ownGeo(n.data()) || n.hasClass("twin"))).forEach(n => {
    const p = n.renderedPosition(), r = n.renderedWidth() / 2;
    if (p.x < -50 || p.y < -50 || p.x > w + 50 || p.y > h + 50) return;
    const id = "g:" + n.id();
    seen.add(id);
    let pin = ov.querySelector(`[data-id="${CSS.escape(id)}"]`);
    if (!pin) {
      pin = document.createElement("div"); pin.className = "geo-pin"; pin.dataset.id = id; pin.innerHTML = PIN_SVG;
      pin.title = "Turi platumą ir ilgumą – spauskite";
      pin.onclick = ev => { ev.stopPropagation(); openPinMenu(S.cy.getElementById(n.id()), ev); };
      ov.append(pin);
    }
    pin.style.left = (p.x - r * .7) + "px";
    pin.style.top = (p.y - r * .7) + "px";
    pin.style.opacity = n.hasClass("temp") || n.hasClass("dim") ? .4 : 1;
  });
  // ⧉ beside (not over) a merged node: two datasets' nodes (twin), the same word of one language (bold) or nodes joined
  // by hand; a group of same-named nodes (×N) gets the stacked sign. The node's own picture stays visible and
  // clickable; with flags at its right the sign stands at its left. A click on it offers "Išskirti". Too small a node gets no badge.
  cy.nodes(".twin:visible, .multi:visible").forEach(n => {
    const p = n.renderedPosition(), r = n.renderedWidth() / 2;
    if (r < 7 || p.x < -50 || p.y < -50 || p.x > w + 50 || p.y > h + 50) return;
    const id = "t:" + n.id();
    seen.add(id);
    const twin = n.hasClass("twin"), manual = n.hasClass("manual"), joined = twin || manual || n.hasClass("same");
    let b = ov.querySelector(`[data-id="${CSS.escape(id)}"]`);
    if (!b) {
      b = document.createElement("div"); b.className = "twin-badge"; b.dataset.id = id; b.innerHTML = joined ? TWIN_ICON : MULTI_ICON;
      b.onclick = ev => { ev.stopPropagation(); openMergeMenu(S.cy.getElementById(n.id()), ev); };
      ov.append(b);
    }
    const k = (n.data("members") || []).length;
    b.title = twin ? tx("Apjungti du duomenynai: {0} – spauskite", (n.data("datasets") || []).join(" + "))
      : manual ? tx("Rankiniu būdu apjungti {0} mazgai (tik šiame sode) – spauskite", k)
      : joined ? tx("Apjungti {0} mazgai: tas pats pavadinimas ir kalba – spauskite", k) : tx("{0} to paties pavadinimo mazgai – spauskite", k);
    const left = (n.scratch("_badges") || []).length > 0;
    b.style.left = (left ? p.x - r * .85 - 9 : p.x + r * .85 + 9) + "px";
    b.style.top = (p.y - r * .85 - 5) + "px";
    b.style.opacity = n.hasClass("dim") ? .4 : 1;
  });
  cy.edges(":visible").forEach(e => {
    const img = edgeType(e.data("type")).image;
    if (!img) return;
    const id = "e:" + e.id();
    seen.add(id);
    let el = ov.querySelector(`[data-id="${CSS.escape(id)}"]`);
    if (!el) { el = document.createElement("img"); el.className = "edge-img"; el.dataset.id = id; ov.append(el); }
    if (el.getAttribute("src") !== img) el.src = img;
    const m = e.renderedMidpoint();
    el.style.width = el.style.height = size + "px";
    el.style.left = m.x + "px";
    el.style.top = (m.y - (S.settings.ui.edgeLabels ? size * .9 : 0)) + "px";
  });
  for (const el of [...ov.children]) if (!seen.has(el.dataset.id)) el.remove();
}

/** The merge badge's menu: what the node joins, "Išskirti" / "Rodyti atskirai" (and "Pervadinti" for one joined by hand). */
function openMergeMenu(t, ev) {
  closeMenus();
  if (t.empty()) return;
  const k = members(t).length;
  menu($("#ctxmenu"), [{title: t.hasClass("twin") ? `${t.data("display_name")}: ${t.data("datasets").join(" + ")}` : `${t.data("display_name")} ×${k}`},
    ...(t.hasClass("manual") ? [{label: "Pervadinti", hint: "tik šiame sode", icon: "✎", run: () => renameManual(t)}] : []),
    {label: t.hasClass("twin") ? "Išskirti" : "Rodyti atskirai", hint: t.hasClass("twin") ? "du atskiri mazgai" : `${k} mazgai`, icon: SPLIT_ICON, run: () => splitVirtual(t)}]);
  place($("#ctxmenu"), ev.clientX, ev.clientY);
}
const PIN_SVG = '<svg viewBox="0 0 24 34" width="16" height="23"><path d="M12 1C5.9 1 1 5.9 1 12c0 8.3 11 21 11 21s11-12.7 11-21C23 5.9 18.1 1 12 1z" fill="#ea4335" stroke="#a52714" stroke-width="1.2"/><circle cx="12" cy="12" r="4.2" fill="#7a1a0e"/></svg>';
function openPinMenu(node, ev) {
  closeMenus();
  if (node.empty()) return;
  menu($("#ctxmenu"), [{title: node.data("display_name")},
    {label: S.map.on ? "Parodyti žemėlapyje" : "Rodyti žemėlapyje", icon: "map", run: () => showOnMap(node)},
    ...(S.map.on ? [{label: "Išjungti žemėlapį", icon: "mapOff", run: mapOff}] : [])]);
  place($("#ctxmenu"), ev.clientX, ev.clientY);
}

// ---------------------------------------------------------------- node picture (panel headers)
const SHAPE_PATHS = {
  "rectangle": "M3 3H37V37H3Z", "round-rectangle": "M9 3H31Q37 3 37 9V31Q37 37 31 37H9Q3 37 3 31V9Q3 3 9 3Z",
  "diamond": "M20 2L38 20L20 38L2 20Z", "triangle": "M20 3L38 36H2Z", "hexagon": "M11 3H29L38 20L29 37H11L2 20Z",
  "octagon": "M13 2H27L38 13V27L27 38H13L2 27V13Z", "star": "M20 2L25 15L38 15L27 23L31 37L20 29L9 37L13 23L2 15L15 15Z",
  "tag": "M3 3H28L38 20L28 37H3Z", "barrel": "M8 3H32Q38 20 32 37H8Q2 20 8 3Z",
};
function nodePicture(d, size = 34) {
  const t = nodeType(d.label), color = d.color || typeColor(d.label);
  const path = SHAPE_PATHS[t.shape];
  const shape = t.image ? "" : path ? `<path d="${path}" fill="${esc(color)}"/>` : `<circle cx="20" cy="20" r="18" fill="${esc(color)}"/>`;
  const img = t.image ? `<image href="${esc(t.image)}" x="4" y="4" width="32" height="32" preserveAspectRatio="xMidYMid meet"/>` : "";
  const badges = badgesFor(d).map(b => `<img src="${esc(b.url)}" alt="${esc(b.title)}" title="${esc(b.title)}" style="width:${Math.round(size * .5)}px;height:${Math.round(size * .5)}px">`).join("");
  return `<span class="node-pic"><svg viewBox="0 0 40 40" width="${size}" height="${size}">${shape}${img}</svg>${badges ? `<span class="pic-badges">${badges}</span>` : ""}</span>`;
}

// ---------------------------------------------------------------- info panel
/** A multi node: its forms (with their languages) and "Rodyti atskirai". */
function showMultiInfo(m, refetch = true) {
  const panel = $("#info"), d = m.data(), center = S.cy.getElementById(d.center || ""), ms = members(m), manual = m.hasClass("manual"),
    bold = m.hasClass("same") || manual;
  S.infoFor = m.id();
  panel.hidden = false;
  const lang = f => {
    const c = (f.data("computed") || {}).language, g = f.data("geo");
    return c && c.length ? c.map(v => v.name).join(", ") : g && g.via ? g.via.name : "";
  };
  panel.innerHTML = `<button class="close" onclick="this.parentNode.hidden=true">×</button>
    <div class="title-row">${nodePicture(d)}<div><h3>${esc(d.display_name)} <span class="muted">×${ms.length}</span></h3>
    <div class="muted">${manual ? esc(tx("Rankiniu būdu apjungti {0} mazgai – tik šiame sode", ms.length))
      : bold ? esc(tx("Drąsiai apjungti {0} mazgai: tas pats pavadinimas ir kalba", ms.length))
      : `${ms.length} ${esc(d.label)} mazgai su tuo pačiu pavadinimu${center.nonempty() ? " · " + esc(center.data("display_name")) : ""}`}</div></div></div>
    <div style="margin-top:8px;display:flex;gap:4px;flex-wrap:wrap">
      <button data-mode="core">Svarbiausia</button><button data-mode="semantic">Išskleisk</button><button data-mode="all">Viskas</button>
      <button data-collapse>Suskleisk</button><button data-split>Rodyti atskirai</button>${manual ? "<button data-rename>Pervadinti</button>" : ""}
      ${mapAllowed() && ms.some(f => !!geoOf(f.data())) ? "<button data-geo>📍 Rodyti žemėlapyje</button>" : ""}</div>
    <p class="muted" style="font-size:.85em">Išskleidžiami visi šie mazgai; jų ryšiai rodomi iš šio mazgo. Žemėlapyje jie rodomi atskirai – kiekvienas savo kalbos vietoje.</p>
    <section>${bold ? "" : `<h4>${esc(d.label)}</h4>`}<table>${ms.map(f => `<tr><td>${esc(f.data("display_name"))}</td>${bold
      ? `<td>${esc(f.data("label"))}</td><td class="muted">${esc(f.data("dataset") || "")}</td>` : ""}<td class="muted">${esc(lang(f))}</td></tr>`).join("")}</table></section>`;
  panel.querySelector("[data-split]").onclick = () => splitVirtual(m);
  if (manual) panel.querySelector("[data-rename]").onclick = () => renameManual(m);
  panel.querySelectorAll("[data-mode]").forEach(b => b.onclick = () => expand(m, b.dataset.mode));
  panel.querySelector("[data-collapse]").onclick = () => collapse(m);
  if (panel.querySelector("[data-geo]")) panel.querySelector("[data-geo]").onclick = () => showOnMap(m);
  const missing = ms.filter(f => !f.data("computed")).map(f => f.id());
  if (refetch && missing.length) fetchComputed(missing).then(() => { if (S.infoFor === m.id() && m.inside()) showMultiInfo(m, false); });
}
const TWIN_ICON = '<svg viewBox="0 0 20 14" width="20" height="14"><circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="13" cy="7" r="5.5" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>';
/** A twin: both datasets' nodes, each with its own relationships and properties; "Išskirti". */
async function showTwinInfo(t) {
  const panel = $("#info"), d = t.data(), ms = members(t);
  S.infoFor = t.id();
  panel.hidden = false;
  const head = `<button class="close" onclick="this.parentNode.hidden=true">×</button>
    <div class="title-row">${nodePicture(d)}<div><h3>${esc(d.display_name)} <span class="twin-mark" title="Apjungti du duomenynai">${TWIN_ICON}</span></h3>
    <div class="muted">${esc(d.label)} · apjungti duomenynai: ${ms.map(m => esc(m.data("dataset"))).join(" + ")}</div></div></div>
    <div style="margin-top:8px;display:flex;gap:4px;flex-wrap:wrap">
      <button data-mode="core">Svarbiausia</button><button data-mode="semantic">Išskleisk</button><button data-mode="all">Viskas</button>
      <button data-collapse>Suskleisk</button><button data-split title="Rodyti kaip du atskirus mazgus">Išskirti</button></div>`;
  panel.innerHTML = head + `<div class="muted">kraunama…</div>`;
  const wire = () => {
    panel.querySelectorAll("[data-mode]").forEach(b => b.onclick = () => expand(t, b.dataset.mode));
    panel.querySelector("[data-collapse]").onclick = () => collapse(t);
    panel.querySelector("[data-split]").onclick = () => splitVirtual(t);
  };
  wire();
  let infos;
  try { infos = await Promise.all(ms.map(m => api(`/api/sodas/node?label=${encodeURIComponent(m.data("label"))}&key=${encodeURIComponent(m.data("key"))}`))); }
  catch (e) { return; }
  if (!t.inside() || S.infoFor !== t.id()) return;
  // the relationship joining the two (the first member is its start) is not shown
  const own = (m, info, i) => {
    const rels = info.relationship_counts.map(c => ({...c, count: c.count - (TWIN_RULES.some(r => r.type === c.type) && c.out === (i === 0) ? 1 : 0)}))
      .filter(c => c.count > 0).map(c => `<div class="rel-row"><span>${c.out ? "→" : "←"} <span class="mono">${esc(c.type)}</span></span>
        <span class="n">${c.count}</span><button data-exp="${esc(m.id())}" data-t="${esc(c.type)}">rodyti</button></div>`).join("");
    const props = Object.entries(info.props).filter(([k]) => k !== "display_name")
      .map(([k, v]) => `<tr><td class="k">${esc(k)}</td><td>${esc(Array.isArray(v) ? v.join(" · ") : v)}</td></tr>`).join("");
    return `<section><h4>${esc(m.data("dataset") || "")} · ${esc(m.data("display_name"))}</h4>${rels || '<span class="muted">kitų ryšių nėra</span>'}
      <details><summary class="muted">savybės</summary><table>${props}</table></details></section>`;
  };
  panel.innerHTML = head + ms.map((m, i) => own(m, infos[i], i)).join("");
  wire();
  panel.querySelectorAll("[data-exp]").forEach(b => b.onclick = () => expand(S.cy.getElementById(b.dataset.exp), "all", [b.dataset.t]));
}
async function showNodeInfo(node) {
  if (node.hasClass("bundle")) return showBundleInfo(node);
  if (node.hasClass("multi")) return showMultiInfo(node);
  if (node.hasClass("twin")) return showTwinInfo(node);
  const d = node.data();
  const panel = $("#info");
  panel.hidden = false;
  const head = dd => `<button class="close" onclick="this.parentNode.hidden=true">×</button>
    <div class="title-row">${nodePicture(dd)}<div><h3 translate="no">${esc(dd.display_name)}</h3>
    <div class="muted">${esc(dd.label)}${dd.dataset ? " · " + esc(dd.dataset) : ""}${dd.degree != null ? ` · ${dd.degree} ryšių` : ""}</div></div></div>`;
  panel.innerHTML = head(d) + `<div class="muted">kraunama…</div>`;
  S.infoFor = node.id();
  let info;
  try { info = await api(`/api/sodas/node?label=${encodeURIComponent(d.label)}&key=${encodeURIComponent(d.key)}`); }
  catch (e) { return; }
  if (!node.inside() || S.infoFor !== node.id()) return;  // another node was opened meanwhile
  node.data("degree", info.degree);
  const computed = Object.entries(d.computed || {}).map(([name, vals]) => `<tr><td class="k">${esc(name)}</td><td class="computed">${vals.map(v => {
      const rule = ruleForValue(d.label, name, v.name) || ruleForValue(v.label, "display_name", v.name);
      const img = rule ? rule.image : nodeType(v.label).image, hint = rule ? ruleHint(rule, v.name) : v.name;
      return `${img ? `<img src="${esc(img)}" alt="${esc(hint)}" title="${esc(hint)}"> ` : ""}<a href="#" data-add="${esc(v.label)}|${esc(v.key)}">${esc(v.name)}</a>`; }).join(", ")}</td></tr>`).join("");
  const props = Object.entries(info.props).filter(([k]) => k !== "display_name")
    .map(([k, v]) => `<tr><td class="k">${esc(k)}</td><td>${esc(Array.isArray(v) ? v.join(" · ") : v)}</td></tr>`).join("");
  const rels = info.relationship_counts.map(c => `<div class="rel-row"><span>${c.out ? "→" : "←"} <span class="mono">${esc(c.type)}</span></span>
      <span class="n">${c.count}</span><button data-exp="${esc(c.type)}">rodyti</button></div>`).join("");
  panel.innerHTML = head({...d, degree: info.degree}) + `
    <div style="margin-top:8px;display:flex;gap:4px;flex-wrap:wrap">
      <button data-mode="core">Svarbiausia</button><button data-mode="semantic">Išskleisk</button><button data-mode="all">Viskas</button>
      <button data-collapse title="Pašalinti kaimynus, susijusius tik su šiuo mazgu">Suskleisk</button>
      <button data-basket>🧺 Į krepšį</button>${geoOf(d) && mapAllowed() ? "<button data-geo>📍 Rodyti žemėlapyje</button>" : ""}</div>
    ${computed ? `<section><h4>Išskaičiuotos savybės</h4><table>${computed}</table></section>` : ""}
    <section><h4>Ryšiai duomenų bazėje</h4>${rels || '<span class="muted">nėra</span>'}</section>
    <section><h4>Savybės</h4><table>${props}</table></section>
    ${info.source_record ? `<section><h4>Šaltinio įrašas</h4><pre class="raw">${esc(JSON.stringify(JSON.parse(info.source_record), null, 1))}</pre></section>` : ""}`;
  panel.querySelectorAll("[data-mode]").forEach(b => b.onclick = () => expand(node, b.dataset.mode));
  panel.querySelector("[data-collapse]").onclick = () => collapse(node);
  panel.querySelectorAll("[data-exp]").forEach(b => b.onclick = () => expand(node, "all", [b.dataset.exp]));
  panel.querySelector("[data-basket]").onclick = () => addToBasket(node);
  if (panel.querySelector("[data-geo]")) panel.querySelector("[data-geo]").onclick = () => showOnMap(node);
  panel.querySelectorAll("[data-add]").forEach(a => a.onclick = ev => {
    ev.preventDefault();
    const [label, key] = a.dataset.add.split(/\|(.*)/s);
    addNode({id: `${label}|${key}`, label, key});
  });
}
function showEdgeInfo(edge) {
  const d = edge.data();
  S.infoFor = edge.id();
  if (edge.hasClass("more")) return;
  const s = S.cy.getElementById(d.source), t = S.cy.getElementById(d.target);
  const props = Object.entries(d.props || {}).map(([k, v]) => `<tr><td class="k">${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
  const panel = $("#info");
  panel.hidden = false;
  panel.innerHTML = `<button class="close" onclick="this.parentNode.hidden=true">×</button><h3 class="mono">${esc(edgeName(d))}</h3>
    ${d.type === "CUSTOM" ? '<div class="muted" style="font-size:.85em">savo pavadintas ryšys (tipas CUSTOM)</div>' : ""}
    <div class="title-row small">${nodePicture(s.data(), 22)} ${esc(s.data("display_name"))} → ${nodePicture(t.data(), 22)} ${esc(t.data("display_name"))}</div>
    <div class="rel-box"></div>
    <div style="margin:8px 0"><button data-off>Bekelė: neiti per ${esc(d.type)}</button></div><table>${props}</table>`;
  panel.querySelector("[data-off]").onclick = () => offRoad(d.type);
  if (drawnRel(edge)) relBox(edge, panel.querySelector(".rel-box"));
}
/** A drawn relationship in the info panel: when it was drawn, its note, and deleting it. */
function relBox(edge, box) {
  const p = drawnRel(edge);
  box.innerHTML = `<div class="muted" style="font-size:.85em">nubrėžta sode · ${esc(String(p.created_at || "").slice(0, 10))}</div>
    ${p.note ? `<div style="margin:4px 0">${esc(p.note)}</div>` : ""}
    <div style="margin:6px 0;display:flex;gap:4px;flex-wrap:wrap"><button data-r="del" class="danger">Ištrinti ryšį</button></div>`;
  box.querySelector("[data-r]").onclick = () => deleteRelationship(edge);
}

// ---------------------------------------------------------------- menus
function closeMenus() { $("#ctxmenu").hidden = true; $("#float").hidden = true; }
function place(el, x, y) {
  const stage = $("#stage").getBoundingClientRect();
  el.hidden = false;
  const w = el.offsetWidth, h = el.offsetHeight;
  el.style.left = Math.max(4, Math.min(x - stage.left, stage.width - w - 4)) + "px";
  el.style.top = Math.max(4, Math.min(y - stage.top, stage.height - h - 4)) + "px";
}
/** Menu pictures: what each command does at a glance (the toolbar uses the same signs). The twin sign is the one shown
 *  beside a node joining two datasets. */
const SPLIT_ICON = '<svg viewBox="0 0 22 14" width="20" height="14"><circle cx="5.5" cy="7" r="4.6" fill="none" stroke="currentColor" stroke-width="1.7"/><circle cx="16.5" cy="7" r="4.6" fill="none" stroke="currentColor" stroke-width="1.7"/></svg>';
const MULTI_ICON = '<svg viewBox="0 0 20 14" width="20" height="14"><circle cx="6" cy="7" r="4" fill="currentColor" opacity=".35"/><circle cx="10" cy="7" r="4" fill="currentColor" opacity=".55"/><circle cx="14" cy="7" r="4" fill="currentColor"/></svg>';
const ICONS = {all: "◉", core: "★", expand: "⊕", collapse: "⊖", basket: "🧺", split: "⇱", map: "📍", center: "◎", focus: "✺", hide: "◌",
  remove: "✕", offroad: "⛔", fit: "⤢", layout: "✣", mapOff: "🗺", show: "👁", select: "▣", svg: "⭳", temps: "🧹", clear: "🗑",
  garden: "🌳", tab: "↗"};
const iconHtml = ic => !ic ? "" : ic.startsWith("<svg") ? ic : esc(ICONS[ic] || ic);
function menu(el, items) {
  el.innerHTML = items.map((it, i) => it === "-" ? '<div class="sep"></div>' : it.title ? `<h5>${esc(it.title)}</h5>` :
    `<div class="mi" data-i="${i}"><span class="mi-ic" aria-hidden="true">${iconHtml(it.icon)}</span>${esc(it.label)}${it.hint ? `<span class="hint">${esc(it.hint)}</span>` : ""}</div>`).join("");
  el.querySelectorAll(".mi").forEach(mi => mi.onclick = () => { closeMenus(); items[mi.dataset.i].run(); });
}
function openCtx(e, kind) {
  closeMenus();
  const ev = e.originalEvent, t = e.target, el = $("#ctxmenu");
  if (kind === "node" && t.hasClass("more")) return loadMore(t);
  if (kind === "node" && t.hasClass("bundle")) {
    if (!t.selected()) { if (!ev.shiftKey) S.cy.$(":selected").unselect(); t.select(); }
    menu(el, [{title: t.data("caption")},
      {label: "Rodyk viską", hint: "visų jo mazgų", icon: "all", run: () => expand(t, "all")},
      {label: "Rodyk svarbiausia", icon: "core", run: () => expand(t, "core")},
      {label: "Išskleisk", hint: "dukart spustelėjus", icon: "expand", run: () => expand(t, "semantic")},
      {label: "Suskleisk", icon: "collapse", run: () => collapse(t)},
      {label: "Mazgų sąrašas", hint: `${t.data("count")}`, icon: "select", run: () => showBundleInfo(t)},
      ...(t.data("count") <= BUNDLE_SPLIT_MAX && !(t.data("bundle").source || {}).bundle ? [{label: "Rodyti atskirai", hint: `${t.data("count")} mazgai`, icon: SPLIT_ICON, run: () => unbundle(t)}] : []), "-",
      ...(mapWayItems(t).length ? mapWayItems(t) : mapAllowed() ? [{label: "Visi žemėlapyje", hint: "🗺", icon: "map", run: () => groupMap(t)}] : []),
      {label: "Centruok", hint: "Home", icon: "center", run: () => centerOn(t)},
      {label: "Paslėpk", hint: "H", icon: "hide", run: hideSelected}, {label: "Pašalink iš sodo", hint: "Delete", icon: "remove", run: removeSelected}]);
  } else if (kind === "node" && t.hasClass("multi")) {
    if (!t.selected()) { if (!ev.shiftKey) S.cy.$(":selected").unselect(); t.select(); }
    menu(el, [{title: t.data("caption")},
      {label: "Rodyk viską", hint: "visų jo mazgų", icon: "all", run: () => expand(t, "all")},
      {label: "Rodyk svarbiausia", icon: "core", run: () => expand(t, "core")},
      {label: "Išskleisk", hint: "dukart spustelėjus", icon: "expand", run: () => expand(t, "semantic")},
      {label: "Suskleisk", icon: "collapse", run: () => collapse(t)},
      ...(splitOf(t, "multi") ? [{label: "Sujunk vienodus", hint: "to paties pavadinimo mazgus", icon: MULTI_ICON, run: () => remerge(t, "multi")}] : []),
      ...(splitOf(t, "twin") ? [{label: "Apjungti tapačius", hint: "skirtingų duomenynų atitikmenis", icon: TWIN_ICON, run: () => remerge(t, "twin")}] : []), "-",
      {label: "Rodyti atskirai", hint: `${t.data("members").length} mazgai`, icon: SPLIT_ICON, run: () => splitVirtual(t)},
      ...(t.hasClass("manual") ? [{label: "Pervadinti", hint: "tik šiame sode", icon: "✎", run: () => renameManual(t)}] : []),
      ...(S.cy.$("node:selected").length > 1 ? [{label: "Apjungti pažymėtus", hint: `${S.cy.$("node:selected").length} mazgai`, icon: TWIN_ICON, run: mergeSelected}] : []),
      ...(mapAllowed() && members(t).some(f => !!geoOf(f.data())) ? [{label: "Rodyti žemėlapyje", icon: "map", run: () => showOnMap(t)}] : []),
      ...(mapWayItems(t).length ? mapWayItems(t) : mapAllowed() ? [{label: "Visi žemėlapyje", hint: "Ctrl+🗺 – ir neįkelti", icon: "map", run: () => groupMap(t)}] : []), "-",
      {label: "Paslėpk", hint: "H", icon: "hide", run: hideSelected}, {label: "Pašalink iš sodo", hint: "Delete", icon: "remove", run: removeSelected}]);
  } else if (kind === "node") {
    if (!t.selected()) { if (!ev.shiftKey) S.cy.$(":selected").unselect(); t.select(); }
    const many = S.cy.$("node:selected").length;
    menu(el, [{title: many > 1 ? `Pažymėta mazgų: ${many}` : t.data("display_name")},
      {label: "Rodyk viską", hint: "visi ryšiai + šaltinis", icon: "all", run: () => expand(t, "all")},
      {label: "Rodyk svarbiausia", hint: "kalbiniai ryšiai", icon: "core", run: () => expand(t, "core")},
      {label: "Išskleisk", hint: "dukart spustelėjus", icon: "expand", run: () => expand(t, "semantic")},
      {label: "Suskleisk", hint: "tik su juo susiję kaimynai", icon: "collapse", run: () => collapse(t)},
      ...(t.hasClass("twin") ? [{label: "Išskirti", hint: t.data("datasets").join(" + "), icon: SPLIT_ICON, run: () => splitVirtual(t)}] : []),
      ...(splitOf(t, "twin") ? [{label: "Apjungti tapačius", hint: "su kito duomenyno atitikmeniu", icon: TWIN_ICON, run: () => remerge(t, "twin")}] : []),
      ...(splitOf(t, "multi") ? [{label: "Sujunk vienodus", hint: "to paties pavadinimo mazgus", icon: MULTI_ICON, run: () => remerge(t, "multi")}] : []),
      {label: "Pridėk į krepšį", icon: "basket", run: () => addToBasket()},
      {label: "Į atskirą sodą", hint: many > 1 ? `${many} mazgai` : "", icon: "split", run: splitToGarden},
      ...(many === 2 ? [{label: "Sukurti ryšį", hint: "Ctrl+J", icon: "⟶", run: linkSelected}] : []),
      ...(many >= 2 ? [{label: "Apjungti pažymėtus", hint: "tik šiame sode", icon: TWIN_ICON, run: mergeSelected}] : []), "-",
      ...(geoOf(t.data()) && mapAllowed() ? [{label: "Rodyti žemėlapyje", icon: "map", run: () => showOnMap(t)}] : []),
      ...(many === 1 ? mapWayItems(t) : []),
      {label: "Centruok", hint: "Home", icon: "center", run: () => centerOn(t)},
      {label: "Paryškink kaimynus", icon: "focus", run: () => focusNode(t)},
      {label: many > 1 ? "Paslėpk pažymėtus" : "Paslėpk", hint: "H", icon: "hide", run: hideSelected},
      {label: "Pašalink iš sodo", hint: "Delete", icon: "remove", run: removeSelected}]);
  } else if (kind === "edge") {
    if (t.hasClass("more")) return;
    const rel = t.hasClass("virtual") ? [] : relMenuItems(t);
    menu(el, [{title: edgeName(t)}, ...(rel.length ? [...rel, "-"] : []),
      {label: "Bekelė", hint: `neiti per ${t.data("type")}`, icon: "offroad", run: () => offRoad(t.data("type"))},
      {label: "Slėpti šio tipo ryšius", icon: "hide", run: () => setTypeVisible(t.data("type"), false)},
      {label: "Pašalink ryšį iš sodo", icon: "remove", run: () => { realEdge(t).remove(); saveGardenSoon(); }}]);
  } else {
    const hiddenN = S.cy.nodes(".hidden").length;
    menu(el, [{label: "Visas sodas", hint: "Shift+Home", icon: "fit", run: fitAll}, {label: "Išdėstyti iš naujo", icon: "layout", run: relayout},
      ...(S.map.on ? [{label: "Išjungti žemėlapį", icon: "mapOff", run: mapOff}] : []),
      ...(hiddenN ? [{label: `Rodyti paslėptus (${hiddenN})`, hint: "Shift+H", icon: "show", run: showHidden}] : []),
      ...(S.cy.nodes().some(n => splitOf(n, "twin")) ? [{label: "Apjungti visus tapačius", hint: "visi išskirti atitikmenys", icon: TWIN_ICON, run: remergeAllTwins}] : []),
      {label: "Pažymėti visus mazgus", icon: "select", run: selectAll}, {label: "Išsaugoti kaip SVG", icon: "svg", run: exportSvg}, {label: "Išsaugoti kaip PNG", icon: "svg", run: exportPng},
      {label: "Išvalyti laikinus radinius", icon: "temps", run: removeTemps}, {label: "Išvalyti sodą", icon: "clear", run: clearGarden}]);
  }
  place(el, ev.clientX, ev.clientY);
}

/** Middle button on a node or relationship: controls that act on that element only. */
async function openElementPanel(el, ev) {
  closeMenus();
  const box = $("#float");
  if (el.isEdge()) {
    if (el.hasClass("more")) return;
    const type = el.data("type"), et = S.settings.edgeTypes[type] || {};
    box.innerHTML = `<div class="fp-head"><span class="mono">${esc(type)}</span>
        <span class="muted">${esc(el.source().data("display_name"))} → ${esc(el.target().data("display_name"))}</span></div>
      <div class="fp-row"><button data-a="offroad">Bekelė</button><button data-a="hideType">Slėpti visus ${esc(type)}</button><button data-a="remove">Pašalinti šį ryšį</button></div>
      <div class="fp-sec">Šio tipo ryšių išvaizda</div>
      <div class="fp-row">storis <input type="number" min="0.5" max="12" step="0.5" value="${et.width || 1.4}" data-f="width" style="width:60px">
        <select data-f="style">${[["solid", "ištisinė"], ["dashed", "brūkšninė"], ["dotted", "taškinė"]].map(([v, l]) => `<option value="${v}" ${(et.style || "solid") === v ? "selected" : ""}>${l}</option>`).join("")}</select>
        <input type="color" value="${esc(et.color || "#b9b5ad")}" data-f="color"></div>`;
    const acts = {offroad: () => offRoad(type), hideType: () => setTypeVisible(type, false), remove: () => { realEdge(el).remove(); saveGardenSoon(); }};
    box.querySelectorAll("[data-a]").forEach(b => b.onclick = () => { closeMenus(); acts[b.dataset.a](); });
    box.querySelectorAll("[data-f]").forEach(inp => inp.oninput = () => {
      const t = (S.settings.edgeTypes[type] = S.settings.edgeTypes[type] || {});
      t[inp.dataset.f] = inp.type === "number" ? Number(inp.value) : inp.value;
      settingsChanged();
    });
    place(box, ev.clientX + 10, ev.clientY + 10);
    return;
  }
  if (el.hasClass("more")) return loadMore(el);
  if (el.hasClass("multi")) { el.select(); return showMultiInfo(el); }
  if (el.hasClass("bundle")) { el.select(); return showBundleInfo(el); }
  if (el.hasClass("twin")) { el.select(); return showTwinInfo(el); }
  touch(el);
  const d = el.data(), nt = S.settings.nodeTypes[d.label] || {};
  box.innerHTML = `<div class="fp-head">${nodePicture(d, 28)}<div><b translate="no">${esc(d.display_name)}</b><div class="muted">${esc(d.label)}${d.dataset ? " · " + esc(d.dataset) : ""}</div></div></div>
    <div class="fp-row"><button data-a="semantic">Išskleisk</button><button data-a="collapse">Suskleisk</button><button data-a="core">Svarbiausia</button><button data-a="all">Viskas</button>
      <button data-a="basket">🧺</button><button data-a="hide">Paslėpk</button>${geoOf(d) && mapAllowed() ? '<button data-a="geo" title="Rodyti žemėlapyje">📍</button>' : ""}
      <button data-a="touch" title="Paliesti mazgai lieka slepiant ryšius">${d.touched ? "✓ paliestas" : "paliesti"}</button></div>
    <div class="fp-sec">Ryšiai pagal tipą <span class="muted">(slepiant paliesti kaimynai lieka)</span></div>
    <div class="fp-rels"><span class="muted">kraunama…</span></div>
    <div class="fp-sec">Visų ${esc(d.label)} išvaizda</div>
    <div class="fp-row"><input type="color" value="${esc(nt.color || typeColor(d.label))}" data-f="color">
      <select data-f="shape">${["ellipse", "round-rectangle", "rectangle", "diamond", "hexagon", "octagon", "triangle", "star", "tag", "barrel"].map(s => `<option ${(nt.shape || "ellipse") === s ? "selected" : ""}>${s}</option>`).join("")}</select></div>`;
  const acts = {semantic: () => expand(el, "semantic"), collapse: () => collapse(el), core: () => expand(el, "core"), all: () => expand(el, "all"), basket: () => addToBasket(el), geo: () => showOnMap(el),
    hide: () => { el.unselect().addClass("hidden"); updateSizes(); renderStatus(); saveGardenSoon(); }, touch: () => { el.data("touched", !d.touched); saveGardenSoon(); }};
  box.querySelectorAll("[data-a]").forEach(b => b.onclick = () => { closeMenus(); acts[b.dataset.a](); });
  box.querySelectorAll("[data-f]").forEach(inp => inp.oninput = () => {
    const t = (S.settings.nodeTypes[d.label] = S.settings.nodeTypes[d.label] || {});
    t[inp.dataset.f] = inp.value;
    if (inp.dataset.f === "color") S.cy.nodes(`[label = "${d.label}"]`).data("color", inp.value);
    settingsChanged();
  });
  place(box, ev.clientX + 10, ev.clientY + 10);
  try {
    const info = await api(`/api/sodas/node?label=${encodeURIComponent(d.label)}&key=${encodeURIComponent(d.key)}`);
    const shownOf = (type, out) => el.connectedEdges(`[type = "${type}"]`).filter(e => (e.source().id() === el.id()) === out).length;
    box.querySelector(".fp-rels").innerHTML = info.relationship_counts.map((c, i) => `<div class="rel-row"><span>${c.out ? "→" : "←"} <span class="mono">${esc(c.type)}</span></span>
        <span class="n">${shownOf(c.type, c.out)} / ${c.count}</span><button data-show="${i}">rodyti</button><button data-hide="${i}">slėpti</button></div>`).join("") || '<span class="muted">nėra</span>';
    box.querySelectorAll("[data-show]").forEach(b => b.onclick = () => { closeMenus(); expand(el, "all", [info.relationship_counts[b.dataset.show].type]); });
    box.querySelectorAll("[data-hide]").forEach(b => b.onclick = () => { closeMenus(); const c = info.relationship_counts[b.dataset.hide]; hideRelType(el, c.type, c.out); });
    place(box, ev.clientX + 10, ev.clientY + 10);
  } catch (e) { box.querySelector(".fp-rels").innerHTML = '<span class="muted">nepavyko</span>'; }
}

// ---------------------------------------------------------------- view actions
function fitAll() { S.cy.animate({fit: {eles: S.cy.elements(":visible"), padding: 40}, duration: 250}); }
function centerOn(node) {
  const n = node || S.cy.$("node:selected");
  if (!n || n.empty()) return toast("Nepažymėtas joks mazgas");
  S.cy.animate({center: {eles: n}, zoom: Math.max(S.cy.zoom(), 1), duration: 250});
}
function relayout() {
  const opts = {name: "cose", animate: false, nodeRepulsion: 12000, idealEdgeLength: 80, componentSpacing: 40, padding: 40, randomize: false};
  if (!S.map.on) S.cy.elements(":visible").layout(opts).run();
  else {
    // on the map each geo node (locked) is laid out only with its own surroundings, so they do not drift across the map
    const groups = new Map(), u = unit();
    S.cy.nodes(":visible").forEach(n => {
      const o = n.data("mapRel") ? n.data("mapOwner") : geoNodes().contains(n) ? n.id() : null;
      if (o) groups.set(o, (groups.get(o) || S.cy.collection()).union(n));
    });
    const scaled = {...opts, nodeRepulsion: opts.nodeRepulsion * u * u, idealEdgeLength: opts.idealEdgeLength * u, componentSpacing: 40 * u, fit: false};
    for (const nodes of groups.values()) if (nodes.length > 1) nodes.union(nodes.edgesWith(nodes)).layout(scaled).run();
    rebind(S.cy.nodes());
  }
  saveGardenSoon();
}
/** "Suskleisk" (the opposite of "Išskleisk"): neighbours related to nothing else in the garden but this node go away,
 *  with this node's "+N" nodes. Basket nodes stay. */
function collapse(node) {
  const cy = S.cy, basket = new Set(S.garden.basket), core = node.hasClass("virtual") ? members(node) : node;
  const ids = new Set(core.map(n => n.id()));
  const alone = m => m.connectedEdges().not(".more, .virtual").every(e => ids.has(e.source().id()) || ids.has(e.target().id()));
  const gone = core.neighborhood("node").not(".more, .virtual").difference(core).filter(m => !basket.has(m.id()) && alone(m));
  const more = cy.nodes(".more").filter(m => ids.has(m.data("parent_node")) || gone.getElementById(m.data("parent_node")).nonempty());
  gone.union(more).remove();
  updateMerges();
  touch(node);
  toast(gone.length ? `${node.data("display_name")}: suskleista, pašalinta ${gone.length} mazgų` : "Nėra mazgų, susijusių tik su šiuo mazgu");
  saveGardenSoon();
}
function focusNode(n) {
  const keep = n.closedNeighborhood();
  S.cy.elements().not(keep).addClass("dim");
  keep.removeClass("dim");
}
/** "Pažymėti visus" (background menu): every node shown in the garden (a group selection: nothing counts as touched). */
function selectAll() {
  S.boxing = true;
  S.cy.nodes(":visible").not(".more").select();
  S.boxing = false;
  syncSelectionButtons();
  toast(`Pažymėta mazgų: ${S.cy.$("node:selected").length}`, "info", 1500);
}
function hideSelected() {
  const sel = selectedReal(S.cy.$("node:selected"));
  if (sel.empty()) return toast("Nepažymėtas joks mazgas");
  sel.unselect().addClass("hidden");
  toast(`Paslėpta ${sel.length} – jie nebeskaičiuojami į sodo ribas. Grąžinti: dešinys klavišas fone → „Rodyti paslėptus“ arba Shift+H`);
  updateSizes(); renderStatus(); saveGardenSoon();
}
function showHidden() { const h = S.cy.nodes(".hidden"); h.removeClass("hidden"); toast(`Parodyta ${h.length}`); updateSizes(); renderStatus(); saveGardenSoon(); }
function removeSelected() {
  const sel = selectedReal(S.cy.$(":selected"));
  if (sel.empty()) return;
  const moreOf = S.cy.nodes(".more").filter(m => sel.getElementById(m.data("parent_node")).nonempty());
  sel.union(moreOf).remove();
  S.garden.basket = S.garden.basket.filter(b => S.cy.getElementById(b).nonempty());
  pruneManual();
  updateMerges(); renderBasket();
  saveGardenSoon();
}
function clearGarden() { S.cy.elements().remove(); S.garden.basket = []; S.garden.manual = []; renderBasket(); saveGardenSoon(); }
function toggleLabels(which) { S.settings.ui[which] = !S.settings.ui[which]; settingsChanged("style"); syncToolbar(); }
function syncToolbar() {
  $$("#typesPanel [data-labels]").forEach(cb => { cb.checked = !!S.settings.ui[cb.dataset.labels]; });
  $('[data-act="basket"]').classList.toggle("on", !$("#basket").hidden);
  syncSelectionButtons();
}
/** "Kelias" is offered only when exactly two nodes are selected; "Į atskirą sodą" when at least one is. */
function syncSelectionButtons() {
  if (!S.cy) return;
  const n = S.cy.$("node:selected").not(".more").length;
  $("#pathBtn").hidden = n !== 2;
  $("#splitBtn").disabled = n === 0;
}

// ---------------------------------------------------------------- "Rodinys" (👁): node and relationship types in the garden
// Only the types present in the garden are listed, checked while shown. A node type is hidden by a style rule
// (S.garden.labelHidden), so nodes of that type added later – and merged "×N" nodes of it – stay hidden too;
// Cytoscape does not draw the relationships of a hidden node. A relationship type is hidden by the class
// "type-hidden" (S.garden.typeVis[type] === false).
const labelShown = n => !S.garden.labelHidden[n.data("label")] && !(n.hasClass("more") && S.garden.labelHidden[n.data("parent_label")]);
function setTypeVisible(type, visible) {
  if (visible) {
    delete S.garden.typeVis[type];
    S.cy.edges(`[type = "${type}"]`).removeClass("type-hidden");
  } else {
    S.garden.typeVis[type] = false;
    S.cy.edges(`[type = "${type}"]`).addClass("type-hidden");
    toast(`${type} ryšiai paslėpti (grąžinami per 👁 „Rodinys“)`);
  }
  updateSizes(); renderStatus(); saveGardenSoon();
  if (!$("#typesPanel").hidden) renderTypesPanel();
}
function setLabelVisible(label, visible) {
  if (visible) delete S.garden.labelHidden[label];
  else {
    S.garden.labelHidden[label] = true;
    const gone = S.cy.nodes(`[label = "${label}"]`);
    gone.unselect();
    toast(`${label}: paslėpta ${gone.not(".virtual").length} mazgų su jų ryšiais (grąžinami per 👁 „Rodinys“)`);
  }
  restyle(); updateSizes(); renderStatus(); scheduleOverlay(); saveGardenSoon();
  if (!$("#typesPanel").hidden) renderTypesPanel();
}
function toggleTypesPanel() {
  const p = $("#typesPanel");
  p.hidden = !p.hidden;
  if (!p.hidden) renderTypesPanel();
}
function renderTypesPanel() {
  const p = $("#typesPanel"), G = S.garden, labels = new Map(), rels = new Map();
  S.cy.nodes().not(".more, .virtual").forEach(n => { const l = n.data("label"); if (l) labels.set(l, (labels.get(l) || 0) + 1); });
  S.cy.edges().not(".more, .virtual").forEach(e => { const t = e.data("type"); if (t) rels.set(t, (rels.get(t) || 0) + 1); });
  const sorted = m => [...m].sort((a, b) => a[0].localeCompare(b[0]));
  const allBtn = (kind, any) => any ? `<a class="all" data-all="${kind}">rodyti visus</a>` : "";
  // the labels of nodes and relationships (Ctrl+Shift+1 / Ctrl+Alt+1), then the types in the garden
  const ui = S.settings.ui;
  p.innerHTML = `<h4><span>Užrašai</span></h4>
    <label class="tl"><input type="checkbox" data-labels="nodeLabels" ${ui.nodeLabels ? "checked" : ""}>Mazgų pavadinimai<span class="n">Ctrl+Shift+1</span></label>
    <label class="tl"><input type="checkbox" data-labels="edgeLabels" ${ui.edgeLabels ? "checked" : ""}>Ryšių pavadinimai<span class="n">Ctrl+Alt+1</span></label>` +
    (!labels.size ? '<div class="none">Sode dar nėra mazgų.</div>' :
    `<h4><span>Mazgų tipai sode</span>${allBtn("labels", Object.keys(G.labelHidden).some(l => labels.has(l)))}</h4>` +
    sorted(labels).map(([l, n]) => `<label class="tl"><input type="checkbox" data-label="${esc(l)}" ${G.labelHidden[l] ? "" : "checked"}>
      <span class="dot" style="background:${esc(typeColor(l))}"></span>${esc(l)}<span class="n">${n.toLocaleString(LOCALE)}</span></label>`).join("") +
    (rels.size ? `<h4><span>Ryšių tipai sode</span>${allBtn("rels", [...rels.keys()].some(t => G.typeVis[t] === false))}</h4>` +
      sorted(rels).map(([t, n]) => `<label class="tl"><input type="checkbox" data-rel="${esc(t)}" ${G.typeVis[t] === false ? "" : "checked"}>
        <span class="mono">${esc(t)}</span><span class="n">${n.toLocaleString(LOCALE)}</span></label>`).join("") : ""));
  p.querySelectorAll("[data-labels]").forEach(cb => cb.onchange = () => { if (!!S.settings.ui[cb.dataset.labels] !== cb.checked) toggleLabels(cb.dataset.labels); });
  p.querySelectorAll("[data-label]").forEach(cb => cb.onchange = () => setLabelVisible(cb.dataset.label, cb.checked));
  p.querySelectorAll("[data-rel]").forEach(cb => cb.onchange = () => setTypeVisible(cb.dataset.rel, cb.checked));
  p.querySelectorAll("[data-all]").forEach(a => a.onclick = () => {
    if (a.dataset.all === "labels") { G.labelHidden = {}; restyle(); updateSizes(); renderStatus(); scheduleOverlay(); saveGardenSoon(); renderTypesPanel(); }
    else for (const t of Object.keys(G.typeVis)) if (G.typeVis[t] === false) setTypeVisible(t, true);
  });
}

// ---------------------------------------------------------------- basket & paths
/** Puts a node into the basket; returns how many nodes were new there (a merged node puts all its nodes). */
function toBasket(n) {
  if (n.hasClass("virtual")) return members(n).map(toBasket).reduce((a, b) => a + b, 0);
  if (n.hasClass("more") || n.hasClass("bundle") || n.hasClass("lexmap")) return 0;
  if (n.hasClass("temp")) promoteTemp(n);
  touch(n);
  const added = S.garden.basket.includes(n.id()) ? 0 : (S.garden.basket.push(n.id()), 1);
  renderBasket(); syncToolbar(); saveGardenSoon();
  return added;
}
/** „Pridėti prie krepšio“: the given (or the selected) nodes. */
function addToBasket(nodes) {
  const sel = nodes || S.cy.$("node:selected").not(".more");
  if (sel.empty()) return toast("Nepažymėtas joks mazgas – pažymėkite mazgus, kuriuos dėti į krepšį");
  let added = 0;
  sel.forEach(n => { added += toBasket(n); });
  toast(added ? `Į krepšį įdėta: ${added} (iš viso ${S.garden.basket.length})` : "Šie mazgai jau krepšyje", "info", 2500);
}
function toggleBasket(show) { $("#basket").hidden = show === undefined ? !$("#basket").hidden : !show; renderBasket(); syncToolbar(); }
/** The 🧺 button: the selected nodes go into the basket; with nothing selected it shows (or hides) the basket. */
function basketClick() {
  if (S.cy.$("node:selected").not(".more").nonempty()) addToBasket();
  else toggleBasket();
}
function clearBasket() {
  const n = S.garden.basket.length;
  S.garden.basket = []; renderBasket(); syncToolbar(); saveGardenSoon();
  toast(`Krepšys išvalytas (${n} mazg.)`);
}
/** ▾ beside 🧺: rodyti krepšį, pridėti prie krepšio, išvalyti krepšį. */
function toggleBasketMenu() {
  const m = $("#basketMenu");
  if (!m.hidden) { m.hidden = true; return; }
  const sel = S.cy.$("node:selected").not(".more").length, n = S.garden.basket.length;
  m.innerHTML = `<div class="item" data-b="show"><span>🧺 ${$("#basket").hidden ? "Rodyti krepšį" : "Slėpti krepšį"}</span><span class="ds">${n} mazg.</span></div>
    <div class="item${sel ? "" : " off"}" data-b="add"><span>＋ Pridėti prie krepšio</span><span class="ds">${sel ? `pažymėta ${sel}` : "nieko nepažymėta"}</span></div>
    <div class="item${n ? "" : " off"}" data-b="clear"><span>🗑 Išvalyti krepšį</span><span class="ds">sode mazgai lieka</span></div>`;
  m.hidden = false;
  m.querySelectorAll("[data-b]").forEach(it => it.onclick = ev => {
    ev.stopPropagation();
    if (it.classList.contains("off")) return;
    const b = it.dataset.b;
    if (b === "clear" && it.dataset.sure !== "1") { it.dataset.sure = "1"; it.querySelector("span").textContent = "🗑 Tikrai išvalyti krepšį?"; return; }
    m.hidden = true;
    if (b === "show") toggleBasket(); else if (b === "add") addToBasket(); else clearBasket();
  });
}
function renderBasket() {
  $("#basketCount").textContent = S.garden.basket.length;
  const el = $("#basket");
  if (el.hidden) return;
  const items = S.garden.basket.map(id => S.cy.getElementById(id)).filter(n => n.nonempty());
  const excluded = S.garden.excluded || [];
  el.innerHTML = `<button class="close" onclick="this.parentNode.hidden=true;syncToolbar()">×</button><h3>🧺 Tyrimo krepšys</h3>
    <div class="muted" style="font-size:.85em">Pažymėkite du mazgus kelio paieškai (arba pažymėkite juos sode su Shift).</div>
    <div style="margin-top:6px"><button id="basketClear" class="danger" ${S.garden.basket.length ? "" : "disabled"}
      title="Išimti visus mazgus iš krepšio (sode jie lieka)">Išvalyti krepšį</button></div>
    <section>${items.map(n => `<div class="rel-row"><input type="checkbox" data-pick="${esc(n.id())}">
        ${nodePicture(n.data(), 18)}<a href="#" data-go="${esc(n.id())}">${esc(n.data("display_name"))}</a>
        <span class="n">${esc(n.data("label"))}</span><button data-rm="${esc(n.id())}" title="Išimti">×</button></div>`).join("") || '<span class="muted">tuščia – dešiniu klavišu „Pridėk į krepšį“</span>'}</section>
    <section><h4>Kelio paieška</h4>
      <div class="muted" style="font-size:.85em">Ieškoma trumpiausių kelių, kad ir kokie ilgi jie būtų.</div>
      <button class="primary" id="pathGo" style="margin-top:6px">⇝ Rasti trumpiausius kelius</button></section>
    <section><h4>Bekelės (neinama per šiuos ryšius)</h4>${excluded.map(t => `<span class="chip mono">${esc(t)}<button data-x="${esc(t)}">×</button></span>`).join("") || '<span class="muted">nėra</span>'}</section>
    <section id="pathList"></section>`;
  $("#basketClear").onclick = e => {
    const b = e.target;
    if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = "Tikrai išvalyti?"; return; }
    clearBasket();
  };
  el.querySelectorAll("[data-rm]").forEach(b => b.onclick = () => { S.garden.basket = S.garden.basket.filter(x => x !== b.dataset.rm); renderBasket(); saveGardenSoon(); });
  el.querySelectorAll("[data-go]").forEach(a => a.onclick = ev => { ev.preventDefault(); const n = S.cy.getElementById(a.dataset.go); S.cy.$(":selected").unselect(); n.removeClass("hidden").select(); centerOn(n); });
  el.querySelectorAll("[data-x]").forEach(b => b.onclick = () => { S.garden.excluded = excluded.filter(t => t !== b.dataset.x); renderBasket(); saveGardenSoon(); });
  $("#pathGo").onclick = () => findPath();
  renderPathList();
}
function pathPair() {
  const sel = S.selOrder.map(id => S.cy.getElementById(id)).filter(n => n.nonempty() && n.selected() && !n.hasClass("more") && !n.hasClass("virtual") && !n.hasClass("bundle"));
  if (sel.length === 2) return sel;
  const picked = $$("#basket [data-pick]:checked").map(c => S.cy.getElementById(c.dataset.pick)).filter(n => n.nonempty());
  if (picked.length >= 2) return picked.slice(0, 2);
  const b = S.garden.basket.map(id => S.cy.getElementById(id)).filter(n => n.nonempty());
  return b.length >= 2 ? b.slice(0, 2) : null;
}
async function findPath(pair) {
  pair = Array.isArray(pair) ? pair : pathPair();
  if (!pair) return toast("Pažymėkite du mazgus (Shift + spustelėjimas) arba įdėkite du į krepšį", "warning");
  const [a, b] = pair.map(n => ({label: n.data("label"), key: n.data("key"), id: n.id()}));
  toast(`Ieškomi keliai: ${pair[0].data("display_name")} ⇝ ${pair[1].data("display_name")}…`, "info", 2500);
  const r = await api("/api/sodas/paths", {a, b, excluded: S.garden.excluded});
  S.lastPath = {a, b, result: r};
  if (!r.paths.length) { S.cy.elements().removeClass("path"); toast(`Kelio tarp šių mazgų nėra${(S.garden.excluded || []).length ? " (neinant per bekeles)" : ""}`, "warning"); renderPathList(); return; }
  addGraph({nodes: r.nodes, edges: r.edges}, {center: a.id, force: true});
  for (const id of r.paths.flatMap(p => p.nodes)) S.cy.getElementById(id).removeClass("hidden");
  for (const id of r.paths.flatMap(p => p.edges)) S.cy.getElementById(id).removeClass("type-hidden");
  highlightPaths(r.paths);
  $("#basket").hidden = false; renderBasket(); syncToolbar();
  toast(`Rasta ${r.paths.length}${r.truncated ? "+" : ""} trumpiausių kelių, ilgis ${r.length}`);
}
function highlightPaths(paths) {
  S.cy.elements().removeClass("path");
  for (const p of paths) for (const id of [...p.nodes, ...p.edges]) S.cy.getElementById(id).addClass("path");
}
function renderPathList() {
  const el = $("#pathList");
  if (!el || !S.lastPath) return;
  const r = S.lastPath.result;
  const name = id => { const n = S.cy.getElementById(id); return n.nonempty() ? n.data("display_name") : id.split("|").pop(); };
  el.innerHTML = `<h4>Keliai (${r.paths.length})</h4>` + (r.paths.map((p, i) => `<div class="path-item" data-p="${i}">${i + 1}. ${p.nodes.map(id => esc(name(id))).join(" → ")}</div>`).join("") || '<span class="muted">nerasta</span>');
  el.querySelectorAll("[data-p]").forEach(d => d.onclick = () => highlightPaths([r.paths[d.dataset.p]]));
}
function offRoad(type) {
  S.garden.excluded = [...new Set([...(S.garden.excluded || []), type])];
  toast(`Bekelė: ${type} ryšiai kelių paieškoje nenaudojami`);
  saveGardenSoon();
  renderBasket();
  if (S.lastPath) {
    const pair = [S.cy.getElementById(S.lastPath.a.id), S.cy.getElementById(S.lastPath.b.id)];
    if (pair.every(n => n.nonempty())) findPath(pair);
  }
}

// ---------------------------------------------------------------- Ctrl+J: relationships drawn in the garden
// Written to Neo4j at once (dataset „Papildymai“); listed in ⚙ → Mano ryšiai, where they can be deleted (rysiai.py).
async function linkSelected() {
  const sel = S.selOrder.map(id => S.cy.getElementById(id)).filter(n => n.nonempty() && n.selected() && !n.hasClass("more") && !n.hasClass("virtual") && !n.hasClass("bundle"));
  if (sel.length !== 2) return toast("Pažymėkite lygiai du mazgus (Shift + spustelėjimas)", "warning");
  relationshipDialog(...sel);
}
async function relationshipDialog(a, b) {
  // the list: the types Neo4j has and the names given to one's own relationships before
  let mine = [];
  try { mine = (await api("/api/sodas/rysiai/uzrasai")).labels; } catch (e) { /* toast shown */ }
  const types = S.schema.types.filter(t => t !== "CUSTOM" && /^[A-Z][A-Z0-9_]*$/.test(t));
  const draw = () => {
    $("#modalBody").innerHTML = `<h3>Naujas ryšys</h3>
      <div class="title-row small">${nodePicture(a.data(), 22)}<b>${esc(a.data("display_name"))}</b> → ${nodePicture(b.data(), 22)}<b>${esc(b.data("display_name"))}</b>
        <button id="swap" title="Sukeisti kryptį">⇄</button></div>
      <label>Ryšys <input id="relType" list="relTypes" placeholder="pasirinkite arba įrašykite, pvz. panašus į" style="width:100%" maxlength="100"></label>
      <datalist id="relTypes">${mine.map(t => `<option value="${esc(t)}">mano</option>`).join("")}${types.map(t => `<option value="${esc(t)}">`).join("")}</datalist>
      <div class="muted" style="font-size:.85em">Duomenų bazės tipas (pvz. <span class="mono">${esc(types[0] || "SIMILAR_TO")}</span>) naudojamas toks, koks yra; bet koks kitas pavadinimas
        tampa ryšiu <span class="mono">CUSTOM</span> su šiuo užrašu – jį sode matysite vietoj tipo.</div>
      <label>Pastaba <textarea id="relNote" rows="2" style="width:100%"></textarea></label>
      <div class="muted" style="font-size:.85em">Ryšys įrašomas į Neo4j (duomenynas „Papildymai“); jų sąrašas – ⚙ → Mano ryšiai.</div>
      <div class="actions"><button id="mCancel">Atšaukti</button><button class="primary" id="mOk">Sukurti</button></div>`;
    $("#swap").onclick = () => { [a, b] = [b, a]; draw(); };
    $("#mCancel").onclick = () => $("#modal").hidden = true;
    $("#mOk").onclick = async () => {
      const name = $("#relType").value.trim();
      if (!name) return $("#relType").focus();
      try {
        const edge = await api("/api/sodas/relationship", {a: {label: a.data("label"), key: a.data("key")}, b: {label: b.data("label"), key: b.data("key")}, type: name,
          note: $("#relNote").value});
        addGraph({nodes: [], edges: [edge]}, {force: true});
        if (edge.type !== "CUSTOM" && !S.schema.types.includes(edge.type)) S.schema.types.push(edge.type);
        $("#modal").hidden = true;
        toast(`Sukurtas ryšys „${edgeName(edge)}“`);
      } catch (e) { /* toast shown */ }
    };
    $("#modal").hidden = false;
    $("#relType").focus();
  };
  draw();
}
/** A relationship drawn in the garden: its props (dataset „Papildymai“), else null. */
const ADDITIONS = new Set(["Papildymai"]);
const drawnRel = e => { const p = e && e.data("props"); return p && ADDITIONS.has(p.dataset) ? p : null; };
async function deleteRelationship(edge) {
  const p = drawnRel(edge);
  if (!p) return;
  if (!confirm(`Ištrinti ryšį „${edgeName(edge)}“ iš duomenų bazės?`)) return;
  // one of its nodes: Neo4j finds the relationship from there instead of reading every relationship of the database
  const end = edge.source();
  await api("/api/sodas/rysiai/istrinti", {key: p.key, end: {label: end.data("label"), key: end.data("key")}});
  S.cy.edges().filter(e => (drawnRel(e) || {}).key === p.key).remove();
  saveGardenSoon();
  toast("Ryšys ištrintas");
  $("#info").hidden = true;
}
/** Menu items for a drawn relationship. */
function relMenuItems(edge) {
  return drawnRel(edge) ? [{label: "Ištrinti ryšį", hint: "iš duomenų bazės", icon: "remove", run: () => deleteRelationship(edge)}] : [];
}

// ---------------------------------------------------------------- search
const runSearch = debounce(async () => {
  const q = $("#q").value.trim();
  S.search.q = q;
  clearTimeout(S.search.fillTimer);
  removeTemps();
  if (!q) { $("#results").hidden = true; return; }
  let r;
  try { r = await api(`/api/sodas/search?q=${encodeURIComponent(q)}`); } catch (e) { return; }
  if (q !== $("#q").value.trim()) return;
  S.search.groups = r.groups; S.search.types = r.types; S.search.cursor = -1;
  renderResults();
  if (semanticCount() === 0 && r.groups.length) S.search.fillTimer = setTimeout(() => fillTemp(q), 2500);
}, 250);

function flatResults() { return S.search.groups.flatMap(g => g.items); }
function renderResults() {
  const box = $("#results");
  const {groups, types} = S.search;
  box.hidden = false;
  if (!groups.length && !types.length) { box.innerHTML = '<div class="none">Nieko nerasta</div>'; return; }
  const flat = flatResults();
  box.innerHTML = groups.map((g, gi) => `<h4><span><span class="dot" style="background:${esc(typeColor(g.label))}"></span> ${esc(g.label)}</span>
      <span>${g.more ? "1000+" : g.total}</span></h4>` +
    g.items.map(it => `<div class="item ${flat.indexOf(it) === S.search.cursor ? "cur" : ""}" data-f="${flat.indexOf(it)}">
      <span translate="no">${esc(it.display_name)}</span><span class="ds">${esc(it.dataset || "")}</span></div>`).join("") +
    (g.items.length < g.total ? `<div class="more" data-g="${gi}">rodyti daugiau (${g.items.length} iš ${g.more ? "1000+" : g.total})</div>` : "")).join("") +
    (types.length ? `<h4><span>Ryšių tipai</span></h4>` + types.map(t => `<div class="item" data-t="${esc(t.type)}"><span class="mono">${esc(t.type)}</span><span class="ds">${t.count}</span></div>`).join("") : "");
  box.querySelectorAll("[data-f]").forEach(el => el.onmousedown = ev => { ev.preventDefault(); pickResult(Number(el.dataset.f)); });
  box.querySelectorAll("[data-g]").forEach(el => el.onmousedown = async ev => {
    ev.preventDefault();
    const g = groups[el.dataset.g];
    const r = await api(`/api/sodas/search?q=${encodeURIComponent(S.search.q)}&label=${encodeURIComponent(g.label)}&skip=${g.items.length}&limit=20`);
    g.items.push(...(r.groups[0] ? r.groups[0].items : []));
    renderResults();
  });
  box.querySelectorAll("[data-t]").forEach(el => el.onmousedown = ev => {
    ev.preventDefault();
    const edges = S.cy.edges(`[type = "${el.dataset.t}"]`);
    S.cy.$(":selected").unselect(); edges.select();
    toast(edges.length ? `Sode pažymėta ${edges.length} ${el.dataset.t} ryšių` : `Sode ${el.dataset.t} ryšių nėra; išskleiskite mazgus, kurie juos turi`);
  });
}
async function pickResult(i) {
  const it = flatResults()[i];
  if (!it) return;
  S.search.cursor = i;
  $("#results").hidden = true;
  await addNode(it);
}
function nextResult() {
  const flat = flatResults();
  if (!flat.length) { $("#q").focus(); return; }
  pickResult((S.search.cursor + 1) % flat.length);
}
function fillTemp(q) {
  if (q !== S.search.q || semanticCount() > 0) return;
  const items = S.search.groups.flatMap(g => g.items.slice(0, 3)).slice(0, 15);
  addGraph({nodes: items.map(i => ({...i, degree: null, props: {}})), edges: []}, {temp: true});
  S.cy.layout({name: "circle", eles: S.cy.nodes(".temp"), animate: false, padding: 60}).run();
  S.cy.fit(S.cy.nodes(), 80);
  api("/api/sodas/nodes", {nodes: items.map(i => ({label: i.label, key: i.key}))}).then(r => {
    for (const n of r.nodes) { const el = S.cy.getElementById(n.id); if (el.nonempty()) el.data({degree: n.degree, props: n.props}); }
    updateSizes(); updateMap();
  }).catch(() => {});
  toast("Radiniai laikinai parodyti sode – pasirinkite mazgą, kad jis liktų", "info", 3500);
}

// ---------------------------------------------------------------- gardens (one per browser tab)
function gardenSnapshot() {
  if (S.lexMap) return S.lexMap.snapshot;  // the lexeme map is a temporary view: the garden stays as it was
  const cy = S.cy;
  const keep = cy.elements().not(".temp, .virtual").filter(el => el.isEdge() ? !el.source().hasClass("temp") && !el.target().hasClass("temp") : true);
  const cls = el => el.classes().filter(c => c !== "path" && c !== "dim" && c !== "merged" && c !== "ds-off" && c !== "map-hidden");
  return {
    name: S.garden.name, excluded: S.garden.excluded, basket: S.garden.basket,
    typeVis: S.garden.typeVis, labelHidden: S.garden.labelHidden, unmerged: S.garden.unmerged, untwinned: S.garden.untwinned,
    manual: S.garden.manual,
    nodes: keep.nodes().map(n => ({data: n.data(), position: n.position(), classes: cls(n)})),
    edges: keep.edges().map(e => ({data: e.data(), classes: cls(e)})),
    viewport: {zoom: cy.zoom(), pan: cy.pan(), map: S.map.on, mapOffset: S.map.offset, mapAnchor: S.map.anchor, mapView: S.map.view},
  };
}
const saveGardenSoon = debounce(saveGardenNow, 700);
function saveGardenNow() {
  if (!S.garden.id || S.restoring) return Promise.resolve();
  return api(`/api/sodas/gardens/${S.garden.id}`, gardenSnapshot()).catch(() => {});
}
function rememberGarden(id) { Kalba.rememberGarden(id); }   // the last garden (bar.js): Vaiva and Žemė lead back to it
/** Garden of this tab: ?sodas=…, then the one this tab used before (after visiting Vaiva), then the last one. */
async function initialGardenId() {
  const fromUrl = new URLSearchParams(location.search).get("sodas");
  if (fromUrl && GARDEN_ID.test(fromUrl)) return fromUrl;
  let id = null;
  try { id = sessionStorage.getItem("kalba.garden") || Kalba.lastGarden(); } catch (e) { /* ignore */ }
  return id && GARDEN_ID.test(id) ? id : (await api("/api/sodas/gardens")).new_id;
}
/** The address shows this garden (and the settings section). ``push``: another garden opened in place of the last one
 *  is a new step of the browser's history, so ← (the bar's or the browser's) goes back to the garden one came from. */
function syncUrl(push = false) {
  const path = $("#settings").hidden ? "/" : "/nustatymai";
  const url = `${path}?sodas=${S.garden.id}${path === "/nustatymai" && settingsSection !== "theme" ? `&skiltis=${settingsSection}` : ""}`;
  const vaiva = document.getElementById("navVaiva");
  if (vaiva) vaiva.href = `/vaiva?sodas=${S.garden.id}`;
  const was = new URLSearchParams(location.search).get("sodas");
  if (location.pathname + location.search !== url) history[push && was && was !== S.garden.id ? "pushState" : "replaceState"]({sodas: S.garden.id}, "", url);
  window.dispatchEvent(new Event("sodas-history"));
}
/** ← / → of the browser or the bar: the garden (and the settings) of that step. */
window.addEventListener("popstate", async () => {
  const id = new URLSearchParams(location.search).get("sodas");
  if (!S.cy || !id || !GARDEN_ID.test(id)) return;
  if (id !== S.garden.id) {
    await saveGardenNow();
    await loadGarden(id);
  }
  const inSettings = location.pathname === "/nustatymai";
  if (inSettings && $("#settings").hidden) openSettings(new URLSearchParams(location.search).get("skiltis") || undefined);
  else if (!inSettings && !$("#settings").hidden) closeSettings();
});
async function loadGarden(id, push = false) {
  let g;
  try { g = await api(`/api/sodas/gardens/${id}`); }
  catch (e) {
    if (e.status !== 400) throw e;
    id = randomGardenId(); g = {};   // a bad id: a new garden instead
  }
  applyGarden(id, g, push);
}
/** Gardens split off the map of a merged node before this was fixed kept its nodes as lm|label|key: they become
 *  real nodes (label|key), and one already in the garden wins. */
function realNodes(nodes) {
  const ids = new Set(nodes.map(n => n.data.id));
  return nodes.flatMap(n => {
    if (!String(n.data.id).startsWith("lm|")) return [n];
    const id = `${n.data.label}|${n.data.key}`;
    if (ids.has(id)) return [];
    ids.add(id);
    const cls = Array.isArray(n.classes) ? n.classes.filter(c => c !== "lexmap" && c !== "lexmap-off") : n.classes;
    return [{...n, data: {...n.data, id}, classes: cls}];
  });
}
/** Show garden ``g`` (as saved, or a snapshot taken before a temporary view such as the lexeme map). */
function applyGarden(id, g, push = false) {
  S.lexMap = null;
  $("#lexInfo").hidden = true;
  S.garden = {id, name: g.name || "", excluded: g.excluded || [...S.settings.pathExcluded], basket: g.basket || [],
    typeVis: g.typeVis || {}, labelHidden: g.labelHidden || {}, unmerged: g.unmerged || [], untwinned: g.untwinned || [],
    manual: Array.isArray(g.manual) ? g.manual.filter(m => m && Array.isArray(m.members) && m.id) : []};
  $("#gardenName").value = S.garden.name;
  document.title = pageTitle();
  S.restoring = true;
  mapOff({restore: false});
  S.cy.elements().remove();
  S.cy.add(realNodes(g.nodes || []).map(n => ({group: "nodes", data: n.data, position: n.position, classes: n.classes})));
  S.cy.add((g.edges || []).map(e => ({group: "edges", data: e.data, classes: e.classes})));
  // hidden relationship types belong to this garden only: nothing is hidden that its typeVis does not hide
  S.cy.edges(".type-hidden").filter(e => S.garden.typeVis[e.data("type")] !== false).removeClass("type-hidden");
  restyle();  // hidden node types (labelHidden) are style rules: those of the previous garden must go
  // "+N" nodes saved before they knew their parent's type
  S.cy.nodes(".more").filter(m => !m.data("parent_label")).forEach(m => m.data("parent_label", S.cy.getElementById(m.data("parent_node")).data("label")));
  applyDatasetsOff();
  // the map first (it allows other zoom levels); gardens saved before the offset existed used offset 0
  const view = g.viewport;
  if (view && view.map && mapAllowed()) {
    S.map.anchor = view.mapAnchor || null;
    S.map.view = view.mapView || null;
    mapOn(view.mapOffset || {x: 0, y: 0});
    S.cy.zoom(view.zoom); S.cy.pan(view.pan);
    attachToMap(); arrangeMap(); syncMapView(true);
  } else updateMerges();
  if (view) { S.cy.zoom(view.zoom); S.cy.pan(view.pan); }
  else if (S.cy.nodes().nonempty()) S.cy.fit(undefined, 40);
  S.restoring = false;
  S.lastPath = null;
  rememberGarden(id); syncUrl(push);
  updateSizes(); refreshOverlay(); renderBasket(); renderStatus(); syncToolbar(); syncMapControls();
  fetchGeo(S.cy.nodes().map(n => n.id()));
  refreshNodes();
  $("#empty").hidden = S.cy.nodes().length > 0;
  if (!$("#typesPanel").hidden) renderTypesPanel();
}
/** A garden keeps a copy of its nodes' data: names and properties are brought up to date from Neo4j when it opens
 *  (a dataset imported again, LKEŽDB languages named anew), and the computed properties follow. */
async function refreshNodes() {
  const gardenId = S.garden.id;
  const nodes = S.cy.nodes().not(".more, .virtual").filter(n => n.data("label") && n.data("key"));
  if (nodes.empty()) return;
  let r;
  try { r = await api("/api/sodas/nodes", {nodes: nodes.map(n => ({label: n.data("label"), key: n.data("key")}))}); } catch (e) { return; }
  if (S.garden.id !== gardenId || S.lexMap) return;
  let changed = 0;
  for (const fresh of r.nodes) {
    const n = S.cy.getElementById(fresh.id);
    if (n.empty()) continue;
    if (n.data("display_name") !== fresh.display_name || JSON.stringify(n.data("props") || {}) !== JSON.stringify(fresh.props || {})) {
      n.data({display_name: fresh.display_name, props: fresh.props, dataset: fresh.dataset, caption: caption(fresh)});
      changed++;
    }
    if (fresh.degree != null) n.data("degree", fresh.degree);
  }
  if (!changed) return;
  S.cy.nodes().removeData("computed");
  fetchComputed(S.cy.nodes().map(n => n.id()));
  updateMerges(); saveGardenSoon();
}
async function switchGarden(id) {
  if (id === S.garden.id) return;
  await saveGardenNow();
  await loadGarden(id, true);
}
/** Browser tab title: "<garden name> - Sodas". */
const pageTitle = () => S.garden.name ? `${S.garden.name} - Sodas` : "Sodas";
const randomGardenId = () => [...crypto.getRandomValues(new Uint8Array(4))].map(b => b.toString(16).padStart(2, "0")).join("");
/** A new, empty garden opens at once (here or in a new tab); it is saved once it has content or a name. */
async function newGarden(inNewTab) {
  // a new tab must open synchronously inside the click, so the id is made here
  if (inNewTab) { window.open(`/?sodas=${randomGardenId()}`, "_blank"); return; }
  await saveGardenNow();
  await loadGarden(randomGardenId(), true);
}
/** The name box doubles as the garden switcher: typing renames this garden, the list switches to another one.
 *  A new garden is the separate ＋ button (newGarden), not part of this box. */
async function showGardenList(all = false) {
  const box = $("#gardens");
  let list;
  try { list = (await api("/api/sodas/gardens")).gardens; } catch (e) { return; }
  const q = all ? "" : $("#gardenName").value.trim().toLocaleLowerCase("lt");
  const others = list.filter(g => g.id !== S.garden.id);
  const shown = others.filter(g => !q || String(g.name).toLocaleLowerCase("lt").includes(q) || String(g.name) === q || q === String(S.garden.name).toLocaleLowerCase("lt"));
  box.innerHTML = `<h4><span>Kiti sodai</span><span class="muted">spauskite – atidaryti čia, Ctrl – naujoje kortelėje</span></h4>` +
    (shown.map(g => `<div class="item" data-g="${esc(g.id)}"><span translate="no">${esc(g.name)}</span><span class="ds">${g.nodes} mazgų · ${esc((g.updated_at || "").slice(0, 16).replace("T", " "))}</span></div>`).join("")
      || '<div class="none">kitų sodų nėra</div>') +
    `<div class="more" data-file="down" title="Šį sodą su jo mazgais, ryšiais ir naudotų duomenų sąrašu – į bylą, kurią galite kam nors nusiųsti">⬇ Atsisiųsti šį sodą (JSON)</div>` +
    `<div class="more" data-file="up" title="Kieno nors atsiųstas sodas taps nauju jūsų sodu">⬆ Įkelti sodą iš bylos…</div>` +
    `<div class="more" data-manage>Tvarkyti sodus…</div>`;
  box.hidden = false;
  box.querySelectorAll("[data-file]").forEach(el => el.onmousedown = ev => {
    ev.preventDefault(); box.hidden = true; $("#gardenName").blur();
    if (el.dataset.file === "down") downloadGarden(S.garden.id); else pickGardenFile();
  });
  box.querySelectorAll("[data-g]").forEach(el => el.onmousedown = ev => {
    ev.preventDefault();
    box.hidden = true;
    if (ev.ctrlKey || ev.metaKey || ev.button === 1) window.open(`/?sodas=${el.dataset.g}`, "_blank");
    else { $("#gardenName").blur(); switchGarden(el.dataset.g); }
  });
  box.querySelector("[data-manage]").onmousedown = ev => { ev.preventDefault(); box.hidden = true; $("#gardenName").blur(); openSettings("gardens"); };
}

// ---------------------------------------------------------------- sharing a garden as a file
/** The garden as a file (``sodo-byla/1``): somebody else uploads it and gets a garden of their own. */
async function downloadGarden(id) {
  if (id === S.garden.id) await saveGardenNow();
  let f;
  try { f = await api(`/api/sodas/gardens/${id}/byla`); } catch (e) { return; }
  const name = (f.garden.name || "sodas").replace(/[^\p{L}\p{N}]+/gu, "_").replace(/^_+|_+$/g, "") || "sodas";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(f, null, 1)], {type: "application/json"}));
  a.download = `${name}.sodas.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  toast("Sodas atsisiųstas – bylą galite nusiųsti kitam sodininkui");
}
function pickGardenFile() {
  const inp = document.createElement("input");
  inp.type = "file"; inp.accept = ".json,application/json";
  inp.onchange = () => { if (inp.files[0]) uploadGarden(inp.files[0]); };
  inp.click();
}
async function uploadGarden(file) {
  let data;
  try { data = JSON.parse(await file.text()); } catch (e) { toast(`Netinkama byla: ${e.message}`, "error"); return; }
  let r;
  try { r = await api("/api/sodas/sodo-byla", {file: data}); } catch (e) { return; }
  await saveGardenNow();
  await loadGarden(r.id, true);
  if (!$("#settings").hidden) closeSettings();
  toast(tx("Įkeltas sodas „{0}“ ({1} mazgų)", r.name, r.nodes));
}

/** "Į atskirą sodą": the selected nodes (with the relationships among them) move to a new garden, opened in a new tab. */
async function splitToGarden() {
  const sel = selectedReal(S.cy.$("node:selected").not(".more"));
  if (sel.empty()) return toast("Nepažymėtas joks mazgas");
  const ids = new Set(sel.map(n => n.id()));
  const edges = sel.connectedEdges().not(".more").filter(e => ids.has(e.source().id()) && ids.has(e.target().id()));
  const tab = window.open("about:blank", "_blank");  // still inside the click, so the browser allows it
  const cls = el => el.classes().filter(c => !["path", "dim", "temp", "merged", "type-hidden", "lexmap", "lexmap-off", "map-hidden"].includes(c));
  // a node of the map of a merged node is a real node in the new garden (lm|label|key → label|key), so expanding it
  // there does not bring the same node a second time; on the map positions are map units: the screen layout is kept
  const realId = n => n.hasClass("lexmap") ? `${n.data("label")}|${n.data("key")}` : n.id();
  const nodeOut = n => {
    const data = {...n.data(), id: realId(n)};
    delete data.premap; delete data.mapRel; delete data.mapOwner;
    return {data, position: S.map.on ? {...n.renderedPosition()} : n.position(), classes: cls(n)};
  };
  const garden = {name: `${S.garden.name || "Sodas"} – dalis`, excluded: S.garden.excluded,
    typeVis: {}, labelHidden: {}, basket: [],  // a new garden shows every type and starts with an empty basket
    nodes: sel.map(nodeOut),
    edges: edges.map(e => ({data: e.data(), classes: cls(e)}))};
  let newId;
  try {
    newId = (await api("/api/sodas/gardens")).new_id;
    await api(`/api/sodas/gardens/${newId}`, garden);
  } catch (e) { if (tab) tab.close(); return; }
  const moreOf = S.cy.nodes(".more").filter(m => ids.has(m.data("parent_node")));
  sel.union(moreOf).remove();
  S.garden.basket = S.garden.basket.filter(id => !ids.has(id));
  renderBasket(); syncSelectionButtons(); await saveGardenNow();
  if (tab) tab.location.href = `/?sodas=${newId}`;
  toast(`${ids.size} mazgų perkelta į naują sodą „${garden.name}“${tab ? "" : " – jį rasite sodų sąraše"}`);
}

// ---------------------------------------------------------------- map
// The map is off until the researcher asks for it on a node with latitude/longitude ("Rodyti žemėlapyje").
// Map point (Web Mercator pixels at zoom MAP_Z0) = garden position + S.map.offset; the offset is chosen so that
// the chosen node's place on the map is where the node already stands.
// On the map nodes are drawn at the size set in the settings, whatever the map zoom (styles are multiplied by
// k = 1 / zoom; it does not depend on the zoom at which the map was turned on). Geo nodes stand (locked) at their places; every other node belongs to its
// nearest geo node through the garden's relationships (``mapOwner``) and keeps its on-screen offset from it
// (``mapRel``, pixels on screen = garden units before the map), so a surrounding looks the same at every map zoom. Turning the map off puts
// geo nodes back where they stood before (``premap``) and their surroundings around them.
// Nodes without coordinates of their own may take them over a geo path (a Form from its Languoid): ``data.geo``.
// The Leaflet map under the graph follows the graph's viewport and never takes input itself.
const MAP_Z0 = 4;
/** Garden length of one "normal" length on screen: 1 without the map, 1 / zoom on it. */
const unit = () => S.map.on ? 1 / S.cy.zoom() : 1;
function latLng(lat, lon) {
  if (lat == null || lon == null || lat === "" || lon === "") return null;
  lat = Number(lat); lon = Number(lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return L.latLng(Math.max(-85, Math.min(85, lat)), lon);
}
const ownGeo = d => !!(window.L && d.props && latLng(d.props.latitude, d.props.longitude));
function geoOf(d) {
  if (!window.L) return null;
  const p = d.props || {};
  return latLng(p.latitude, p.longitude) || (d.geo ? latLng(d.geo.latitude, d.geo.longitude) : null);
}
const mapAllowed = () => !!(window.L && S.settings.map && S.settings.map.enabled);
const geoNodes = () => !mapAllowed() ? S.cy.collection() : S.cy.nodes().not(".more, .multi, .merged, .lexmap-off, .ds-off").filter(n => !!geoOf(n.data()));

/** Coordinates over the geo paths (settings) for nodes that have none of their own; asked once per node. */
async function fetchGeo(ids) {
  const labels = new Set((S.settings.map.geoPaths || []).map(g => g.label));
  const nodes = ids.map(id => S.cy.getElementById(id))
    .filter(n => n.nonempty() && n.data("key") && n.data("geo") === undefined && labels.has(n.data("label")) && !ownGeo(n.data()));
  if (!nodes.length) return;
  let r;
  try { r = await api("/api/sodas/geo", {nodes: nodes.map(n => ({label: n.data("label"), key: n.data("key")}))}); } catch (e) { return; }
  for (const n of nodes) if (n.inside()) n.data("geo", r[n.id()] || null);
  updateMapSoon(); scheduleOverlay(); saveGardenSoon();
}
/** Where each geo node stands on the map (garden coordinates); nodes sharing one place are spread on a small ring. */
function mapTargets(geo) {
  const places = new Map(), out = new Map(), o = S.map.offset, u = unit();
  geo.forEach(n => {
    const p = L.CRS.EPSG3857.latLngToPoint(geoOf(n.data()), MAP_Z0), k = `${Math.round(p.x * 10)},${Math.round(p.y * 10)}`;
    if (!places.has(k)) places.set(k, []);
    places.get(k).push([n, p]);
  });
  for (const list of places.values()) {
    list.sort((a, b) => a[0].id() < b[0].id() ? -1 : 1);
    const r = list.length > 1 ? (16 + 6 * list.length) * u : 0;
    list.forEach(([n, p], i) => out.set(n.id(), {x: p.x - o.x + r * Math.cos(2 * Math.PI * i / list.length),
                                                 y: p.y - o.y + r * Math.sin(2 * Math.PI * i / list.length)}));
  }
  return out;
}
function ensureMap() {
  if (S.map.l) return S.map.l;
  const m = L.map($("#map"), {zoomControl: false, dragging: false, touchZoom: false, scrollWheelZoom: false, doubleClickZoom: false,
    boxZoom: false, keyboard: false, zoomSnap: 0, zoomAnimation: false, fadeAnimation: false, markerZoomAnimation: false, inertia: false});
  // OSM refuses tiles without a Referer, and the page policy (same-origin) sends none: send the origin for tiles only
  S.map.tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 19, referrerPolicy: "strict-origin",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'}).addTo(m);
  m.attributionControl.setPrefix(false);
  m.setView([0, 0], 1);
  return (S.map.l = m);
}
/** Each node belongs to the geo node nearest to it through the garden's relationships; geo nodes that stay win ties. */
function geoOwners(geo, stays = () => true) {
  const owner = new Map(), queue = [];
  for (const g of [...geo.filter(stays), ...geo.filter(n => !stays(n))]) { owner.set(g.id(), g); queue.push(g); }
  for (let i = 0; i < queue.length; i++) {
    const n = queue[i], o = owner.get(n.id());
    n.neighborhood("node").forEach(m => { if (!owner.has(m.id())) { owner.set(m.id(), o); queue.push(m); } });
  }
  return owner;
}
/** Nodes that follow a geo node on the map (merged nodes follow their merged node instead). */
const mapFree = () => S.cy.nodes().not(".merged");
/** Bind new nodes to the map: geo nodes remember where they stood; the others get their owner and offset. */
/** ``fresh``: the map was just turned on, positions are still the garden's own (offsets are taken as they are). */
function attachToMap({fresh = false} = {}) {
  const cy = S.cy, geo = geoNodes(), u = fresh ? 1 : unit();
  hideOffMap(geo);
  geo.forEach(g => {
    if (!g.data("premap")) g.data("premap", {...g.position()});
    g.removeData("mapRel mapOwner");
    if (g.hasClass("twin")) members(g).data("premap", g.data("premap"));
  });
  const bound = n => n.data("mapRel") && geo.contains(cy.getElementById(n.data("mapOwner")));
  const loose = mapFree().filter(n => !geo.contains(n) && !bound(n));
  if (loose.empty()) return;
  const owner = geoOwners(geo, g => g.id() === S.map.anchor);
  loose.forEach(n => {
    const o = owner.get(n.id());
    if (!o) { n.removeData("mapRel mapOwner"); return; }
    n.data({mapOwner: o.id(), mapRel: {x: (n.position("x") - o.position("x")) / u, y: (n.position("y") - o.position("y")) / u}});
  });
}
/** On the map only nodes with a place on it are shown; the others (class "map-hidden") still follow their geo node,
 *  so turning the map off brings them back where they belong. */
function hideOffMap(geo = geoNodes()) {
  const cy = S.cy;
  cy.batch(() => {
    if (!S.map.on || S.lexMap) { cy.nodes(".map-hidden").removeClass("map-hidden"); return; }
    const off = cy.nodes().not(".lexmap").difference(geo);
    off.not(".map-hidden").addClass("map-hidden").unselect();
    geo.filter(".map-hidden").removeClass("map-hidden");
  });
}
/** Geo nodes to their places, every bound node at its on-screen offset from its geo node. */
function arrangeMap() {
  if (!S.map.on) return;
  const cy = S.cy, geo = geoNodes(), targets = mapTargets(geo), u = unit();
  cy.batch(() => {
    geo.forEach(g => { g.unlock(); g.position(targets.get(g.id())); g.lock(); });
    mapFree().forEach(n => {
      const rel = n.data("mapRel"), o = rel && cy.getElementById(n.data("mapOwner"));
      if (!o || o.empty() || geo.contains(n)) return;
      n.position({x: o.position("x") + rel.x * u, y: o.position("y") + rel.y * u});
    });
  });
  S.map.arrangedAt = cy.zoom();
}
/** A node dragged on the map keeps its new offset from its geo node. */
function rebind(nodes) {
  if (!S.map.on) return;
  const u = unit();
  nodes.forEach(n => {
    const o = n.data("mapRel") && S.cy.getElementById(n.data("mapOwner"));
    if (o && o.nonempty()) n.data("mapRel", {x: (n.position("x") - o.position("x")) / u, y: (n.position("y") - o.position("y")) / u});
  });
}
/** Turn the map on so that ``node`` (with coordinates) keeps its place, or just bring it into view if the map is on. */
function showOnMap(node) {
  if (node && node.hasClass("bundle")) return groupMap(node);
  if (node && node.hasClass("multi")) node = S.cy.getElementById(node.data("members")[0]);
  if (!node || node.empty() || !geoOf(node.data())) return toast("Šis mazgas neturi platumos ir ilgumos", "warning");
  if (!S.map.on) {
    S.map.anchor = node.id();
    S.map.view = {zoom: S.cy.zoom(), pan: {...S.cy.pan()}};  // turning the map off brings the garden back to this view
    mapOn({x: 0, y: 0});  // unmerges first: a form of a multi node now stands where the multi node stood
    const p = L.CRS.EPSG3857.latLngToPoint(geoOf(node.data()), MAP_Z0), pos = {...node.position()};
    S.map.offset = {x: p.x - pos.x, y: p.y - pos.y};
    // a node sharing its place with others stands a little aside on the map: the garden follows that spot, too
    const t = mapTargets(geoNodes()).get(node.id());
    S.map.offset = {x: S.map.offset.x + t.x - pos.x, y: S.map.offset.y + t.y - pos.y};
    attachToMap({fresh: true}); arrangeMap(); syncMapView();
    const moved = geoNodes().length - 1;
    if (moved && !S.lexMap) toast(`${moved} kitų mazgų su koordinatėmis nukelta į savo vietas žemėlapyje; mazgai be vietos žemėlapyje paslėpti`);
  }
  touch(node);
  if (!S.lexMap) S.cy.animate({center: {eles: node}, duration: 250});  // the lexeme map fits all its lexemes itself
  saveGardenSoon();
}
function mapOn(offset) {
  S.map.on = true; S.map.offset = offset; S.map.k = 1;
  updateMerges();  // on the map every form stands where its language is
  $("#map").hidden = false; document.body.classList.add("map-on");
  ensureMap().invalidateSize({pan: false});
  applyMapOpacity();
  S.cy.minZoom(Math.pow(2, 1 - MAP_Z0)); S.cy.maxZoom(Math.pow(2, 18 - MAP_Z0));
  S.map.arrangedAt = S.cy.zoom();  // the caller binds the nodes and arranges them
  syncMapView(true); syncMapControls();
}
/** ``restore``: geo nodes go back where they stood before the map, their surroundings around them. */
function mapOff({restore = true} = {}) {
  if (!S.map.on) return;
  if (S.lexMap) return leaveLexemeMap();
  const cy = S.cy;
  if (restore) {
    const to = new Map();
    cy.nodes().forEach(n => {
      const was = n.data("premap"), rel = n.data("mapRel"), o = rel && cy.getElementById(n.data("mapOwner"));
      if (was) to.set(n.id(), was);
      else if (o && o.nonempty() && o.data("premap")) to.set(n.id(), {x: o.data("premap").x + rel.x, y: o.data("premap").y + rel.y});
    });
    cy.nodes().unlock();
    cy.batch(() => to.forEach((p, id) => cy.getElementById(id).position(p)));
  }
  S.map.on = false; S.map.k = 1;
  $("#map").hidden = true; document.body.classList.remove("map-on");
  cy.nodes().unlock().removeData("premap mapRel mapOwner");
  hideOffMap();
  cy.minZoom(.05); cy.maxZoom(4);
  if (restore && S.map.view) cy.viewport(S.map.view);
  S.map.view = null;
  restyle(); updateMerges();
  syncMapControls(); saveGardenSoon();
}
/** What 🗺 shows for a node beyond its own place: a sense – its lemmas (a sense without a lexeme: its forms), with Ctrl
 *  every form of its concept; a concept – the lemmas of all its senses; a cognate set – its forms. A merged node or a bundle of them the same. Null: nothing. */
function mapWayOf(n, ctrl = false) {
  const label = n.data("label");
  if (label === "Sense") return ctrl ? "concept_forms" : "lemmas";
  if (label === "CognateSet") return "cognate_forms";
  if (label === "Concept") return "concept_lemmas";
  return null;
}
/** The node 🗺 acts on: the last one selected. */
function mapSubject() {
  const sel = S.cy.$("node:selected").not(".more");
  const order = S.selOrder.map(id => S.cy.getElementById(id)).filter(n => n.nonempty() && sel.contains(n));
  return order.length ? order[order.length - 1] : sel[0] || null;
}
/** Toolbar 🗺: off when the map is shown; otherwise, by the selected node:
 *  a sense – its lemmas on the map (Ctrl: all forms of its concept); a cognate set – its forms; a bundle – all its
 *  nodes; Ctrl with a merged node (×N) – all its nodes; else the map at the selected (or first) node with coordinates. */
function toggleMap(ev) {
  if (S.map.on) return mapOff();
  const ctrl = !!(ev && (ev.ctrlKey || ev.metaKey)), t = mapSubject();
  if (t) {
    const way = mapWayOf(t, ctrl);
    if (way) return groupMap(t, way);
    if (t.hasClass("bundle") || (ctrl && t.hasClass("multi"))) return groupMap(t);
  }
  if (ctrl) return toast("Ctrl + 🗺: pažymėkite Sense mazgą (visos jo sąvokos lytys) arba apjungtą mazgą (×N) – visi jo mazgai bus parodyti žemėlapyje", "warning", 6000);
  const geo = geoNodes(), sel = geo.filter(":selected").union(S.cy.nodes(".multi:selected"));
  if (geo.empty()) return toast("Sode nėra mazgų su platuma ir ilguma");
  showOnMap(sel.nonempty() ? sel[0] : geo[0]);
}
/** Menu items for the map of a node's lemmas / forms (mapWayOf). */
function mapWayItems(t) {
  if (!mapAllowed()) return [];
  const label = t.data("label");
  if (label === "Sense") return [{label: "Lemos žemėlapyje", hint: "🗺", icon: "map", run: () => groupMap(t, "lemmas")},
    {label: "Visos sąvokos lytys žemėlapyje", hint: "Ctrl+🗺", icon: "map", run: () => groupMap(t, "concept_forms")}];
  if (label === "CognateSet") return [{label: "Lytys žemėlapyje", hint: "🗺", icon: "map", run: () => groupMap(t, "cognate_forms")}];
  if (label === "Concept") return [{label: "Sąvokos lemos žemėlapyje", hint: "🗺", icon: "map", run: () => groupMap(t, "concept_lemmas")}];
  return [];
}

// ---------------------------------------------------------------- the map of a merged node (Ctrl + 🗺)
// Every node a bundle or a multi node stands for – of Sense nodes their lexemes (over HAS_SENSE) – each where its
// language is, asked from the server whole (not only what the garden loaded). Thousands of points are kept in the
// browser, but only those in the visible part of the map are drawn, at most LEXMAP_MAX of them, spread evenly over
// it: zooming in on a region shows that region's nodes. The garden stays as it is under the map (hidden), so going
// back is instant; nothing of this view is saved.
const LEXMAP_MAX = 400, LEXMAP_CELL = 40;   // most nodes drawn at once; one per LEXMAP_CELL px square first
async function groupMap(node, way = null) {
  if (!mapAllowed()) return toast("Žemėlapis išjungtas nustatymuose", "warning");
  if (S.map.on) mapOff();
  const desc = bundleOf(node), done = Kalba.working("Ruošiamas žemėlapis…");
  let r;
  try {
    if (way) {
      // the server finds them from the whole group (a bundle, a multi node with a common source) or from these nodes
      const label = node.data("label");
      const refs = (node.hasClass("virtual") ? members(node) : node).filter(n => n.data("key") && n.data("label") === label)
        .map(n => ({label, key: n.data("key")}));
      r = await api("/api/sodas/node-map", desc ? {bundle: desc, way} : {nodes: refs, way});
    } else r = desc ? await api("/api/sodas/bundle-map", {bundle: desc}) : await loadedPoints(node);
  }
  catch (e) { return; }
  finally { done(); }
  const none = {lemmas: "Šis Sense neturi nei lemų, nei lyčių", concept_forms: "Šios sąvokos lyčių nerasta", concept_lemmas: "Šios sąvokos lemų nerasta", cognate_forms: "Šis kognatų rinkinys neturi lyčių"};
  if (!r.points.length) return toast(r.total ? "Nė vienas šių mazgų neturi platumos ir ilgumos" : (none[way] || "Šių mazgų nerasta"), "warning");
  enterGroupMap(r, node);
  const lost = r.without ? `; ${r.without} be koordinačių nerodoma` : "", cut = r.truncated ? `; parodyta pirmų ${r.points.length + r.without} iš ${r.total}` : "";
  const kinds = (r.labels || [r.label]).map(l => ({Lexeme: "lemų", Form: "lyčių"})[l] || "mazgų");
  const what = way === "concept_forms" ? `visos sąvokos lytys – ${r.points.length}` : `${r.points.length} ${[...new Set(kinds)].join(" ir ")}`;
  toast(`${node.data("caption")}: žemėlapyje ${what}${lost}${cut}. Artinkite – bus rodomi tos srities mazgai. Sodas laikinai paslėptas: 🗺 – grįžti.`, "info", 8000);
}
/** A multi node the server cannot find whole (no common source): the points of its loaded members. */
async function loadedPoints(node) {
  const ms = members(node).filter(n => n.data("key"));
  const label = node.data("label"), nodes = ms.map(n => n.data());
  const geo = nodes.length ? await api("/api/sodas/geo", {nodes: nodes.map(n => ({label: n.label, key: n.key}))}) : {};
  const points = [];
  for (const n of nodes) {
    const g = geo[n.id], ll = latLng((n.props || {}).latitude, (n.props || {}).longitude) || (g && latLng(g.latitude, g.longitude));
    if (ll) points.push([n.key, n.display_name, ll.lat, ll.lng, g && g.via ? g.via.name : null, n.dataset, n.label]);
  }
  return {label, total: nodes.length, points, without: nodes.length - points.length, truncated: false};
}
function enterGroupMap(r, node) {
  const cy = S.cy;
  closeMenus(); cy.$(":selected").unselect(); $("#info").hidden = true;
  const snapshot = gardenSnapshot();   // what is saved meanwhile: the garden as it is
  S.lexMap = {snapshot, view: {zoom: cy.zoom(), pan: {...cy.pan()}}, points: r.points, label: r.label, title: node.data("caption"),
    rank: new Map(), computed: new Map()};
  cy.batch(() => cy.elements().addClass("lexmap-off"));
  mapOn({x: 0, y: 0});
  // the view takes in every point
  const ps = r.points.map(p => L.CRS.EPSG3857.latLngToPoint(L.latLng(p[2], p[3]), MAP_Z0));
  const xs = ps.map(p => p.x), ys = ps.map(p => p.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const w = Math.max(x1 - x0, 40), h = Math.max(y1 - y0, 40);
  const zoom = Math.max(cy.minZoom(), Math.min(cy.maxZoom(), Math.min(cy.width() / w, cy.height() / h) * 0.85));
  cy.viewport({zoom, pan: {x: cy.width() / 2 - (x0 + x1) / 2 * zoom, y: cy.height() / 2 - (y0 + y1) / 2 * zoom}});
  syncMapView(true);
  drawGroupMap();
  syncMapControls();
}
/** A stable order of the points (by key), so that moving the map a little does not change which ones are drawn. */
function pointRank(key) {
  const m = S.lexMap.rank;
  if (!m.has(key)) {
    let h = 2166136261;
    for (let i = 0; i < key.length; i++) h = Math.imul(h ^ key.charCodeAt(i), 16777619);
    m.set(key, h >>> 0);
  }
  return m.get(key);
}
/** The points in the visible part of the map: all of them when there are few, else at most LEXMAP_MAX spread evenly
 *  (one per square of the screen first, then a second one, …). Selected nodes stay. */
function drawGroupMap() {
  const lm = S.lexMap;
  if (!lm || !S.map.on || !S.map.l) return;
  const cy = S.cy, m = S.map.l, bounds = m.getBounds().pad(0.05);
  const inside = lm.points.filter(p => bounds.contains([p[2], p[3]]));
  let want = inside;
  if (inside.length > LEXMAP_MAX) {
    const cells = new Map();
    for (const p of inside) {
      const c = m.latLngToContainerPoint([p[2], p[3]]), k = `${Math.floor(c.x / LEXMAP_CELL)},${Math.floor(c.y / LEXMAP_CELL)}`;
      if (!cells.has(k)) cells.set(k, []);
      cells.get(k).push(p);
    }
    const lists = [...cells.values()].map(l => l.sort((a, b) => pointRank(a[0]) - pointRank(b[0])))
      .sort((a, b) => pointRank(a[0][0]) - pointRank(b[0][0]));
    want = [];
    for (let i = 0; want.length < LEXMAP_MAX; i++) {
      let any = false;
      for (const l of lists) {
        if (i >= l.length) continue;
        any = true; want.push(l[i]);
        if (want.length >= LEXMAP_MAX) break;
      }
      if (!any) break;
    }
  }
  const idOf = p => `lm|${p[6] || lm.label}|${p[0]}`, wanted = new Set(want.map(idOf));
  const fresh = [];
  cy.batch(() => {
    cy.nodes(".lexmap").filter(n => !wanted.has(n.id()) && !n.selected()).remove();
    const add = want.filter(p => cy.getElementById(idOf(p)).empty()).map(p => ({group: "nodes", classes: "lexmap", position: {x: 0, y: 0},
      data: nodeData({id: idOf(p), label: p[6] || lm.label, key: p[0], display_name: p[1], dataset: p[5], degree: null, props: {},
        geo: {latitude: p[2], longitude: p[3], via: p[4] ? {name: p[4]} : null}, ...(lm.computed.has(idOf(p)) ? {computed: lm.computed.get(idOf(p))} : {})})}));
    cy.add(add);
    fresh.push(...add.filter(a => !a.data.computed).map(a => a.data.id));
  });
  arrangeMap();
  if (fresh.length) fetchComputed(fresh); else refreshOverlay();
  const shown = cy.nodes(".lexmap").length, info = $("#lexInfo");
  info.textContent = inside.length > shown
    ? `${lm.title}: rodoma ${shown} iš ${inside.length} šioje srityje (iš viso ${lm.points.length}) – artinkite, kad pamatytumėte kitus`
    : `${lm.title}: šioje srityje ${inside.length} iš ${lm.points.length}`;
  info.hidden = false;
}
const drawGroupMapSoon = debounce(drawGroupMap, 150);
/** Back to the garden: it was only hidden under the map, so it is shown again where it was, at once. */
function leaveLexemeMap() {
  const lm = S.lexMap, cy = S.cy;
  cy.batch(() => cy.nodes(".lexmap").remove());
  S.map.on = false; S.map.k = 1;
  $("#map").hidden = true; document.body.classList.remove("map-on");
  $("#lexInfo").hidden = true;
  cy.nodes().unlock().removeData("premap mapRel mapOwner");
  cy.minZoom(.05); cy.maxZoom(4);
  S.lexMap = null;
  cy.batch(() => cy.elements().removeClass("lexmap-off"));
  cy.viewport(lm.view);
  restyle(); updateMerges(); updateSizes(); refreshOverlay(); syncMapControls(); renderStatus();
}
const updateMapSoon = debounce(() => updateMap(), 120);
/** After the garden changed: new nodes are bound to the map; the map goes away when it is no longer allowed. */
function updateMap() {
  if (!S.cy || !S.settings) return;
  if (S.map.on && !mapAllowed()) mapOff();
  else if (S.map.on) { attachToMap(); arrangeMap(); }
  syncMapControls();
}
function applyMapOpacity() {
  const v = Number(S.settings.map.opacity ?? 0.7);
  if (S.map.tiles) S.map.tiles.setOpacity(v);
  $("#mapOpacity").value = v;
}
function syncMapControls() {
  $("#mapCtl").hidden = !S.map.on;
  const b = $('[data-act="map"]');
  b.hidden = !S.map.on && geoNodes().empty() && S.cy.nodes(".multi, .bundle").empty() && S.cy.nodes().filter(n => !!mapWayOf(n)).empty();
  b.classList.toggle("on", S.map.on);
  b.title = S.map.on ? (S.lexMap ? "Išjungti žemėlapį ir grąžinti sodą" : "Išjungti žemėlapį")
    : "Rodyti žemėlapį (pažymėtas arba pirmas mazgas su koordinatėmis). Pažymėtas Sense – jo lemos, Concept – visos sąvokos lemos, kognatų rinkinys – jo lytys. Ctrl – visos pažymėto Sense sąvokos lytys, visi apjungto mazgo (×N) mazgai";
}
/** Leaflet follows the graph viewport; on a zoom change the sizes and the surroundings follow, too. */
function syncMapView(forceStyle = false) {
  if (!S.map.on || !S.map.l) return;
  const cy = S.cy, z = cy.zoom(), pan = cy.pan(), o = S.map.offset;
  const center = S.map.l.unproject(L.point((cy.width() / 2 - pan.x) / z + o.x, (cy.height() / 2 - pan.y) / z + o.y), MAP_Z0);
  S.map.l.setView(center, MAP_Z0 + Math.log2(z), {animate: false});
  if (S.map.arrangedAt !== z) arrangeMap();
  const k = 1 / z;
  if (forceStyle || Math.abs(k - S.map.k) / S.map.k > 0.02) { S.map.k = k; restyleSoon(); }
  if (S.lexMap) drawGroupMapSoon();
}
let restyleQueued = false;
function restyleSoon() { if (!restyleQueued) { restyleQueued = true; requestAnimationFrame(() => { restyleQueued = false; restyle(); }); } }

// ---------------------------------------------------------------- merged nodes (display only, class "virtual")
// * multi: without the map, forms of one cognate set (senses of one concept) having the same name and no other
//   relationship in the garden are shown as one node "name ×N"; on the map they are separate again (each where its
//   language is).
// * twin: two nodes of one kind from different datasets joined 1:1 by CORRESPONDS_TO (IE-CoR ↔ Concepticon concept)
//   are shown as one node; every relationship of either of them is drawn from it (class "proxy"), their own
//   CORRESPONDS_TO is not. It expands both.
// * same ("Drąsiai jungti mazgus", on by default): forms and lexemes of one name in one language (the same Glottolog
//   code, or the same language name), whatever their datasets, are one node (a multi node without a center); every
//   relationship of them is drawn from it.
// * manual ("Apjungti pažymėtus"): any nodes the researcher joined by hand, under a name they chose. Kept in this garden
//   only (S.garden.manual: [{id, members, name}]), never written to the database; it wins over the other kinds.
// The nodes standing behind get "merged" and are not drawn; virtual elements are rebuilt from the garden and never saved.
const MERGE_RULES = [{center: "CognateSet", member: "Form"}, {center: "Concept", member: "Sense"}];
const TWIN_RULES = [{label: "Concept", type: "CORRESPONDS_TO"}, {label: "Languoid", type: "CORRESPONDS_TO"}];
function wantedTwins() {
  const out = new Map(), off = new Set(S.garden.untwinned);
  if (S.lexMap) return out;
  const manual = manualMembers();
  const ok = n => !n.hasClass("hidden") && !n.hasClass("temp") && !n.hasClass("ds-off") && !manual.has(n.id());
  for (const rule of TWIN_RULES) {
    const pairs = S.cy.edges(`[type = "${rule.type}"]`).not(".virtual").filter(e => e.source() !== e.target() &&
      e.source().data("label") === rule.label && e.target().data("label") === rule.label &&
      e.source().data("dataset") !== e.target().data("dataset") && ok(e.source()) && ok(e.target()));
    // a node with several counterparts in the garden (Old Czech and Czech → Glottolog Czech) is joined only with
    // the one of the same name, if there is exactly one; the others stay separate, related to the twin
    const partners = new Map();
    pairs.forEach(e => [[e.source(), e], [e.target(), e]].forEach(([n, x]) => partners.set(n.id(), [...(partners.get(n.id()) || []), x])));
    const name = n => String(n.data("display_name") || "").toLocaleLowerCase();
    const chosen = n => {
      const es = partners.get(n.id());
      if (es.length === 1) return es[0];
      const same = es.filter(x => name(x.source()) === name(x.target()));
      return same.length === 1 ? same[0] : null;
    };
    pairs.forEach(e => {
      const a = e.source(), b = e.target(), id = `twin|${a.id()}|${b.id()}`;
      if (chosen(a) === e && chosen(b) === e && !off.has(id)) out.set(id, {members: [a, b], edge: e});
    });
  }
  return out;
}
const BOLD_LABELS = new Set(["Form", "Lexeme"]);
/** The language of a node for bold merging: its Glottolog code, else its language's name; null when not one known. */
function boldLanguage(n) {
  const langs = (n.data("computed") || {}).language;
  if (!langs || !langs.length) return null;
  const keys = new Set(langs.map(v => v.glottocode || "n:" + String(v.name || "").toLocaleLowerCase()));
  return keys.size === 1 ? [...keys][0] : null;
}
/** Bold groups: id → {center: null, members, edge: null}; two or more nodes each. */
function wantedBold(free) {
  const groups = new Map();
  if (S.settings.graph.boldMerge === false) return groups;
  const off = new Set(S.garden.unmerged);
  S.cy.nodes().filter(n => BOLD_LABELS.has(n.data("label")) && free(n)).forEach(n => {
    const lang = boldLanguage(n), name = String(n.data("display_name") || "").normalize("NFC").trim().toLocaleLowerCase();
    if (!lang || !name) return;
    const id = `multi|same|${lang}|${name}`;
    if (off.has(id)) return;
    if (!groups.has(id)) groups.set(id, {center: null, members: [], edge: null, bold: true});
    groups.get(id).members.push(n);
  });
  for (const [id, g] of groups) {
    if (g.members.length < 2) groups.delete(id);
    else g.members.sort((a, b) => a.id() < b.id() ? -1 : 1);   // forms first (Form| < Lexeme|): the node looks like a form
  }
  return groups;
}
/** Groups joined by hand (without the map only): id → {center: null, members, edge: null, manual: true, name}; groups
 *  with fewer than two nodes in the garden wait (their nodes may come back). */
function wantedManual() {
  const groups = new Map();
  if (S.map.on || S.lexMap) return groups;
  for (const m of S.garden.manual || []) {
    const ms = m.members.map(id => S.cy.getElementById(id)).filter(n => n.nonempty() && !n.hasClass("temp") && !n.hasClass("ds-off") && !n.hasClass("hidden"));
    if (ms.length >= 2) groups.set(m.id, {center: null, members: ms.sort((a, b) => a.id() < b.id() ? -1 : 1), edge: null, manual: true, name: m.name});
  }
  return groups;
}
/** Ids of the nodes in groups joined by hand (shown now). */
const manualMembers = () => new Set([...wantedManual().values()].flatMap(g => g.members.map(m => m.id())));
/** The computed values of several nodes together (a merged node of several languages shows each language's flag). */
function mergedComputed(ms) {
  const out = {};
  for (const m of ms) for (const [name, vals] of Object.entries(m.data("computed") || {})) {
    const list = (out[name] = out[name] || []);
    for (const v of vals) if (!list.some(x => x.key === v.key && x.label === v.label)) list.push(v);
  }
  return Object.keys(out).length ? out : null;
}
/** Multi nodes (without the map only). ``twinRep``: twin member id → twin id.
 *  1. rules: nodes of one kind with the same name around one center (forms of a cognate set, senses of a concept),
 *     whatever else they are related to: those relationships are drawn from the multi node;
 *  2. then nodes of one kind with the same name whose every relationship leads to one node as drawn
 *     (e.g. the lexemes of the senses behind "rain ×125"). */
function wantedMerges(twinRep) {
  const groups = new Map();
  if (S.map.on || S.lexMap) return groups;
  const basket = new Set(S.garden.basket), off = new Set(S.garden.unmerged);
  // groups joined by hand first: their nodes are not taken into any other group
  for (const [id, g] of wantedManual()) groups.set(id, g);
  const manual = manualMembers();
  const free0 = n => !n.hasClass("virtual") && !n.hasClass("more") && !n.hasClass("bundle") && !n.hasClass("temp") && !n.hasClass("hidden") && !n.hasClass("ds-off") &&
    !basket.has(n.id()) && !twinRep.has(n.id()) && !manual.has(n.id());
  // then bold groups: their nodes are not taken into the other groups
  for (const [id, g] of wantedBold(free0)) groups.set(id, g);
  const inBold = new Set([...groups.values()].flatMap(g => g.members.map(m => m.id())));
  const free = n => free0(n) && !inBold.has(n.id());
  const add = (id, center, f, edge) => {
    if (off.has(id)) return;
    if (!groups.has(id)) groups.set(id, {center, members: [], edge});
    groups.get(id).members.push(f);
  };
  const prune = () => { for (const [id, g] of groups) if (g.members.length < 2) groups.delete(id); };
  for (const rule of MERGE_RULES) S.cy.nodes(`[label = "${rule.center}"]`).not(".virtual, .hidden").forEach(c => {
    const center = twinRep.get(c.id()) || c.id();
    c.neighborhood(`node[label = "${rule.member}"]`).filter(free)
      .forEach(f => add(`multi|${c.id()}|${f.data("display_name")}`, center, f, f.edgesWith(c)[0]));
  });
  prune();
  const rep = new Map(twinRep);
  for (const [id, g] of groups) g.members.forEach(m => rep.set(m.id(), id));
  const drawn = n => rep.get(n.id()) || n.id();
  const second = [];
  S.cy.nodes().filter(n => free(n) && !rep.has(n.id())).forEach(n => {
    const es = n.connectedEdges().not(".more, .virtual");
    if (es.empty()) return;
    const ends = new Set(es.map(e => drawn(e.source() === n ? e.target() : e.source())));
    if (ends.size !== 1) return;
    const [r] = ends;
    if (r !== n.id()) second.push([`multi|${r}|${n.data("label")}|${n.data("display_name")}`, r, n, es[0]]);
  });
  second.forEach(x => add(...x));
  prune();
  return groups;
}
/** A twin lies where either of its nodes lies (the first one wins). */
function twinGeo(a, b) {
  const ll = geoOf(a.data()) || geoOf(b.data());
  return ll ? {latitude: ll.lat, longitude: ll.lng} : null;
}
const updateMergesSoon = debounce(() => updateMerges(), 80);
/** Rebuild the virtual elements the garden needs now; unchanged ones stay (with their places). */
function updateMerges() {
  if (!S.cy || !S.settings || S.lexMap) return;   // under the map of a merged node the garden waits as it was
  const cy = S.cy, twins = wantedTwins(), twinRep = new Map();
  for (const [id, t] of twins) t.members.forEach(m => twinRep.set(m.id(), id));
  const multis = wantedMerges(twinRep);
  const repOf = new Map(twinRep), multiOf = new Map();  // member id → id of the node drawn for it / its multi group
  for (const [id, g] of multis) g.members.forEach(m => { repOf.set(m.id(), id); multiOf.set(m.id(), g); });
  const rep = n => repOf.get(n.id()) || n.id();
  // wanted virtual nodes and edges: id → {group, data, classes}
  const want = new Map();
  for (const [id, t] of twins) {
    const [a, b] = t.members;
    want.set(id, {group: "nodes", classes: "virtual twin", data: {...a.data(), id, kind: "twin", key: "", members: [a.id(), b.id()],
      datasets: [a.data("dataset"), b.data("dataset")], caption: caption(a.data()), touched: false, computed: null,
      degree: (a.data("degree") || 0) + (b.data("degree") || 0) - 2, geo: twinGeo(a, b)}});
  }
  for (const [id, g] of multis) {
    const f0 = g.members[0];
    // a bold node is one word of one language: its plain name, and its language's flag; a node joined by hand has
    // the name chosen for it and the flags of all its nodes
    const name = g.manual ? g.name : f0.data("display_name");
    want.set(id, {group: "nodes", classes: g.manual ? "virtual multi manual" : g.bold ? "virtual multi same" : "virtual multi",
      data: {...f0.data(), id, kind: "multi", key: "", display_name: name, members: g.members.map(f => f.id()).sort(), center: g.center,
      caption: g.bold || g.manual ? caption({display_name: name}) : `${caption(f0.data())} ×${g.members.length}`, touched: false,
      computed: g.manual ? mergedComputed(g.members) : g.bold ? f0.data("computed") : null, geo: null, premap: null, mapRel: null, mapOwner: null}});
    if (!g.edge) continue;
    const out = g.edge.source() === f0;
    want.set(id + "|e", {group: "edges", classes: "virtual multi",
      data: {id: id + "|e", source: out ? id : g.center, target: out ? g.center : id, type: g.edge.data("type")}});
  }
  // every other relationship of a merged node is drawn from the node standing for it (same ends and type: one line)
  const represented = (m, other) => { const g = multiOf.get(m.id()); return g && rep(other) === g.center; };
  const twinEdges = new Set([...twins.values()].map(t => t.edge.id()));
  cy.edges().not(".virtual").forEach(e => {
    const a = e.source(), b = e.target();
    if (!repOf.has(a.id()) && !repOf.has(b.id())) return;
    if (twinEdges.has(e.id()) || represented(a, b) || represented(b, a)) return;
    const src = rep(a), tgt = rep(b);
    if (src === tgt) return;
    const pid = `px|${src}>${tgt}|${edgeName(e)}`;
    if (want.has(pid)) { want.get(pid).data.reals.push(e.id()); return; }
    want.set(pid, {group: "edges", classes: "virtual proxy" + (e.hasClass("more") ? " more" : "") + (e.hasClass("type-hidden") ? " type-hidden" : ""),
      data: {...e.data(), id: pid, source: src, target: tgt, reals: [e.id()]}});
  });
  const nodeSig = d => `${d.kind}:${d.members.join(" ")}:${JSON.stringify(d.geo || null)}:${d.display_name}:${JSON.stringify(d.computed || null)}`;
  const sig = x => x.group === "nodes" ? nodeSig(x.data) : `${x.data.source}>${x.data.target}:${x.data.type}:${x.classes}`;
  const has = el => el.isNode() ? nodeSig(el.data()) : `${el.data("source")}>${el.data("target")}:${el.data("type")}:${el.classes().join(" ")}`;
  const was = new Map();
  let changed = false;
  cy.batch(() => {
    cy.elements(".virtual").forEach(el => {
      if (el.removed()) return;
      const w = want.get(el.id());
      if (w && sig(w) === has(el)) { want.delete(el.id()); return; }
      if (el.isNode()) { was.set(el.id(), {...el.position()}); release(el, el.hasClass("twin") || S.map.on); }
      el.remove();
      changed = true;
    });
    for (const [id, w] of want) if (w.group === "nodes") {
      const m0 = cy.getElementById(w.data.members[0]);
      cy.add({...w, position: was.get(id) || {...m0.position()}});
      changed = true;
    }
    for (const w of want.values()) if (w.group === "edges") { cy.add(w); changed = true; }
    cy.nodes(".merged").filter(n => !repOf.has(n.id())).removeClass("merged");
    cy.collection([...repOf.keys()].map(id => cy.getElementById(id))).unselect().addClass("merged");
    cy.nodes(".twin").forEach(t => members(t).positions(() => ({...t.position()})));
  });
  if (changed) {
    updateSizes(); renderStatus();
    refreshOverlay();   // a new merged node shows its flags (and its merge badge) at once, not only after the next expand
    // the open info panel was about a node now shown inside a merged one: show the merged one
    const v = S.infoFor && repOf.get(S.infoFor);
    if (v && !$("#info").hidden) showNodeInfo(cy.getElementById(v));
  }
}
/** The nodes behind a virtual node are shown again; ``here``: they appear where the virtual node stands. */
function release(v, here) {
  const ms = members(v);
  if (here) ms.positions(() => ({...v.position()}));
  ms.removeClass("merged");
  return ms;
}
const members = v => S.cy.collection((v.data("members") || []).map(id => S.cy.getElementById(id)).filter(f => f.nonempty()));
/** "Rodyti atskirai" / "Išskirti": this group is not merged any more (in this garden); its nodes stand around it. */
function splitVirtual(v) {
  if (v.hasClass("manual")) S.garden.manual = (S.garden.manual || []).filter(m => m.id !== v.id());
  else {
    const list = v.hasClass("twin") ? "untwinned" : "unmerged";
    S.garden[list] = [...new Set([...S.garden[list], v.id()])];
  }
  const obs = obstacles(v), p = v.position();
  const ms = release(v, false);
  ms.forEach(f => f.position(freeSpot({...p}, f.width() / 2, obs)));
  v.remove();
  updateMerges(); saveGardenSoon();
}
/** Groups joined by hand keep only the nodes still in the garden; a group of fewer than two is gone. */
function pruneManual() {
  S.garden.manual = (S.garden.manual || []).map(m => ({...m, members: m.members.filter(id => S.cy.getElementById(id).nonempty())}))
    .filter(m => m.members.length >= 2);
}
/** "Apjungti pažymėtus": the selected nodes become one node of this garden (not of the database). Different names:
 *  the researcher picks one of them or writes their own. Merged nodes among the selected bring all their nodes. */
function mergeSelected() {
  const sel = S.cy.$("node:selected").not(".more, .bundle, .lexmap");
  if (sel.length < 2) return toast("Pažymėkite bent du mazgus (Shift + spustelėjimas), kuriuos norite apjungti", "warning");
  const ids = [...new Set(selectedReal(sel).filter(n => n.isNode() && !n.hasClass("more")).map(n => n.id()))];
  if (ids.length < 2) return toast("Šių mazgų apjungti negalima", "warning");
  // the names offered: of the selected nodes as shown (in the order they were selected)
  const order = S.selOrder.map(id => S.cy.getElementById(id)).filter(n => n.nonempty() && sel.contains(n));
  const names = [...new Set([...order, ...sel.not(S.cy.collection(order))].map(n => String(n.data("display_name") ?? "")).filter(Boolean))];
  const old = new Set(sel.filter(".manual").map(n => n.id()));
  const done = name => {
    // a node can be in one group only: groups it was in give it up (a group joined again is replaced)
    const rest = (S.garden.manual || []).filter(m => !old.has(m.id)).map(m => ({...m, members: m.members.filter(id => !ids.includes(id))}))
      .filter(m => m.members.length >= 2);
    const id = "manual|" + randomGardenId() + randomGardenId();
    S.garden.manual = [...rest, {id, members: ids.sort(), name}];
    S.cy.$(":selected").unselect();
    updateMerges(); saveGardenSoon();
    const v = S.cy.getElementById(id);
    if (v.nonempty()) v.select();
    toast(tx("Apjungta {0} mazgų į „{1}“ – tik šiame sode", ids.length, name));
  };
  if (names.length <= 1) return done(names[0] || "?");
  nameDialog(tx("Apjungti {0} mazgus", ids.length), names, names[0], done);
}
/** The name of a node joined by hand: one of ``names`` or the researcher's own. */
function nameDialog(title, names, current, done) {
  const own = !names.includes(current);
  $("#modalBody").innerHTML = `<h3>${esc(title)}</h3>
    <p class="muted" style="font-size:.85em">Pavadinimai skiriasi. Kurį rodyti? Apjungtas mazgas yra tik šio sodo – duomenų bazėje niekas nekeičiama.</p>
    <div class="name-pick">${names.map((n, i) => `<label><input type="radio" name="mName" value="${i}" ${n === current ? "checked" : ""}> <span translate="no">${esc(n)}</span></label>`).join("")}
      <label><input type="radio" name="mName" value="own" ${own ? "checked" : ""}> savas pavadinimas:
        <input id="mOwn" maxlength="200" value="${own ? esc(current) : ""}" style="width:100%"></label></div>
    <div class="actions"><button id="mCancel">Atšaukti</button><button class="primary" id="mOk">Gerai</button></div>`;
  $("#mOwn").onfocus = () => { $('[name="mName"][value="own"]').checked = true; };
  $("#mCancel").onclick = () => { $("#modal").hidden = true; };
  $("#mOk").onclick = () => {
    const v = ($('[name="mName"]:checked') || {}).value;
    const name = v === "own" ? $("#mOwn").value.trim() : names[Number(v)];
    if (!name) return $("#mOwn").focus();
    $("#modal").hidden = true;
    done(name);
  };
  $("#modal").hidden = false;
}
/** "Pervadinti": another name for a node joined by hand. */
function renameManual(v) {
  const g = (S.garden.manual || []).find(m => m.id === v.id());
  if (!g) return;
  const names = [...new Set(members(v).map(n => String(n.data("display_name") ?? "")).filter(Boolean))];
  nameDialog(tx("Pervadinti apjungtą mazgą"), names, g.name, name => {
    g.name = name;
    updateMerges(); saveGardenSoon();
    if (S.infoFor === v.id()) showNodeInfo(S.cy.getElementById(v.id()));
  });
}
/** "Sujunk vienodus" / "Apjungti tapačius": groups of this node that were split are merged again.
 *  ``kind``: "multi" (same-named nodes), "twin" (the same thing in two datasets) or both. */
const groupOf = (id, node, kind) => (kind !== "twin" && id.startsWith(`multi|${node.id()}|`)) ||
  (kind !== "multi" && (id.startsWith(`twin|${node.id()}|`) || id.startsWith("twin|") && id.endsWith(`|${node.id()}`)));
function remerge(node, kind) {
  const mine = id => groupOf(id, node, kind);
  if (kind !== "twin") S.garden.unmerged = S.garden.unmerged.filter(id => !mine(id));
  if (kind !== "multi") S.garden.untwinned = S.garden.untwinned.filter(id => !mine(id));
  updateMerges(); saveGardenSoon();
  if (kind === "twin") toast(`${node.data("display_name")}: apjungta su atitikmeniu`);
}
function remergeAllTwins() {
  const n = S.garden.untwinned.length;
  S.garden.untwinned = [];
  updateMerges(); saveGardenSoon();
  toast(`Apjungta tapačių porų: ${n}`);
}
const splitOf = (node, kind) => (kind === "twin" ? S.garden.untwinned : kind === "multi" ? S.garden.unmerged : [...S.garden.unmerged, ...S.garden.untwinned])
  .some(id => groupOf(id, node, kind));
/** Selected elements with the real ones behind the selected virtual ones instead of them. */
function selectedReal(sel) {
  let out = sel.not(".virtual");
  sel.filter(".virtual").forEach(v => { out = out.union(v.isNode() ? members(v) : realEdge(v)); });
  return out;
}
/** The garden's relationships a proxy stands for (a multi edge stands for none: its nodes are removed with the node). */
const realEdge = e => e.data("reals") ? S.cy.collection(e.data("reals").map(id => S.cy.getElementById(id))) : e.hasClass("virtual") ? S.cy.collection() : e;

// ---------------------------------------------------------------- SVG export
// Drawn from the computed Cytoscape styles. Without the map: the whole garden; on the map: what is on screen,
// with the map tiles under it. Pictures and tiles are embedded, so the file stands alone.
async function toDataUrl(url) {
  try {
    const r = await fetch(url, {mode: "cors"});
    if (!r.ok) return url;
    const b = await r.blob();
    return await new Promise(ok => { const f = new FileReader(); f.onload = () => ok(f.result); f.onerror = () => ok(url); f.readAsDataURL(b); });
  } catch (e) { return url; }
}
const cssUrl = v => { const m = /url\(["']?(.*?)["']?\)/.exec(v || ""); return m ? m[1] : v && v !== "none" ? v : null; };
const DASH = {dashed: "6 4", dotted: "1.5 3"};
/** The garden as an SVG picture: {text, width, height}; null when the garden is empty. Without the map – the whole
 *  garden, with the map – what is seen (with the map's tiles). */
async function gardenSvg(bib) {
  const cy = S.cy, nodes = cy.nodes(":visible"), edges = cy.edges(":visible");
  if (nodes.empty()) return null;
  const bg = cssVar("--graph-bg") || "#fff", font = getComputedStyle(document.body).fontFamily.replace(/"/g, "'");
  let W, H, tf, scale;
  if (S.map.on) {
    W = cy.width(); H = cy.height(); scale = cy.zoom();
    tf = `translate(${cy.pan().x} ${cy.pan().y}) scale(${scale})`;
  } else {
    const bb = cy.elements(":visible").boundingBox({includeLabels: true}), pad = 24;
    W = Math.ceil(bb.w + 2 * pad); H = Math.ceil(bb.h + 2 * pad); scale = 1;
    // a narrow garden is widened (and centred) so that its sources fit under it
    const extra = Math.max(0, FOOT_MIN_W - W) / 2;
    W += 2 * extra;
    tf = `translate(${pad - bb.x1 + extra} ${pad - bb.y1})`;
  }
  const foot = bibFooter(bib, W), Hg = H;
  H += foot.height;
  const urls = new Set(), img = [];
  const halo = `stroke="${esc(bg)}" stroke-opacity=".75" paint-order="stroke" stroke-linejoin="round"`;
  const out = [];
  // map tiles, where they are on screen
  if (S.map.on) {
    const box = $("#cy").getBoundingClientRect(), dark = document.documentElement.dataset.theme === "dark";
    const op = Number(S.settings.map.opacity ?? 0.7);
    for (const t of $$("#map img.leaflet-tile-loaded")) {
      const r = t.getBoundingClientRect();
      if (r.right < box.left || r.bottom < box.top || r.left > box.right || r.top > box.bottom) continue;
      urls.add(t.src);
      img.push(`<image xlink:href="${esc(t.src)}" x="${r.left - box.left}" y="${r.top - box.top}" width="${r.width}" height="${r.height}" opacity="${op}"` +
        (dark ? ` style="filter: invert(1) hue-rotate(180deg) brightness(.85) contrast(.9)"` : "") + "/>");
    }
  }
  const g = [];
  edges.forEach(e => {
    const st = p => e.pstyle(p), w = st("width").pfValue, color = st("line-color").strValue, op = st("opacity").value;
    const a = e.sourceEndpoint(), b = e.targetEndpoint(), cps = e.controlPoints && e.controlPoints();
    const d = cps && cps.length ? `M${a.x} ${a.y} Q${cps[0].x} ${cps[0].y} ${b.x} ${b.y}` : `M${a.x} ${a.y} L${b.x} ${b.y}`;
    const dash = DASH[st("line-style").strValue];
    g.push(`<path d="${d}" fill="none" stroke="${esc(color)}" stroke-width="${w}" opacity="${op}"${dash ? ` stroke-dasharray="${dash.split(" ").map(x => x * w / 1.4).join(" ")}"` : ""}/>`);
    if (st("target-arrow-shape").strValue !== "none") {
      const from = cps && cps.length ? cps[cps.length - 1] : a, ang = Math.atan2(b.y - from.y, b.x - from.x);
      // Cytoscape's triangle: size max((13.37 w)^0.9, 29), 0.3 of it long and 0.15 of it to each side
      const size = Math.max(Math.pow(w * 13.37, 0.9), 29) * st("arrow-scale").value, len = 0.3 * size, half = 0.15 * size;
      const p1 = {x: b.x - len * Math.cos(ang) + half * Math.sin(ang), y: b.y - len * Math.sin(ang) - half * Math.cos(ang)};
      const p2 = {x: b.x - len * Math.cos(ang) - half * Math.sin(ang), y: b.y - len * Math.sin(ang) + half * Math.cos(ang)};
      g.push(`<polygon points="${b.x},${b.y} ${p1.x},${p1.y} ${p2.x},${p2.y}" fill="${esc(st("target-arrow-color").strValue)}" opacity="${op}"/>`);
    }
    const label = st("label").strValue;
    if (label) {
      const m = e.midpoint(), fs = st("font-size").pfValue;
      let ang = Math.atan2(b.y - a.y, b.x - a.x) * 180 / Math.PI;
      if (ang > 90) ang -= 180; else if (ang < -90) ang += 180;
      g.push(`<text x="${m.x}" y="${m.y}" font-size="${fs}" fill="${esc(st("color").strValue)}" text-anchor="middle" dominant-baseline="central"
        transform="rotate(${ang} ${m.x} ${m.y})" stroke-width="${fs / 4}" ${halo}>${esc(label)}</text>`);
    }
  });
  const badge = S.settings.graph.badgeSize / scale;
  nodes.forEach(n => {
    const st = p => n.pstyle(p), {x, y} = n.position(), w = n.width(), h = n.height(), op = st("opacity").value;
    const fill = st("background-color").strValue, fillOp = st("background-opacity").value;
    const bw = st("border-width").pfValue, bc = st("border-color").strValue, bs = st("border-style").strValue;
    const shape = st("shape").strValue, path = SHAPE_PATHS[shape];
    const stroke = bw > 0 ? ` stroke="${esc(bc)}" stroke-width="${bs === "double" ? bw / 3 : bw}"${DASH[bs] ? ` stroke-dasharray="${DASH[bs]}"` : ""}` : "";
    const paint = `fill="${esc(fill)}" fill-opacity="${fillOp}"${stroke}`;
    const parts = [];
    if (path) parts.push(`<path d="${path}" transform="translate(${x - w / 2} ${y - h / 2}) scale(${w / 40} ${h / 40})" ${paint.replace(/stroke-width="([\d.]+)"/, (_, v) => `stroke-width="${v * 40 / w}"`)}/>`);
    else if (/rect|tag/.test(shape)) parts.push(`<rect x="${x - w / 2}" y="${y - h / 2}" width="${w}" height="${h}" rx="${shape.startsWith("round") ? Math.min(w, h) / 4 : 0}" ${paint}/>`);
    else parts.push(`<ellipse cx="${x}" cy="${y}" rx="${w / 2}" ry="${h / 2}" ${paint}/>`);
    if (bs === "double" && bw > 0) parts.push(`<ellipse cx="${x}" cy="${y}" rx="${w / 2 - bw * 2 / 3}" ry="${h / 2 - bw * 2 / 3}" fill="none" stroke="${esc(bc)}" stroke-width="${bw / 3}"/>`);
    const pic = cssUrl(st("background-image").strValue);
    if (pic) { urls.add(pic); parts.push(`<image xlink:href="${esc(pic)}" x="${x - w / 2}" y="${y - h / 2}" width="${w}" height="${h}" preserveAspectRatio="xMidYMid meet"/>`); }
    (n.scratch("_badges") || []).forEach((bd, i) => {
      const u = bd.url || bd;   // a badge is {url, title}
      urls.add(u);
      parts.push(`<image xlink:href="${esc(u)}" x="${x + w / 2 * .7 + i * (badge + 2 / scale)}" y="${y - h / 2 * .7 - badge}" width="${badge}" height="${badge}" preserveAspectRatio="xMidYMid meet"/>`);
    });
    const label = st("label").strValue;
    if (label) {
      const fs = st("font-size").pfValue, ty = y + h / 2 + st("text-margin-y").pfValue + bw / 2 + fs * .85;
      parts.push(`<text x="${x}" y="${ty}" font-size="${fs}" fill="${esc(st("color").strValue)}" text-anchor="middle" stroke-width="${fs / 4}" ${halo}>${esc(label)}</text>`);
    }
    g.push(`<g opacity="${op}">${parts.join("")}</g>`);
  });
  // pictures and tiles go into the file itself
  const data = new Map(await Promise.all([...urls].map(async u => [u, await toDataUrl(u)])));
  const embed = str => str.replace(/href="([^"]*)"/g, (m, u) => { const raw = u.replace(/&amp;/g, "&"); return data.has(raw) ? `href="${esc(data.get(raw))}"` : m; });
  out.push(`<?xml version="1.0" encoding="UTF-8"?>`,
    // xlink:href (not only SVG 2 href): Inkscape and other programs show the pictures only so
    `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="${esc(font)}">`,
    `<title>${esc(S.garden.name || "Sodas")}</title>`, bibMetadata(bib),
    `<rect width="100%" height="100%" fill="${esc(bg)}"/>`, `<svg width="${W}" height="${Hg}" overflow="hidden">`, embed(img.join("\n")),
    `<g transform="${tf}">`, embed(g.join("\n")), `</g>`,
    S.map.on ? `<text x="${W - 6}" y="${Hg - 6}" font-size="10" text-anchor="end" fill="#555">© OpenStreetMap</text>` : "", `</svg>`,
    `<g transform="translate(0 ${Hg})">${foot.svg}</g>`, `</svg>`);
  return {text: out.join("\n"), width: W, height: H};
}
// ---------------------------------------------------------------- the sources a downloaded garden carries
// Every download carries the whole bibliography (SODAS and every dataset the garden used): an SVG or PNG shows it under
// the garden and keeps it in its metadata, a JSON file has it in „bibliografija“. Without it nothing is downloaded.
const FOOT_MIN_W = 560, FOOT_FS = 11, FOOT_LH = 14;
/** All formats of the bibliography (/api/bibliografija/visa): the garden's own datasets and those shown now
 *  (on the map of a merged node too). */
async function exportBibliography() {
  if (S.garden.id) await saveGardenNow();
  const shown = new Set();
  S.cy.nodes().not(".more").forEach(n => { const d = dsOf(n.data()); if (d) shown.add(d); });
  if (S.lexMap) S.lexMap.points.forEach(p => { if (p[5]) shown.add(String(p[5])); });
  const q = new URLSearchParams({ir: [...shown].join(",")});
  if (S.garden.id) q.set("sodas", S.garden.id);
  try { return await api(`/api/bibliografija/visa?${q}`); }
  catch (e) {
    if (!q.has("sodas")) throw e;
    q.delete("sodas");
    return await api(`/api/bibliografija/visa?${q}`);
  }
}
/** Words into lines of at most ``n`` characters. */
function wrapText(text, n) {
  const out = [];
  let line = "";
  for (const w of String(text).split(/\s+/).filter(Boolean)) {
    if (line && (line + " " + w).length > n) { out.push(line); line = w; } else line = line ? line + " " + w : w;
  }
  if (line) out.push(line);
  return out;
}
/** The band under the garden: what it is, when, and every source to cite (APA). */
function bibFooter(bib, W) {
  const ink = cssVar("--ink") || "#222", muted = cssVar("--muted") || "#666", line = cssVar("--line") || "#ccc";
  const n = Math.max(40, Math.floor((W - 24) / (FOOT_FS * 0.56)));
  const rows = [[tx("„{0}“ – Sodas, {1}. Šaltiniai, kuriuos būtina cituoti:", S.garden.name || tx("Sodas be pavadinimo"), bib.made_at), true]];
  for (const e of String(bib.tekstas || "").split(/\n\s*\n/).map(x => x.trim()).filter(Boolean)) wrapText(e, n).forEach((l, i) => rows.push([(i ? "   " : "• ") + l, false]));
  const top = 10, height = top + rows.length * FOOT_LH + 10;
  const svg = `<line x1="0" y1="0.5" x2="${W}" y2="0.5" stroke="${esc(line)}"/>` + rows.map(([t, head], i) =>
    `<text x="12" y="${top + FOOT_LH * (i + 0.8)}" font-size="${FOOT_FS}" fill="${esc(head ? ink : muted)}"${head ? ' font-weight="600"' : ""} xml:space="preserve">${esc(t)}</text>`).join("");
  return {svg, height};
}
const cdata = t => `<![CDATA[${String(t).replace(/\]\]>/g, "]]]]><![CDATA[>")}]]>`;
/** The bibliography inside the SVG file: a description (APA) and the metadata (APA, BibTeX, RIS). */
const bibMetadata = bib => `<desc>${esc(bib.tekstas)}</desc><metadata id="bibliografija" data-program="Sodas">` +
  `<tekstas>${cdata(bib.tekstas)}</tekstas><bibtex>${cdata(bib.bibtex)}</bibtex><ris>${cdata(bib.ris)}</ris></metadata>`;
let crcTable = null;
function crc32(bytes) {
  if (!crcTable) crcTable = Array.from({length: 256}, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
  let c = 0xffffffff;
  for (const b of bytes) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
/** A PNG with international text chunks (iTXt, UTF-8) put in before its end: Title, Software, Description (APA), Comment (BibTeX). */
async function pngWithText(blob, texts) {
  const png = new Uint8Array(await blob.arrayBuffer()), enc = new TextEncoder();
  const chunks = Object.entries(texts).map(([key, value]) => {
    const data = new Uint8Array([...enc.encode(key), 0, 0, 0, 0, 0, ...enc.encode(String(value))]);   // keyword, flags, no language
    const type = enc.encode("iTXt"), out = new Uint8Array(12 + data.length), dv = new DataView(out.buffer);
    dv.setUint32(0, data.length); out.set(type, 4); out.set(data, 8);
    dv.setUint32(8 + data.length, crc32(new Uint8Array([...type, ...data])));
    return out;
  });
  const end = png.length - 12;   // IEND is the last chunk
  return new Blob([png.slice(0, end), ...chunks, png.slice(end)], {type: "image/png"});
}
const exportName = ext => `${(S.garden.name || "sodas").replace(/[\\/:*?"<>|]+/g, "_")}.${ext}`;
function saveBlob(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  toast(`Išsaugota: ${name}`);
}
async function exportSvg() {
  const done = Kalba.working("Ruošiamas SVG…");
  try {
    if (S.cy.nodes(":visible").empty()) return toast("Sodas tuščias");
    let bib;
    try { bib = await exportBibliography(); } catch (e) { return toast("Be bibliografijos sodo atsisiųsti negalima – bandykite dar kartą", "error"); }
    const svg = await gardenSvg(bib);
    saveBlob(new Blob([svg.text], {type: "image/svg+xml"}), exportName("svg"));
  } finally { done(); }
}
/** The same picture as the SVG, drawn on a canvas: twice the screen's size (sharp when printed), at most PNG_MAX_PX a side. */
const PNG_MAX_PX = 12000;
async function exportPng() {
  const done = Kalba.working("Ruošiamas PNG…");
  try {
    if (S.cy.nodes(":visible").empty()) return toast("Sodas tuščias");
    let bib;
    try { bib = await exportBibliography(); } catch (e) { return toast("Be bibliografijos sodo atsisiųsti negalima – bandykite dar kartą", "error"); }
    const svg = await gardenSvg(bib);
    const k = Math.min(2, PNG_MAX_PX / svg.width, PNG_MAX_PX / svg.height);
    const url = URL.createObjectURL(new Blob([svg.text], {type: "image/svg+xml"}));
    const img = new Image();
    try {
      await new Promise((ok, fail) => { img.onload = ok; img.onerror = () => fail(new Error("SVG nepavyko nupiešti")); img.src = url; });
      const c = document.createElement("canvas");
      c.width = Math.max(1, Math.round(svg.width * k)); c.height = Math.max(1, Math.round(svg.height * k));
      const ctx = c.getContext("2d");
      ctx.drawImage(img, 0, 0, c.width, c.height);
      const blob = await new Promise(ok => c.toBlob(ok, "image/png"));
      if (!blob) throw new Error("per didelis vaizdas");
      saveBlob(await pngWithText(blob, {Title: S.garden.name || "Sodas", Software: "Sodas", Description: bib.tekstas, Comment: bib.bibtex}), exportName("png"));
    } catch (e) { toast(`PNG nepavyko: ${e.message}`, "error"); }
    finally { URL.revokeObjectURL(url); }
  } finally { done(); }
}
/** JSON: the garden file (``sodo-byla/1``, as „Tvarkyti sodus“ ⬇): nodes with their places, relationships, the view and the
 *  datasets used – it can be uploaded again. A garden the server does not keep yet: made here. */
async function exportJson() {
  if (S.cy.nodes().empty()) return toast("Sodas tuščias");
  if (S.garden.id) return downloadGarden(S.garden.id);   // the server puts the bibliography in
  let bib;
  try { bib = await exportBibliography(); } catch (e) { return toast("Be bibliografijos sodo atsisiųsti negalima – bandykite dar kartą", "error"); }
  saveBlob(new Blob([JSON.stringify({format: "sodo-byla/1", program: "Sodas", exported_at: new Date().toISOString(), garden: gardenSnapshot(),
    bibliografija: bib}, null, 1)], {type: "application/json"}), exportName("sodas.json"));
}
const EXPORTS = [["svg", "SVG", "vektorinis vaizdas – galima didinti, taisyti Inkscape", exportSvg],
  ["png", "PNG", "paveikslas – pranešimams, skaidrėms", exportPng],
  ["json", "JSON", "sodo duomenys – vėl įkeliami „Tvarkyti sodus“", exportJson]];
const EXPORT_NOTE = "Kiekvienoje byloje – visa bibliografija: SVG ir PNG – po sodu ir bylos metaduomenyse, JSON – lauke „bibliografija“.";
function toggleExportMenu() {
  const m = $("#exportMenu");
  if (!m.hidden) { m.hidden = true; return; }
  m.innerHTML = `<div class="hint-row">${S.map.on ? "Su žemėlapiu – matomas vaizdas" : "Visas sodas"}</div>` +
    EXPORTS.map(([k, name, hint]) => `<div class="item" data-x="${k}"><b>${name}</b><span class="ds">${esc(hint)}</span></div>`).join("") +
    `<div class="hint-row">📚 ${esc(tx(EXPORT_NOTE))}</div>`;
  m.hidden = false;
  m.querySelectorAll("[data-x]").forEach(it => it.onclick = ev => { ev.stopPropagation(); m.hidden = true; EXPORTS.find(x => x[0] === it.dataset.x)[3](); });
}

// ---------------------------------------------------------------- status
async function pollStatus() {
  try { S.neo4j = await (await fetch("/api/sodas/status")).json(); } catch (e) { S.neo4j = {ok: false, error: "serveris nepasiekiamas"}; }
  renderStatus();
}
function renderStatus() {
  if (!S.cy || !S.settings) return;
  const lim = S.settings.limits;
  const n = semanticCount(), e = edgeCount();
  const hidden = S.cy.nodes().not(".more, .virtual").filter(x => x.hasClass("hidden") || !labelShown(x)).length;
  const touched = S.cy.nodes("[?touched]").length;
  const off = datasetsOff().size, dsOff = S.cy.nodes(".ds-off").not(".more").length;
  const neo = S.neo4j ? (S.neo4j.ok ? `Neo4j ✓ ${S.neo4j.datasets.length} duomenynai` : `<span class="bad">Neo4j ✗ ${esc(S.neo4j.error || "")}</span>`) : "";
  const offNote = off ? ` · <a href="#" data-ds-off title="⚙ → Duomenynai">išjungta duomenynų: ${off}${dsOff ? `, sode paslėpta ${dsOff} mazgų` : ""}</a>` : "";
  $("#status").innerHTML = `<span>Mazgai ${n}/${lim.maxNodes}${hidden ? ` (paslėpta ${hidden})` : ""} · paliesti ${touched} · Ryšiai ${e}/${lim.maxEdges}</span> · ${neo}${offNote}`;
  const a = $("#status [data-ds-off]");
  if (a) a.onclick = ev => { ev.preventDefault(); openSettings("datasets"); };
}

// ---------------------------------------------------------------- keyboard
const SIZE_LIMITS = {node: [2, 400], badge: [4, 160], label: [4, 96], edge: [0.2, 10]};
const ADJUST_NAMES = {"graph.maxNodeSize": "didžiausias mazgas", "graph.minNodeSize": "mažiausias mazgas", "graph.nodeSize": "visų mazgų dydis",
  "graph.badgeSize": "savybių paveiksliukai", "graph.labelSize": "užrašų dydis", "graph.edgeWidth": "ryšių storis", "ui.fontSize": "raidžių dydis",
  "graph.nodeSizes": "mazgų dydis"};
/** One toast for a run of the same adjustment (the mouse wheel sends many steps). */
function hint(msg) {
  let el = $("#toasts .toast.hint");
  if (!el) { el = document.createElement("div"); el.className = "toast info hint"; $("#toasts").append(el); }
  el.textContent = msg;
  clearTimeout(hint.timer);
  hint.timer = setTimeout(() => el.remove(), 1200);
}
const typing = el => el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
/** ``delta`` ±1: one step, about a tenth of the current value (at least 1). */
function adjust(path, delta, lo, hi) {
  const [a, b] = path.split("."), g = S.settings.graph;
  if (path === "graph.nodeSizes") {
    // every node (the mouse wheel): one size, or the smallest and the largest together
    if (!g.sizeByDegree) return adjust("graph.nodeSize", delta, lo, hi);
    const f = delta > 0 ? 1.1 : 1 / 1.1;
    if ((delta > 0 && g.maxNodeSize >= hi) || (delta < 0 && g.minNodeSize <= lo)) return hint(`${ADJUST_NAMES[path]}: riba`);
    g.minNodeSize = Math.max(lo, Math.min(hi, Math.round(g.minNodeSize * f + Math.sign(delta) * .49)));
    g.maxNodeSize = Math.max(g.minNodeSize, Math.min(hi, Math.round(g.maxNodeSize * f + Math.sign(delta) * .49)));
    settingsChanged("sizes");
    return hint(`${ADJUST_NAMES[path]}: ${g.minNodeSize}–${g.maxNodeSize}`);
  }
  const v = Number(S.settings[a][b]);
  S.settings[a][b] = b === "edgeWidth" ? Math.max(lo, Math.min(hi, Math.round(v * (delta > 0 ? 1.15 : 1 / 1.15) * 100) / 100))
    : Math.max(lo, Math.min(hi, Math.round(v + delta * Math.max(1, v * 0.1))));
  // the other end follows, so min ≤ max always
  if (g.minNodeSize > g.maxNodeSize) { if (b === "maxNodeSize") g.minNodeSize = g.maxNodeSize; else g.maxNodeSize = g.minNodeSize; }
  settingsChanged(a === "graph" && /NodeSize|nodeSize/.test(b) ? "sizes" : "style");
  hint(`${ADJUST_NAMES[path]}: ${b === "edgeWidth" ? "×" + S.settings[a][b] : S.settings[a][b]}`);
}
/** Mouse wheel over the garden with a modifier: Shift – node sizes, Alt – labels of nodes and relationships,
 *  Ctrl+Shift – relationship widths. Taken before Cytoscape (it would zoom) and before the browser (Ctrl: page zoom,
 *  Shift: sideways scroll, Alt: history). Steps are at most one per 50 ms, so a touchpad does not race. */
function onModifiedWheel(ev) {
  const c = ev.ctrlKey || ev.metaKey, sh = ev.shiftKey, alt = ev.altKey;
  const what = c && sh && !alt ? ["graph.edgeWidth", SIZE_LIMITS.edge] : sh && !c && !alt ? ["graph.nodeSizes", SIZE_LIMITS.node]
    : alt && !c && !sh ? ["graph.labelSize", SIZE_LIMITS.label] : null;
  if (!what || !ev.target.closest("#cy, #overlay, #map")) return;  // panels over the garden scroll as usual
  ev.preventDefault(); ev.stopPropagation();
  const dy = ev.deltaY || ev.deltaX;  // Shift turns the wheel sideways in some browsers
  const now = performance.now();
  if (!dy || now - (onModifiedWheel.last || 0) < 50) return;
  onModifiedWheel.last = now;
  adjust(what[0], dy < 0 ? 1 : -1, ...what[1]);
}
document.addEventListener("keydown", ev => {
  const k = ev.code, c = ev.ctrlKey || ev.metaKey, sh = ev.shiftKey, alt = ev.altKey;
  const d = k === "NumpadAdd" ? 1 : k === "NumpadSubtract" ? -1 : 0;
  if (k === "Escape") { closeMenus(); $("#results").hidden = true; $("#typesPanel").hidden = true; $("#basketMenu").hidden = true; $("#exportMenu").hidden = true; $("#gardens").hidden = true; $("#modal").hidden = true; return; }
  // Ctrl+Numpad ± is the font size everywhere (also on the settings page); it replaces the browser zoom here.
  if (d && c && !sh && !alt) { ev.preventDefault(); return adjust("ui.fontSize", d, 9, 24); }
  if (!$("#settings").hidden) return;
  if (c && !sh && !alt && k === "KeyF") { ev.preventDefault(); $("#q").focus(); $("#q").select(); if (S.search.q) renderResults(); return; }
  if (k === "F3") { ev.preventDefault(); nextResult(); return; }
  if (d && c && sh && alt) { ev.preventDefault(); return adjust("graph.badgeSize", d, SIZE_LIMITS.badge[0], SIZE_LIMITS.badge[1]); }
  if (d && c && sh && !alt) { ev.preventDefault(); return adjust(S.settings.graph.sizeByDegree ? "graph.maxNodeSize" : "graph.nodeSize", d, SIZE_LIMITS.node[0], SIZE_LIMITS.node[1]); }
  // label size: Alt+Numpad ±; Ctrl+Alt+Numpad ± too where the system lets it through (X11 keymaps give it to
  // XF86Next_VMode / XF86Prev_VMode, so the browser never sees it)
  if (d && alt && !sh) { ev.preventDefault(); return adjust("graph.labelSize", d, SIZE_LIMITS.label[0], SIZE_LIMITS.label[1]); }
  if (c && k === "Digit1" && sh && !alt) { ev.preventDefault(); return toggleLabels("nodeLabels"); }
  if (c && k === "Digit1" && alt && !sh) { ev.preventDefault(); return toggleLabels("edgeLabels"); }
  if (typing(ev.target)) return;
  if (k === "Home" && sh) { ev.preventDefault(); return fitAll(); }
  if (k === "Home") { ev.preventDefault(); return centerOn(); }
  if (c && k === "KeyJ") { ev.preventDefault(); return linkSelected(); }
  if (k === "KeyH" && !c && !alt) { ev.preventDefault(); return sh ? showHidden() : hideSelected(); }
  if (k === "Delete") return removeSelected();
});
$("#q").addEventListener("input", runSearch);
$("#q").addEventListener("focus", () => { if (S.search.q && (S.search.groups.length || S.search.types.length)) renderResults(); });
$("#q").addEventListener("blur", () => setTimeout(() => { $("#results").hidden = true; }, 150));
$("#q").addEventListener("keydown", ev => {
  const flat = flatResults();
  if (ev.key === "ArrowDown") { ev.preventDefault(); S.search.cursor = Math.min(flat.length - 1, S.search.cursor + 1); renderResults(); }
  else if (ev.key === "ArrowUp") { ev.preventDefault(); S.search.cursor = Math.max(0, S.search.cursor - 1); renderResults(); }
  else if (ev.key === "Enter") { ev.preventDefault(); pickResult(Math.max(0, S.search.cursor)); }
});

// ---------------------------------------------------------------- environments: garden | settings (| Vaiva page)
function openSettings(sec) {
  if (sec) settingsSection = sec;
  $("#settings").hidden = false;
  document.body.classList.add("mode-settings");
  $$("[data-env]").forEach(a => a.classList.toggle("active", a.dataset.env === "settings"));
  closeMenus(); $("#typesPanel").hidden = true;
  syncUrl();
  renderSettings();
}
function closeSettings() {
  if (S.previewDark !== undefined) { S.previewDark = undefined; KalbaTheme.apply(S.settings); restyle(); }
  $("#settings").hidden = true;
  document.body.classList.remove("mode-settings");
  $$("[data-env]").forEach(a => a.classList.toggle("active", a.dataset.env === "garden"));
  syncUrl();
  S.cy.resize(); scheduleOverlay();
  if (S.map.l) { S.map.l.invalidateSize({pan: false}); syncMapView(); }
}

// ---------------------------------------------------------------- settings UI
const SHORTCUTS = [
  ["Shift+Home", "parodo visą sodą"], ["Home", "parodo pažymėtą mazgą"], ["Ctrl+F", "paieškos laukelis"],
  ["F3", "pažymėti pirmą / kitą rastą mazgą"], ["Ctrl+Shift+Numpad +/−", "didžiausias mazgų dydis ±"],
  ["Alt+Numpad +/−", "mazgų ir ryšių užrašų dydis ± (arba Ctrl+Alt+Numpad, jei sistema jo neperima)"], ["Ctrl+Alt+Shift+Numpad +/−", "savybių paveiksliukai ±"],
  ["Shift + pelės ratukas", "mazgų dydis ±"], ["Alt + pelės ratukas", "mazgų ir ryšių užrašų dydis ±"],
  ["Ctrl+Shift + pelės ratukas", "ryšių storis ±"],
  ["Ctrl+Numpad +/−", "sąsajos raidžių dydis ±"], ["Ctrl+J", "sukurti ryšį tarp dviejų pažymėtų mazgų (įrašomas į Neo4j, duomenynas „Papildymai“)"],
  ["Ctrl+Shift+1", "mazgų užrašai rodyti / slėpti"], ["Ctrl+Alt+1", "ryšių užrašai rodyti / slėpti"],
  ["H", "paslėpti pažymėtus mazgus"], ["Shift+H", "parodyti paslėptus mazgus"],
  ["Delete", "pašalinti pažymėtus iš sodo"], ["Esc", "uždaryti meniu"], ["Shift + spustelėjimas", "pažymėti kelis mazgus"],
  ["Shift + tempimas", "pažymėti stačiakampiu"], ["Ctrl + tempimas", "stačiakampyje esančius mazgus atžymėti"],
  ["Dukart spustelėti", "išskleisti mazgą"], ["Ctrl + 🗺", "visi pažymėto apjungto mazgo (×N) mazgai žemėlapyje (Sense – jų leksemos); artinant rodomi tos srities mazgai"], ["Dešinys klavišas", "veiksmų meniu"],
  ["Vidurinis klavišas ant mazgo / ryšio", "to mazgo / ryšio valdymo skydelis"],
  ["Dešinys klavišas → Suskleisk", "pašalinti kaimynus, susijusius tik su šiuo mazgu"],
];
const SHAPES = ["ellipse", "round-rectangle", "rectangle", "diamond", "hexagon", "octagon", "triangle", "star", "tag", "barrel"];
let settingsSection = "theme";
const SETTINGS_SECTIONS = new Set(["theme", "nodes", "edges", "values", "limits", "map", "datasets", "gardens", "keys", "log", "rysiai"]);
let paletteMode = null;

function uploadButton(onDone) {
  const b = document.createElement("button");
  b.textContent = "Įkelti…";
  b.onclick = () => {
    const inp = document.createElement("input");
    inp.type = "file"; inp.accept = ".png,.svg,.jpg,.jpeg,.webp,.gif";
    inp.onchange = async () => {
      const f = inp.files[0];
      if (!f) return;
      const r = await fetch("/api/sodas/images", {method: "POST", headers: {"X-Filename": encodeURIComponent(f.name)}, body: f});
      const j = await r.json();
      if (!r.ok) { toast(j.error, "warning"); return; }
      onDone(j.url);
    };
    inp.click();
  };
  return b;
}
function imgCell(td, url, set) {
  td.innerHTML = url ? `<img class="thumb" src="${esc(url)}" alt=""> ` : "";
  td.append(uploadButton(u => { set(u); renderSettings(); }));
  if (url) { const x = document.createElement("button"); x.textContent = "×"; x.title = "Pašalinti"; x.onclick = () => { set(null); renderSettings(); }; td.append(" ", x); }
}
const bind = (el, fn, what = "style") => { el.addEventListener("input", () => { fn(el); settingsChanged(what); }); return el; };
const propCache = {}, valueCache = {};
async function propsFor(label) {
  if (label === "*") return [{name: "display_name"}, {name: "dataset"}, ...[...new Set(S.settings.computed.map(c => c.name))].map(name => ({name, computed: true}))];
  if (!propCache[label]) propCache[label] = (await api(`/api/sodas/properties?label=${encodeURIComponent(label)}`)).properties;
  return propCache[label];
}
async function valuesFor(label, prop) {
  if (label === "*" || !prop) return [];
  const k = label + "|" + prop;
  if (!valueCache[k]) valueCache[k] = (await api(`/api/sodas/values?label=${encodeURIComponent(label)}&property=${encodeURIComponent(prop)}`)).values;
  return valueCache[k];
}

/** The theme's colours, each with what it is for (⚙ → Tema: they can be set one by one). */
const THEME_ROLES = [["--bg", "Fonas"], ["--panel", "Skydelis"], ["--panel2", "Antras skydelis"], ["--chip", "Žymė, mygtukų grupė"],
  ["--line", "Linijos, rėmeliai"], ["--ink", "Tekstas"], ["--muted", "Blankus tekstas"], ["--accent", "Paryškinimas"],
  ["--accent-soft", "Paryškinimo fonas"], ["--accent-ink", "Tekstas ant paryškinimo"], ["--graph-bg", "Sodo fonas"],
  ["--ok", "Gerai"], ["--warn", "Įspėjimas"], ["--err", "Klaida"], ["--logo", "Ženklas"]];
/** Pairs that must be told apart, with the least contrast (WCAG ratio) that does it: text needs more than surfaces. */
const CONTRAST_PAIRS = [["--ink", "--bg", 7, "Tekstas ant fono"], ["--ink", "--panel", 7, "Tekstas ant skydelio"],
  ["--muted", "--panel", 4.5, "Blankus tekstas ant skydelio"], ["--accent", "--panel", 3, "Paryškinimas ant skydelio"],
  ["--accent-ink", "--accent", 4.5, "Tekstas ant paryškinimo"], ["--ink", "--accent-soft", 4.5, "Tekstas ant paryškinimo fono"],
  ["--panel", "--bg", 1.06, "Skydelis ir fonas"], ["--chip", "--panel", 1.12, "Žymė ant skydelio"], ["--line", "--panel", 1.35, "Linijos ant skydelio"],
  ["--accent-soft", "--panel", 1.12, "Paryškinimo fonas ant skydelio"], ["--line", "--graph-bg", 1.35, "Ryšiai sodo fone"]];
let colorCtx = null;
/** Any CSS colour as #rrggbb (through a canvas, which understands hsl() as well). */
function hexOf(color) {
  colorCtx = colorCtx || document.createElement("canvas").getContext("2d");
  colorCtx.fillStyle = "#000"; colorCtx.fillStyle = String(color || "#000");
  const f = colorCtx.fillStyle;
  if (f.startsWith("#")) return f;
  const m = f.match(/[\d.]+/g) || [0, 0, 0];
  return "#" + m.slice(0, 3).map(x => Math.round(Number(x)).toString(16).padStart(2, "0")).join("");
}
function luminance(hex) {
  const c = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(x => x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
const contrastRatio = (a, b) => { const x = luminance(hexOf(a)), y = luminance(hexOf(b)); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
/** The colours of the palette being tuned, as theme.js makes them (not read from the page: a light ↔ dark switch glides). */
function themeColours() {
  const st = S.settings, dark = S.previewDark ?? KalbaTheme.isDark(st);
  return KalbaTheme.colours(st.theme[dark ? "dark" : "light"], dark);
}
function syncSwatches() {
  const c = themeColours();
  $$(".pal-role").forEach(el => { const inp = el.querySelector("input"); if (inp && document.activeElement !== inp) inp.value = hexOf(c[el.dataset.var]); });
}
/** ✓ / ⚠ for each pair that must be told apart, with its contrast ratio; too similar – what to do. */
function renderContrastChecks() {
  const box = $("#contrastChecks");
  if (!box) return;
  const c = themeColours();
  const rows = CONTRAST_PAIRS.map(([fg, bg, min, name]) => {
    const r = contrastRatio(c[fg], c[bg]), ok = r >= min;
    return `<div class="cc ${ok ? "ok" : "bad"}"><span class="cc-pair"><span style="background:var(${bg});color:var(${fg});border-color:var(${fg})">Aa</span></span>
      <span>${esc(tx(name))}</span><span class="cc-r">${r.toFixed(2)} : 1</span><span class="cc-mark">${ok ? "✓" : "⚠ " + esc(tx("per panašios (reikia ≥ {0})", min))}</span></div>`;
  });
  const bad = CONTRAST_PAIRS.filter(([fg, bg, min]) => contrastRatio(c[fg], c[bg]) < min).length;
  box.innerHTML = rows.join("") + (bad ? `<div class="muted" style="font-size:.85em;margin-top:4px">${esc(tx("Per panašioms spalvoms padidinkite „Kontrastas“, pakeiskite sąsajos šviesumą arba parinkite tą spalvą ranka."))}</div>` : "");
}
async function renderSettings() {
  $$("#settingsNav a").forEach(a => a.classList.toggle("active", a.dataset.sec === settingsSection));
  const body = $("#settingsBody"), st = S.settings;
  body.classList.remove("embed");
  syncUrl();
  if (settingsSection !== "theme" && S.previewDark !== undefined) { S.previewDark = undefined; KalbaTheme.apply(st); restyle(); }
  if (settingsSection === "theme") {
    const t = st.theme;
    const current = KalbaTheme.isDark(st) ? "dark" : "light";
    paletteMode = paletteMode || current;
    const P = t[paletteMode];
    const sun = KalbaTheme.sunTimes(new Date(), t.latitude, t.longitude);
    const fmt = d => d ? d.toLocaleTimeString(LOCALE, {hour: "2-digit", minute: "2-digit"}) : "—";
    const hslRows = (key, title) => ["h", "s", "l"].map(k => `<div class="row"><label>${tx(title)} – ${tx(({h: "atspalvis", s: "sodrumas", l: "šviesumas"})[k])}</label>
      <input type="range" min="0" max="${k === "h" ? 360 : 100}" value="${P[key][k]}" data-hsl="${key}.${k}"><span>${P[key][k]}</span></div>`).join("");
    body.innerHTML = `<h3>Tema</h3>
      <div class="row"><label>Režimas</label>${[["light", "Šviesi"], ["dark", "Tamsi"], ["sun", "Pagal Saulę"]].map(([v, l]) =>
        `<label><input type="radio" name="mode" value="${v}" ${t.mode === v ? "checked" : ""}> ${l}</label>`).join(" ")}</div>
      <div class="row"><label>Vieta („pagal Saulę“)</label>platuma <input type="number" step="0.01" id="lat" value="${t.latitude}"> ilguma <input type="number" step="0.01" id="lon" value="${t.longitude}">
        <span class="muted">šiandien: saulėtekis ${fmt(sun.sunrise)}, saulėlydis ${fmt(sun.sunset)}${sun.polar ? " (poliarinė " + (sun.polar === "day" ? "diena" : "naktis") + ")" : ""}</span></div>
      <h3 style="margin-top:22px">Spalvos</h3>
      <div class="row"><label>Derinama tema</label><span class="seg">${[["light", "☀ Šviesi"], ["dark", "☾ Tamsi"]].map(([v, l]) =>
        `<button data-pal="${v}" class="${paletteMode === v ? "on" : ""}">${l}</button>`).join("")}</span>
        <span class="muted">kiekviena tema turi savo spalvas; derinant rodoma derinamos temos peržiūra</span></div>
      ${hslRows("base", "Sąsaja")}${hslRows("accent", "Paryškinimas")}
      <div class="row"><label>Kontrastas</label><input type="range" min="0" max="100" value="${P.contrast ?? 50}" id="contrast"><span>${P.contrast ?? 50}</span>
        <span class="muted">kiek skiriasi fonas, skydeliai, žymės ir linijos (50 – kaip anksčiau)</span></div>
      <div class="row top"><label>Spalvos po vieną</label><div>
        <div class="palette-grid">${THEME_ROLES.map(([v, name]) => `<div class="pal-role${(P.custom || {})[v] ? " own" : ""}" data-var="${v}">
          <label class="pal-sw" style="background:var(${v})" title="${esc(tx("Pakeisti spalvą"))}"><input type="color"></label>
          <span class="pal-name">${esc(tx(name))}<small class="mono">${v}</small></span>
          ${(P.custom || {})[v] ? `<button class="pal-x" title="${esc(tx("Grąžinti apskaičiuotą spalvą"))}">×</button>` : ""}</div>`).join("")}</div>
        <div class="muted" style="font-size:.85em">Spustelėkite spalvą, kad ją pakeistumėte ranka; ranka parinkta spalva nebesikeičia keičiant slankiklius (× – grąžinti).
          ${Object.keys(P.custom || {}).length ? '<a href="#" id="palClear">Grąžinti visas apskaičiuotas spalvas</a>' : ""}</div></div></div>
      <div class="row top"><label>Pavyzdys</label><div class="theme-sample">
        <div class="ts-panel"><b>Skydelis</b> <span class="ts-muted">blankus tekstas</span> <span class="ts-chip">žymė</span>
          <a href="#" onclick="return false">nuoroda</a> <button class="primary" type="button">Mygtukas</button> <button type="button">Kitas</button>
          <div class="ts-soft">paryškinimo fonas</div><div class="ts-states"><span style="color:var(--ok)">✓ gerai</span> <span style="color:var(--warn)">⚠ įspėjimas</span> <span style="color:var(--err)">✕ klaida</span></div></div>
        <div class="ts-graph"><span></span><span></span><i></i></div></div></div>
      <div class="row top"><label>Kontrasto patikra</label><div class="contrast-checks" id="contrastChecks"></div></div>
      <div class="row"><label>Raidžių dydis</label><input type="number" id="fs" min="9" max="24" value="${st.ui.fontSize}"> px <span class="muted">(Ctrl+Numpad + / −)</span></div>
      <h3 style="margin-top:22px">Numatytieji nustatymai</h3>
      <p class="muted">Visi nustatymai (tema, spalvos, paveiksliukai, ribos) grąžinami į tokius, su kokiais programa pateikiama; išjungti duomenynai lieka išjungti.</p>
      <div class="row"><button id="setReset">Grąžinti numatytuosius</button></div>`;
    S.previewDark = paletteMode === "dark";
    KalbaTheme.apply(st, S.previewDark); restyle();
    syncSwatches(); renderContrastChecks();
    const contrast = $("#contrast");
    bind(contrast, el => { P.contrast = Number(el.value); el.nextElementSibling.textContent = el.value; }, "all");
    contrast.addEventListener("input", () => { syncSwatches(); renderContrastChecks(); });
    body.querySelectorAll(".pal-role").forEach(el => {
      const v = el.dataset.var, inp = el.querySelector("input");
      inp.oninput = () => { P.custom = {...(P.custom || {}), [v]: inp.value}; el.classList.add("own"); settingsChanged("all"); renderContrastChecks(); };
      inp.onchange = () => renderSettings();
      const x = el.querySelector(".pal-x");
      if (x) x.onclick = () => { const c = {...(P.custom || {})}; delete c[v]; P.custom = c; settingsChanged("all"); renderSettings(); };
    });
    if ($("#palClear")) $("#palClear").onclick = e => { e.preventDefault(); P.custom = {}; settingsChanged("all"); renderSettings(); };
    body.querySelectorAll('[name="mode"]').forEach(r => r.onchange = () => { t.mode = r.value; paletteMode = null; settingsChanged("all"); renderSettings(); });
    body.querySelectorAll("[data-pal]").forEach(b => b.onclick = () => { paletteMode = b.dataset.pal; renderSettings(); });
    bind($("#lat"), el => t.latitude = Number(el.value), "all"); bind($("#lon"), el => t.longitude = Number(el.value), "all");
    bind($("#fs"), el => st.ui.fontSize = Number(el.value) || 14);
    body.querySelectorAll("[data-hsl]").forEach(inp => {
      bind(inp, el => { const [o, k] = el.dataset.hsl.split("."); P[o][k] = Number(el.value); el.nextElementSibling.textContent = el.value; }, "all");
      inp.addEventListener("input", () => { syncSwatches(); renderContrastChecks(); });
    });
    const afterReset = async r => { adoptSettings(r); KalbaTheme.apply(S.settings); restyle(); refreshOverlay(); updateSizes(); renderSettings(); };
    if ($("#setReset")) $("#setReset").onclick = async e => {
      if (e.target.dataset.sure !== "1") { e.target.dataset.sure = "1"; e.target.textContent = "Tikrai grąžinti?"; return; }
      afterReset(await api("/api/sodas/settings/reset", {})); toast("Grąžinti numatytieji nustatymai");
    };
  } else if (settingsSection === "nodes") {
    const labels = [...new Set([...S.schema.labels, ...Object.keys(st.nodeTypes)])].sort();
    body.innerHTML = `<h3>Mazgų išvaizda</h3><p class="muted">Kiekvieno tipo mazgui galima parinkti spalvą, formą ir paveiksliuką (PNG, SVG, JPG, WebP; iki 2 MB). Dydis – skyriuje „Ribos ir dydžiai“.</p>
      <table><tr><th>Tipas</th><th>Spalva</th><th>Forma</th><th>Paveiksliukas</th><th>Vaizdas</th></tr>${labels.map(l => `<tr data-l="${esc(l)}"><td>${esc(l)}</td>
        <td><input type="color" value="${esc(nodeType(l).color || "#888888")}"></td>
        <td><select>${SHAPES.map(s => `<option ${(nodeType(l).shape || "ellipse") === s ? "selected" : ""}>${s}</option>`).join("")}</select></td><td class="img"></td>
        <td>${nodePicture({label: l, display_name: l}, 26)}</td></tr>`).join("")}</table>`;
    body.querySelectorAll("tr[data-l]").forEach(tr => {
      const l = tr.dataset.l, get = () => (st.nodeTypes[l] = st.nodeTypes[l] || {});
      bind(tr.querySelector("input[type=color]"), el => { get().color = el.value; S.cy.nodes(`[label = "${l}"]`).data("color", el.value); });
      tr.querySelector("select").onchange = e => { get().shape = e.target.value; settingsChanged(); renderSettings(); };
      imgCell(tr.querySelector(".img"), nodeType(l).image, u => { get().image = u || undefined; settingsChanged(); });
    });
  } else if (settingsSection === "edges") {
    const types = [...new Set([...S.schema.types, ...Object.keys(st.edgeTypes)])].sort();
    body.innerHTML = `<h3>Ryšių išvaizda</h3><p class="muted">Linijos storis, stilius, spalva ir paveiksliukas, rodomas prie ryšio užrašo.</p>
      <table><tr><th>Tipas</th><th>Storis</th><th>Stilius</th><th>Spalva</th><th>Paveiksliukas prie užrašo</th></tr>${types.map(t => {
        const e = edgeType(t);
        return `<tr data-t="${esc(t)}"><td class="mono">${esc(t)}</td><td><input type="number" min="0.5" max="12" step="0.5" value="${e.width || 1.4}"></td>
          <td><select>${[["solid", "ištisinė"], ["dashed", "brūkšninė"], ["dotted", "taškinė"]].map(([v, l]) => `<option value="${v}" ${(e.style || "solid") === v ? "selected" : ""}>${l}</option>`).join("")}</select></td>
          <td><input type="color" value="${esc(e.color || "#b9b5ad")}"> <button data-nocolor title="Numatytoji spalva">↺</button></td><td class="img"></td></tr>`; }).join("")}</table>`;
    body.querySelectorAll("tr[data-t]").forEach(tr => {
      const t = tr.dataset.t, get = () => (st.edgeTypes[t] = st.edgeTypes[t] || {});
      bind(tr.querySelector("input[type=number]"), el => get().width = Number(el.value));
      tr.querySelector("select").onchange = e => { get().style = e.target.value; settingsChanged(); };
      bind(tr.querySelector("input[type=color]"), el => get().color = el.value);
      tr.querySelector("[data-nocolor]").onclick = () => { delete get().color; settingsChanged(); renderSettings(); };
      imgCell(tr.querySelector(".img"), edgeType(t).image, u => { get().image = u || undefined; settingsChanged(); });
    });
  } else if (settingsSection === "values") {
    const labels = ["*", ...S.schema.labels];
    body.innerHTML = `<h3>Savybių paveiksliukai</h3>
      <p class="muted">Pasirinkite mazgo tipą, tada jo savybę ir reikšmę iš duomenų bazėje esančių (galima ir įrašyti ranka). Jei mazgo savybė turi tą reikšmę, šalia mazgo rodomas paveiksliukas.
      Išskaičiuotos savybės (pvz. <span class="mono">language</span>) pažymėtos ƒ. Taisyklė <span class="mono">Languoid · display_name · Lithuanian</span> suteikia paveiksliuką pačiai kalbai – jis perimamas visiems tos kalbos žodžiams.</p>
      <table><tr><th>Mazgo tipas</th><th>Savybė</th><th>Reikšmė</th><th>Paveiksliukas</th><th></th></tr>${st.valueImages.map((v, i) => `<tr data-i="${i}">
        <td><select data-f="label">${labels.map(l => `<option ${v.label === l ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></td>
        <td><select data-f="property"><option value="${esc(v.property || "")}">${esc(v.property || "— pasirinkite —")}</option></select></td>
        <td><input data-f="value" value="${esc(v.value || "")}" list="vals${i}" placeholder="pasirinkite arba įrašykite" style="min-width:220px"><datalist id="vals${i}"></datalist></td>
        <td class="img"></td><td><button data-del>×</button></td></tr>`).join("")}</table>
      <button id="addRule" style="margin-top:8px">＋ Nauja taisyklė</button>
      <button id="addFlags" style="margin-top:8px" title="Kalboms, turinčioms žinomą valstybės ar regiono vėliavą, pridėti taisykles Languoid · display_name → vėliava (flag-icons, reikia interneto). Esamos taisyklės nekeičiamos, joms pridedamos užuominos su šalimi.">🏳 Priskirti vėliavas kalboms</button>
      <h3 style="margin-top:28px">Išskaičiuotos savybės</h3>
      <p class="muted">Savybė apskaičiuojama keliu grafe nuo mazgo <span class="mono">(n)</span> iki tikslo <span class="mono">(t)</span>; reikšmė – tikslo pavadinimas. Leidžiamas tik kelio aprašas, užklausa vykdoma tik skaitymui.
</p>
      <table><tr><th>Vardas</th><th>Mazgo tipas</th><th>Kelias</th><th>Paveiksliukas iš tikslo mazgo</th><th></th></tr>${st.computed.map((c, i) => `<tr data-c="${i}">
        <td><input data-f="name" value="${esc(c.name)}" style="width:110px"></td>
        <td><select>${S.schema.labels.map(l => `<option ${c.label === l ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></td>
        <td><input data-f="pattern" value="${esc(c.pattern)}" class="mono" style="width:100%;min-width:320px"></td>
        <td><input type="checkbox" ${c.image_from_target ? "checked" : ""}></td><td><button data-del>×</button></td></tr>`).join("")}</table>
      <button id="addComputed" style="margin-top:8px">＋ Nauja išskaičiuota savybė</button> <button id="recompute">Perskaičiuoti sode</button>`;
    body.querySelectorAll("tr[data-i]").forEach(async tr => {
      const v = st.valueImages[tr.dataset.i];
      const propSel = tr.querySelector('[data-f="property"]'), valInp = tr.querySelector('[data-f="value"]'), dl = tr.querySelector("datalist");
      const fillValues = async () => {
        dl.innerHTML = "";
        const vals = await valuesFor(v.label, v.property).catch(() => []);
        dl.innerHTML = vals.map(x => `<option value="${esc(x.value)}">${x.count}×</option>`).join("");
      };
      const fillProps = async () => {
        const props = await propsFor(v.label).catch(() => []);
        const names = props.map(p => p.name);
        propSel.innerHTML = `<option value="">— pasirinkite —</option>` + props.map(p => `<option value="${esc(p.name)}" ${p.name === v.property ? "selected" : ""}>${p.computed ? "ƒ " : ""}${esc(p.name)}</option>`).join("")
          + (v.property && !names.includes(v.property) ? `<option selected value="${esc(v.property)}">${esc(v.property)} (nėra šiame tipe)</option>` : "");
        fillValues();
      };
      tr.querySelector('[data-f="label"]').onchange = e => { v.label = e.target.value; settingsChanged(); fillProps(); };
      propSel.onchange = () => { v.property = propSel.value; valInp.value = v.value = ""; settingsChanged(); fillValues(); };
      bind(valInp, el => v.value = el.value);
      imgCell(tr.querySelector(".img"), v.image, u => { v.image = u; settingsChanged(); });
      tr.querySelector("[data-del]").onclick = () => { st.valueImages.splice(tr.dataset.i, 1); settingsChanged(); renderSettings(); };
      fillProps();
    });
    $("#addFlags").onclick = async e => {
      e.target.disabled = true;
      try {
        const r = await api("/api/sodas/flags", {});
        adoptSettings(r.settings);
        refreshOverlay(); renderSettings();
        toast(r.added.length ? `Vėliavos priskirtos ${r.added.length} kalbų pavadinimams` : "Naujų vėliavų nėra – visos kalbos jau turi paveiksliukus",
          r.failed.length ? "warning" : "info");
      } finally { e.target.disabled = false; }
    };
    $("#addRule").onclick = () => { st.valueImages.push({label: S.schema.labels.includes("Languoid") ? "Languoid" : "*", property: "display_name", value: "", image: null}); renderSettings(); };
    body.querySelectorAll("tr[data-c]").forEach(tr => {
      const c = st.computed[tr.dataset.c];
      tr.querySelector("select").onchange = e => { c.label = e.target.value; settingsChanged(); };
      tr.querySelectorAll("input[data-f]").forEach(inp => bind(inp, el => c[el.dataset.f] = el.value));
      tr.querySelector("input[type=checkbox]").onchange = e => { c.image_from_target = e.target.checked; settingsChanged(); };
      tr.querySelector("[data-del]").onclick = () => { st.computed.splice(tr.dataset.c, 1); settingsChanged(); renderSettings(); };
    });
    $("#addComputed").onclick = () => { st.computed.push({name: "", label: S.schema.labels[0] || "Form", pattern: "(n)-->(t)", image_from_target: false}); renderSettings(); };
    $("#recompute").onclick = async () => {
      await postSettings(st);
      for (const k in propCache) delete propCache[k];
      for (const k in valueCache) delete valueCache[k];
      S.cy.nodes().removeData("computed"); fetchComputed(S.cy.nodes().map(n => n.id())); toast("Perskaičiuojama");
    };
  } else if (settingsSection === "limits") {
    const L = st.limits, G = st.graph;
    const row = (label, objName, key, min, max, what, hint = "") => `<div class="row"><label>${label}</label><input type="number" min="${min}" max="${max}" value="${st[objName][key]}" data-k="${key}" data-o="${objName}" data-w="${what}"> <span class="muted">${hint}</span></div>`;
    body.innerHTML = `<h3>Ribos</h3>
      ${row("Daugiausia mazgų sode", "limits", "maxNodes", 10, 5000, "style", "viršijus nauji mazgai neberodomi, įrašas žurnale")}
      ${row("Daugiausia ryšių sode", "limits", "maxEdges", 10, 20000, "style")}
      ${row("Daugiausia ryšių iš vieno mazgo", "limits", "maxPerNode", 5, 500, "style", "likusieji rodomi kaip „+N TIPAS“ mazgas – spustelėjus įkeliama daugiau")}
      ${row("Pluoštas nuo", "limits", "bundleMin", 2, 1000, "style", "tiek ar daugiau vieno pavadinimo kaimynų rodoma kaip vienas mazgas „pavadinimas ×N“, jų neįkeliant (virš 1000 – visada)")}
      <h3 style="margin-top:24px">Mazgų jungimas</h3>
      <div class="row"><label>Drąsiai jungti mazgus</label><label><input type="checkbox" id="boldMerge" ${G.boldMerge !== false ? "checked" : ""}> to paties pavadinimo ir tos pačios kalbos formos bei lytys (Form, Lexeme) iš visų duomenynų rodomos kaip vienas mazgas</label></div>
      <h3 style="margin-top:24px">Mazgų dydis</h3>
      <div class="row"><label>Vienodas dydis</label><label><input type="checkbox" id="sameSize" ${G.sizeByDegree ? "" : "checked"}> visi mazgai vienodo dydžio</label></div>
      ${G.sizeByDegree ? `<div class="row"><label>Dydis pagal</label><select id="sizeSource"><option value="visible" ${G.sizeSource !== "db" ? "selected" : ""}>matomų sode ryšių skaičių</option>
        <option value="db" ${G.sizeSource === "db" ? "selected" : ""}>visų ryšių duomenų bazėje skaičių</option></select></div>`
        + row("Mažiausias mazgas", "graph", "minNodeSize", ...SIZE_LIMITS.node, "sizes", "") + row("Didžiausias mazgas", "graph", "maxNodeSize", ...SIZE_LIMITS.node, "sizes", "Ctrl+Shift+Numpad +/−")
        : row("Visų mazgų dydis", "graph", "nodeSize", ...SIZE_LIMITS.node, "sizes", "Ctrl+Shift+Numpad +/−")}
      ${row("Užrašų dydis", "graph", "labelSize", ...SIZE_LIMITS.label, "style", "mazgų užrašai, px; ryšių užrašai proporcingai; Alt+Numpad +/− arba Alt + pelės ratukas")}
      ${row("Savybių paveiksliukai", "graph", "badgeSize", ...SIZE_LIMITS.badge, "style", "Ctrl+Alt+Shift+Numpad +/−")}
      ${row("Ryšių storis", "graph", "edgeWidth", ...SIZE_LIMITS.edge, "style", "daugiklis visiems ryšiams (ir tipų storiams); Ctrl+Shift + pelės ratukas")}`;
    body.querySelectorAll("input[data-k]").forEach(inp => bind(inp, el => st[el.dataset.o][el.dataset.k] = Number(el.value), inp.dataset.w));
    body.querySelector('[data-k="edgeWidth"]').step = "0.1";
    $("#boldMerge").onchange = e => {
      G.boldMerge = e.target.checked;
      // turned on again: the bold groups shown apart ("Rodyti atskirai") are joined again, too
      if (G.boldMerge) { S.garden.unmerged = S.garden.unmerged.filter(id => !id.startsWith("multi|same|")); saveGardenSoon(); }
      settingsChanged(); updateMerges();
    };
    $("#sameSize").onchange = e => { G.sizeByDegree = !e.target.checked; settingsChanged("sizes"); renderSettings(); };
    if ($("#sizeSource")) $("#sizeSource").onchange = e => { G.sizeSource = e.target.value; settingsChanged("sizes"); };
  } else if (settingsSection === "map") {
    body.innerHTML = `<h3>Žemėlapis</h3>
      <div class="row"><label>Naudoti žemėlapį</label><label><input type="checkbox" id="useMap" ${st.map.enabled ? "checked" : ""}> mazgus su koordinatėmis galima rodyti žemėlapyje</label></div>
      <div class="row"><label>Žemėlapio ryškumas</label><input type="range" id="mapOpacitySet" min="0.1" max="1" step="0.05" value="${st.map.opacity ?? 0.7}"></div>
      <p class="muted">Šalia mazgų su savybėmis <span class="mono">latitude</span> ir <span class="mono">longitude</span> rodomas ženkliukas 📍.
        Spustelėjus jį (arba mazgo meniu) – „Rodyti žemėlapyje“: žemėlapis įjungiamas taip, kad šis mazgas liktų savo vietoje, o kiti sodo mazgai nepajuda.
        Kiti mazgai su koordinatėmis nukeliami į savo vietas, o mazgai be vietos žemėlapyje paslepiami – išjungus žemėlapį jie grįžta ten, kur buvo. Žemėlapyje mazgai su koordinatėmis užrakinti. Išjungti – mygtukas 🗺 viršuje.
        Žemėlapio plytelės – <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>, reikia interneto ryšio.
        Šiuo metu: ${S.map.on ? "žemėlapis rodomas" : "žemėlapis nerodomas"}.</p>
      <h4>Koordinatės per ryšius</h4>
      <p class="muted">Mazgas be savų koordinačių gauna pirmojo kelio tikslo <span class="mono">(t)</span> platumą ir ilgumą,
        pvz. forma – savo kalbos (per leksemą). Išjungus žemėlapį, vieno CognateSet formos tuo pačiu pavadinimu rodomos kaip vienas mazgas „forma ×N“.</p>
      <table><tr><th>Mazgo tipas</th><th>Kelias</th><th></th></tr>${(st.map.geoPaths || []).map((g, i) => `<tr data-gp="${i}">
        <td><select>${S.schema.labels.map(l => `<option ${g.label === l ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></td>
        <td><input class="mono" value="${esc(g.pattern)}" style="width:100%;min-width:380px"></td><td><button data-x>×</button></td></tr>`).join("")}</table>
      <button id="gpAdd" style="margin-top:8px">＋ Kelias</button>`;
    const geoPathsChanged = async () => {
      try { await postSettings(); } catch (e) { return; }
      S.cy.nodes().removeData("geo");
      fetchGeo(S.cy.nodes().map(n => n.id()));
    };
    body.querySelectorAll("tr[data-gp]").forEach(tr => {
      const g = st.map.geoPaths[tr.dataset.gp];
      tr.querySelector("select").onchange = e => { g.label = e.target.value; geoPathsChanged(); };
      tr.querySelector("input").onchange = e => { g.pattern = e.target.value.trim(); geoPathsChanged(); };
      tr.querySelector("[data-x]").onclick = () => { st.map.geoPaths.splice(tr.dataset.gp, 1); geoPathsChanged(); renderSettings(); };
    });
    $("#gpAdd").onclick = () => { (st.map.geoPaths = st.map.geoPaths || []).push({label: S.schema.labels[0] || "", pattern: "(n)-[:USED_IN]->(t:Languoid)"}); renderSettings(); };
    $("#useMap").onchange = e => { st.map.enabled = e.target.checked; settingsChanged(); updateMap(); renderSettings(); };
    $("#mapOpacitySet").oninput = e => { st.map.opacity = Number(e.target.value); applyMapOpacity(); saveSettings(); };
  } else if (settingsSection === "datasets") {
    if (!S.neo4j || !S.neo4j.ok) await pollStatus();
    const all = (S.neo4j && S.neo4j.datasets) || [], off = datasetsOff();
    const inGarden = {};
    S.cy.nodes().not(".more, .virtual").forEach(n => { const d = dsOf(n.data()); inGarden[d] = (inGarden[d] || 0) + 1; });
    body.innerHTML = `<h3>Duomenynai</h3>
      <p class="muted">Duomenyną galima laikinai išjungti, pvz. kai darbui nereikia sunkiasvorių duomenynų. Išjungto duomenyno mazgai neieškomi,
        neišskleidžiami, nerodomi keliuose ir žemėlapyje, o sode esantys – paslepiami (ne pašalinami). Įjungus vėl – jie iškart grįžta.
        Duomenys iš Neo4j netrinami ir iš naujo neįkeliami: tai tik jungtukas.</p>
      <div style="display:flex;gap:6px;margin:8px 0"><button data-all-on>Įjungti visus</button><button data-all-off>Išjungti visus</button></div>
      <table class="ds-table"><tr><th>Įjungtas</th><th>Duomenynas</th><th>Šiame sode mazgų</th></tr>${all.map(d => `<tr>
        <td><label><input type="checkbox" data-ds="${esc(d)}" ${off.has(d) ? "" : "checked"}></label></td>
        <td class="mono">${esc(d)}</td><td class="muted">${inGarden[d] || ""}</td></tr>`).join("")}</table>
      ${all.length ? "" : '<p class="muted">Neo4j nepasiekiama – duomenynų sąrašo nėra.</p>'}`;
    const save = async list => {
      st.datasetsOff = [...new Set(list)].sort();
      applyDatasetsOff(); updateMerges(); updateSizes(); renderStatus(); updateMapSoon();
      try { const r = await postSettings(); S.settings = r; } catch (e) { /* toast shown */ }
      renderSettings();
    };
    body.querySelectorAll("[data-ds]").forEach(cb => cb.onchange = () => {
      const now = datasetsOff();
      if (cb.checked) now.delete(cb.dataset.ds); else now.add(cb.dataset.ds);
      save([...now]);
    });
    body.querySelector("[data-all-on]").onclick = () => save([]);
    body.querySelector("[data-all-off]").onclick = () => save(all);
  } else if (settingsSection === "gardens") {
    await saveGardenNow();
    const list = (await api("/api/sodas/gardens")).gardens;
    body.innerHTML = `<h3>Tvarkyti sodus</h3>
      <table><tr><th>Pavadinimas</th><th>Mazgų</th><th>Pakeistas</th><th></th></tr>${list.map(g => `<tr data-g="${esc(g.id)}">
        <td><input value="${esc(g.name)}" style="min-width:260px">${g.id === S.garden.id ? ' <span class="chip">šis sodas</span>' : ""}</td><td>${g.nodes}</td>
        <td class="muted">${esc((g.updated_at || "").slice(0, 16).replace("T", " "))}</td>
        <td><button data-a="open">Atidaryti</button> <button data-a="tab">Naujoje kortelėje</button> <button data-a="dup">Kopija</button>
          <button data-a="file" title="Atsisiųsti sodą kaip bylą (JSON), kurią kitas sodininkas galės įkelti į savo Sodą">⬇ Byla</button>
          <button data-a="bib" title="Sodo bibliografija: SODAS ir jame naudoti duomenynai">📚</button>
          <button data-a="del" class="danger">Ištrinti</button></td></tr>`).join("") || '<tr><td class="muted">sodų dar nėra</td></tr>'}</table>
      <div class="row" style="margin-top:10px"><button id="gNew">＋ Naujas sodas</button>
        <button id="gUpload" title="Kieno nors atsiųstas sodas (JSON byla) taps nauju jūsų sodu">⬆ Įkelti sodą iš bylos…</button></div>
      <p class="muted">Sodo byloje – jo mazgai, ryšiai, vaizdas ir naudotų duomenynų sąrašas (bibliografijai).</p>`;
    body.querySelectorAll("tr[data-g]").forEach(tr => {
      const id = tr.dataset.g, inp = tr.querySelector("input");
      inp.onchange = async () => {
        await api(`/api/sodas/gardens/${id}/rename`, {name: inp.value});
        if (id === S.garden.id) { S.garden.name = inp.value; $("#gardenName").value = inp.value; }
        toast("Pervadinta");
      };
      tr.querySelectorAll("[data-a]").forEach(b => b.onclick = async () => {
        if (b.dataset.a === "open") { await switchGarden(id); closeSettings(); }
        else if (b.dataset.a === "tab") window.open(`/?sodas=${id}`, "_blank");
        else if (b.dataset.a === "dup") { await api(`/api/sodas/gardens/${id}/duplicate`, {}); renderSettings(); }
        else if (b.dataset.a === "file") downloadGarden(id);
        else if (b.dataset.a === "bib") Kalba.bibliography(b, {sodas: id});
        else if (b.dataset.a === "del") {
          if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = "Tikrai ištrinti?"; return; }
          await api(`/api/sodas/gardens/${id}/delete`, {});
          if (id === S.garden.id) { const r = await api("/api/sodas/gardens"); await loadGarden(r.new_id); }
          renderSettings();
        }
      });
    });
    $("#gNew").onclick = async () => { await newGarden(false); closeSettings(); };
    $("#gUpload").onclick = pickGardenFile;
  } else if (settingsSection === "keys") {
    body.innerHTML = `<h3>Trumpiniai</h3><table>${SHORTCUTS.map(([k, d]) => `<tr><td>${k.split(/(?<=\S)\+(?=\S)/).map(x => `<span class="kbd">${esc(x)}</span>`).join(" + ")}</td><td>${esc(d)}</td></tr>`).join("")}</table>`;
  } else if (settingsSection === "rysiai") {
    const list = (await api("/api/sodas/rysiai")).relationships;
    const line = x => `<b>${esc(x.a.name)}</b> <span class="muted">${esc(x.a.label)}</span> —<span class="mono" title="${x.label ? "CUSTOM: savo pavadintas ryšys" : "duomenų bazės tipas"}">${esc(x.name)}</span>→ <b>${esc(x.b.name)}</b> <span class="muted">${esc(x.b.label)}</span>`;
    body.innerHTML = `<h3>Mano ryšiai</h3>
      <p class="muted">Ryšiai, kuriuos nubrėžėte sode (pažymėkite du mazgus ir spauskite Ctrl+J). Jie įrašyti į Neo4j (duomenynas „Papildymai“)
        ir rodomi kaip visi kiti ryšiai – išskleidus mazgą, kelių paieškoje.</p>
      ${list.length ? list.map(x => `<div class="rel-card" data-r="${x.id}"><div>${line(x)}</div>
        ${x.note ? `<div class="body">${esc(x.note)}</div>` : ""}
        <div class="muted" style="font-size:.85em">nubrėžta ${esc(String(x.created_at || "").slice(0, 16).replace("T", " "))}</div>
        <div style="display:flex;gap:6px;margin-top:6px"><button data-a="show">Rodyti sode</button><button data-a="del" class="danger">Ištrinti</button></div></div>`).join("")
        : '<p class="muted">Ryšių dar nenubrėžėte.</p>'}`;
    body.querySelectorAll("[data-r] [data-a]").forEach(b => b.onclick = async () => {
      const x = list.find(y => String(y.id) === b.closest("[data-r]").dataset.r);
      if (b.dataset.a === "del") {
        if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = "Tikrai? Ištrins iš duomenų bazės"; return; }
        await api("/api/sodas/rysiai/istrinti", {key: x.key});
        S.cy.edges().filter(e => (drawnRel(e) || {}).key === x.key).remove();
        saveGardenSoon(); toast("Ryšys ištrintas"); renderSettings();
        return;
      }
      // both nodes come into this garden, and the relationship with them
      closeSettings();
      const a = await addNode({id: x.a.id, label: x.a.label, key: x.a.key}, {select: false});
      const c = await addNode({id: x.b.id, label: x.b.label, key: x.b.key}, {select: false});
      await connectToGarden([x.a.id, x.b.id], undefined, true);
      if (a && c) { S.cy.$(":selected").unselect(); a.union(c).select(); S.cy.animate({fit: {eles: a.union(c), padding: 120}, duration: 250}); }
    });
  } else if (settingsSection === "log") {
    const entries = await api("/api/sodas/log");
    $("#logCount").textContent = entries.filter(e => e.level === "error").length || "";
    body.innerHTML = `<h3>Žurnalas</h3><p class="muted">Programos klaidos ir įspėjimai (ir naršyklėje įvykusios klaidos).</p>
      <div class="row"><button id="logRefresh">Atnaujinti</button><button id="logClear" class="danger" ${entries.length ? "" : "disabled"}>Valyti žurnalą</button>
      <label><input type="checkbox" id="logErr"> tik klaidos ir įspėjimai</label></div>
      <div id="logList">${entries.map(e => `<div class="log-entry" data-lvl="${esc(e.level)}"><span class="lvl ${esc(e.level)}">${esc(e.level)}</span>
        <span class="muted">${esc(e.at.replace("T", " ").slice(0, 19))} · ${esc(e.source)}</span><div>${esc(e.message)}</div>
        ${e.detail ? `<details><summary class="muted">išsamiau</summary><pre class="raw">${esc(e.detail)}</pre></details>` : ""}</div>`).join("") || '<p class="muted">Nesklandumų neužfiksuota.</p>'}</div>`;
    $("#logRefresh").onclick = renderSettings;
    if ($("#logClear")) $("#logClear").onclick = async e => {
      const b = e.target;
      if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = "Tikrai išvalyti?"; return; }
      await api("/api/sodas/log/clear", {});
      $("#logCount").textContent = "";
      renderSettings();
    };
    $("#logErr").onchange = e => $$("#logList .log-entry").forEach(x => x.hidden = e.target.checked && x.dataset.lvl === "info");
  }
}

// ---------------------------------------------------------------- boot
async function boot() {
  // loadGarden rewrites the address (?sodas=…): remember first whether the settings were asked for
  const startPath = location.pathname, startSection = new URLSearchParams(location.search).get("skiltis");
  await Kalba.ready;
  adoptSettings(await KalbaTheme.load());
  // the theme changed in another tab of this browser: this one follows (and will not save the old one back)
  KalbaTheme.onRemote(s => {
    if (!s || !s.theme || JSON.stringify(s.theme) === JSON.stringify(S.settings.theme)) return;
    S.settings.theme = cloneJson(s.theme);
    if (S.settingsFrom) S.settingsFrom.theme = cloneJson(s.theme);
    KalbaTheme.apply(S.settings, S.previewDark); restyle();
    if (settingsSection === "theme" && !$("#settings").hidden) renderSettings();
  });
  KalbaTheme.onChange(() => restyle());
  initCy();
  try { S.schema = await api("/api/sodas/schema"); } catch (e) { report("error", "Neo4j schema nepasiekiama: " + e.message); }
  await loadGarden(await initialGardenId());
  if (startPath === "/nustatymai") openSettings(SETTINGS_SECTIONS.has(startSection) ? startSection : undefined);
  syncToolbar();
  pollStatus(); setInterval(pollStatus, 30000);
  api("/api/sodas/log").then(l => { $("#logCount").textContent = l.filter(e => e.level === "error").length || ""; }).catch(() => {});

  const bibliography = async ev => { const b = ev.currentTarget; await saveGardenNow(); Kalba.bibliography(b, {sodas: S.garden.id}); };
  const acts = {export: toggleExportMenu, bib: bibliography, fit: fitAll, center: () => centerOn(), layout: relayout, path: () => findPath(), split: splitToGarden, map: toggleMap,
    basket: basketClick, basketMenu: toggleBasketMenu, types: toggleTypesPanel};
  // one drop-down at a time: a toolbar button closes the others
  const drops = {types: "#typesPanel", export: "#exportMenu", basketMenu: "#basketMenu"};
  $$("#toolbar [data-act]").forEach(b => b.onclick = ev => {
    ev.stopPropagation(); closeMenus();
    for (const [act, sel] of Object.entries(drops)) if (act !== b.dataset.act) $(sel).hidden = true;
    acts[b.dataset.act](ev);
  });
  // „Sodas“ in the menu and ⚙ in the bar's right-hand corner (drawn by bar.js, maybe later): garden ↔ settings here
  document.addEventListener("click", ev => {
    const a = ev.target.closest("[data-env]");
    if (!a || ev.ctrlKey || ev.metaKey || ev.button === 1) return;  // let the browser open another tab
    ev.preventDefault();
    a.dataset.env === "settings" ? openSettings() : closeSettings();
  });
  $$("#settingsNav a").forEach(a => a.onclick = () => openSettings(a.dataset.sec));
  const nameBox = $("#gardenName");
  nameBox.addEventListener("focus", showGardenList);
  nameBox.addEventListener("input", () => {
    S.garden.name = nameBox.value; document.title = pageTitle();
    saveGardenSoon(); showGardenList();
  });
  nameBox.addEventListener("keydown", ev => { if (ev.key === "Enter") nameBox.blur(); });
  nameBox.addEventListener("blur", () => setTimeout(() => { $("#gardens").hidden = true; }, 150));
  // ▾ shows every other garden without focusing the name; ＋ (a separate control) opens a new garden at once (Ctrl or middle button: in a new tab)
  $("#gardenList").addEventListener("mousedown", ev => { ev.preventDefault(); if ($("#gardens").hidden) showGardenList(true); else $("#gardens").hidden = true; });
  $("#gardenNew").addEventListener("click", ev => { $("#gardens").hidden = true; newGarden(ev.ctrlKey || ev.metaKey); });
  $("#gardenNew").addEventListener("auxclick", ev => { if (ev.button === 1) { ev.preventDefault(); newGarden(true); } });
  document.addEventListener("click", e => {
    if (!e.target.closest(".menu, .float, [data-act]")) closeMenus();
    if (!e.target.closest(".types-box")) $("#typesPanel").hidden = true;
    if (!e.target.closest(".basket-box")) $("#basketMenu").hidden = true;
    if (!e.target.closest(".export-box")) $("#exportMenu").hidden = true;
    if (!e.target.closest(".name-box")) $("#gardens").hidden = true;
  });
  $("#mapOpacity").addEventListener("input", e => { S.settings.map.opacity = Number(e.target.value); applyMapOpacity(); saveSettings(); });
  window.addEventListener("resize", () => { scheduleOverlay(); if (S.map.l) { S.map.l.invalidateSize({pan: false}); syncMapView(); } });
  window.addEventListener("pagehide", () => {
    if (S.garden.id) navigator.sendBeacon(`/api/sodas/gardens/${S.garden.id}`, new Blob([JSON.stringify(gardenSnapshot())], {type: "application/json"}));
  });
}
boot().catch(e => { report("error", "Sodo paleidimas nepavyko: " + e.message, e.stack); toast("Paleidimo klaida: " + e.message, "error", 10000); });
