"use strict";
/* LKEŽDB: words of the etymological database explained by a language model and included in the Neo4j graph. */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[c]);
const L = {offset: 0, limit: 60, total: 0, current: null, picked: new Set(), status: null, missing: null};

function toast(msg, level = "info", ms = 5000) {
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
  if (!r.ok) { toast(j.error || r.statusText, r.status >= 500 ? "error" : "warning", 9000); throw new Error(j.error || r.statusText); }
  return j;
}
/** ⟨esmi⟩ (italics in LKEŽDB: a cited language form) shown as italics. */
const marked = t => esc(t).replace(/⟨([^⟩]*)⟩/g, "<i>$1</i>");
const modal = html => { $("#modalBody").innerHTML = html + `<div class="row"><button id="mClose">Uždaryti</button></div>`; $("#modal").hidden = false;
  $("#mClose").onclick = () => { $("#modal").hidden = true; }; };
const copy = text => navigator.clipboard.writeText(text).then(() => toast("Nukopijuota"), () => toast("Nukopijuoti nepavyko", "warning"));

// ---------------------------------------------------------------- tabs
$$(".tab").forEach(t => t.onclick = () => {
  $$(".tab").forEach(x => x.classList.toggle("active", x === t));
  $$("[data-pane]").forEach(p => p.hidden = p.dataset.pane !== t.dataset.tab);
  ({jobs: renderJobs, engine: renderEngine, neo4j: renderNeo4j})[t.dataset.tab]?.();
});

async function loadStatus() {
  L.status = await api("/api/lkezdb/status");
  if (!L.status.available) {
    $("#detail").innerHTML = `<p class="warn">Duomenų talpykla nerasta: <span class="mono">${esc(L.status.db)}</span></p>`;
    return false;
  }
  const s = L.status.stats;
  $("#stats").textContent = `${s.zodziai.toLocaleString(LOCALE)} žodžių · ${s.straipsniai.toLocaleString(LOCALE)} straipsnių · išaiškinta ${s.isaiskinta} · įtraukta ${s.itraukta}`;
  $("#qn").textContent = s.eileje ? `(${s.eileje})` : "";
  return true;
}

// ---------------------------------------------------------------- words
async function loadWords() {
  const q = encodeURIComponent($("#q").value.trim()), st = $("#status").value;
  const r = await api(`/api/lkezdb/words?q=${q}&status=${st}&offset=${L.offset}&limit=${L.limit}`);
  L.total = r.total;
  const badge = w => w.darbas === "running" ? `<span class="badge run">aiškinama…</span>` : w.darbas === "pending" ? `<span class="badge run">eilėje</span>`
    : w.itraukta ? `<span class="badge ok">Neo4j</span>` : w.isaiskinta ? `<span class="badge">išaiškinta</span>` : w.darbas === "failed" ? `<span class="badge err">klaida</span>` : "";
  $("#items").innerHTML = r.words.map(w => `<div class="item ${L.current === w.GUID ? "active" : ""}" data-g="${esc(w.GUID)}">
      <input type="checkbox" data-pick="${esc(w.GUID)}" ${L.picked.has(w.GUID) ? "checked" : ""}>
      <span>${esc(w.zodis)} <span class="n">${w.straipsniai}</span></span>${badge(w)}</div>`).join("") || `<p class="muted small" style="padding:10px">Nieko nerasta.</p>`;
  $("#page").textContent = `${L.total ? L.offset + 1 : 0}–${Math.min(L.total, L.offset + L.limit)} iš ${L.total.toLocaleString(LOCALE)}`;
  $$("#items [data-g]").forEach(el => el.onclick = ev => { if (ev.target.dataset.pick) return; openWord(el.dataset.g); });
  $$("#items [data-pick]").forEach(cb => cb.onchange = () => { cb.checked ? L.picked.add(cb.dataset.pick) : L.picked.delete(cb.dataset.pick); syncBulk(); });
  syncBulk();
}
const syncBulk = () => { $("#bulkExplain").disabled = !L.picked.size; $("#bulkExplain").textContent = `Išaiškinti pažymėtus${L.picked.size ? ` (${L.picked.size})` : ""}`; };
let qTimer;
$("#q").oninput = () => { clearTimeout(qTimer); qTimer = setTimeout(() => { L.offset = 0; loadWords(); }, 250); };
$("#status").onchange = () => { L.offset = 0; loadWords(); };
$("#prev").onclick = () => { if (L.offset > 0) { L.offset = Math.max(0, L.offset - L.limit); loadWords(); } };
$("#next").onclick = () => { if (L.offset + L.limit < L.total) { L.offset += L.limit; loadWords(); } };
$("#pickAll").onchange = e => { $$("#items [data-pick]").forEach(cb => { cb.checked = e.target.checked; e.target.checked ? L.picked.add(cb.dataset.pick) : L.picked.delete(cb.dataset.pick); }); syncBulk(); };
$("#bulkExplain").onclick = async () => {
  const n = L.picked.size;
  if (!confirm(`Išaiškinti ${n} žodž. kalbos modeliu? Kiekvienas žodis – atskira (mokama) užklausa.`)) return;
  await api("/api/lkezdb/explain", {words: [...L.picked], include: $("#bulkInclude").checked});
  toast(`${n} žodž. įdėta į eilę`); L.picked.clear(); loadWords(); loadStatus(); watchJobs();
};

