"use strict";
/* Vaiva: spectral analysis studies of the basket of this tab's garden.
 * Left: the basket, the study with its parameters, the studies done so far. Right: the fruits of one study,
 * drawn by the renderer registered for its study id (RENDERERS). */

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[c]);
const fmt = (x, d = 2) => x == null || Number.isNaN(x) ? "–" : Number(x).toLocaleString(LOCALE, {minimumFractionDigits: d, maximumFractionDigits: d});
const pct = x => x == null ? "–" : `${Math.round(100 * x)} %`;
const V = {studies: [], runs: [], basket: [], gardenId: null, run: null, poll: null};

function toast(msg, level = "info", ms = 4500) {
  const el = document.createElement("div");
  el.className = "toast " + level;
  el.textContent = msg;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), ms);
}
async function api(path, body) {
  const opts = body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)};
  let r;
  try { r = await fetch(path, opts); } catch (e) { toast("Serveris nepasiekiamas", "error"); throw e; }
  const j = await r.json().catch(() => ({error: r.statusText}));
  if (!r.ok) { toast(j.error || r.statusText, r.status >= 500 ? "error" : "warning"); throw new Error(j.error || r.statusText); }
  return j;
}

// ---------------------------------------------------------------- colours (validated reference palette, see vaiva.css)
const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
/** Cluster i keeps its colour whatever else is shown; past 8 clusters: neutral, the number carries identity. */
const clusterColor = i => cssVar(i < 8 ? `--series-${i + 1}` : "--series-other") || "#888";

// ---------------------------------------------------------------- basket of this tab's garden
function gardenId() {
  const u = new URLSearchParams(location.search).get("sodas");
  if (u) return u;
  try { return sessionStorage.getItem("kalba.garden") || Kalba.lastGarden(); } catch (e) { return null; }
}
async function loadBasket() {
  V.gardenId = gardenId();
  V.basket = [];
  if (V.gardenId) {
    try { sessionStorage.setItem("kalba.garden", V.gardenId); } catch (e) { /* ignore */ }
    $("#navGarden").href = `/?sodas=${V.gardenId}`;
    const g = await api(`/api/sodas/gardens/${V.gardenId}`).catch(() => ({}));
    const byId = new Map((g.nodes || []).map(n => [n.data.id, n.data]));
    V.basket = (g.basket || []).map(id => byId.get(id)).filter(Boolean)
      .map(d => ({label: d.label, key: d.key, display_name: d.display_name || d.key, on: true}));
    $("#gardenOf").textContent = g.name ? `· ${g.name}` : "";
  }
  renderBasket();
}
const wsMode = () => document.body.classList.contains("ws-mode");
function renderBasket() {
  const study = wsMode() ? null : currentStudy(), ok = l => !study || study.accepts.includes(l);
  $("#basket").innerHTML = V.basket.length ? V.basket.map((b, i) => `<label class="bitem">
      <input type="checkbox" data-b="${i}" ${b.on && ok(b.label) ? "checked" : ""} ${ok(b.label) ? "" : "disabled"}>
      <span>${esc(b.display_name)}</span><span class="lbl">${esc(b.label)}${ok(b.label) ? "" : " – šiam tyrimui netinka"}</span></label>`).join("")
    : `<p class="muted small">Krepšys tuščias. Sode dešiniu pelės klavišu spauskite mazgą → „Pridėk į krepšį“ ir grįžkite čia.</p>`;
  if (study && study.basket_optional && !chosenNodes().length)
    $("#basket").insertAdjacentHTML("beforeend", `<p class="muted small">Šiam tyrimui krepšys nebūtinas: be jo tiriamos visos kalbos su kognatų duomenimis.</p>`);
  if (wsMode()) $("#basket").insertAdjacentHTML("beforeend", `<p class="muted small">Krepšį į sąranką įneša detalė „Krepšys“; be jos krepšys nenaudojamas.</p>`);
  $$("#basket [data-b]").forEach(cb => cb.onchange = () => { V.basket[cb.dataset.b].on = cb.checked; syncRunButton(); });
  syncRunButton();
}
const chosenNodes = () => { const s = wsMode() ? null : currentStudy(); return V.basket.filter(b => b.on && (!s || s.accepts.includes(b.label))); };
function syncRunButton() {
  $("#run").disabled = (!chosenNodes().length && !currentStudy()?.basket_optional) || !!V.poll;
  if ($("#wsRun")) $("#wsRun").disabled = !!V.poll;
}

// ---------------------------------------------------------------- studies and their parameters
const currentStudy = () => V.studies.find(s => s.id === $("#study").value);
/** What a parameter means and what it may be: shown under it by its „?“. */
function paramHelp(p) {
  const lim = p.type === "number" ? `Ribos: ${p.min}–${p.max}; numatyta: ${p.default ?? "tuščia"}${p.hint ? ` (${p.hint})` : ""}.`
    : p.type === "bool" ? `Numatyta: ${p.default ? "taip" : "ne"}.`
    : p.type === "select" ? `Galima: ${p.options.map(([, t]) => `„${t}“`).join(", ")}; numatyta: „${(p.options.find(([v]) => v === p.default) || [, ""])[1]}“.` : "";
  return `${esc(p.help || "")}<span class="lim">${esc(lim)}</span>`;
}
function renderStudy() {
  const s = currentStudy();
  if (!s) return;
  $("#studyText").innerHTML = esc(s.summary);
  $("#barNote").textContent = `Vaivos dirbtuvės – ${s.title}`;
  document.title = `${s.title} - Vaiva`;
  $("#params").innerHTML = s.params.map(p => `<div class="param-row"><div class="pl">${p.type === "bool"
    ? `<label class="param bool"><input type="checkbox" data-p="${p.name}" ${p.default ? "checked" : ""}> ${esc(p.label)}</label>`
    : p.type === "select" ? `<label class="param">${esc(p.label)}<select data-p="${p.name}">${p.options.map(([v, t]) =>
        `<option value="${esc(v)}" ${v === p.default ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`
    : `<label class="param">${esc(p.label)}<input type="number" data-p="${p.name}" min="${p.min}" max="${p.max}" value="${p.default ?? ""}"
        placeholder="${esc(p.hint || "")}"></label>`}
      <button type="button" class="help-btn" data-help="${p.name}" title="Ką reiškia šis parametras" aria-expanded="false">?</button></div>
      <div class="param-help" data-help-of="${p.name}" hidden>${paramHelp(p)}</div></div>`).join("");
  $$("#params [data-help]").forEach(b => b.onclick = () => {
    const box = $(`#params [data-help-of="${b.dataset.help}"]`);
    box.hidden = !box.hidden;
    b.classList.toggle("on", !box.hidden); b.setAttribute("aria-expanded", String(!box.hidden));
  });
  renderBasket();
}
function paramValues() {
  const out = {};
  $$("#params [data-p]").forEach(el => { out[el.dataset.p] = el.type === "checkbox" ? el.checked : el.tagName === "SELECT" ? el.value
    : (el.value === "" ? null : Number(el.value)); });
  return out;
}
async function startRun(params = paramValues(), nodes = chosenNodes()) {
  const s = currentStudy();
  if (!s || (!nodes.length && !s.basket_optional)) return;
  const r = await api("/api/vaiva/run", {study: s.id, nodes, params});
  follow(r.id);
}
/** Polls a running study until its fruits are ready, then shows them. */
function follow(id) {
  clearInterval(V.poll);
  const state = html => $$("#runState, #wsState").forEach(el => { el.innerHTML = html; });
  state(`<span class="spinner"></span>Pradedama…`);
  V.poll = setInterval(async () => {
    let r;
    try { r = await api(`/api/vaiva/runs/${id}`); } catch (e) { clearInterval(V.poll); V.poll = null; syncRunButton(); return; }
    if (r.status === "running") { state(`<span class="spinner"></span>${esc(r.progress || "")}`); return; }
    clearInterval(V.poll); V.poll = null; syncRunButton();
    state(r.status === "failed" ? `<span class="neg">${esc(r.error)}</span>` : "");
    await loadRuns();
    if (r.status === "completed") showRun(r);
  }, 700);
  syncRunButton();
}

