/* Shared theme for every Kalba page: light / dark / by the sun, user hue-saturation-lightness, font size. */
(function () {
  const CACHE = "kalba.settings";
  const listeners = [];
  let current = null, animTimer = null, followRun = 0;
  const THEME_MS = 4000;

  // Sunrise/sunset (SunCalc formulas, public domain algorithm by V. Agafonkin / NOAA).
  function sunTimes(date, lat, lon) {
    const rad = Math.PI / 180, dayMs = 864e5, J1970 = 2440588, J2000 = 2451545, e = rad * 23.4397, J0 = 0.0009;
    const toDays = d => d.valueOf() / dayMs - 0.5 + J1970 - J2000;
    const fromJulian = j => new Date((j + 0.5 - J1970) * dayMs);
    const anomaly = d => rad * (357.5291 + 0.98560028 * d);
    const eclLon = M => M + rad * (1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M)) + rad * 102.9372 + Math.PI;
    const lw = rad * -lon, phi = rad * lat, d = toDays(date);
    const n = Math.round(d - J0 - lw / (2 * Math.PI));
    const ds = J0 + lw / (2 * Math.PI) + n;
    const M = anomaly(ds), L = eclLon(M);
    const dec = Math.asin(Math.sin(e) * Math.sin(L));
    const Jnoon = J2000 + ds + 0.0053 * Math.sin(M) - 0.0069 * Math.sin(2 * L);
    const cosW = (Math.sin(rad * -0.833) - Math.sin(phi) * Math.sin(dec)) / (Math.cos(phi) * Math.cos(dec));
    if (cosW < -1) return {polar: "day"};
    if (cosW > 1) return {polar: "night"};
    const w = Math.acos(cosW);
    const a = J0 + (w + lw) / (2 * Math.PI) + n;
    const Jset = J2000 + a + 0.0053 * Math.sin(M) - 0.0069 * Math.sin(2 * L);
    return {sunrise: fromJulian(Jnoon - (Jset - Jnoon)), sunset: fromJulian(Jset)};
  }

  function isDark(settings) {
    const t = settings.theme;
    if (t.mode === "dark") return true;
    if (t.mode !== "sun") return false;
    const s = sunTimes(new Date(), Number(t.latitude) || 54.69, Number(t.longitude) || 25.28);
    if (s.polar) return s.polar === "night";
    const now = new Date();
    return now < s.sunrise || now > s.sunset;
  }

  // comma syntax: the graph canvas (Cytoscape) does not parse the space-separated CSS Color 4 form
  const hsl = (h, s, l) => `hsl(${Math.round(h)}, ${Math.max(0, Math.min(100, s)).toFixed(0)}%, ${Math.max(0, Math.min(100, l)).toFixed(1)}%)`;

  /** "Kontrastas" 0–100 (50: as before) → how far apart the surfaces' lightnesses are (0.4× … 2.5×). */
  const spread = c => { c = Number.isFinite(Number(c)) ? Math.max(0, Math.min(100, Number(c))) : 50; return c <= 50 ? 0.4 + 0.6 * c / 50 : 1 + 1.5 * (c - 50) / 50; };
  const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
  /** The colours a palette ({base, accent, contrast, custom}) gives: the surfaces from the base colour, their lightness
   *  steps scaled by the contrast; every colour the researcher set by hand (``custom``: variable → #rrggbb) wins. */
  function colours(palette, dark) {
    const {h, s, l} = palette.base, A = palette.accent, k = spread(palette.contrast);
    let v;
    if (dark) {
      const bgL = 6 + l * 0.1;
      v = {
        "--bg": hsl(h, s * 0.8, bgL), "--panel": hsl(h, s * 0.7, bgL + 4 * k), "--panel2": hsl(h, s * 0.7, bgL + 8 * k),
        "--line": hsl(h, s * 0.6, bgL + 16 * k), "--chip": hsl(h, s * 0.6, bgL + 10 * k), "--ink": hsl(h, 10, 90), "--muted": hsl(h, 8, clamp(64 + 10 * (k - 1), 45, 85)),
        "--accent": hsl(A.h, A.s, Math.min(80, A.l + 22)), "--accent-ink": hsl(A.h, 30, 10), "--accent-soft": hsl(A.h, A.s * 0.6, clamp(bgL + 10 * k, 14, 45)),
        "--ok": "#6cc08b", "--warn": "#e0a64b", "--err": "#ef7d72", "--graph-bg": hsl(h, s * 0.8, bgL + k),
        "--logo": hsl(A.h, A.s, Math.min(80, A.l + 22)),   // the program's sign (bar.js): like the accent unless set by hand
      };
    } else {
      // the panels are lighter than the background: with a light background they push it down instead of passing white
      let bgL = 88 + l * 0.1;
      bgL = Math.min(bgL, 100 - 4 * k);
      v = {
        "--bg": hsl(h, s, bgL), "--panel": hsl(h, s * 0.6, bgL + 4 * k), "--panel2": hsl(h, s * 0.6, bgL - 2 * k),
        "--line": hsl(h, s, bgL - 13 * k), "--chip": hsl(h, s, bgL - 6 * k), "--ink": hsl(h, 10, 12), "--muted": hsl(h, 8, clamp(40 - 10 * (k - 1), 18, 55)),
        "--accent": hsl(A.h, A.s, A.l), "--accent-ink": "#fff", "--accent-soft": hsl(A.h, A.s * 0.7, clamp(bgL + 4 - 6 * k, 55, 97)),
        "--ok": "#2e7d4f", "--warn": "#b26a00", "--err": "#b3261e", "--graph-bg": hsl(h, s * 0.6, Math.min(100, bgL + 2 * k)),
        "--logo": hsl(A.h, A.s, A.l),
      };
    }
    for (const [name, val] of Object.entries(palette.custom || {})) if (name in v && /^#[0-9a-f]{6}$/i.test(String(val))) v[name] = val;
    return v;
  }

  // ``forceDark`` previews one palette (settings page) without changing the chosen mode.
  function apply(settings, forceDark) {
    if (!settings || !settings.theme) return;
    current = settings;
    const dark = forceDark === undefined ? isDark(settings) : forceDark;
    const palette = settings.theme[dark ? "dark" : "light"] || settings.theme;  // older cached settings had one palette
    const root = document.documentElement;
    const v = colours(palette, dark);
    // light ↔ dark glides over THEME_MS (the colour variables are registered as <color> in theme.css, so they interpolate)
    const was = root.dataset.theme, switching = was && was !== (dark ? "dark" : "light");
    if (switching) {
      root.classList.add("theme-anim");
      clearTimeout(animTimer);
      animTimer = setTimeout(() => root.classList.remove("theme-anim"), THEME_MS + 100);
    }
    for (const [k, val] of Object.entries(v)) root.style.setProperty(k, val);
    root.style.setProperty("--fs", (settings.ui && settings.ui.fontSize || 14) + "px");
    root.dataset.theme = dark ? "dark" : "light";
    root.style.colorScheme = dark ? "dark" : "light";
    try { localStorage.setItem(CACHE, JSON.stringify(settings)); } catch (e) { /* private mode */ }
    notify(settings, dark);
    if (switching) follow(settings, dark);
  }
  const notify = (settings, dark) => listeners.forEach(fn => { try { fn(settings, dark); } catch (e) { console.error(e); } });
  // pages drawing with the colours themselves (the garden canvas) are told again while the colours glide
  function follow(settings, dark) {
    const until = performance.now() + THEME_MS + 50, run = ++followRun;
    const step = () => {
      if (run !== followRun) return;
      notify(settings, dark);
      if (performance.now() < until) setTimeout(() => requestAnimationFrame(step), 70);
    };
    requestAnimationFrame(step);
  }

  async function load() {
    const r = await fetch("/api/sodas/settings");
    const s = await r.json();
    apply(s);
    return s;
  }

  try { const cached = JSON.parse(localStorage.getItem(CACHE) || "null"); if (cached) apply(cached); } catch (e) { /* ignore */ }
  // another tab of this browser applied (changed) the theme: pages that keep settings of their own decide (onRemote),
  // the others simply follow
  let remote = null;
  window.addEventListener("storage", e => {
    if (e.key !== CACHE || !e.newValue) return;
    let s;
    try { s = JSON.parse(e.newValue); } catch (err) { return; }
    if (remote) remote(s);
    else if (s && s.theme && (!current || JSON.stringify(s.theme) !== JSON.stringify(current.theme))) apply(s);
  });
  setInterval(() => current && current.theme.mode === "sun" && apply(current), 5 * 60 * 1000);
  window.KalbaTheme = {apply, load, isDark, sunTimes, colours, onRemote: fn => { remote = fn; }, onChange: fn => listeners.push(fn), get settings() { return current; }};
  if (!window.KALBA_NO_AUTOLOAD) load().catch(() => {});
})();