async function openWord(guid) {
  L.current = guid;
  $$("#items .item").forEach(el => el.classList.toggle("active", el.dataset.g === guid));
  const w = await api(`/api/lkezdb/word/${guid}`), ex = w.explanation, planObj = ex && ex.grafo_importo_planas;
  const sem = ex && ex.semantinis_json, byArt = Object.fromEntries(((sem && sem.articles) || []).map(a => [a.GUID, a]));
  const warn = (ex && ex.ispejimai) || [];
  // opened from the garden, where this word's node had nothing to expand (?guid=…&truksta=1)
  const missing = L.missing === guid && !w.word.itraukta ? `<div class="card notice"><h3>Duomenų apie šį mazgą nėra</h3>
      Sodo mazgas „${esc(w.word.zodis)}“ išskleisti negalima: šio žodžio LKEŽDB straipsniai dar ${ex ? "išaiškinti, bet neįtraukti į Neo4j. Spauskite „Įtraukti į Neo4j“."
      : "neištraukti. Juos galima užklausti iš LKEŽDB su dirbtinio proto pagalba – spauskite „Išaiškinti“ (kalbos modelio užklausa mokama)."}
      Kai žodis bus įtrauktas, grįžkite į sodą ir išskleiskite mazgą dar kartą.</div>` : "";
  $("#detail").innerHTML = `${missing}<h1>${esc(w.word.zodis)}</h1>
    <div class="muted small">${w.articles.length} straipsn. · <a href="${esc(w.word.url)}" target="_blank" rel="noopener">LKEŽDB ↗</a>
      ${ex ? ` · išaiškinta ${esc((ex.atnaujinta || "").slice(0, 16).replace("T", " "))} (${esc(ex.modelis || "be modelio")})` : ""}
      ${w.word.itraukta ? " · <b>įtraukta į Neo4j</b>" : ""}</div>
    <div class="actions">
      <button id="aPrompt">Užklausa</button>
      <button id="aExplain" class="primary">${ex ? "Išaiškinti iš naujo" : "Išaiškinti"}</button>
      <label class="small"><input type="checkbox" id="aInc" checked> ir įtraukti</label>
      ${ex ? `<button id="aInclude">${w.word.itraukta ? "Atnaujinti Neo4j" : "Įtraukti į Neo4j"}</button><button id="aReplan" title="Grafo planą sudaryti iš naujo pagal išsaugotą aiškinimą, be kalbos modelio">Perdaryti planą</button>` : ""}
      ${w.word.itraukta ? `<button id="aRemove" class="danger">Pašalinti iš Neo4j</button>` : ""}
    </div>
    ${warn.length ? `<div class="card"><h3>Patikros pastabos (${warn.length})</h3>${warn.map(x => `<div class="warn">${esc(x)}</div>`).join("")}</div>` : ""}
    ${w.articles.map(a => { const s = byArt[a.GUID];
      return `<div class="card"><h3>${esc(a.antraste || w.word.zodis)} ${a.reiksme ? `<span class="muted">‘${esc(a.reiksme)}’</span>` : ""}</h3>
        <div class="muted small">${esc(a.saltinis || a.saltinis_pilnas || "")}${a.vieta_saltinyje ? `, ${esc(a.vieta_saltinyje)}` : ""}</div>
        <div class="art-text">${marked(a.tekstas)}</div>
        ${s ? `<div class="expl">${esc(s.paaiskinimas || "")}</div>${articleSummary(s)}` : ""}</div>`; }).join("")}
    ${planObj ? planView(planObj) : ""}
    ${sem ? `<div class="card"><h3>Visas JSON, pagal kurį sudarytas grafas <button id="cpSem" class="small">kopijuoti</button></h3>
      <pre class="json">${esc(JSON.stringify(sem, null, 2))}</pre>
      <details><summary>Modelio atsakymas be patikros</summary><pre class="json">${esc(ex.llm_atsakymas || "")}</pre></details>
      ${planObj ? `<details><summary>Grafo planas (JSON) <button id="cpPlan" class="small">kopijuoti</button></summary><pre class="json">${esc(JSON.stringify(planObj, null, 2))}</pre></details>` : ""}</div>` : ""}`;
  $("#aPrompt").onclick = async () => { const p = await api(`/api/lkezdb/prompt/${guid}`);
    modal(`<h3>Užklausa modeliui <button id="cpPrompt" class="small">kopijuoti</button></h3><div class="muted small">${p.for_model} iš ${p.articles} straipsnių siunčiami modeliui (kryžminės nuorodos ir tušti – be modelio)</div><pre class="json">${esc(p.prompt)}</pre>`);
    $("#cpPrompt").onclick = () => copy(p.prompt); };
  $("#aExplain").onclick = async () => { await api("/api/lkezdb/explain", {words: [guid], include: $("#aInc").checked}); toast("Įdėta į eilę"); loadWords(); watchJobs(); };
  const act = (id, path, msg) => { const b = $(id); if (b) b.onclick = async () => { b.disabled = true;
    try { const r = await api(`/api/lkezdb/${path}`, {word: guid}); toast(msg(r[guid] || {})); } finally { openWord(guid); loadWords(); loadStatus(); } }; };
  act("#aInclude", "include", r => `Neo4j: ${r.nodes} mazgų, ${r.relationships} ryšių`);
  act("#aReplan", "replan", r => `Planas: ${r.nodes} mazgų, ${r.relationships} ryšių`);
  act("#aRemove", "remove", r => `Pašalinta ${r.nodes} mazgų ir ${r.relationships} ryšių (bendri su kitais žodžiais – palikti)`);
  if ($("#cpSem")) $("#cpSem").onclick = () => copy(JSON.stringify(sem, null, 2));
  if ($("#cpPlan")) $("#cpPlan").onclick = ev => { ev.preventDefault(); copy(JSON.stringify(planObj, null, 2)); };
}

