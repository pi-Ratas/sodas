/* Pamokos: a short guided walk through a page (Kalba.lesson in bar.js loads this file when it is needed).
   Each step lights up one part of the page (the rest is shaded), tells what it is for and may offer to try it
   (e.g. "Pasodinti pavyzdį"). Nothing is blocked: the page can be used while the lesson is open. Esc ends it,
   ← / → go back and forth. A page without its lesson yet says so (Kalba.lessonFor). */
"use strict";
(function () {
  const T = (x, ...v) => window.SodasI18n && SodasI18n.t ? SodasI18n.t(x, ...v) : x.replace(/\{(\d+)\}/g, (m, i) => v[i]);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const DONE = page => `sodas.pamoka.${page}`;
  const sleep = ms => new Promise(ok => setTimeout(ok, ms));
  const visible = el => !!el && el.getClientRects().length > 0 && !el.closest("[hidden]");

  // ---------------------------------------------------------------- the garden's actions offered on the way
  /** Types a word into the search, as the researcher would. */
  function typeSearch(word) {
    const q = document.getElementById("q");
    if (!q) return;
    q.focus(); q.value = word;
    q.dispatchEvent(new Event("input", {bubbles: true}));
  }
  /** Plants an example: the first word the search finds (of the datasets this visitor may see), expanded. */
  async function plantExample() {
    if (typeof S === "undefined" || typeof addNode !== "function") return;
    typeSearch("saulė");   // the visitor sees where the word comes from
    for (const word of ["saulė", "sun", "water"]) {
      let r;
      try { r = await (await fetch(`/api/sodas/search?q=${encodeURIComponent(word)}`)).json(); } catch (e) { continue; }
      const items = (r.groups || []).flatMap(g => g.items || []);
      // the word itself (with its accents ignored) before anything that only resembles it; a lexeme before a form
      const plain = x => String(x || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase();
      const exact = items.filter(i => String(i.display_name).toLocaleLowerCase() === word.toLocaleLowerCase());
      const same = items.filter(i => plain(i.display_name) === plain(word));
      const it = exact.find(i => i.label === "Lexeme") || exact[0] || same.find(i => i.label === "Lexeme") || same[0] || items[0];
      if (!it) continue;
      const q = document.getElementById("q");
      if (q) { q.value = ""; document.getElementById("results").hidden = true; }
      const el = await addNode(it);
      if (el && el.nonempty && el.nonempty()) {
        await expand(el, "semantic");
        // the whole example in view, not blown up: a few nodes fill the screen otherwise
        const cy = S.cy;
        cy.fit(cy.elements(":visible"), 160);
        if (cy.zoom() > 1.2) cy.zoom({level: 1.2, renderedPosition: {x: cy.width() / 2, y: cy.height() / 2}});
      }
      return;
    }
  }
  // after the click that brought the step has gone by (the page closes drop-downs on any click elsewhere)
  /** No node of its own in the garden yet (search results shown for a while do not count). */
  const gardenEmpty = () => typeof S === "undefined" || !S.cy || S.cy.nodes().not(".temp, .more, .virtual").empty();
  const openViewPanel = () => setTimeout(() => { const p = document.getElementById("typesPanel"); if (cur && p && p.hidden) document.querySelector('[data-act="types"]').click(); }, 60);
  const closeDrops = () => ["typesPanel", "exportMenu", "basketMenu"].forEach(id => { const el = document.getElementById(id); if (el) el.hidden = true; });

  // ---------------------------------------------------------------- the lessons
  const LESSONS = {
    sodas: [
      {title: "Sveiki atvykę į Sodą!",
        text: "Čia auginate savo tyrimo sodą – kalbų, žodžių, jų reikšmių ir sąvokų grafą iš daugelio duomenynų. Pamoka trunka apie dvi minutes. Ją bet kada galite nutraukti (Esc), o pakartoti – spustelėję ženklą SODAS."},
      {target: "#q", place: "below-left", title: "Paieška",
        text: "Pasodinkime pirmąjį žodį. Paieškos lauke įrašykite, pvz., saulė, ir atsiradusiame sąraše spustelėkite pirmą radinį – jis atsiras sode. Ieškoti galima ir kalbų, sąvokų ar giminiškų žodžių rinkinių.",
        action: {label: "Padaryk už mane", run: plantExample},
        // the next steps are about nodes: an empty garden gets the example on the way
        leave: async () => { if (gardenEmpty()) await plantExample(); }},
      {target: "#cy", title: "Sodas", place: "inside",
        text: "Mazgai – žodžiai, reikšmės, kalbos, sąvokos; linijos – ryšiai tarp jų. Dukart spustelėjus mazgą jis išskleidžiamas: atsiranda jo kaimynai. Ratuku sodas artinamas, tempiant – stumdomas."},
      {target: "#cy", title: "Pelė sode", place: "inside",
        text: "Dešinysis klavišas ant mazgo – visi jo veiksmai (išskleisti, suskleisti, žemėlapis, krepšys…). Vidurinis klavišas – mazgo skydelis. Shift + spustelėjimas – pažymėti kelis mazgus: pažymėtus galima apjungti arba sujungti ryšiu."},
      {target: "#info", optional: true, place: "left", title: "Mazgo aprašas",
        text: "Pažymėto mazgo savybės, ryšiai duomenų bazėje ir šaltinio įrašas rodomi čia. Vėliavėlė prie mazgo – jo kalba, ženkliukas ⧉ – apjungti mazgai."},
      {target: "#typesPanel", place: "left", before: openViewPanel, after: closeDrops, title: "Rodinys",
        text: "👁 – mazgų ir ryšių pavadinimai bei sode esantys tipai: nuėmus varnelę tipas paslepiamas, sodas tampa aiškesnis."},
      {target: '[data-act="map"]', title: "Žemėlapis",
        text: "🗺 atsiranda, kai sode yra mazgų su vieta: jie nukeliami į savo vietas žemėlapyje. Pažymėjus sąvoką ar reikšmę (Sense), žemėlapyje parodomi visi jų žodžiai.",
        missing: "Kai sode atsiras mazgų su vieta (kalbų, žodžių), juostoje atsiras 🗺: mazgai nukeliami į savo vietas žemėlapyje. Pažymėjus sąvoką ar reikšmę (Sense), žemėlapyje parodomi visi jų žodžiai."},
      {target: ".basket-box", title: "Krepšys",
        text: "🧺 – tyrimo krepšys: čia dedami mazgai, su kuriais vėliau dirba Vaivos tyrimai (pvz. garsų atitikmenys, kalbų medžiai)."},
      {target: ".export-box", title: "Atsisiuntimas",
        text: "Sodą galima atsisiųsti kaip SVG, PNG ar JSON. Prie kiekvienos bylos pridedami naudotų duomenų ir paties Sodo bibliografiniai įrašai. 📚 – tie patys įrašai atskirai."},
      {target: ".name-box", title: "Jūsų sodai",
        text: "Sodo pavadinimas ir kiti jūsų sodai; ＋ – naujas sodas. Kiekvienas sodas – atskiras tyrimas."},
      {target: ".kalba-nav", title: "Kitos dalys",
        text: "Žemė – duomenynai, iš kurių auga sodai; Vaiva – tyrimai su krepšio mazgais."},
      {target: "#kalbaUser", title: "Kalba ir nustatymai",
        text: "Sodai išsaugomi patys. Raidės – sąsajos kalba; ⚙ – nustatymai: tema, spalvos, mazgų išvaizda, duomenynai, sodų tvarkymas."},
      {target: "#kbLogo", title: "Pamoka visada po ranka",
        text: "Spustelėję ženklą SODAS sužinosite apie aplinką, kaip ją cituoti, ir galėsite pakartoti šią pamoką. Sėkmingo sodininkavimo!"},
    ],
  };

  // ---------------------------------------------------------------- the walk
  let cur = null;   // {page, steps, i, shade, ring, box, timer}
  function stop(done) {
    if (!cur) return;
    const c = cur;
    cur = null;
    if (c.steps[c.i] && c.steps[c.i].after) try { c.steps[c.i].after(); } catch (e) { /* ignore */ }
    clearInterval(c.timer);
    c.ring.remove(); c.box.remove();
    document.body.classList.remove("pm-on");
    window.dispatchEvent(new Event("resize"));   // the garden takes the room they leave
    document.removeEventListener("keydown", onKey, true);
    window.removeEventListener("resize", place);
    try { localStorage.setItem(DONE(c.page), done ? "baigta" : "nutraukta"); } catch (e) { /* private mode */ }
  }
  function onKey(ev) {
    if (!cur) return;
    const typing = ev.target && /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName);
    if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); stop(false); }
    else if (!typing && ev.key === "ArrowRight") { ev.preventDefault(); cur.box.querySelector('[data-pm="next"]').click(); }
    else if (!typing && ev.key === "ArrowLeft") { ev.preventDefault(); go(cur.i - 1); }
  }
  function targetOf(step) {
    if (!step.target) return null;
    const el = document.querySelector(step.target);
    return visible(el) ? el : null;
  }
  /** The ring over the step's part of the page (its shadow shades the rest) and the box beside it. */
  function place() {
    if (!cur) return;
    const step = cur.steps[cur.i], el = targetOf(step), ring = cur.ring, box = cur.box;
    const W = innerWidth, H = innerHeight, gap = 12, bw = box.offsetWidth, bh = box.offsetHeight;
    if (!el) {
      ring.classList.add("pm-none");
      Object.assign(ring.style, {left: `${W / 2}px`, top: `${H / 2}px`, width: "0px", height: "0px"});
      if (cur.pinned) return pinBox();
      Object.assign(box.style, {left: `${Math.max(8, (W - bw) / 2)}px`, top: `${Math.max(8, (H - bh) / 2)}px`});
      return;
    }
    ring.classList.remove("pm-none");
    const r = el.getBoundingClientRect(), pad = 6;
    Object.assign(ring.style, {left: `${r.left - pad}px`, top: `${r.top - pad}px`, width: `${r.width + 2 * pad}px`, height: `${r.height + 2 * pad}px`});
    if (cur.pinned) return pinBox();
    Object.assign(ring.style, {left: `${r.left - pad}px`, top: `${r.top - pad}px`, width: `${r.width + 2 * pad}px`, height: `${r.height + 2 * pad}px`});
    let x, y;
    if (step.place === "left" && r.left - gap - bw > 0) { x = r.left - gap - bw; y = r.top; }
    else if (step.place === "below-left" && r.left - gap - bw > 0) { x = r.left - gap - bw; y = r.bottom + gap; }   // the list opening under it stays free
    else if (step.place === "inside" || (r.height > H * .6 && r.width > W * .5)) { x = r.left + (r.width - bw) / 2; y = r.top + Math.min(80, r.height / 6); }
    else if (r.bottom + gap + bh < H) { x = r.left; y = r.bottom + gap; }
    else if (r.top - gap - bh > 0) { x = r.left; y = r.top - gap - bh; }
    else { x = r.right + gap; y = r.top; }
    Object.assign(box.style, {left: `${Math.max(8, Math.min(x, W - bw - 8))}px`, top: `${Math.max(8, Math.min(y, H - bh - 8))}px`});
  }
  /** The box where the visitor dragged it (kept on the screen). */
  function pinBox() {
    const b = cur.box, p = cur.pinned;
    b.style.left = `${Math.max(0, Math.min(p.x, innerWidth - b.offsetWidth))}px`;
    b.style.top = `${Math.max(0, Math.min(p.y, innerHeight - b.offsetHeight))}px`;
  }
  /** The box is dragged by its head: it stays where it is put for the rest of the lesson (↺ – back beside the part). */
  function draggable(box) {
    box.addEventListener("pointerdown", ev => {
      if (!ev.target.closest(".pm-head") || ev.target.closest("button") || ev.button !== 0) return;
      ev.preventDefault();
      const r = box.getBoundingClientRect(), dx = ev.clientX - r.left, dy = ev.clientY - r.top;
      box.classList.add("pm-drag");
      const move = e => { if (!cur) return; cur.pinned = {x: e.clientX - dx, y: e.clientY - dy}; pinBox(); };
      const up = () => {
        box.classList.remove("pm-drag");
        removeEventListener("pointermove", move); removeEventListener("pointerup", up);
        if (cur && cur.pinned) { const h = box.querySelector('[data-pm="home"]'); if (h) h.hidden = false; }
      };
      addEventListener("pointermove", move); addEventListener("pointerup", up);
    });
  }
  function go(i) {
    if (!cur) return;
    const steps = cur.steps;
    // a step about a part not on the page now (an optional one) is passed over in the direction of travel
    const dir = i >= cur.i ? 1 : -1;
    while (i >= 0 && i < steps.length && steps[i].optional && !targetOf(steps[i])) i += dir;
    if (i < 0) i = 0;
    if (i >= steps.length) return stop(true);
    const was = steps[cur.i];
    if (was && was !== steps[i] && was.after) try { was.after(); } catch (e) { /* ignore */ }
    cur.i = i;
    const step = steps[i];
    if (step.before) try { step.before(); } catch (e) { /* ignore */ }
    const el = targetOf(step), text = !el && step.missing ? step.missing : step.text;
    const shown = steps.length, n = i + 1;
    cur.box.innerHTML = `<div class="pm-head" title="${esc(T("Tempkite, kad perkeltumėte"))}"><b>${esc(T(step.title))}</b><span class="pm-n">${n} / ${shown}</span>
        <button class="pm-x" data-pm="home" title="${esc(T("Grąžinti prie aiškinamos dalies"))}" ${cur.pinned ? "" : "hidden"}>↺</button>
        <button class="pm-x" data-pm="stop" title="${esc(T("Baigti pamoką (Esc)"))}">×</button></div>
      <p>${esc(T(text))}</p>
      <div class="pm-actions">${step.action ? `<button data-pm="try" class="pm-try">${esc(T(step.action.label))}</button>` : ""}
        <span class="pm-sp"></span>${i ? `<button data-pm="back">${esc(T("Atgal"))}</button>` : ""}
        <button data-pm="next" class="primary">${esc(T(i === steps.length - 1 ? "Baigti" : "Toliau"))}</button></div>`;
    cur.ring.classList.toggle("pm-none", !el);
    cur.box.querySelector('[data-pm="stop"]').onclick = () => stop(false);
    cur.box.querySelector('[data-pm="home"]').onclick = ev => { cur.pinned = null; ev.target.hidden = true; place(); };
    cur.box.querySelector('[data-pm="next"]').onclick = async ev => {
      if (step.leave) { ev.target.disabled = true; try { await step.leave(); } catch (e) { /* the page tells */ } }
      if (cur && cur.steps[cur.i] === step) go(cur.i + 1);
    };
    const back = cur.box.querySelector('[data-pm="back"]');
    if (back) back.onclick = () => go(cur.i - 1);
    const t = cur.box.querySelector('[data-pm="try"]');
    if (t) t.onclick = async () => {
      t.disabled = true;
      try { await step.action.run(); } catch (e) { /* the page tells what went wrong */ }
      await sleep(300);
      t.disabled = false;
      place();
    };
    place();
    cur.box.querySelector('[data-pm="next"]').focus({preventScroll: true});
  }
  /** Starts the lesson of ``page``; false when that page has no lesson yet. */
  function start(page) {
    const steps = LESSONS[page];
    if (!steps) return false;
    stop(false);
    const ring = document.createElement("div"), box = document.createElement("div");
    ring.className = "pm-ring"; box.className = "pm-box"; box.setAttribute("role", "dialog"); box.setAttribute("aria-label", T("Pamoka"));
    document.body.append(ring, box);
    document.body.classList.add("pm-on");   // the sign-in prompts step aside while the lesson runs
    window.dispatchEvent(new Event("resize"));   // the garden takes the room they leave
    cur = {page, steps, i: 0, ring, box, pinned: null, timer: setInterval(place, 400)};   // parts move (panels open, the garden grows)
    draggable(box);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", place);
    go(0);
    return true;
  }
  window.SodasPamoka = {start, has: page => !!LESSONS[page], seen: page => { try { return !!localStorage.getItem(DONE(page)); } catch (e) { return true; } },
    forget: page => { try { localStorage.setItem(DONE(page), "nutraukta"); } catch (e) { /* ignore */ } }};
})();