// ---------------------------------------------------------------- studies done so far
async function loadRuns() {
  V.runs = (await api("/api/vaiva/runs")).runs;
  $("#runs").innerHTML = V.runs.map(r => `<div class="run-item ${r.status === "failed" ? "failed" : ""} ${V.run && V.run.id === r.id ? "active" : ""}" data-r="${esc(r.id)}">
      <span class="t" title="${esc(r.name)}">${esc(r.name)}</span>
      <span class="m">${esc((r.started_at || "").slice(0, 16).replace("T", " "))} · ${r.status === "failed" ? "nepavyko" : r.status === "running" ? "vyksta…"
        : r.study === "kalbu-medis" ? `${r.summary?.languages ?? "?"} kalbų, ρ ${fmt(r.summary?.rho)}`
        : r.study === "semantinis-pastovumas" ? `${r.summary?.concepts ?? "?"} sąvokų`
        : r.study === "dirbtuves" ? `🔧 ${r.summary?.fruits ?? "?"} vaisiai${r.summary?.errors ? `, ${r.summary.errors} su klaida` : ""}`
        : `${r.summary?.included ?? "?"} formų, ${r.summary?.clusters ?? "?"} gr.`}</span>
      <button class="x" data-del="${esc(r.id)}" title="Ištrinti tyrimą">×</button></div>`).join("") || '<p class="muted small">Dar nieko netyrėte.</p>';
  $$("#runs [data-r]").forEach(el => el.onclick = async ev => {
    if (ev.target.dataset.del) return;
    const r = await api(`/api/vaiva/runs/${el.dataset.r}`);
    if (r.status === "running") follow(r.id);
    else if (r.status === "failed") toast(r.error, "warning");
    else showRun(r);
  });
  $$("#runs [data-del]").forEach(b => b.onclick = async () => {
    if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = "trinti?"; return; }
    await api(`/api/vaiva/runs/${b.dataset.del}/delete`, {});
    if (V.run && V.run.id === b.dataset.del) { V.run = null; $("#result").innerHTML = ""; }
    loadRuns();
  });
}
function showRun(run) {
  V.run = run;
  history.replaceState(null, "", `/vaiva?tyrimas=${run.id}${V.gardenId ? `&sodas=${V.gardenId}` : ""}`);
  $$("#runs .run-item").forEach(el => el.classList.toggle("active", el.dataset.r === run.id));
  if (run.study !== "dirbtuves" && wsMode()) setMode("tyrimai");
  const draw = RENDERERS[run.study];
  $("#result").innerHTML = "";
  if (!draw) { $("#result").innerHTML = `<p class="muted">Šio tyrimo vaizdavimo nėra.</p>`; return; }
  draw(run, $("#result"));
  // every run keeps the datasets it used: its bibliography (SODAS and those datasets)
  const head = $("#result .r-head");
  if (head && !head.querySelector(".bib-btn")) {
    const b = document.createElement("button");
    b.className = "bib-btn";
    b.textContent = "📚 Bibliografija";
    b.title = "SODAS ir šiame tyrime naudoti duomenynai: BibTeX, RIS, CSL-JSON, tekstas";
    b.onclick = () => Kalba.bibliography(b, {tyrimas: run.id});
    head.append(b);
  }
}

// ---------------------------------------------------------------- tooltip
function tip(html, ev) {
  const t = $("#tip");
  if (!html) { t.hidden = true; return; }
  t.innerHTML = html;
  t.hidden = false;
  const x = Math.min(ev.clientX + 14, innerWidth - t.offsetWidth - 8), y = Math.min(ev.clientY + 14, innerHeight - t.offsetHeight - 8);
  t.style.left = x + "px"; t.style.top = y + "px";
}