/** One article's analysis in words: objects, features, claims and relations. */
function articleSummary(s) {
  const name = Object.fromEntries([...s.entities.map(e => [e.id, e.written]), ...s.features.map(f => [f.id, `${f.label || f.value}`]),
    ...s.meanings.map(m => [m.id, `‘${m.gloss}’`]), ...s.meaning_groups.map(g => [g.id, g.label])]);
  const prov = p => p === "llm_inference" ? ` <span class="lbl">(modelio išvada)</span>` : p === "article_inference" ? ` <span class="lbl">(išvesta iš teksto)</span>` : "";
  const lex = Object.fromEntries(s.entities.map(e => [e.id, e]));
  return `<details><summary>Analizė: ${s.entities.length} objektų, ${s.features.length} savybių, ${s.claims.length} teiginių, ${s.relations.length} ryšių</summary>
    ${s.entities.length ? `<table class="t"><tr><th>objektas</th><th>tipas</th><th>kalba</th><th>lema</th><th>morfologija</th></tr>
      ${s.entities.map(e => `<tr><td>${esc(e.written)}${e.is_headword ? " ★" : ""}${prov(e.provenance)}</td><td>${esc(e.kind)}</td><td>${esc(e.language || e.language_text || "")}</td>
        <td>${e.lexeme_id ? esc(lex[e.lexeme_id]?.written) : ""}</td><td class="small">${e.morphology.map(m => `${esc(m.category)}=${esc(m.value)}`).join(", ")}</td></tr>`).join("")}</table>` : ""}
    ${s.features.map(f => `<div class="rel">savybė <span class="t">${esc(f.feature)}=${esc(f.value)}</span>: ${f.applies_to.map(x => esc(name[x])).join(", ") || "<span class='muted'>apskritai</span>"}${prov(f.provenance)}</div>`).join("")}
    ${s.claims.map(c => `<div class="rel">teiginys <span class="lbl">${esc(c.type)} · ${esc(c.status)}</span> ${esc(c.text)} → ${c.about.map(x => esc(name[x])).join(", ")}</div>`).join("")}
    ${s.relations.map(r => `<div class="rel">${esc(name[r.from])} <span class="t">${esc(r.type)}</span> ${esc(name[r.to])}${prov(r.provenance)}</div>`).join("")}
  </details>`;
}

