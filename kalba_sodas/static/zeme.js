/* Žemė: the datasets (the importer page: downloading, importing into Neo4j) and LKEŽDB, each in its tab. */
"use strict";
const $ = s => document.querySelector(s);
const params = new URLSearchParams(location.search);
let tab = params.get("skiltis") || "duomenynai";
const frames = {};

function show(name) {
  tab = ["duomenynai", "lkezdb"].includes(name) ? name : "duomenynai";
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === tab));
  const url = new URL(location.href);
  url.searchParams.set("skiltis", tab);
  if (tab !== "lkezdb") ["guid", "truksta", "zodis"].forEach(k => url.searchParams.delete(k));
  history.replaceState(null, "", url);
  for (const f of Object.values(frames)) f.hidden = true;
  if (!frames[tab]) {
    const f = document.createElement("iframe");
    f.className = "pane";
    f.title = tab === "lkezdb" ? "LKEŽDB" : "Duomenynai";
    // a garden node without data opens its word, with a note why (sodas.js lkezdbMissing)
    const guid = params.get("guid"), word = params.get("zodis");
    f.src = tab === "lkezdb" ? `/lkezdb?embed=1${guid ? `&guid=${encodeURIComponent(guid)}` : ""}${params.has("truksta") ? "&truksta=1" : ""}${word ? `&zodis=${encodeURIComponent(word)}` : ""}`
      : "/importas?embed=1";
    frames[tab] = f; $("#main").append(f);
  }
  frames[tab].hidden = false;
}

(async function boot() {
  await Kalba.ready;
  KalbaTheme.load().catch(() => {});
  const g = params.get("sodas") || (() => { try { return sessionStorage.getItem("kalba.garden"); } catch (e) { return null; } })();
  if (g) { $("#navGarden").href = `/?sodas=${g}`; $("#navVaiva").href = `/vaiva?sodas=${g}`; }
  document.querySelectorAll(".tab").forEach(t => t.onclick = () => show(t.dataset.tab));
  show(tab);
})();
