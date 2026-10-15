/* The interface's language. The program's texts are Lithuanian; for another language this script loads its dictionary
   (/sodas/i18n/<kalba>.js, made from kalba_sodas/i18n/*.tsv) and translates the page: the texts written in the HTML,
   those the scripts put on the page later (watched with a MutationObserver), the titles and placeholders, the browser's
   own question windows (alert/confirm/prompt). A text with {0}, {1} … in the dictionary is a pattern: the parts the
   program fills in are kept. A text marked translate="no" (a name, a post, a message) is left as it is.

   The language: the one chosen (a cookie and localStorage, so the server and every tab know it), else the one of the
   country the browser's time zone is in, else the first of the browser's languages the program speaks, else English.
   It must be the first script of a page: the dictionary has to arrive before the page is drawn. */
(function () {
  "use strict";
  const LANGS = {
    lt: ["Lietuvių", "lt-LT"], en: ["English", "en-GB"], lv: ["Latviešu", "lv-LV"], pl: ["Polski", "pl-PL"],
    uk: ["Українська", "uk-UA"], be: ["Беларуская", "be-BY"], ru: ["Русский", "ru-RU"],
    de: ["Deutsch", "de-DE"], fr: ["Français", "fr-FR"], es: ["Español", "es-ES"],
    it: ["Italiano", "it-IT"], pt: ["Português", "pt-BR"], ar: ["العربية", "ar-u-nu-latn"],
    ja: ["日本語", "ja-JP"], zh: ["中文（简体）", "zh-CN"],
  };
  const COOKIE = "sodas_kalba", STORE = "sodas.kalba";
  // the time zone tells the country (no address of the user is looked up anywhere)
  const ZONES = {
    "Europe/Vilnius": "lt", "Europe/Riga": "lv", "Europe/Warsaw": "pl", "Europe/Minsk": "be",
    "Europe/Kyiv": "uk", "Europe/Kiev": "uk", "Europe/Uzhgorod": "uk", "Europe/Zaporozhye": "uk",
    "Europe/London": "en", "Europe/Belfast": "en", "Europe/Guernsey": "en", "Europe/Jersey": "en", "Europe/Isle_of_Man": "en",
    "Europe/Dublin": "en",
    "Europe/Berlin": "de", "Europe/Busingen": "de", "Europe/Vienna": "de", "Europe/Vaduz": "de",
    "Asia/Tokyo": "ja", "Asia/Shanghai": "zh", "Asia/Chongqing": "zh", "Asia/Harbin": "zh", "Asia/Urumqi": "zh",
    "Asia/Hong_Kong": "zh", "Asia/Macau": "zh", "Asia/Taipei": "zh", "Asia/Singapore": "en",
    "Europe/Lisbon": "pt", "Atlantic/Madeira": "pt", "Atlantic/Azores": "pt", "Africa/Luanda": "pt", "Africa/Maputo": "pt",
    "Europe/Rome": "it", "Europe/San_Marino": "it", "Europe/Vatican": "it",
    "Europe/Paris": "fr", "Europe/Monaco": "fr", "Europe/Madrid": "es", "Atlantic/Canary": "es", "Africa/Ceuta": "es",
  };
  // Spanish-speaking America
  ["Mexico_City", "Cancun", "Merida", "Monterrey", "Chihuahua", "Hermosillo", "Mazatlan", "Tijuana", "Bogota", "Lima", "Santiago",
    "Caracas", "Guayaquil", "La_Paz", "Asuncion", "Montevideo", "Argentina/Buenos_Aires", "Argentina/Cordoba", "Argentina/Mendoza",
    "Buenos_Aires", "Guatemala", "El_Salvador", "Tegucigalpa", "Managua", "Costa_Rica", "Panama", "Havana", "Santo_Domingo", "Puerto_Rico"]
    .forEach(z => { ZONES["America/" + z] = "es"; });
  ["Sao_Paulo", "Bahia", "Fortaleza", "Recife", "Belem", "Manaus", "Cuiaba", "Campo_Grande", "Porto_Velho", "Boa_Vista", "Rio_Branco",
    "Maceio", "Araguaina", "Santarem", "Noronha", "Eirunepe"].forEach(z => { ZONES["America/" + z] = "pt"; });
  ["Asia/Riyadh", "Asia/Dubai", "Asia/Baghdad", "Asia/Kuwait", "Asia/Qatar", "Asia/Bahrain", "Asia/Muscat", "Asia/Aden", "Asia/Amman",
    "Asia/Beirut", "Asia/Damascus", "Asia/Gaza", "Asia/Hebron", "Africa/Cairo", "Africa/Algiers", "Africa/Tunis", "Africa/Tripoli",
    "Africa/Casablanca", "Africa/Khartoum", "Africa/Nouakchott"].forEach(z => { ZONES[z] = "ar"; });
  const RU_ZONES = ["Europe/Moscow", "Europe/Kaliningrad", "Europe/Samara", "Europe/Volgograd", "Europe/Saratov", "Europe/Ulyanovsk",
    "Europe/Astrakhan", "Europe/Kirov", "Asia/Yekaterinburg", "Asia/Omsk", "Asia/Novosibirsk", "Asia/Barnaul", "Asia/Tomsk",
    "Asia/Novokuznetsk", "Asia/Krasnoyarsk", "Asia/Irkutsk", "Asia/Chita", "Asia/Yakutsk", "Asia/Khandyga", "Asia/Vladivostok",
    "Asia/Ust-Nera", "Asia/Magadan", "Asia/Sakhalin", "Asia/Srednekolymsk", "Asia/Kamchatka", "Asia/Anadyr"];
  RU_ZONES.forEach(z => { ZONES[z] = "ru"; });

  function chosen() {
    const m = document.cookie.match(/(?:^|;\s*)sodas_kalba=([a-z]{2})/);
    if (m && LANGS[m[1]]) return m[1];
    try { const v = localStorage.getItem(STORE); if (v && LANGS[v]) return v; } catch (e) { /* private mode */ }
    return null;
  }
  function guess() {
    let zone = "";
    try { zone = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (e) { /* old browser */ }
    if (ZONES[zone]) return ZONES[zone];
    for (const l of navigator.languages || [navigator.language || ""]) {
      const code = String(l).slice(0, 2).toLowerCase();
      if (LANGS[code]) return code;
    }
    return "en";
  }
  const lang = chosen() || guess();
  const locale = LANGS[lang][1];
  document.documentElement.lang = lang;
  if (lang === "ar") document.documentElement.dir = "rtl";   // Arabic is written right to left: the whole page turns
  // the dictionary must be there before the next scripts and the page body: a parser-blocking script
  if (lang !== "lt" && !(window.SODAS_I18N && window.SODAS_I18N.lang === lang)) {
    document.write(`<script src="/sodas/i18n/${lang}.js"><\/script>`);
  }

  function setLang(code) {
    if (!LANGS[code]) return;
    document.cookie = `${COOKIE}=${code}; Path=/; Max-Age=${400 * 86400}; SameSite=Lax`;
    try { localStorage.setItem(STORE, code); } catch (e) { /* private mode */ }
    window.dispatchEvent(new CustomEvent("sodas-kalba", {detail: code}));
    location.reload();
  }

  // ------------------------------------------------------------ the dictionary
  let D = null;
  function dict() {
    if (D) return D;
    const src = window.SODAS_I18N;
    if (!src || src.lang !== lang || !src.dict) return null;
    const all = new Map(Object.entries(src.dict)), exact = new Map(), byStart = new Map(), loose = [];
    for (const [k, v] of Object.entries(src.dict)) {
      if (!/\{\d+\}/.test(k)) { exact.set(k, v); continue; }
      const parts = k.split(/(\{\d+\})/);
      const re = new RegExp("^" + parts.map(p => /^\{\d+\}$/.test(p) ? "([\\s\\S]+?)" : p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("") + "$");
      const order = parts.filter(p => /^\{\d+\}$/.test(p)).map(p => Number(p.slice(1, -1)));
      // the literal parts must all be in a text before the (slower) expression is tried
      const lits = parts.filter(p => p && !/^\{\d+\}$/.test(p));
      const end = /^\{\d+\}$/.test(parts[parts.length - 1]) || !parts[parts.length - 1] ? "" : parts[parts.length - 1];
      const item = {re, order, to: v, len: k.length, lits, end};
      if (parts[0].length >= 2) {
        const head = parts[0].slice(0, 2);
        if (!byStart.has(head)) byStart.set(head, []);
        byStart.get(head).push(item);
      } else loose.push(item);
    }
    // the longest pattern first: "Ištrinti {0} mazgų?" before "Ištrinti {0}"
    for (const list of byStart.values()) list.sort((a, b) => b.len - a.len);
    loose.sort((a, b) => b.len - a.len);
    D = {all, exact, byStart, loose, cache: new Map()};
    return D;
  }
  function fill(to, values) {
    return to.replace(/\{(\d+)\}/g, (m, n) => (values[Number(n)] !== undefined ? values[Number(n)] : m));
  }
  /** The translation of one whole text (spaces at its ends kept), or null when the dictionary has none. */
  let depth = 0;   // a value inside a pattern is looked up once more, not deeper
  function lookup(text) {
    const d = dict();
    if (!d || !text) return null;
    const key = String(text).replace(/\s+/g, " ").trim();
    if (!key || key.length > 700 || !/[A-Za-zĄ-ž]/.test(key)) return null;
    let out = d.exact.get(key);
    if (out === undefined) {
      if (d.cache.has(key)) out = d.cache.get(key);
      else {
        out = null;
        for (const p of [...(d.byStart.get(key.slice(0, 2)) || []), ...d.loose]) {
          if ((p.end && !key.endsWith(p.end)) || !p.lits.every(l => key.includes(l))) continue;
          const m = p.re.exec(key);
          if (m) {
            // a value that is itself a text of the interface (a title, a word) is translated too
            const values = [];
            p.order.forEach((n, i) => {
              const v = m[i + 1];
              let t = d.exact.get(v.trim());
              if (t === undefined && depth < 1) { depth++; try { t = lookup(v); } finally { depth--; } }
              values[n] = t == null ? v : t;
            });
            out = fill(p.to, values);
            break;
          }
        }
        if (d.cache.size > 5000) d.cache.clear();
        d.cache.set(key, out);
      }
    }
    if (out == null) {
      // "🔒 Name", "Name:", "– name": the text without the signs around it may be in the dictionary
      const m = /^([^\p{L}\p{N}]*)([\s\S]*?)([^\p{L}\p{N}]*)$/u.exec(key);
      const core = m && m[2];
      if (core && core !== key && d.exact.has(core)) out = m[1] + d.exact.get(core) + m[3];
    }
    if (out == null || out === key) return null;
    const s = String(text);
    return s.match(/^\s*/)[0] + out + s.match(/\s*$/)[0];
  }
  /** For the scripts: t("Ištrinti {0} mazgų?", n) – the text in this language with the values put in. */
  function t(text, ...values) {
    const d = dict();
    const v = d ? d.all.get(text) : undefined;
    return fill(v !== undefined ? v : text, values);
  }

  // ------------------------------------------------------------ translating the page
  const ATTRS = ["title", "placeholder", "aria-label", "alt", "label", "data-tip"];
  const SKIP = new Set(["SCRIPT", "STYLE", "TEXTAREA", "NOSCRIPT", "svg", "SVG"]);
  const kept = el => !!(el && el.closest && el.closest('[translate="no"], .notranslate, [contenteditable="true"]'));

  function textNode(n) {
    const p = n.parentNode;
    if (!p || SKIP.has(p.nodeName) || (p.nodeType === 1 && kept(p))) return;
    const v = lookup(n.nodeValue);
    if (v == null) return;
    if (p.nodeName === "OPTION" && !p.hasAttribute("value")) p.setAttribute("value", p.textContent);   // its value stays the same
    n.nodeValue = v;
  }
  function attrs(el) {
    for (const a of ATTRS) {
      const old = el.getAttribute(a);
      if (old) { const v = lookup(old); if (v != null) el.setAttribute(a, v); }
    }
    if (el.nodeName === "INPUT" && /^(button|submit|reset)$/i.test(el.type) && el.value) {
      const v = lookup(el.value); if (v != null) el.value = v;
    }
  }
  function walk(root) {
    if (root.nodeType === 3) { textNode(root); return; }
    if (root.nodeType !== 1 || SKIP.has(root.nodeName) || kept(root)) return;
    attrs(root);
    const it = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: n => n.nodeType === 1 && (SKIP.has(n.nodeName) || n.getAttribute("translate") === "no" || n.classList.contains("notranslate"))
        ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
    });
    let n = it.nextNode();
    while (n) {
      if (n.nodeType === 3) textNode(n); else attrs(n);
      n = it.nextNode();
    }
  }
  function translate(root) { if (dict()) walk(root || document.documentElement); }

  if (lang !== "lt") {
    const obs = new MutationObserver(list => {
      if (!dict()) return;
      for (const m of list) {
        if (m.type === "childList") m.addedNodes.forEach(walk);
        else if (m.type === "characterData") textNode(m.target);
        else if (m.type === "attributes" && !kept(m.target)) {
          const old = m.target.getAttribute(m.attributeName);
          const v = old ? lookup(old) : null;
          if (v != null) m.target.setAttribute(m.attributeName, v);
        }
      }
    });
    obs.observe(document.documentElement, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS});
    const first = () => translate();
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", first); else first();
    // the browser's own windows
    const ask = {alert: window.alert, confirm: window.confirm, prompt: window.prompt};
    window.alert = msg => ask.alert.call(window, lookup(msg) || msg);
    window.confirm = msg => ask.confirm.call(window, lookup(msg) || msg);
    window.prompt = (msg, def) => ask.prompt.call(window, lookup(msg) || msg, def);
  }

  window.SodasI18n = {lang, locale, t, translate, setLang, lookup,
    languages: Object.entries(LANGS).map(([code, [name, loc]]) => ({code, name, locale: loc}))};
  window.LOCALE = locale;
})();