function planView(p) {
  const names = Object.fromEntries(p.nodes.map(n => [n.key, `${n.props.display_name}`]));
  const byLabel = {};
  p.nodes.forEach(n => (byLabel[n.label] = byLabel[n.label] || []).push(n.props.display_name));
  const technical = new Set(["Dataset", "DatasetRelease", "SourceTable", "SourceRecord"]);
  const rels = p.relationships.filter(r => !technical.has(r.start_label) && !technical.has(r.end_label));
  return `<div class="card"><h3>Grafo planas: ${p.nodes.length} mazgų, ${p.relationships.length} ryšių</h3>
    <table class="t">${Object.entries(byLabel).filter(([l]) => !technical.has(l)).map(([l, xs]) => `<tr><td>${esc(l)}</td><td>${xs.length}</td><td class="small">${esc(xs.slice(0, 8).join(" · "))}${xs.length > 8 ? " …" : ""}</td></tr>`).join("")}</table>
    <details><summary>Ryšiai (${rels.length}; techniniai nerodomi)</summary>${rels.map(r => `<div class="rel"><span class="lbl">${esc(r.start_label)}</span> ${esc(names[r.start] || r.start)}
      <span class="t">${esc(r.type)}</span> <span class="lbl">${esc(r.end_label)}</span> ${esc(names[r.end] || r.end)}</div>`).join("")}</details></div>`;
}