// ---------------------------------------------------------------- small SVG charts
/** Dots on a 0-based y axis; ``mark``: index drawn stronger. Hover shows ``label(i)``. */
function dotChart({values, xLabel, yMax, mark, label, height = 180}) {
  const w = 420, h = height, L = 34, B = 26, T = 8, R = 8, n = values.length;
  const x = i => L + (w - L - R) * (n > 1 ? i / (n - 1) : .5), y = v => T + (h - T - B) * (1 - v / yMax);
  const ticks = [0, yMax / 2, yMax];
  return `<svg viewBox="0 0 ${w} ${h}" role="img">
    ${ticks.map(t => `<line class="grid" x1="${L}" x2="${w - R}" y1="${y(t)}" y2="${y(t)}"/><text class="lab" x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${fmt(t, 1)}</text>`).join("")}
    ${values.map((v, i) => `<text class="lab" x="${x(i)}" y="${h - 8}" text-anchor="middle">${i + 1}</text>`).join("")}
    <text class="lab" x="${w - R}" y="${h - 8 - 12}" text-anchor="end">${esc(xLabel)}</text>
    ${values.map((v, i) => `<circle cx="${x(i)}" cy="${y(v)}" r="${i === mark ? 6 : 4.5}" fill="${i === mark ? cssVar("--series-2") : cssVar("--series-1")}"
        stroke="var(--panel)" stroke-width="2" data-tip="${esc(label(i))}"/>
      <rect x="${x(i) - 12}" y="${T}" width="24" height="${h - T - B}" fill="transparent" data-tip="${esc(label(i))}"/>`).join("")}
  </svg>`;
}
/** Up to two lines over k; the chosen k gets a vertical rule. */
function lineChart({xs, series, chosen, height = 180, xTip = k => `${k} grupės`, clickable = true, yMin, yMax}) {
  const w = 420, h = height, L = 34, B = 26, T = 8, R = 8;
  const all = series.flatMap(s => s.values.filter(v => v != null));
  const lo = yMin ?? Math.min(0, ...all), hi = yMax ?? Math.max(0.5, ...all);
  const x = i => L + (w - L - R) * i / Math.max(1, xs.length - 1), y = v => T + (h - T - B) * (1 - (v - lo) / (hi - lo));
  const ticks = [lo, 0, hi].filter((t, i, a) => a.indexOf(t) === i);
  const ci = xs.indexOf(chosen);
  return `<svg viewBox="0 0 ${w} ${h}" role="img">
    ${ticks.map(t => `<line class="grid" x1="${L}" x2="${w - R}" y1="${y(t)}" y2="${y(t)}"/><text class="lab" x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${fmt(t, 1)}</text>`).join("")}
    ${xs.map((k, i) => `<text class="lab" x="${x(i)}" y="${h - 8}" text-anchor="middle">${k}</text>`).join("")}
    ${ci >= 0 ? `<line x1="${x(ci)}" x2="${x(ci)}" y1="${T}" y2="${h - B}" stroke="var(--muted)" stroke-width="1"/>` : ""}
    ${series.map(s => `<polyline fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" points="${s.values.map((v, i) => v == null ? "" : `${x(i)},${y(v)}`).join(" ")}"/>
      ${s.values.map((v, i) => v == null ? "" : `<circle cx="${x(i)}" cy="${y(v)}" r="${xs[i] === chosen ? 5 : 3}" fill="${s.color}" stroke="var(--panel)" stroke-width="2"/>`).join("")}`).join("")}
    ${xs.map((k, i) => `<rect x="${x(i) - 14}" y="${T}" width="28" height="${h - T - B}" fill="transparent" ${clickable ? `data-k="${k}" style="cursor:pointer"` : ""}
        data-tip="${esc(`<b>${xTip(k)}</b><br>` + series.map(s => `${s.name}: ${fmt(s.values[i], 3)}`).join("<br>"))}"/>`).join("")}
  </svg>`;
}
function bindTips(root) {
  root.querySelectorAll("[data-tip]").forEach(el => {
    el.addEventListener("mousemove", ev => tip(el.dataset.tip, ev));
    el.addEventListener("mouseleave", () => tip(null));
  });
}
/** A table whose columns sort on click; ``rows`` are arrays of {html, v} (v: sort value). */
function sortableTable(el, head, rows) {
  let by = -1, dir = 1;
  const draw = () => {
    const rs = by < 0 ? rows : [...rows].sort((a, b) => { const x = a[by].v, y = b[by].v; return (x > y ? 1 : x < y ? -1 : 0) * dir; });
    el.innerHTML = `<table class="t"><thead><tr>${head.map((h, i) => `<th class="sort ${h.n ? "n" : ""}" data-i="${i}">${esc(h.t)}${by === i ? (dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead>
      <tbody>${rs.map(r => `<tr>${r.map((c, i) => `<td class="${head[i].n ? "n" : ""}">${c.html}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    el.querySelectorAll("th[data-i]").forEach(th => th.onclick = () => { const i = +th.dataset.i; dir = by === i ? -dir : 1; by = i; draw(); });
  };
  draw();
}
const cell = (html, v) => ({html, v: v ?? html});

// ---------------------------------------------------------------- study renderers
const RENDERERS = {"garsiniai-klasteriai": renderSoundClusters, "kalbu-medis": renderTreeFit, "semantinis-pastovumas": renderStability};

function renderSoundClusters(run, root) {
  const R = run.result, S = R.summary, F = R.forms, C = R.clusters;
  const find = id => R.findings.find(f => f.id === id);
  const finding = f => f ? `<div class="finding ${f.cluster != null ? "cluster" : ""}" ${f.cluster != null ? `style="--c:${clusterColor(f.cluster)}"` : ""}>
      <h4>${f.cluster != null ? `<span class="num" style="--c:${clusterColor(f.cluster)}">${f.cluster + 1}</span> ` : ""}${esc(f.title)}</h4><p>${esc(f.text)}</p></div>` : "";
  const num = c => `<span class="num" style="--c:${clusterColor(c)}">${c + 1}</span>`;
  const date = (run.finished_at || run.started_at || "").slice(0, 16).replace("T", " ");
  const inputs = R.input.used.map(n => `${esc(n.display_name || n.key)} <span class="muted">(${esc(n.label)}, ${n.forms} f.)</span>`).join(", ");
  root.innerHTML = `<div class="viz-root">
    <div class="r-head"><h1>${esc(run.name)}</h1>
      <div class="sub">${esc(R.title)} · ${esc(date)} · ${inputs}${R.input.ignored.length ? ` · netinkami: ${R.input.ignored.map(n => esc(n.display_name || n.key)).join(", ")}` : ""}</div></div>
    <div class="tiles">
      <div class="tile"><div class="v">${S.included} / ${S.forms}</div><div class="l">formų ištirta</div></div>
      <div class="tile"><div class="v">${S.clusters}</div><div class="l">garsinių grupių${S.clusters !== S.k_auto ? ` (pati analizė siūlė ${S.k_auto})` : ""}</div></div>
      <div class="tile"><div class="v">${fmt(S.silhouette)}</div><div class="l">vidutinis siluetas</div></div>
      <div class="tile"><div class="v">${fmt(S.ari_cognate)}</div><div class="l">ARI su kognatais</div></div>
      <div class="tile"><div class="v">${pct(S.purity)}</div><div class="l">grupių grynumas</div></div>
    </div>

    <div class="block"><h2>Garsinis sodas</h2>
      <div class="split"><div>
        <div class="toolbar"><button id="toGarden">Atverti sode</button>
          <label class="small"><input type="checkbox" id="nnEdges" checked> artimiausio kaimyno ryšiai</label>
          <label class="small"><input type="checkbox" id="lbls" checked> užrašai</label>
          <span class="muted small">Kuo arčiau formos, tuo panašiau jos skamba. Užvedus – formos duomenys.</span></div>
        <div class="chips" id="legend">${C.map(c => `<span class="chip" data-c="${c.id}">${num(c.id)} „${esc(c.medoid_name)}“ · ${c.size}</span>`).join("")}
          <span class="muted small">spustelėjus – paryškinti grupę</span></div>
        <div id="gcy"></div></div>
        <div>${finding(find("coverage"))}${finding(find("border"))}</div></div></div>

    <div class="block"><h2>Kiek grupių?</h2>
      <div class="split"><div class="charts">
        <div class="chart card"><h3>Laplaso matricos savosios reikšmės</h3>
          <p class="cap">Didelis šuolis po k-osios reikšmės rodo, kad duomenys skyla į k grupių. Oranžinė – pasirinktas k.</p>
          ${dotChart({values: R.spectrum.eigenvalues.slice(0, 14), xLabel: "eilės nr.", yMax: Math.max(1, ...R.spectrum.eigenvalues.slice(0, 14)),
            mark: S.clusters - 1, label: i => `<b>${i + 1}-oji savoji reikšmė</b><br>${fmt(R.spectrum.eigenvalues[i], 3)}${i ? `<br>šuolis nuo ankstesnės: ${fmt(R.spectrum.eigenvalues[i] - R.spectrum.eigenvalues[i - 1], 3)}` : ""}`})}</div>
        <div class="chart card"><h3>Kokybė pagal grupių skaičių</h3>
          <p class="cap">Siluetas – kiek grupės atsiskyrusios; ARI – kiek sutampa su IE-CoR kognatais. Spustelėkite k, kad perskaičiuotumėte.</p>
          ${lineChart({xs: R.scan.map(s => s.k), chosen: S.clusters, series: [
            {name: "siluetas", color: cssVar("--series-1"), values: R.scan.map(s => s.silhouette)},
            {name: "ARI su kognatais", color: cssVar("--series-2"), values: R.scan.map(s => s.ari_cognate)}]})}
          <div class="legend"><span><i style="background:${cssVar("--series-1")}"></i>siluetas</span><span><i style="background:${cssVar("--series-2")}"></i>ARI su kognatais</span></div></div>
      </div><div>${finding(find("k"))}</div></div></div>

    <div class="block"><h2>Grupės</h2>
      <div class="split"><div id="clusterCards"></div><div>${finding(find("purity"))}${finding(find("cognacy"))}</div></div></div>

    ${R.matrix ? `<div class="block"><h2>Atstumų matrica</h2>
      <div class="split"><div class="card"><p class="cap muted small">Formos surikiuotos pagal grupes (spalvota juosta kairėje ir viršuje). Tamsiau – panašiau skamba.
        Ryškūs tamsūs kvadratai įstrižainėje – vieningos grupės; tamsios dėmės už jų – panašumas tarp grupių.</p>
        <canvas id="heat"></canvas>
        <div class="legend"><span>atstumas 0</span><span style="flex:0 0 160px;height:10px;border-radius:3px;background:linear-gradient(90deg,${cssVar("--seq-700")},${cssVar("--seq-400")},${cssVar("--seq-100")})"></span><span>1</span></div></div>
      <div>${finding(find("method"))}</div></div></div>` : ""}

    <div class="block"><h2>Grupės, kognatai ir kalbų šakos</h2>
      <div class="split"><div><h3 class="small muted">Kiek kiekvienos grupės formų priklauso kognatų grupei</h3><div class="tablebox" id="ctCog"></div>
        <h3 class="small muted" style="margin-top:14px">Kiek kiekvienos grupės formų yra iš kalbų šakos (Glottolog)</h3><div class="tablebox" id="ctBr"></div></div>
      <div>${finding(find("branches"))}</div></div></div>

    <div class="block"><h2>Visos ištirtos formos</h2>
      <div class="toolbar"><input type="search" id="formFilter" placeholder="filtruoti: forma, kalba, šaka, kognatas…"></div>
      <div class="tablebox" id="formsTable"></div></div>

    <div class="block"><h2>Neįtrauktos formos (${R.excluded.length})</h2>
      <div class="tablebox" id="exTable"></div></div>

    <div class="block"><h2>Garsai ir CLTS</h2>
      <div class="split"><div class="tablebox" id="soundTable"></div><div>${finding(find("sounds"))}</div></div></div>
  </div>`;

  // cluster cards
  $("#clusterCards").innerHTML = C.map(c => {
    const f = find(`cluster-${c.id}`);
    return finding(f) + `<details class="members"><summary>${c.size} formos</summary>
      <table class="t">${c.members.map(i => F[i]).map(x => `<tr><td>${esc(x.name)}</td><td class="muted">${esc(x.language || "")}</td>
        <td class="mono">${esc(x.segments)}</td><td class="muted">${esc(x.cognate || "")}</td></tr>`).join("")}</table></details>`;
  }).join("");

  // contingency tables: cluster × cognate / branch, cells shaded by share of the row
  const ct = (el, t) => {
    const max = Math.max(1, ...t.rows.flat());
    el.innerHTML = `<table class="t heat"><thead><tr><th>grupė</th>${t.columns.map(c => `<th class="n">${esc(c)}</th>`).join("")}</tr></thead><tbody>
      ${t.rows.map((row, i) => `<tr><td>${num(C[i].id)} „${esc(C[i].medoid_name)}“</td>${row.map(v => `<td class="n" style="background:${v
        ? `color-mix(in srgb, ${cssVar("--seq-400")} ${Math.round(12 + 60 * v / max)}%, transparent)` : "transparent"}">${v || ""}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  };
  ct($("#ctCog"), R.contingency.cognates);
  ct($("#ctBr"), R.contingency.branches);

  // forms
  const SRC = {segments: "Segments", phonemic_segments: "Phonemic_Segments", orthography: "orthography.tsv"};
  const formRows = F.map((f, i) => ({i, text: [f.name, f.language, f.branch, f.cognate, f.segments].join(" ").toLowerCase(), row: [
    cell(`${esc(f.name)}${f.reconstructed ? " <span class='muted'>(*)</span>" : ""}`, f.name), cell(esc(f.language || ""), f.language || ""),
    cell(esc(f.branch || ""), f.branch || ""), cell(`<span class="mono">${esc(f.variants_text.join(" | "))}</span>`, f.segments),
    cell(esc(SRC[f.source] || f.source), f.source), cell(num(f.cluster), f.cluster),
    cell(`<span class="${f.silhouette < 0 ? "neg" : ""}">${fmt(f.silhouette)}</span>`, f.silhouette), cell(esc(f.cognate || ""), f.cognate || "")]}));
  const formHead = [{t: "forma"}, {t: "kalba"}, {t: "šaka"}, {t: "analizės segmentai"}, {t: "segmentų šaltinis"}, {t: "grupė", n: 1}, {t: "siluetas", n: 1}, {t: "kognatų grupė"}];
  const drawForms = q => sortableTable($("#formsTable"), formHead, formRows.filter(r => !q || r.text.includes(q)).map(r => r.row));
  drawForms("");
  $("#formFilter").oninput = e => drawForms(e.target.value.trim().toLowerCase());

  sortableTable($("#exTable"), [{t: "forma"}, {t: "kalba"}, {t: "priežastis"}, {t: "paaiškinimas"}],
    R.excluded.map(e => [cell(esc(e.name), e.name), cell(esc(e.language || ""), e.language || ""), cell(esc(e.reason)), cell(`<span class="muted">${esc(e.detail || "")}</span>`, e.detail || "")]));
  const VIA = {bipa: "BIPA", system: "kita CLTS sistema", approx: "apytiksliai", unknown: "neatpažintas"};
  const viaRank = {unknown: 0, approx: 1, system: 2, bipa: 3};
  sortableTable($("#soundTable"), [{t: "segmentas"}, {t: "CLTS garsas"}, {t: "kaip rastas"}, {t: "kartų", n: 1}],
    [...R.sounds].sort((a, b) => viaRank[a.via] - viaRank[b.via] || b.count - a.count).map(s => [
      cell(`<span class="mono">${esc(s.symbol)}</span>`, s.symbol), cell(esc(s.name || "–"), s.name || ""),
      cell(esc(VIA[s.via]) + (s.base ? ` <span class="muted">(kaip ${esc(s.base)})</span>` : s.systems?.length ? ` <span class="muted">(${esc(s.systems.slice(0, 3).join(", "))})</span>` : ""), viaRank[s.via]),
      cell(String(s.count), s.count)]));

  if (R.matrix) drawHeat($("#heat"), R, F);
  bindTips(root);
  root.querySelectorAll("[data-k]").forEach(el => el.addEventListener("click", () => {
    const k = +el.dataset.k;
    if (k === S.clusters) return;
    toast(`Perskaičiuojama su ${k} grupėmis…`);
    startRun({...R.params, k}, R.input.used.map(({label, key, display_name}) => ({label, key, display_name})));
  }));
  drawGarden(R);
  $("#toGarden").onclick = () => openInGarden(run);
}

// ---------------------------------------------------------------- study „Kalbų leksinis artumas ir genealoginis medis“
function renderTreeFit(run, root) {
  const R = run.result, S = R.summary, L = R.languages, B = R.branches;
  const find = id => R.findings.find(f => f.id === id);
  const bIndex = new Map(B.map((b, i) => [b, i]));
  const bColor = b => clusterColor(bIndex.get(b) ?? 99);
  const swatch = b => `<span class="sw" style="background:${bColor(b)}"></span>`;
  const finding = f => f ? `<div class="finding"><h4>${esc(f.title)}</h4><p>${esc(f.text)}</p></div>` : "";
  const date = (run.finished_at || run.started_at || "").slice(0, 16).replace("T", " ");
  const scope = R.input.scope.length ? R.input.scope.map(n => `${esc(n.display_name || n.key)} <span class="muted">(${n.languages} k.)</span>`).join(", ") : "visos kalbos su kognatų duomenimis";
  const MEASURE = {ancestor: "bendro protėvio gylis", edges: "briaunų skaičius"};
  const legend = `<div class="chips">${B.map(b => `<span class="chip static">${swatch(b)}${esc(b)} · ${L.filter(l => l.branch === b).length}</span>`).join("")}</div>`;
  root.innerHTML = `<div class="viz-root">
    <div class="r-head"><h1>${esc(run.name)}</h1>
      <div class="sub">${esc(R.title)} · ${esc(date)} · ${scope}${R.input.meaning_filter ? ` · ${R.input.meaning_filter} reikšmės iš krepšio sąvokų` : ""}
        · ${esc(MEASURE[R.params.measure])}, ≥ ${R.params.min_overlap} bendrų reikšmių</div></div>
    <div class="tiles">
      <div class="tile"><div class="v">${S.languages}</div><div class="l">kalbų${S.excluded ? ` (${S.excluded} neįtraukta)` : ""}</div></div>
      <div class="tile"><div class="v">${fmt(S.rho)}</div><div class="l">ρ medis ↔ žodynas${S.p_value != null ? ` · p = ${fmt(S.p_value, 3)}` : ""}</div></div>
      <div class="tile"><div class="v">${S.clusters}</div><div class="l">leksinės grupės</div></div>
      <div class="tile"><div class="v">${S.best_level ? fmt(S.best_level.ari_lexical) : "–"}</div><div class="l">ARI su ${S.best_level ? S.best_level.level + "-uoju" : ""} medžio lygiu</div></div>
      <div class="tile"><div class="v">${R.branch_fit.filter(b => b.monophyletic && b.languages > 1).length} / ${R.branch_fit.filter(b => b.languages > 1).length}</div><div class="l">šakų vientisos leksiniame medyje</div></div>
    </div>

    <div class="block"><h2>Kalbų žemėlapiai: pagal žodyną ir pagal medį</h2>
      <p class="muted small">Kairėje – kalbos pagal žodyną (bendrų kognatų dalį), dešinėje – pagal Glottolog medį. Spalva – medžio šaka.
        Užvedus kalbą ji paryškinama abiejuose. „Atstumai“ išdėsto kalbas taip, kad atstumai ekrane kuo labiau atitiktų tikruosius (MDS);
        „Spektras“ – antrasis ir trečiasis normalizuoto Laplaso savieji vektoriai, kaip pirmajame bandyme.</p>
      <div class="toolbar"><label class="small"><input type="radio" name="maptype" value="mds" checked> atstumai (MDS)</label>
        <label class="small"><input type="radio" name="maptype" value="spectral"> spektras (savieji vektoriai)</label></div>
      ${legend}
      <div class="split"><div class="charts" id="maps"></div><div>${finding(find("coverage"))}${finding(find("clusters"))}</div></div></div>

    <div class="block"><h2>Kiek bendrų kognatų lieka einant medžiu tolyn</h2>
      <div class="split"><div class="chart card"><h3>Leksinis artumas pagal atstumą medyje</h3>
        <p class="cap">Kiekvienam atstumui – kalbų porų artumo dėžė: vidurinė pusė porų (nuo 25 iki 75 procentilio), linija – mediana, ūsai – mažiausias ir didžiausias.</p>
        ${boxPlot(R.by_distance)}</div>
      <div>${finding(find("rho"))}${finding(find("measure"))}${finding(find("decay"))}</div></div></div>

    <div class="block"><h2>Grupės ir medžio lygiai</h2>
      <div class="split"><div class="charts">
        <div class="chart card"><h3>Laplaso savosios reikšmės</h3>
          <p class="cap">Šuolis po k-osios reikšmės rodo k grupių. Spustelėkite k, kad perskaičiuotumėte su tiek grupių.</p>
          ${lineChart({xs: R.spectrum.lexical.map((_, i) => i + 1), chosen: S.clusters, xTip: k => `${k}-oji savoji reikšmė`, yMin: 0,
            series: [{name: "leksinis grafas", color: cssVar("--series-1"), values: R.spectrum.lexical},
                     {name: "medžio grafas", color: cssVar("--series-2"), values: R.spectrum.tree.slice(0, R.spectrum.lexical.length)}]})}
          <div class="legend"><span><i style="background:${cssVar("--series-1")}"></i>leksinis grafas</span><span><i style="background:${cssVar("--series-2")}"></i>medžio grafas</span></div></div>
        <div class="chart card"><h3>Kuriam medžio lygiui grupės artimiausios</h3>
          <p class="cap">ARI tarp ${S.clusters} leksinių grupių ir Glottolog šakų kiekviename lygyje žemiau bendro protėvio${R.ancestor ? ` (${esc(R.ancestor)})` : ""}.</p>
          ${lineChart({xs: R.levels.map(l => l.level), chosen: S.best_level?.level, clickable: false, yMin: 0, yMax: 1,
            xTip: k => { const l = R.levels.find(x => x.level === k); return `${k} lygis · ${l.clades} šakų<br><span class="muted">${esc(l.examples.join(", "))}</span>`; },
            series: [{name: "leksinės grupės", color: cssVar("--series-1"), values: R.levels.map(l => l.ari_lexical)},
                     {name: "medžio grafo grupės", color: cssVar("--series-2"), values: R.levels.map(l => l.ari_tree_spectrum)}]})}
          <div class="legend"><span><i style="background:${cssVar("--series-1")}"></i>leksinės grupės</span><span><i style="background:${cssVar("--series-2")}"></i>medžio grafo grupės</span></div></div>
      </div><div></div></div>
      <div class="split" style="margin-top:14px"><div id="clusterBars"></div><div></div></div></div>

    <div class="block"><h2>Leksinis medis</h2>
      <div class="split"><div class="card"><p class="cap muted small">Kalbos sujungtos pagal leksinį atstumą (UPGMA): kuo toliau į dešinę jungtis, tuo mažiau bendrų kognatų.
          Šakos linija spalvota, jei visos jos kalbos iš tos pačios Glottolog šakos.</p>
        <div class="dendro" id="dendro"></div></div>
      <div>${finding(find("tree"))}${finding(find("rootsplit"))}</div></div>
      <h3 class="small muted" style="margin-top:14px">Šakos: kiek bendrų kognatų viduje ir su kitomis šakomis</h3>
      <div class="tablebox" id="branchFit"></div></div>

    <div class="block"><h2>Leksinio artumo matrica</h2>
      <div class="split"><div class="card"><p class="cap muted small">Kalbos surikiuotos pagal Glottolog medį (spalvota juosta – šaka). Tamsiau – daugiau bendrų kognatų;
          tuščia – per mažai bendrų reikšmių. Tamsūs kvadratai įstrižainėje – šakos; tamsios dėmės už jų – artumas tarp šakų.</p>
        <canvas id="heat"></canvas>
        <div class="legend"><span>0 %</span><span style="flex:0 0 160px;height:10px;border-radius:3px;background:linear-gradient(90deg,${cssVar("--seq-100")},${cssVar("--seq-400")},${cssVar("--seq-700")})"></span><span>100 % bendrų kognatų</span></div></div>
      <div>${finding(find("closer"))}${finding(find("farther"))}</div></div></div>

    <div class="block"><h2>Netikėtos poros</h2>
      <div class="charts"><div><h3 class="small muted">Skirtingų šakų, bet leksiškai artimos (galimi kontaktai)</h3><div class="tablebox" id="closerT"></div></div>
        <div><h3 class="small muted">Tos pačios šakos, bet leksiškai tolimos</h3><div class="tablebox" id="fartherT"></div></div></div></div>

    <div class="block"><h2>Kalbos</h2>
      <div class="split"><div><div class="toolbar"><input type="search" id="langFilter" placeholder="filtruoti: kalba, šaka…"></div>
        <div class="tablebox" id="langTable"></div></div><div>${finding(find("misfits"))}</div></div></div>

    ${R.excluded.length ? `<div class="block"><h2>Neįtrauktos kalbos (${R.excluded.length})</h2><div class="tablebox" id="exTable"></div></div>` : ""}
    <div class="block"><h2>Metodas</h2><div class="split"><div>${finding(find("method"))}</div><div></div></div></div>
  </div>`;

  const drawMaps = (type, bind = true) => {
    const [a, b, c, d] = type === "mds" ? ["mx", "my", "hx", "hy"] : ["lx", "ly", "gx", "gy"];
    $("#maps").innerHTML = `<div class="chart card"><h3>Pagal žodyną</h3>${scatter(L, a, b, "lexmap")}</div>
      <div class="chart card"><h3>Pagal medį</h3>${scatter(L, c, d, "treemap")}</div>`;
    if (bind) bindTips($("#maps"));
    $("#maps").querySelectorAll("[data-li]").forEach(el => {
      el.addEventListener("mouseenter", () => root.querySelectorAll(`[data-li="${el.dataset.li}"]`).forEach(x => x.classList.add("hl")));
      el.addEventListener("mouseleave", () => root.querySelectorAll(".hl").forEach(x => x.classList.remove("hl")));
    });
  };
  drawMaps("mds", false);
  root.querySelectorAll("input[name=maptype]").forEach(r => r.onchange = () => drawMaps(r.value));

  // group composition: one bar per lexical group, split by tree branch
  const maxSize = Math.max(...R.clusters.map(c => c.size));
  $("#clusterBars").innerHTML = R.clusters.map(c => {
    const f = find(`cluster-${c.id}`);
    return `<div class="finding"><h4><span class="num plain">${c.id + 1}</span> ${esc(f ? f.title : "")}</h4>
      <div class="bar" style="width:${Math.max(8, 100 * c.size / maxSize)}%">${c.branches.map(([b, n]) =>
        `<span style="flex:${n};background:${bColor(b)}" data-tip="${esc(`<b>${b}</b><br>${n} iš ${c.size} grupės kalbų`)}"></span>`).join("")}</div>
      <p>${esc(f ? f.text : "")}</p></div>`;
  }).join("");

  drawDendrogram($("#dendro"), R, bColor);
  sortableTable($("#branchFit"), [{t: "šaka"}, {t: "kalbų", n: 1}, {t: "viduje", n: 1}, {t: "su kitomis", n: 1}, {t: "leksiniame medyje"}],
    R.branch_fit.map(b => [cell(`${swatch(b.branch)}${esc(b.branch)}`, b.branch), cell(String(b.languages), b.languages),
      cell(pct(b.within), b.within ?? -1), cell(pct(b.between), b.between ?? -1),
      cell(b.monophyletic ? "vientisa" : `įsiterpia: ${esc(b.intruders.slice(0, 5).map(i => L[i].name).join(", "))}${b.intruders.length > 5 ? "…" : ""}`, b.monophyletic ? 1 : 0)]));
  drawSimilarityHeat($("#heat"), R, bColor);
  const pairRows = list => list.map(x => [cell(`${swatch(L[x.a].branch)}${esc(L[x.a].name)}`, L[x.a].name), cell(`${swatch(L[x.b].branch)}${esc(L[x.b].name)}`, L[x.b].name),
    cell(pct(x.similarity), x.similarity), cell(pct(x.expected), x.expected), cell(String(x.distance), x.distance), cell(String(x.meanings), x.meanings)]);
  const pairHead = [{t: "kalba"}, {t: "kalba"}, {t: "artumas", n: 1}, {t: "tikėtasi", n: 1}, {t: "atstumas medyje", n: 1}, {t: "bendrų reikšmių", n: 1}];
  sortableTable($("#closerT"), pairHead, pairRows(R.closer));
  sortableTable($("#fartherT"), pairHead, pairRows(R.farther));
  const langRows = L.map(l => ({text: [l.name, l.branch, l.subbranch].join(" ").toLowerCase(), row: [
    cell(`${swatch(l.branch)}${esc(l.name)}`, l.name), cell(esc(l.branch), l.branch), cell(esc(l.subbranch), l.subbranch),
    cell(String(l.meanings), l.meanings), cell(`<span class="${l.fit != null && l.fit < 0.3 ? "neg" : ""}">${fmt(l.fit)}</span>`, l.fit ?? 9),
    cell(`<span class="num plain">${l.cluster + 1}</span>`, l.cluster),
    cell(l.lex_neighbor != null ? `${esc(L[l.lex_neighbor].name)} <span class="muted">${pct(l.lex_neighbor_sim)} · medyje ${l.lex_neighbor_distance ?? "–"}</span>` : "–",
      l.lex_neighbor != null ? L[l.lex_neighbor].name : ""),
    cell(l.tree_neighbors.map(j => esc(L[j].name)).join(", ") || "–", l.tree_neighbors.length ? L[l.tree_neighbors[0]].name : "")]}));
  const langHead = [{t: "kalba"}, {t: "šaka"}, {t: "pošakis"}, {t: "reikšmių", n: 1}, {t: "atitikimas γ", n: 1}, {t: "grupė", n: 1},
    {t: "artimiausia pagal žodyną"}, {t: "artimiausios medyje"}];
  const drawLangs = q => sortableTable($("#langTable"), langHead, langRows.filter(r => !q || r.text.includes(q)).map(r => r.row));
  drawLangs("");
  $("#langFilter").oninput = e => drawLangs(e.target.value.trim().toLowerCase());
  if (R.excluded.length) sortableTable($("#exTable"), [{t: "kalba"}, {t: "priežastis"}, {t: "paaiškinimas"}],
    R.excluded.map(e => [cell(esc(e.name), e.name), cell(esc(e.reason)), cell(`<span class="muted">${esc(e.detail)}</span>`, e.detail)]));

  bindTips(root);   // the maps drawn now included; a redrawn map binds its own
  root.querySelectorAll("[data-k]").forEach(el => el.addEventListener("click", () => {
    const k = +el.dataset.k;
    if (k === S.clusters || k < 2) return;
    toast(`Perskaičiuojama su ${k} grupėmis…`);
    startRun({...R.params, k}, run.nodes || []);
  }));

  function scatter(items, kx, ky, id) {
    const w = 460, h = 380, P = 16, xs = items.map(l => l[kx]), ys = items.map(l => l[ky]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const X = v => P + (w - 2 * P) * (v - x0) / ((x1 - x0) || 1), Y = v => h - P - (h - 2 * P) * (v - y0) / ((y1 - y0) || 1);
    // name the languages at the edges of every branch cloud (selective direct labels)
    const named = new Set();
    for (const b of B) {
      const mine = items.map((l, i) => [l, i]).filter(([l]) => l.branch === b);
      if (!mine.length) continue;
      const cx = mine.reduce((a, [l]) => a + l[kx], 0) / mine.length, cy = mine.reduce((a, [l]) => a + l[ky], 0) / mine.length;
      named.add(mine.reduce((best, cur) => Math.hypot(cur[0][kx] - cx, cur[0][ky] - cy) < Math.hypot(best[0][kx] - cx, best[0][ky] - cy) ? cur : best)[1]);
    }
    return `<svg viewBox="0 0 ${w} ${h}" id="${id}" role="img">
      <rect x="0" y="0" width="${w}" height="${h}" fill="transparent"/>
      ${items.map((l, i) => `<circle cx="${X(l[kx])}" cy="${Y(l[ky])}" r="5" fill="${bColor(l.branch)}" stroke="var(--panel)" stroke-width="2" data-li="${i}"
          data-tip="${esc(`<b>${l.name}</b><br>${l.branch} › ${l.subbranch}<br>leksinė grupė ${l.cluster + 1} · ${l.meanings} reikšmių`)}"/>`).join("")}
      ${[...named].map(i => `<text class="lab ink" x="${X(items[i][kx]) + 7}" y="${Y(items[i][ky]) - 6}">${esc(items[i].branch)}</text>`).join("")}
    </svg>`;
  }
  function boxPlot(bd) {
    const w = 640, h = 260, Lm = 40, Bm = 34, T = 10, R_ = 10, n = bd.length;
    const x = i => Lm + (w - Lm - R_) * (i + .5) / n, y = v => T + (h - T - Bm) * (1 - v), bw = Math.max(4, Math.min(26, (w - Lm - R_) / n * .6));
    return `<svg viewBox="0 0 ${w} ${h}" role="img">
      ${[0, .25, .5, .75, 1].map(t => `<line class="grid" x1="${Lm}" x2="${w - R_}" y1="${y(t)}" y2="${y(t)}"/><text class="lab" x="${Lm - 6}" y="${y(t) + 4}" text-anchor="end">${Math.round(t * 100)} %</text>`).join("")}
      ${bd.map((b, i) => `<g data-tip="${esc(`<b>atstumas ${b.distance}</b><br>${b.pairs} porų<br>mediana ${pct(b.median)} · vidurinė pusė ${pct(b.q1)}–${pct(b.q3)}<br>nuo ${pct(b.min)} iki ${pct(b.max)}`)}">
          <line x1="${x(i)}" x2="${x(i)}" y1="${y(b.max)}" y2="${y(b.min)}" stroke="var(--muted)" stroke-width="1"/>
          <rect x="${x(i) - bw / 2}" y="${y(b.q3)}" width="${bw}" height="${Math.max(1, y(b.q1) - y(b.q3))}" rx="3" fill="${cssVar("--series-1")}" opacity=".35"/>
          <line x1="${x(i) - bw / 2}" x2="${x(i) + bw / 2}" y1="${y(b.median)}" y2="${y(b.median)}" stroke="${cssVar("--series-1")}" stroke-width="2.5"/>
          <rect x="${x(i) - bw / 2 - 3}" y="${T}" width="${bw + 6}" height="${h - T - Bm}" fill="transparent"/>
          <text class="lab" x="${x(i)}" y="${h - Bm + 16}" text-anchor="middle">${b.distance}</text></g>`).join("")}
      <text class="lab" x="${w - R_}" y="${h - 4}" text-anchor="end">atstumas medyje (${esc(MEASURE[R.params.measure])})</text>
    </svg>`;
  }
}

// ---------------------------------------------------------------- study „Sąvokų semantinis pastovumas“
function renderStability(run, root) {
  const R = run.result, S = R.summary, C = R.concepts, K = R.components.filter(c => R.keys.includes(c.key));
  const byKey = Object.fromEntries(R.components.map(c => [c.key, c]));
  const find = id => R.findings.find(f => f.id === id);
  const finding = f => f ? `<div class="finding"><h4>${esc(f.title)}</h4><p>${esc(f.text)}</p></div>` : "";
  const date = (run.finished_at || run.started_at || "").slice(0, 16).replace("T", " ");
  const fields = [...new Set(C.map(c => c.field))].sort();
  // diverging: blue (pastovu) ↔ neutral ↔ red (judru), around the middle
  const div = t => t == null ? "transparent" : t >= .5
    ? `color-mix(in srgb, ${cssVar("--series-1")} ${Math.round(Math.min(1, (t - .5) * 2) * 70)}%, var(--chip))`
    : `color-mix(in srgb, ${cssVar("--series-8")} ${Math.round(Math.min(1, (.5 - t) * 2) * 70)}%, var(--chip))`;
  const bar = t => t == null ? `<span class="muted">–</span>` : `<span class="pbar"><i style="width:${Math.round(t * 100)}%"></i></span> ${Math.round(t * 100)}`;
  const opts = sel => K.map(c => `<option value="${c.key}" ${c.key === sel ? "selected" : ""}>${esc(c.side)}: ${esc(c.label)}</option>`).join("");
  const pca = R.pca;
  root.innerHTML = `<div class="viz-root">
    <div class="r-head"><h1>${esc(run.name)}</h1>
      <div class="sub">${esc(R.title)} · ${esc(date)}${R.input.scope.length ? " · " + R.input.scope.map(n => esc(n.display_name || n.key)).join(", ") : ""}
        ${R.params.include_derivation ? " · su derivacija" : ""}</div></div>
    <div class="tiles">
      <div class="tile"><div class="v">${S.concepts}</div><div class="l">sąvokų (${S.with_meaning} su reikšmių tinklu)</div></div>
      <div class="tile"><div class="v">${S.languages}</div><div class="l">IE-CoR kalbų, ${S.branches} šakos</div></div>
      <div class="tile"><div class="v">${S.families}</div><div class="l">kalbų šeimų reikšmių tinkle</div></div>
      <div class="tile"><div class="v">${pca ? pct(pca.explained[0]) : "–"}</div><div class="l">paaiškina viena bendra kryptis</div></div>
    </div>
    <div class="block"><div class="split"><div>${finding(find("coverage"))}</div><div></div></div></div>

    <div class="block"><h2>Forma ir reikšmė</h2>
      <div class="split"><div class="card">
        <div class="toolbar"><label class="small">X <select id="ax">${opts("replacement")}</select></label>
          <label class="small">Y <select id="ay">${opts("spectral")}</select></label>
          <label class="small">paryškinti lauką <select id="fieldSel"><option value="">—</option>${fields.map(f => `<option>${esc(f)}</option>`).join("")}</select></label></div>
        <p class="cap muted small">Abi ašys – pastovumo procentilis (dešinėje ir viršuje – pastoviau). Linijos dalija per pusę. Spustelėkite sąvoką – jos duomenys žemiau.</p>
        <div id="quad"></div>
        <div class="legend"><span><i style="background:${cssVar("--series-1")};height:8px;width:8px;border-radius:50%"></i>paryškintas laukas</span>
          <span><i style="background:${cssVar("--series-2")};height:8px;width:8px;border-radius:50%"></i>krepšio sąvokos</span>
          <span><i style="background:var(--muted);height:8px;width:8px;border-radius:50%"></i>kitos</span></div></div>
      <div>${finding(find("twokinds"))}${finding(find("quadrants"))}</div></div>
      <div id="detail" class="card detail-card" hidden></div></div>

    <div class="block"><h2>Komponentai atskirai</h2>
      <div class="comp-grid">${K.map(c => `<div class="finding"><h4>${esc(c.label)} <span class="muted small">(${esc(c.side)})</span></h4>
        <p>${esc((find("comp-" + c.key) || {}).text || c.explain)}</p></div>`).join("")}</div></div>

    <div class="block"><h2>Ar komponentai pasakoja tą patį?</h2>
      <div class="split"><div class="charts">
        <div class="chart card"><h3>Spearman koreliacijos tarp komponentų</h3><p class="cap">Mėlyna – kartu pastovu, raudona – priešingai, pilka – nesusiję.</p>
          <div class="tablebox" id="corrT"></div></div>
        ${pca ? `<div class="chart card"><h3>Pagrindinės komponentės</h3><p class="cap">Kiek bendros įvairovės paaiškina kiekviena kryptis; žemiau – kaip komponentai įeina į pirmąją.</p>
          ${pcaChart(pca)}</div>` : ""}
      </div><div>${finding(find("index"))}</div></div></div>

    <div class="block"><h2>Semantiniai laukai</h2>
      <div class="split"><div><p class="cap muted small">Vidutinis lauko sąvokų pastovumo procentilis kiekvienam komponentui. ● – reikšmingai pastovesnis ar judresnis už atsitiktinę imtį (p &lt; 0,05).</p>
        <div class="tablebox" id="fieldT"></div></div><div>${finding(find("fields"))}</div></div></div>

    ${R.findings.some(f => f.focus) ? `<div class="block"><h2>Krepšio sąvokos</h2><div class="comp-grid">${R.findings.filter(f => f.focus).map(finding).join("")}</div></div>` : ""}

    <div class="block"><h2>Visos sąvokos</h2>
      <div class="toolbar"><input type="search" id="conFilter" placeholder="filtruoti: sąvoka, laukas…"></div>
      <div class="tablebox" id="conT"></div></div>
    <div class="block"><h2>Metodas</h2><div class="split"><div>${finding(find("method"))}</div><div></div></div></div>
  </div>`;

  const drawQuad = () => {
    const ax = $("#ax").value, ay = $("#ay").value, field = $("#fieldSel").value;
    const w = 640, h = 440, P = 34, X = t => P + (w - 2 * P) * t, Y = t => h - P - (h - 2 * P) * t;
    const pts = C.filter(c => ax in c.pct && ay in c.pct);
    const col = c => c.focus ? cssVar("--series-2") : field && c.field === field ? cssVar("--series-1") : "var(--muted)";
    const front = c => c.focus || (field && c.field === field);
    const sorted = [...pts].sort((a, b) => front(a) - front(b));
    $("#quad").innerHTML = `<svg viewBox="0 0 ${w} ${h}" role="img">
      <line class="grid" x1="${X(.5)}" x2="${X(.5)}" y1="${Y(0)}" y2="${Y(1)}"/><line class="grid" x1="${X(0)}" x2="${X(1)}" y1="${Y(.5)}" y2="${Y(.5)}"/>
      <rect x="${P}" y="${P}" width="${w - 2 * P}" height="${h - 2 * P}" fill="none" stroke="var(--line)"/>
      <text class="lab" x="${X(1) - 4}" y="${Y(1) + 14}" text-anchor="end">pastovu abu</text>
      <text class="lab" x="${X(0) + 4}" y="${Y(1) + 14}">pastovu tik Y</text>
      <text class="lab" x="${X(1) - 4}" y="${Y(0) - 6}" text-anchor="end">pastovu tik X</text>
      <text class="lab" x="${X(0) + 4}" y="${Y(0) - 6}">judru abu</text>
      <text class="lab" x="${X(.5)}" y="${h - 8}" text-anchor="middle">${esc(byKey[ax].label)} →</text>
      <text class="lab" transform="translate(12 ${Y(.5)}) rotate(-90)" text-anchor="middle">${esc(byKey[ay].label)} →</text>
      ${sorted.map(c => `<circle cx="${X(c.pct[ax])}" cy="${Y(c.pct[ay])}" r="${front(c) ? 6 : 4}" fill="${col(c)}" opacity="${front(c) || !field ? 1 : .45}"
          stroke="var(--panel)" stroke-width="2" data-cid="${esc(c.cid)}" style="cursor:pointer"
          data-tip="${esc(`<b>${c.name}</b> · ${c.field}<br>${byKey[ax].label}: ${pct(c.pct[ax])}<br>${byKey[ay].label}: ${pct(c.pct[ay])}`)}"/>`).join("")}
      ${pts.filter(c => c.focus).map(c => `<text class="lab ink" x="${X(c.pct[ax]) + 8}" y="${Y(c.pct[ay]) - 6}">${esc(c.name)}</text>`).join("")}
    </svg>`;
    bindTips($("#quad"));
    $("#quad").querySelectorAll("[data-cid]").forEach(el => el.onclick = () => showConcept(el.dataset.cid));
  };
  ["#ax", "#ay", "#fieldSel"].forEach(sel => $(sel).onchange = drawQuad);
  drawQuad();

  // correlations
  $("#corrT").innerHTML = `<table class="t heat"><thead><tr><th></th>${R.keys.map(k => `<th class="n" title="${esc(byKey[k].label)}">${esc(byKey[k].label.split(" ")[0])}…</th>`).join("")}</tr></thead>
    <tbody>${R.keys.map((a, i) => `<tr><td>${esc(byKey[a].label)}</td>${R.corr[i].map((v, j) => `<td class="n" style="background:${i === j ? "transparent" : div(v == null ? null : (v + 1) / 2)}"
      data-tip="${esc(`${byKey[a].label} ↔ ${byKey[R.keys[j]].label}<br>ρ = ${fmt(v)}`)}">${i === j ? "" : fmt(v)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;

  // semantic fields × components
  $("#fieldT").innerHTML = `<table class="t heat"><thead><tr><th>laukas</th><th class="n">sąvokų</th>${R.keys.map(k => `<th class="n" title="${esc(byKey[k].label)}">${esc(byKey[k].label.split(" ")[0])}…</th>`).join("")}</tr></thead>
    <tbody>${R.fields.map(f => `<tr><td>${esc(f.field)}</td><td class="n">${f.concepts}</td>${R.keys.map(k => { const t = f.tests[k];
      if (!t) return `<td class="n muted">–</td>`;
      const sig = t.p_stable < .05 || t.p_mobile < .05;
      return `<td class="n" style="background:${div(t.mean)}" data-tip="${esc(`<b>${f.field}</b> · ${byKey[k].label}<br>vid. procentilis ${pct(t.mean)} (${t.n} sąvokų)<br>p pastovumui ${fmt(t.p_stable, 3)} · judrumui ${fmt(t.p_mobile, 3)}<br>${f.names.slice(0, 12).join(", ")}`)}">${sig ? "● " : ""}${Math.round(t.mean * 100)}</td>`; }).join("")}</tr>`).join("")}</tbody></table>`;

  // all concepts
  const rows = C.map(c => ({text: `${c.name} ${c.field}`.toLowerCase(), row: [
    cell(`${c.focus ? "🧺 " : ""}<a href="#" data-cid="${esc(c.cid)}">${esc(c.name)}</a>`, c.name), cell(esc(c.field), c.field),
    ...R.keys.map(k => cell(bar(c.pct[k]), c.pct[k] ?? -1))]}));
  const head = [{t: "sąvoka"}, {t: "laukas"}, ...R.keys.map(k => ({t: byKey[k].label, n: 1}))];
  const drawRows = q => sortableTable($("#conT"), head, rows.filter(r => !q || r.text.includes(q)).map(r => r.row));
  // one listener: sorting redraws the rows
  $("#conT").addEventListener("click", ev => { const a = ev.target.closest("[data-cid]"); if (a) { ev.preventDefault(); showConcept(a.dataset.cid); } });
  drawRows("");
  $("#conFilter").oninput = e => drawRows(e.target.value.trim().toLowerCase());
  bindTips(root);

  function showConcept(cid) {
    const c = C.find(x => x.cid === cid), f = c.form, m = c.meaning, el = $("#detail");
    const nameOf = id => (C.find(x => x.cid === id) || {}).name || id;
    el.hidden = false;
    el.innerHTML = `<h3>${esc(c.name)} <span class="muted small">${esc(c.field)} · Concepticon ${esc(c.cid)}</span></h3>
      <div class="charts">
        <div><h4 class="small muted">Pastovumo procentiliai</h4><table class="t">${R.components.map(k => `<tr><td>${esc(k.label)} <span class="muted small">(${esc(k.side)})</span></td>
          <td>${bar(c.pct[k.key])}</td><td class="n muted">${c.values[k.key] == null ? "" : fmt(c.values[k.key], 3)}</td></tr>`).join("")}</table></div>
        <div><h4 class="small muted">Forma: IE-CoR kognatų klasės</h4>${f ? `<table class="t">${f.class_list.map(x => `<tr><td>${esc(x.name)}</td>
            <td class="n">${x.languages} k.</td><td class="n">${x.branches} šak.</td></tr>`).join("")}</table>
          <p class="small muted">${f.languages} kalbos, ${f.classes} klasės, medyje bent ${f.changes} pakeitimai.
          ${f.colex_partners.length ? `Tas pats žodis reiškia ir: ${f.colex_partners.map(([p, n]) => `${esc(nameOf(p))} (${n} k.)`).join(", ")}.` : ""}</p>` : `<p class="muted">IE-CoR duomenų nėra.</p>`}</div>
        <div><h4 class="small muted">Reikšmė: DatSemShift kaimynai (šeimų skaičius)</h4>${m ? `<table class="t">${m.top_partners.map(x => `<tr><td>${esc(x.name)}</td><td class="n">${x.families}</td></tr>`).join("")}</table>
          <p class="small muted">Polisemija ${m.families} šeimose; daugiausia: ${esc(m.top_families.join(", "))}.</p>` : `<p class="muted">DatSemShift duomenų nėra.</p>`}</div>
      </div>`;
    el.scrollIntoView({behavior: "smooth", block: "nearest"});
  }

  function pcaChart(pc) {
    const w = 420, h = 230, L = 150, T = 6, bh = 16, gap = 6;
    const ex = pc.explained.slice(0, 5);
    const top = ex.map((v, i) => `<g data-tip="${esc(`${i + 1}-oji kryptis: ${pct(v)} įvairovės`)}"><text class="lab" x="${L - 8}" y="${T + i * (bh + gap) + 12}" text-anchor="end">${i + 1}-oji kryptis</text>
      <rect x="${L}" y="${T + i * (bh + gap)}" width="${Math.max(2, (w - L - 50) * v)}" height="${bh}" rx="4" fill="${cssVar("--series-1")}"/>
      <text class="lab ink" x="${L + Math.max(2, (w - L - 50) * v) + 6}" y="${T + i * (bh + gap) + 12}">${pct(v)}</text></g>`).join("");
    const y0 = T + 5 * (bh + gap) + 18, mid = L + (w - L - 50) / 2, half = (w - L - 50) / 2;
    const loads = R.keys.map((k, i) => { const v = pc.loadings[i], x = v >= 0 ? mid : mid + half * v;
      return `<g data-tip="${esc(`${byKey[k].label}: ${fmt(v)}`)}"><text class="lab" x="${L - 8}" y="${y0 + i * 14 + 10}" text-anchor="end">${esc(byKey[k].label)}</text>
        <rect x="${x}" y="${y0 + i * 14}" width="${Math.max(1, half * Math.abs(v))}" height="10" rx="3" fill="${cssVar(v >= 0 ? "--series-1" : "--series-8")}"/></g>`; }).join("");
    const H = y0 + R.keys.length * 14 + 6;
    return `<svg viewBox="0 0 ${w} ${H}" role="img">${top}<line class="grid" x1="${mid}" x2="${mid}" y1="${y0 - 4}" y2="${H - 2}"/>
      <text class="lab" x="${mid}" y="${y0 - 6}" text-anchor="middle">1-osios krypties svoriai</text>${loads}</svg>`;
  }
}

/** The lexical tree: leaves top to bottom in tree order, joins further right the less the vocabularies share. */
function drawDendrogram(el, R, bColor) {
  const L = R.languages, n = L.length, row = 12, labelW = 170, w = 720, T = 8, h = n * row + T * 2;
  const pos = new Map(R.leaf_order.map((leaf, i) => [leaf, i]));
  const maxH = Math.max(...R.tree.map(t => t[2]), 0.01);
  const X = v => labelW + 10 + (w - labelW - 20) * v / maxH;
  const node = new Map();   // id → {x, y, branch (if pure)}
  for (let i = 0; i < n; i++) node.set(i, {x: X(0), y: T + pos.get(i) * row + row / 2, branch: L[i].branch});
  let lines = "";
  R.tree.forEach(([a, b, height], t) => {
    const A = node.get(a), Bn = node.get(b), xh = X(height);
    const branch = A.branch && A.branch === Bn.branch ? A.branch : null;
    const col = branch ? bColor(branch) : "var(--muted)";
    lines += `<path d="M${A.x},${A.y}H${xh}M${Bn.x},${Bn.y}H${xh}M${xh},${A.y}V${Bn.y}" stroke="${col}" stroke-width="${branch ? 1.6 : 1}" fill="none"/>`;
    node.set(n + t, {x: xh, y: (A.y + Bn.y) / 2, branch});
  });
  const labels = R.leaf_order.map((leaf, i) => `<g data-tip="${esc(`<b>${L[leaf].name}</b><br>${L[leaf].branch} › ${L[leaf].subbranch}`)}">
      <rect x="${labelW - 2}" y="${T + i * row + 2}" width="8" height="8" rx="2" fill="${bColor(L[leaf].branch)}"/>
      <text class="lab ink" x="${labelW - 6}" y="${T + i * row + row / 2 + 4}" text-anchor="end" style="font-size:10px">${esc(L[leaf].name)}</text></g>`).join("");
  const ticks = [0, .25, .5, .75, 1].filter(t => t <= maxH + 1e-9);
  el.innerHTML = `<svg viewBox="0 0 ${w} ${h + 22}" role="img" style="width:100%;height:auto">${lines}${labels}
    ${ticks.map(t => `<text class="lab" x="${X(t)}" y="${h + 14}" text-anchor="middle">${Math.round((1 - t) * 100)} %</text>`).join("")}
    <text class="lab" x="${w - 4}" y="${h + 14}" text-anchor="end"> </text></svg>
    <p class="muted small">Ašis – bendrų kognatų dalis toje jungtyje.</p>`;
}

/** Share of cognate-coded meanings in common, languages in Glottolog order; empty – too few meanings in common. */
function drawSimilarityHeat(canvas, R, bColor) {
  const order = R.matrix.order, M = R.matrix.s, n = order.length, L = R.languages, strip = Math.max(3, Math.round(n / 40));
  canvas.width = n + strip; canvas.height = n + strip;
  const ctx = canvas.getContext("2d"), img = ctx.createImageData(n, n);
  const hex = h => { const m = h.replace("#", ""); return [0, 2, 4].map(i => parseInt(m.slice(i, i + 2), 16)); };
  const stops = [cssVar("--seq-100"), cssVar("--seq-400"), cssVar("--seq-700")].map(hex);
  const ramp = t => { const u = Math.min(1, Math.max(0, t)) * 2, k = Math.min(1, Math.floor(u)), f = u - k;
    return stops[k].map((x, i) => Math.round(x + (stops[k + 1][i] - x) * f)); };
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
    const v = M[i][j], p = 4 * (i * n + j);
    if (v == null) { img.data[p + 3] = 0; continue; }
    const [r, g, b] = ramp(v);
    img.data[p] = r; img.data[p + 1] = g; img.data[p + 2] = b; img.data[p + 3] = 255;
  }
  ctx.putImageData(img, strip, strip);
  order.forEach((li, k) => { ctx.fillStyle = bColor(L[li].branch); ctx.fillRect(0, strip + k, strip - 1, 1); ctx.fillRect(strip + k, 0, 1, strip - 1); });
  canvas.onmousemove = ev => {
    const r = canvas.getBoundingClientRect(), s = canvas.width / r.width;
    const j = Math.floor((ev.clientX - r.left) * s) - strip, i = Math.floor((ev.clientY - r.top) * s) - strip;
    if (i < 0 || j < 0 || i >= n || j >= n) return tip(null);
    const a = L[order[i]], b = L[order[j]], v = M[i][j];
    tip(`<b>${esc(a.name)}</b> ↔ <b>${esc(b.name)}</b><br>${v == null ? "per mažai bendrų reikšmių" : `${pct(v)} bendrų kognatų`}<br>${esc(a.branch)} · ${esc(b.branch)}`, ev);
  };
  canvas.onmouseleave = () => tip(null);
}

/** The forms placed by multidimensional scaling of their distances, coloured and numbered by group. */
function drawGarden(R) {
  const F = R.forms, scale = 420;
  const els = F.map((f, i) => ({group: "nodes", data: {id: "f" + i, i, name: f.name, c: f.cluster, color: clusterColor(f.cluster)},
    position: {x: f.x * scale, y: f.y * scale}}));
  F.forEach((f, i) => { const nb = f.neighbors[0]; if (nb && nb.d <= 0.35 && !(F[nb.i].neighbors[0]?.i === i && nb.i < i))
    els.push({group: "edges", data: {id: `e${i}`, source: "f" + i, target: "f" + nb.i, d: nb.d}}); });
  const ink = getComputedStyle(document.documentElement).getPropertyValue("--ink").trim() || "#222";
  const bg = getComputedStyle(document.documentElement).getPropertyValue("--graph-bg").trim() || "#fff";
  const line = getComputedStyle(document.documentElement).getPropertyValue("--line").trim() || "#ccc";
  const cy = cytoscape({container: $("#gcy"), elements: els, layout: {name: "preset", fit: true, padding: 30}, wheelSensitivity: .25,
    style: [
      {selector: "node", style: {"background-color": "data(color)", width: 12, height: 12, "border-width": 2, "border-color": bg,
        label: "data(name)", "font-size": 9, color: ink, "text-valign": "top", "text-margin-y": -3,
        "text-background-color": bg, "text-background-opacity": .7, "text-background-padding": 1}},
      {selector: "edge", style: {width: 1, "line-color": line, "curve-style": "straight", opacity: .8}},
      {selector: ".dim", style: {opacity: .12}},
      {selector: ".nolabel", style: {label: ""}},
    ]});
  cy.on("mouseover", "node", e => { const f = F[e.target.data("i")];
    tip(`<b>${esc(f.name)}</b> · ${esc(f.language || "")}<br><span class="mono">${esc(f.variants_text.join(" | "))}</span><br>
      grupė ${f.cluster + 1} · siluetas ${fmt(f.silhouette)}${f.cognate ? `<br>kognatai: ${esc(f.cognate)}` : ""}${f.branch ? `<br>šaka: ${esc(f.branch)}` : ""}
      <br>artimiausia: ${f.neighbors.map(n => `${esc(F[n.i].name)} (${fmt(n.d)})`).join(", ")}`, e.originalEvent); });
  cy.on("mousemove", "node", e => tip($("#tip").innerHTML, e.originalEvent));
  cy.on("mouseout", "node", () => tip(null));
  let focus = null;
  $$("#legend [data-c]").forEach(ch => ch.onclick = () => {
    const c = +ch.dataset.c;
    focus = focus === c ? null : c;
    $$("#legend [data-c]").forEach(x => x.classList.toggle("off", focus != null && +x.dataset.c !== focus));
    cy.nodes().forEach(n => n.toggleClass("dim", focus != null && n.data("c") !== focus));
    cy.edges().forEach(e => e.toggleClass("dim", focus != null && (e.source().data("c") !== focus || e.target().data("c") !== focus)));
  });
  $("#nnEdges").onchange = e => cy.edges().style("display", e.target.checked ? "element" : "none");
  $("#lbls").onchange = e => cy.nodes().toggleClass("nolabel", !e.target.checked);
}

/** Distance matrix as pixels (one per pair), ordered by group; a colour strip marks each group. */
function drawHeat(canvas, R, F) {
  const order = R.matrix.order, D = R.matrix.d, n = order.length, strip = Math.max(3, Math.round(n / 40));
  canvas.width = n + strip; canvas.height = n + strip;
  const ctx = canvas.getContext("2d"), img = ctx.createImageData(n, n);
  const hex = h => { const m = h.replace("#", ""); return [0, 2, 4].map(i => parseInt(m.slice(i, i + 2), 16)); };
  const stops = [cssVar("--seq-700"), cssVar("--seq-400"), cssVar("--seq-100")].map(hex);
  const ramp = t => { const u = Math.min(1, Math.max(0, t)) * 2, a = stops[Math.min(1, Math.floor(u))], b = stops[Math.min(2, Math.floor(u) + 1)], f = u - Math.floor(u);
    return a.map((x, i) => Math.round(x + (b[i] - x) * (u >= 2 ? 1 : f))); };
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
    const [r, g, b] = ramp(D[i][j]), p = 4 * (i * n + j);
    img.data[p] = r; img.data[p + 1] = g; img.data[p + 2] = b; img.data[p + 3] = 255;
  }
  ctx.putImageData(img, strip, strip);
  order.forEach((fi, k) => { ctx.fillStyle = clusterColor(F[fi].cluster); ctx.fillRect(0, strip + k, strip - 1, 1); ctx.fillRect(strip + k, 0, 1, strip - 1); });
  canvas.onmousemove = ev => {
    const r = canvas.getBoundingClientRect(), s = canvas.width / r.width;
    const j = Math.floor((ev.clientX - r.left) * s) - strip, i = Math.floor((ev.clientY - r.top) * s) - strip;
    if (i < 0 || j < 0 || i >= n || j >= n) return tip(null);
    const a = F[order[i]], b = F[order[j]];
    tip(`<b>${esc(a.name)}</b> ↔ <b>${esc(b.name)}</b><br>atstumas ${fmt(D[i][j])}<br>grupės ${a.cluster + 1} ir ${b.cluster + 1}`, ev);
  };
  canvas.onmouseleave = () => tip(null);
}

/** A new garden with these forms where the study placed them, coloured by group; opened in a new tab. */
async function openInGarden(run) {
  const R = run.result, tab = window.open("about:blank", "_blank");
  const {new_id} = await api("/api/sodas/gardens");
  const nodes = R.forms.map(f => ({data: {id: `Form|${f.key}`, label: "Form", key: f.key, display_name: f.name, dataset: f.dataset,
    caption: `${f.name.length > 36 ? f.name.slice(0, 35) + "…" : f.name} · ${f.cluster + 1}`, color: clusterColor(f.cluster), size: 30, degree: null, props: {},
    vaiva_cluster: f.cluster + 1}, position: {x: f.x * 900, y: f.y * 900}, classes: []}));
  await api(`/api/sodas/gardens/${new_id}`, {name: `Vaiva · ${run.name}`, nodes, edges: [], basket: [], typeVis: {}, labelHidden: {},
    unmerged: [], untwinned: []});
  if (tab) tab.location.href = `/?sodas=${new_id}`;
  toast(`Sukurtas sodas „Vaiva · ${run.name}“`);
}

/** ＋ as in the garden: a new garden for this tab – its basket is empty (saved once it gets content in the garden). */
const randomGardenId = () => [...crypto.getRandomValues(new Uint8Array(4))].map(b => b.toString(16).padStart(2, "0")).join("");
function newGarden(inNewTab) {
  const id = randomGardenId();
  if (inNewTab) { window.open(`/vaiva?sodas=${id}`, "_blank"); return; }
  history.replaceState(null, "", `/vaiva?sodas=${id}${V.run ? `&tyrimas=${V.run.id}` : ""}`);
  Kalba.rememberGarden(id);
  loadBasket();
  toast("Naujas sodas: krepšys tuščias. Mazgus į jį dėkite sode.");
}

// ---------------------------------------------------------------- boot
async function boot() {
  await Kalba.ready;
  $("#gardenNew").addEventListener("click", ev => newGarden(ev.ctrlKey || ev.metaKey));
  $("#gardenNew").addEventListener("auxclick", ev => { if (ev.button === 1) { ev.preventDefault(); newGarden(true); } });
  await KalbaTheme.load().catch(() => {});
  // charts take their colours when drawn: redraw once when light ↔ dark changes (not on every step of the glide)
  let dark = document.documentElement.dataset.theme;
  KalbaTheme.onChange(() => {
    const now = document.documentElement.dataset.theme;
    if (now !== dark) { dark = now; if (V.run) showRun(V.run); }
  });
  V.studies = (await api("/api/vaiva/studies")).studies.filter(s => !s.workshop);
  $("#study").innerHTML = V.studies.map(s => `<option value="${esc(s.id)}">${esc(s.title)}</option>`).join("");
  $("#study").onchange = renderStudy;
  $("#run").onclick = () => startRun();
  renderStudy();
  await loadBasket();
  await loadRuns();
  const ws = !!new URLSearchParams(location.search).get("dirbtuves");
  if (typeof Workshop !== "undefined") await Workshop.init().catch(e => console.error(e));
  const asked = new URLSearchParams(location.search).get("tyrimas");
  const wanted = asked || V.runs.find(r => r.status === "completed" && (r.study === "dirbtuves") === ws)?.id;
  if (!asked && typeof Workshop !== "undefined") Workshop.ws.keepDraft = true;
  if (wanted) {
    const r = await api(`/api/vaiva/runs/${wanted}`).catch(() => null);
    if (r && r.status === "completed") showRun(r); else if (r && r.status === "running") follow(r.id);
  }
}
boot();
