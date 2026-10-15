/* The shared top bar of every page of Sodas: on the left – the sign and ← → (back and forward, like the browser's: one
   garden to another); on the right – the interface language and ⚙ the settings.
   Kalba.ready → resolves when the bar is drawn; Kalba.call(path, body) – a request to the server (POST with a body).
   Kalba.bibliography(button, {sodas | tyrimas}) – the menu of formats and the bibliography of a garden or a Vaiva run.
   Kalba.working(text) → done(): a notice „Puslapis dirba…“ when work (or any request) takes longer than 2 s. */
(function () {
  "use strict";
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const embedded = new URLSearchParams(location.search).has("embed");

  async function call(path, body) {
    const r = await fetch(path, body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const j = await r.json().catch(() => ({error: r.statusText}));
    if (!r.ok) { const e = new Error(j.error || r.statusText); e.status = r.status; throw e; }
    return j;
  }
  const gardenId = () => { try { return sessionStorage.getItem("kalba.garden"); } catch (e) { return null; } };

  // ------------------------------------------------------------ "Dirbama…": work that takes longer than 2 s
  // Every request of the page is followed (fetch is wrapped); when one of them, or work announced with
  // Kalba.working(text), is still going after BUSY_AFTER ms, a notice shows that the page is working (and for how long).
  // The status checks are not work the person waits for.
  const BUSY_AFTER = 2000, QUIET = /^\/api\/(sodas\/status|sodas\/log)$/;
  const busy = new Map();   // token → {text, at}
  let busyTimer = null, busyEl = null, busySeq = 0;
  function busyRender() {
    const now = Date.now(), late = [...busy.values()].filter(b => now - b.at >= BUSY_AFTER);
    if (!late.length) { if (busyEl) busyEl.hidden = true; document.documentElement.classList.remove("kb-busy-on"); return; }
    if (!busyEl) {
      busyEl = document.createElement("div");
      busyEl.className = "kb-busy"; busyEl.setAttribute("role", "status"); busyEl.setAttribute("aria-live", "polite");
      document.body.append(busyEl);
    }
    const oldest = Math.min(...late.map(b => b.at)), text = late.map(b => b.text).filter(Boolean).pop();
    busyEl.innerHTML = `<span class="kb-spin"></span><span>${esc(text || "Puslapis dirba…")}</span><span class="kb-muted">${Math.round((now - oldest) / 1000)} s</span>`;
    busyEl.hidden = false;
    document.documentElement.classList.add("kb-busy-on");
  }
  function busyTick() {
    clearTimeout(busyTimer);
    busyRender();
    if (busy.size) busyTimer = setTimeout(busyTick, 1000);
  }
  /** Work the person waits for: the notice appears if it is not done in 2 s. Returns the function that ends it. */
  function working(text) {
    const token = ++busySeq;
    busy.set(token, {text: text || "", at: Date.now()});
    if (busy.size === 1) { clearTimeout(busyTimer); busyTimer = setTimeout(busyTick, BUSY_AFTER); }
    let done = false;
    return () => { if (done) return; done = true; busy.delete(token); if (!busy.size) busyTick(); };
  }
  const nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    let path = "";
    try { path = new URL(typeof input === "string" ? input : input.url, location.href).pathname; } catch (e) { /* not a URL */ }
    if (QUIET.test(path) || (init && init.keepalive)) return nativeFetch(input, init);
    const done = working();
    return nativeFetch(input, init).then(r => { done(); return r; }, e => { done(); throw e; });
  };

  // ------------------------------------------------------------ the garden one works in
  /** The last garden (another page – Vaiva, Žemė – leads back to it). */
  function lastGarden() {
    try { return (localStorage.getItem("kalba.lastGarden") || "").split(":").pop() || null; } catch (e) { return null; }
  }
  function rememberGarden(id) {
    try { sessionStorage.setItem("kalba.garden", id); localStorage.setItem("kalba.lastGarden", id); } catch (e) { /* ignore */ }
  }

  // ------------------------------------------------------------ the right-hand corner of the bar
  function render() {
    const bar = document.querySelector("header.kalba-bar");
    if (!bar || embedded) return;
    let box = document.getElementById("kalbaUser");
    if (!box) { box = document.createElement("div"); box.id = "kalbaUser"; box.className = "kalba-user"; bar.append(box); }
    const g = gardenId();
    const settingsOn = location.pathname === "/nustatymai";
    history_();
    logo_();
    box.innerHTML = `${langHtml()}<a class="kb-gear${settingsOn ? " active" : ""}" href="/nustatymai${g ? `?sodas=${encodeURIComponent(g)}` : ""}" data-env="settings" title="Nustatymai">⚙</a>`;
    box.querySelectorAll("[data-kb]").forEach(el => el.onclick = ev => {
      ev.preventDefault(); ev.stopPropagation();
      const what = el.dataset.kb;
      if (what === "lang") { const m = box.querySelector(".kb-langs"); closeDrops(m); m.hidden = !m.hidden; }
      else if (what === "setlang") I18N.setLang(el.dataset.code);
    });
  }
  // ------------------------------------------------------------ the interface language
  const I18N = window.SodasI18n || {lang: "lt", languages: [{code: "lt", name: "Lietuvių"}], setLang() {}};
  /** A whole sentence in the interface's language, with values put in. */
  const T = (x, ...v) => I18N.t ? I18N.t(x, ...v) : x.replace(/\{(\d+)\}/g, (m, i) => v[i]);
  function langHtml() {
    const items = I18N.languages.map(l => `<a href="#" data-kb="setlang" data-code="${l.code}" class="${l.code === I18N.lang ? "on" : ""}"
      lang="${l.code}" translate="no"><span class="kb-lang-code">${l.code.toUpperCase()}</span>${esc(l.name)}</a>`).join("");
    return `<button class="kb-lang" data-kb="lang" title="Sąsajos kalba">${I18N.lang.toUpperCase()}</button>
      <div class="kb-langs kb-menu kb-drop" hidden><div class="kb-muted kb-small kb-langs-h">Sąsajos kalba</div>${items}</div>`;
  }

  // ------------------------------------------------------------ back and forward
  // The browser's own history: a garden opened in place of another one is a step of it too (sodas.js), so ← returns to
  // the garden one came from. Where the browser tells (the Navigation API), a button with nowhere to go is greyed out.
  function history_() {
    const bar = document.querySelector("header.kalba-bar");
    if (!bar || embedded) return;
    let box = document.getElementById("kbHistory");
    if (!box) {
      box = document.createElement("div"); box.id = "kbHistory"; box.className = "kb-history";
      const rtl = document.documentElement.dir === "rtl";   // back points the way the text came from
      box.innerHTML = `<button data-h="back" title="Atgal (Alt+←)" aria-label="Atgal">${rtl ? "→" : "←"}</button><button data-h="forward" title="Pirmyn (Alt+→)" aria-label="Pirmyn">${rtl ? "←" : "→"}</button>`;
      bar.prepend(box);
      box.querySelector('[data-h="back"]').onclick = () => history.back();
      box.querySelector('[data-h="forward"]').onclick = () => history.forward();
      if (window.navigation && "canGoBack" in window.navigation) navigation.addEventListener("currententrychange", syncHistory);
      window.addEventListener("popstate", syncHistory);
      window.addEventListener("sodas-history", syncHistory);
    }
    syncHistory();
  }
  function syncHistory() {
    const box = document.getElementById("kbHistory");
    if (!box) return;
    const nav = window.navigation && "canGoBack" in window.navigation ? window.navigation : null;
    box.querySelector('[data-h="back"]').disabled = nav ? !nav.canGoBack : history.length < 2;
    box.querySelector('[data-h="forward"]').disabled = nav ? !nav.canGoForward : false;
  }

  // ------------------------------------------------------------ the program's sign and „Apie Sodą“
  // The sign stands first in the bar, before ← (put in after it, as the first child). It is drawn inline – not as a
  // picture – so that its colours come from the theme (theme.css, .kb-logo). A click: what Sodas is, how to cite it,
  // whom to write to (kontaktai.yaml on the server).
  let logoSvg = null;
  const logoText = () => logoSvg || (logoSvg = fetch("/sodas/ikonos/zenklas.svg").then(r => r.ok ? r.text() : Promise.reject(r.status))
    .then(t => t.replace(/<!--[\s\S]*?-->/g, "")).catch(() => (logoSvg = null, '<b style="color:var(--logo)">SODAS</b>')));
  function logo_() {
    const bar = document.querySelector("header.kalba-bar");
    if (!bar || embedded || document.getElementById("kbLogo")) return;
    const b = document.createElement("button");
    b.id = "kbLogo"; b.className = "kb-logo"; b.type = "button";
    b.title = T("Apie Sodą"); b.setAttribute("aria-label", T("Apie Sodą"));
    bar.prepend(b);
    b.onclick = openAbout;
    logoText().then(t => { b.innerHTML = t; });
  }
  // ------------------------------------------------------------ pamokos (pamoka.js, loaded when needed)
  /** Which page this is, as the lessons name them. */
  function pageName() {
    if (document.getElementById("cy")) return document.body.classList.contains("mode-settings") ? "nustatymai" : "sodas";
    const p = location.pathname.replace(/\/+$/, "");
    return {"/zeme": "zeme", "/importas": "zeme", "/lkezdb": "zeme", "/vaiva": "vaiva"}[p] || p.slice(1) || "sodas";
  }
  let lessonScript = null;
  const loadLessons = () => lessonScript || (lessonScript = new Promise((ok, fail) => {
    const s = document.createElement("script");
    s.src = "/sodas/pamoka.js"; s.onload = () => ok(window.SodasPamoka); s.onerror = () => { lessonScript = null; fail(new Error("pamoka.js")); };
    document.head.append(s);
  }));
  /** Starts this page's lesson; false when the page has none yet. */
  async function lesson() {
    document.getElementById("kbLesson")?.remove();
    const P = await loadLessons();
    return P.start(pageName());
  }
  const LESSON_KEY = "sodas.pamoka.sodas";
  /** Who comes to the garden for the first time is offered the lesson – gently: a small card in a corner a few seconds
   *  after the page is ready, never again once it was taken or put aside. */
  function lessonOffer() {
    if (embedded || pageName() !== "sodas") return;
    try { if (localStorage.getItem(LESSON_KEY)) return; } catch (e) { return; }
    setTimeout(() => {
      if (document.getElementById("kbLesson") || pageName() !== "sodas" || document.querySelector(".pm-box")) return;
      const card = document.createElement("div");
      card.id = "kbLesson"; card.className = "kb-lesson"; card.setAttribute("role", "dialog");
      card.innerHTML = `<button class="kb-x" data-l="no" title="${esc(T("Uždaryti"))}">×</button>
        <div class="kb-lesson-t">🎓 ${esc(T("Pirmą kartą Sode?"))}</div>
        <p>${esc(T("Trumpa pamoka parodys, kaip ieškoti žodžių, auginti savo sodą ir jį tyrinėti (apie 2 min.)."))}</p>
        <div class="kb-actions"><button class="primary" data-l="go">${esc(T("Pradėti pamoką"))}</button><button data-l="no">${esc(T("Ne dabar"))}</button></div>
        <div class="kb-muted kb-small">${esc(T("Pamoką bet kada rasite spustelėję ženklą SODAS."))}</div>`;
      document.body.append(card);
      card.querySelectorAll("[data-l]").forEach(b => b.onclick = () => {
        card.remove();
        if (b.dataset.l === "go") lesson();
        else try { localStorage.setItem(LESSON_KEY, "atidėta"); } catch (e) { /* ignore */ }
      });
    }, 3000);
  }

  async function openAbout() {
    let bg = document.getElementById("kbAbout");
    if (!bg) { bg = document.createElement("div"); bg.id = "kbAbout"; bg.className = "kb-modal-bg"; document.body.append(bg); }
    let a = {contacts: {}}, cite = null;
    try { [a, cite] = await Promise.all([call("/api/apie"), call("/api/bibliografija?formatas=tekstas").catch(() => null)]); } catch (e) { /* shown without them */ }
    const c = a.contacts || {};
    const link = (href, text) => `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(text)}</a>`;
    const rows = [["Vardas, pavardė", c.vardas], ["Pareigos", c.pareigos], ["Institucija", c.institucija],
      ["El. paštas", c.el_pastas && `<a href="mailto:${esc(c.el_pastas)}">${esc(c.el_pastas)}</a>`, true],
      ["Telefonas", c.telefonas], ["Adresas", c.adresas],
      ["Tinklalapis", c.tinklalapis && link(/^https?:/.test(c.tinklalapis) ? c.tinklalapis : "https://" + c.tinklalapis, c.tinklalapis), true],
      ["Programos kodas", c.saugykla && link(c.saugykla, c.saugykla), true]]
      .filter(r => r[1]).map(([k, v, html]) => `<tr><td class="kb-muted">${esc(T(k))}</td><td>${html ? v : esc(v)}</td></tr>`).join("");
    bg.innerHTML = `<div class="kb-modal kb-about" role="dialog" aria-modal="true" aria-label="${esc(T("Apie Sodą"))}">
      <button class="kb-x" data-close title="${esc(T("Uždaryti"))}">×</button>
      <div class="kb-about-logo">${await logoText()}</div>
      <p><b>Sodas</b> – ${esc(T("aplinka kalbų duomenims tirti. Daugelio duomenynų (Glottolog, Concepticon, IE-CoR, Lexibank, WOLD, CLICS, LKEŽDB ir kt.) kalbos, žodžiai, jų reikšmės, sąvokos ir giminiški žodžiai sujungti į vieną grafą, kuriame tyrėjas ieško, lygina ir mato ryšius."))}</p>
      <ul>
        <li><b>${esc(T("Sodas"))}</b> – ${esc(T("tyrėjo sodas: mazgų ir ryšių grafas, kuris auga išskleidžiant žodžius, reikšmes ir sąvokas; tapatūs mazgai apjungiami, juos galima rodyti žemėlapyje."))}</li>
        <li><b>${esc(T("Žemė"))}</b> – ${esc(T("duomenynai: jų įkėlimas ir tvarkymas, LKEŽDB žodžių aiškinimas."))}</li>
        <li><b>${esc(T("Vaiva"))}</b> – ${esc(T("tyrimai su sodo mazgais: garsų atitikmenys, kalbų medžiai, dirbtuvės savo tyrimams sudėlioti."))}</li>
      </ul>
      <h4>🎓 ${esc(T("Pamoka"))}</h4>
      ${pageName() === "sodas" ? `<div class="kb-actions" style="margin-top:0"><button class="primary" data-lesson>${esc(T("Pradėti sodo pamoką"))}</button>
          <span class="kb-muted kb-small">${esc(T("apie 2 min.; Esc – nutraukti"))}</span></div>`
        : `<p class="kb-muted">${esc(T("Šio puslapio pamoka ruošiama. Sodo pamoką rasite sodo lange – spustelėkite ten ženklą SODAS."))}</p>`}
      <h4>${esc(T("Kaip cituoti"))}</h4>
      ${cite && cite.trial ? `<div class="kb-note">⚠ ${esc(T("SODAS įrašas kol kas preliminarus: DOI ir programos saugykla dar ruošiami."))}</div>` : ""}
      ${cite ? `<textarea class="kb-cite" readonly spellcheck="false" translate="no">${esc(cite.text.trim())}</textarea>
        <div class="kb-actions"><button data-copy>${esc(T("Kopijuoti"))}</button><button data-bib>${esc(T("Kiti formatai…"))}</button><span class="kb-muted kb-small" data-said></span></div>`
        : `<p class="kb-muted">${esc(T("Citavimo duomenų gauti nepavyko."))}</p>`}
      <h4>${esc(T("Susisiekti"))}</h4>
      ${rows ? `<table>${rows}</table>` : `<p class="kb-muted">${esc(T("Kontaktai dar neįrašyti."))}</p>`}
      ${c.pastaba ? `<p>${esc(c.pastaba)}</p>` : ""}
      <p class="kb-muted kb-small">${esc(T("Versija {0}", a.version || "?"))}</p></div>`;
    bg.hidden = false;
    const close = () => { bg.hidden = true; document.removeEventListener("keydown", onEsc); };
    const onEsc = ev => { if (ev.key === "Escape") close(); };
    document.addEventListener("keydown", onEsc);
    bg.querySelector("[data-close]").onclick = close;
    bg.onclick = ev => { if (ev.target === bg) close(); };
    const copy = bg.querySelector("[data-copy]");
    if (copy) copy.onclick = async () => {
      const ta = bg.querySelector("textarea");
      try { await navigator.clipboard.writeText(ta.value); } catch (e) { ta.select(); document.execCommand("copy"); }
      bg.querySelector("[data-said]").textContent = T("Nukopijuota");
    };
    const go = bg.querySelector("[data-lesson]");
    if (go) go.onclick = () => { close(); lesson(); };
    const bib = bg.querySelector("[data-bib]");
    if (bib) bib.onclick = () => bibliography(bib, {});
  }

  function closeDrops(except) { document.querySelectorAll("#kalbaUser .kb-drop").forEach(d => { if (d !== except) d.hidden = true; }); }

  // ------------------------------------------------------------ bibliography of a garden or a Vaiva run
  const BIB_FORMATS = [["bibtex", "BibTeX"], ["biblatex", "BibLaTeX"], ["ris", "RIS (EndNote, Zotero, Mendeley)"],
    ["csl", "CSL-JSON (Zotero, Mendeley, Pandoc)"], ["tekstas", "Tekstas (APA)"]];
  /** ``what``: {sodas: id} or {tyrimas: id}. A menu of formats under ``button``; the chosen one opens in a window. */
  function bibliography(button, what) {
    document.querySelectorAll(".kb-bibmenu").forEach(m => m.remove());
    const menu = document.createElement("div");
    menu.className = "kb-bibmenu kb-drop";
    menu.innerHTML = `<div class="kb-muted kb-small kb-langs-h">Bibliografija</div>` +
      BIB_FORMATS.map(([k, t]) => `<a href="#" data-f="${k}">${esc(t)}</a>`).join("");
    document.body.append(menu);
    const r = button.getBoundingClientRect();
    menu.style.top = `${r.bottom + 4}px`;
    menu.style.left = `${Math.max(8, Math.min(r.left, innerWidth - menu.offsetWidth - 8))}px`;
    const close = ev => { if (!menu.contains(ev.target) && ev.target !== button) { menu.remove(); document.removeEventListener("mousedown", close, true); } };
    setTimeout(() => document.addEventListener("mousedown", close, true), 0);
    menu.querySelectorAll("[data-f]").forEach(a => a.onclick = ev => {
      ev.preventDefault(); menu.remove(); document.removeEventListener("mousedown", close, true);
      showBibliography(what, a.dataset.f);
    });
  }
  async function showBibliography(what, fmt) {
    let bg = document.getElementById("kbBib");
    if (!bg) { bg = document.createElement("div"); bg.id = "kbBib"; bg.className = "kb-modal-bg"; document.body.append(bg); }
    const q = new URLSearchParams({...what, formatas: fmt});
    let b;
    try { b = await call(`/api/bibliografija?${q}`); }
    catch (e) { bg.hidden = false; bg.innerHTML = `<div class="kb-modal"><button class="kb-x" data-close title="Uždaryti">×</button><p>${esc(e.message)}</p></div>`;
      bg.querySelector("[data-close]").onclick = () => { bg.hidden = true; }; return; }
    const T = I18N.t || ((x, ...v) => x.replace(/\{(\d+)\}/g, (m, i) => v[i]));
    const day = iso => iso ? String(iso).slice(0, 10) : "";
    const used = b.entries.filter(e => e.dataset !== "sodas");
    bg.innerHTML = `<div class="kb-modal kb-bib" role="dialog" aria-modal="true">
      <button class="kb-x" data-close title="Uždaryti">×</button>
      <h3 style="margin-top:0">${esc(T(b.what === "tyrimas" ? "Tyrimo „{0}“ bibliografija" : "Sodo „{0}“ bibliografija", b.name))}</h3>
      <div class="kb-tabs">${BIB_FORMATS.map(([k, t]) => `<button data-f="${k}" class="${k === fmt ? "on" : ""}">${esc(t.split(" (")[0])}</button>`).join("")}</div>
      ${b.trial ? `<div class="kb-note">⚠ ${esc(T("SODAS įrašas kol kas preliminarus: DOI ir programos saugykla dar ruošiami."))}</div>` : ""}
      ${b.approximate ? `<div class="kb-note">${esc(T(b.what === "tyrimas" ? "Šis tyrimas atliktas dar prieš pradedant sekti naudotus duomenis – sąrašas sudarytas pagal jo krepšį ir tyrimo rūšį." : "Šis sodas išsaugotas dar prieš pradedant sekti naudotus duomenis – sąrašas sudarytas pagal dabar jame esančius mazgus."))}</div>` : ""}
      <p class="kb-muted kb-small">${used.length ? esc(T("Naudoti duomenys:")) : esc(T("Duomenynų dar nenaudota – pateikiamas tik SODAS įrašas."))}</p>
      ${used.length ? `<table class="kb-bib-used">${used.map(e => `<tr><td translate="no">${esc(e.title)}</td><td>${esc(e.version || "")}</td>
        <td class="kb-muted kb-small">${e.first ? esc(day(e.first) === day(e.last) ? day(e.first) : `${day(e.first)} – ${day(e.last)}`) : ""}</td>
        <td class="kb-muted kb-small">${esc(e.license || "")}</td></tr>`).join("")}</table>` : ""}
      <textarea class="kb-bib-text" readonly spellcheck="false" translate="no">${esc(b.text)}</textarea>
      <div class="kb-actions"><button class="primary" data-copy>Kopijuoti</button><button data-save>${esc(T("Atsisiųsti {0}", b.filename))}</button>
        <span class="kb-muted kb-small" data-said></span></div></div>`;
    bg.hidden = false;
    const close = () => { bg.hidden = true; document.removeEventListener("keydown", onEsc); };
    const onEsc = ev => { if (ev.key === "Escape") close(); };
    document.addEventListener("keydown", onEsc);
    bg.querySelector("[data-close]").onclick = close;
    bg.onclick = ev => { if (ev.target === bg) close(); };
    bg.querySelectorAll("[data-f]").forEach(x => x.onclick = () => { document.removeEventListener("keydown", onEsc); showBibliography(what, x.dataset.f); });
    bg.querySelector("[data-copy]").onclick = async () => {
      const ta = bg.querySelector("textarea");
      try { await navigator.clipboard.writeText(b.text); } catch (e) { ta.select(); document.execCommand("copy"); }
      bg.querySelector("[data-said]").textContent = T("Nukopijuota");
    };
    bg.querySelector("[data-save]").onclick = () => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([b.text], {type: b.mime}));
      a.download = b.filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    };
  }

  document.addEventListener("click", ev => {
    if (!ev.target.closest("#kalbaUser")) closeDrops(null);
  });

  const ready = new Promise(resolve => {
    const go = () => { render(); resolve({}); };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", go); else go();
  });
  ready.then(lessonOffer);

  window.Kalba = {ready, call, esc, bibliography, lastGarden, rememberGarden, working, lesson};
})();