// ---------------------------------------------------------------- jobs
let jobTimer = null;
function watchJobs() {
  if (jobTimer) return;
  jobTimer = setInterval(async () => {
    await loadStatus();
    if (!$("[data-pane=jobs]").hidden) renderJobs();
    if (!L.status.stats.eileje) { clearInterval(jobTimer); jobTimer = null; loadWords(); if (L.current) openWord(L.current); }
  }, 2500);
}
async function renderJobs() {
  const {jobs} = await api("/api/lkezdb/jobs");
  const label = {pending: "eilėje", running: "aiškinama", done: "atlikta", failed: "nepavyko"};
  $("[data-pane=jobs]").innerHTML = `<div class="row"><button id="jClear">Išvalyti atliktus ir nepavykusius</button></div>
    <table class="t"><tr><th>žodis</th><th>būsena</th><th>įtraukti</th><th>sukurta</th><th>baigta</th><th>rezultatas / klaida</th></tr>
    ${jobs.map(j => { let res = ""; try { const r = JSON.parse(j.rezultatas || "{}"); res = r.nodes ? `${r.nodes} mazgų, ${r.relationships} ryšių${r.warnings?.length ? `, ${r.warnings.length} pastabų` : ""}` : ""; } catch (e) { /* */ }
      return `<tr><td><a href="#" data-open="${esc(j.zodzio_GUID)}">${esc(j.zodis)}</a></td><td>${label[j.busena] || esc(j.busena)}</td><td>${j.auto_itraukti ? "taip" : "ne"}</td>
        <td class="small">${esc((j.sukurta || "").slice(0, 16))}</td><td class="small">${esc((j.baigta || "").slice(0, 16).replace("T", " "))}</td>
        <td class="small">${j.klaida ? `<span style="color:var(--err)">${esc(j.klaida)}</span>` : esc(res)}</td></tr>`; }).join("") || `<tr><td colspan="6" class="muted">Eilė tuščia.</td></tr>`}</table>`;
  $("#jClear").onclick = async () => { await api("/api/lkezdb/jobs/clear", {}); renderJobs(); };
  $$("[data-open]").forEach(a => a.onclick = ev => { ev.preventDefault(); $$(".tab")[0].click(); openWord(a.dataset.open); });
}

// ---------------------------------------------------------------- engine and prompt
async function renderEngine() {
  await loadStatus();
  const e = L.status.engine, pane = $("[data-pane=engine]");
  pane.innerHTML = `<h3>Kalbos modelis</h3>
    <div class="row"><label>Tiekėjas</label><select id="eProv">${e.providers.map(p => `<option value="${p.id}" ${p.id === e.provider ? "selected" : ""}>${esc(p.label)}</option>`).join("")}</select></div>
    <div class="row"><label>API adresas</label><input type="text" id="eUrl" value="${esc(e.url)}" style="width:420px"></div>
    <div class="row"><label>Modelis</label><input type="text" id="eModel" value="${esc(e.model)}" list="eModels" style="width:300px"><datalist id="eModels"></datalist>
      <button id="eList">Gauti modelių sąrašą</button></div>
    <div class="row"><label>API raktas</label><input type="password" id="eKey" placeholder="${e.has_key ? "įrašykite naują, jei norite pakeisti" : "nenustatytas"}" style="width:320px"
        title="ChatGPT raktas įrašomas į bylą .raktas projekto aplanke (žr. API_raktas.md)">
      <span class="muted small">${e.has_key ? `naudojamas <span class="mono">${esc(e.key_hint)}</span> – ${esc(e.key_from)}` : "arba aplinkos kintamasis OPENAI_API_KEY"}</span></div>
    <div class="row"><label>JSON schema</label><label><input type="checkbox" id="eSchema" ${e.json_schema ? "checked" : ""}> griežta atsakymo schema (jei modelis nepalaiko – išjungiama savaime)</label></div>
    <div class="row"><label></label><button id="eSave" class="primary">Išsaugoti</button></div>
    <h3 style="margin-top:26px">Užklausa</h3>
    <p class="muted small">Rodomos tik šios programos atsakymo schemai parašytos užklausos (su žyme <span class="mono">&lt;!-- kalba-lkezdb-schema: 1 --&gt;</span>). Ankstesnės programos užklausos lieka talpykloje, bet netinka naujam grafo modeliui.</p>
    <table class="t">${L.status.prompts.map(p => `<tr><td><label><input type="radio" name="pr" value="${esc(p.GUID)}" ${p.GUID === L.status.active ? "checked" : ""}> ${esc(p.name)}</label>
      ${p.builtin ? `<span class="badge">programos</span>` : ""}</td><td class="small muted">${esc((p.updated || "").slice(0, 16))}</td><td class="small muted">${p.length} simb.</td>
      <td><button data-view="${esc(p.GUID)}" class="small">peržiūrėti</button></td></tr>`).join("")}</table>
    <div class="row"><label>Nauja užklausa</label><input type="file" id="pFile" accept=".md,.txt"><button id="pUpload">Įkelti ir naudoti</button></div>`;
  $("#eList").onclick = async () => { const {models} = await api("/api/lkezdb/models"); $("#eModels").innerHTML = models.map(m => `<option value="${esc(m)}">`).join(""); toast(`${models.length} modelių`); };
  $("#eProv").onchange = async () => { await api("/api/lkezdb/engine", {provider: $("#eProv").value}); renderEngine(); };
  $("#eSave").onclick = async () => { await api("/api/lkezdb/engine", {provider: $("#eProv").value, url: $("#eUrl").value, model: $("#eModel").value,
    json_schema: $("#eSchema").checked, key: $("#eKey").value || undefined}); toast("Išsaugota"); renderEngine(); };
  $$("input[name=pr]").forEach(r => r.onchange = async () => { await api("/api/lkezdb/prompts/select", {GUID: r.value}); toast("Užklausa pasirinkta"); });
  $$("[data-view]").forEach(b => b.onclick = async () => { const p = await api(`/api/lkezdb/prompts/${encodeURIComponent(b.dataset.view)}`); modal(`<pre class="json">${esc(p.text)}</pre>`); });
  $("#pUpload").onclick = async () => { const f = $("#pFile").files[0]; if (!f) return toast("Pasirinkite bylą", "warning");
    await api("/api/lkezdb/prompts", {name: f.name, text: await f.text()}); toast("Užklausa įkelta ir pasirinkta"); renderEngine(); };
}

