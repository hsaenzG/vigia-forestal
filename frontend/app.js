/* Vigía Forestal — globo 3D de la deforestación global.
 * Lee archivos estáticos que la ingesta semanal deja en S3/CloudFront:
 *   data/loss.json (Hansen/GFW) · data/fires.json (NASA FIRMS) · data/alerts.json (agente)
 * La única llamada dinámica es POST /analyze (agente bajo demanda).
 */
(() => {
  "use strict";

  const CFG = Object.assign({ apiUrl: "", dataUrl: "data" }, window.VIGIA_CONFIG || {});
  const $ = (id) => document.getElementById(id);
  const fmt = new Intl.NumberFormat("es-MX");
  const regionNames = (() => {
    try { return new Intl.DisplayNames(["es"], { type: "region" }); } catch { return null; }
  })();

  const state = {
    from: 2001, to: 2024, mode: "cumulative", fireDays: 1, rank: "loss",
    loss: null, fires: null, features: [], byIso: new Map(), alerts: [],
    normMax: null, playing: false, selected: null, lastInteraction: 0,
  };

  // ------------------------------------------------------------------ utilidades
  const escapeHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const compactHa = (v) => v >= 1e6 ? `${(v / 1e6).toLocaleString("es-MX", { maximumFractionDigits: 1 })} M ha`
    : v >= 1e3 ? `${(v / 1e3).toLocaleString("es-MX", { maximumFractionDigits: 0 })} mil ha` : `${fmt.format(Math.round(v))} ha`;
  const timeAgo = (ts) => {
    const s = Math.max(0, (Date.now() - ts) / 1000);
    if (s < 60) return "hace segundos";
    if (s < 3600) return `hace ${Math.round(s / 60)} min`;
    if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
    return `hace ${Math.round(s / 86400)} d`;
  };
  const hhmm = (ts) => new Date(ts).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" });

  const STOPS = [[15, 61, 36], [63, 125, 32], [245, 158, 11], [239, 68, 68], [255, 45, 85]];
  function ramp(t) {
    t = Math.max(0, Math.min(1, t)) * (STOPS.length - 1);
    const i = Math.min(Math.floor(t), STOPS.length - 2), f = t - i, a = STOPS[i], b = STOPS[i + 1];
    return a.map((v, k) => Math.round(v + (b[k] - v) * f));
  }
  const rgba = (rgb, a) => `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${a})`;

  function countryName(iso, fallback) {
    const f = state.byIso.get(iso);
    const a2 = f && (f.properties.ISO_A2_EH || f.properties.ISO_A2);
    if (regionNames && a2 && /^[A-Z]{2}$/.test(a2)) {
      try { return regionNames.of(a2); } catch { /* sigue */ }
    }
    return (f && f.properties.NAME) || fallback || iso;
  }

  function centroid(feature) {
    const g = feature.geometry;
    const polys = g.type === "MultiPolygon" ? g.coordinates : [g.coordinates];
    const ring = polys.reduce((best, p) => (p[0].length > best.length ? p[0] : best), []);
    const lng = ring.reduce((s, p) => s + p[0], 0) / ring.length;
    const lat = ring.reduce((s, p) => s + p[1], 0) / ring.length;
    return { lat, lng };
  }

  async function getJson(path, bust) {
    // countries.geojson viaja con el frontend; los datos semanales vienen del CDN de datos
    const base = path === "countries.geojson" ? "data" : CFG.dataUrl;
    const url = `${base}/${path}${bust ? `?v=${bust}` : ""}`;
    const r = await fetch(url, { cache: "no-cache" });
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  }

  // ------------------------------------------------------------------ cálculos
  function yearIdx(y) { return state.loss ? state.loss.years.indexOf(y) : -1; }

  function lossValue(iso) {
    const c = state.loss && state.loss.countries[iso];
    if (!c) return null;
    const i1 = yearIdx(state.to);
    if (state.mode === "annual") return c.loss[i1] || 0;
    const i0 = yearIdx(state.from);
    let s = 0;
    for (let i = i0; i <= i1; i++) s += c.loss[i] || 0;
    return s;
  }

  function worldLoss() {
    if (!state.loss) return 0;
    const i1 = yearIdx(state.to), i0 = state.mode === "annual" ? i1 : yearIdx(state.from);
    let s = 0;
    for (let i = i0; i <= i1; i++) s += state.loss.world[i] || 0;
    return s;
  }

  function currentMax() {
    if (state.normMax) return state.normMax;
    let m = 1;
    for (const iso in state.loss.countries) m = Math.max(m, lossValue(iso) || 0);
    return m;
  }

  function fireWindow() {
    if (!state.fires || !state.fires.dates.length) return { n: 0, start: 0 };
    const n = state.fires.dates.length;
    return { n, start: Math.max(0, n - state.fireDays) };
  }

  function fireCells() {
    const { n, start } = fireWindow();
    if (!n) return [];
    const out = [];
    for (const [, lat, lng, iso, counts] of state.fires.cells) {
      let w = 0;
      for (let i = start; i < n; i++) w += counts[i];
      if (w > 0) out.push({ lat, lng, w, iso });
    }
    return out;
  }

  function firesByCountry() {
    const { n, start } = fireWindow();
    const m = new Map();
    if (!n) return m;
    for (const [, , , iso, counts] of state.fires.cells) {
      if (!iso) continue;
      let w = 0;
      for (let i = start; i < n; i++) w += counts[i];
      m.set(iso, (m.get(iso) || 0) + w);
    }
    return m;
  }

  function countryFireSeries(iso) {
    const dates = state.fires ? state.fires.dates : [];
    const row = dates.map(() => 0);
    if (state.fires) for (const [, , , ciso, counts] of state.fires.cells) if (ciso === iso) counts.forEach((c, i) => (row[i] += c));
    return dates.map((d, i) => ({ d, v: row[i] }));
  }

  // ------------------------------------------------------------------ globo
  const globe = new Globe($("globe"))
    .globeImageUrl("vendor/earth-night.jpg")
    .bumpImageUrl("vendor/earth-topology.png")
    .backgroundImageUrl("vendor/night-sky.png")
    .showAtmosphere(true)
    .atmosphereColor("#3ddc97")
    .atmosphereAltitude(0.2)
    // pérdida de cobertura: polígonos extruidos
    .polygonsTransitionDuration(700)
    .polygonCapColor((f) => polyColor(f, 0.82))
    .polygonSideColor((f) => polyColor(f, 0.18))
    .polygonStrokeColor(() => "rgba(255,255,255,0.12)")
    .polygonAltitude((f) => polyAltitude(f))
    .polygonLabel((f) => polyLabel(f))
    .onPolygonHover((f) => { state.hover = f; globe.polygonAltitude(globe.polygonAltitude()); $("globe").style.cursor = f ? "pointer" : "grab"; })
    .onPolygonClick((f) => selectCountry(f.properties.ADM0_A3, true))
    // focos de calor: columnas hexagonales
    .hexBinPointLat("lat").hexBinPointLng("lng").hexBinPointWeight("w")
    .hexBinResolution(3)
    .hexMargin(0.15)
    .hexTransitionDuration(800)
    .hexAltitude(({ sumWeight }) => 0.012 + Math.min(0.32, Math.sqrt(sumWeight) * 0.006))
    // colores OPACOS: miles de columnas translúcidas obligan a ordenar por frame (15 fps -> 40+)
    .hexTopColor(({ sumWeight }) => fireColor(sumWeight, 1))
    .hexSideColor(({ sumWeight }) => fireColor(sumWeight, 0.6))
    .hexLabel(({ sumWeight, points }) => `<div class="globe-tip"><b>🔥 ${fmt.format(sumWeight)} focos de calor</b><br/>${escapeHtml(countryName(points[0].iso, "Océano / costa"))}</div>`)
    // alertas: anillos pulsantes
    .ringColor((a) => (t) => (a.nivel === "alta" ? `rgba(255,59,92,${1 - t})` : `rgba(245,158,11,${1 - t})`))
    .ringMaxRadius(6)
    .ringPropagationSpeed(2.5)
    .ringRepeatPeriod(900)
    .ringAltitude(0.015);

  globe.controls().autoRotate = true;
  globe.controls().autoRotateSpeed = 0.35;
  globe.controls().addEventListener("start", () => (state.lastInteraction = Date.now()));
  globe.pointOfView({ lat: -5, lng: -40, altitude: window.innerWidth < 700 ? 3.4 : 2.3 });
  const resize = () => globe.width(window.innerWidth).height(window.innerHeight);
  window.addEventListener("resize", resize);
  resize();

  function polyColor(f, a) {
    const v = lossValue(f.properties.ADM0_A3);
    if (v == null) return `rgba(120,130,140,${a * 0.15})`;
    if (f === state.hover || f.properties.ADM0_A3 === state.selected) return `rgba(52,211,153,${a * 0.4})`;
    return rgba(ramp(Math.pow(v / currentMax(), 0.45)), a * (0.35 + 0.65 * Math.min(1, v / currentMax() * 4)));
  }

  function polyAltitude(f) {
    if (!$("layerLoss").checked) return 0.004;
    const v = lossValue(f.properties.ADM0_A3) || 0;
    const base = 0.004 + 0.04 * Math.pow(v / currentMax(), 0.6);
    return f === state.hover ? base + 0.01 : base;
  }

  function polyLabel(f) {
    const iso = f.properties.ADM0_A3, v = lossValue(iso), fires = firesByCountry().get(iso) || 0;
    const period = state.mode === "annual" ? `${state.to}` : `${state.from}–${state.to}`;
    return `<div class="globe-tip"><b>${escapeHtml(countryName(iso))}</b><br/>
      🌳 Pérdida ${period}: <b>${v == null ? "sin datos" : compactHa(v)}</b><br/>
      🔥 Focos de calor (${fireLabel()}): <b>${fmt.format(fires)}</b><br/>
      <span class="muted">Clic para ver detalle</span></div>`;
  }

  function fireColor(w, shade) {
    const t = Math.min(1, Math.log10(1 + w) / 3);
    const r = 255 * shade, g = (200 - 160 * t) * shade, b = (60 - 50 * t) * shade;
    return `rgb(${Math.round(r)},${Math.round(g)},${Math.round(b)})`;
  }

  // auto-rotación: se pausa mientras la persona interactúa
  setInterval(() => {
    const idle = Date.now() - state.lastInteraction > 8000;
    globe.controls().autoRotate = $("autoRotate").checked && idle && !state.playing;
  }, 1000);

  // ------------------------------------------------------------------ render
  function fireLabel() {
    return { 1: "último día", 2: "48 h", 3: "3 días", 7: "7 días" }[state.fireDays] || `${state.fireDays} días`;
  }

  function renderGlobe() {
    if (!state.loss) return;
    globe.polygonsData(state.features);
    globe.polygonCapColor(globe.polygonCapColor()); // reevalúa accesores -> transición animada
    globe.hexBinPointsData($("layerFires").checked ? fireCells() : []);
    renderRings();
  }

  function renderRings() {
    const rings = $("layerAlerts").checked ? state.alerts.filter((a) => a.lat != null).map((a) => ({ ...a, lng: a.lon })) : [];
    globe.ringsData(rings);
  }

  function bump(el) { el.classList.add("bump"); setTimeout(() => el.classList.remove("bump"), 300); }

  function renderKpis() {
    const w = worldLoss();
    const years = state.mode === "annual" ? 1 : state.to - state.from + 1;
    $("kpiPeriod").textContent = state.mode === "annual" ? state.to : `${state.from}–${state.to}`;
    $("kpiLoss").textContent = compactHa(w);
    // 1 cancha FIFA ≈ 0.714 ha
    $("kpiFields").textContent = fmt.format(Math.round(w / years / 525600 / 0.714));
    const fires = fireCells().reduce((s, c) => s + c.w, 0);
    const kf = $("kpiFires");
    if (kf.textContent !== fmt.format(fires)) { kf.textContent = fmt.format(fires); bump(kf); }
    $("kpiWindow").textContent = fireLabel();
    $("kpiAlerts").textContent = state.alerts.length;
  }

  function renderRanking() {
    let rows;
    if (state.rank === "loss") {
      rows = Object.keys(state.loss.countries).map((iso) => ({ iso, v: lossValue(iso) || 0, label: compactHa(lossValue(iso) || 0) }));
    } else {
      rows = [...firesByCountry()].map(([iso, v]) => ({ iso, v, label: `${fmt.format(v)} 🔥` }));
    }
    rows.sort((a, b) => b.v - a.v);
    rows = rows.slice(0, 8);
    const max = rows[0] ? rows[0].v || 1 : 1;
    $("ranking").innerHTML = rows.map((r, i) => `
      <li><button type="button" data-iso="${escapeHtml(r.iso)}">
        <span class="num">${i + 1}</span><span>${escapeHtml(countryName(r.iso, state.loss.countries[r.iso]?.name))}</span>
        <span class="val">${escapeHtml(r.label)}</span>
        <span class="bar" style="width:${Math.max(4, (100 * r.v) / max)}%"></span>
      </button></li>`).join("");
  }

  function renderAll() {
    $("fromLabel").textContent = state.from;
    $("toLabel").textContent = state.to;
    renderGlobe();
    renderKpis();
    renderRanking();
    if (state.selected) renderDetail(state.selected);
  }

  // ------------------------------------------------------------------ detalle
  function selectCountry(iso, fly) {
    state.selected = iso;
    state.lastInteraction = Date.now();
    $("detail").classList.remove("hidden");
    $("agentOut").classList.add("hidden");
    renderDetail(iso);
    globe.polygonCapColor(globe.polygonCapColor());
    const f = state.byIso.get(iso);
    if (fly && f) globe.pointOfView({ ...centroid(f), altitude: 1.5 }, 1200);
  }

  function renderDetail(iso) {
    const c = state.loss.countries[iso];
    $("detailName").textContent = countryName(iso, c && c.name);
    const total = c ? c.loss.slice(yearIdx(state.from), yearIdx(state.to) + 1).reduce((a, b) => a + b, 0) : 0;
    $("detailMeta").textContent = c ? `Pérdida ${state.from}–${state.to}: ${compactHa(total)} · ISO ${iso}` : "Sin datos de pérdida de cobertura";

    // barras de pérdida anual
    const svg = $("lossChart");
    if (c) {
      const max = Math.max(...c.loss, 1), n = c.loss.length, bw = 320 / n;
      svg.innerHTML = c.loss.map((v, i) => {
        const y = state.loss.years[i], h = (v / max) * 92, inRange = y >= state.from && y <= state.to;
        const col = inRange ? rgba(ramp(Math.pow(v / max, 0.6)), 0.95) : "rgba(148,163,184,0.25)";
        return `<rect x="${i * bw + 1}" y="${100 - h}" width="${bw - 2}" height="${h}" rx="1.5" fill="${col}"><title>${y}: ${fmt.format(v)} ha</title></rect>`;
      }).join("") + `<text x="0" y="109" fill="#8b98a8" font-size="9">${state.loss.years[0]}</text><text x="320" y="109" fill="#8b98a8" font-size="9" text-anchor="end">${state.loss.years[n - 1]}</text>`;
    } else svg.innerHTML = "";

    // barras de focos por día
    const series = countryFireSeries(iso), fmax = Math.max(1, ...series.map((s) => s.v)), fw = 320 / Math.max(1, series.length);
    $("fireChart").innerHTML = series.map((s, i) => {
      const h = (s.v / fmax) * 48;
      return `<rect x="${i * fw + 3}" y="${54 - h}" width="${fw - 6}" height="${h}" rx="2" fill="${i === series.length - 1 ? "rgba(255,106,26,0.5)" : "#ff6a1a"}"><title>${s.d}: ${fmt.format(s.v)} focos${i === series.length - 1 ? " (día en curso)" : ""}</title></rect>
        <text x="${i * fw + fw / 2}" y="66" fill="#8b98a8" font-size="9" text-anchor="middle">${s.d.slice(5)}</text>`;
    }).join("");
  }

  function renderAgentText(text) {
    return escapeHtml(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br/>");
  }

  async function analyzeSelected() {
    const iso = state.selected;
    if (!iso) return;
    const btn = $("analyzeBtn"), out = $("agentOut");
    btn.disabled = true;
    btn.textContent = "🤖 El agente está analizando…";
    out.classList.add("hidden");
    try {
      const r = await fetch(`${CFG.apiUrl}/analyze`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ iso3: iso, from_year: state.from, to_year: state.to }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
      const u = data.usage || {};
      out.className = `agent-out${data.mode === "agente" ? "" : " fallback"}`;
      out.innerHTML = `${renderAgentText(data.analysis)}
        <div class="footprint">${data.mode === "agente"
          ? `Huella de esta respuesta: <b>${fmt.format(u.total_tokens || 0)} tokens</b> · ${u.model_calls || 0} llamadas al modelo · ${(data.duration_ms / 1000).toFixed(1)} s · ${escapeHtml(data.model)}`
          : `⚠️ Respaldo sin modelo (${escapeHtml(data.error || "")}). Cifras calculadas directamente de los datos.`}</div>`;
    } catch (err) {
      out.className = "agent-out fallback";
      out.textContent = `No se pudo contactar al agente: ${err.message}`;
    } finally {
      btn.disabled = false;
      btn.textContent = "🤖 Analizar con el agente";
    }
  }

  // ------------------------------------------------------------------ feed en vivo
  function addFeed(kind, html, onClick, ts = Date.now()) {
    const li = document.createElement("li");
    li.className = kind;
    li.innerHTML = `<span class="t">${hhmm(ts)}</span>${html}`;
    if (onClick) { li.addEventListener("click", onClick); li.tabIndex = 0; li.addEventListener("keydown", (e) => e.key === "Enter" && onClick()); }
    $("feed").prepend(li);
    while ($("feed").children.length > 25) $("feed").lastChild.remove();
  }

  function addAlertToFeed(a, ts) {
    addFeed(`alert ${a.nivel === "media" ? "media" : ""}`,
      `<strong>🚨 ${a.iso3 ? `Repunte de focos de calor en ${escapeHtml(countryName(a.iso3, a.pais))}` : escapeHtml(a.titulo)}</strong>${escapeHtml(a.motivo)}<br/><span class="muted">${escapeHtml(a.fuente)}</span>`,
      () => { if (a.iso3) selectCountry(a.iso3, false); if (a.lat != null) globe.pointOfView({ lat: a.lat, lng: a.lon, altitude: 1.4 }, 1200); },
      ts);
  }

  // Reporte semanal que el agente dejó en data/alerts.json
  function renderReport(report) {
    $("feed").innerHTML = "";
    if (!report) {
      addFeed("data", "<strong>Sin reporte todavía</strong>El agente corre después de cada ingesta semanal.");
      return;
    }
    const ts = report.generated_at * 1000, u = report.usage || {};
    const footprint = report.model_invoked
      ? `Huella: <b>${fmt.format(u.total_tokens || 0)} tokens</b> · ${u.model_calls || 0} llamadas · ${(report.duration_ms / 1000).toFixed(1)} s · ${escapeHtml(report.model)}`
      : report.mode === "respaldo" ? "Respaldo sin modelo (reglas determinísticas)"
      : "El modelo no se invocó: <b>0 tokens</b>";
    state.alerts = report.alerts || [];
    [...state.alerts].reverse().forEach((a) => addAlertToFeed(a, ts));
    addFeed("data", `<strong>🤖 ${report.signals} señales revisadas · ${state.alerts.length} alertas</strong>${escapeHtml(report.summary)}<br/><span class="muted">${footprint}</span>`, null, ts);
    $("feed").append($("feed").firstChild); // el resumen va al final, las alertas arriba
    renderRings();
    renderKpis();
  }

  let toastTimer;
  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.add("hidden"), 5000);
  }

  function renderFreshness() {
    const d = state.fires && state.fires.dates;
    if (!d || !d.length) { $("liveBadge").textContent = "📡 SIN DATOS"; return; }
    const f = (s) => new Date(`${s}T12:00:00Z`).toLocaleDateString("es-MX", { day: "numeric", month: "short" });
    $("liveBadge").textContent = `📡 ${f(d[0])} – ${f(d[d.length - 1])}`;
    $("freshness").textContent = `Ingesta ${timeAgo(state.fires.updated_at * 1000)}`;
  }

  // ------------------------------------------------------------------ reproducción
  let playTimer = null;
  function stopPlay() {
    clearInterval(playTimer);
    playTimer = null;
    state.playing = false;
    state.normMax = null;
    $("playBtn").textContent = "▶ Ver el avance";
    $("bigYear").classList.remove("show");
    renderAll();
  }

  function play() {
    if (playTimer) return stopPlay();
    state.playing = true;
    const end = state.to;
    // normaliza con el valor final para que las columnas CREZCAN durante la animación
    let m = 1;
    if (state.mode === "annual") {
      const i0 = yearIdx(state.from), i1 = yearIdx(end);
      for (const iso in state.loss.countries) m = Math.max(m, ...state.loss.countries[iso].loss.slice(i0, i1 + 1));
    } else {
      for (const iso in state.loss.countries) m = Math.max(m, lossValue(iso) || 0);
    }
    state.normMax = m;
    state.to = state.from;
    $("toYear").value = state.to;
    $("playBtn").textContent = "⏸ Pausar";
    $("bigYear").classList.add("show");
    const step = () => {
      $("bigYear").textContent = state.to;
      $("toYear").value = state.to;
      renderAll();
      if (state.to >= end) { clearInterval(playTimer); playTimer = null; setTimeout(stopPlay, 1600); return; }
      state.to++;
    };
    step();
    playTimer = setInterval(step, 750);
  }

  // ------------------------------------------------------------------ controles
  function setYears(from, to) {
    state.from = Math.min(from, to);
    state.to = Math.max(from, to);
    $("fromYear").value = state.from;
    $("toYear").value = state.to;
    renderAll();
  }
  $("fromYear").addEventListener("input", (e) => { if (state.playing) stopPlay(); setYears(+e.target.value, state.to); });
  $("toYear").addEventListener("input", (e) => { if (state.playing) stopPlay(); setYears(state.from, +e.target.value); });
  $("playBtn").addEventListener("click", play);

  function wireSegmented(container, attr, apply) {
    container.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      container.querySelectorAll("button").forEach((x) => { x.classList.toggle("active", x === b); x.setAttribute(x.getAttribute("role") === "tab" ? "aria-selected" : "aria-checked", x === b); });
      apply(b.dataset[attr]);
      renderAll();
    }));
  }
  wireSegmented(document.querySelector(".filters .segmented"), "mode", (v) => (state.mode = v));
  wireSegmented($("fireWindow"), "days", (v) => (state.fireDays = +v));
  wireSegmented(document.querySelector(".tabs"), "rank", (v) => (state.rank = v));

  ["layerLoss", "layerFires", "layerAlerts"].forEach((id) => $(id).addEventListener("change", renderAll));
  $("dayTexture").addEventListener("change", (e) => globe.globeImageUrl(e.target.checked ? "vendor/earth-blue-marble.jpg" : "vendor/earth-night.jpg"));
  $("ranking").addEventListener("click", (e) => { const b = e.target.closest("button[data-iso]"); if (b) selectCountry(b.dataset.iso, true); });
  $("closeDetail").addEventListener("click", () => { state.selected = null; $("detail").classList.add("hidden"); globe.polygonCapColor(globe.polygonCapColor()); });
  $("analyzeBtn").addEventListener("click", analyzeSelected);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") $("closeDetail").click();
    if (e.key === " " && e.target === document.body) { e.preventDefault(); play(); }
  });

  // ------------------------------------------------------------------ arranque
  async function init() {
    // el navegador puede restaurar controles de una visita previa: arrancamos limpio
    ["layerLoss", "layerFires", "layerAlerts", "autoRotate"].forEach((id) => ($(id).checked = true));
    $("dayTexture").checked = false;
    const [geo, loss, fires] = await Promise.all([
      getJson("countries.geojson"),
      getJson("loss.json", Date.now()),
      getJson("fires.json", Date.now()).catch(() => ({ dates: [], cells: [], total: 0 })),
    ]);
    state.features = geo.features.filter((f) => f.properties.ADM0_A3 !== "ATA");
    state.features.forEach((f) => state.byIso.set(f.properties.ADM0_A3, f));
    state.loss = loss;
    state.fires = fires;
    const ys = loss.years;
    for (const id of ["fromYear", "toYear"]) { $(id).min = ys[0]; $(id).max = ys[ys.length - 1]; }
    state.from = ys[0];
    state.to = ys[ys.length - 1];
    setYears(state.from, state.to);
    renderFreshness();

    renderReport(await getJson("alerts.json").catch(() => null));
  }

  init().catch((err) => {
    console.error(err);
    toast(`No se pudieron cargar los datos: ${err.message}`);
  });

  // para depurar desde la consola
  window.vigia = { state, globe, play, selectCountry };
})();