// ---------------------------------------------------------------- Neo4j
async function renderNeo4j() {
  const pane = $("[data-pane=neo4j]");
  pane.innerHTML = `<p class="muted">Skaičiuojama…</p>`;
  let c;
  try { c = await api("/api/lkezdb/counts"); } catch (e) { pane.innerHTML = `<p class="warn">Neo4j nepasiekiama.</p>`; return; }
  pane.innerHTML = `<h3>LKEŽDB duomenys Neo4j</h3>
    <p>${c.nodes.toLocaleString(LOCALE)} mazgų ir ${c.relationships.toLocaleString(LOCALE)} ryšių su <span class="mono">dataset = "lkezdb"</span>.</p>
    <table class="t" style="max-width:420px">${c.labels.map(l => `<tr><td>${esc(l.label)}</td><td>${l.c}</td></tr>`).join("")}</table>
    <div><h3 style="margin-top:26px">Ištrinti visus LKEŽDB duomenis</h3>
    <p class="muted small">Ištrinami tik šiuo įrankiu įtraukti mazgai ir jų ryšiai (taip pat ryšiai į Glottolog ir Concepticon). Kiti duomenynai,
      apribojimai ir indeksai nepaliečiami. Aiškinimai SQLite talpykloje lieka – juos galima vėl įtraukti.</p>
    <div class="row"><input type="text" id="delConfirm" placeholder="įrašykite IŠTRINTI"><button id="delAll" class="danger" ${c.nodes ? "" : "disabled"}>Ištrinti</button></div></div>`;
  $("#delAll").onclick = async () => {
    const r = await api("/api/lkezdb/delete-all", {confirm: $("#delConfirm").value.trim()});
    toast(`Ištrinta ${r.deleted_nodes} mazgų, ${r.deleted_relationships} ryšių`); renderNeo4j(); loadStatus(); loadWords();
  };
}

(async function boot() {
  await KalbaTheme.load().catch(() => {});
  if (!(await loadStatus())) return;
  const params = new URLSearchParams(location.search);
  const wanted = params.get("zodis"), guid = params.get("guid");   // /lkezdb?zodis=esmi or ?guid=… opens that word
  if (guid) {
    L.missing = params.has("truksta") ? guid : null;
    const w = await api(`/api/lkezdb/word/${encodeURIComponent(guid)}`).catch(() => null);
    if (w) $("#q").value = w.word.zodis;
  } else if (wanted) $("#q").value = wanted;
  await loadWords();
  if (guid) openWord(guid);
  else if (wanted) { const first = $("#items [data-g]"); if (first) openWord(first.dataset.g); }
  if (L.status.stats.eileje) watchJobs();
})();
