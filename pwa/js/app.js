/* Thinkuy — lógica del widget PWA (módulo ES). */
import { API, api, apiPost } from "./api.js";
import { esc, escapeHtml, showNotification } from "./dom.js";

const CONFIG_KEY = "thinkuy-config";

const DEFAULT_CONFIG = {
  keywords: "comunicación política, ecología de los medios, narrativas televisivas, ética y estética",
  langs: ["es", "pt"],
  sources: ["scielo", "crossref", "openalex", "redalyc"],
  limit: 20,
  days: 3650,
  sort: "relevance",
};

const state = {
  config: loadConfig(),
  deferredPrompt: null,
  radarExcluded: [],
  radarIncluded: [],
  radarExcludedNames: {},
};

const RADAR_FILTER_STORAGE_KEY = "thinkuy-radar-filters-v1";

function loadRadarFilters() {
  try {
    const raw = localStorage.getItem(RADAR_FILTER_STORAGE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    if (Array.isArray(saved.excluded)) {
      state.radarExcluded = saved.excluded.filter(x => typeof x === "string" && x.trim()).slice(0, 200);
    }
    if (Array.isArray(saved.included)) {
      state.radarIncluded = saved.included.filter(x => typeof x === "string" && x.trim()).slice(0, 200);
    }
    if (saved.names && typeof saved.names === "object") {
      state.radarExcludedNames = Object.fromEntries(
        Object.entries(saved.names).filter(([k, v]) => typeof k === "string" && typeof v === "string")
      );
    }
  } catch (e) { /* filtros inválidos: empezar limpio */ }
}

function saveRadarFilters() {
  try {
    localStorage.setItem(RADAR_FILTER_STORAGE_KEY, JSON.stringify({
      excluded: state.radarExcluded || [],
      included: state.radarIncluded || [],
      names: state.radarExcludedNames || {},
    }));
  } catch (e) { /* almacenamiento no disponible */ }
}

/* ---------------- config ---------------- */
function loadConfig() {
  try {
    const raw = localStorage.getItem(CONFIG_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (!parsed.limit || parsed.limit < 10) parsed.limit = 20;
      if (!parsed.days || parsed.days < 365) parsed.days = 3650;
      return { ...DEFAULT_CONFIG, ...parsed };
    }
  } catch (e) { /* ignorar */ }
  return { ...DEFAULT_CONFIG };
}
function saveConfig() {
  localStorage.setItem(CONFIG_KEY, JSON.stringify(state.config));
}

function readForm() {
  const kwEl = document.getElementById("keywords");
  if (kwEl) state.config.keywords = kwEl.value.trim();
  state.config.langs = [...document.querySelectorAll("#langs input:checked")].map(i => i.value);
  state.config.sources = [...document.querySelectorAll("#sources input:checked")].map(i => i.value);
  const limitEl = document.getElementById("limit");
  if (limitEl) state.config.limit = parseInt(limitEl.value, 10) || 5;
  const daysEl = document.getElementById("days");
  if (daysEl) state.config.days = parseInt(daysEl.value, 10) || 365;
  const sortEl = document.getElementById("sort");
  if (sortEl) state.config.sort = sortEl.value;
  saveConfig();
}
function writeForm() {
  const kwEl = document.getElementById("keywords");
  if (kwEl) kwEl.value = state.config.keywords || "";
  document.querySelectorAll("#langs input").forEach(i => { i.checked = (state.config.langs || []).includes(i.value); });
  document.querySelectorAll("#sources input").forEach(i => { i.checked = (state.config.sources || []).includes(i.value); });
  const limitEl = document.getElementById("limit");
  if (limitEl) limitEl.value = String(state.config.limit || 5);
  const daysEl = document.getElementById("days");
  if (daysEl) daysEl.value = String(state.config.days || 365);
  const sortEl = document.getElementById("sort");
  if (sortEl) sortEl.value = state.config.sort || "relevance";
}

/* ---------------- render ---------------- */
const SOURCE_NAMES = { scielo: "SciELO", crossref: "Crossref", openalex: "OpenAlex", redalyc: "Redalyc" };
const FIELD_NAMES = { title: "título", keywords: "palabras clave del artículo", abstract: "resumen" };

function keywordStrings(list) {
  return (Array.isArray(list) ? list : [])
    .map(k => {
      if (typeof k === "string") return k.trim();
      if (k && typeof k === "object") return String(k.keyword ?? k.k ?? k.display_name ?? "").trim();
      return "";
    })
    .filter(Boolean);
}

function selectableKeywordChip(keyword) {
  const text = String(keyword || "").trim();
  if (!text) return "";
  return `<button type="button" class="keyword-chip is-selectable" data-keyword-toggle data-keyword="${esc(text)}" aria-pressed="false" title="Seleccionar palabra clave para anclar">${esc(text)}</button>`;
}

function selectedKeywordsIn(scope) {
  const selected = [];
  scope.querySelectorAll('[data-keyword-toggle].is-selected').forEach(chip => {
    const value = String(chip.dataset.keyword ?? chip.textContent ?? "").trim();
    if (value && !selected.includes(value)) selected.push(value);
  });
  return selected;
}

function updateKeywordPinButtons(scope) {
  const selected = selectedKeywordsIn(scope);
  scope.querySelectorAll("[data-pin-selected-keywords]").forEach(button => {
    button.disabled = selected.length === 0;
    button.setAttribute("aria-disabled", selected.length === 0 ? "true" : "false");
  });
}

document.addEventListener("click", event => {
  const toggle = event.target instanceof Element ? event.target.closest("[data-keyword-toggle]") : null;
  if (toggle) {
    const selected = toggle.classList.toggle("is-selected");
    toggle.setAttribute("aria-pressed", selected ? "true" : "false");
    const scope = toggle.closest("[data-keyword-scope]");
    if (scope) updateKeywordPinButtons(scope);
    return;
  }

  const pinButton = event.target instanceof Element ? event.target.closest("[data-pin-selected-keywords],[data-pin-all-keywords]") : null;
  if (!pinButton) return;
  const scope = pinButton.closest("[data-keyword-scope]");
  if (!scope) return;
  const keywords = pinButton.hasAttribute("data-pin-all-keywords")
    ? [...scope.querySelectorAll("[data-keyword-toggle]")].map(chip => String(chip.dataset.keyword ?? "").trim()).filter(Boolean)
    : selectedKeywordsIn(scope);
  const unique = [...new Set(keywords)];
  if (!unique.length) return;
  window.pinRadarKeywords(unique, pinButton.dataset.pinLabel || "Radar: selección de palabras clave");
});

function authorsLine(a) {
  const aus = (a.authors || []).map(au => `${au.family || ""} ${au.given || ""}`.trim()).filter(Boolean);
  if (!aus.length) return "Autores no disponibles";
  if (aus.length <= 3) return aus.join(", ");
  return `${aus.slice(0, 3).join(", ")} et al.`;
}

function articleCard(a) {
  const dateStr = (a.pub_date || "").slice(0, 10);
  const badges = [];
  badges.push(`<span class="badge src-${a.source}">◉ ${SOURCE_NAMES[a.source] || a.source}</span>`);
  if (a.quartile) badges.push(`<span class="badge quartile q-${a.quartile.toLowerCase()}">${a.quartile} · SJR</span>`);
  if (a.access === "oa") badges.push(`<span class="badge oa">acceso abierto</span>`);
  if (a.cited_by > 0) badges.push(`<span class="badge cited">◆ ${a.cited_by} citas</span>`);
  if (a.lang) badges.push(`<span class="badge lang">${esc(a.lang)}</span>`);

  const kwList = keywordStrings(a.display_keywords?.length ? a.display_keywords : a.keywords);
  const scopeLabel = `Radar · ${(a.title || "artículo").slice(0, 80)}`;
  const keywordSource = a.keyword_source === "derived" ? ` <span class="sub">(sugeridas)</span>` : "";
  const kws = kwList.map(selectableKeywordChip).join("");

  let why = "";
  const convWhy = (a.conversation && a.conversation.why) || [];
  if (convWhy.length) {
    why += `<div class="why"><b>⦿ ¿Por qué este artículo?</b> ${convWhy.map(esc).join(" · ")}</div>`;
  } else if (a.matched && a.matched.length) {
    const chips = a.matched.map(m =>
      `<span class="kw">«${esc(m.keyword)}»</span> en ${FIELD_NAMES[m.field] || m.field}`
    ).join(" · ");
    why = `<div class="why"><b>⦿ ¿Por qué este artículo?</b> Coincide con: ${chips}</div>`;
  }
  if (a.conversation && a.conversation.cites_anchor) {
    badges.push(`<span class="badge cited">cita el corpus</span>`);
  }
  if (a.thematic_fields && a.thematic_fields.length) {
    badges.push(`<span class="badge thematic-field">🏷️ ${esc(a.thematic_fields[0].name)}</span>`);
  }

  const exportLinks = ["apa", "bibtex", "ris"].map(f =>
    `<a href="/api/articles/${encodeURIComponent(a.doi || "")}/citation?format=${f}" download>${f.toUpperCase()}</a>`
  ).join("");
  const trackerBtn = a.doi ? `<button class="btn-track-doi" data-doi="${esc(a.doi)}" data-title="${esc(a.title)}" title="Ver difusión web, Wikipedia, citas y menciones">🌐 Huella Web</button>` : "";

  return `
  <article class="article" data-keyword-scope>
    <span class="when">${dateStr || ""}</span>
    <h3><a href="${esc(a.url || `https://doi.org/${a.doi}`)}" target="_blank" rel="noopener">${esc(a.title)}</a></h3>
    <div class="meta">${esc(authorsLine(a))} — <span class="journal">${esc(a.journal_title || "Revista")}</span>${a.volume ? ` <b>${esc(a.volume)}</b>` : ""}${a.issue ? `(${esc(a.issue)})` : ""}${a.year ? ` · ${a.year}` : ""}</div>
    <div class="badges">${badges.join("")}</div>
    ${why}
    ${kws ? `<div class="keywords-line"><span class="sub">Selecciona palabras clave para anclar:${keywordSource}</span> ${kws}<div class="keyword-actions"><button type="button" class="btn sm cool" data-pin-selected-keywords data-pin-label="${esc(scopeLabel)}" disabled>📌 Anclar seleccionadas</button></div></div>` : ""}
    <div class="export"><span class="sep">Citar:</span>${exportLinks}${trackerBtn}</div>
  </article>`;
}

async function renderFeed(retry = true) {
  const feed = document.getElementById("feed");
  // Skeletons mientras carga (UX-4)
  feed.innerHTML = '<div class="skeleton"></div>'.repeat(Math.min(state.config.limit || 5, 5));
  try {
    const params = {
      keywords: state.config.keywords,
      langs: state.config.langs.join(","),
      sources: state.config.sources.join(","),
      limit: state.config.limit,
      days: state.config.days,
      sort: state.config.sort,
    };
    if (state.config.journal) {
      params.journal = state.config.journal;
    }
    const data = await api("/feed", params);
    document.getElementById("stat-feed").textContent = String(data.count);

    let journalBadgeHtml = "";
    if (state.config.journal) {
      journalBadgeHtml = `
        <div class="active-filter-badge" style="display:inline-flex; align-items:center; gap:8px; margin-bottom:16px; background:rgba(97,145,150,0.15); border:1px solid var(--primary); padding:6px 14px; border-radius:20px; font-size:0.85rem;">
          <span class="material-symbols-outlined text-[16px]">menu_book</span>
          <span>Revista: <strong>${esc(state.config.journal)}</strong></span>
          <button id="btn-clear-journal-filter" style="background:none; border:none; cursor:pointer; color:var(--primary); font-weight:bold; font-size:1.1rem; padding:0 4px; line-height:1;" title="Quitar filtro de revista">&times;</button>
        </div>
      `;
    }

    if (!data.articles.length) {
      // Ayuda cuando no hay señales: cuántas coincidencias hay en una ventana mayor
      let hintHtml = "";
      let rows = [];
      if (data.hints && data.hints.wider_window) {
        rows = data.hints.wider_window.keyword_counts.filter(k => k.count > 0);
        if (rows.length) {
          hintHtml = `<p class="sub" style="margin-top:8px">Con ventana de 1 año:
            ${rows.map(k => `«${esc(k.keyword)}» → <b>${k.count}</b>`).join(" · ")}</p>
            <button class="btn sm cool" id="btn-widen" style="margin-top:10px">Ampliar ventana a 1 año</button>`;
        } else {
          hintHtml = `<p class="sub" style="margin-top:8px">Sin coincidencias ni en el último año en el catálogo actual.</p>`;
        }
      }
      feed.innerHTML = `${journalBadgeHtml}<div class="empty"><p>🛰️ Sin señales con estos filtros.</p>
        <p class="sub">Prueba con otras palabras clave, revisa los separadores o quita los filtros activos.</p>
        ${hintHtml}</div>`;
      if (rows.length) {
        document.getElementById("btn-widen")?.addEventListener("click", () => {
          state.config.days = 365;
          document.getElementById("days").value = "365";
          saveConfig();
          renderFeed();
        });
      }
      document.getElementById("btn-clear-journal-filter")?.addEventListener("click", () => {
        delete state.config.journal;
        renderFeed();
      });
      return;
    }
    feed.innerHTML = journalBadgeHtml + data.articles.map(articleCard).join("");
    document.getElementById("btn-clear-journal-filter")?.addEventListener("click", () => {
      delete state.config.journal;
      renderFeed();
    });
  } catch (e) {
    if (retry) { setTimeout(() => renderFeed(false), 1500); return; }
    feed.innerHTML = `<div class="empty"><p>⚠️ No se pudo contactar el radar: ${esc(e.message)}</p><p class="sub">Verifica que el backend esté corriendo (uvicorn) y recarga. Si abriste la app hace rato, prueba <a href="./" style="color:var(--cyan)">recargar la página</a>.</p></div>`;
  }
}

async function renderStats() {
  try {
    const st = await api("/stats");
    const artEl = document.getElementById("stat-articles");
    const jrnEl = document.getElementById("stat-journals");
    const hdrEl = document.getElementById("stat-articles-header");
    if (artEl) artEl.textContent = st.articles;
    if (jrnEl) jrnEl.textContent = st.journals;
    if (hdrEl) {
      hdrEl.textContent = "Sonda en Vivo: OpenAlex · Crossref";
      hdrEl.title = `Búsquedas en tiempo real contra bases globales. Repositorio local fuera de línea: ${st.articles} artículos.`;
    }
  } catch (e) { /* no crítico */ }
}

async function renderSources() {
  const box = document.getElementById("sources-status");
  if (!box) return;
  try {
    const { sources } = await api("/sources");
    box.innerHTML = Object.entries(sources).map(([name, s]) => {
      const ok = s.status === "ok";
      const cls = ok ? "ok" : (s.status === "error" ? "err" : "never");
      const stateTxt = ok ? "✔ operativa" : (s.status === "error" ? "✖ no disponible" : "sin cosecha aún");
      const detail = s.finished_at ? `${s.articles_found || 0} artículos · ${(s.finished_at || "").replace("T", " ").slice(0, 16)} UTC` : (s.notes || "");
      return `<div class="src-item ${cls}"><div class="name">${SOURCE_NAMES[name] || name}</div><div class="state">${stateTxt}</div><div class="detail">${esc(detail)}</div></div>`;
    }).join("");
  } catch (e) {
    box.innerHTML = `<span>No disponible</span>`;
  }
}

async function refreshSuggest() {
  const input = document.getElementById("keywords");
  const dl = document.getElementById("kw-suggest");
  if (!input || !dl) return;
  const q = (input.value || "").split(",").pop().trim();
  if (q.length < 2) return;
  try {
    const { keywords } = await api("/suggest", { q, limit: 10 });
    dl.innerHTML = keywords.map(k => `<option value="${esc(k)}">`).join("");
  } catch (e) { /* silencioso */ }
}

/* ---------------- radar anclado (watch) ---------------- */
async function loadWatch() {
  const box = document.getElementById("watch-list");
  if (!box) return;
  try {
    const data = await api("/watch/total");
    const feedStat = document.getElementById("stat-feed");
    if (feedStat) feedStat.textContent = String(data.total || 0);

    if (!data.pins.length) {
      box.innerHTML = `<p class="sub" style="margin: 8px 0;">No tienes vigilancias activas todavía. Usa el botón «📌 Anclar» en el Explorador o «Anclar Vigilancia» en el Diagnóstico para que el radar te avise cuando ingresen nuevas publicaciones.</p>`;
      refreshNotifyButton();
      return;
    }
    box.innerHTML = data.pins.map(p => `
      <div class="pin-card ${p.new > 0 ? 'has-new' : ''}">
        <div class="pin-info">
          <div class="pin-label">
            <span class="material-symbols-outlined pin-icon" style="font-size: 16px;">bookmark</span>
            <strong>${esc(p.label)}</strong>
          </div>
          <div class="pin-kw">Descriptores vigilados: <code>${esc(p.keywords)}</code></div>
        </div>
        <div class="pin-actions">
          <span class="pin-new-badge ${p.new > 0 ? 'highlight' : ''}">
            ${p.new > 0 ? `◉ ${p.new} nueva${p.new === 1 ? '' : 's'}` : '✓ Al día'}
          </span>
          ${p.new > 0 ? `<button class="btn btn-primary sm" data-pin-see="${p.id}">Ver ${p.new} nueva${p.new === 1 ? '' : 's'}</button>` : `<button class="btn btn-ghost sm" data-pin-see="${p.id}">Revisar</button>`}
          <button class="btn btn-ghost sm danger-hover" data-pin-del="${p.id}" title="Eliminar vigilancia">✕</button>
        </div>
      </div>`).join("");
    box.querySelectorAll("[data-pin-see]").forEach(b =>
      b.addEventListener("click", () => showWatchNew(parseInt(b.dataset.pinSee, 10))));
    box.querySelectorAll("[data-pin-del]").forEach(b =>
      b.addEventListener("click", () => delWatch(parseInt(b.dataset.pinDel, 10))));
    refreshNotifyButton();
    maybeNotify(data.total);
  } catch (e) {
    box.innerHTML = `<p class="sub">Sin anclas todavía.</p>`;
  }
}

async function addWatch() {
  const kwEl = document.getElementById("keywords");
  const keywords = kwEl ? kwEl.value.trim() : "";
  if (!keywords) return;
  try {
    await api("/watch", {}, { method: "POST", body: { keywords } });
    await loadWatch();
  } catch (e) {
    showNotification({ title: "No se pudo anclar", message: e.message, type: "error" });
  }
}

async function delWatch(id) {
  try {
    await api(`/watch/${id}`, {}, { method: "DELETE" });
    await loadWatch();
    renderFeed();
  } catch (e) { /* ignorar */ }
}

async function showWatchNew(id) {
  const feed = document.getElementById("feed");
  feed.innerHTML = '<div class="skeleton"></div>'.repeat(3);
  try {
    const data = await api(`/watch/${id}/new`, { mark: 1, limit: 20 });
    const back = `<div class="why" style="margin-bottom:14px"><b>⦿ Nuevas publicaciones para «${esc(data.label)}»</b>
      <button class="btn sm cool" id="btn-back-radar" style="margin-left:10px">← Volver al radar</button></div>`;
    if (!data.articles.length) {
      feed.innerHTML = back + `<div class="empty"><p>✅ Al día. No hay publicaciones nuevas para este ancla.</p></div>`;
    } else {
      feed.innerHTML = back + data.articles.map(articleCard).join("");
    }
    document.getElementById("btn-back-radar").addEventListener("click", () => renderFeed());
    await loadWatch();
  } catch (e) {
    feed.innerHTML = `<div class="empty"><p>⚠️ ${esc(e.message)}</p></div>`;
  }
}

/* ---------------- notificaciones del navegador ---------------- */
const NOTIFY_COOLDOWN_KEY = "radar-obcc-notify-at";
async function maybeNotify(total) {
  try {
    if (!total || Notification.permission !== "granted" || !document.hidden) return;
    const last = parseInt(localStorage.getItem(NOTIFY_COOLDOWN_KEY) || "0", 10);
    if (Date.now() - last < 15 * 60 * 1000) return;
    localStorage.setItem(NOTIFY_COOLDOWN_KEY, String(Date.now()));
    const n = new Notification("Thinkuy", {
      body: `◉ ${total} nueva${total === 1 ? "" : "s"} publicación${total === 1 ? "" : "es"} coincide${total === 1 ? "" : "n"} con tus keywords ancladas`,
      icon: "icons/icon-192.png",
      tag: "radar-new",
    });
    n.onclick = () => { window.focus(); n.close(); };
  } catch (e) { /* sin permiso o no soportado */ }
}

function refreshNotifyButton() {
  const btn = document.getElementById("btn-notify");
  if (!btn) return;
  if ("Notification" in window && Notification.permission === "granted") {
    btn.innerHTML = `<span class="material-symbols-outlined text-[16px]">notifications_active</span> <span>Alertas del navegador activadas</span>`;
    btn.classList.add("btn-primary");
    btn.classList.remove("btn-secondary");
    btn.title = "Las notificaciones en segundo plano del navegador están activadas";
  } else {
    btn.innerHTML = `<span class="material-symbols-outlined text-[16px]">notifications</span> <span>Activar notificaciones</span>`;
    btn.classList.add("btn-secondary");
    btn.classList.remove("btn-primary");
    btn.title = "Permitir avisos en segundo plano del navegador cuando lleguen nuevos papers";
  }
}

/* ---------------- temas y conceptos en tendencia ---------------- */
async function renderTrendingTopics() {
  const box = document.getElementById("trending-topics-list");
  if (!box) return;
  try {
    const data = await api("/topics/trending", { limit: 16 });
    const topics = data.topics || [];
    if (!topics.length) {
      box.innerHTML = `<span class="sub">No hay temas suficientes registrados aún.</span>`;
      return;
    }
    box.innerHTML = topics.map(t => `
      <button type="button" class="topic-tag-chip" data-topic="${esc(t.topic)}" title="Explorar publicaciones sobre «${esc(t.topic)}»">
        <span>#${esc(t.topic)}</span>
        <span class="topic-count">${t.count}</span>
      </button>
    `).join("");

    box.querySelectorAll(".topic-tag-chip").forEach(chip => {
      chip.addEventListener("click", () => {
        const topic = chip.dataset.topic;
        if (!topic) return;

        // Cargar en el input de keywords y actualizar config
        const kwInput = document.getElementById("keywords");
        if (kwInput) kwInput.value = topic;
        
        // Sincronizar con radar y matching
        const radarTopic = document.getElementById("radar-topic");
        if (radarTopic) radarTopic.value = topic;
        const journalInput = document.getElementById("match-journal-input");
        if (journalInput) journalInput.value = topic;

        readForm();
        renderFeed();
        refreshSuggest();

        // Scroll suave al feed de artículos si está lejos
        const feed = document.getElementById("feed");
        if (feed) {
          feed.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
    });
  } catch (e) {
    box.innerHTML = `<span class="sub">Temas en tendencia no disponibles.</span>`;
  }
}

/* ---------------- radar de proximidad autoral ---------------- */
const SECTOR_COLORS = ["#22D3EE", "#F59E0B", "#34D399", "#A78BFA", "#F472B6", "#60A5FA", "#FBBF24", "#F87171", "#4ADE80"];

function radarSectorColor(sector, sectors) {
  const i = sectors.indexOf(sector);
  return SECTOR_COLORS[i >= 0 ? i : i % SECTOR_COLORS.length] || "#94A3B8";
}

// Sectores temáticos ocultos por el filtro de leyenda (solo cliente, no recalcula el radar).
const radarHiddenSectors = new Set();

function radarSectorLabel(sector, labels) {
  if (labels && labels[sector]) return labels[sector];
  return String(sector || "general").replace(/_/g, " ");
}

function renderRadarSectorLegend(allNodes, sectors, labels) {
  const holder = document.getElementById("radar-sector-legend");
  if (!holder) return;
  if (!sectors || !sectors.length) {
    holder.innerHTML = "";
    holder.hidden = true;
    return;
  }
  const counts = {};
  (allNodes || []).forEach(n => {
    counts[n.sector] = (counts[n.sector] || 0) + 1;
  });
  holder.hidden = false;
  holder.innerHTML = `<span class="radar-sector-legend-title">Sectores:</span> ` + sectors.map(s => {
    const off = radarHiddenSectors.has(s);
    const nm = radarSectorLabel(s, labels);
    return `<button type="button" class="radar-sector-chip${off ? " is-off" : ""}" data-sector="${esc(s)}" aria-pressed="${off ? "false" : "true"}" title="${off ? "Mostrar" : "Ocultar"} autores de «${esc(nm)}»">`
      + `<span class="radar-sector-dot" style="background:${radarSectorColor(s, sectors)}"></span>`
      + `<span>${esc(nm)}</span><b>${counts[s] || 0}</b></button>`;
  }).join("");
  holder.querySelectorAll(".radar-sector-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const s = chip.dataset.sector;
      if (radarHiddenSectors.has(s)) radarHiddenSectors.delete(s);
      else radarHiddenSectors.add(s);
      renderRadar({ keepSectorFilter: true });
    });
  });
}

async function renderRadar(opts = {}) {
  const canvas = document.getElementById("radar-canvas");
  const legend = document.getElementById("radar-legend") || document.getElementById("radar-status-telemetry");
  if (!canvas) return;
  // Una búsqueda nueva reinicia el filtro de sectores; los toggles de leyenda lo conservan.
  if (!opts.keepSectorFilter) radarHiddenSectors.clear();
  const topic = document.getElementById("radar-topic") ? document.getElementById("radar-topic").value.trim() : "";
  const doi = document.getElementById("radar-doi") ? document.getElementById("radar-doi").value.trim() : "";
  const weightsEl = document.getElementById("radar-weights");
  const weights = weightsEl ? weightsEl.value : "0.4,0.3,0.2,0.1";
  const minWorksEl = document.getElementById("radar-min-works");
  const min_works = minWorksEl ? parseInt(minWorksEl.value, 10) || 1 : 1;
  if (!topic && !doi) {
    if (legend) legend.innerHTML = `<span class="sub">Escribe un tema (o DOI) y pulsa «Generar radar».</span>`;
    renderRadarExcludedBar();
    return;
  }

  renderRadarExcludedBar();
  if (legend) legend.innerHTML = `<span class="sub">Calculando proximidad…</span>`;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  let data;
  try {
    const params = {
      topic,
      doi,
      weights,
      limit: 30,
      min_works,
    };
    const affDivEl = document.getElementById("radar-affinity-divisor");
    const prodConstEl = document.getElementById("radar-productivity-constant");
    const minDistEl = document.getElementById("radar-min-dist");
    const recDecayEl = document.getElementById("radar-recency-decay");
    const normWeightsEl = document.getElementById("radar-normalize-weights");

    if (affDivEl && affDivEl.value) params.affinity_divisor = parseInt(affDivEl.value, 10);
    if (prodConstEl && prodConstEl.value) params.productivity_constant = parseFloat(prodConstEl.value);
    if (minDistEl && minDistEl.value) params.min_dist = parseFloat(minDistEl.value);
    if (recDecayEl && recDecayEl.value) params.recency_decay = recDecayEl.value;
    if (normWeightsEl) params.normalize_weights = normWeightsEl.checked;

    if (state.radarExcluded && state.radarExcluded.length) {
      params.excluded = state.radarExcluded.join(",");
    }
    if (state.radarIncluded && state.radarIncluded.length) {
      params.included = state.radarIncluded.join(",");
    }
    data = await api("/radar", params);
  } catch (e) {
    legend.innerHTML = `<span class="sub">⚠ ${esc(e.message)}</span>`;
    return;
  }

  const W = canvas.width, H = canvas.height;
  const cx = W / 2, cy = H / 2, R = Math.min(W, H) / 2 - 46;

  const scale = 1 / 100; // las coordenadas vienen en unidades de radio 0..100
  const nodes = (data.nodes || []).filter(n => !radarHiddenSectors.has(n.sector));
  nodes.forEach(n => {
    if (n.id && n.name) {
      state.radarExcludedNames[n.id] = n.name;
    }
  });
  const sectors = data.sectors || [];
  const sectorLabels = data.sector_labels || {};
  canvas._sectors = sectors;
  canvas._sectorLabels = sectorLabels;
  canvas._radarWeights = data.weights || null;
  renderRadarSectorLegend(data.nodes || [], sectors, sectorLabels);
  const pos = {};
  nodes.forEach(n => {
    pos[n.id] = { x: cx + n.x * R * scale, y: cy - n.y * R * scale };
  });

  const maxDeg = Math.max(1, ...nodes.map(n => n.degree || 0));
  const nodePositions = [];
  nodes.forEach(n => {
    const p = pos[n.id];
    if (!p) return;
    const r = 4 + 6 * (n.degree || 0) / maxDeg;
    nodePositions.push({ ...n, px: p.x, py: p.y, r });
  });

  // Pass 2: compute label bounding boxes with font sizing and overlap prevention
  const LABEL_PAD = 3;
  const LABEL_MARGIN = 2;

  function labelsOverlap(a, b) {
    return !(
      a.x + a.w + LABEL_MARGIN < b.x ||
      b.x + b.w + LABEL_MARGIN < a.x ||
      a.y + a.h + LABEL_MARGIN < b.y ||
      b.y + b.h + LABEL_MARGIN < a.y
    );
  }

  function getLabelMetrics(text, fontSize) {
    ctx.font = `${fontSize}px sans-serif`;
    const tw = ctx.measureText(text).width;
    const lh = fontSize === 9 ? 11 : 12;
    return { w: tw + LABEL_PAD * 2, h: lh, fontSize };
  }

  const labels = nodePositions.map(n => {
    const text = n.name.split(" ").slice(0, 2).join(" ");
    const m = getLabelMetrics(text, 10);
    return {
      node: n,
      text,
      fontSize: 10,
      w: m.w,
      h: m.h,
      x: n.px - m.w / 2,
      y: n.py - n.r - m.h - 2,
      nx: n.px,
      ny: n.py,
      nr: n.r,
      degree: n.degree || 0,
      displaced: false,
      hidden: false,
    };
  });

  // Sort labels so higher-degree nodes take priority positioning
  const sortedIndices = labels.map((_, i) => i).sort((a, b) => labels[b].degree - labels[a].degree);
  const placed = [];

  function findLabelPosition(lbl, w, h) {
    // 8 candidate positions around the node
    const offsets = [
      { dx: -w / 2, dy: -lbl.nr - h - 2 },          // above (default)
      { dx: -w / 2, dy: lbl.nr + 4 },               // below
      { dx: lbl.nr + 4, dy: -h / 2 },               // right
      { dx: -w - lbl.nr - 4, dy: -h / 2 },         // left
      { dx: lbl.nr + 2, dy: -lbl.nr - h },          // upper-right
      { dx: -w - lbl.nr - 2, dy: -lbl.nr - h },    // upper-left
      { dx: lbl.nr + 2, dy: lbl.nr + 2 },           // lower-right
      { dx: -w - lbl.nr - 2, dy: lbl.nr + 2 },     // lower-left
    ];

    for (const off of offsets) {
      const cx = lbl.nx + off.dx;
      const cy = lbl.ny + off.dy;
      if (cx >= 6 && cx + w <= W - 6 && cy >= 6 && cy + h <= H - 6) {
        const cand = { x: cx, y: cy, w, h };
        if (!placed.some(p => labelsOverlap(cand, p))) {
          return { x: cx, y: cy, found: true };
        }
      }
    }

    // Nudge en espiral/pasos radiales si las 8 posiciones inmediatas colisionan
    const stepDistances = [14, 22, 30, 40, 50];
    const angles = [0, Math.PI / 4, Math.PI / 2, 3 * Math.PI / 4, Math.PI, 5 * Math.PI / 4, 3 * Math.PI / 2, 7 * Math.PI / 4];
    for (const dist of stepDistances) {
      for (const ang of angles) {
        const cx = lbl.nx + Math.cos(ang) * (lbl.nr + dist) - w / 2;
        const cy = lbl.ny + Math.sin(ang) * (lbl.nr + dist) - h / 2;
        if (cx >= 6 && cx + w <= W - 6 && cy >= 6 && cy + h <= H - 6) {
          const cand = { x: cx, y: cy, w, h };
          if (!placed.some(p => labelsOverlap(cand, p))) {
            return { x: cx, y: cy, found: true };
          }
        }
      }
    }

    return { found: false };
  }

  for (const idx of sortedIndices) {
    const lbl = labels[idx];
    let res = findLabelPosition(lbl, lbl.w, lbl.h);
    if (!res.found) {
      const m9 = getLabelMetrics(lbl.text, 9);
      res = findLabelPosition(lbl, m9.w, m9.h);
      if (res.found) {
        lbl.fontSize = 9;
        lbl.w = m9.w;
        lbl.h = m9.h;
      }
    }

    if (res.found) {
      lbl.x = res.x;
      lbl.y = res.y;
      lbl.displaced = Math.hypot(res.x + lbl.w / 2 - lbl.nx, res.y + lbl.h / 2 - lbl.ny) > (lbl.nr + lbl.h + 4);
      placed.push({ x: lbl.x, y: lbl.y, w: lbl.w, h: lbl.h });
    } else {
      lbl.hidden = true;
    }
  }

  function drawRadarScene() {
    ctx.clearRect(0, 0, W, H);

    // círculos concéntricos del radar
    ctx.strokeStyle = "rgba(148,163,184,.28)";
    ctx.lineWidth = 1;
    for (const f of [0.33, 0.66, 1]) {
      ctx.beginPath(); ctx.arc(cx, cy, R * f, 0, Math.PI * 2); ctx.stroke();
    }
    ctx.beginPath(); ctx.moveTo(cx - R, cy); ctx.lineTo(cx + R, cy); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy + R); ctx.stroke();

    // centro: tema o artículo
    const isCenterSelected = canvas._selectedNodeId === "__center__";
    const centerTitle = data.center?.label || (data.center?.doi ? `DOI: ${data.center.doi}` : (topic || "tu pregunta"));

    ctx.fillStyle = isCenterSelected ? "#38BDF8" : "#22D3EE";
    ctx.beginPath(); ctx.arc(cx, cy, isCenterSelected ? 9 : 7, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = isCenterSelected ? "#FFFFFF" : "rgba(14, 165, 233, 0.8)";
    ctx.lineWidth = 2;
    ctx.stroke();

    if (isCenterSelected) {
      ctx.strokeStyle = "rgba(56, 189, 248, 0.8)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(cx, cy, 14, 0, Math.PI * 2);
      ctx.stroke();
    }

    ctx.fillStyle = isCenterSelected ? "#38BDF8" : "#8FA0D4";
    ctx.font = isCenterSelected ? "bold 12px sans-serif" : "12px sans-serif";
    ctx.textAlign = "center";
    const shortLabel = centerTitle.length > 32 ? centerTitle.slice(0, 30) + "…" : centerTitle;
    ctx.fillText(shortLabel, cx, cy + 22);

    // aristas (red multiplex: coautoría=cíticas, citación=ambar, revista=gris)
    const edgeStyle = { coauthor: "rgba(34,211,238,.5)", citation: "rgba(245,158,11,.5)", journal: "rgba(148,163,184,.22)" };
    (data.edges || []).forEach(e => {
      const a = pos[e.a], b = pos[e.b];
      if (!a || !b) return;
      ctx.strokeStyle = edgeStyle[e.type] || "rgba(148,163,184,.3)";
      ctx.lineWidth = e.type === "citation" ? 1.4 : Math.min(3, 0.6 + e.weight * 0.5);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      if (e.type === "citation") {
        const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
        const ax = b.x - dx / len * 8, ay = b.y - dy / len * 8;
        ctx.fillStyle = "rgba(245,158,11,.7)";
        ctx.beginPath();
        ctx.moveTo(b.x, b.y);
        ctx.lineTo(ax - dy / len * 4, ay + dx / len * 4);
        ctx.lineTo(ax + dy / len * 4, ay - dx / len * 4);
        ctx.fill();
      }
    });

    // Pass 4: draw labels with background and optional leader lines
    for (const lbl of labels) {
      if (lbl.hidden) continue;

      if (lbl.displaced) {
        ctx.strokeStyle = "rgba(148, 163, 184, 0.45)";
        ctx.lineWidth = 0.8;
        ctx.setLineDash([2, 2]);
        ctx.beginPath();
        ctx.moveTo(lbl.nx, lbl.ny);
        ctx.lineTo(lbl.x + lbl.w / 2, lbl.y + lbl.h / 2);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      ctx.fillStyle = "rgba(11, 18, 38, 0.85)";
      ctx.fillRect(lbl.x, lbl.y, lbl.w, lbl.h);
      ctx.strokeStyle = "rgba(35, 50, 95, 0.65)";
      ctx.lineWidth = 0.5;
      ctx.strokeRect(lbl.x, lbl.y, lbl.w, lbl.h);

      ctx.fillStyle = "#E6ECFF";
      ctx.font = `${lbl.fontSize}px sans-serif`;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(lbl.text, lbl.x + LABEL_PAD, lbl.y + lbl.h / 2);
    }

    // Dibujar los círculos de los nodos encima de etiquetas y conectores.
    for (const n of nodePositions) {
      const isSelected = canvas._selectedNodeId === n.id;
      ctx.fillStyle = radarSectorColor(n.sector, sectors);
      ctx.globalAlpha = 0.9;
      ctx.beginPath(); ctx.arc(n.px, n.py, n.r, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
      ctx.strokeStyle = isSelected ? "#FFFFFF" : "rgba(11,18,38,.9)";
      ctx.lineWidth = isSelected ? 2 : 1;
      ctx.stroke();

      if (isSelected) {
        ctx.strokeStyle = "rgba(34, 211, 238, 0.8)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(n.px, n.py, n.r + 5, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
    ctx.textBaseline = "alphabetic";
    ctx.textAlign = "center";
  }

  canvas._drawRadar = drawRadarScene;
  drawRadarScene();

  const minWorksLabel = min_works > 1 ? ` (filtro: ≥${min_works} obras)` : "";
  const totalCount = (data.nodes || []).length;
  const hiddenCount = totalCount - nodePositions.length;
  const hiddenLabel = hiddenCount > 0 ? ` · <b>${nodePositions.length}</b> de ${totalCount} visibles (filtro por sector)` : "";
  if (legend) {
    legend.innerHTML = `<span class="sub"><b>${totalCount} autores</b>${minWorksLabel}${hiddenLabel} · aristas: <b>coautoría</b> (cian), <b>cita</b> (ámbar), <b>revista</b> (gris)</span>`;
  }
  canvas._radarNodes = nodePositions;
  canvas._radarCenter = data.center;
  canvas._cx = cx;
  canvas._cy = cy;

  // Renderizar la lista de autores en órbita en el panel lateral
  const proximityListEl = document.getElementById("proximity-author-list");
  if (proximityListEl) {
    const sortedNodes = [...nodePositions].sort((a, b) => (b.proximity || 0) - (a.proximity || 0));
    proximityListEl.innerHTML = sortedNodes.map((n, idx) => `
      <div class="radar-author-row" data-author-id="${esc(n.id)}">
        <div class="radar-author-row-top">
          <div style="display:flex; align-items:center; min-width:0;">
            <span class="radar-author-rank">${idx + 1}</span>
            <span class="radar-author-name" style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${esc(n.name)}</span>
          </div>
          <span class="radar-author-score">${Math.round((n.proximity || 0) * 100)}%</span>
        </div>
        <div style="width:100%; height:4px; background:var(--surface-container-high); border-radius:var(--radius-full); overflow:hidden; margin:4px 0;">
          <div style="width:${Math.round((n.proximity || 0) * 100)}%; height:100%; background:var(--brand-teal); border-radius:var(--radius-full);"></div>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:11px; color:var(--on-surface-variant); margin-top:2px;">
          <span>${n.n || 1} paper${(n.n || 1) > 1 ? 's' : ''}</span>
          <span style="color:var(--secondary); font-weight:500;">${esc(radarSectorLabel(n.sector, sectorLabels))}</span>
        </div>
      </div>
    `).join("");

    proximityListEl.querySelectorAll(".radar-author-row").forEach(row => {
      row.addEventListener("click", () => {
        const aId = row.dataset.authorId;
        const target = nodePositions.find(n => n.id === aId);
        if (target) {
          canvas._selectedNodeId = target.id;
          if (canvas._drawRadar) canvas._drawRadar();
          renderRadarAuthorCard(target, sectors);
        }
      });
    });
  }

  // Actualizar tarjeta lateral si hay un nodo previamente seleccionado
  if (canvas._selectedNodeId === "__center__") {
    renderRadarCenterCard(data.center);
  } else if (canvas._selectedNodeId) {
    const active = nodePositions.find(n => n.id === canvas._selectedNodeId);
    renderRadarAuthorCard(active || null, sectors);
  } else {
    renderRadarAuthorCard(null);
  }
}

function renderRadarAuthorCard(node, sectors) {
  const card = document.getElementById("radar-author-card");
  if (!card) return;
  if (!node) {
    card.innerHTML = `
      <div class="radar-author-empty">
        <span class="radar-empty-icon">👈</span>
        <p><b>Explora los autores del radar</b></p>
        <span class="sub">Haz clic en cualquier nodo para ver la ficha del autor, métricas de red y sus artículos en el catálogo.</span>
      </div>`;
    return;
  }

  const sectorColor = radarSectorColor(node.sector, sectors || []);
  const canvasLbl = document.getElementById("radar-canvas");
  const sectorName = radarSectorLabel(node.sector, (canvasLbl && canvasLbl._sectorLabels) || {});
  const works = node.works_list || [];

  const orcidBadge = node.orcid ? `
    <a href="https://orcid.org/${esc(node.orcid)}" target="_blank" rel="noopener" class="radar-orcid-badge" title="Ver perfil verificado en ORCID.org">
      <svg width="11" height="11" viewBox="0 0 256 256" fill="currentColor"><path d="M128 0C57.3 0 0 57.3 0 128s57.3 128 128 128 128-57.3 128-128S198.7 0 128 0zm-45.5 186.2H63.8V79.8h18.7v106.4zm-9.3-120.6c-6.1 0-11-4.9-11-11s4.9-11 11-11 11 4.9 11 11-4.9 11-11 11zm118.8 63.8c0 31.9-18.4 46.8-44.8 46.8H111V79.8h38.2c24.6 0 42.6 15.6 42.6 49.6zm-19.4 0c0-21.9-10.4-32.9-25.7-32.9h-17.7v65.8h17.7c15.8 0 25.7-11 25.7-32.9z"/></svg>
      ${esc(node.orcid)} ↗
    </a>` : "";
  const identityNote = node.identity_status === "ambiguous"
    ? `<div class="sub radar-identity-note">⚠️ Este nombre tiene varias identidades ORCID en el catálogo; aquí solo se agrupan obras sin ORCID que no pueden asignarse con certeza.</div>`
    : (node.identity_status === "orcid-inferred"
      ? `<div class="sub">Identidad asignada por una coincidencia única entre nombre y ORCID.</div>`
      : "");

  const yearsLabel = (node.first_year && node.last_year && node.first_year !== node.last_year)
    ? `${node.first_year}–${node.last_year}`
    : (node.last_year || '–');

  const journalsContext = (node.journals && node.journals.length) ? `
    <div class="radar-context-row">
      <span class="lbl">Revistas:</span>
      ${node.journals.map(j => `<span class="tag-journal">${esc(j)}</span>`).join(" ")}
    </div>` : "";

  const coauthorsContext = (node.coauthors && node.coauthors.length) ? `
    <div class="radar-context-row">
      <span class="lbl">Colaboradores en la red:</span>
      ${node.coauthors.map(c => `<span class="tag-coauthor" title="${c.weight} colaboraciones">${esc(c.name)}${c.orcid ? ' 🔗' : ''}</span>`).join(" ")}
    </div>` : "";

  const contextBlock = (journalsContext || coauthorsContext) ? `
    <div class="radar-author-context">
      ${journalsContext}
      ${coauthorsContext}
    </div>` : "";

  const breakdownBlock = (() => {
    const comp = node.components;
    if (!comp) return "";
    const canvasEl = document.getElementById("radar-canvas");
    const W = (canvasEl && canvasEl._radarWeights) || { w1_affinity: 0.4, w2_connection: 0.3, w3_recency: 0.2, w4_productivity: 0.1 };
    const rows = [
      { key: "affinity", label: "Afinidad temática", hint: "Mejor encaje de sus obras con tu consulta", w: W.w1_affinity },
      { key: "connection", label: "Conexión", hint: "Proporción de su obra afín al tema (o citas directas si el centro es un DOI)", w: W.w2_connection },
      { key: "recency", label: "Actualidad", hint: "Recencia de su última publicación en el catálogo", w: W.w3_recency },
      { key: "productivity", label: "Productividad", hint: "Volumen en catálogo: n/(n+C)", w: W.w4_productivity },
    ];
    const total = Math.round((node.proximity || 0) * 1000) / 10;
    const body = rows.map(r => {
      const v = Number(comp[r.key] ?? 0);
      const w = Number(r.w ?? 0);
      const pts = v * w * 100;
      return `<div class="radar-breakdown-row" title="${esc(r.hint)} · peso ${w.toFixed(2)}">
        <span class="radar-breakdown-label">${esc(r.label)}</span>
        <span class="radar-breakdown-bar"><span class="radar-breakdown-fill" style="width:${Math.round(v * 100)}%"></span></span>
        <span class="radar-breakdown-vals data-tabular">${Math.round(v * 100)}% × ${w.toFixed(2)} = <b>+${pts.toFixed(1)}</b></span>
      </div>`;
    }).join("");
    return `<div class="radar-author-context radar-breakdown" data-breakdown>
      <div class="radar-context-row"><span class="lbl">Cómo se compone su proximidad (${total.toFixed(1)}%):</span></div>
      ${body}
    </div>`;
  })();
  const topKeywords = Array.isArray(node.top_keywords) ? node.top_keywords : [];
  const topKeywordsBlock = topKeywords.length ? `
    <div class="radar-author-context" data-keyword-scope>
      <div class="radar-context-row">
        <span class="lbl">Palabras clave del autor${node.keyword_source === "derived" ? " sugeridas" : ""}:</span>
        ${topKeywords.map(k => selectableKeywordChip(k.keyword)).join("")}
      </div>
      <div class="keyword-actions">
        <button class="btn sm cool" data-pin-selected-keywords data-pin-label="${esc(`Radar · ${node.name}`)}" disabled>📌 Anclar seleccionadas</button>
        <button class="btn sm" data-action="pin-author-keywords">📌 Anclar todas</button>
      </div>
    </div>` : "";

  const worksHtml = works.length ? works.map((w, workIndex) => {
    const isTopicBadge = w.is_topic ? `<span style="background:rgba(34,211,238,0.15);color:#22D3EE;border:1px solid rgba(34,211,238,0.3);font-size:0.7rem;padding:1px 5px;border-radius:4px;font-weight:600;">Tema consultado</span>` : "";
    const citationsBadge = (w.cited_by && w.cited_by > 0) ? `<span class="badge-cited">⭐ ${w.cited_by} citas</span>` : "";
    const doiBtn = w.doi ? `<a href="https://doi.org/${esc(w.doi)}" target="_blank" rel="noopener" class="radar-btn-doi" title="Abrir DOI">DOI: ${esc(w.doi)} ↗</a>` : "";
    const workHref = w.url || (w.doi ? `https://doi.org/${w.doi}` : "");
    const centerBtn = w.doi ? `<button class="radar-btn-center" data-action="center-work" data-doi="${esc(w.doi)}">🎯 Usar como centro</button>` : "";
    const abstractSnippet = w.abstract ? `<p class="radar-work-abstract">${esc(w.abstract)}${w.abstract.length >= 350 ? "…" : ""}</p>` : "";

      const authorsLine = (w.authors && w.authors.length) ? `
        <div class="radar-work-authors">
          <b>Autores:</b> ${w.authors.map(au => au.orcid ? `<a href="https://orcid.org/${esc(au.orcid)}" target="_blank" rel="noopener" class="author-orcid-link" title="ORCID: ${esc(au.orcid)}">${esc(au.name)} 🔗</a>` : `<span>${esc(au.name)}</span>`).join(", ")}
        </div>` : "";
      const workKeywords = keywordStrings(w.display_keywords?.length ? w.display_keywords : w.keywords);
      const keywordSource = w.keyword_source === "derived" ? ` <span class="sub">(sugeridas)</span>` : "";
      const workKeywordsLine = workKeywords.length ? `
        <div class="radar-work-keywords">
          <b>Palabras clave:</b>${keywordSource} ${workKeywords.map(selectableKeywordChip).join(" ")}
        </div>` : "";

    return `
      <div class="radar-work-item ${w.is_topic ? 'is-topic' : ''}" data-keyword-scope>
        <div class="radar-work-title">${workHref ? `<a href="${esc(workHref)}" target="_blank" rel="noopener" title="Abrir publicación original">${esc(w.title)}</a>` : esc(w.title)}</div>
        ${authorsLine}
        ${workKeywordsLine}
        <div class="radar-work-meta">
          <span><b>${esc(w.journal || 'Revista')}</b></span>
          <span>·</span>
          <span>${w.year || 's.f.'}</span>
          ${citationsBadge}
          ${isTopicBadge}
        </div>
        ${abstractSnippet}
        <div class="radar-work-actions">
          ${doiBtn}
          ${centerBtn}
          ${w.doi ? `<button class="radar-btn-track" data-action="track-doi" data-doi="${esc(w.doi)}" data-title="${esc(w.title || '')}">🌐 Huella Web</button>` : ""}
          ${workKeywords.length ? `<button class="radar-btn-pin-keywords" data-pin-selected-keywords data-pin-label="${esc(`Radar · ${(w.title || "artículo").slice(0, 80)}`)}" disabled>📌 Anclar seleccionadas</button><button class="radar-btn-pin-keywords" data-action="pin-work-keywords" data-work-index="${workIndex}">📌 Anclar todas</button>` : ""}
        </div>
      </div>
    `;
  }).join("") : `<div class="sub">No hay artículos detallados disponibles.</div>`;

  card.innerHTML = `
    <div class="radar-author-header">
      <div>
        <div class="radar-author-name">${esc(node.name)}</div>
        <div class="radar-header-badges">
          <span class="radar-sector-badge" style="background:${sectorColor};" title="Sector temático dominante del perfil (no es un tema del autor)">Sector: ${esc(sectorName)}</span>
          ${orcidBadge}
        </div>
      </div>
      <button class="radar-btn-close" data-action="close-card" title="Cerrar ficha">✕</button>
    </div>
    ${identityNote}
    ${topKeywordsBlock}
    <button class="radar-btn-hide-author" data-action="hide-author" data-id="${esc(node.id)}" data-name="${esc(node.name)}">
      🚫 Ocultar este autor del radar
    </button>
    <div class="radar-author-stats">
      <div class="radar-stat-chip">
        <div class="val">${Math.round((node.proximity || 0) * 100)}%</div>
        <div class="lbl">Proximidad</div>
      </div>
      <div class="radar-stat-chip">
        <div class="val">${node.n || works.length || 1}</div>
        <div class="lbl">Obras en catálogo</div>
      </div>
      <div class="radar-stat-chip">
        <div class="val">${node.degree || 0}</div>
        <div class="lbl">Grado en red</div>
      </div>
      <div class="radar-stat-chip">
        <div class="val">${yearsLabel}</div>
        <div class="lbl">Periodo activo</div>
      </div>
    </div>
    ${contextBlock}
    ${breakdownBlock}
    <div class="radar-works-title">Artículos en catálogo (${works.length})</div>
    <div class="radar-works-list">
      ${worksHtml}
    </div>
  `;

  card.querySelector('[data-action="close-card"]')?.addEventListener("click", () => closeRadarAuthorCard());
  card.querySelector('[data-action="hide-author"]')?.addEventListener("click", (event) => {
    const button = event.currentTarget;
    hideRadarAuthor(button.dataset.id, button.dataset.name);
  });
  card.querySelectorAll('[data-action="center-work"]').forEach(button => {
    button.addEventListener("click", () => setRadarDoiCenter(button.dataset.doi));
  });
  card.querySelectorAll('[data-action="track-doi"]').forEach(button => {
    button.addEventListener("click", () => openDoiTracker(button.dataset.doi, button.dataset.title));
  });
  card.querySelector('[data-action="pin-author-keywords"]')?.addEventListener("click", () => {
    window.pinRadarKeywords(
      (node.top_keywords || []).map(item => item.keyword),
      `Radar · ${node.name}`
    );
  });
  card.querySelectorAll('[data-action="pin-work-keywords"]').forEach(button => {
    button.addEventListener("click", () => {
      const work = works[Number(button.dataset.workIndex)];
      if (work) {
        window.pinRadarKeywords(work.keywords, `Radar · ${(work.title || "artículo").slice(0, 80)}`);
      }
    });
  });
}

window.closeRadarAuthorCard = function() {
  const canvas = document.getElementById("radar-canvas");
  if (canvas) {
    canvas._selectedNodeId = null;
    if (canvas._drawRadar) canvas._drawRadar();
  }
  renderRadarAuthorCard(null);
};

function renderRadarCenterCard(center) {
  const card = document.getElementById("radar-author-card");
  if (!card) return;

  const topicInput = document.getElementById("radar-topic")?.value.trim() || "";
  const doiInput = document.getElementById("radar-doi")?.value.trim() || "";
  const isArticle = Boolean(center?.doi || doiInput || center?.type === "article");
  const title = center?.label || (doiInput ? `Artículo ${doiInput}` : (topicInput || "Pregunta Central"));
  const doi = center?.doi || doiInput;
  const journal = center?.journal || "";
  const year = center?.year || "";
  const authors = Array.isArray(center?.authors) ? center.authors : [];
  const keywords = Array.isArray(center?.keywords) ? center.keywords.filter(k => String(k || "").trim()) : [];
  const abstract = center?.abstract || "";

  const authorsHtml = authors.length ? `
    <div class="radar-work-authors" style="margin-top:8px">
      <b>Autores:</b> ${authors.map(au => {
        const name = typeof au === "string" ? au : (au.name || `${au.family || ""} ${au.given || ""}`.trim());
        const orcid = typeof au === "object" ? au.orcid : null;
        return orcid ? `<a href="https://orcid.org/${esc(orcid)}" target="_blank" rel="noopener" class="author-orcid-link" title="ORCID: ${esc(orcid)}">${esc(name)} 🔗</a>` : `<span>${esc(name)}</span>`;
      }).join(", ")}
    </div>` : "";

  const keywordsHtml = keywords.length ? `
    <div class="radar-author-context" style="margin-top:10px" data-keyword-scope>
      <div class="radar-context-row">
        <span class="lbl">Palabras clave del centro${center.keyword_source === "derived" ? " sugeridas" : ""}:</span>
        ${keywordStrings(keywords).map(selectableKeywordChip).join(" ")}
      </div>
      <div class="keyword-actions">
        <button class="btn sm cool" data-pin-selected-keywords data-pin-label="${esc(`Radar · ${title.slice(0, 80)}`)}" disabled>📌 Anclar seleccionadas</button>
        <button class="btn sm" data-action="pin-center-keywords">📌 Anclar todas</button>
      </div>
    </div>` : "";

  card.innerHTML = `
    <div class="radar-author-header">
      <div>
        <div class="radar-author-name">🎯 ${esc(title)}</div>
        <div class="radar-header-badges">
          <span class="radar-sector-badge" style="background:linear-gradient(135deg, #0EA5E9, #0284C7);color:#FFF">Centro del Radar</span>
          ${isArticle ? `<span class="badge cited">Artículo Central</span>` : `<span class="badge">Tema Central</span>`}
        </div>
      </div>
      <button class="radar-btn-close" data-action="close-card" title="Cerrar ficha">✕</button>
    </div>
    ${(journal || year) ? `<div class="sub" style="margin-top:6px"><b>${esc(journal)}</b> ${year ? `· ${year}` : ''}</div>` : ''}
    ${authorsHtml}
    ${keywordsHtml}
    ${abstract ? `<p class="radar-work-abstract" style="margin-top:10px">${esc(abstract)}</p>` : ''}
    <div class="radar-work-actions" style="margin-top:14px">
      ${doi ? `<a href="https://doi.org/${esc(doi)}" target="_blank" rel="noopener" class="radar-btn-doi" title="Abrir DOI">DOI: ${esc(doi)} ↗</a>` : ''}
      ${doi ? `<button class="radar-btn-track" data-action="track-doi" data-doi="${esc(doi)}" data-title="${esc(title)}">🌐 Huella Web</button>` : ''}
    </div>
  `;

  card.querySelector('[data-action="close-card"]')?.addEventListener("click", () => closeRadarAuthorCard());
  card.querySelector('[data-action="track-doi"]')?.addEventListener("click", () => {
    if (doi) openDoiTracker(doi, title);
  });
  card.querySelector('[data-action="pin-center-keywords"]')?.addEventListener("click", () => {
    const rawKws = keywords.map(k => typeof k === "string" ? k : (k.keyword || k.k || ''));
    if (rawKws.length) {
      window.pinRadarKeywords(rawKws, `Radar · ${title.slice(0, 80)}`);
    }
  });
}

window.setRadarDoiCenter = function(doi) {
  const doiInput = document.getElementById("radar-doi");
  if (doiInput) {
    doiInput.value = doi;
    renderRadar();
  }
};

/* ---------------- gestión de autores en el radar (excluir/agregar) ---------------- */
function renderRadarExcludedBar() {
  const bar = document.getElementById("radar-excluded-bar");
  const countEl = document.getElementById("radar-excluded-count");
  const chipsEl = document.getElementById("radar-excluded-chips");
  if (!bar || !chipsEl) return;
  const list = state.radarExcluded || [];
  if (!list.length) {
    bar.hidden = true;
    chipsEl.innerHTML = "";
    return;
  }
  bar.hidden = false;
  if (countEl) countEl.textContent = String(list.length);
  chipsEl.innerHTML = list.map(id => {
    const name = state.radarExcludedNames[id] || id;
    return `<span class="radar-chip-excluded">
      ${esc(name)}
      <button data-action="restore-author" data-id="${esc(id)}" title="Restaurar este autor al radar">✕</button>
    </span>`;
  }).join("");
  chipsEl.querySelectorAll('[data-action="restore-author"]').forEach(button => {
    button.addEventListener("click", () => restoreRadarAuthor(button.dataset.id));
  });
}

function radarNormAuthor(value) {
  const normalized = String(value || "").toLowerCase().normalize("NFD");
  return normalized
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

window.hideRadarAuthor = function(id, name) {
  if (!id) return;
  state.radarExcluded = state.radarExcluded || [];
  state.radarExcludedNames = state.radarExcludedNames || {};
  if (!state.radarExcluded.includes(id)) {
    state.radarExcluded.push(id);
    if (name) state.radarExcludedNames[id] = name;
  }
  state.radarIncluded = (state.radarIncluded || []).filter(x => x !== id);
  saveRadarFilters();
  closeRadarAuthorCard();
  renderRadar();
};

window.restoreRadarAuthor = function(id) {
  state.radarExcluded = (state.radarExcluded || []).filter(x => x !== id);
  saveRadarFilters();
  renderRadar();
};

window.restoreAllRadarAuthors = function() {
  state.radarExcluded = [];
  state.radarExcludedNames = {};
  saveRadarFilters();
  renderRadar();
};

window.addRadarAuthor = async function(authorKeyOrName) {
  const clean = (authorKeyOrName || "").trim();
  const statusEl = document.getElementById("radar-discovery-status");
  if (!clean) return;
  try {
    const { authors } = await api("/authors/suggest", { q: clean, limit: 10 });
    const needle = clean.toLowerCase();
    const needleNorm = radarNormAuthor(clean);
    const exactKey = (authors || []).find(a => (a.key || "").toLowerCase() === needle);
    const exactOrcid = (authors || []).find(a => (a.orcid || "").toLowerCase() === needle);
    const sameName = (authors || []).filter(a => radarNormAuthor(a.name) === needleNorm);
    const exact = exactKey || exactOrcid || (sameName.length === 1 ? sameName[0] : null);
    if (!exact) {
      if (statusEl) {
        statusEl.hidden = false;
        statusEl.textContent = sameName.length > 1
          ? `⚠️ «${clean}» tiene varias identidades en el catálogo. Selecciona la sugerencia con el ORCID correcto.`
          : `⚠️ «${clean}» no coincide exactamente con ningún autor del catálogo. Elige una sugerencia de la lista.`;
      }
      return;
    }
    state.radarIncluded = state.radarIncluded || [];
    if (!state.radarIncluded.includes(exact.key)) {
      state.radarIncluded.push(exact.key);
    }
    state.radarExcluded = (state.radarExcluded || []).filter(x => x.toLowerCase() !== exact.key.toLowerCase());
    saveRadarFilters();
    const input = document.getElementById("radar-add-author");
    if (input) input.value = "";
    if (statusEl) statusEl.hidden = true;
    renderRadar();
  } catch (e) {
    if (statusEl) {
      statusEl.hidden = false;
      statusEl.textContent = `⚠️ No se pudo agregar al autor: ${e.message}`;
    }
  }
};

window.pinRadarKeywords = async function(keywords, label) {
  const list = Array.isArray(keywords) ? keywords : String(keywords || "").split(",");
  const clean = [...new Set(list.map(k => String(k || "").trim()).filter(Boolean))];
  const statusEl = document.getElementById("radar-discovery-status");
  if (!clean.length) {
    if (statusEl) {
      statusEl.hidden = false;
      statusEl.textContent = "⚠️ Este artículo no tiene palabras clave declaradas para anclar.";
    }
    return;
  }
  try {
    const joined = clean.join(", ");
    const res = await api("/watch", {}, {
      method: "POST",
      body: { keywords: joined, label: label || `Radar: ${clean.slice(0, 3).join(", ")}` },
    });
    if (statusEl) {
      statusEl.hidden = false;
      statusEl.textContent = `📌 Ancla creada (#${res.id}): ${joined}`;
    }
    await loadWatch();
  } catch (e) {
    if (statusEl) {
      statusEl.hidden = false;
      statusEl.textContent = `⚠️ No se pudo anclar: ${e.message}`;
    }
  }
};

window.discoverRadarLive = async function() {
  const topic = document.getElementById("radar-topic").value.trim();
  if (!topic) {
    showNotification({ title: "Falta el tema", message: "Escribe primero un tema o pregunta en el buscador del radar.", type: "info" });
    return;
  }
  const btn = document.getElementById("btn-radar-discover");
  const statusEl = document.getElementById("radar-discovery-status");
  const oldText = btn ? btn.textContent : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳ Buscando en OpenAlex…";
  }
  if (statusEl) {
    statusEl.hidden = false;
    statusEl.textContent = "🛰️ Buscando en OpenAlex publicaciones recientes para enriquecer la órbita de autores…";
  }

  try {
    const weights = document.getElementById("radar-weights").value;
    const doiInput = document.getElementById("radar-doi");
    const doi = doiInput ? doiInput.value.trim() : "";
    const minWorksEl = document.getElementById("radar-min-works");
    const min_works = minWorksEl ? parseInt(minWorksEl.value, 10) || 1 : 1;

    const payload = {
      topic,
      doi,
      weights,
      min_works,
      limit: 30,
      days: 730,
      max_results: 35,
      watch: true,
      excluded: (state.radarExcluded || []).join(","),
      included: (state.radarIncluded || []).join(","),
    };
    const affDivEl = document.getElementById("radar-affinity-divisor");
    const prodConstEl = document.getElementById("radar-productivity-constant");
    const minDistEl = document.getElementById("radar-min-dist");
    const recDecayEl = document.getElementById("radar-recency-decay");
    const normWeightsEl = document.getElementById("radar-normalize-weights");

    if (affDivEl && affDivEl.value) payload.affinity_divisor = parseInt(affDivEl.value, 10);
    if (prodConstEl && prodConstEl.value) payload.productivity_constant = parseFloat(prodConstEl.value);
    if (minDistEl && minDistEl.value) payload.min_dist = parseFloat(minDistEl.value);
    if (recDecayEl && recDecayEl.value) payload.recency_decay = recDecayEl.value;
    if (normWeightsEl) payload.normalize_weights = normWeightsEl.checked;

    const res = await api("/radar/discover", {}, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
    });

    const disc = res.discovery || {};
    const monitoring = res.continuous_monitoring || {};
    if (statusEl) {
      statusEl.hidden = false;
      const sources = Object.entries(disc.sources || {})
        .map(([name, info]) => `${name}: ${info.found || 0}/${info.new || 0}`)
        .join(" · ");
      const harvestState = monitoring.auto_harvest_enabled
        ? "La vigilancia periódica está activa."
        : "Activa la cosecha automática del servidor para recibir avisos periódicos.";
      const msg = disc.error
        ? `⚠️ No se pudo completar la búsqueda en vivo: ${esc(disc.error)}`
        : (disc.new > 0)
          ? `✨ ¡Descubrimiento completado! Se incorporaron <b>${disc.new}</b> nuevas publicaciones (${disc.authors_added || 0} autores nuevos, ${disc.journals_added || 0} revistas nuevas). Fuentes: ${esc(sources || "sin resultados")}. ${esc(harvestState)}`
          : (disc.found > 0 ? `✔ <b>${disc.found}</b> artículos examinados. El radar ya cuenta con las publicaciones más recientes. ${esc(harvestState)}` : `✔ Búsqueda completada. ${esc(harvestState)}`);
      statusEl.innerHTML = msg;
      if (!disc.error) {
        setTimeout(() => { if (statusEl) statusEl.hidden = true; }, 12000);
      }
    }
    renderRadar();
    renderStats();
  } catch (e) {
    if (statusEl) {
      statusEl.hidden = false;
      statusEl.textContent = `⚠️ Error al buscar novedades: ${e.message}`;
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText;
    }
  }
};

const radarCanvasEl = document.getElementById("radar-canvas");
if (radarCanvasEl) {
  radarCanvasEl.addEventListener("mousemove", e => {
    const nodes = radarCanvasEl._radarNodes;
    if (!nodes) return;
    const rect = radarCanvasEl.getBoundingClientRect();
    const scaleX = radarCanvasEl.width / rect.width;
    const scaleY = radarCanvasEl.height / rect.height;
    const mx = (e.clientX - rect.left) * scaleX;
    const my = (e.clientY - rect.top) * scaleY;

    // Centro del radar
    const cx = radarCanvasEl._cx || (radarCanvasEl.width / 2);
    const cy = radarCanvasEl._cy || (radarCanvasEl.height / 2);
    if (Math.hypot(cx - mx, cy - my) <= 16) {
      radarCanvasEl.style.cursor = "pointer";
      const cLabel = radarCanvasEl._radarCenter?.label || "Centro del Radar";
      radarCanvasEl.title = `🎯 Centro: ${cLabel} (Clic para ver ficha e impacto web)`;
      return;
    }

    const hovered = nodes.find(n => Math.hypot(n.px - mx, n.py - my) <= Math.max(8, n.r + 4));
    if (hovered) {
      radarCanvasEl.style.cursor = "pointer";
      radarCanvasEl.title = `${hovered.name} (${hovered.sector}) · Proximidad: ${hovered.proximity} · Grado: ${hovered.degree} · Obras: ${hovered.n} (Clic para ver ficha)`;
    } else {
      radarCanvasEl.style.cursor = "default";
      radarCanvasEl.title = "";
    }
  });

  radarCanvasEl.addEventListener("click", e => {
    const nodes = radarCanvasEl._radarNodes;
    if (!nodes) return;
    const rect = radarCanvasEl.getBoundingClientRect();
    const scaleX = radarCanvasEl.width / rect.width;
    const scaleY = radarCanvasEl.height / rect.height;
    const mx = (e.clientX - rect.left) * scaleX;
    const my = (e.clientY - rect.top) * scaleY;

    // Clic en el centro del radar
    const cx = radarCanvasEl._cx || (radarCanvasEl.width / 2);
    const cy = radarCanvasEl._cy || (radarCanvasEl.height / 2);
    if (Math.hypot(cx - mx, cy - my) <= 16) {
      radarCanvasEl._selectedNodeId = "__center__";
      if (radarCanvasEl._drawRadar) radarCanvasEl._drawRadar();
      renderRadarCenterCard(radarCanvasEl._radarCenter);
      return;
    }

    const clicked = nodes.find(n => Math.hypot(n.px - mx, n.py - my) <= Math.max(10, n.r + 5));
    if (clicked) {
      radarCanvasEl._selectedNodeId = clicked.id;
      if (radarCanvasEl._drawRadar) radarCanvasEl._drawRadar();
      renderRadarAuthorCard(clicked, radarCanvasEl._sectors);
    } else {
      radarCanvasEl._selectedNodeId = null;
      if (radarCanvasEl._drawRadar) radarCanvasEl._drawRadar();
      renderRadarAuthorCard(null);
    }
  });
}

document.getElementById("btn-radar")?.addEventListener("click", renderRadar);
document.getElementById("radar-topic")?.addEventListener("keydown", e => { if (e.key === "Enter") renderRadar(); });
document.getElementById("radar-min-works")?.addEventListener("change", renderRadar);
document.getElementById("radar-weights")?.addEventListener("change", renderRadar);
document.getElementById("btn-radar-discover")?.addEventListener("click", discoverRadarLive);
document.getElementById("btn-restore-all-authors")?.addEventListener("click", restoreAllRadarAuthors);

// Panel de ajustes avanzados del algoritmo
const settingsToggleBtn = document.getElementById("btn-radar-settings-toggle");
const advancedPanel = document.getElementById("radar-advanced-settings");
settingsToggleBtn?.addEventListener("click", () => {
  if (!advancedPanel) return;
  const isHidden = advancedPanel.hidden || advancedPanel.style.display === "none";
  advancedPanel.hidden = !isHidden;
  advancedPanel.style.display = isHidden ? "block" : "none";
  settingsToggleBtn.setAttribute("aria-expanded", String(isHidden));
  settingsToggleBtn.classList.toggle("active", isHidden);
});

document.getElementById("btn-radar-settings-reset")?.addEventListener("click", () => {
  const affDivEl = document.getElementById("radar-affinity-divisor");
  const prodConstEl = document.getElementById("radar-productivity-constant");
  const minDistEl = document.getElementById("radar-min-dist");
  const recDecayEl = document.getElementById("radar-recency-decay");
  const normWeightsEl = document.getElementById("radar-normalize-weights");

  if (affDivEl) affDivEl.value = "60";
  if (prodConstEl) prodConstEl.value = "5.0";
  if (minDistEl) minDistEl.value = "11.0";
  if (recDecayEl) recDecayEl.value = "linear";
  if (normWeightsEl) normWeightsEl.checked = true;

  renderRadar();
});

document.getElementById("radar-affinity-divisor")?.addEventListener("change", renderRadar);
document.getElementById("radar-productivity-constant")?.addEventListener("change", renderRadar);
document.getElementById("radar-min-dist")?.addEventListener("change", renderRadar);
document.getElementById("radar-recency-decay")?.addEventListener("change", renderRadar);
document.getElementById("radar-normalize-weights")?.addEventListener("change", renderRadar);

// Autocompletado y agregado manual de autores
const addAuthorInput = document.getElementById("radar-add-author");
const addAuthorBtn = document.getElementById("btn-radar-add-author");
const authorDatalist = document.getElementById("radar-author-suggest-list");

if (addAuthorInput && authorDatalist) {
  let authorSuggestTimer = null;
  let authorSuggestToken = 0;
  addAuthorInput.addEventListener("input", () => {
    const q = addAuthorInput.value.trim();
    if (q.length < 2) return;
    clearTimeout(authorSuggestTimer);
    authorSuggestTimer = setTimeout(async () => {
      const token = ++authorSuggestToken;
      try {
        const { authors } = await api("/authors/suggest", { q, limit: 10 });
        if (token !== authorSuggestToken) return;
        authorDatalist.innerHTML = (authors || []).map(a => `<option value="${esc(a.key)}">${esc(a.name)} (${a.n} obra${a.n > 1 ? 's' : ''}${a.orcid ? ` · ORCID ${esc(a.orcid)}` : ""})</option>`).join("");
      } catch (e) { /* silencioso */ }
    }, 250);
  });

  addAuthorInput.addEventListener("keydown", e => {
    if (e.key === "Enter") {
      addRadarAuthor(addAuthorInput.value);
    }
  });
}

if (addAuthorBtn && addAuthorInput) {
  addAuthorBtn.addEventListener("click", () => {
    addRadarAuthor(addAuthorInput.value);
  });
}

/* ---------------- instalación PWA ---------------- */
window.addEventListener("beforeinstallprompt", e => {
  e.preventDefault();
  state.deferredPrompt = e;
  document.getElementById("install-wrap").hidden = false;
});
document.getElementById("btn-install").addEventListener("click", async () => {
  if (!state.deferredPrompt) return;
  state.deferredPrompt.prompt();
  await state.deferredPrompt.userChoice;
  state.deferredPrompt = null;
  document.getElementById("install-wrap").hidden = true;
});

/* ---------------- boot ---------------- */
document.getElementById("btn-apply")?.addEventListener("click", () => {
  readForm(); renderFeed(); refreshSuggest();
});
document.getElementById("btn-refresh")?.addEventListener("click", () => { renderFeed(); renderSources(); loadWatch(); });
document.getElementById("btn-pin")?.addEventListener("click", addWatch);
document.getElementById("btn-cfp")?.addEventListener("click", async () => {
  try {
    const data = await api("/cfp");
    const kws = (data.cfp && data.cfp.keywords) || [];
    const kwInput = document.getElementById("keywords");
    if (kwInput) kwInput.value = kws.slice(0, 6).join(", ");
    readForm();
    renderFeed();
  } catch (e) { /* silencioso */ }
});
document.getElementById("btn-notify")?.addEventListener("click", async () => {
  if (!("Notification" in window)) { showNotification({ title: "Notificaciones", message: "Tu navegador no soporta notificaciones.", type: "info" }); return; }
  const p = await Notification.requestPermission();
  refreshNotifyButton();
  if (p === "granted") loadWatch();
});
document.getElementById("keywords")?.addEventListener("input", debounce(refreshSuggest, 400));
document.getElementById("keywords")?.addEventListener("keydown", e => {
  if (e.key === "Enter") {
    e.preventDefault();
    readForm();
    renderFeed();
    refreshSuggest();
  }
});

function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/* ---------------- SPA Router & Vista Switcher ---------------- */
function switchView(viewName) {
  let isReviewShortcut = false;
  if (viewName === "review") {
    viewName = "home";
    isReviewShortcut = true;
  }

  const views = ["home", "explorer", "journals", "reviewers", "radar"];
  if (!views.includes(viewName)) viewName = "home";

  views.forEach(v => {
    const el = document.getElementById(`view-${v}`);
    if (el) {
      if (v === viewName) {
        el.classList.add("active");
      } else {
        el.classList.remove("active");
      }
    }
  });

  document.querySelectorAll(".nav-link").forEach(btn => {
    if (btn.dataset.view === (isReviewShortcut ? "review" : viewName)) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  });

  window.location.hash = "#" + (isReviewShortcut ? "review" : viewName);
  
  if (isReviewShortcut) {
    const libPanel = document.getElementById("home-librarian-panel");
    const libResults = document.getElementById("librarian-results");
    if (libPanel) {
      libPanel.hidden = false;
      libPanel.style.display = "block";
    }
    if (libResults) {
      libResults.hidden = false;
      libResults.style.display = "flex";
    }
    const btnSubmotorRev = document.getElementById("btn-submotor-review");
    if (btnSubmotorRev) btnSubmotorRev.click();
    setupProtocolManager();
    setTimeout(() => {
      document.getElementById("librarian-epistemic-section")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 150);
  } else {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  if (viewName === "radar") {
    const topic = document.getElementById("radar-topic")?.value.trim();
    if (topic) renderRadar();
  }
}

function initRouter() {
  document.addEventListener("click", e => {
    const trigger = e.target.closest("[data-view]");
    if (trigger) {
      const v = trigger.dataset.view;
      if (v) {
        e.preventDefault();
        switchView(v);
      }
    }
  });

  window.addEventListener("hashchange", () => {
    const hash = (window.location.hash || "").replace("#", "");
    if (hash) switchView(hash);
  });

  const initialHash = (window.location.hash || "").replace("#", "");
  if (initialHash) {
    switchView(initialHash);
  }
}

let currentLibrarianData = null;

function renderLibrarianResults(data) {
  currentLibrarianData = data;
  const panel = document.getElementById("home-librarian-panel");
  const loading = document.getElementById("librarian-loading");
  const results = document.getElementById("librarian-results");
  if (!panel || !results) return;

  panel.hidden = false;
  panel.style.display = "block";
  if (loading) {
    loading.hidden = true;
    loading.style.display = "none";
  }
  results.hidden = false;
  results.style.display = "flex";

  const isProbe = data.data_source === "live_probe";

  // 0. Badge distintivo de Sonda en Vivo (OpenAlex)
  const probeBadge = document.getElementById("librarian-probe-badge");
  if (probeBadge) {
    probeBadge.hidden = !isProbe;
    probeBadge.style.display = isProbe ? "flex" : "none";
  }

  // 0-bis. Aviso de consulta ampliada: transparencia sobre QUÉ se buscó realmente.
  // El backend relaja la formulación cuando la consulta estricta devuelve cero; si el
  // investigador no lo sabe, cree que esos resultados responden a su pregunta literal.
  const relaxBadge = document.getElementById("librarian-relax-badge");
  const relaxText = document.getElementById("librarian-relax-text");
  if (relaxBadge && relaxText) {
    const intentos = Array.isArray(data.consultas_intentadas) ? data.consultas_intentadas : [];
    const usada = data.consulta_usada;
    if (data.consulta_relajada && usada) {
      const fallidas = intentos.filter(i => !i.resultados).length;
      relaxText.textContent = fallidas
        ? `Su formulación completa no arrojó resultados (${fallidas} ${fallidas === 1 ? "intento" : "intentos"}); se recuperó con «${usada}». Revise si los trabajos responden a su pregunta o reformúlela.`
        : `Se recuperó con «${usada}» en lugar de su formulación literal.`;
      relaxBadge.hidden = false;
      relaxBadge.style.display = "flex";
    } else if (intentos.length > 1 && !(data.articles || []).length) {
      relaxText.textContent = `Se probaron ${intentos.length} formulaciones (de la más específica a la más general) y ninguna encontró publicaciones en acceso abierto. El vacío está declarado, no inventado.`;
      relaxBadge.hidden = false;
      relaxBadge.style.display = "flex";
    } else {
      relaxBadge.hidden = true;
      relaxBadge.style.display = "none";
    }
  }

  // 1. Lema y Diagnóstico de Saturación / Brechas
  const sat = data.saturation || {};
  const satBadge = document.getElementById("eco-saturation-badge");
  if (satBadge) {
    satBadge.textContent = sat.label || (isProbe ? "Sonda en Vivo Abierta" : "Exploración de Ecosistema");
    satBadge.title = sat.description || "";
  }

  // 2. Termómetro del Ecosistema (Métricas Reales Grounded)
  const eco = data.ecosystem || {};
  const totalMatched = eco.total_matched ?? (data.articles || []).length;
  const totalEl = document.getElementById("eco-metric-total");
  if (totalEl) totalEl.textContent = Number(totalMatched).toLocaleString("es-ES");

  const totalLabel = document.getElementById("eco-metric-total-label");
  if (totalLabel) {
    totalLabel.textContent = isProbe ? "Obras Globales (Acceso Abierto)" : "Documentos en el Catálogo";
  }

  const sourcesEl = document.getElementById("eco-metric-sources");
  if (sourcesEl) {
    if (isProbe) {
      sourcesEl.textContent = "OpenAlex Works API • Filtro Open Access (is_oa:true)";
    } else if (eco.sources) {
      const srcParts = Object.entries(eco.sources)
        .map(([s, c]) => `${esc(s.toUpperCase())}: ${c}`);
      sourcesEl.textContent = srcParts.join(" • ") || "SciELO • Redalyc • Crossref • OpenAlex";
    }
  }

  const journalsCountEl = document.getElementById("eco-metric-journals-count");
  if (journalsCountEl) {
    journalsCountEl.textContent = (eco.top_journals || []).length;
  }

  const yearsEl = document.getElementById("eco-metric-years");
  const recentEl = document.getElementById("eco-metric-recent");
  if (eco.years) {
    if (yearsEl) {
      yearsEl.textContent = eco.years.min && eco.years.max ? `${eco.years.min} – ${eco.years.max}` : "Catálogo activo";
    }
    if (recentEl) {
      recentEl.textContent = eco.years.recent_count ? `${eco.years.recent_count} publicaciones recientes (últimos 3 años)` : "Monitoreo continuo";
    }
  }

  const articlesTitleLabel = document.getElementById("librarian-articles-title-text");
  if (articlesTitleLabel) {
    articlesTitleLabel.textContent = isProbe
      ? "Obras destacadas recuperadas en tiempo real"
      : "Documentos destacados con enlaces verificados";
  }

  // 3. Síntesis Grounded del Auditor de Cultura Científica
  const heardEl = document.getElementById("librarian-heard-text");
  const explEl = document.getElementById("librarian-explanation-text");
  const badgeEl = document.getElementById("librarian-field-badge");

  if (heardEl) heardEl.textContent = data.heard_as || `«${data.corrected || data.inquiry}»`;
  if (explEl) explEl.textContent = data.explanation || (isProbe ? "Diagnóstico en tiempo real completado mediante Sonda Abierta OpenAlex." : "Diagnóstico bibliométrico completado sobre el catálogo iberoamericano.");
  if (badgeEl) badgeEl.textContent = isProbe ? "Sonda Multidisciplinar" : (data.field ? data.field.name : "Comunicación");

  // 4. Palabras Clave de Búsqueda & Descriptores de Refinamiento
  const kwContainer = document.getElementById("librarian-keywords-chips");
  if (kwContainer) {
    kwContainer.innerHTML = "";
    (data.keywords || []).forEach(kw => {
      const chip = document.createElement("span");
      chip.className = "librarian-chip";
      chip.textContent = kw;
      kwContainer.appendChild(chip);
    });
  }

  const suggestedContainer = document.getElementById("librarian-suggested-chips");
  const refineRow = document.getElementById("librarian-refine-row");
  if (suggestedContainer) {
    suggestedContainer.innerHTML = "";
    const sugg = data.suggested_keywords || [];
    if (sugg.length > 0 && refineRow) {
      refineRow.hidden = false;
      sugg.forEach(skw => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "librarian-suggested-chip";
        chip.innerHTML = `<span class="material-symbols-outlined text-[12px]">add</span> ${esc(skw)}`;
        chip.title = `Afinar la búsqueda sumando «${skw}»`;
        chip.addEventListener("click", () => {
          const inqInput = document.getElementById("home-inquiry-input");
          if (inqInput) {
            const currentVal = inqInput.value.trim();
            inqInput.value = currentVal ? `${currentVal}, ${skw}` : skw;
            const sendBtn = document.getElementById("btn-home-send");
            if (sendBtn) sendBtn.click();
          }
        });
        suggestedContainer.appendChild(chip);
      });
    } else if (refineRow) {
      refineRow.hidden = true;
    }
  }

  // 5. Revistas Núcleo (con enlace directo a Explorador)
  const journalsList = document.getElementById("eco-journals-list");
  if (journalsList) {
    journalsList.innerHTML = "";
    const topJ = eco.top_journals || [];
    if (topJ.length === 0) {
      journalsList.innerHTML = `<p style="font-size: 0.82rem; color: var(--on-surface-variant); margin: 0;">Dispersión en publicaciones periódicas diversas.</p>`;
    } else {
      topJ.forEach(j => {
        const item = document.createElement("div");
        item.className = "eco-list-item";
        item.title = `Filtrar y explorar publicaciones de ${j.name} en el catálogo`;
        item.innerHTML = `
          <span class="eco-list-item-title">
            <span class="material-symbols-outlined text-[14px]" style="vertical-align: -2px;">menu_book</span>
            ${esc(j.name)}
          </span>
          <span class="eco-list-item-badge">${j.count} doc${j.count > 1 ? "s" : ""}</span>
        `;
        item.addEventListener("click", () => {
          state.config.journal = j.name;
          const kwInput = document.getElementById("keywords");
          if (kwInput) kwInput.value = (data.keywords || []).join(", ");
          readForm();
          switchView("explorer");
          renderFeed();
        });
        journalsList.appendChild(item);
      });
    }
  }

  // 6. Autores que Articulan la Conversación (con enlace a Radar de Proximidad)
  const authorsList = document.getElementById("eco-authors-list");
  if (authorsList) {
    authorsList.innerHTML = "";
    const topA = data.top_authors || [];
    if (topA.length === 0) {
      authorsList.innerHTML = `<p style="font-size: 0.82rem; color: var(--on-surface-variant); margin: 0;">Autorías individuales sin concentración prominente.</p>`;
    } else {
      topA.forEach(a => {
        const item = document.createElement("div");
        item.className = "eco-list-item";
        const aName = a.name || a;
        const aCount = a.count || 1;
        item.title = `Abrir órbita de proximidad y conexiones para ${aName}`;
        item.innerHTML = `
          <span class="eco-list-item-title">
            <span class="material-symbols-outlined text-[14px]" style="vertical-align: -2px;">person</span>
            ${esc(aName)}
          </span>
          <span class="eco-list-item-badge">${aCount} obra${aCount > 1 ? "s" : ""}</span>
        `;
        item.addEventListener("click", () => {
          const topicKeywords = (data.keywords || []).join(", ") || data.corrected || data.inquiry || "";
          const radarTopic = document.getElementById("radar-topic");
          if (radarTopic && topicKeywords) radarTopic.value = topicKeywords;
          switchView("radar");
          if (typeof window.addRadarAuthor === "function") window.addRadarAuthor(aName);
        });
        authorsList.appendChild(item);
      });
    }
  }

  // 7. Lista de Documentos Clave Recuperados (Enlaces directos a DOI y revistas)
  const countEl = document.getElementById("librarian-articles-count");
  const articles = data.articles || [];
  const allMatchedCount = (data.ecosystem && data.ecosystem.total_matched) || (data.saturation && data.saturation.total_indexed) || articles.length;
  if (countEl) countEl.textContent = (allMatchedCount > articles.length) ? `${articles.length} de ${allMatchedCount}` : articles.length;

  const viewAllBtn = document.getElementById("btn-librarian-view-all");
  if (viewAllBtn) {
    if (allMatchedCount > articles.length) {
      viewAllBtn.innerHTML = `<span>Ver los ${allMatchedCount} artículos en Catálogo</span><span class="material-symbols-outlined text-[15px]">arrow_forward</span>`;
    } else {
      viewAllBtn.innerHTML = `<span>Ver todos en Catálogo</span><span class="material-symbols-outlined text-[15px]">arrow_forward</span>`;
    }
  }

  const listEl = document.getElementById("librarian-articles-list");
  if (listEl) {
    listEl.innerHTML = "";
    if (articles.length === 0) {
      listEl.innerHTML = `<p style="font-size: 0.9rem; color: var(--on-surface-variant); padding: 12px 0;">No se encontraron artículos con coincidencias directas en la base actual. Puede probar agregando descriptores complementarios o explorando el catálogo general.</p>`;
    } else {
      articles.forEach(art => {
        const card = document.createElement("div");
        card.className = "librarian-article-card";

        const authorsStr = (art.authors || []).map(a => {
          if (typeof a === "object" && a) return `${a.given || ""} ${a.family || ""}`.trim() || a.name || "";
          return a;
        }).filter(Boolean).slice(0, 3).join(", ") || "Autor no declarado";

        const title = esc(art.title || "Sin título");
        const journal = esc(art.journal_title || art.journal || "Revista");
        const year = art.year || (art.pub_date ? String(art.pub_date).slice(0, 4) : "");
        const source = esc(String(art.source || "catálogo").toUpperCase());
        const doi = art.doi ? `https://doi.org/${art.doi}` : (art.url || "#");
        const scoreBadge = art.match_score ? `<span class="badge badge-source sm" style="font-size: 11px;">Relevancia ${art.match_score}</span>` : "";

        card.innerHTML = `
          <div class="librarian-article-meta">
            <span class="librarian-article-source">${esc(source)}</span>
            <span>•</span>
            <span>${esc(journal)}</span>
            ${year ? `<span>•</span><span>${esc(year)}</span>` : ""}
            ${scoreBadge}
          </div>
          <div class="librarian-article-title">
            <a href="${esc(doi)}" target="_blank" rel="noopener noreferrer" title="Abrir publicación original (DOI oficial)">
              ${esc(title)}
              <span class="material-symbols-outlined text-[14px]" style="vertical-align: -1px; margin-left: 3px;">open_in_new</span>
            </a>
          </div>
          <div class="librarian-article-authors">
            <span class="material-symbols-outlined text-[13px]" style="vertical-align: -2px;">person</span> ${esc(authorsStr)}
          </div>
        `;
        listEl.appendChild(card);
      });
    }
  }

  // Cargar Módulo Epistemológico y Scoping Review para Modo Investigador
  loadEpistemicDashboard(data);

  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

let currentEpistemicRoles = [];
let lastLibrarianData = null;
let epistemicSubmotorLoaded = false;
let reviewSubmotorLoaded = false;

async function loadEpistemicDashboard(librarianData) {
  const epistemicSection = document.getElementById("librarian-epistemic-section");
  if (!epistemicSection) return;

  lastLibrarianData = librarianData;
  epistemicSubmotorLoaded = false;
  reviewSubmotorLoaded = false;

  initSubmotorSwitcher();
  initSubmotorATabs();
  initPrismaStepper();
  setupProtocolManager();

  // Activar el submotor recordado o por defecto Submotor A
  const savedSubmotor = sessionStorage.getItem("thinkuy_active_submotor") || "submotor-panel-epistemic";
  const targetTab = document.querySelector(`.submotor-tab[data-submotor="${savedSubmotor}"]`) || document.getElementById("btn-submotor-epistemic");
  if (targetTab) {
    targetTab.click();
  }

  // Pre-cargar Paso 0 (Clasificación de Roles) para que esté listo al entrar al Submotor B
  loadRolesStep0(librarianData);
  setupScreeningTab(librarianData);
  setupChartingTab();
  setupValidationQueue();
  loadValidationQueue();
  setupSystematicTab();
}

function initEpistemicTabs() {
  initSubmotorSwitcher();
  initSubmotorATabs();
  initPrismaStepper();
  setupProtocolManager();
  setupChartingTab();
}

function initSubmotorSwitcher() {
  const tabs = document.querySelectorAll(".submotor-tab");
  tabs.forEach(tab => {
    tab.onclick = () => {
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      const targetId = tab.dataset.submotor;
      sessionStorage.setItem("thinkuy_active_submotor", targetId);

      document.querySelectorAll(".submotor-panel").forEach(p => {
        if (p.id === targetId) {
          p.classList.add("active");
          p.hidden = false;
          p.style.display = "block";
        } else {
          p.classList.remove("active");
          p.hidden = true;
          p.style.display = "none";
        }
      });

      if (targetId === "submotor-panel-epistemic" && !epistemicSubmotorLoaded) {
        loadEpistemicSubmotorA(lastLibrarianData);
        setupSnowballingExplorer(lastLibrarianData);
      } else if (targetId === "submotor-panel-review" && !reviewSubmotorLoaded) {
        reviewSubmotorLoaded = true;
        refreshPrismaFlow();
      }
    };
  });

  const recalcBtn = document.getElementById("btn-recalc-epistemic");
  if (recalcBtn) {
    recalcBtn.onclick = () => {
      loadEpistemicSubmotorA(lastLibrarianData, true);
    };
  }
}

function initSubmotorATabs() {
  const pills = document.querySelectorAll("#submotor-panel-epistemic .epistemic-pill");
  pills.forEach(pill => {
    pill.onclick = () => {
      pills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      const targetId = pill.dataset.target;
      document.querySelectorAll("#submotor-panel-epistemic .epistemic-tab-content").forEach(tc => {
        if (tc.id === targetId) {
          tc.classList.add("active");
          tc.hidden = false;
          tc.style.display = "block";
        } else {
          tc.classList.remove("active");
          tc.hidden = true;
          tc.style.display = "none";
        }
      });
    };
  });
}

async function loadEpistemicSubmotorA(librarianData, forceRefresh = false) {
  const schoolsContainer = document.getElementById("epistemic-schools-container");
  const mainpathContainer = document.getElementById("epistemic-mainpath-container");
  const indicator = document.getElementById("epistemic-corpus-indicator");

  // El análisis epistémico se acota a las primeras 30 obras por coste del grafo. Se declara
  // en la interfaz: si no, el investigador cree que se analizó TODO su resultado.
  const TOPE_OBRAS_GRAFO = 30;
  const todasLasDois = (librarianData && librarianData.articles)
    ? librarianData.articles.map(a => a.doi).filter(Boolean)
    : [];
  const articleDois = todasLasDois.slice(0, TOPE_OBRAS_GRAFO);

  if (indicator) {
    if (articleDois.length > 0) {
      indicator.textContent = todasLasDois.length > TOPE_OBRAS_GRAFO
        ? `Corpus anclado al tema (${articleDois.length} de ${todasLasDois.length} obras: el análisis epistémico se acota a las ${TOPE_OBRAS_GRAFO} primeras por coste del grafo)`
        : `Corpus anclado al tema (${articleDois.length} obras)`;
    } else {
      indicator.textContent = "Vista global del catálogo (sin tema específico)";
    }
  }

  if (epistemicSubmotorLoaded && !forceRefresh) return;
  epistemicSubmotorLoaded = true;

  if (schoolsContainer) {
    schoolsContainer.innerHTML = `<div class="loading-placeholder">Analizando escuelas de pensamiento mediante Union-Find...</div>`;
  }
  if (mainpathContainer) {
    mainpathContainer.innerHTML = `<div class="loading-placeholder">Calculando Trayectoria Principal (SPC) histórica...</div>`;
  }

  // 1. Escuelas de Pensamiento (asíncrono, no bloqueante)
  try {
    const schoolsParams = articleDois.length > 0
      ? { limit: 12, threshold: 2, dois: articleDois }
      : { limit: 12, threshold: 2 };
    const schoolsData = await api("/graph/schools", schoolsParams);
    renderEpistemicSchools(schoolsData.schools || []);
  } catch (err) {
    console.error("Error al cargar escuelas de pensamiento:", err);
    if (schoolsContainer) {
      schoolsContainer.innerHTML = `<div class="snowball-empty-hint">No se pudieron calcular escuelas: ${esc(err.message || err)}</div>`;
    }
  }

  // 2. Main Path (asíncrono)
  try {
    const mpParams = articleDois.length > 0 ? { top_n: 15, dois: articleDois } : { top_n: 15 };
    const mpData = await api("/graph/main-path", mpParams);
    renderMainPath(mpData.main_path_transitions || []);
  } catch (err) {
    console.error("Error al cargar Main Path:", err);
    if (mainpathContainer) {
      mainpathContainer.innerHTML = `<div class="snowball-empty-hint">No se pudo calcular la trayectoria principal: ${esc(err.message || err)}</div>`;
    }
  }
}

async function loadRolesStep0(librarianData) {
  const rolesContainer = document.getElementById("epistemic-roles-container");
  const transferSummary = document.getElementById("roles-transfer-summary");
  if (!rolesContainer) return;

  const articleDois = (librarianData && librarianData.articles)
    ? librarianData.articles.map(a => a.doi).filter(Boolean)
    : [];

  try {
    const rolesParams = articleDois.length > 0 ? { dois: articleDois } : { limit: 100 };
    const rolesData = await api("/graph/roles", rolesParams);
    const roleMap = new Map();
    (rolesData.roles || []).forEach(r => {
      if (r.doi) roleMap.set(r.doi.toLowerCase().trim(), r);
    });

    if (librarianData && librarianData.articles && librarianData.articles.length > 0) {
      currentEpistemicRoles = librarianData.articles.map(a => {
        const doiKey = (a.doi || "").toLowerCase().trim();
        const matched = roleMap.get(doiKey);
        if (matched) {
          return {
            ...matched,
            source: matched.source || a.source || a.source_engine || "openalex",
          };
        }
        const title = (a.title || "").toLowerCase();
        let role = "Empirical";
        if (/revisi[oó]n|review|systematic|scoping|meta-anal|estado del arte/i.test(title)) role = "Synthesis/Review";
        else if (/metodolog[ií]a|methodology|escala|scale|validaci[oó]n|instrumento|protocol/i.test(title)) role = "Methodological";
        else if (/marco te[oó]rico|theoretical|epistemolog|conceptual/i.test(title)) role = "Theoretical/Framework";
        else if ((a.cited_by || a.cited_by_global || 0) >= 35) role = "Seminal";
        return {
          id: a.id,
          doi: a.doi,
          title: a.title,
          year: a.year,
          journal: a.journal_title || a.journal,
          cited_by_global: a.cited_by || a.cited_by_global || 0,
          role: role,
          source: a.source || a.source_engine || "openalex",
          abstract: a.abstract,
          authors: a.authors,
          url: a.url,
        };
      });
    } else {
      currentEpistemicRoles = rolesData.roles || [];
    }

    if (!currentEpistemicRoles || currentEpistemicRoles.length === 0) {
      // Si no hay roles en memoria pero el protocolo activo ya tiene obras, cargarlas desde el protocolo
      try {
        const pid = await ensureProtocol();
        if (pid) {
          const scData = await api(`/review/protocol/${pid}/screenings`, { limit: 60 });
          if (scData && scData.screenings && scData.screenings.length > 0) {
            currentEpistemicRoles = scData.screenings.map(s => {
              const title = (s.title || "").toLowerCase();
              let role = "Empirical";
              if (/revisi[oó]n|review|systematic|scoping|meta-anal|estado del arte/i.test(title)) role = "Synthesis/Review";
              else if (/metodolog[ií]a|methodology|escala|scale|validaci[oó]n|instrumento|protocol/i.test(title)) role = "Methodological";
              else if (/marco te[oó]rico|theoretical|epistemolog|conceptual/i.test(title)) role = "Theoretical/Framework";
              else if ((s.cited_by || s.cited_by_global || 0) >= 35) role = "Seminal";
              return {
                id: s.article_id || s.id,
                doi: s.doi,
                title: s.title,
                year: s.year,
                journal: s.journal_title,
                cited_by_global: s.cited_by || 0,
                role: role,
                source: s.source || "openalex",
                abstract: s.abstract,
                authors: s.authors,
                url: s.url,
              };
            });
          }
        }
      } catch (_) {}
    }

    renderEpistemicRoles(currentEpistemicRoles);

    if (transferSummary) {
      transferSummary.textContent = `${currentEpistemicRoles.length} publicaciones clasificadas listas para screening`;
    }
  } catch (err) {
    console.error("Error al clasificar roles:", err);
    if (librarianData && librarianData.articles && librarianData.articles.length > 0) {
      currentEpistemicRoles = librarianData.articles.map(a => ({
        id: a.id,
        doi: a.doi,
        title: a.title,
        year: a.year,
        journal: a.journal_title || a.journal,
        cited_by_global: a.cited_by || 0,
        role: "Empirical",
        source: a.source || a.source_engine || "openalex",
        abstract: a.abstract,
        authors: a.authors,
        url: a.url,
      }));
      renderEpistemicRoles(currentEpistemicRoles);
      if (transferSummary) {
        transferSummary.textContent = `${currentEpistemicRoles.length} publicaciones cargadas directamente`;
      }
    } else {
      rolesContainer.innerHTML = `<div class="snowball-empty-hint">Utiliza la <strong>Sonda Federada</strong> arriba para cosechar en tiempo real desde OpenAlex, OpenAIRE y Dialnet para este protocolo.</div>`;
    }
  }

  // Integración de la Sonda Federada en Vivo de Paso 0
  const harvestBtn = document.getElementById("btn-protocol-harvest");
  const harvestInput = document.getElementById("input-protocol-harvest-query");
  const harvestStatus = document.getElementById("protocol-harvest-status");

  if (harvestInput && !harvestInput.value) {
    try {
      const activeProto = window.activeProtocolObj;
      if (activeProto && (activeProto.research_question || activeProto.title)) {
        harvestInput.value = activeProto.research_question || activeProto.title;
      }
    } catch (_) {}
  }

  if (harvestBtn && !harvestBtn.dataset.bound) {
    harvestBtn.dataset.bound = "true";
    harvestBtn.onclick = async () => {
      const pid = await ensureProtocol();
      if (!pid) return;
      const q = (harvestInput ? harvestInput.value : "").trim();
      if (!q) {
        showNotification({ title: "Falta la búsqueda", message: "Ingresa una ecuación de búsqueda o pregunta de investigación.", type: "info" });
        return;
      }
      harvestBtn.disabled = true;
      const origHtml = harvestBtn.innerHTML;
      harvestBtn.innerHTML = `<span class="material-symbols-outlined text-[15px] animate-spin">sync</span> Cosechando...`;
      if (harvestStatus) harvestStatus.innerHTML = `<span class="text-secondary">Consultando en paralelo OpenAlex · OpenAIRE Graph · Dialnet...</span>`;
      try {
        const res = await apiPost(`/review/protocol/${pid}/harvest-search`, { query: q, limit: 100 });
        if (res && res.articles) {
          currentEpistemicRoles = res.articles;
          renderEpistemicRoles(currentEpistemicRoles);
          if (transferSummary) {
            transferSummary.textContent = `${currentEpistemicRoles.length} publicaciones cosechadas listas para screening`;
          }
          if (harvestStatus) {
            harvestStatus.innerHTML = `<span style="color:var(--brand-teal); font-weight:600;">✅ Cosecha completada: ${res.harvested_count || res.articles.length} obras agregadas a screening (Total identificado: ${res.total_matched || res.articles.length}).</span>`;
          }
          await refreshPrismaFlow();
        }
      } catch (err) {
        console.error("Error en cosecha federada:", err);
        if (harvestStatus) {
          harvestStatus.innerHTML = `<span style="color:#EF4444;">Error en la cosecha: ${esc(err.message || err)}</span>`;
        }
      } finally {
        harvestBtn.disabled = false;
        harvestBtn.innerHTML = origHtml;
      }
    };
  }

  // --- Integración de Subida Asistida y Diagnóstico Inteligente de Archivos Propios (CSV/RIS) ---
  const fileInput = document.getElementById("input-protocol-file-upload");
  const triggerBtn = document.getElementById("btn-trigger-file-upload");
  const auditBtn = document.getElementById("btn-audit-file-action");
  const labelFile = document.getElementById("label-file-selected");
  const uploadStatus = document.getElementById("protocol-upload-status");
  const modalAudit = document.getElementById("modal-file-audit");
  const closeAuditBtn = document.getElementById("btn-close-audit-modal");
  const cancelAuditBtn = document.getElementById("btn-cancel-audit");
  const confirmCommitBtn = document.getElementById("btn-confirm-import-commit");

  let pendingUploadFile = null;

  if (triggerBtn && !triggerBtn.dataset.bound) {
    triggerBtn.dataset.bound = "true";
    triggerBtn.onclick = () => fileInput && fileInput.click();
  }

  if (fileInput && !fileInput.dataset.bound) {
    fileInput.dataset.bound = "true";
    fileInput.onchange = () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) return;
      pendingUploadFile = file;
      if (labelFile) labelFile.textContent = file.name;
      if (auditBtn) {
        auditBtn.disabled = false;
        auditBtn.classList.remove("btn-secondary");
        auditBtn.classList.add("btn-primary");
      }
      if (uploadStatus) {
        uploadStatus.innerHTML = `<span style="color:var(--brand-teal);">Archivo listo: <strong>${esc(file.name)}</strong> (${(file.size / (1024*1024)).toFixed(2)} MB). Pulsa "Auditar".</span>`;
      }
    };
  }

  const closeAuditModal = () => {
    if (modalAudit) modalAudit.hidden = true;
  };

  if (closeAuditBtn) closeAuditBtn.onclick = closeAuditModal;
  if (cancelAuditBtn) cancelAuditBtn.onclick = closeAuditModal;

  if (auditBtn && !auditBtn.dataset.bound) {
    auditBtn.dataset.bound = "true";
    auditBtn.onclick = async () => {
      if (!pendingUploadFile) {
        showNotification({ title: "Falta el archivo", message: "Selecciona primero un archivo CSV o RIS.", type: "info" });
        return;
      }
      const pid = await ensureProtocol();
      if (!pid) return;

      if (modalAudit) modalAudit.hidden = false;
      const loadingEl = document.getElementById("audit-loading");
      const contentEl = document.getElementById("audit-content");
      if (loadingEl) loadingEl.hidden = false;
      if (contentEl) contentEl.hidden = true;
      if (confirmCommitBtn) confirmCommitBtn.disabled = true;

      const fd = new FormData();
      fd.append("file", pendingUploadFile);

      try {
        const resp = await fetch(`/api/review/protocol/${pid}/upload-audit`, {
          method: "POST",
          body: fd,
        });
        if (!resp.ok) {
          const errData = await resp.json().catch(() => ({}));
          throw new Error(errData.detail || `Error HTTP ${resp.status}`);
        }
        const data = await resp.json();

        if (loadingEl) loadingEl.hidden = true;
        if (contentEl) contentEl.hidden = false;

        const fnEl = document.getElementById("audit-filename");
        if (fnEl) fnEl.textContent = data.filename || pendingUploadFile.name;
        const fmtEl = document.getElementById("audit-format");
        if (fmtEl) fmtEl.textContent = data.recommendation ? data.recommendation.format_type : "CSV";
        const rowsEl = document.getElementById("audit-total-rows");
        if (rowsEl) rowsEl.textContent = Number(data.total_rows || 0).toLocaleString();
        const absEl = document.getElementById("audit-abstract-pct");
        if (absEl) absEl.textContent = `${data.coverage ? data.coverage.abstract_pct : 0}%`;
        const doiEl = document.getElementById("audit-doi-pct");
        if (doiEl) doiEl.textContent = `${data.coverage ? data.coverage.doi_pct : 0}%`;

        const warnBox = document.getElementById("audit-warning-box");
        const warnText = document.getElementById("audit-warning-text");
        if (data.recommendation && data.recommendation.warning) {
          if (warnBox) warnBox.style.display = "block";
          if (warnText) warnText.textContent = data.recommendation.warning;
        } else {
          if (warnBox) warnBox.style.display = "none";
        }

        const solText = document.getElementById("audit-solution-text");
        if (solText && data.recommendation) {
          solText.textContent = data.recommendation.solution_msg;
        }

        const sampleList = document.getElementById("audit-sample-list");
        if (sampleList) {
          sampleList.innerHTML = (data.sample_preview || []).map(p => `
            <div style="padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.05);">
              <strong style="color:var(--text-primary);">${esc(p.title)}</strong>
              <div style="color:var(--text-secondary); font-size:0.7rem;">${esc(p.authors || "S/A")} • ${p.year || "S/F"} ${p.has_abstract ? '• <span style="color:#10B981;">Con Abstract</span>' : ''}</div>
            </div>
          `).join("");
        }

        if (confirmCommitBtn) {
          confirmCommitBtn.disabled = false;
          confirmCommitBtn.innerHTML = `
            <span class="material-symbols-outlined text-[16px]">file_download_done</span>
            <span>Importar ${Number(data.total_rows || 0).toLocaleString()} Obras y Activar Enriquecedor</span>
          `;
        }
      } catch (err) {
        console.error("Error en auditoría de archivo:", err);
        if (loadingEl) loadingEl.innerHTML = `<div style="color:#EF4444; padding:1rem;">Error al auditar archivo: ${esc(err.message || err)}</div>`;
      }
    };
  }

  if (confirmCommitBtn && !confirmCommitBtn.dataset.bound) {
    confirmCommitBtn.dataset.bound = "true";
    confirmCommitBtn.onclick = async () => {
      if (!pendingUploadFile) return;
      const pid = await ensureProtocol();
      if (!pid) return;

      confirmCommitBtn.disabled = true;
      const origHtml = confirmCommitBtn.innerHTML;
      confirmCommitBtn.innerHTML = `<span class="material-symbols-outlined animate-spin text-[16px]">sync</span> Importando obras a la base de datos...`;

      const fd = new FormData();
      fd.append("file", pendingUploadFile);

      try {
        const resp = await fetch(`/api/review/protocol/${pid}/upload-commit`, {
          method: "POST",
          body: fd,
        });
        if (!resp.ok) {
          const errData = await resp.json().catch(() => ({}));
          throw new Error(errData.detail || `Error HTTP ${resp.status}`);
        }
        const res = await resp.json();
        closeAuditModal();

        if (uploadStatus) {
          uploadStatus.innerHTML = `<span style="color:var(--brand-teal); font-weight:600;">✅ Importación completada: ${res.total_processed || res.imported_new} obras añadidas a screening en Protocolo ${pid}.</span>`;
        }

        // Refrescar PRISMA y saltar a Screening
        await refreshPrismaFlow();
        goToPrismaStep("screening");
        setupScreeningTab();
      } catch (err) {
        console.error("Error al importar commit:", err);
        showNotification({ title: "Error al importar archivo", message: String(err.message || err), type: "error" });
        confirmCommitBtn.disabled = false;
        confirmCommitBtn.innerHTML = origHtml;
      }
    };
  }
}

function initPrismaStepper() {
  const stepButtons = document.querySelectorAll(".stepper-step");
  stepButtons.forEach(btn => {
    btn.onclick = () => {
      const stepTarget = btn.dataset.step;
      goToPrismaStep(stepTarget);
    };
  });

  // Botón: Enviar todo de Paso 0 a Screening (Paso 1)
  const transferBtn = document.getElementById("btn-transfer-roles-to-screening");
  if (transferBtn) {
    transferBtn.onclick = async () => {
      const pid = await ensureProtocol();
      if (!pid) {
        showNotification({ title: "Falta el protocolo", message: "Selecciona o crea un protocolo primero.", type: "info" });
        return;
      }

      let articles = (currentEpistemicRoles && currentEpistemicRoles.length > 0)
        ? currentEpistemicRoles
        : (lastLibrarianData && lastLibrarianData.articles ? lastLibrarianData.articles : []);

      if (articles.length === 0) {
        // Si no hay artículos en memoria pero el protocolo ya tiene obras importadas, avanzar directo
        goToPrismaStep("step-content-screening");
        return;
      }

      transferBtn.disabled = true;
      transferBtn.innerHTML = `<span class="material-symbols-outlined text-[15px]">hourglass_top</span> Transfiriendo...`;

      try {
        // Se envía el artículo COMPLETO: es aquí (acción explícita) donde el servidor lo
        // persiste. Buscar ya no escribe en la base; transferir a una revisión sí.
        const items = articles.map(a => ({
          doi: a.doi || `article:${a.id}`,
          decision: "pending",
          article_id: a.id,
          article: a,
        }));
        await apiPost(`/review/protocol/${pid}/screen-batch`, { items });

        // Cambiar a Paso 1
        goToPrismaStep("step-content-screening");
        await refreshPrismaFlow();
      } catch (err) {
        console.error("Error al transferir a screening:", err);
        goToPrismaStep("step-content-screening");
      } finally {
        transferBtn.disabled = false;
        transferBtn.innerHTML = `<span class="material-symbols-outlined text-[15px]">send_to_mobile</span> <span>Enviar todo a Screening (Paso 1) →</span>`;
      }
    };
  }

  // Botón: Avanzar de Screening a Charteo (Paso 2)
  const advanceBtn = document.getElementById("btn-advance-to-charting");
  if (advanceBtn) {
    advanceBtn.onclick = () => {
      goToPrismaStep("step-content-charting");
      const loadChartingBtn = document.getElementById("btn-load-charting");
      if (loadChartingBtn) loadChartingBtn.click();
    };
  }

  // Pestañas internas de Síntesis (Paso 3)
  const synthesisPills = document.querySelectorAll(".synthesis-tabs-pills .epistemic-pill");
  synthesisPills.forEach(pill => {
    pill.onclick = () => {
      synthesisPills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      const targetId = pill.dataset.target;
      document.querySelectorAll(".synthesis-subtab").forEach(st => {
        if (st.id === targetId) {
          st.classList.add("active");
          st.hidden = false;
          st.style.display = "block";
        } else {
          st.classList.remove("active");
          st.hidden = true;
          st.style.display = "none";
        }
      });
    };
  });
}

function goToPrismaStep(stepTargetId) {
  let targetId = stepTargetId;
  if (targetId === "screening" || targetId === "step-screening") targetId = "step-content-screening";
  if (targetId === "roles" || targetId === "step-roles") targetId = "step-content-roles";
  if (targetId === "charting" || targetId === "step-charting") targetId = "step-content-charting";
  if (targetId === "synthesis" || targetId === "step-synthesis") targetId = "step-content-synthesis";

  const stepButtons = document.querySelectorAll(".stepper-step");
  stepButtons.forEach(b => {
    if (b.dataset.step === targetId || b.dataset.step === stepTargetId) {
      b.classList.add("active");
    } else {
      b.classList.remove("active");
    }
  });

  document.querySelectorAll(".prisma-step-content").forEach(sc => {
    if (sc.id === targetId || sc.id === stepTargetId) {
      sc.classList.add("active");
      sc.hidden = false;
      sc.style.display = "block";
    } else {
      sc.classList.remove("active");
      sc.hidden = true;
      sc.style.display = "none";
    }
  });

  if (targetId === "step-content-screening") {
    setupScreeningTab();
  } else if (targetId === "step-content-charting") {
    setupChartingTab();
  }
}

function renderEpistemicSchools(schools) {
  const container = document.getElementById("epistemic-schools-container");
  if (!container) return;
  if (!schools || schools.length === 0) {
    container.innerHTML = `<div class="snowball-empty-hint">No se detectaron vecindarios fuertemente conectados en este corte bibliográfico.</div>`;
    return;
  }

  container.innerHTML = "";
  schools.forEach((s, idx) => {
    const card = document.createElement("div");
    card.className = "school-card";

    const topicsHtml = (s.dominant_topics || []).map(t =>
      `<span class="school-topic-tag">${esc(t)}</span>`
    ).join("");

    const seenArtKeys = new Set();
    const uniqueArticles = (s.representative_articles || []).filter(a => {
      const key = (a.id ? `id:${a.id}` : '') + '|' + (a.title || '').trim().toLowerCase();
      if (seenArtKeys.has(key)) return false;
      seenArtKeys.add(key);
      return true;
    });

    const artsHtml = uniqueArticles.slice(0, 3).map(a => `
      <div class="school-article-item">
        <span class="school-article-title">${esc(a.title || "Sin título")}</span>
        <div class="school-article-meta">
          <span>${a.year || "S/F"}</span>
          <span>•</span>
          <span>${esc(a.journal_title || a.journal || "")}</span>
          <span class="role-badge ${esc(a.role || 'Empirical')}">${esc(a.role || 'Empirical')}</span>
        </div>
      </div>
    `).join("");

    card.innerHTML = `
      <div class="school-header">
        <span class="school-badge">Escuela #${s.cluster_id || idx + 1}</span>
        <span class="school-meta">${s.catalog_count} en catálogo • ${s.total_nodes} referencias${(s.corpus_count || 0) > 0 ? ` • <b>${s.corpus_count} de tu consulta</b>` : ""}</span>
      </div>
      <div class="school-topics-wrap">
        ${topicsHtml || '<span class="school-topic-tag">General</span>'}
      </div>
      <div class="school-articles-sub">Obras Núcleo de la Escuela</div>
      <div class="school-articles-list">
        ${artsHtml || '<div style="font-size:0.75rem; color:var(--on-surface-variant);">Artículos externos de referencia</div>'}
      </div>
    `;
    container.appendChild(card);
  });
}

function renderMainPath(transitions) {
  const container = document.getElementById("epistemic-mainpath-container");
  if (!container) return;
  if (!transitions || transitions.length === 0) {
    container.innerHTML = `<div class="snowball-empty-hint">No hay suficientes citas transitivas dentro del catálogo para trazar la trayectoria principal.</div>`;
    return;
  }

  container.innerHTML = "";
  transitions.forEach(t => {
    const item = document.createElement("div");
    item.className = "mainpath-item";

    const src = t.source || {};
    const tgt = t.target || {};

    item.innerHTML = `
      <div class="mainpath-dot"></div>
      <div class="mainpath-flow-row">
        <span class="spc-weight-badge">Flujo SPC: ${t.spc_weight}</span>
        <span style="color:var(--on-surface-variant);">Salto temporal: ${t.year_gap > 0 ? `+${t.year_gap} años` : 'Mismo periodo'}</span>
      </div>
      <div class="mainpath-transition">
        <div class="mainpath-work mainpath-source">
          <strong>${src.year || 'S/F'} · Fundamento:</strong> ${esc(src.title || "Sin título")}
          <div style="font-size:0.72rem; color:var(--on-surface-variant); margin-top:2px;">
            ${esc(src.journal || "")} · Rol: <span class="role-badge ${esc(src.role || 'Seminal')}">${esc(src.role || 'Seminal')}</span>
          </div>
        </div>
        <div style="display:flex; justify-content:center; color:var(--brand-teal);">
          <span class="material-symbols-outlined text-[18px]">arrow_downward</span>
        </div>
        <div class="mainpath-work mainpath-target">
          <strong>${tgt.year || 'S/F'} · Evolución / Continuador:</strong> ${esc(tgt.title || "Sin título")}
          <div style="font-size:0.72rem; color:var(--on-surface-variant); margin-top:2px;">
            ${esc(tgt.journal || "")} · Rol: <span class="role-badge ${esc(tgt.role || 'Empirical')}">${esc(tgt.role || 'Empirical')}</span>
          </div>
        </div>
      </div>
    `;
    container.appendChild(item);
  });
}

let activeEpistemicRoleFilter = "all";
let activeEpistemicSourceFilter = "all";

function renderEpistemicRoles(roles) {
  const container = document.getElementById("epistemic-roles-container");
  if (!container) return;

  const counts = { all: roles.length, seminal: 0, review: 0, theory: 0, method: 0, empirical: 0 };
  const srcCounts = { all: roles.length, openalex: 0, openaire: 0, dialnet: 0 };

  roles.forEach(r => {
    const role = r.role || "Empirical";
    if (role === "Seminal") counts.seminal++;
    else if (role.includes("Review") || role.includes("Synthesis")) counts.review++;
    else if (role.includes("Theoret")) counts.theory++;
    else if (role.includes("Method")) counts.method++;
    else counts.empirical++;

    const s = String(r.source || r.source_engine || "").toLowerCase();
    if (s.includes("openaire")) srcCounts.openaire++;
    else if (s.includes("dialnet")) srcCounts.dialnet++;
    else srcCounts.openalex++;
  });

  const setC = (id, n) => { const el = document.getElementById(id); if (el) el.textContent = n; };
  setC("count-role-all", counts.all);
  setC("count-role-seminal", counts.seminal);
  setC("count-role-review", counts.review);
  setC("count-role-theory", counts.theory);
  setC("count-role-method", counts.method);
  setC("count-role-empirical", counts.empirical);

  setC("count-role-src-all", srcCounts.all);
  setC("count-role-src-openalex", srcCounts.openalex);
  setC("count-role-src-openaire", srcCounts.openaire);
  setC("count-role-src-dialnet", srcCounts.dialnet);

  const filterChips = document.querySelectorAll(".role-chip");
  filterChips.forEach(chip => {
    chip.onclick = () => {
      filterChips.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      activeEpistemicRoleFilter = chip.dataset.role;
      filterRolesList();
    };
  });

  const sourceChips = document.querySelectorAll(".role-src-chip");
  sourceChips.forEach(chip => {
    chip.onclick = () => {
      sourceChips.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      activeEpistemicSourceFilter = chip.dataset.source;
      filterRolesList();
    };
  });

  filterRolesList();
}

function filterRolesList() {
  const container = document.getElementById("epistemic-roles-container");
  if (!container) return;

  const roleFilter = activeEpistemicRoleFilter;
  const srcFilter = activeEpistemicSourceFilter;

  const filtered = currentEpistemicRoles.filter(r => {
    const rRole = r.role || "Empirical";
    let roleOk = true;
    if (roleFilter === "Seminal") roleOk = (rRole === "Seminal");
    else if (roleFilter.includes("Review")) roleOk = (rRole.includes("Review") || rRole.includes("Synthesis"));
    else if (roleFilter.includes("Theoret")) roleOk = rRole.includes("Theoret");
    else if (roleFilter.includes("Method")) roleOk = rRole.includes("Method");
    else if (roleFilter === "Empirical") roleOk = (rRole === "Empirical");

    if (!roleOk) return false;

    if (srcFilter !== "all") {
      const s = String(r.source || r.source_engine || "").toLowerCase();
      if (srcFilter === "openaire" && !s.includes("openaire")) return false;
      if (srcFilter === "dialnet" && !s.includes("dialnet")) return false;
      if (srcFilter === "openalex" && (s.includes("openaire") || s.includes("dialnet"))) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    container.innerHTML = `<div class="snowball-empty-hint" style="grid-column:1/-1;">No hay artículos que coincidan con estos filtros de rol y base de datos.</div>`;
    return;
  }

  container.innerHTML = "";
  filtered.forEach(r => {
    const card = document.createElement("div");
    card.className = "role-card";
    const role = r.role || "Empirical";
    const rawSrc = String(r.source || r.source_engine || "openalex").toLowerCase();
    const isAire = rawSrc.includes("openaire");
    const isDial = rawSrc.includes("dialnet");
    const srcBadge = isAire
      ? `<span class="source-badge badge-openaire">🇪🇺 OpenAIRE</span>`
      : isDial
      ? `<span class="source-badge badge-dialnet">📚 Dialnet</span>`
      : `<span class="source-badge badge-openalex">🌐 OpenAlex</span>`;

    card.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <div style="display:flex; gap:6px; align-items:center;">
          <span class="role-badge ${esc(role)}">${esc(role)}</span>
          ${srcBadge}
        </div>
        <span style="font-size:0.75rem; font-weight:600; color:var(--brand-teal);">Citas int: ${r.indegree_catalog || 0}</span>
      </div>
      <div style="font-weight:600; font-size:0.86rem; color:var(--on-surface); line-height:1.35; margin-top:6px;">
        ${esc(r.title || "Sin título")}
      </div>
      <div style="font-size:0.74rem; color:var(--on-surface-variant); margin-top:4px;">
        ${r.year || 'S/F'} • ${esc(r.journal || "")} • Citas globales: ${Number(r.cited_by_global || 0).toLocaleString()}
      </div>
      <div style="margin-top:auto; display:flex; gap:8px; align-items:center; padding-top:8px;">
        ${r.doi ? `
          <button type="button" class="btn btn-ghost sm" style="padding:2px 8px; font-size:0.72rem;" onclick="launchSnowballFromDoi('${esc(r.doi)}')">
            <span class="material-symbols-outlined text-[13px]">account_tree</span>
            <span>Snowballing</span>
          </button>
        ` : ''}
      </div>
    `;
    container.appendChild(card);
  });
}

function extractCleanDoi(val) {
  if (!val) return "";
  const s = String(val).trim();
  const m = s.match(/(10\.\d{4,9}\/[^\s"'>]+)/i);
  if (m) {
    return m[1].toLowerCase().replace(/[.,;/]+$/, "");
  }
  return s.replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "")
          .replace(/^(?:dx\.)?doi\.org\//i, "")
          .replace(/^doi:\s*/i, "")
          .toLowerCase()
          .trim()
          .replace(/[.,;/]+$/, "");
}

window.launchSnowballFromDoi = function(doi) {
  const pillSnowball = document.getElementById("tab-pill-snowball");
  if (pillSnowball) pillSnowball.click();
  const clean = extractCleanDoi(doi);
  const input = document.getElementById("snowball-doi-input");
  if (input) input.value = clean;
  const btn = document.getElementById("btn-run-snowball");
  if (btn) btn.click();
};

function setupSnowballingExplorer(librarianData) {
  const btn = document.getElementById("btn-run-snowball");
  const input = document.getElementById("snowball-doi-input");
  const dirSelect = document.getElementById("snowball-direction-select");
  const container = document.getElementById("epistemic-snowball-container");
  const seedsContainer = document.getElementById("snowball-seeds-container");

  if (!btn || !input || !container) return;

  // Extraer candidatos para semillas sugeridas
  let candidateArticles = (librarianData && librarianData.articles && librarianData.articles.length > 0)
    ? librarianData.articles.filter(a => a.doi)
    : [];

  if (candidateArticles.length === 0 && Array.isArray(currentEpistemicRoles) && currentEpistemicRoles.length > 0) {
    candidateArticles = currentEpistemicRoles.filter(a => a.doi);
  }

  // Renderizar chips de semillas sugeridas
  if (seedsContainer) {
    if (candidateArticles.length > 0) {
      const topCandidates = candidateArticles.slice(0, 5);
      seedsContainer.innerHTML = `
        <span class="snowball-seeds-label">
          <span class="material-symbols-outlined text-[15px]">tips_and_updates</span>
          <span>${librarianData ? 'Obras de tu consulta:' : 'Semillas recomendadas:'}</span>
        </span>
        ${topCandidates.map((a, idx) => {
          const rawTitle = a.title || a.doi || "Artículo";
          const shortTitle = rawTitle.length > 42 ? rawTitle.slice(0, 42) + "..." : rawTitle;
          return `
            <button type="button" class="snowball-seed-chip ${idx === 0 && !input.value ? 'active' : ''}" data-doi="${esc(a.doi)}" title="${esc(rawTitle)}">
              <span>🌱 ${esc(shortTitle)}</span>
              ${a.year ? `<span class="chip-year">(${a.year})</span>` : ''}
            </button>
          `;
        }).join("")}
      `;

      seedsContainer.querySelectorAll(".snowball-seed-chip").forEach(chip => {
        chip.onclick = () => {
          seedsContainer.querySelectorAll(".snowball-seed-chip").forEach(c => c.classList.remove("active"));
          chip.classList.add("active");
          const chipDoi = chip.dataset.doi;
          if (input && chipDoi) {
            input.value = extractCleanDoi(chipDoi);
            if (btn) btn.click();
          }
        };
      });
    } else {
      seedsContainer.innerHTML = "";
    }
  }

  // Pre-cargar la primera semilla si el input está vacío y lanzar expansión inicial
  if (!input.value && candidateArticles.length > 0) {
    input.value = extractCleanDoi(candidateArticles[0].doi);
    setTimeout(() => {
      btn.click();
    }, 150);
  }

  btn.onclick = async () => {
    let rawDoi = input.value.trim();
    if (!rawDoi) {
      if (candidateArticles.length > 0) {
        input.value = extractCleanDoi(candidateArticles[0].doi);
        rawDoi = input.value;
      } else {
        container.innerHTML = `<div class="snowball-empty-hint">Por favor, ingresa un DOI o haz clic en una de las semillas recomendadas.</div>`;
        input.focus();
        return;
      }
    }
    const doi = extractCleanDoi(rawDoi);
    input.value = doi;
    const dir = dirSelect ? dirSelect.value : "both";

    container.innerHTML = `<div class="loading-placeholder">Rastreando ancestros y descendientes de ${esc(doi)}...</div>`;

    try {
      const data = await api("/graph/expand", { doi: doi, direction: dir, limit: 30 });
      if (data.error) {
        container.innerHTML = `<div class="snowball-empty-hint">${esc(data.error)}</div>`;
        return;
      }

      const seed = data.seed || {};
      const arts = data.articles || [];
      const edges = data.network_edges || [];

      let artsHtml = arts.map(a => `
        <div class="school-article-item" style="border-left: 3px solid ${a.is_seed ? 'var(--brand-teal)' : '#64748B'};">
          <div style="display:flex; justify-content:space-between; margin-bottom:2px;">
            <strong style="color:var(--on-surface); font-size:0.82rem;">${a.is_seed ? '🌱 Semilla' : (a.relation || 'Relacionado')}</strong>
            <span class="role-badge ${esc(a.role || 'Empirical')}">${esc(a.role || 'Empirical')}</span>
          </div>
          <span class="school-article-title">${esc(a.title || "Sin título")}</span>
          <div class="school-article-meta">
            <span>${a.year || 'S/F'}</span>
            <span>•</span>
            <span>${esc(a.journal_title || "")}</span>
            <span>•</span>
            <span>Citas: ${a.cited_by || 0}</span>
          </div>
          ${!a.is_seed && a.doi ? `
            <div style="margin-top:6px;">
              <button type="button" class="btn btn-ghost sm" style="padding:2px 8px; font-size:0.72rem;" onclick="launchSnowballFromDoi('${esc(a.doi)}')">
                <span class="material-symbols-outlined text-[13px]" style="vertical-align:-2px;">travel_explore</span>
                <span>Expandir este (Snowballing)</span>
              </button>
            </div>
          ` : ''}
        </div>
      `).join("");

      const singleSeedNote = (arts.length <= 1) ? `
        <div class="snowball-empty-hint" style="text-align:left; background:rgba(0,106,106,0.05); border-left:3px solid var(--brand-teal); border-radius:8px; padding:12px 16px; margin-top:10px;">
          <strong>🌱 Artículo semilla identificado:</strong> <em>${esc(seed.title || doi)}</em>.<br>
          <span style="font-size:0.8rem; color:var(--on-surface-variant);">Registra ${seed.cited_by || 0} citas globales. En este corte bibliográfico local aún no presenta vínculos cerrados con otros papers del acervo. Puedes seleccionar otra obra recomendada arriba o ingresar un DOI diferente.</span>
        </div>
      ` : '';

      container.innerHTML = `
        <div class="snowball-results-box">
          <div class="snowball-stat-row">
            <span>Artículo semilla: ${esc(seed.title || doi)} (${seed.year || 'S/F'})</span>
          </div>
          <div class="snowball-stat-row" style="font-size:0.78rem; color:var(--on-surface-variant); font-weight:normal;">
            <span>Dirección: <strong>${dir}</strong></span> • 
            <span>Obras conectadas: <strong>${data.expanded_count}</strong></span> • 
            <span>Vínculos internos de citación: <strong>${edges.length}</strong></span>
          </div>
          ${singleSeedNote}
          <div style="margin-top:12px; display:flex; flex-direction:column; gap:8px;">
            ${artsHtml}
          </div>
        </div>
      `;
    } catch (err) {
      console.error("Snowballing error:", err);
      container.innerHTML = `<div class="snowball-empty-hint">No se pudo expandir el DOI «${esc(doi)}»: verifique que el DOI esté registrado o tenga referencias disponibles.</div>`;
    }
  };
}

// ================================================================
// VALIDACIÓN HUMANA DE CONTEXTOS DE CITACIÓN
// ================================================================
const VALIDATION_FUNCTIONS = [
  "supporting_or_agreement",
  "contrasting_or_refuting",
  "methodological_adoption",
  "neutral_or_mention",
];

const VALIDATION_FUNCTION_LABELS = {
  supporting_or_agreement: "Posible consenso",
  contrasting_or_refuting: "Posible disenso",
  methodological_adoption: "Posible adopción metodológica",
  neutral_or_mention: "Posible mención contextual",
};

function validationFunctionLabel(fn) {
  return VALIDATION_FUNCTION_LABELS[fn] || fn || "—";
}

async function loadValidationQueue() {
  const container = document.getElementById("epistemic-validation-container");
  const statusSelect = document.getElementById("validation-status-select");
  if (!container) return;
  const status = statusSelect ? statusSelect.value : "pending";
  container.innerHTML = `<div class="loading-placeholder">Cargando contextos...</div>`;
  try {
    const params = { limit: 30 };
    if (status) params.status = status;
    const data = await api("/citation-contexts", params);
    renderValidationQueue(data.contexts || []);
  } catch (err) {
    console.error("Error cargando validación:", err);
    container.innerHTML = `<div class="snowball-empty-hint">No se pudo cargar la cola: ${esc(err.message || err)}</div>`;
  }
}

function renderValidationQueue(contexts) {
  const container = document.getElementById("epistemic-validation-container");
  if (!container) return;
  if (!contexts.length) {
    container.innerHTML = `<div class="snowball-empty-hint">Sin contextos en este estado: sube un PDF o ejecuta la ingesta para generar interpretaciones a validar.</div>`;
    return;
  }
  container.innerHTML = "";
  contexts.forEach(c => {
    const card = document.createElement("div");
    card.className = "school-article-item";
    card.style.borderLeft = "3px solid var(--brand-teal)";
    const fnOpts = VALIDATION_FUNCTIONS.map(f =>
      `<option value="${f}"${f === c.sentiment ? " selected" : ""}>${validationFunctionLabel(f)}</option>`
    ).join("");
    card.innerHTML = `
      <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <strong style="font-size:0.8rem;">Cita: ${esc((c.citing_doi || "").slice(0, 42))} → ${esc((c.cited_doi || "").slice(0, 42))}</strong>
        <span class="role-badge ${esc(c.sentiment || 'neutral_or_mention')}">${esc(validationFunctionLabel(c.sentiment))}</span>
      </div>
      <div class="school-article-title" style="font-style:italic;">«${esc(c.sentence || "")}»</div>
      <div class="school-article-meta"><span>${esc(c.section || "body")}</span><span>•</span><span>confianza: ${esc(c.confidence || "heuristic")}</span><span>•</span><span>estado: ${esc(c.validation_status || "pending")}</span></div>
      ${c.claim_text ? `<div style="font-size:0.78rem; margin-top:4px;"><b>Claim IA:</b> «${esc(c.claim_text)}»</div>` : ""}
      ${c.paragraph ? `<details style="font-size:0.75rem; margin-top:4px;"><summary>Ver párrafo de evidencia</summary><p>${esc(c.paragraph)}</p></details>` : ""}
      <div class="validation-editor" hidden>
        <select class="filter-select validation-fn-select">${fnOpts}</select>
        <input type="text" class="filter-input validation-claim-input" placeholder="Claim corregido (cita literal)" value="${esc(c.claim_text || "")}">
      </div>
      <div style="display:flex; gap:6px; margin-top:8px; flex-wrap:wrap;">
        <button type="button" class="btn btn-ghost sm" data-vaction="validated">✓ Validar</button>
        <button type="button" class="btn btn-ghost sm" data-vaction="edit">✎ Corregir</button>
        <button type="button" class="btn btn-ghost sm" data-vaction="rejected">✕ Rechazar</button>
        <button type="button" class="btn btn-primary sm" data-vaction="save" hidden>Guardar corrección</button>
      </div>
    `;
    const editor = card.querySelector(".validation-editor");
    const saveBtn = card.querySelector('[data-vaction="save"]');
    const sendDecision = async (decision, corrected) => {
      try {
        await apiPost(`/citation-contexts/${c.id}/validate`, {
          decision, ...(corrected || {}), by: "researcher",
        });
        loadValidationQueue();
      } catch (err) {
        console.error("Error validando:", err);
      }
    };
    card.querySelector('[data-vaction="validated"]').onclick = () => sendDecision("validated");
    card.querySelector('[data-vaction="rejected"]').onclick = () => sendDecision("rejected");
    card.querySelector('[data-vaction="edit"]').onclick = () => {
      editor.hidden = !editor.hidden;
      saveBtn.hidden = editor.hidden;
    };
    saveBtn.onclick = () => sendDecision("corrected", {
      corrected_function: card.querySelector(".validation-fn-select").value,
      corrected_claim: card.querySelector(".validation-claim-input").value.trim(),
    });
    container.appendChild(card);
  });
}

async function apiUploadPdf(file, doi) {
  // Subida multipart (el helper api() solo habla JSON): el navegador fija el boundary.
  const form = new FormData();
  form.append("file", file, file.name || "paper.pdf");
  const qs = doi ? `?doi=${encodeURIComponent(doi)}` : "";
  const url = `${API}/fulltext/extract-pdf${qs}`;
  let resp;
  try {
    resp = await fetch(url, { method: "POST", headers: { Accept: "application/json" }, body: form });
  } catch (e) {
    throw new Error(`no se pudo contactar ${url}. ¿Está corriendo el backend? Usa "inicio.bat" o arranca uvicorn.`);
  }
  if (!resp.ok) throw new Error(`API ${resp.status}: ${url}`);
  return resp.json();
}

function setupValidationQueue() {
  const btn = document.getElementById("btn-reload-validation");
  const sel = document.getElementById("validation-status-select");
  if (btn) btn.onclick = () => loadValidationQueue();
  if (sel) sel.onchange = () => loadValidationQueue();

  const fileInput = document.getElementById("pdf-upload-input");
  const doiInput = document.getElementById("pdf-upload-doi");
  const uploadBtn = document.getElementById("btn-upload-pdf");
  const statusEl = document.getElementById("pdf-upload-status");
  if (!uploadBtn || !fileInput) return;
  const setStatus = (msg, isError) => {
    if (!statusEl) return;
    statusEl.hidden = false;
    statusEl.innerHTML = msg;
    statusEl.style.borderLeft = isError ? "3px solid #ef4444" : "3px solid var(--brand-teal)";
  };
  uploadBtn.onclick = async () => {
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      setStatus("Selecciona primero un archivo PDF para adjuntar.", true);
      fileInput.focus();
      return;
    }
    const doi = doiInput ? doiInput.value.trim() : "";
    uploadBtn.disabled = true;
    setStatus(`Analizando «${esc(file.name)}» (texto completo, contextos e ingeridos)...`);
    try {
      const data = await apiUploadPdf(file, doi);
      const byFn = data.by_function || {};
      const fnSummary = Object.entries(byFn).map(([k, v]) => `${validationFunctionLabel(k)}: ${v}`).join(" • ") || "sin contextos";
      const cited = (data.ingested_cited || []).length;
      setStatus(`<strong>✓ ${esc(file.name)}</strong> — ${data.word_count || 0} palabras, ${data.sections_found ? data.sections_found.length : 0} secciones, ${data.citation_contexts_extracted || 0} contextos (${esc(fnSummary)})${cited ? `, ${cited} citados auto-ingeridos` : ""}. Revisa la cola de pendientes.`);
      fileInput.value = "";
      loadValidationQueue();
    } catch (err) {
      console.error("Error subiendo PDF:", err);
      setStatus(`No se pudo analizar el PDF: ${esc(err.message || err)}`, true);
    } finally {
      uploadBtn.disabled = false;
    }
  };
}

function renderSystematicMarkdown(mdText) {
  // Render mínimo y seguro: se escapa primero y luego se maquetan
  // encabezados, negritas, listas y tablas Markdown.
  const safe = esc(mdText || "");
  const lines = safe.split("\n");
  let html = "";
  let inList = false;
  let i = 0;
  const inline = s => s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  const isSep = cells => cells.length >= 2 && cells.every(c => /^:?-{2,}:?$/.test(c));
  const splitRow = line => line.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
  while (i < lines.length) {
    const line = lines[i];
    const t = line.trim();
    if (t.startsWith("|") && t.endsWith("|") && t.includes("|", 1)) {
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        rows.push(splitRow(lines[i]));
        i++;
      }
      const body = rows.filter(r => !isSep(r));
      if (!body.length) continue;
      const head = body[0];
      const rest = body.slice(1);
      html += `<div style="overflow-x:auto;margin:8px 0;"><table style="border-collapse:collapse;font-size:0.78rem;width:100%;">`
        + `<thead><tr>${head.map(c => `<th style="border:1px solid var(--outline-variant,#cbd5e1);padding:4px 8px;background:rgba(0,106,106,0.08);text-align:left;">${inline(c)}</th>`).join("")}</tr></thead>`
        + `<tbody>${rest.map(r => `<tr>${r.map(c => `<td style="border:1px solid var(--outline-variant,#cbd5e1);padding:4px 8px;vertical-align:top;">${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
      continue;
    }
    if (/^#{1,4}\s/.test(t)) {
      if (inList) { html += "</ul>"; inList = false; }
      const level = Math.min(4, t.match(/^#+/)[0].length);
      html += `<h${level + 1} style="margin:12px 0 6px;">${inline(t.replace(/^#+\s*/, ""))}</h${level + 1}>`;
    } else if (/^([-*•]|\d+[.)])\s+/.test(t)) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inline(t.replace(/^([-*•]|\d+[.)])\s+/, ""))}</li>`;
    } else if (!t) {
      if (inList) { html += "</ul>"; inList = false; }
    } else {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<p style="margin:6px 0;">${inline(t)}</p>`;
    }
    i++;
  }
  if (inList) html += "</ul>";
  return html;
}

function setupSystematicTab() {
  const btn = document.getElementById("btn-run-systematic");
  const inquiryInput = document.getElementById("systematic-inquiry-input");
  const booleanInput = document.getElementById("systematic-boolean-input");
  const statusEl = document.getElementById("systematic-status");
  const container = document.getElementById("epistemic-systematic-container");
  if (!btn || !inquiryInput || !container) return;

  // Prefill con la consulta actual del home si el campo está vacío
  const homeInput = document.getElementById("home-inquiry-input");
  if (homeInput && homeInput.value.trim() && !inquiryInput.value) {
    inquiryInput.value = homeInput.value.trim();
  }

  const setStatus = msg => {
    if (!statusEl) return;
    statusEl.hidden = false;
    statusEl.innerHTML = msg;
  };

  btn.onclick = async () => {
    const inquiry = inquiryInput.value.trim();
    if (!inquiry) {
      setStatus("Escribe primero tu pregunta de investigación.");
      inquiryInput.focus();
      return;
    }
    const booleanQuery = booleanInput ? booleanInput.value.trim() : "";
    btn.disabled = true;
    setStatus("Generando informe PRISMA en 7 fases (unos minutos, no cierres)...");
    container.innerHTML = `<div class="loading-placeholder">El Metodólogo redacta sobre el corpus verificado...</div>`;
    try {
      const body = { inquiry, limit: 30 };
      if (screeningProtocolId) body.protocol_id = screeningProtocolId;
      if (booleanQuery) body.boolean_query = booleanQuery;
      const data = await apiPost("/review/systematic", body);
      if (data.status !== "ok") {
        const warn = data.warning ? `<br><small style="color:var(--text-secondary,#888);">${esc(data.warning)}</small>` : "";
        setStatus(esc(data.report || "Sin corpus verificado para esta pregunta.") + warn);
        container.innerHTML = `<div class="snowball-empty-hint">${esc(data.report || "")}${warn}</div>`;
        return;
      }
      const audit = data.audit || {};
      const auditLine = audit.clean
        ? `Auditoría: ${audit.rows_checked || 0} filas verificadas contra el corpus, sin invenciones.`
        : `Auditoría: revisar ${(audit.unmatched || []).length} filas y ${(audit.foreign_dois || []).length} DOIs ajenos.`;
      setStatus(`<strong>${esc(data.sample_message || "")}</strong><br>Corpus: ${data.corpus_count} artículos • ${esc(auditLine)}`);
      container.innerHTML = renderSystematicMarkdown(data.report || "");
      container.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
      console.error("Error generando informe:", err);
      setStatus(`No se pudo generar el informe: ${esc(err.message || err)}`);
      container.innerHTML = `<div class="snowball-empty-hint">Verifica que el backend y el LLM local estén corriendo.</div>`;
    } finally {
      btn.disabled = false;
    }
  };
}

// ================================================================
// ================================================================
// GESTOR DE PROYECTOS / PROTOCOLOS PERSISTENTES (PRISMA / JBI)
// ================================================================
let screeningProtocolId = null;
let screeningArticlesCache = [];

async function setupProtocolManager() {
  const select = document.getElementById("review-protocol-select");
  const badgeStatus = document.getElementById("review-protocol-badge-status");
  const btnNewModal = document.getElementById("btn-new-protocol-modal");
  const createForm = document.getElementById("protocol-create-form");
  const btnCloseNew = document.getElementById("btn-close-new-protocol");
  const btnSaveNew = document.getElementById("btn-save-new-protocol");
  const titleInput = document.getElementById("new-protocol-title-input");
  const frameworkSelect = document.getElementById("new-protocol-framework-select");

  if (!select) return;

  // Cargar lista de protocolos
  let protocols = [];
  try {
    const data = await api("/review/protocols", { limit: 50 });
    protocols = data.protocols || [];
  } catch (err) {
    console.error("Error al obtener protocolos:", err);
  }

  // Si no hay protocolos, crear uno inicial por defecto
  if (protocols.length === 0) {
    try {
      const res = await apiPost("/review/protocol", {
        title: "Revisión Sistemática — " + new Date().toISOString().slice(0, 10),
        framework: "PCC",
        status: "screening"
      });
      if (res && res.protocol) {
        protocols = [res.protocol];
        screeningProtocolId = res.protocol_id;
        localStorage.setItem("thinkuy_active_protocol_id", screeningProtocolId);
      }
    } catch (e) {
      console.error("Error al crear protocolo inicial:", e);
    }
  }

  // Ordenar protocolos poniendo los más recientes primero
  protocols.sort((a, b) => (b.id || 0) - (a.id || 0));

  // Recuperar ID persistido de localStorage
  const savedPid = parseInt(localStorage.getItem("thinkuy_active_protocol_id"), 10);
  if (savedPid && protocols.some(p => p.id === savedPid)) {
    screeningProtocolId = savedPid;
  } else if (protocols.length > 0) {
    screeningProtocolId = protocols[0].id;
    localStorage.setItem("thinkuy_active_protocol_id", screeningProtocolId);
  }

  // Renderizar opciones del selector de proyectos
  select.innerHTML = protocols.map(p =>
    `<option value="${p.id}" ${p.id === screeningProtocolId ? "selected" : ""}>${esc(p.title || "Protocolo #" + p.id)} [${esc(p.framework || "PCC")}]</option>`
  ).join("");

  const updateStatusBadge = (pid) => {
    const activeP = protocols.find(p => p.id === pid);
    if (badgeStatus && activeP) {
      badgeStatus.textContent = activeP.status || "screening";
    }
  };
  updateStatusBadge(screeningProtocolId);

  // Cambio de protocolo por el usuario
  select.onchange = async () => {
    const newPid = parseInt(select.value, 10);
    if (newPid) {
      screeningProtocolId = newPid;
      localStorage.setItem("thinkuy_active_protocol_id", screeningProtocolId);
      updateStatusBadge(newPid);
      await refreshPrismaFlow();
      const filterSelect = document.getElementById("screening-filter-select");
      if (filterSelect) filterSelect.dispatchEvent(new Event("change"));
    }
  };

  // Toggle form para crear nuevo protocolo
  if (btnNewModal && createForm) {
    btnNewModal.onclick = () => {
      createForm.hidden = !createForm.hidden;
      if (!createForm.hidden && titleInput) {
        titleInput.focus();
      }
    };
  }

  if (btnCloseNew && createForm) {
    btnCloseNew.onclick = () => {
      createForm.hidden = true;
    };
  }

  // Guardar nuevo protocolo
  if (btnSaveNew && titleInput && frameworkSelect) {
    btnSaveNew.onclick = async () => {
      const title = titleInput.value.trim();
      if (!title) {
        showNotification({ title: "Falta el título", message: "Introduce un título para el protocolo.", type: "info" });
        titleInput.focus();
        return;
      }
      const framework = frameworkSelect.value || "PCC";
      btnSaveNew.disabled = true;
      try {
        const res = await apiPost("/review/protocol", {
          title,
          framework,
          status: "screening"
        });
        if (res && res.protocol_id) {
          screeningProtocolId = res.protocol_id;
          localStorage.setItem("thinkuy_active_protocol_id", screeningProtocolId);
          titleInput.value = "";
          if (createForm) createForm.hidden = true;
          await setupProtocolManager();
          await refreshPrismaFlow();
        }
      } catch (err) {
        console.error("Error creando protocolo:", err);
        showNotification({ title: "No se pudo crear el protocolo", message: String(err.message || err), type: "error" });
      } finally {
        btnSaveNew.disabled = false;
      }
    };
  }
}

async function ensureProtocol() {
  if (screeningProtocolId) return screeningProtocolId;
  const savedPid = parseInt(localStorage.getItem("thinkuy_active_protocol_id"), 10);
  if (savedPid) {
    screeningProtocolId = savedPid;
    return screeningProtocolId;
  }
  try {
    const data = await api("/review/protocols", { limit: 1 });
    if (data.protocols && data.protocols.length > 0) {
      screeningProtocolId = data.protocols[0].id;
      localStorage.setItem("thinkuy_active_protocol_id", screeningProtocolId);
      return screeningProtocolId;
    }
  } catch (_) {}
  // Auto-create a default protocol
  try {
    const res = await apiPost("/review/protocol", {
      title: "Scoping Review — Sesión " + new Date().toISOString().slice(0, 10),
      framework: "PCC",
      status: "screening",
    });
    screeningProtocolId = res.protocol_id;
    localStorage.setItem("thinkuy_active_protocol_id", screeningProtocolId);
    return screeningProtocolId;
  } catch (err) {
    console.error("Error creando protocolo:", err);
    return null;
  }
}

/* Declara a QUÉ PROTOCOLO pertenece lo que se está viendo.
   Motivo (18-09-2026): un investigador buscó «pembrolizumab» y al abrir el Data Charting vio
   fichas de campañas presidenciales latinoamericanas. No había corrupción: esas fichas eran
   del protocolo activo (una revisión electoral de días antes). El fallo era NO DECIRLO.
   La búsqueda en vivo no alimenta ningún protocolo; el cribado y el charting sí son de uno. */
async function renderProtocolContext(elementoId, proposito) {
  const contenedor = document.getElementById(elementoId);
  if (!contenedor) return;
  let pid = null;
  try {
    pid = await ensureProtocol();
  } catch (_) {}
  if (!pid) {
    contenedor.innerHTML = `<span class="material-symbols-outlined" style="font-size:18px;">info</span>
      <div>No hay ningún protocolo de revisión activo. Crea uno para cribar y chartear.</div>`;
    contenedor.hidden = false;
    return;
  }
  let protocolo = {};
  try {
    protocolo = await api(`/review/protocol/${pid}`);
  } catch (_) {}
  const titulo = protocolo.title || `Protocolo #${pid}`;
  const pregunta = protocolo.research_question || "";
  contenedor.innerHTML = `
    <span class="material-symbols-outlined" style="font-size:18px; color:var(--brand-teal);">bookmark</span>
    <div>
      <strong>${proposito} del protocolo #${pid}: «${esc(titulo)}»</strong>
      ${pregunta ? `<div class="protocol-context-question">Pregunta: ${esc(pregunta)}</div>` : ""}
      <div class="protocol-context-note">
        Esto pertenece a <em>esa revisión</em>, no a tu última búsqueda. La <strong>búsqueda en vivo
        no alimenta ningún protocolo</strong>: si quieres cribar y chartear lo que acabas de buscar,
        transfiérelo primero a cribado con el botón de transferencia.
      </div>
    </div>`;
  contenedor.hidden = false;
  contenedor.style.display = "flex";
}

// ================================================================
// PROPUESTA ASISTIDA DE PICC/PCC (el motor propone, el humano verifica)
// ================================================================

/* Rellena los campos PCC de una fila a partir del resumen.
   Reglas: nunca sobrescribe lo que el investigador ya escribió, marca lo propuesto, y declara
   cuando no hay resumen o cuando el motor no encontró fragmentos literales. */
window.proponerPcc = async function(doi, safeId) {
  const pid = await ensureProtocol();
  if (!pid) return;

  const contenedor = document.getElementById(`abstract-text-${safeId}`);
  const fila = document.querySelector(`tr[data-doi="${CSS.escape(doi)}"]`);
  const tituloEl = fila ? fila.querySelector("td a span") : null;
  const titulo = tituloEl ? tituloEl.textContent.trim() : "";
  const boton = fila ? fila.querySelector(".charting-propose-btn") : null;

  let resumen = contenedor ? (contenedor.textContent || "").trim() : "";

  // Si la ficha no trae resumen, se intenta traerlo de la fuente antes de rendirse.
  if (resumen.length < 60 && contenedor && contenedor.dataset.url) {
    if (boton) boton.disabled = true;
    await window.fetchDeterministicAbstract(`abstract-text-${safeId}`);
    resumen = (contenedor.textContent || "").trim();
  }

  if (boton) {
    boton.disabled = true;
    boton.dataset.original = boton.innerHTML;
    boton.innerHTML = `<span class="material-symbols-outlined text-[12px]">hourglass_top</span><span>Proponiendo…</span>`;
  }

  try {
    const r = await apiPost(`/review/protocol/${pid}/chart-propose`,
      { doi, title: titulo, abstract: resumen }, { timeoutMs: 180000 });

    if (r.status === "sin_propuesta") {
      showNotification({ title: `Sin propuesta para «${titulo || doi}»`, message: r.declarado || "el motor no encontró datos literales.", type: "info" });
      return;
    }

    const mapa = { population: "chart-pop-", concept: "chart-con-", context: "chart-ctx-",
                   methodology: "chart-met-", key_findings: "chart-find-", limitations: "chart-lim-" };
    let rellenados = 0;
    Object.entries(r.campos || {}).forEach(([campo, valor]) => {
      const input = document.getElementById(mapa[campo] + safeId);
      if (!input) return;
      if ((input.value || "").trim()) return;   // nunca se pisa lo que el humano escribió
      input.value = valor;
      input.dataset.propuesta = "1";
      input.style.borderLeft = "3px solid var(--brand-teal, #009688)";
      input.title = "Propuesta del motor a partir del resumen. Verifique antes de guardar.";
      rellenados += 1;
    });

    if (!rellenados) {
      showNotification({ title: "Sin cambios", message: "Todos los campos ya estaban rellenos: no se tocó nada.", type: "info" });
      return;
    }
    // Se avisa qué se descartó, para que el investigador sepa qué no quedó cubierto.
    if ((r.descartados || []).length) {
      console.warn("Campos descartados por el guardián de fidelidad:", r.descartados);
    }
  } catch (e) {
    showNotification({ title: "No se pudo proponer el PICC", message: String(e && e.message ? e.message : e), type: "error" });
  } finally {
    if (boton) {
      boton.disabled = false;
      if (boton.dataset.original) boton.innerHTML = boton.dataset.original;
    }
  }
};

/* Propone el PICC de TODOS los incluidos, uno por uno, con progreso. */
window.proponerPccTodos = async function() {
  const filas = Array.from(document.querySelectorAll("#charting-table-container tr[data-doi]"));
  if (!filas.length) {
    showNotification({ title: "Sin artículos", message: "Primero carga los artículos incluidos con «Cargar artículos incluidos para charteo».", type: "info" });
    return;
  }
  if (!confirm(`Se propondrá el PICC de ${filas.length} artículos, uno por uno.\n`
             + `Solo se rellenan campos vacíos y usted verifica antes de guardar.\n\n¿Continuar?`)) return;

  const barra = document.getElementById("charting-propose-progress");
  if (barra) { barra.hidden = false; barra.textContent = `0 / ${filas.length}`; }

  let hechos = 0, conPropuesta = 0;
  for (const fila of filas) {
    const doi = fila.dataset.doi;
    const safeId = doi.replace(/[^a-zA-Z0-9]/g, "_");
    try {
      const antes = document.getElementById(`chart-pop-${safeId}`);
      const vacios = ["chart-pop-", "chart-con-", "chart-ctx-", "chart-met-", "chart-find-", "chart-lim-"]
        .some(p => { const el = document.getElementById(p + safeId); return el && !(el.value || "").trim(); });
      if (vacios) await window.proponerPcc(doi, safeId);
      const despues = document.getElementById(`chart-con-${safeId}`);
      if (despues && (despues.value || "").trim()) conPropuesta += 1;
    } catch (_) {}
    hechos += 1;
    if (barra) barra.textContent = `${hechos} / ${filas.length} · con propuesta: ${conPropuesta}`;
  }
  if (barra) barra.textContent = `Terminado: ${hechos} artículos · ${conPropuesta} con propuesta. Verifique y guarde cada fila.`;
};

async function refreshPrismaFlow() {  const pid = await ensureProtocol();
  if (!pid) return;
  try {
    const flow = await api(`/review/protocol/${pid}/flow-diagram`);
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    set("prisma-identified", flow.total_identified || 0);
    set("prisma-duplicates", flow.duplicates_detected || 0);
    set("prisma-screened", (flow.included || 0) + (flow.excluded || 0) + (flow.maybe || 0));
    set("prisma-excluded", flow.excluded || 0);
    set("prisma-included", flow.included || 0);
    set("prisma-pending", flow.pending || 0);
    set("prisma-maybe", flow.maybe || 0);
    // Exclusion reasons
    const reasonsEl = document.getElementById("prisma-exclusion-reasons");
    if (reasonsEl && flow.exclusion_reasons) {
      const entries = Object.entries(flow.exclusion_reasons);
      if (entries.length > 0) {
        reasonsEl.innerHTML = entries.map(([r, n]) => `<div>• ${esc(r)}: ${n}</div>`).join("");
      } else {
        reasonsEl.innerHTML = "";
      }
    }
  } catch (err) {
    console.error("Error cargando diagrama PRISMA:", err);
  }
}

async function screenArticle(doi, decision, reason) {
  const pid = await ensureProtocol();
  if (!pid) return;
  try {
    await apiPost(`/review/protocol/${pid}/screen`, { doi, decision, reason });

    // UI OPTIMISTA: se pinta la tarjeta ANTES de refrescar el diagrama de flujo.
    // Antes se hacía `await refreshPrismaFlow()` primero, y como ese endpoint tardaba
    // (hasta colgarse), el botón parecía muerto aunque la decisión ya estaba guardada.
    const card = document.querySelector(`.screening-card[data-doi="${CSS.escape(doi)}"]`);
    if (card) {
      card.className = `screening-card decision-${decision}`;
      // Update active buttons
      card.querySelectorAll(".screening-btn").forEach(b => b.classList.remove("active"));
      const activeBtn = card.querySelector(`.screening-btn.btn-${decision === "included" ? "include" : decision === "excluded" ? "exclude" : "maybe"}`);
      if (activeBtn) activeBtn.classList.add("active");
      // Show reason
      const reasonEl = card.querySelector(".screening-card-reason");
      if (reasonEl && reason) {
        reasonEl.textContent = `Razón: ${reason}`;
        reasonEl.style.display = "block";
      }

      // Enriquecimiento Progresivo Asistido (Vía Híbrida):
      // Si el artículo no tenía DOI real o revista completa, consultar en segundo plano OpenAlex
      if (decision === "included") {
        const aid = card.dataset.articleId;
        if (aid && (doi.includes("csv_") || doi.includes("dialnet:") || doi.includes("openaire:"))) {
          apiPost(`/review/protocol/${pid}/enrich-article/${aid}`).then(res => {
            if (res && res.matched) {
              const metaJournal = card.querySelector(".meta-journal");
              if (metaJournal && res.journal_title) metaJournal.textContent = res.journal_title;
              const doiBadge = card.querySelector(".screening-doi-badge");
              if (doiBadge && res.real_doi) {
                doiBadge.textContent = `DOI: ${res.real_doi}`;
                doiBadge.href = `https://doi.org/${res.real_doi}`;
              }
            }
          }).catch(() => {});
        }
      }
    }

    // El diagrama de flujo se refresca después y sin bloquear: si falla o tarda, la decisión
    // ya está visible y el investigador puede seguir cribando.
    refreshPrismaFlow().catch(err => console.warn("No se pudo refrescar el diagrama PRISMA:", err));
  } catch (err) {
    console.error("Error en screening:", err);
  }
}

function extractMethodologyIndicators(article) {
  const text = ((article.abstract || "") + " " + (article.title || "") + " " + (Array.isArray(article.keywords) ? article.keywords.join(" ") : (article.keywords || ""))).toLowerCase();
  const methods = [];
  if (/cualitativ|qualitative|entrevista|interview|grupo focal|focus group|etnogra|etno-/.test(text)) methods.push("Cualitativo");
  if (/cuantitativ|quantitative|encuesta|survey|cuestionario|muestreo|regresion|estadistic/.test(text)) methods.push("Cuantitativo");
  if (/mixto|mixed methods|triangulac/.test(text)) methods.push("Métodos Mixtos");
  if (/analisis de contenido|content analysis|analisis del discurso|discourse analysis/.test(text)) methods.push("Análisis de Contenido/Discurso");
  if (/estudio de caso|case study/.test(text)) methods.push("Estudio de Caso");
  if (/revision sistematica|systematic review|scoping|estado del arte|meta-analisis|meta-analysis/.test(text)) methods.push("Revisión/Síntesis");
  if (/experimento|experimental|ensayo/.test(text)) methods.push("Experimental");
  if (/corpus|mineria de texto|text mining|computacional/.test(text)) methods.push("Computacional / Corpus");
  return methods;
}

/* Resumen por la CADENA DETERMINISTA (escalón 2 de la ingesta):
   metaetiquetas del editor -> Dublin Core -> PDF declarado -> vacío declarado.
   Nunca lo rellena un modelo: si la fuente no lo publica, lo dice. Registra la procedencia. */
window.fetchDeterministicAbstract = async function(elementoId) {
  const contenedor = document.getElementById(elementoId);
  if (!contenedor) return;
  const url = (contenedor.dataset.url || "").trim();
  if (!url) {
    contenedor.innerHTML = `<em>Este registro no tiene URL de ficha para consultar.</em>`;
    return;
  }
  const placeholder = `<em>Resumen no disponible en la ficha inicial.</em>`;
  contenedor.innerHTML = `<em>Consultando la ficha del editor y, si hace falta, su PDF declarado…</em>`;
  try {
    const d = await apiPost("/metadata/abstract", { url, allow_pdf: true }, { timeoutMs: 150000 });
    if (d && d.resumen) {
      const etiquetas = {
        citation_abstract: "metaetiqueta del editor",
        dc_description: "Dublin Core de la revista",
        pdf_abstract: "PDF declarado por el editor",
        meta_description: "descripción de la ficha",
      };
      const origen = etiquetas[d.fuente] || d.fuente;
      contenedor.innerHTML = `${esc(d.resumen)}
        <div style="margin-top:6px; font-size:0.72rem; color:var(--text-secondary);">
          Fuente: ${esc(origen)} · ${d.caracteres || d.resumen.length} caracteres
        </div>`;
      // Se propaga a la caché del cribado para que la decisión use el texto recuperado.
      const card = contenedor.closest(".screening-card");
      const doiCard = card ? (card.dataset.doi || "").toLowerCase() : "";
      const cached = screeningArticlesCache.find(x => (x.doi || "").toLowerCase() === doiCard);
      if (cached) cached.abstract = d.resumen;
    } else {
      contenedor.innerHTML = `<em>La fuente no publica resumen.</em>
        <div style="margin-top:6px; font-size:0.72rem; color:var(--text-secondary);">
          ${esc((d && d.detalle) || "Sin resumen declarado por el editor.")}
        </div>${placeholder}`;
    }
  } catch (err) {
    contenedor.innerHTML = `<em>No se pudo consultar la fuente: ${esc(err && err.message ? err.message : err)}</em>${placeholder}`;
  }
};

window.fetchArticleDetails = async function(identifier, safeId) {  const abstractEl = document.getElementById(`abstract-text-${safeId}`);
  if (abstractEl) {
    abstractEl.innerHTML = `<em>Cargando resumen oficial desde la fuente...</em>`;
  }
  try {
    const data = await api(`/articles/${encodeURIComponent(identifier)}`);
    if (data && data.abstract) {
      if (abstractEl) abstractEl.textContent = data.abstract;
      const cleanIdent = (identifier || "").toLowerCase();
      const cached = screeningArticlesCache.find(x =>
        (x.doi || "").toLowerCase() === cleanIdent ||
        (x.id && `article:${x.id}` === cleanIdent) ||
        (x.source_id && x.source_id.toLowerCase() === cleanIdent)
      );
      if (cached) {
        cached.abstract = data.abstract;
        if (data.authors) cached.authors = data.authors;
      }
    } else {
      if (abstractEl) abstractEl.innerHTML = `<em>No se encontró resumen en el repositorio para este registro. Puedes consultarlo directamente en el enlace oficial.</em>`;
    }
  } catch (err) {
    if (abstractEl) abstractEl.innerHTML = `<em>Error al cargar resumen: ${esc(err.message || err)}</em>`;
  }
};

function renderScreeningCards(articles, existingDecisions) {
  const container = document.getElementById("screening-articles-container");
  if (!container) return;
  if (!articles || articles.length === 0) {
    container.innerHTML = `<div class="snowball-empty-hint">No hay artículos para cribar.</div>`;
    return;
  }
  const decisionMap = {};
  (existingDecisions || []).forEach(s => { decisionMap[s.doi] = s; });

  container.innerHTML = "";
  articles.forEach(a => {
    const rawDoi = a.doi || "";
    const cleanDoiVal = extractCleanDoi(rawDoi);
    const isRealDoi = cleanDoiVal && cleanDoiVal.startsWith("10.");
    const doiKey = (rawDoi || (a.id ? `article:${a.id}` : "")).toLowerCase();
    const existing = decisionMap[doiKey] || (cleanDoiVal ? decisionMap[cleanDoiVal.toLowerCase()] : null) || (rawDoi ? decisionMap[rawDoi.toLowerCase()] : null);
    const dec = existing ? existing.decision : "pending";
    const reason = existing ? existing.reason : "";

    const officialUrl = isRealDoi
      ? `https://doi.org/${cleanDoiVal}`
      : (a.url || "#");

    const safeId = (cleanDoiVal || (a.id ? `art_${a.id}` : Math.random().toString(36).substring(7))).replace(/[^a-zA-Z0-9]/g, "_");

    // Autores formateados
    let authorsStr = "Autor(es) no declarados";
    if (a.authors) {
      if (Array.isArray(a.authors)) {
        authorsStr = a.authors.map(aut => {
          if (typeof aut === "object" && aut) return `${aut.given || ""} ${aut.family || ""}`.trim() || aut.name || "";
          return String(aut);
        }).filter(Boolean).join(", ") || "Autor(es) no declarados";
      } else if (typeof a.authors === "string") {
        authorsStr = a.authors;
      }
    }

    // Metodología deducida o rol epistemológico
    const role = a.role || "Empirical";
    const roleDescriptions = {
      "Seminal": "Obra Fundacional / Seminal — Alta densidad de citación histórica y base teórica del campo.",
      "Synthesis/Review": "Revisión / Síntesis Integrativa — Scoping Review, revisión sistemática o estado del conocimiento.",
      "Theoretical/Framework": "Teórico / Conceptual — Modelos epistemológicos, marcos conceptuales y debate analítico.",
      "Methodological": "Metodológico / Instrumental — Validación de métodos, métricas, algoritmos o protocolos.",
      "Empirical": "Estudio Empírico — Investigación basada en datos primarios, observación empírica o trabajo de campo."
    };
    const roleDesc = roleDescriptions[role] || "Clasificación metodológica en el debate científico.";
    const methodIndicators = extractMethodologyIndicators(a);
    const abstractText = a.abstract ? a.abstract.trim() : "";
    const rawSrc = String(a.source || a.source_engine || "openalex").toLowerCase();
    const srcKey = rawSrc.includes("openaire") ? "openaire" : rawSrc.includes("dialnet") ? "dialnet" : "openalex";
    const srcLabel = srcKey === "openaire" ? "🇪🇺 OpenAIRE" : srcKey === "dialnet" ? "📚 Dialnet" : "🌐 OpenAlex";
    const srcBadge = `<span class="source-badge badge-${srcKey}">${srcLabel}</span>`;

    const card = document.createElement("div");
    card.className = `screening-card decision-${dec}`;
    card.dataset.doi = doiKey;
    card.dataset.source = srcKey;
    card.dataset.articleId = a.id || a.article_id || "";
    card.innerHTML = `
      <div class="screening-card-info">
        <!-- Encabezado con título clicable al texto completo -->
        <div class="screening-card-title-row">
          <a href="${esc(officialUrl)}" ${officialUrl !== "#" ? 'target="_blank" rel="noopener noreferrer"' : 'onclick="return false;" style="cursor:default;"'} class="screening-article-link" title="${officialUrl !== "#" ? 'Abrir publicación original' : 'Artículo importado desde archivo local'}">
            <span class="material-symbols-outlined text-[16px] text-brand-teal">${officialUrl !== "#" ? 'open_in_new' : 'description'}</span>
            <span>${esc(a.title || "Sin título")}</span>
          </a>
        </div>

        <!-- Metadatos de publicación y autores -->
        <div class="screening-card-meta">
          ${srcBadge}
          <span>•</span>
          <span class="meta-journal">${esc(a.journal_title || a.journal || "Revista")}</span>
          <span>•</span>
          <span>${a.year || "S/F"}</span>
          <span>•</span>
          <span>Citas: <strong>${a.cited_by || a.cited_by_global || 0}</strong></span>
          ${a.role ? `<span>•</span> <span class="role-badge ${esc(a.role)}">${esc(a.role)}</span>` : ""}
          ${isRealDoi ? `<a href="${esc(officialUrl)}" target="_blank" rel="noopener" class="screening-doi-badge" title="Enlace oficial DOI">DOI: ${esc(cleanDoiVal)}</a>` : (a.id || a.article_id ? `<span class="screening-doi-badge" style="background:rgba(255,255,255,0.06); color:var(--text-secondary); cursor:default;">ID: ${esc(a.id || a.article_id)}</span>` : "")}
        </div>

        <div class="screening-card-authors">
          <span class="material-symbols-outlined text-[13px]">group</span>
          <span>${esc(authorsStr)}</span>
        </div>

        <div class="screening-card-reason" style="${reason ? "" : "display:none;"}">${reason ? `Razón de exclusión: ${esc(reason)}` : ""}</div>

        <!-- Ficha Técnica, Resumen y Metodología (Abierto por defecto para screening) -->
        <details class="screening-details" id="details-${safeId}" open>
          <summary class="screening-details-summary">
            <span class="material-symbols-outlined text-[15px]">description</span>
            <span>Ficha Técnica, Resumen y Metodología</span>
            <span class="details-chevron material-symbols-outlined text-[15px]">expand_more</span>
          </summary>
          <div class="screening-details-body" id="details-body-${safeId}">
            <!-- Sección Metodología -->
            <div class="details-section">
              <div class="details-section-title">
                <span class="material-symbols-outlined text-[14px] text-brand-teal">science</span>
                <strong>Enfoque Metodológico Deducido:</strong>
              </div>
              <p class="details-text">${esc(roleDesc)}</p>
              ${methodIndicators.length > 0 ? `
                <div class="method-indicators-chips">
                  ${methodIndicators.map(m => `<span class="method-indicator-tag">🔬 ${esc(m)}</span>`).join("")}
                </div>
              ` : ''}
            </div>

            <!-- Sección Resumen / Abstract -->
            <div class="details-section">
              <div class="details-section-title">
                <span class="material-symbols-outlined text-[14px] text-brand-teal">notes</span>
                <strong>Resumen (Abstract):</strong>
              </div>
              <p class="details-abstract-text" id="abstract-text-${safeId}" data-url="${esc(officialUrl === "#" ? "" : officialUrl)}">
                ${abstractText ? esc(abstractText) : '<em>Resumen no disponible en la ficha inicial.</em>'}
              </p>
              ${!abstractText && (doiKey || cleanDoiVal || a.id) ? `
                <div style="display:flex; gap:6px; flex-wrap:wrap; margin-top:6px;">
                  <button type="button" class="btn btn-ghost sm" style="font-size:0.72rem; padding:2px 8px;" onclick="fetchArticleDetails('${esc(cleanDoiVal || doiKey || (a.id ? `article:${a.id}` : ''))}', '${safeId}')">
                    <span class="material-symbols-outlined text-[13px]">download</span>
                    <span>Cargar del catálogo</span>
                  </button>
                  ${officialUrl !== "#" ? `
                    <button type="button" class="btn btn-ghost sm" style="font-size:0.72rem; padding:2px 8px;" onclick="fetchDeterministicAbstract('abstract-text-${safeId}')" title="Lee el resumen de la ficha del editor (metaetiquetas o PDF declarado). Si no existe, lo declara en vez de inventarlo.">
                      <span class="material-symbols-outlined text-[13px]">travel_explore</span>
                      <span>Buscar en la fuente</span>
                    </button>
                  ` : ''}
                </div>
              ` : ''}
            </div>

            <!-- Ficha Técnica Detallada -->
            <div class="details-section details-tech-grid">
              <div><strong>DOI:</strong> <a href="${esc(officialUrl)}" target="_blank" rel="noopener">${esc(cleanDoiVal || 'No registrado')}</a></div>
              <div><strong>Revista:</strong> ${esc(a.journal_title || a.journal || 'No especificada')}</div>
              <div><strong>Año:</strong> ${esc(a.year || 'S/F')}</div>
              <div><strong>Impacto / Citas globales:</strong> ${esc(a.cited_by_global || a.cited_by || 0)}</div>
              ${a.keywords ? `<div><strong>Palabras clave:</strong> ${esc(Array.isArray(a.keywords) ? a.keywords.join(", ") : a.keywords)}</div>` : ''}
              <div><strong>Enlace Oficial:</strong> <a href="${esc(officialUrl)}" target="_blank" rel="noopener" style="font-weight:600; color:var(--brand-teal);">Abrir artículo completo ↗</a></div>
            </div>
          </div>
        </details>
      </div>

      <!-- Acciones de Screening PRISMA -->
      <div class="screening-actions">
        <button type="button" class="screening-btn btn-include ${dec === "included" ? "active" : ""}" title="Incluir en la síntesis PRISMA" onclick="onScreenDecision('${esc(doiKey)}', 'included')">
          <span class="material-symbols-outlined text-[14px]">check_circle</span> Incluir
        </button>
        <button type="button" class="screening-btn btn-exclude ${dec === "excluded" ? "active" : ""}" title="Excluir con motivo documentado" onclick="onScreenDecision('${esc(doiKey)}', 'excluded')">
          <span class="material-symbols-outlined text-[14px]">cancel</span> Excluir
        </button>
        <button type="button" class="screening-btn btn-maybe ${dec === "maybe" ? "active" : ""}" title="Marcar como dudoso / a revisar" onclick="onScreenDecision('${esc(doiKey)}', 'maybe')">
          <span class="material-symbols-outlined text-[14px]">help</span> Dudoso
        </button>
      </div>
    `;
    container.appendChild(card);
  });

  // Conteo y filtrado por base de datos en Screening
  const screenSrcCounts = { all: articles.length, openalex: 0, openaire: 0, dialnet: 0 };
  articles.forEach(a => {
    const s = String(a.source || a.source_engine || "").toLowerCase();
    if (s.includes("openaire")) screenSrcCounts.openaire++;
    else if (s.includes("dialnet")) screenSrcCounts.dialnet++;
    else screenSrcCounts.openalex++;
  });
  const setScreenCount = (id, n) => { const el = document.getElementById(id); if (el) el.textContent = n; };
  setScreenCount("count-screen-src-all", screenSrcCounts.all);
  setScreenCount("count-screen-src-openalex", screenSrcCounts.openalex);
  setScreenCount("count-screen-src-openaire", screenSrcCounts.openaire);
  setScreenCount("count-screen-src-dialnet", screenSrcCounts.dialnet);

  let activeScreenSource = "all";
  const screenSrcChips = document.querySelectorAll(".screen-src-chip");
  screenSrcChips.forEach(chip => {
    chip.onclick = () => {
      screenSrcChips.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      activeScreenSource = chip.dataset.source;
      const allCards = container.querySelectorAll(".screening-card");
      allCards.forEach(card => {
        if (activeScreenSource === "all" || card.dataset.source === activeScreenSource) {
          card.style.display = "";
        } else {
          card.style.display = "none";
        }
      });
    };
  });
}

window.onScreenDecision = async function(doi, decision) {
  let reason = null;
  if (decision === "excluded") {
    reason = prompt("Razón de exclusión (ej: Fuera de alcance, Idioma, Duplicado, No empírico, etc.):");
    if (reason === null) return; // Cancelled
  }
  await screenArticle(doi, decision, reason || null);
};

function setupScreeningTab(librarianData) {
  const loadBtn = document.getElementById("btn-load-screening-articles");
  const filterSelect = document.getElementById("screening-filter-select");

  // El mismo aviso que en el charting: sin él, una cola de 7.000cribados de otra revisión
  // parece «el resultado de la búsqueda que acabo de hacer».
  renderProtocolContext("screening-protocol-context", "Cola de cribado");

  const loadScreeningsFromBackend = async () => {
    const pid = await ensureProtocol();
    if (!pid) return;
    try {
      const data = await api(`/review/protocol/${pid}/screenings`, { limit: 100 });
      const screenings = data.screenings || [];
      if (screenings.length > 0) {
        screeningArticlesCache = screenings;
        renderScreeningCards(screenings, screenings);
        await refreshPrismaFlow();
      }
    } catch (err) {
      console.error("Error cargando screenings del protocolo:", err);
    }
  };

  // Auto-cargar de inmediato las obras del protocolo
  loadScreeningsFromBackend();

  if (loadBtn) {
    loadBtn.onclick = async () => {
      const pid = await ensureProtocol();
      if (!pid) return;

      // Get articles from librarian or roles
      let articles = [];
      if (librarianData && librarianData.articles && librarianData.articles.length > 0) {
        articles = librarianData.articles.filter(a => a.doi);
      } else if (currentEpistemicRoles && currentEpistemicRoles.length > 0) {
        articles = currentEpistemicRoles.filter(a => a.doi);
      }

      if (articles.length === 0) {
        await loadScreeningsFromBackend();
        return;
      }

      // Batch register as pending con el artículo completo para persistir resumen y metadatos
      const items = articles.map(a => ({
        doi: a.doi || (a.id ? `article:${a.id}` : ""),
        decision: "pending",
        article_id: a.id,
        article: a,
      }));
      try {
        await apiPost(`/review/protocol/${pid}/screen-batch`, { items });
      } catch (_) {}

      // Fetch existing decisions
      let existing = [];
      try {
        const data = await api(`/review/protocol/${pid}/screenings`, { limit: 500 });
        existing = data.screenings || [];
      } catch (_) {}

      screeningArticlesCache = articles;
      renderScreeningCards(articles, existing);
      await refreshPrismaFlow();
    };
  }

  if (filterSelect) {
    filterSelect.onchange = async () => {
      const val = filterSelect.value;
      const pid = await ensureProtocol();
      if (!pid) return;
      try {
        const params = val === "all" ? { limit: 500 } : { decision: val, limit: 500 };
        const data = await api(`/review/protocol/${pid}/screenings`, params);
        const screenings = data.screenings || [];
        renderScreeningCards(screenings, screenings);
      } catch (err) {
        console.error("Error filtrando screenings:", err);
      }
    };
  }

  // Auto-load flow diagram on tab open
  refreshPrismaFlow();
}

// ================================================================
// CHARTING & EXPORT
// ================================================================
function setupChartingTab() {
  const loadBtn = document.getElementById("btn-load-charting");
  const container = document.getElementById("charting-table-container");

  // Se declara el protocolo ANTES de cargar nada: el investigador debe saber de qué revisión
  // son las fichas que va a ver.
  renderProtocolContext("charting-protocol-context", "Fichas de extracción");

  if (loadBtn) {
    loadBtn.onclick = async () => {
      const pid = await ensureProtocol();
      if (!pid) return;

      // Fetch included articles
      let included = [];
      try {
        const data = await api(`/review/protocol/${pid}/screenings`, { decision: "included", limit: 200 });
        included = data.screenings || [];
      } catch (_) {}

      if (included.length === 0) {
        container.innerHTML = `<div class="snowball-empty-hint">No hay artículos incluidos aún. Marca artículos como «Incluido» en la pestaña Screening PRISMA.</div>`;
        return;
      }

      // Fetch existing charting data
      let chartingData = [];
      try {
        const data = await api(`/review/protocol/${pid}/charting`, { limit: 200 });
        chartingData = data.charting || [];
      } catch (_) {}

      const chartMap = {};
      chartingData.forEach(c => { chartMap[c.doi] = c; });

      // Build editable table
      let tableHtml = `
        <table class="charting-table">
          <thead>
            <tr>
              <th style="min-width:200px;">Título / DOI</th>
              <th>Población</th>
              <th>Concepto</th>
              <th>Contexto</th>
              <th>Metodología</th>
              <th style="min-width:180px;">Hallazgos clave</th>
              <th>Limitaciones</th>
              <th style="width:55px;">Calidad</th>
              <th style="width:60px;">Guardar</th>
            </tr>
          </thead>
          <tbody>
      `;

      included.forEach(s => {
        const doi = s.doi || "";
        const c = chartMap[doi] || {};
        const cached = screeningArticlesCache.find(a => (a.doi || "").toLowerCase() === doi);
        // El título viene de la API (que ya lo unió con el artículo). Antes se usaba solo la
        // caché de la interfaz y, si fallaba, la tabla mostraba el DOI en su lugar.
        const tituloApi = (s.title || "").trim();
        const title = (tituloApi && tituloApi !== doi) ? tituloApi
          : (cached && cached.title) ? cached.title : doi;
        const resumen = ((s.abstract || (cached && cached.abstract) || "") + "").trim();
        const urlFuente = (s.url || (cached && cached.url) || "").trim();
        const safeId = doi.replace(/[^a-zA-Z0-9]/g, "_");

        tableHtml += `
          <tr data-doi="${esc(doi)}">
            <td>
              <div style="font-weight:600; font-size:0.78rem; margin-bottom:2px;">
                <a href="${doi ? (doi.startsWith('http') ? doi : 'https://doi.org/' + encodeURIComponent(doi)) : '#'}" target="_blank" rel="noopener noreferrer" style="color:var(--on-surface, #1E293B); text-decoration:none; display:inline-flex; align-items:flex-start; gap:4px;" title="Abrir texto completo original (DOI)">
                  <span>${esc(title)}</span>
                  <span class="material-symbols-outlined text-[13px] text-brand-teal" style="flex-shrink:0; margin-top:2px;">open_in_new</span>
                </a>
              </div>
              <div style="font-size:0.65rem; color:var(--on-surface-variant); font-family:var(--font-mono, monospace);">${esc(doi)}</div>
              <!-- El resumen es el insumo del charteo: sin él no se puede llenar el PCC.
                   Si la ficha no lo trae, se ofrece traerlo de la fuente (cadena determinista). -->
              <details class="charting-abstract">
                <summary>${resumen ? "Resumen" : "Sin resumen"}</summary>
                <div class="charting-abstract-text" id="abstract-text-${safeId}" data-url="${esc(urlFuente)}">
                  ${resumen ? esc(resumen) : '<em>La ficha no publica resumen.</em>'}
                </div>
                ${!resumen && urlFuente ? `
                  <button type="button" class="btn btn-ghost sm" style="margin-top:6px; font-size:0.7rem; padding:2px 8px;"
                          onclick="fetchDeterministicAbstract('abstract-text-${safeId}')">
                    <span class="material-symbols-outlined text-[12px]">travel_explore</span>
                    <span>Buscar resumen en la fuente</span>
                  </button>` : ""}
              </details>
              <button type="button" class="btn btn-ghost sm charting-propose-btn"
                      style="margin-top:6px; font-size:0.68rem; padding:2px 7px;"
                      title="El motor propone los campos a partir del resumen; usted verifica y corrige."
                      onclick="proponerPcc('${esc(doi)}', '${safeId}')">
                <span class="material-symbols-outlined text-[12px]">auto_awesome</span>
                <span>Proponer PICC</span>
              </button>
            </td>
            <td><input type="text" id="chart-pop-${safeId}" value="${esc(c.population || "")}" placeholder="Ej: Adolescentes 12-18"></td>
            <td><input type="text" id="chart-con-${safeId}" value="${esc(c.concept || "")}" placeholder="Ej: Alfabetización digital"></td>
            <td><input type="text" id="chart-ctx-${safeId}" value="${esc(c.context || "")}" placeholder="Ej: Escuelas rurales México"></td>
            <td><input type="text" id="chart-met-${safeId}" value="${esc(c.methodology || "")}" placeholder="Ej: Mixto/Cualitativo"></td>
            <td><textarea id="chart-find-${safeId}" placeholder="Hallazgos principales...">${esc(c.key_findings || "")}</textarea></td>
            <td><input type="text" id="chart-lim-${safeId}" value="${esc(c.limitations || "")}" placeholder="Ej: Muestra pequeña"></td>
            <td><input type="number" id="chart-q-${safeId}" value="${c.quality_score || ""}" min="0" max="10" step="0.5" placeholder="0-10" style="width:50px;"></td>
            <td><button type="button" class="charting-save-btn" onclick="saveChartingRow('${esc(doi)}', '${safeId}')">💾</button></td>
          </tr>
        `;
      });

      tableHtml += `</tbody></table>`;
      container.innerHTML = tableHtml;
    };
  }

  // Propuesta asistida del PICC para todos los incluidos (el humano verifica)
  const proposeBtn = document.getElementById("btn-propose-charting");
  if (proposeBtn) proposeBtn.onclick = () => window.proponerPccTodos();

  // Traer de la fuente los resúmenes que faltan, declarando los que no existen.
  const hydrateBtn = document.getElementById("btn-hydrate-abstracts");
  if (hydrateBtn) {
    hydrateBtn.onclick = async () => {
      const pid = await ensureProtocol();
      if (!pid) return;
      const barra = document.getElementById("charting-propose-progress");
      hydrateBtn.disabled = true;
      if (barra) { barra.hidden = false; barra.textContent = "Buscando resúmenes en las fuentes… puede tardar un par de minutos."; }
      try {
        const r = await apiPost(`/review/protocol/${pid}/hydrate-abstracts`, {}, { timeoutMs: 900000 });
        const lineas = [
          `Recuperados: ${r.recuperados} de ${r.sin_resumen_antes} que faltaban.`,
          `Enlazados al catálogo: ${r.enlazados}.`,
          `No existen en acceso abierto: ${r.no_disponibles}.`,
          `Bloqueados por la fuente: ${r.bloqueados_por_la_fuente}.`,
          "",
          r.declaracion || "",
        ];
        if ((r.detalle_no_disponibles || []).length) {
          lineas.push("", "Sin resumen disponible (se leen en el texto completo):");
          (r.detalle_no_disponibles || []).slice(0, 12).forEach(d => lineas.push(`  · ${d.titulo}`));
        }
        if ((r.detalle_bloqueados || []).length) {
          lineas.push("", "Bloqueados por la fuente:");
          (r.detalle_bloqueados || []).slice(0, 12).forEach(d => lineas.push(`  · ${d.titulo}`));
        }
        if (barra) barra.textContent = lineas.join("\n");
        if (r.recuperados > 0) {
          const cargar = document.getElementById("btn-load-charting");
          if (cargar) cargar.click();   // recargar la tabla con los resúmenes nuevos
        }
      } catch (e) {
        if (barra) barra.textContent = "No se pudo completar: " + (e && e.message ? e.message : e);
      } finally {
        hydrateBtn.disabled = false;
      }
    };
  }

  // Export buttons
  const exportCsv = document.getElementById("btn-export-csv");  const exportRis = document.getElementById("btn-export-ris");
  const exportBibtex = document.getElementById("btn-export-bibtex");

  const doExport = async (format) => {
    const pid = await ensureProtocol();
    if (!pid) {
      showNotification({ title: "Sin protocolo", message: "No hay un protocolo activo seleccionado.", type: "info" });
      return;
    }
    const btn = format === "csv" ? exportCsv : (format === "ris" ? exportRis : exportBibtex);
    const origHtml = btn ? btn.innerHTML : "";
    if (btn) {
      btn.disabled = true;
      btn.style.opacity = "0.6";
      btn.innerHTML = `<span class="material-symbols-outlined text-[15px] animate-spin">sync</span> Descargando...`;
    }
    try {
      const base = (window.__API_BASE || "/api").replace(/\/api$/, "");
      const url = `${base}/api/review/protocol/${pid}/export?format=${format}&decision=included`;
      const resp = await fetch(url);
      if (!resp.ok) {
        let errMsg = resp.statusText;
        try {
          const errData = await resp.json();
          errMsg = errData.detail || errMsg;
        } catch (_) {}
        throw new Error(errMsg);
      }
      const blob = await resp.blob();
      const ext = format === "bibtex" ? "bib" : format;
      const filename = `thinkuy_protocol_${pid}_matriz.${ext}`;
      const blobUrl = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.style.display = "none";
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        document.body.removeChild(a);
        window.URL.revokeObjectURL(blobUrl);
      }, 500);
      showNotification({
        title: `Exportación ${format.toUpperCase()} completada`,
        message: `Se descargó el archivo ${filename} correctamente.`,
        type: "success"
      });
    } catch (err) {
      console.error(`Error exportando ${format}:`, err);
      showNotification({
        title: `Error al exportar ${format.toUpperCase()}`,
        message: err.message || String(err),
        type: "error"
      });
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.style.opacity = "1";
        btn.innerHTML = origHtml;
      }
    }
  };

  if (exportCsv) exportCsv.onclick = () => doExport("csv");
  if (exportRis) exportRis.onclick = () => doExport("ris");
  if (exportBibtex) exportBibtex.onclick = () => doExport("bibtex");
}

window.saveChartingRow = async function(doi, safeId) {
  const pid = await ensureProtocol();
  if (!pid) return;
  const payload = {
    doi,
    population: document.getElementById(`chart-pop-${safeId}`)?.value || "",
    concept: document.getElementById(`chart-con-${safeId}`)?.value || "",
    context: document.getElementById(`chart-ctx-${safeId}`)?.value || "",
    methodology: document.getElementById(`chart-met-${safeId}`)?.value || "",
    key_findings: document.getElementById(`chart-find-${safeId}`)?.value || "",
    limitations: document.getElementById(`chart-lim-${safeId}`)?.value || "",
    quality_score: parseFloat(document.getElementById(`chart-q-${safeId}`)?.value) || null,
  };
  try {
    await apiPost(`/review/protocol/${pid}/chart`, payload);
    const btn = document.querySelector(`tr[data-doi="${CSS.escape(doi)}"] .charting-save-btn`);
    if (btn) {
      btn.textContent = "✅";
      setTimeout(() => { btn.textContent = "💾"; }, 1500);
    }
  } catch (err) {
    console.error("Error guardando charteo:", err);
    showNotification({ title: "Error al guardar el charteo", message: "No se pudieron guardar los datos.", type: "error" });
  }
};

let radarComparedJournals = [];

const RADAR_COMPARE_PALETTES = [
  { stroke: "#F59E0B", fill: "#F59E0B", line: "rgba(245, 158, 11, 0.65)", text: "#FDE68A", bg: "rgba(245, 158, 11, 0.95)", label: "Contrastada 1" },
  { stroke: "#EC4899", fill: "#EC4899", line: "rgba(236, 72, 153, 0.65)", text: "#FBCFE8", bg: "rgba(236, 72, 153, 0.95)", label: "Contrastada 2" },
  { stroke: "#8B5CF6", fill: "#8B5CF6", line: "rgba(139, 92, 246, 0.65)", text: "#DDD6FE", bg: "rgba(139, 92, 246, 0.95)", label: "Contrastada 3" }
];

const RADAR_COMPARE_ANGLES = [135, 45, 225];

function getRadarOrbitInfo(r) {
  if (!r || r <= 0) return { name: "Órbita 4: Periferia del Grafo", badge: "Periferia" };
  if (r <= 10000) return { name: "Núcleo / Epicentro Global", badge: "Núcleo" };
  if (r <= 100000) return { name: "Órbita 1: Alta Conectividad", badge: "Alta Conectividad" };
  if (r <= 500000) return { name: "Órbita 2: Cuerpo Principal", badge: "Cuerpo Principal" };
  if (r <= 2000000) return { name: "Órbita 3: Conectividad Intermedia", badge: "Conectividad Intermedia" };
  return { name: "Órbita 4: Periferia del Grafo", badge: "Periferia" };
}

function renderProximityRadar(svgEl, radarData, data) {
  if (!svgEl) return;
  svgEl.innerHTML = "";

  // Resolver datos cibermétricos de proximidad
  const harm = (data && data.harmonic_centrality) || {};
  const rank = (radarData && radarData.rank) != null ? radarData.rank : harm.harmonic_rank;
  const journalTitle = (data && data.journal_title) || (data && data.query) || "Revista";
  const domain = (data && data.domain) || "";

  function getRadarRadius(r) {
    if (!r || r <= 0) return 0.94;
    if (r <= 10000) {
      const frac = Math.max(0, Math.log10(Math.max(1, r)) / 4.0);
      return 0.08 + frac * (0.25 - 0.08);
    } else if (r <= 100000) {
      const frac = (Math.log10(r) - 4.0) / 1.0;
      return 0.25 + frac * (0.48 - 0.25);
    } else if (r <= 500000) {
      const frac = (Math.log10(r) - 5.0) / Math.log10(5.0);
      return 0.48 + frac * (0.70 - 0.48);
    } else if (r <= 2000000) {
      const frac = (Math.log10(r) - Math.log10(500000)) / Math.log10(4.0);
      return 0.70 + frac * (0.88 - 0.70);
    } else {
      const frac = Math.min(1.0, (Math.log10(r) - Math.log10(2000000)) / (Math.log10(58900000) - Math.log10(2000000)));
      return 0.88 + frac * (0.95 - 0.88);
    }
  }

  const targetRadius = (radarData && radarData.target_radius) || getRadarRadius(rank);

  // HUD elements
  const orbitBadge = document.getElementById("scivis-radar-orbit-badge");
  const distPct = document.getElementById("scivis-radar-distance-pct");
  const rankReadout = document.getElementById("scivis-radar-rank-readout");
  const orbitDesc = document.getElementById("scivis-radar-orbit-desc");

  const totalDomains = (radarData && radarData.total_domains) || 58900000;
  let pctTop = rank && rank > 0 ? ((rank / totalDomains) * 100).toFixed(2) : null;
  if (pctTop && parseFloat(pctTop) < 0.01) pctTop = "0.01";
  const betterThan = pctTop ? (100 - parseFloat(pctTop)).toFixed(1) : null;

  let orbitName = "Sin registro";
  let orbitBadgeText = "Sin dato";
  let descText = "El dominio no figura en el corte primario del Web Graph de Common Crawl. Sin registro de conectividad estructural en este release.";
  let aiImpactText = "Sin registro de conectividad: la inclusión en corpus de entrenamiento depende de un robots.txt abierto, sitemaps y enlaces entrantes; la posición no puede evaluarse.";

  if (rank && rank > 0) {
    if (rank <= 10000) {
      orbitName = "Núcleo / Epicentro Global";
      orbitBadgeText = "Núcleo";
      descText = "Núcleo de máxima conectividad estructural: alcanzable en muy pocos saltos desde casi cualquier punto del grafo.";
      aiImpactText = "El dominio está en el núcleo mejor conectado del grafo: la probabilidad de presencia en corpus de rastreo es alta. Aun así, la prioridad de cada rastreador (CCBot, GPTBot, ClaudeBot) no es pública y depende de robots.txt, sitemaps y de la calidad técnica del sitio; no existe una garantía formal.";
    } else if (rank <= 100000) {
      orbitName = "Órbita 1: Alta Conectividad Internacional";
      orbitBadgeText = "Alta Conectividad";
      descText = "Alta conectividad estructural: alcanzable en pocos saltos desde amplias regiones de la web, aunque fuera del núcleo de máxima visibilidad.";
      aiImpactText = "Conectividad alta: el dominio es estructuralmente muy accesible, lo que favorece su rastreo e inclusión en corpus de entrenamiento. La prioridad concreta de cada proveedor no es pública; robots.txt y sitemaps siguen siendo los factores controlables.";
    } else if (rank <= 500000) {
      orbitName = "Órbita 2: Cuerpo Principal de la Web";
      orbitBadgeText = "Cuerpo Principal";
      descText = "Cuerpo principal de la web: presencia estructural sólida y accesible, a varias distancias de los ejes centrales de difusión.";
      aiImpactText = "Conectividad sólida: el dominio es rastreable y puede estar presente en corpus de entrenamiento. La prioridad de rastreo no es automática ni está garantizada por el rango; depende de robots.txt, sitemaps y de los enlaces entrantes.";
    } else if (rank <= 2000000) {
      orbitName = "Órbita 3: Conectividad Intermedia";
      orbitBadgeText = "Conectividad Intermedia";
      descText = "Posición estructural intermedia: el dominio tiene enlaces entrantes, pero opera lejos de los ejes centrales de difusión y su conectividad es modesta en términos absolutos.";
      aiImpactText = "Posición intermedia: el dominio es alcanzable, pero está lejos de los ejes centrales. La inclusión en corpus de IA no está garantizada por esta posición; las palancas controlables son un robots.txt abierto, sitemaps y enlaces desde portales consolidados.";
    } else {
      orbitName = "Órbita 4: Periferia del Grafo";
      orbitBadgeText = "Periferia";
      descText = "Periferia del grafo: conectividad entrante limitada. En este rango la métrica es una señal débil; la mejora depende de enlaces desde dominios establecidos.";
      aiImpactText = "Periferia del grafo: la probabilidad de presencia en corpus de entrenamiento es baja y la prioridad de rastreo menor. Las acciones efectivas son abrir robots.txt, publicar sitemaps y ganar enlaces desde dominios de autoridad.";
    }
  }

  if (orbitBadge) orbitBadge.textContent = (radarData && radarData.orbit_badge) || orbitBadgeText;
  if (distPct) distPct.textContent = pctTop ? `Top ${pctTop}% global` : "Sin dato";
  if (rankReadout) {
    rankReadout.innerHTML = (radarData && radarData.distance_label)
      ? escapeHtml(radarData.distance_label)
      : (rank && rank > 0
        ? `Rango HC: #${Number(rank).toLocaleString()} entre ${Number(totalDomains).toLocaleString()} dominios`
        : "Rango HC: <em>Sin corte primario en este release</em>");
  }
  if (orbitDesc) {
    let txt = (radarData && radarData.orbit_desc) || descText;
    const measuredNote = radarData && radarData.measured_note;
    orbitDesc.innerHTML = escapeHtml(txt) + (measuredNote ? `<br/><em style="font-size:0.78rem; color:var(--on-surface-variant, #536062);">${escapeHtml(measuredNote)}</em>` : "");
  }
  const aiImpactEl = document.getElementById("scivis-radar-ai-impact");
  if (aiImpactEl) aiImpactEl.textContent = (radarData && radarData.ai_impact) || aiImpactText;

  // Renderizar Radar SVG en lienzo generoso (500x500)
  const cx = 250;
  const cy = 250;
  const maxR = 210;
  svgEl.setAttribute("viewBox", "0 0 500 500");

  const tooltipEl = document.getElementById("scivis-radar-tooltip");
  const containerEl = document.getElementById("scivis-radar-container");

  function showTooltip(html, mouseX, mouseY) {
    if (!tooltipEl || !containerEl) return;
    tooltipEl.innerHTML = html;
    tooltipEl.style.display = "block";
    const rect = containerEl.getBoundingClientRect();
    let left = mouseX - rect.left + 14;
    let top = mouseY - rect.top + 14;
    if (left + 240 > rect.width) left = mouseX - rect.left - 250;
    if (top + 120 > rect.height) top = mouseY - rect.top - 110;
    tooltipEl.style.left = `${Math.max(10, left)}px`;
    tooltipEl.style.top = `${Math.max(10, top)}px`;
  }

  function hideTooltip() {
    if (tooltipEl) tooltipEl.style.display = "none";
  }

  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  defs.innerHTML = `
    <filter id="radar-glow-strong" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="4.5" result="blur" />
      <feMerge>
        <feMergeNode in="blur" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
  `;
  svgEl.appendChild(defs);

  // Crosshair Axes (Polar Grid)
  const axesGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
  axesGroup.setAttribute("opacity", "0.28");
  axesGroup.innerHTML = `
    <line x1="${cx}" y1="${cy - maxR}" x2="${cx}" y2="${cy + maxR}" stroke="#00F0D0" stroke-width="1.2" stroke-dasharray="4,4" />
    <line x1="${cx - maxR}" y1="${cy}" x2="${cx + maxR}" y2="${cy}" stroke="#00F0D0" stroke-width="1.2" stroke-dasharray="4,4" />
    <line x1="${cx - maxR * 0.707}" y1="${cy - maxR * 0.707}" x2="${cx + maxR * 0.707}" y2="${cy + maxR * 0.707}" stroke="#00F0D0" stroke-width="0.8" stroke-dasharray="3,5" />
    <line x1="${cx - maxR * 0.707}" y1="${cy + maxR * 0.707}" x2="${cx + maxR * 0.707}" y2="${cy - maxR * 0.707}" stroke="#00F0D0" stroke-width="0.8" stroke-dasharray="3,5" />
  `;
  svgEl.appendChild(axesGroup);

  // Concentric Orbit Rings (Alta accesibilidad cromática y contraste)
  const rings = [
    { id: "core", r: 0.25, label: "Top 10k", name: "Núcleo / Epicentro", color: "#FFD166", range: "Rango 1 a 10.000", dash: "3,3" },
    { id: "orbit1", r: 0.48, label: "Top 100k", name: "Órbita 1: Alta Conectividad", color: "#06D6A0", range: "Rango 10.000 a 100.000", dash: "4,4" },
    { id: "orbit2", r: 0.70, label: "Top 500k", name: "Órbita 2: Cuerpo Principal", color: "#38BDF8", range: "Rango 100.000 a 500.000", dash: "5,5" },
    { id: "orbit3", r: 0.88, label: "Top 2M", name: "Órbita 3: Intermedia", color: "#C084FC", range: "Rango 500.000 a 2.000.000", dash: "5,5" },
    { id: "orbit4", r: 0.96, label: "Periferia", name: "Órbita 4: Periferia", color: "#FB7185", range: "Rango > 2.000.000 o sin presencia", dash: "3,5" },
  ];

  const ringsGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
  rings.forEach((ring) => {
    const radiusPx = maxR * ring.r;

    // Círculo visible
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("id", `radar-ring-${ring.id}`);
    circle.setAttribute("class", "radar-ring-interactive");
    circle.setAttribute("cx", cx);
    circle.setAttribute("cy", cy);
    circle.setAttribute("r", radiusPx);
    circle.setAttribute("fill", "none");
    circle.setAttribute("stroke", ring.color);
    circle.setAttribute("stroke-width", "1.8");
    circle.setAttribute("stroke-dasharray", ring.dash);
    circle.setAttribute("opacity", "0.55");
    ringsGroup.appendChild(circle);

    // Hit area invisible amplia para facilitar hover y click
    const hitArea = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    hitArea.setAttribute("cx", cx);
    hitArea.setAttribute("cy", cy);
    hitArea.setAttribute("r", radiusPx);
    hitArea.setAttribute("fill", "none");
    hitArea.setAttribute("stroke", "transparent");
    hitArea.setAttribute("stroke-width", "20");
    hitArea.style.cursor = "pointer";
    hitArea.addEventListener("mouseenter", (e) => {
      circle.classList.add("highlighted");
      showTooltip(`<strong>${escapeHtml(ring.name)}</strong><br/><span style="color:${ring.color}; font-weight:700;">${escapeHtml(ring.range)}</span><br/><span style="font-size:0.75rem; color:#A3D9E2;">Radio hipertextual: ${(ring.r * 100).toFixed(0)}%</span>`, e.clientX, e.clientY);
    });
    hitArea.addEventListener("mousemove", (e) => {
      showTooltip(`<strong>${escapeHtml(ring.name)}</strong><br/><span style="color:${ring.color}; font-weight:700;">${escapeHtml(ring.range)}</span><br/><span style="font-size:0.75rem; color:#A3D9E2;">Radio hipertextual: ${(ring.r * 100).toFixed(0)}%</span>`, e.clientX, e.clientY);
    });
    hitArea.addEventListener("mouseleave", () => {
      circle.classList.remove("highlighted");
      hideTooltip();
    });
    ringsGroup.appendChild(hitArea);

    // Etiqueta de distancia sobre el eje vertical superior con cápsula de alto contraste
    const tagGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
    const tagY = cy - radiusPx;
    const tagW = ring.label.length > 7 ? 68 : 56;

    const bgRect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    bgRect.setAttribute("x", cx - tagW / 2);
    bgRect.setAttribute("y", tagY - 9);
    bgRect.setAttribute("width", tagW);
    bgRect.setAttribute("height", "18");
    bgRect.setAttribute("rx", "4");
    bgRect.setAttribute("fill", "rgba(6, 20, 24, 0.88)");
    bgRect.setAttribute("stroke", ring.color);
    bgRect.setAttribute("stroke-width", "1");
    tagGroup.appendChild(bgRect);

    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", cx);
    text.setAttribute("y", tagY + 4);
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("fill", "#FFFFFF");
    text.setAttribute("font-size", "10.5px");
    text.setAttribute("font-weight", "700");
    text.setAttribute("font-family", "monospace");
    text.textContent = ring.label;
    tagGroup.appendChild(text);

    ringsGroup.appendChild(tagGroup);
  });
  svgEl.appendChild(ringsGroup);

  // Epicentro Central (Beacon del Núcleo: Rank #1)
  const coreBeacon = document.createElementNS("http://www.w3.org/2000/svg", "g");
  coreBeacon.style.cursor = "pointer";
  coreBeacon.innerHTML = `
    <circle cx="${cx}" cy="${cy}" r="7" fill="#FFD166" filter="url(#radar-glow-strong)" />
    <circle cx="${cx}" cy="${cy}" r="2" fill="#FFFFFF" />
  `;
  coreBeacon.addEventListener("mouseenter", (e) => {
    showTooltip(`<strong>🎯 Epicentro Global del Web Graph</strong><br/><span style="color:#FFD166; font-weight:700;">Rango #1</span><br/><span style="font-size:0.75rem;">Máxima densidad de enlaces en la red mundial.</span>`, e.clientX, e.clientY);
  });
  coreBeacon.addEventListener("mouseleave", hideTooltip);
  svgEl.appendChild(coreBeacon);

  const blipsGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");

  // Nodo de Referencia: Wikipedia (Núcleo)
  const wikiR = maxR * getRadarRadius(5);
  const wikiAngleRad = (215 * Math.PI) / 180;
  const wikiX = cx + wikiR * Math.cos(wikiAngleRad);
  const wikiY = cy + wikiR * Math.sin(wikiAngleRad);

  const wikiNode = document.createElementNS("http://www.w3.org/2000/svg", "g");
  wikiNode.setAttribute("class", "radar-blip-node");
  wikiNode.innerHTML = `
    <circle cx="${wikiX}" cy="${wikiY}" r="6" fill="#FFD166" stroke="#ffffff" stroke-width="1.5" filter="url(#radar-glow-strong)" />
    <rect x="${wikiX - 90}" y="${wikiY - 10}" width="80" height="20" rx="4" fill="rgba(6, 20, 24, 0.85)" stroke="#FFD166" stroke-width="1" />
    <text x="${wikiX - 50}" y="${wikiY + 4}" text-anchor="middle" fill="#FFD166" font-size="10px" font-weight="700">Wikipedia (#5)</text>
  `;
  wikiNode.addEventListener("mouseenter", (e) => {
    showTooltip(`<strong>Wikipedia</strong> (wikipedia.org)<br/><span style="color:#FFD166; font-weight:700;">Rango HC: #5</span><br/>Ubicación: Núcleo Global.<br/><span style="font-size:0.75rem; color:#A3D9E2;">Referencia central del hipergrafo.</span>`, e.clientX, e.clientY);
  });
  wikiNode.addEventListener("mouseleave", hideTooltip);
  blipsGroup.appendChild(wikiNode);

  // COORDENADAS DEL NODO OBJETIVO (LA REVISTA AUDITADA)
  const targetDistPx = maxR * targetRadius;
  const targetAngleRad = (315 * Math.PI) / 180; // Cuadrante superior derecho
  const targetX = cx + targetDistPx * Math.cos(targetAngleRad);
  const targetY = cy + targetDistPx * Math.sin(targetAngleRad);

  // NODOS CONTRASTADOS (COMPARACIÓN DINÁMICA DE REVISTAS)
  radarComparedJournals.forEach((comp, idx) => {
    const pal = RADAR_COMPARE_PALETTES[idx % RADAR_COMPARE_PALETTES.length];
    const cRank = comp.rank;
    const cRadius = comp.target_radius || getRadarRadius(cRank);
    const cDistPx = maxR * cRadius;
    const cAngleDeg = RADAR_COMPARE_ANGLES[idx % RADAR_COMPARE_ANGLES.length];
    const cAngleRad = (cAngleDeg * Math.PI) / 180;
    const cX = cx + cDistPx * Math.cos(cAngleRad);
    const cY = cy + cDistPx * Math.sin(cAngleRad);

    const compGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
    compGroup.setAttribute("class", "radar-blip-node");
    compGroup.setAttribute("id", `radar-compared-node-${idx}`);

    // Línea radial conectora con el centro
    const cLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
    cLine.setAttribute("x1", cx);
    cLine.setAttribute("y1", cy);
    cLine.setAttribute("x2", cX);
    cLine.setAttribute("y2", cY);
    cLine.setAttribute("stroke", pal.line);
    cLine.setAttribute("stroke-width", "1.6");
    cLine.setAttribute("stroke-dasharray", "3,3");
    blipsGroup.appendChild(cLine);

    // Conector diferencial entre el Objetivo y la primera revista comparada (idx === 0)
    if (idx === 0) {
      const chordLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
      chordLine.setAttribute("x1", targetX);
      chordLine.setAttribute("y1", targetY);
      chordLine.setAttribute("x2", cX);
      chordLine.setAttribute("y2", cY);
      chordLine.setAttribute("stroke", "rgba(255, 255, 255, 0.4)");
      chordLine.setAttribute("stroke-width", "1.2");
      chordLine.setAttribute("stroke-dasharray", "2,4");
      blipsGroup.appendChild(chordLine);

      // Distancia vectorial relativa entre ambas
      const chordMidX = (targetX + cX) / 2;
      const chordMidY = (targetY + cY) / 2;
      const deltaTag = document.createElementNS("http://www.w3.org/2000/svg", "text");
      deltaTag.setAttribute("x", chordMidX);
      deltaTag.setAttribute("y", chordMidY - 5);
      deltaTag.setAttribute("text-anchor", "middle");
      deltaTag.setAttribute("fill", "#FFD166");
      deltaTag.setAttribute("font-size", "9.5px");
      deltaTag.setAttribute("font-weight", "700");
      deltaTag.setAttribute("font-family", "monospace");
      const rDiff = Math.abs((targetRadius - cRadius) * 100).toFixed(0);
      deltaTag.textContent = `Δr = ${rDiff}%`;
      blipsGroup.appendChild(deltaTag);
    }

    // Anillo de pulso animado
    const cPulse = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    cPulse.setAttribute("cx", cX);
    cPulse.setAttribute("cy", cY);
    cPulse.setAttribute("r", "6");
    cPulse.setAttribute("fill", "none");
    cPulse.setAttribute("stroke", pal.stroke);
    cPulse.setAttribute("class", "radar-blip-pulse");
    compGroup.appendChild(cPulse);

    // Punto central brillante
    const cDot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    cDot.setAttribute("cx", cX);
    cDot.setAttribute("cy", cY);
    cDot.setAttribute("r", "7.5");
    cDot.setAttribute("fill", pal.fill);
    cDot.setAttribute("stroke", "#ffffff");
    cDot.setAttribute("stroke-width", "2");
    cDot.setAttribute("filter", "url(#radar-glow-strong)");
    compGroup.appendChild(cDot);

    // Etiqueta inteligente orientada hacia adentro
    const cShort = comp.title.length > 20 ? comp.title.slice(0, 18) + "…" : comp.title;
    const cRankTag = cRank && cRank > 0 ? `#${Number(cRank).toLocaleString()}` : "Periferia";
    const cLabelText = `📊 ${cShort} (${cRankTag})`;
    const cLabelWidth = Math.min(210, Math.max(90, cLabelText.length * 6.8 + 18));
    const cLabelX = cX > cx ? cX - cLabelWidth - 12 : cX + 12;
    const cLabelY = cY > cy ? cY - 24 : cY - 6;

    const cLabelBg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    cLabelBg.setAttribute("x", cLabelX);
    cLabelBg.setAttribute("y", cLabelY - 13);
    cLabelBg.setAttribute("width", cLabelWidth);
    cLabelBg.setAttribute("height", "22");
    cLabelBg.setAttribute("rx", "4");
    cLabelBg.setAttribute("fill", "rgba(6, 20, 24, 0.92)");
    cLabelBg.setAttribute("stroke", pal.stroke);
    cLabelBg.setAttribute("stroke-width", "1.2");
    compGroup.appendChild(cLabelBg);

    const cLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    cLabel.setAttribute("x", cLabelX + 8);
    cLabel.setAttribute("y", cLabelY + 2);
    cLabel.setAttribute("fill", "#FFFFFF");
    cLabel.setAttribute("font-size", "10.5px");
    cLabel.setAttribute("font-weight", "700");
    cLabel.textContent = cLabelText;
    compGroup.appendChild(cLabel);

    // Hover interactivo con cálculo comparativo
    let compDeltaNote = "";
    if (rank && cRank) {
      const diff = rank - cRank;
      if (diff > 0) compDeltaNote = `<span style="color:#06D6A0; font-weight:700;">▲ +${Number(diff).toLocaleString()} puestos más cerca del epicentro</span>`;
      else if (diff < 0) compDeltaNote = `<span style="color:#FB7185; font-weight:700;">▼ -${Number(Math.abs(diff)).toLocaleString()} puestos hacia la periferia</span>`;
      else compDeltaNote = `<span style="color:#38BDF8; font-weight:700;">= Mismo rango que ${escapeHtml(journalTitle)}</span>`;
    }

    compGroup.addEventListener("mouseenter", (e) => {
      cDot.setAttribute("r", "10");
      showTooltip(`
        <div style="font-weight:700; font-size:0.88rem; color:${pal.stroke}; margin-bottom:4px;">📊 ${escapeHtml(comp.title)}</div>
        <div><strong>Dominio:</strong> ${escapeHtml(comp.domain || 'N/D')}</div>
        <div><strong>Rango HC:</strong> <span style="color:#FFD166; font-weight:700;">${cRankTag}</span></div>
        <div><strong>Ubicación:</strong> ${escapeHtml(comp.orbit_name || 'Órbita calculada')}</div>
        <div><strong>Distancia radial:</strong> ${(cRadius * 100).toFixed(1)}%</div>
        ${compDeltaNote ? `<div style="margin-top:4px; padding-top:4px; border-top:1px solid rgba(255,255,255,0.15);">${compDeltaNote}</div>` : ""}
      `, e.clientX, e.clientY);
    });

    compGroup.addEventListener("mouseleave", () => {
      cDot.setAttribute("r", "7.5");
      hideTooltip();
    });

    blipsGroup.appendChild(compGroup);
  });

  // Si no hay revistas contrastadas activas, mostrar 1-2 competidores de referencia
  if (radarComparedJournals.length === 0) {
    const competitors = (data && data.competitors) || [];
    const compAngles = [115, 30, 160];
    let compCount = 0;
    competitors.forEach((comp) => {
      if (compCount >= 2) return;
      const cRank = comp.harmonic_rank;
      if (cRank && !comp.is_target) {
        const cR = maxR * getRadarRadius(cRank);
        const cAngleRad = (compAngles[compCount % compAngles.length] * Math.PI) / 180;
        const cX = cx + cR * Math.cos(cAngleRad);
        const cY = cy + cR * Math.sin(cAngleRad);
        const cTitle = comp.journal_title || "Comparable";
        const shortTitle = cTitle.length > 16 ? cTitle.slice(0, 14) + "…" : cTitle;

        const compNode = document.createElementNS("http://www.w3.org/2000/svg", "g");
        compNode.setAttribute("class", "radar-blip-node");
        compNode.innerHTML = `
          <circle cx="${cX}" cy="${cY}" r="5" fill="#38BDF8" stroke="#ffffff" stroke-width="1.2" />
          <rect x="${cX + 8}" y="${cY - 9}" width="${shortTitle.length * 6.2 + 12}" height="18" rx="3" fill="rgba(6, 20, 24, 0.8)" stroke="#38BDF8" stroke-width="0.8" />
          <text x="${cX + 14}" y="${cY + 4}" fill="#E0F2FE" font-size="9.5px" font-weight="600">${escapeHtml(shortTitle)}</text>
        `;
        compNode.addEventListener("mouseenter", (e) => {
          showTooltip(`<strong>${escapeHtml(cTitle)}</strong><br/><span style="color:#38BDF8; font-weight:700;">Rango HC: #${Number(cRank).toLocaleString()}</span><br/><span style="font-size:0.75rem;">Distancia radial: ${(cR / maxR * 100).toFixed(0)}%</span><br/><em style="font-size:0.72rem; color:#A3D9E2;">Haga clic en 'Contrastar' para compararla en detalle.</em>`, e.clientX, e.clientY);
        });
        compNode.addEventListener("mouseleave", hideTooltip);
        blipsGroup.appendChild(compNode);
        compCount++;
      }
    });
  }

  // NODO OBJETIVO: LA REVISTA AUDITADA (Foco Principal)
  const targetGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
  targetGroup.setAttribute("id", "scivis-radar-target-group");
  targetGroup.setAttribute("class", "radar-blip-node");

  // Línea radial conectora desde el centro con etiqueta de distancia
  const connector = document.createElementNS("http://www.w3.org/2000/svg", "line");
  connector.setAttribute("id", "scivis-radar-connector-line");
  connector.setAttribute("x1", cx);
  connector.setAttribute("y1", cy);
  connector.setAttribute("x2", targetX);
  connector.setAttribute("y2", targetY);
  connector.setAttribute("stroke", "rgba(0, 240, 208, 0.55)");
  connector.setAttribute("stroke-width", "2");
  connector.setAttribute("stroke-dasharray", "4,4");
  blipsGroup.appendChild(connector);

  const midX = (cx + targetX) / 2;
  const midY = (cy + targetY) / 2;
  const distMarker = document.createElementNS("http://www.w3.org/2000/svg", "text");
  distMarker.setAttribute("x", midX - 8);
  distMarker.setAttribute("y", midY + 5);
  distMarker.setAttribute("fill", "#00F0D0");
  distMarker.setAttribute("font-size", "9.5px");
  distMarker.setAttribute("font-weight", "700");
  distMarker.setAttribute("font-family", "monospace");
  distMarker.setAttribute("transform", `rotate(-45, ${midX}, ${midY})`);
  distMarker.textContent = rank && rank > 0 ? `r = ${(targetRadius * 100).toFixed(0)}%` : "periferia";
  blipsGroup.appendChild(distMarker);

  // Anillo de pulso expansivo animado
  const pulseRing = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  pulseRing.setAttribute("id", "scivis-radar-target-pulse");
  pulseRing.setAttribute("cx", targetX);
  pulseRing.setAttribute("cy", targetY);
  pulseRing.setAttribute("r", "7");
  pulseRing.setAttribute("fill", "none");
  pulseRing.setAttribute("stroke", "#00F0D0");
  pulseRing.setAttribute("class", "radar-blip-pulse");
  targetGroup.appendChild(pulseRing);

  // Punto central brillante de la revista
  const targetDot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  targetDot.setAttribute("cx", targetX);
  targetDot.setAttribute("cy", targetY);
  targetDot.setAttribute("r", "8.5");
  targetDot.setAttribute("fill", "#00F0D0");
  targetDot.setAttribute("stroke", "#ffffff");
  targetDot.setAttribute("stroke-width", "2.5");
  targetDot.setAttribute("filter", "url(#radar-glow-strong)");
  targetGroup.appendChild(targetDot);

  // ETIQUETA INTELIGENTE (orientada hacia el interior para NUNCA recortarse contra el marco)
  const shortTarget = journalTitle.length > 22 ? journalTitle.slice(0, 20) + "…" : journalTitle;
  const rankTag = rank && rank > 0 ? `#${Number(rank).toLocaleString()}` : "Periferia";
  const labelFullText = `🎯 ${shortTarget} (${rankTag})`;
  const labelWidth = Math.min(220, Math.max(100, labelFullText.length * 7.2 + 20));

  const labelX = targetX > cx ? targetX - labelWidth - 14 : targetX + 14;
  const labelY = targetY > cy ? targetY - 26 : targetY - 6;

  const labelBg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  labelBg.setAttribute("x", labelX);
  labelBg.setAttribute("y", labelY - 14);
  labelBg.setAttribute("width", labelWidth);
  labelBg.setAttribute("height", "24");
  labelBg.setAttribute("rx", "5");
  labelBg.setAttribute("fill", "rgba(6, 20, 24, 0.92)");
  labelBg.setAttribute("stroke", "#00F0D0");
  labelBg.setAttribute("stroke-width", "1.5");
  targetGroup.appendChild(labelBg);

  const labelText = document.createElementNS("http://www.w3.org/2000/svg", "text");
  labelText.setAttribute("x", labelX + 10);
  labelText.setAttribute("y", labelY + 3);
  labelText.setAttribute("fill", "#FFFFFF");
  labelText.setAttribute("font-size", "11.5px");
  labelText.setAttribute("font-weight", "700");
  labelText.textContent = labelFullText;
  targetGroup.appendChild(labelText);

  // Eventos de hover interactivo en la revista objetivo
  targetGroup.addEventListener("mouseenter", (e) => {
    targetDot.setAttribute("r", "11");
    showTooltip(`
      <div style="font-weight:700; font-size:0.88rem; color:#00F0D0; margin-bottom:4px;">🎯 ${escapeHtml(journalTitle)}</div>
      <div><strong>Dominio:</strong> ${escapeHtml(domain || 'N/D')}</div>
      <div><strong>Rango HC:</strong> <span style="color:#FFD166; font-weight:700;">${rankTag}</span></div>
      <div><strong>Órbita:</strong> ${escapeHtml(orbitName)}</div>
      <div><strong>Distancia radial:</strong> ${(targetRadius * 100).toFixed(1)}% del hipergrafo</div>
    `, e.clientX, e.clientY);
  });
  targetGroup.addEventListener("mouseleave", () => {
    targetDot.setAttribute("r", "8.5");
    hideTooltip();
  });

  blipsGroup.appendChild(targetGroup);
  svgEl.appendChild(blipsGroup);

  // 3. Controles Interactivos (Pausar barrido, Localizar objetivo y Chips de órbita)
  const toggleSweepBtn = document.getElementById("scivis-radar-toggle-sweep");
  const focusTargetBtn = document.getElementById("scivis-radar-focus-target");
  const beamEl = document.getElementById("scivis-radar-beam");

  if (toggleSweepBtn && beamEl) {
    toggleSweepBtn.onclick = () => {
      const isPaused = beamEl.classList.toggle("radar-sweep-paused");
      toggleSweepBtn.innerHTML = isPaused
        ? `<span class="material-symbols-outlined text-[14px]">play_arrow</span><span>Reanudar</span>`
        : `<span class="material-symbols-outlined text-[14px]">pause</span><span>Pausar</span>`;
    };
  }

  if (focusTargetBtn) {
    focusTargetBtn.onclick = () => {
      pulseRing.classList.remove("radar-blip-pulse");
      void pulseRing.offsetWidth; // Force reflow
      pulseRing.classList.add("radar-blip-pulse");
      connector.setAttribute("stroke", "#FFFFFF");
      connector.setAttribute("stroke-width", "3");
      setTimeout(() => {
        connector.setAttribute("stroke", "rgba(0, 240, 208, 0.55)");
        connector.setAttribute("stroke-width", "2");
      }, 1200);
    };
  }

  // Chips de órbita interactivos (Click para resaltar órbita)
  document.querySelectorAll(".radar-orbit-chip").forEach((chip) => {
    chip.onclick = () => {
      const orbitKey = chip.getAttribute("data-orbit");
      document.querySelectorAll(".radar-orbit-chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");

      document.querySelectorAll(".radar-ring-interactive").forEach((c) => c.classList.remove("highlighted"));
      const ringEl = document.getElementById(`radar-ring-${orbitKey}`);
      if (ringEl) {
        ringEl.classList.add("highlighted");
        setTimeout(() => ringEl.classList.remove("highlighted"), 2500);
      }
    };
  });

  // 4. Actualizar Matriz de Contraste y UI de Comparación
  renderRadarComparisonMatrix(data, rank, targetRadius, orbitName);
  setupRadarComparisonUI(data);
}

function renderRadarComparisonMatrix(data, targetRank, targetRadius, targetOrbit) {
  const matrixEl = document.getElementById("scivis-radar-comparison-matrix");
  const counterEl = document.getElementById("scivis-radar-compare-counter");
  if (!matrixEl) return;

  const count = radarComparedJournals.length;
  if (counterEl) {
    counterEl.textContent = `${count} / 3 contrastadas`;
    counterEl.style.background = count > 0 ? "rgba(0, 240, 208, 0.2)" : "rgba(97, 145, 150, 0.15)";
    counterEl.style.color = count > 0 ? "#047857" : "var(--brand-teal-darker, #1E4F54)";
  }

  if (count === 0) {
    matrixEl.style.display = "block";
    matrixEl.innerHTML = `
      <div style="grid-column: 1 / -1; padding: 16px; background: rgba(97, 145, 150, 0.08); border-radius: 8px; border: 1px dashed rgba(97, 145, 150, 0.35); text-align: center; color: var(--on-surface-variant); font-size: 0.84rem;">
        <span class="material-symbols-outlined text-[20px]" style="vertical-align: -4px; margin-right: 6px; color: var(--brand-teal);">ads_click</span>
        Haga clic en una de las sugerencias del área o escriba otra revista en el buscador para proyectarla en el radar y contrastar su conectividad hipertextual.
      </div>
    `;
    return;
  }

  matrixEl.style.display = "grid";
  matrixEl.innerHTML = "";

  const targetTitle = (data && data.journal_title) || (data && data.query) || "Revista Auditada";
  const targetDomain = (data && data.domain) || "N/D";
  const targetRankStr = targetRank && targetRank > 0 ? `#${Number(targetRank).toLocaleString()}` : "Periferia / Sin corte";

  // 1. Tarjeta de Revista Objetivo (Foco Principal)
  const targetCard = document.createElement("div");
  targetCard.className = "radar-compare-card target-card";
  targetCard.innerHTML = `
    <div class="radar-compare-card-header">
      <div>
        <span style="font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: #0D9488; display: block; margin-bottom: 2px;">
          🎯 Foco Auditado (Base)
        </span>
        <h6 class="radar-compare-card-title">${escapeHtml(targetTitle)}</h6>
      </div>
      <span class="badge" style="background: rgba(0, 240, 208, 0.2); color: #047857; font-weight: 700; font-size: 0.75rem;">Referencia</span>
    </div>
    <div style="font-size: 0.8rem; color: var(--on-surface-variant); display: flex; flex-direction: column; gap: 4px;">
      <div><strong>Dominio:</strong> <code>${escapeHtml(targetDomain)}</code></div>
      <div><strong>Rango HC:</strong> <span style="font-weight: 700; color: var(--on-surface);">${targetRankStr}</span></div>
      <div><strong>Ubicación:</strong> ${escapeHtml(targetOrbit || 'Calculando')}</div>
      <div><strong>Radio Polar:</strong> ${(targetRadius * 100).toFixed(1)}% del hipergrafo</div>
    </div>
    <div style="font-size: 0.78rem; color: var(--on-surface-variant); line-height: 1.45; background: rgba(255,255,255,0.7); border-radius: 6px; padding: 8px 10px; margin-top: auto;">
      Revista base contra la que se calculan las distancias vectoriales y la diferencia de retroenlaces en el grafo.
    </div>
  `;
  matrixEl.appendChild(targetCard);

  // 2. Tarjetas de Revistas Contrastadas
  radarComparedJournals.forEach((comp, idx) => {
    const pal = RADAR_COMPARE_PALETTES[idx % RADAR_COMPARE_PALETTES.length];
    const cRank = comp.rank;
    const cRadius = comp.target_radius || 0.94;
    const cRankStr = cRank && cRank > 0 ? `#${Number(cRank).toLocaleString()}` : "Periferia / Sin corte";

    let deltaBadgeHtml = "";
    let diagnosisHtml = "";

    if (!targetRank || targetRank <= 0) {
      if (cRank && cRank > 0) {
        deltaBadgeHtml = `<span class="radar-compare-delta-badge better">▲ Mejor posicionada</span>`;
        diagnosisHtml = `Esta revista cuenta con posición verificada en Common Crawl (#${Number(cRank).toLocaleString()}), superando la falta de registro del objetivo en este release.`;
      } else {
        deltaBadgeHtml = `<span class="radar-compare-delta-badge equal">= Ambas en periferia</span>`;
        diagnosisHtml = `Ambas publicaciones operan sin registro primario de retroenlaces en el corte oficial del Web Graph.`;
      }
    } else if (!cRank || cRank <= 0) {
      deltaBadgeHtml = `<span class="radar-compare-delta-badge worse">▼ Sin corte en CC</span>`;
      diagnosisHtml = `El dominio consultado no registra enlaces suficientes para ingresar al corte primario de Common Crawl, quedando en la periferia frente a ${escapeHtml(targetTitle)}.`;
    } else {
      const delta = targetRank - cRank; // Si delta > 0, cRank es menor número (mejor conectado)
      const deltaRatio = (Math.abs(delta) / targetRank) * 100;

      if (delta > 0) {
        deltaBadgeHtml = `<span class="radar-compare-delta-badge better">▲ +${Number(delta).toLocaleString()} puestos (+${deltaRatio.toFixed(1)}%)</span>`;
        diagnosisHtml = `<strong>Mayor centralidad:</strong> Se ubica más cerca del epicentro hipertextual (${escapeHtml(comp.orbit_name)} vs ${escapeHtml(targetOrbit)}). Sus contenidos son accesibles a menor número medio de saltos de enlace en el grafo global.`;
      } else if (delta < 0) {
        deltaBadgeHtml = `<span class="radar-compare-delta-badge worse">▼ -${Number(Math.abs(delta)).toLocaleString()} puestos (-${deltaRatio.toFixed(1)}%)</span>`;
        diagnosisHtml = `<strong>Menor centralidad:</strong> ${escapeHtml(targetTitle)} la supera por ${Number(Math.abs(delta)).toLocaleString()} posiciones en el Web Graph. La comparada requiere más saltos hipertextuales para ser descubierta desde el núcleo web.`;
      } else {
        deltaBadgeHtml = `<span class="radar-compare-delta-badge equal">= Rango equivalente</span>`;
        diagnosisHtml = `Ambas revistas comparten una visibilidad e intensidad de retroenlaces prácticamente idéntica en este release del Web Graph.`;
      }
    }

    const compCard = document.createElement("div");
    compCard.className = `radar-compare-card compared-card-${idx}`;
    compCard.innerHTML = `
      <div class="radar-compare-card-header">
        <div>
          <span style="font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: ${pal.stroke}; display: block; margin-bottom: 2px;">
            📊 ${pal.label}
          </span>
          <h6 class="radar-compare-card-title">${escapeHtml(comp.title)}</h6>
        </div>
        ${deltaBadgeHtml}
      </div>
      <div style="font-size: 0.8rem; color: var(--on-surface-variant); display: flex; flex-direction: column; gap: 4px;">
        <div><strong>Dominio:</strong> <code>${escapeHtml(comp.domain || 'N/D')}</code></div>
        <div><strong>Rango HC:</strong> <span style="font-weight: 700; color: var(--on-surface);">${cRankStr}</span></div>
        <div><strong>Ubicación:</strong> ${escapeHtml(comp.orbit_name || 'Órbita calculada')}</div>
        <div><strong>Radio Polar:</strong> ${(cRadius * 100).toFixed(1)}% (${cRadius < targetRadius ? 'más céntrica' : cRadius > targetRadius ? 'más periférica' : 'mismo radio'})</div>
      </div>
      <div style="font-size: 0.78rem; color: var(--on-surface-variant); line-height: 1.48; background: rgba(255,255,255,0.7); border-radius: 6px; padding: 8px 10px; border-left: 3px solid ${pal.stroke};">
        ${diagnosisHtml}
      </div>
      <button type="button" class="radar-remove-compare-btn" data-compare-idx="${idx}" title="Eliminar del radar">
        <span class="material-symbols-outlined text-[14px]">close</span>
        <span>Quitar del Radar</span>
      </button>
    `;

    const removeBtn = compCard.querySelector(".radar-remove-compare-btn");
    if (removeBtn) {
      removeBtn.addEventListener("click", () => {
        removeJournalFromRadarComparison(idx);
      });
    }

    matrixEl.appendChild(compCard);
  });
}

function setupRadarComparisonUI(data) {
  const inputEl = document.getElementById("scivis-radar-compare-input");
  const addBtn = document.getElementById("scivis-radar-compare-add-btn");
  const suggestionsEl = document.getElementById("scivis-radar-compare-suggestions");
  if (!inputEl || !addBtn) return;

  // Sugerencias dinámicas basadas en competitors
  if (suggestionsEl) {
    suggestionsEl.innerHTML = "";
    const rawComps = (data && data.competitors) || [];
    const validComps = rawComps.filter(c => c && !c.is_target);

    // Fallbacks si la revista no tiene competidores detectados
    const defaultSuggestions = [
      { journal_title: "El Profesional de la Información", domain: "profesionaldelainformacion.com" },
      { journal_title: "Comunicar", domain: "revistacomunicar.com" },
      { journal_title: "Revista Latina de Comunicación Social", domain: "revistalatinacs.org" },
      { journal_title: "Palabra Clave", domain: "unisabana.edu.co" }
    ];

    const pool = validComps.length >= 2 ? validComps : [...validComps, ...defaultSuggestions];
    const seen = new Set();
    const targetTitleNorm = (data && (data.journal_title || data.query || "")).toLowerCase().trim();

    pool.forEach(item => {
      const title = item.journal_title || "";
      const titleNorm = title.toLowerCase().trim();
      if (!title || titleNorm === targetTitleNorm || seen.has(titleNorm) || seen.size >= 5) return;
      seen.add(titleNorm);

      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "radar-suggestion-chip";
      chip.innerHTML = `<span class="material-symbols-outlined text-[13px]">add</span><span>${escapeHtml(title)}</span>`;
      chip.addEventListener("click", () => {
        addJournalToRadarComparison(item);
      });
      suggestionsEl.appendChild(chip);
    });
  }

  // Evento botón Contrastar
  addBtn.onclick = () => {
    const q = (inputEl.value || "").trim();
    if (!q) {
      inputEl.focus();
      return;
    }
    addJournalToRadarComparison(q);
    inputEl.value = "";
  };

  // Evento tecla Enter en input
  inputEl.onkeydown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addBtn.click();
    }
  };
}

async function addJournalToRadarComparison(queryOrObj) {
  const errorEl = document.getElementById("scivis-radar-compare-error");
  const addBtn = document.getElementById("scivis-radar-compare-add-btn");
  const showError = (msg) => {
    if (errorEl) {
      errorEl.textContent = msg;
      errorEl.style.display = "block";
      setTimeout(() => { if (errorEl) errorEl.style.display = "none"; }, 4000);
    }
  };

  if (radarComparedJournals.length >= 3) {
    showError("Máximo 3 revistas contrastadas simultáneamente. Descarte una para añadir otra.");
    return;
  }

  let title = typeof queryOrObj === "string" ? queryOrObj.trim() : (queryOrObj.journal_title || "");
  let domain = typeof queryOrObj === "object" ? (queryOrObj.domain || "") : "";
  let rank = typeof queryOrObj === "object" ? queryOrObj.harmonic_rank : undefined;

  const targetTitle = (currentJournalAuditData && (currentJournalAuditData.journal_title || currentJournalAuditData.query || "")).toLowerCase().trim();
  if (title.toLowerCase().trim() === targetTitle) {
    showError("Esta es la revista auditada de referencia.");
    return;
  }

  if (radarComparedJournals.some(c => c.title.toLowerCase().trim() === title.toLowerCase().trim())) {
    showError("Esta revista ya está proyectada en el radar.");
    return;
  }

  // Si no tenemos rango ni datos completos, consultar al endpoint
  if (rank == null) {
    if (addBtn) {
      addBtn.disabled = true;
      addBtn.innerHTML = `<span class="material-symbols-outlined text-[16px] animate-spin">progress_activity</span><span>Cargando...</span>`;
    }
    try {
      const resp = await fetch(`/api/scivis/audit?q=${encodeURIComponent(title)}`);
      if (!resp.ok) throw new Error("No se pudo obtener la auditoría cibermétrica");
      const audit = await resp.json();
      title = audit.journal_title || title;
      domain = audit.domain || domain;
      const harm = audit.harmonic_centrality || {};
      rank = harm.harmonic_rank != null ? harm.harmonic_rank : (audit.proximity_radar && audit.proximity_radar.rank);
    } catch (err) {
      showError("Error al auditar la revista para comparar: " + err.message);
      if (addBtn) {
        addBtn.disabled = false;
        addBtn.innerHTML = `<span class="material-symbols-outlined text-[16px]">add_circle</span><span>Contrastar</span>`;
      }
      return;
    } finally {
      if (addBtn) {
        addBtn.disabled = false;
        addBtn.innerHTML = `<span class="material-symbols-outlined text-[16px]">add_circle</span><span>Contrastar</span>`;
      }
    }
  }

  const orbitInfo = getRadarOrbitInfo(rank);
  const totalDomains = (currentJournalAuditData && currentJournalAuditData.proximity_radar && currentJournalAuditData.proximity_radar.total_domains) || 58900000;
  
  function calcRadius(r) {
    if (!r || r <= 0) return 0.94;
    if (r <= 10000) {
      const frac = Math.max(0, Math.log10(Math.max(1, r)) / 4.0);
      return 0.08 + frac * (0.25 - 0.08);
    } else if (r <= 100000) {
      const frac = (Math.log10(r) - 4.0) / 1.0;
      return 0.25 + frac * (0.48 - 0.25);
    } else if (r <= 500000) {
      const frac = (Math.log10(r) - 5.0) / Math.log10(5.0);
      return 0.48 + frac * (0.70 - 0.48);
    } else if (r <= 2000000) {
      const frac = (Math.log10(r) - Math.log10(500000)) / Math.log10(4.0);
      return 0.70 + frac * (0.88 - 0.70);
    } else {
      const frac = Math.min(1.0, (Math.log10(r) - Math.log10(2000000)) / (Math.log10(totalDomains) - Math.log10(2000000)));
      return 0.88 + frac * (0.95 - 0.88);
    }
  }

  radarComparedJournals.push({
    title,
    domain,
    rank,
    target_radius: calcRadius(rank),
    orbit_name: orbitInfo.name,
    orbit_badge: orbitInfo.badge,
  });

  const radarSvg = document.getElementById("scivis-radar-svg");
  if (radarSvg && currentJournalAuditData) {
    renderProximityRadar(radarSvg, currentJournalAuditData.proximity_radar, currentJournalAuditData);
  }
}

function removeJournalFromRadarComparison(index) {
  if (index >= 0 && index < radarComparedJournals.length) {
    radarComparedJournals.splice(index, 1);
    const radarSvg = document.getElementById("scivis-radar-svg");
    if (radarSvg && currentJournalAuditData) {
      renderProximityRadar(radarSvg, currentJournalAuditData.proximity_radar, currentJournalAuditData);
    }
  }
}

let currentHomePersona = "researcher";
let currentJournalAuditData = null;

function renderJournalAuditResults(data) {
  if (!currentJournalAuditData || currentJournalAuditData.journal_title !== data.journal_title) {
    radarComparedJournals = [];
  }
  currentJournalAuditData = data;
  const panel = document.getElementById("home-journal-audit-panel");
  const loading = document.getElementById("journal-audit-loading");
  const results = document.getElementById("journal-audit-results");
  if (!panel || !results) return;

  panel.hidden = false;
  panel.style.display = "block";
  if (loading) {
    loading.hidden = true;
    loading.style.display = "none";
  }
  results.hidden = false;
  results.style.display = "block";

  const cc = data.common_crawl || {};
  const local = data.local_stats || {};
  const isVerified = Boolean(cc.verified && cc.sample_captures_count > 0);

  // Cabecera
  const titleEl = document.getElementById("scivis-journal-title");
  const metaEl = document.getElementById("scivis-journal-meta");
  const notesEl = document.getElementById("scivis-journal-notes");
  const diagBadge = document.getElementById("scivis-diagnostic-badge");
  const statusIcon = document.getElementById("scivis-status-icon");
  const liveStatusLbl = document.getElementById("scivis-live-status-lbl");
  const collTag = document.getElementById("scivis-collection-id");

  if (titleEl) {
    titleEl.textContent = data.journal_title || data.query;
  }
  if (metaEl) {
    const resLabels = {
      domain_direct: "dominio directo",
      curated_registry: "registro curado",
      catalog_url: "catálogo local",
      fuzzy_catalog: "coincidencia aproximada",
      openalex_homepage: "OpenAlex",
      none: "sin resolver",
    };
    const resTxt = data.domain_resolution ? resLabels[data.domain_resolution] || data.domain_resolution : "";
    let metaText = `ISSN: ${data.issn || "N/D"} • Dominio: ${data.domain || "N/D"} • Área: ${data.category || "General"}`;
    if (resTxt) metaText += ` • Resolución: ${resTxt}`;
    if (data.shared_host) metaText += ` • ⚠ Portal compartido (métrica del host)`;
    const attr = data.harmonic_centrality?.attribution;
    if (attr && attr.level === "escalated" && attr.matched) {
      metaText += ` • ⚠ Métrica de '${attr.matched}' (PLD de Common Crawl)`;
    }
    try {
      const src = document.querySelector('script[src*="app.js"]')?.src || "";
      const m = src.match(/v=([\d.]+)/);
      if (m) metaText += `  ·  UI v${m[1]}`;
    } catch (e) { /* no-op */ }
    metaEl.textContent = metaText;
  }
  if (notesEl && data.ambiguous) {
    const cands = (data.ambiguous_matches || []).slice(0, 6).join(" | ");
    notesEl.textContent = `⚠ Consulta ambigua: existen varias revistas con título similar (${cands}). Para mayor precisión, busque por ISSN o por dominio web.`;
  }
  if (notesEl) {
    if (cc.note) {
      notesEl.textContent = cc.note;
    } else if (isVerified) {
      notesEl.textContent = `Dominio verificado en la colección activa de Common Crawl (${cc.collection_name || cc.collection}).`;
    } else {
      notesEl.textContent = cc.error || "No se detectaron capturas en la colección activa consultada de Common Crawl.";
    }
  }

  if (diagBadge) {
    if (isVerified) {
      diagBadge.className = "badge badge-primary";
      diagBadge.textContent = "Indexado en Common Crawl";
    } else if (local.has_local_records) {
      diagBadge.className = "badge badge-neutral";
      diagBadge.textContent = "Catálogo Local";
    } else {
      diagBadge.className = "badge badge-warning";
      diagBadge.textContent = "Sin Registros Activos";
    }
  }

  if (statusIcon) {
    statusIcon.textContent = isVerified ? "verified" : "info";
    statusIcon.style.color = isVerified ? "var(--brand-teal)" : "var(--outline)";
  }
  if (liveStatusLbl) {
    liveStatusLbl.textContent = isVerified ? "CRAWLER VERIFICADO" : "SIN CAPTURAS EN COLECCIÓN";
    liveStatusLbl.style.color = isVerified ? "var(--brand-teal)" : "var(--outline)";
  }
  if (collTag) {
    collTag.textContent = cc.collection || "CC-MAIN";
  }

  // Nota Metodológica
  const methodEl = document.getElementById("scivis-methodology-text");
  if (methodEl && data.methodology_note) {
    methodEl.textContent = data.methodology_note;
  }

  // Centralidad Armónica y PageRank oficiales de Common Crawl
  const harm = data.harmonic_centrality || {};
  const harmonicVal = document.getElementById("scivis-harmonic-val");
  const harmonicSub = document.getElementById("scivis-harmonic-sub");
  const pagerankVal = document.getElementById("scivis-pagerank-val");
  const pagerankSub = document.getElementById("scivis-pagerank-sub");

  if (harmonicVal) {
    if (harm.available && harm.harmonic_val != null) {
      harmonicVal.textContent = Number(harm.harmonic_val).toExponential(2);
    } else {
      harmonicVal.textContent = harm.status && harm.status.includes("Descargando") ? "En ingesta" : "No indizado";
    }
  }
  if (harmonicSub) {
    if (harm.available && harm.harmonic_rank != null) {
      harmonicSub.textContent = `Rank #${Number(harm.harmonic_rank).toLocaleString()} en la Web`;
    } else {
      harmonicSub.textContent = harm.status || "Web Graph oficial";
    }
  }

  if (pagerankVal) {
    if (harm.available && harm.pagerank_val != null) {
      pagerankVal.textContent = Number(harm.pagerank_val).toExponential(3);
    } else {
      pagerankVal.textContent = harm.status && harm.status.includes("Descargando") ? "En ingesta" : "No indizado";
    }
  }
  if (pagerankSub) {
    if (harm.available && harm.pagerank_rank != null) {
      pagerankSub.textContent = `Rank #${Number(harm.pagerank_rank).toLocaleString()} global`;
    } else {
      pagerankSub.textContent = harm.available ? "PageRank oficial" : "Web Graph oficial";
    }
  }

  // Diagnóstico Conversacional del Grafo Web (Harmonic Centrality & PageRank)
  const analysis = data.web_graph_analysis || (harm && harm.analysis) || null;
  const analysisCard = document.getElementById("scivis-conversational-analysis-card");
  const analysisTitle = document.getElementById("scivis-analysis-title");
  const analysisTier = document.getElementById("scivis-analysis-tier");
  const analysisHeadline = document.getElementById("scivis-analysis-headline");
  const analysisParagraphs = document.getElementById("scivis-analysis-paragraphs");
  const itemHarmRank = document.getElementById("scivis-item-harm-rank");
  const itemHarmVal = document.getElementById("scivis-item-harm-val");
  const itemPrRank = document.getElementById("scivis-item-pr-rank");

  if (analysisCard) {
    if (analysis) {
      analysisCard.style.display = "block";
      if (analysisTitle) analysisTitle.textContent = `Diagnóstico de Visibilidad Web: ${data.journal_title || 'Revista'}`;
      if (analysisTier) {
        analysisTier.textContent = analysis.tier_label || "Evaluación Cibermétrica";
        analysisTier.style.display = "inline-block";
      }
      if (analysisHeadline) analysisHeadline.textContent = analysis.headline || "";
      if (analysisParagraphs) {
        analysisParagraphs.innerHTML = "";
        const paras = analysis.summary_paragraphs || [];
        paras.forEach(p => {
          const pEl = document.createElement("p");
          pEl.style.margin = "0";
          pEl.textContent = p;
          analysisParagraphs.appendChild(pEl);
        });
      }
      const items = analysis.items_explanation || {};
      if (itemHarmRank) itemHarmRank.textContent = items.harmonic_rank || "--";
      if (itemHarmVal) itemHarmVal.textContent = items.harmonic_val || "--";
      if (itemPrRank) itemPrRank.textContent = items.pagerank_rank || "--";
    } else {
      analysisCard.style.display = "none";
    }
  }

  // Radar de Proximidad en la Web Abierta (Common Crawl) & In-Out Open Science Audit
  const inOut = data.in_out_audit;
  const radarCard = document.getElementById("scivis-radar-proximity-card");
  const inOutCard = document.getElementById("scivis-in-out-card");
  const ctaCard = document.getElementById("scivis-cta-card");

  // 1. Radar de Proximidad en el Web Graph
  if (radarCard) {
    radarCard.style.display = "block";
    const radarSvg = document.getElementById("scivis-radar-svg");
    const radarData = data.proximity_radar || (inOut && inOut.proximity_radar) || null;
    renderProximityRadar(radarSvg, radarData, data);
  }

  if (inOut) {

    // 2. In-Links vs Out-Links
    if (inOutCard) {
      inOutCard.style.display = "block";
      const badgeEl = document.getElementById("scivis-health-badge");
      if (badgeEl) badgeEl.textContent = inOut.health_badge || "Diagnóstico Hipertextual";

      const inWikiCount = document.getElementById("scivis-in-wiki-count");
      const wikiCount = inOut.in_links?.wikipedia_count || 0;
      const blogsList = inOut.in_links?.blogs?.mentions || [];
      const blogsCount = inOut.in_links?.blogs?.count || blogsList.length || 0;
      const ccRef = inOut.in_links?.referrers || {};
      const ccList = ccRef.referrers || [];
      const ccAttribution = ccRef.attribution || {};
      const twins = inOut.in_links?.web_twins || {};
      const twNeighbors = twins.neighbors || [];
      const twGap = twins.link_gap || [];

      if (inWikiCount) {
        const ccNote = ccList.length ? ` · ${ccList.length} dominios enlazan (Web Graph)` : "";
        if (wikiCount > 0 && blogsCount > 0) {
          inWikiCount.textContent = `${wikiCount} Wikipedia · ${blogsCount} Redes/Transmedia${ccNote}`;
        } else if (blogsCount > 0) {
          inWikiCount.textContent = `${blogsCount} Redes / Transmedia (0 en Wikipedia)${ccNote}`;
        } else if (ccList.length) {
          inWikiCount.textContent = `${ccList.length} dominios enlazan (Web Graph CC)`;
        } else {
          inWikiCount.textContent = `${wikiCount} en Wikipedia`;
        }
      }

      const inLinksList = document.getElementById("scivis-in-links-list");
      const wikiNoteEl = document.getElementById("scivis-wiki-note");
      if (wikiNoteEl) {
        const wn = inOut.in_links?.wikipedia_note || "";
        if (wn) {
          wikiNoteEl.textContent = wn;
          wikiNoteEl.style.display = "block";
        } else {
          wikiNoteEl.style.display = "none";
        }
      }
      if (inLinksList) {
        inLinksList.innerHTML = "";
        const wikiArticles = inOut.in_links?.wikipedia_sample || [];

        if (wikiArticles.length === 0 && blogsList.length === 0 && ccList.length === 0) {
          inLinksList.innerHTML = `<div style="font-size: 0.82rem; color: var(--on-surface-variant); font-style: italic;">No se detectaron citas directas a esta revista en Wikipedia ni canales de divulgación transmedia asociados. Oportunidad para divulgación UCC+I.</div>`;
        } else {
          // 0. Who-links: referring domains desde el Web Graph real de Common Crawl
          if (ccList.length > 0) {
            const header = document.createElement("div");
            header.style.cssText = "font-size: 0.72rem; font-weight: 700; color: var(--brand-teal); text-transform: uppercase; letter-spacing: 0.04em; margin: 2px 0 6px;";
            const escNote = ccAttribution.level === "escalated"
              ? ` — atribuido a '${escapeHtml(ccAttribution.matched || "")}' (portal/ancestro compartido)`
              : "";
            header.textContent = `Quién enlaza (Web Graph Common Crawl · release ${escapeHtml(ccList[0].release || "")})${ccAttribution.level === "escalated" ? escNote : ""}`;
            inLinksList.appendChild(header);
            ccList.forEach(r => {
              const row = document.createElement("div");
              row.style.cssText = "display: flex; align-items: center; justify-content: space-between; gap: 8px; background: rgba(255,255,255,0.75); padding: 5px 8px; border-radius: 6px; font-size: 0.82rem; margin-bottom: 4px;";
              row.innerHTML = `
                <div style="display: flex; align-items: center; gap: 6px; overflow: hidden;">
                  <span class="material-symbols-outlined text-[15px]" style="color: var(--brand-teal);">link</span>
                  <a href="https://${escapeHtml(r.domain)}/" target="_blank" rel="noopener noreferrer" style="font-weight: 600; color: var(--brand-teal); text-decoration: underline dotted; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="Abrir ${escapeHtml(r.domain)}">${escapeHtml(r.domain)}</a>
                </div>
                <span style="font-size: 0.74rem; color: var(--on-surface-variant); white-space: nowrap;">${Number(r.links || 0).toLocaleString("es")} enlaces</span>
              `;
              inLinksList.appendChild(row);
            });
          }

          // 1. Canales de Substack / LinkedIn / Blogs de divulgación
          blogsList.forEach(blog => {
            const isLinkedIn = blog.platform === "LinkedIn";
            const brandColor = isLinkedIn ? "#0A66C2" : "#FF6600";
            const linkColor = isLinkedIn ? "#004182" : "#D84315";
            const bgLight = isLinkedIn ? "rgba(10, 102, 194, 0.08)" : "rgba(255, 107, 0, 0.08)";
            const borderLight = isLinkedIn ? "rgba(10, 102, 194, 0.25)" : "rgba(255, 107, 0, 0.25)";

            const row = document.createElement("div");
            row.style.cssText = `display: flex; flex-direction: column; gap: 4px; background: ${bgLight}; border: 1px solid ${borderLight}; padding: 8px 10px; border-radius: 6px; font-size: 0.82rem; margin-bottom: 6px;`;
            const posts = (blog.posts || []).slice(0, 3);
            const postsHtml = posts.map(p => `
              <li style="margin-bottom: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                <a href="${escapeHtml(p.url)}" target="_blank" rel="noopener noreferrer" style="color: ${linkColor}; text-decoration: underline;">${escapeHtml(p.title)}</a>
              </li>
            `).join("");

            row.innerHTML = `
              <div style="display: flex; align-items: center; justify-content: space-between; gap: 6px;">
                <div style="display: flex; align-items: center; gap: 6px; overflow: hidden;">
                  <span style="font-size: 0.68rem; font-weight: 700; background: ${brandColor}; color: white; padding: 1px 6px; border-radius: 4px; text-transform: uppercase;">${escapeHtml(blog.platform || "Canal")}</span>
                  <strong style="font-weight: 600; color: var(--on-surface); overflow: hidden; text-overflow: ellipsis;">${escapeHtml(blog.source || blog.title)}</strong>
                </div>
                <a href="${escapeHtml(blog.url)}" target="_blank" rel="noopener noreferrer" style="color: ${brandColor}; display: flex; align-items: center;" title="Abrir ${escapeHtml(blog.platform)}">
                  <span class="material-symbols-outlined text-[16px]">open_in_new</span>
                </a>
              </div>
              ${blog.description ? `<div style="font-size: 0.72rem; color: var(--on-surface-variant); line-height: 1.35; margin-top: 2px;">${escapeHtml(blog.description)}</div>` : ""}
              ${postsHtml ? `<div style="font-size: 0.72rem; font-weight: 700; margin-top: 5px; color: ${linkColor};">Notas recientes de divulgación (${posts.length}):</div><ul style="margin: 2px 0 0 16px; padding: 0; font-size: 0.72rem; line-height: 1.45;">${postsHtml}</ul>` : ""}
            `;
            inLinksList.appendChild(row);
          });

          // 2. Citas en Wikipedia
          wikiArticles.forEach(art => {
            const row = document.createElement("div");
            row.style.cssText = "display: flex; align-items: center; justify-content: space-between; gap: 8px; background: rgba(255,255,255,0.75); padding: 5px 8px; border-radius: 6px; font-size: 0.82rem; margin-bottom: 4px;";
            if (art.matched_url) row.title = art.matched_url;
            row.innerHTML = `
              <div style="display: flex; flex-direction: column; gap: 2px; overflow: hidden;">
                <div style="display: flex; align-items: center; gap: 6px; overflow: hidden;">
                  <span style="font-size: 0.68rem; font-weight: 700; background: var(--brand-teal); color: white; padding: 1px 5px; border-radius: 4px; text-transform: uppercase;">${escapeHtml(art.lang || "es")}</span>
                  <span style="font-weight: 600; color: var(--on-surface); overflow: hidden; text-overflow: ellipsis;">${escapeHtml(art.title)}</span>
                </div>
                ${art.matched_url ? `<div style="font-size: 0.68rem; color: var(--on-surface-variant, #404849); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"><a href="${escapeHtml(art.matched_url)}" target="_blank" rel="noopener noreferrer" style="color: var(--brand-teal);">${escapeHtml(art.matched_url)}</a></div>` : ""}
              </div>
              <a href="${escapeHtml(art.url)}" target="_blank" rel="noopener noreferrer" style="color: var(--brand-teal); display: flex; align-items: center;" title="Ver en Wikipedia">
                <span class="material-symbols-outlined text-[15px]">open_in_new</span>
              </a>
            `;
            inLinksList.appendChild(row);
          });
        }
      }

      const outTotalCount = document.getElementById("scivis-out-total-count");
      const totalRaw = inOut.out_links?.total_extracted || inOut.out_links?.total_external || 0;
      const totalClassified = inOut.out_links?.total_classified ?? 0;
      if (outTotalCount) {
        if (totalClassified > 0) {
          outTotalCount.textContent = `${totalClassified} de Ciencia Abierta (${totalRaw} en portada)`;
        } else {
          outTotalCount.textContent = `${totalRaw} enlaces detectados`;
        }
      }

      const outCatList = document.getElementById("scivis-out-categories-list");
      if (outCatList) {
        outCatList.innerHTML = "";
        const cats = inOut.out_links?.categories || {};
        const catKeys = Object.keys(cats);
        if (catKeys.length === 0) {
          outCatList.innerHTML = `<div style="font-size: 0.82rem; color: var(--on-surface-variant); font-style: italic;">Sin enlaces externos abiertos detectados en la portada examinada.</div>`;
        } else {
          catKeys.forEach(k => {
            const cat = cats[k];
            const isOther = k === "other_links";
            const catRow = document.createElement("div");
            catRow.style.cssText = isOther 
              ? "background: rgba(255,255,255,0.55); border: 1px dashed rgba(97,145,150,0.35); border-radius: 6px; padding: 6px 10px;"
              : "background: rgba(255,255,255,0.75); border-radius: 6px; padding: 6px 10px;";
            catRow.innerHTML = `
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
                <strong style="font-size: 0.82rem; color: ${isOther ? "var(--on-surface, #2D3748)" : "var(--brand-teal-darker, #336368)"};">${escapeHtml(cat.label)}</strong>
                <span style="font-size: 0.75rem; font-weight: 700; background: ${isOther ? "rgba(0,0,0,0.06)" : "rgba(97,145,150,0.18)"}; padding: 1px 6px; border-radius: 10px; color: ${isOther ? "var(--on-surface-variant)" : "var(--brand-teal-darker)"};">${cat.count} enlaces</span>
              </div>
              ${cat.sample ? `<div style="font-size: 0.74rem; color: var(--on-surface-variant); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">Ejemplo: <a href="${escapeHtml(cat.sample)}" target="_blank" rel="noopener noreferrer" style="color: var(--brand-teal);">${escapeHtml(cat.sample)}</a></div>` : ""}
            `;
            outCatList.appendChild(catRow);
          });
        }
      }

      // Cajón interactivo de inspección de todos los enlaces detectados
      const btnToggleDrawer = document.getElementById("btn-toggle-outlinks-detail");
      const drawerEl = document.getElementById("scivis-outlinks-drawer");
      const toggleText = document.getElementById("toggle-outlinks-btn-text");
      const allLinks = inOut.out_links?.all_links || [];

      if (btnToggleDrawer && drawerEl) {
        if (allLinks.length === 0) {
          btnToggleDrawer.style.display = "none";
          drawerEl.style.display = "none";
        } else {
          btnToggleDrawer.style.display = "flex";
          if (toggleText) toggleText.textContent = `Ver los ${allLinks.length} enlaces detectados en la portada ▾`;
          
          let drawerHtml = `<div style="font-weight:700; margin-bottom: 6px; color: var(--brand-teal-darker);">Lista de enlaces detectados por la sonda (${allLinks.length}):</div><ol style="margin: 0; padding-left: 18px; line-height: 1.55;">`;
          allLinks.forEach(url => {
            drawerHtml += `<li style="margin-bottom: 4px; word-break: break-all;"><a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" style="color: var(--brand-teal); text-decoration: underline;">${escapeHtml(url)}</a></li>`;
          });
          drawerHtml += `</ol>`;
          drawerEl.innerHTML = drawerHtml;

          btnToggleDrawer.onclick = () => {
            const isHidden = drawerEl.style.display === "none";
            drawerEl.style.display = isHidden ? "block" : "none";
            if (toggleText) {
              toggleText.textContent = isHidden
                ? `Ocultar lista de enlaces ▴`
                : `Ver los ${allLinks.length} enlaces detectados en la portada ▾`;
            }
          };
        }
      }

      // ---- Gemelos web + mapa de posición: sección ancha propia (fuera del scroll de in-links) ----
      const twinsSec = document.getElementById("scivis-twins-section");
      if (twinsSec) {
        const domFallback = (typeof currentJournalAuditData !== "undefined" && currentJournalAuditData && currentJournalAuditData.domain) || "";
        const searchHint = twins.map_search_host || twins.matched_host || ccAttribution.matched || domFallback;
        const mapUrl = twins.map_view_url || "https://commoncrawl-web-graph-embeddings.static.hf.space/";
        const knnUrl = twins.knn_space_url || "https://commoncrawl-web-graph-knn.hf.space/";
        twinsSec.style.display = "block";

        const noteEl = document.getElementById("scivis-twins-note");
        if (noteEl) {
          if (twins.available) {
            const escT = twins.attribution_level === "escalated" ? ` · tu host se resolvió a '${escapeHtml(twins.matched_host || "")}'` : "";
            noteEl.innerHTML = `Vecinos por <strong>patrón de enlaces</strong> (embedding CC de 128 dimensiones, release ${escapeHtml(twins.release || "")})${escT}. El emparejamiento es por dominio registrable, no por ruta de revista.`;
          } else {
            noteEl.textContent = `Gemelos aún no calculados para este dominio${twins.status ? ` (${String(twins.status).slice(0, 90)})` : ""} — el mapa de posición sí está disponible abajo.`;
          }
        }

        const nbEl = document.getElementById("scivis-twins-neighbors");
        if (nbEl) {
          nbEl.innerHTML = "";
          if (twNeighbors.length === 0) {
            nbEl.innerHTML = `<div style="font-size:0.75rem;color:var(--on-surface-variant);font-style:italic;">Sin vecindario en caché para este dominio.</div>`;
          }
          twNeighbors.forEach(n => {
            const row = document.createElement("div");
            const own = !!n.same_site;
            row.style.cssText = own
              ? "display: flex; align-items: center; justify-content: space-between; gap: 8px; background: rgba(0,0,0,0.03); padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; opacity: 0.62;"
              : "display: flex; align-items: center; justify-content: space-between; gap: 8px; background: rgba(255,255,255,0.8); padding: 4px 8px; border-radius: 6px; font-size: 0.8rem;";
            const anchor = (!own && n.anchor) ? '<span class="material-symbols-outlined text-[14px]" style="color:#2e7d32;" title="Ancla aspiracional: mayor PageRank que tu dominio">trending_up</span>' : "";
            const ownBadge = own ? '<span style="font-size:0.62rem;font-weight:700;background:rgba(0,0,0,0.08);color:#5f6368;padding:1px 6px;border-radius:4px;text-transform:uppercase;">tu propio sitio</span>' : "";
            row.innerHTML = `
              <a href="https://${escapeHtml(n.host)}/" target="_blank" rel="noopener noreferrer" style="font-weight:${own ? 400 : 600};color:${own ? '#5f6368' : 'var(--brand-teal)'};text-decoration:underline dotted;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${own ? 'Otra puerta de tu mismo dominio raíz: no es un par externo' : 'Abrir ' + escapeHtml(n.host)}">${escapeHtml(n.host)}</a>
              <span style="display:flex;align-items:center;gap:6px;white-space:nowrap;color:var(--on-surface-variant);font-size:0.72rem;">${anchor}${ownBadge}cos ${escapeHtml(String(n.cosine))}</span>
            `;
            nbEl.appendChild(row);
          });
        }

        const gpEl = document.getElementById("scivis-twins-gap");
        if (gpEl) {
          gpEl.innerHTML = "";
          if (twGap.length === 0) {
            gpEl.innerHTML = `<div style="font-size:0.75rem;color:var(--on-surface-variant);font-style:italic;">Sin brecha calculada (requiere gemelos e in-links de los vecinos).</div>`;
          }
          twGap.forEach(g => {
            const row = document.createElement("div");
            row.style.cssText = "display: flex; align-items: center; justify-content: space-between; gap: 8px; background: rgba(141,110,99,0.08); border: 1px solid rgba(141,110,99,0.22); padding: 4px 8px; border-radius: 6px; font-size: 0.8rem;";
            const claseTxt = g.clase === "indexacion" ? "indexación/infra" : (g.clase === "region" ? "tu región" : "");
            const badge = claseTxt ? `<span style="font-size:0.62rem;font-weight:700;background:rgba(0,77,64,0.1);color:#004d40;padding:1px 6px;border-radius:4px;text-transform:uppercase;margin-right:6px;">${escapeHtml(claseTxt)}</span>` : "";
            row.innerHTML = `
              <span style="display:flex;align-items:center;overflow:hidden;"><a href="https://${escapeHtml(g.domain)}/" target="_blank" rel="noopener noreferrer" style="font-weight:600;color:#6d4c41;text-decoration:underline dotted;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="Abrir ${escapeHtml(g.domain)}">${escapeHtml(g.domain)}</a></span>
              <span style="white-space:nowrap;color:#6d4c41;font-size:0.72rem;">${badge}enlaza a ${Number(g.twins_linked).toLocaleString("es")} de tus gemelos</span>
            `;
            gpEl.appendChild(row);
          });
          const hidden = Number(twins.link_gap_hidden_globales || 0);
          if (hidden > 0) {
            const hn = document.createElement("div");
            hn.style.cssText = "font-size:0.66rem;color:var(--on-surface-variant);font-style:italic;margin-top:5px;line-height:1.35;";
            hn.textContent = `+${hidden} hubs enlazan también a tus gemelos pero quedaron fuera (fuera de región y no son indexadores: en revistas académicas la similitud de enlaces mide a menudo plomería de indexación compartida, no audiencia).`;
            gpEl.appendChild(hn);
          }
        }

        const hintEl = document.getElementById("scivis-map-hint");
        if (hintEl) {
          hintEl.innerHTML = `
            Escribe en "Host" <strong>exactamente este nodo</strong>: <code>${escapeHtml(searchHint || "dominio")}</code> → Search. El panel de la izquierda usa ese mismo host, así que las dos listas coincidirán. Si escribes el dominio raíz (p. ej. sin el subdominio), el buscador resuelve a OTRO sitio (el www/institucional) y te dará otro vecindario: distinto punto del mapa, no contradicción.<br/>
            <strong>Glosario:</strong> <em>cos</em> = similitud del patrón de enlaces (0-1). <em>same site ✓</em> = el vecino es otra puerta de tu mismo edificio (mismo dominio raíz), no un par externo. <em>degree</em> = nº de enlaces con los que el sitio participa; el modelo solo cubre degree ≥ 8 (~19% de la web).<br/>
            <strong>Nota honesta:</strong> el mapa 2D (arriba a la derecha) es contexto global — su buscador solo indexa los 20.000 sitios más enlazados; para localizar revistas usa este kNN.
          `;
        }
        const mh = document.getElementById("scivis-map-holder");
        if (mh) {
          mh.innerHTML = `<iframe src="${escapeHtml(knnUrl)}" title="Explorador kNN del grafo web de Common Crawl (busca tu revista y sus vecinos)" style="width:100%;height:clamp(660px,80vh,960px);border:1px solid rgba(0,97,104,0.3);border-radius:8px;background:#fff;" loading="lazy"></iframe>`;
        }
      }

      const healthSum = document.getElementById("scivis-health-summary");
      if (healthSum) {
        const verdict = inOut.connectivity_health?.conclusion || "";
        healthSum.innerHTML = verdict
          ? `${escapeHtml(inOut.health_summary || "")}<br/><span style="font-weight:700; color:var(--on-surface, #111E20);">${escapeHtml(verdict)}</span>`
          : escapeHtml(inOut.health_summary || "");
      }

      const recoList = document.getElementById("scivis-recommendations-list");
      if (recoList) {
        recoList.innerHTML = "";
        (inOut.recommendations || []).forEach(r => {
          const li = document.createElement("li");
          li.style.marginBottom = "4px";
          li.textContent = r;
          recoList.appendChild(li);
        });
      }
    }

    // 3. CTA Consultoría UCC+I
    if (ctaCard && inOut.consultancy_cta) {
      ctaCard.style.display = "block";
      const cta = inOut.consultancy_cta;
      const ctaTitle = document.getElementById("scivis-cta-title");
      const ctaDesc = document.getElementById("scivis-cta-desc");
      const ctaBtn = document.getElementById("scivis-cta-btn");
      const ctaBtnTxt = document.getElementById("scivis-cta-btn-text");

      if (ctaTitle) ctaTitle.textContent = cta.title || "¿Desea escalar el impacto de su revista?";
      if (ctaDesc) ctaDesc.textContent = cta.description || "";
      if (ctaBtnTxt) ctaBtnTxt.textContent = cta.button_text || "Solicitar Asesoría Editorial UCC+I";
      if (ctaBtn) {
        const mailtoUrl = `mailto:${encodeURIComponent(cta.email_target || 'culturacientifica@thinkuy.org')}?subject=${encodeURIComponent(cta.email_subject || 'Acompañamiento Editorial UCC+I')}&body=${encodeURIComponent(cta.email_body || '')}`;
        ctaBtn.setAttribute("href", mailtoUrl);
      }
    }
  } else {
    if (inOutCard) inOutCard.style.display = "none";
    if (ctaCard) ctaCard.style.display = "none";
  }

  // Métricas de Common Crawl y Catálogo Local
  const ccCapturesVal = document.getElementById("scivis-cc-captures-val");
  const ccCollSub = document.getElementById("scivis-cc-coll-sub");
  const ccDateVal = document.getElementById("scivis-cc-date-val");
  const ccWarcSub = document.getElementById("scivis-cc-warc-sub");
  const articlesVal = document.getElementById("scivis-articles-val");
  const coverageSub = document.getElementById("scivis-coverage-sub");
  const citationsVal = document.getElementById("scivis-citations-val");

  if (ccCapturesVal) {
    ccCapturesVal.textContent = isVerified ? `${cc.sample_captures_count} URLs` : "0";
  }
  if (ccCollSub) {
    ccCollSub.textContent = cc.collection_name || "Índice oficial CDX";
  }
  if (ccDateVal) {
    ccDateVal.textContent = cc.latest_crawl_date || "N/D";
  }
  if (ccWarcSub) {
    ccWarcSub.textContent = isVerified ? "Última captura activa" : "Sin rastreo en este índice";
  }
  if (articlesVal) {
    articlesVal.textContent = Number(local.articles_count || 0).toLocaleString();
  }
  if (coverageSub) {
    coverageSub.textContent = local.years_coverage ? `Cobertura: ${local.years_coverage}` : "Artículos indizados";
  }
  if (citationsVal) {
    citationsVal.textContent = Number(local.total_citations || 0).toLocaleString();
  }

  // Muestra de URLs de Common Crawl
  const urlsCard = document.getElementById("scivis-urls-card");
  const urlsList = document.getElementById("scivis-sample-urls-list");
  if (urlsCard && urlsList) {
    urlsList.innerHTML = "";
    const urls = cc.sample_urls || [];
    if (urls.length > 0) {
      urlsCard.hidden = false;
      urlsCard.style.display = "block";
      urls.forEach(u => {
        const item = document.createElement("div");
        item.className = "cc-url-pill";
        item.innerHTML = `
          <span class="material-symbols-outlined text-[16px] text-brand-teal">link</span>
          <a href="${escapeHtml(u)}" target="_blank" rel="noopener noreferrer">${escapeHtml(u)}</a>
        `;
        urlsList.appendChild(item);
      });
    } else {
      urlsCard.hidden = true;
      urlsCard.style.display = "none";
    }
  }

  // Benchmarking: Revistas reales comparables
  const compList = document.getElementById("scivis-competitors-list");
  if (compList) {
    compList.innerHTML = "";
    const competitors = data.competitors || [];
    if (competitors.length === 0) {
      compList.innerHTML = `<p class="text-muted text-[13px]">Sin otras revistas registradas en el catálogo local.</p>`;
    } else {
      competitors.forEach((c, idx) => {
        const item = document.createElement("div");
        item.className = `competitor-item ${c.is_target ? "highlight-target" : ""}`;
        item.style.cursor = "pointer";
        item.title = `Clic para auditar ${c.journal_title}`;
        item.innerHTML = `
          <div class="competitor-info">
            <span class="competitor-title">${idx + 1}. ${escapeHtml(c.journal_title)} ${c.is_target ? '<span class="badge badge-primary text-[10px] ml-1">Actual</span>' : ""}</span>
            <span class="competitor-meta">ISSN: ${escapeHtml(c.issn || "N/D")} • ${c.articles_count} artículos indizados</span>
          </div>
          <div class="competitor-score">
            <span class="competitor-scivis-val">${c.total_citations}</span>
            <span class="competitor-scivis-lbl">citas</span>
          </div>
        `;
        item.addEventListener("click", () => {
          const input = document.getElementById("home-inquiry-input");
          if (input) {
            input.value = c.journal_title;
            const sendBtn = document.getElementById("btn-home-send");
            if (sendBtn) sendBtn.click();
          }
        });
        compList.appendChild(item);
      });
    }
  }

  // Mapeo Bibliométrico de Oportunidades Temáticas (OpenAlex Topics)
  const dominantWrap = document.getElementById("scivis-dominant-topics");
  const emergingWrap = document.getElementById("scivis-emerging-topics");
  const gapWrap = document.getElementById("scivis-gap-topics");
  const topics = data.topics || {};

  const handleTopicClick = (topicName) => {
    const input = document.getElementById("home-inquiry-input");
    if (input) {
      input.value = topicName;
      const sendBtn = document.getElementById("btn-home-send");
      if (sendBtn) sendBtn.click();
    }
    showNotification({
      title: "Tema en Monitoreo",
      message: `«${topicName}» fijado en tu radar de indagación.`,
      type: "success",
    });
  };

  if (dominantWrap) {
    dominantWrap.innerHTML = "";
    const domList = (topics.raw_consolidated && topics.raw_consolidated.length > 0) 
      ? topics.raw_consolidated 
      : (topics.dominant_topics || []);
    if (domList.length === 0) {
      dominantWrap.innerHTML = `<span class="text-muted text-[12px]">Sin temas consolidados identificados</span>`;
    } else {
      domList.forEach(item => {
        const name = typeof item === "object" ? item.name : item;
        const vel = typeof item === "object" ? `${item.velocity}x` : "";
        const tag = document.createElement("span");
        tag.className = "agenda-tag";
        tag.textContent = vel ? `${name} (${vel})` : name;
        tag.style.cursor = "pointer";
        tag.title = typeof item === "object" ? (item.interpretation || "Núcleo tradicional") : "Filtrar por este tema";
        tag.addEventListener("click", () => handleTopicClick(name));
        dominantWrap.appendChild(tag);
      });
    }
  }

  if (emergingWrap) {
    emergingWrap.innerHTML = "";
    const emList = (topics.raw_emerging && topics.raw_emerging.length > 0)
      ? topics.raw_emerging
      : (topics.emerging_topics || []);
    if (emList.length === 0) {
      emergingWrap.innerHTML = `<span class="text-muted text-[12px]">Sin tendencias emergentes con velocidad atípica (>1.4x)</span>`;
    } else {
      emList.forEach(item => {
        const name = typeof item === "object" ? item.name : item;
        const vel = typeof item === "object" ? `${item.velocity}x` : "";
        const tag = document.createElement("span");
        tag.className = "agenda-tag emerging";
        tag.textContent = vel ? `✦ ${name} (${vel})` : `✦ ${name}`;
        tag.style.cursor = "pointer";
        tag.title = typeof item === "object" ? (item.interpretation || "Oportunidad para Call for Papers") : "Oportunidad de frontera";
        tag.addEventListener("click", () => handleTopicClick(name));
        emergingWrap.appendChild(tag);
      });
    }
  }

  if (gapWrap) {
    gapWrap.innerHTML = "";
    const gapList = (topics.raw_gaps && topics.raw_gaps.length > 0)
      ? topics.raw_gaps
      : (topics.gap_topics || []);
    if (gapList.length === 0) {
      gapWrap.innerHTML = `<span class="text-muted text-[12px]">Sin vacíos editoriales extremos detectados</span>`;
    } else {
      gapList.forEach(item => {
        const name = typeof item === "object" ? item.name : item;
        const tag = document.createElement("span");
        tag.className = "agenda-tag gap";
        tag.textContent = `🔍 ${name}`;
        tag.style.cursor = "pointer";
        tag.title = typeof item === "object" ? (item.interpretation || "Vacío / Nicho de baja cobertura") : "Vacío editorial";
        tag.addEventListener("click", () => handleTopicClick(name));
        gapWrap.appendChild(tag);
      });
    }
  }

  // Editores y Revisores Sugeridos con ORCID verificado
  const editorsWrap = document.getElementById("scivis-editors-list");
  if (editorsWrap) {
    editorsWrap.innerHTML = "";
    const editors = data.suggested_editors || [];
    if (editors.length === 0) {
      editorsWrap.innerHTML = `<p class="text-muted text-[13px]">Sin investigadores registrados para este campo o tema.</p>`;
    } else {
      editors.forEach(ed => {
        const card = document.createElement("div");
        const samplePaper = ed.sample_work
          ? `«${ed.sample_work}»${ed.sample_year ? ` (${ed.sample_year})` : ""}`
          : ((ed.sample_papers && ed.sample_papers[0]) ? `«${ed.sample_papers[0]}»` : "");
        const hasOrcid = Boolean(ed.orcid);
        const orcidUrl = ed.orcid_url || (hasOrcid ? `https://orcid.org/${escapeHtml(ed.orcid)}` : "");

        card.innerHTML = `
          <div class="editor-header-row">
            <span class="editor-name">${escapeHtml(ed.name)}</span>
            ${hasOrcid ? `
              <a href="${esc(orcidUrl)}" target="_blank" rel="noopener" class="radar-orcid-badge" title="Ver perfil verificado en ORCID.org">
                ${escapeHtml(ed.orcid)} ↗
              </a>
            ` : `
              <span class="editor-role-badge">${escapeHtml(ed.role_suggestion || "Revisor Par")}</span>
            `}
          </div>

          ${ed.affiliation ? `
            <div class="editor-affiliation">
              <span class="material-symbols-outlined text-[15px] text-brand-teal">apartment</span>
              <span>${escapeHtml(ed.affiliation)}${ed.country && ed.country !== 'N/D' ? ` (${escapeHtml(ed.country)})` : ''}</span>
            </div>
          ` : ''}

          ${ed.specialty_topic ? `
            <div class="editor-specialty">
              <span>Especialidad: <strong>${escapeHtml(ed.specialty_topic)}</strong></span>
            </div>
          ` : ''}

          <div class="editor-meta-stats">
            <span><strong>${ed.works_count || ed.articles_count || 1}</strong> obras</span>
            <span><strong>${ed.citations ?? ed.cited_by_count ?? ed.total_citations ?? 0}</strong> citas</span>
            ${ed.h_index && ed.h_index !== 'N/D' ? `<span>H-Index: <strong>${escapeHtml(String(ed.h_index))}</strong></span>` : `<span>Último: <strong>${ed.recent_year || 2026}</strong></span>`}
          </div>

          ${samplePaper ? `<div class="editor-sample-paper">${escapeHtml(samplePaper)}</div>` : ""}

          <button class="btn btn-outline sm editor-invite-btn" type="button">
            <span class="material-symbols-outlined text-[15px]">mail</span>
            <span>Invitar a la Revista</span>
          </button>
        `;
        const inviteBtn = card.querySelector(".editor-invite-btn");
        if (inviteBtn) {
          inviteBtn.addEventListener("click", () => {
            openEditorialInviteModal(ed, data.journal_title || data.query, data.domain);
          });
        }
        editorsWrap.appendChild(card);
      });
    }
  }

  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function openEditorialInviteModal(ed, journalTitle, journalDomain) {
  const modal = document.getElementById("scivis-invite-modal");
  if (!modal) return;

  const authorNameEl = document.getElementById("invite-author-name");
  const authorOrcidEl = document.getElementById("invite-author-orcid");
  const authorAffilEl = document.getElementById("invite-author-affiliation");
  const authorSpecEl = document.getElementById("invite-author-specialty");
  const roleReviewerBtn = document.getElementById("invite-role-reviewer");
  const roleBoardBtn = document.getElementById("invite-role-board");
  const subjectInput = document.getElementById("invite-email-subject");
  const bodyTextarea = document.getElementById("invite-email-body");
  const mailtoBtn = document.getElementById("btn-mailto-invite");
  const copyBtn = document.getElementById("btn-copy-invite");
  const copyBtnText = document.getElementById("copy-btn-text");
  const closeBtn = document.getElementById("btn-close-invite-modal");
  const cancelBtn = document.getElementById("btn-cancel-invite");

  const name = ed.name || "Investigador/a";
  const jTitle = journalTitle || "nuestra revista científica";
  const jDomain = journalDomain && journalDomain !== "N/D" ? `https://${journalDomain}` : "";
  const specialty = ed.specialty_topic || "su disciplina científica";

  if (authorNameEl) authorNameEl.textContent = name;
  if (authorOrcidEl) {
    if (ed.orcid) {
      authorOrcidEl.style.display = "inline-flex";
      authorOrcidEl.href = ed.orcid_url || `https://orcid.org/${ed.orcid}`;
      authorOrcidEl.textContent = `${ed.orcid} ↗`;
    } else {
      authorOrcidEl.style.display = "none";
    }
  }
  if (authorAffilEl) {
    authorAffilEl.textContent = `🏛️ ${ed.affiliation || 'Institución académica no especificada'}${ed.country && ed.country !== 'N/D' ? ` (${ed.country})` : ''}`;
  }
  if (authorSpecEl) {
    authorSpecEl.textContent = `📚 Especialidad: ${specialty}`;
  }

  let currentRole = "reviewer"; // "reviewer" o "board"

  const workMention = ed.sample_work
    ? ` y en especial por su reciente contribución científica «${ed.sample_work}»${ed.sample_year ? ` (${ed.sample_year})` : ""}`
    : "";

  function updateLetterContent() {
    if (currentRole === "reviewer") {
      subjectInput.value = `Invitación formal como Revisor/a Par — ${jTitle}`;
      bodyTextarea.value = `Estimado/a Dr./Dra. ${name}:

En nombre del equipo editorial de ${jTitle}, nos ponemos en contacto con usted conociendo su destacada trayectoria y contribuciones en el área de ${specialty}${workMention}.

Nuestra revista se encuentra en proceso de evaluación de manuscritos vinculados a esta temática y nos honraría enormemente contar con su valiosa experiencia como revisor/a par (peer reviewer) para arbitrar artículos en este campo.

La revisión se realiza bajo el modelo [doble ciego / abierto] conforme a los estándares éticos de COPE (Committee on Publication Ethics). En caso de aceptar colaborar con nosotros, le haremos llegar el título, resumen y los plazos sugeridos antes de asignarle formalmente el manuscrito en nuestra plataforma editorial.

Agradecemos de antemano su tiempo y consideración a esta invitación, y celebramos su aporte al avance del conocimiento en nuestra comunidad académica.

Atentamente,

Equipo Editorial
${jTitle}${jDomain ? `\nPortal: ${jDomain}` : ""}`;
    } else {
      subjectInput.value = `Invitación al Comité Científico / Editorial — ${jTitle}`;
      bodyTextarea.value = `Estimado/a Dr./Dra. ${name}:

Nos dirigimos a usted en nombre de la Dirección y el Consejo Editorial de ${jTitle}. Conociendo su sólida trayectoria investigadora y el impacto de su producción en ${specialty}${workMention}, nos complace extenderle una cordial invitación para formar parte de nuestro Comité Científico Internacional / Consejo Asesor.

Como miembro del comité, su función consistirá en asesorar a la dirección editorial en la definición de frentes de investigación, orientar futuras convocatorias monográficas y avalar la calidad de los procesos de arbitraje en su área de especialidad.

Sería un gran honor contar con su prestigio y criterio académico para consolidar la proyección y el impacto de ${jTitle}.

Quedamos a su entera disposición para coordinar los detalles formales.

Muy cordialmente,

Dirección Editorial
${jTitle}${jDomain ? `\nPortal: ${jDomain}` : ""}`;
    }

    if (mailtoBtn) {
      mailtoBtn.href = `mailto:?subject=${encodeURIComponent(subjectInput.value)}&body=${encodeURIComponent(bodyTextarea.value)}`;
    }
  }

  if (roleReviewerBtn && roleBoardBtn) {
    roleReviewerBtn.onclick = () => {
      currentRole = "reviewer";
      roleReviewerBtn.className = "btn btn-primary sm";
      roleBoardBtn.className = "btn btn-outline sm";
      updateLetterContent();
    };
    roleBoardBtn.onclick = () => {
      currentRole = "board";
      roleBoardBtn.className = "btn btn-primary sm";
      roleReviewerBtn.className = "btn btn-outline sm";
      updateLetterContent();
    };
  }

  if (subjectInput && bodyTextarea && mailtoBtn) {
    const refreshMailto = () => {
      mailtoBtn.href = `mailto:?subject=${encodeURIComponent(subjectInput.value)}&body=${encodeURIComponent(bodyTextarea.value)}`;
    };
    subjectInput.oninput = refreshMailto;
    bodyTextarea.oninput = refreshMailto;
  }

  if (copyBtn) {
    copyBtn.onclick = async () => {
      try {
        await navigator.clipboard.writeText(bodyTextarea.value);
        if (copyBtnText) copyBtnText.textContent = "¡Copiada al portapapeles!";
        copyBtn.classList.remove("btn-outline");
        copyBtn.classList.add("btn-primary");
        setTimeout(() => {
          if (copyBtnText) copyBtnText.textContent = "Copiar Carta";
          copyBtn.classList.remove("btn-primary");
          copyBtn.classList.add("btn-outline");
        }, 2200);
      } catch (err) {
        bodyTextarea.select();
        document.execCommand("copy");
      }
    };
  }

  const closeModal = () => {
    modal.hidden = true;
    modal.style.display = "none";
  };

  if (closeBtn) closeBtn.onclick = closeModal;
  if (cancelBtn) cancelBtn.onclick = closeModal;
  modal.onclick = (e) => {
    if (e.target === modal) closeModal();
  };

  updateLetterContent();
  modal.hidden = false;
  modal.style.display = "flex";
}

function initHomeInquiry() {
  const inquiryInput = document.getElementById("home-inquiry-input");
  const sendBtn = document.getElementById("btn-home-send");
  const deepBtn = document.getElementById("deep-research-toggle");
  const subText = document.getElementById("home-hero-subtitle-text");

  // Paneles
  const libPanel = document.getElementById("home-librarian-panel");
  const libLoading = document.getElementById("librarian-loading");
  const libResults = document.getElementById("librarian-results");

  const journalPanel = document.getElementById("home-journal-audit-panel");
  const journalLoading = document.getElementById("journal-audit-loading");
  const journalResults = document.getElementById("journal-audit-results");
  let lastJournalAuditQuery = "";

  document.getElementById("scivis-force-refresh")?.addEventListener("click", async () => {
    const q = (inquiryInput && inquiryInput.value.trim()) || lastJournalAuditQuery;
    if (!q || !journalPanel) return;
    const btn = document.getElementById("scivis-force-refresh");
    if (btn) { btn.disabled = true; btn.style.opacity = "0.6"; }
    if (journalLoading) { journalLoading.hidden = false; journalLoading.style.display = "flex"; }
    if (journalResults) { journalResults.hidden = true; journalResults.style.display = "none"; }
    try {
      const auditData = await api("/scivis/audit", { query: q, refresh: 1 });
      lastJournalAuditQuery = q;
      renderJournalAuditResults(auditData);
      showNotification({ title: "Medición actualizada", message: `Nueva medición en vivo para «${q}» (caché ignorada).`, type: "success" });
    } catch (err) {
      showNotification({ title: "Error en Auditoría Editorial", message: err.message || String(err), type: "error" });
    } finally {
      if (journalLoading) { journalLoading.hidden = true; journalLoading.style.display = "none"; }
      if (btn) { btn.disabled = false; btn.style.opacity = "1"; }
    }
  });

  // Tabs Persona
  const tabResearcher = document.getElementById("tab-persona-researcher");
  const tabJournal = document.getElementById("tab-persona-journal");

  const setPersona = (persona) => {
    currentHomePersona = persona;
    if (persona === "researcher") {
      if (tabResearcher) {
        tabResearcher.classList.add("active");
        tabResearcher.setAttribute("aria-selected", "true");
      }
      if (tabJournal) {
        tabJournal.classList.remove("active");
        tabJournal.setAttribute("aria-selected", "false");
      }
      if (subText) {
        subText.textContent = "Monitoreamos papers para tu investigación basados en resúmenes revisados por pares, literatura completa y preprints de diferentes bases de datos.";
      }
      if (inquiryInput) {
        inquiryInput.placeholder = "¿Qué te gustaría saber más? Escribe tu pregunta, hipótesis, DOI o tema de estudio...";
      }
      if (journalPanel) {
        journalPanel.hidden = true;
        journalPanel.style.display = "none";
      }
    } else {
      if (tabJournal) {
        tabJournal.classList.add("active");
        tabJournal.setAttribute("aria-selected", "true");
      }
      if (tabResearcher) {
        tabResearcher.classList.remove("active");
        tabResearcher.setAttribute("aria-selected", "false");
      }
      if (subText) {
        subText.textContent = "Inteligencia editorial, posicionamiento temático, captación de editores/revisores y auditoría cibermétrica SCIVIS con datos de Common Crawl.";
      }
      if (inquiryInput) {
        inquiryInput.placeholder = "Pega la URL o el dominio (revistacomunicar.com), el nombre de la revista, ISSN o tema (ej. Revista Panamericana de Pedagogía, 1665-0557, educación digital)...";
      }
      if (libPanel) {
        libPanel.hidden = true;
        libPanel.style.display = "none";
      }
    }
  };

  if (tabResearcher) {
    tabResearcher.addEventListener("click", () => setPersona("researcher"));
  }
  if (tabJournal) {
    tabJournal.addEventListener("click", () => setPersona("journal"));
  }

  if (deepBtn) {
    deepBtn.addEventListener("click", () => {
      deepBtn.classList.toggle("active");
    });
  }

  const submitQuery = async () => {
    const q = inquiryInput ? inquiryInput.value.trim() : "";
    if (!q) {
      if (inquiryInput) inquiryInput.focus();
      return;
    }

    if (sendBtn) {
      sendBtn.disabled = true;
      sendBtn.style.opacity = "0.6";
    }

    if (currentHomePersona === "journal") {
      // Flujo de Modo Revista / Editorial: SCIVIS
      if (libPanel) {
        libPanel.hidden = true;
        libPanel.style.display = "none";
      }
      if (journalPanel) {
        journalPanel.hidden = false;
        journalPanel.style.display = "block";
        if (journalLoading) {
          journalLoading.hidden = false;
          journalLoading.style.display = "flex";
        }
        if (journalResults) {
          journalResults.hidden = true;
          journalResults.style.display = "none";
        }
        journalPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }

      try {
        const auditData = await api("/scivis/audit", { query: q });
        lastJournalAuditQuery = q;
        renderJournalAuditResults(auditData);
      } catch (err) {
        console.error("SCIVIS audit error:", err);
        if (journalResults) {
          journalResults.hidden = true;
          journalResults.style.display = "none";
        }
        showNotification({
          title: "Error en Auditoría Editorial",
          message: `No se pudieron obtener datos para «${q}»: ${err.message || err}`,
          type: "error",
        });
      } finally {
        if (journalLoading) {
          journalLoading.hidden = true;
          journalLoading.style.display = "none";
        }
        if (sendBtn) {
          sendBtn.disabled = false;
          sendBtn.style.opacity = "1";
        }
      }
    } else {
      // Flujo de Modo Investigador: Bibliotecario Thinkuy
      if (journalPanel) {
        journalPanel.hidden = true;
        journalPanel.style.display = "none";
      }
      if (libPanel) {
        libPanel.hidden = false;
        libPanel.style.display = "block";
        if (libLoading) {
          libLoading.hidden = false;
          libLoading.style.display = "flex";
        }
        if (libResults) {
          libResults.hidden = true;
          libResults.style.display = "none";
        }
        libPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }

      try {
        const data = await api("/librarian/assist", {}, { method: "POST", body: { inquiry: q, limit: 36, source: "live" } });
        renderLibrarianResults(data);
      } catch (e) {
        console.warn("Librarian assist error, fallback to catalog:", e);
        renderLibrarianResults({
          inquiry: q,
          corrected: q,
          heard_as: `Ah, lo que usted busca es ${q}`,
          field: { name: "Catálogo General" },
          keywords: [q],
          explanation: "Hemos consultado el catálogo con los términos de su búsqueda para recuperar los artículos disponibles en el acervo.",
          articles: [],
          top_authors: [],
        });
      } finally {
        if (libLoading) {
          libLoading.hidden = true;
          libLoading.style.display = "none";
        }
        if (sendBtn) {
          sendBtn.disabled = false;
          sendBtn.style.opacity = "1";
        }
      }
    }
  };

  if (sendBtn) sendBtn.addEventListener("click", submitQuery);
  if (inquiryInput) {
    inquiryInput.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submitQuery();
      }
    });
  }

  // Acciones del panel del bibliotecario
  const exploreBtn = document.getElementById("btn-librarian-explore");
  const viewAllBtn = document.getElementById("btn-librarian-view-all");
  const radarBtn = document.getElementById("btn-librarian-radar");
  const pinBtn = document.getElementById("btn-librarian-pin");

  const goToExplorer = () => {
    if (!currentLibrarianData) return;
    const kwInput = document.getElementById("keywords");
    if (kwInput) {
      kwInput.value = (currentLibrarianData.keywords || [currentLibrarianData.corrected || currentLibrarianData.inquiry]).join(", ");
    }
    state.config.days = 3650;
    state.config.limit = 35;
    const daysEl = document.getElementById("days");
    if (daysEl) daysEl.value = "3650";
    const limitEl = document.getElementById("limit");
    if (limitEl) limitEl.value = "35";
    readForm();
    switchView("explorer");
    renderFeed();
    refreshSuggest();
  };

  if (exploreBtn) exploreBtn.addEventListener("click", goToExplorer);
  if (viewAllBtn) viewAllBtn.addEventListener("click", goToExplorer);

  if (radarBtn) {
    radarBtn.addEventListener("click", () => {
      if (!currentLibrarianData) return;
      const radarTopic = document.getElementById("radar-topic");
      if (radarTopic) {
        radarTopic.value = currentLibrarianData.corrected || currentLibrarianData.inquiry;
      }
      switchView("radar");
      const radarOrbitBtn = document.getElementById("btn-radar");
      if (radarOrbitBtn) radarOrbitBtn.click();
    });
  }

  if (pinBtn) {
    pinBtn.addEventListener("click", async () => {
      if (!currentLibrarianData) return;
      pinBtn.disabled = true;
      pinBtn.textContent = "Anclando…";
      try {
        const kws = (currentLibrarianData.keywords || [currentLibrarianData.corrected || currentLibrarianData.inquiry]).join(", ");
        const label = currentLibrarianData.heard_as || currentLibrarianData.inquiry;
        await api("/watch", {}, {
          method: "POST",
          body: { keywords: kws, label: label }
        });
        pinBtn.innerHTML = `<span class="material-symbols-outlined text-[16px]">check</span> Vigilancia anclada`;
        pinBtn.classList.add("btn-primary");
        pinBtn.classList.remove("btn-outline");
        if (typeof loadWatch === "function") await loadWatch();
      } catch (e) {
        showNotification({ title: "Error al anclar vigilancia", message: e.message, type: "error" });
        pinBtn.disabled = false;
        pinBtn.innerHTML = `<span class="material-symbols-outlined text-[18px]">bookmark_add</span> <span>Anclar Vigilancia</span>`;
      }
    });
  }
}

/* ---------------- método socrático ---------------- */
let currentSocraticData = null;
let currentConcertedData = null;

function initSocratic() {
  const modal = document.getElementById("socratic-modal");
  const openTopBtn = document.getElementById("btn-open-socratic-top");
  const openSidebarBtn = document.getElementById("btn-open-socratic-sidebar");
  const openOldBtn = document.getElementById("btn-open-socratic");
  const closeBtn = document.getElementById("btn-close-socratic");
  const analyzeBtn = document.getElementById("btn-socratic-analyze");
  const backBtn = document.getElementById("btn-socratic-back");
  const concertBtn = document.getElementById("btn-socratic-concert");
  const pinBtn = document.getElementById("btn-socratic-pin");
  const applyBtn = document.getElementById("btn-socratic-apply");

  if (!modal) return;

  const closeModal = () => {
    modal.hidden = true;
    modal.style.display = "none";
  };

  const openModal = () => {
    modal.hidden = false;
    modal.style.display = "flex";
    document.getElementById("socratic-step-1").hidden = false;
    document.getElementById("socratic-step-2").hidden = true;
    document.getElementById("socratic-step-3").hidden = true;
    document.getElementById("socratic-input").focus();
  };

  if (openTopBtn) openTopBtn.addEventListener("click", openModal);
  if (openSidebarBtn) openSidebarBtn.addEventListener("click", openModal);
  if (openOldBtn) openOldBtn.addEventListener("click", openModal);
  if (closeBtn) closeBtn.addEventListener("click", closeModal);

  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) closeModal();
  });

  if (analyzeBtn) {
    analyzeBtn.addEventListener("click", async () => {
      const inquiry = document.getElementById("socratic-input").value.trim();
      if (!inquiry) return;
      analyzeBtn.disabled = true;
      analyzeBtn.textContent = "Analizando con método socrático…";
      try {
        currentSocraticData = await api("/socratic/analyze", {}, { method: "POST", body: { inquiry } });
        // Si la inquietud es trivial ("hola"), el backend pide precisar sin inventar campo.
        if (currentSocraticData && currentSocraticData.status === "need_clarification") {
          showNotification({ title: "Análisis socrático", message: currentSocraticData.message || "Cuéntame un poco más para ubicarte en el campo correcto.", type: "info" });
          const dens = currentSocraticData.literature_density || {};
          document.getElementById("socratic-density").textContent = `Catálogo: ${dens.articles_found || 0} artículos en ${dens.journals_covered || 0} revistas. Precisa tu tema para continuar.`;
          document.getElementById("socratic-step-1").hidden = false;
          document.getElementById("socratic-step-2").hidden = true;
          return;
        }
        document.getElementById("socratic-field-badge").textContent = `Campo: ${currentSocraticData.primary_field.name}`;
        document.getElementById("socratic-epistemic").textContent = currentSocraticData.epistemic_reflection;
        
        const qList = document.getElementById("socratic-questions-list");
        qList.innerHTML = currentSocraticData.socratic_questions.map((q, idx) => `
          <div style="font-size: 13px; padding: 6px 10px; background: #FFFFFF; border-radius: var(--radius-sm); border: 1px solid rgba(192, 200, 201, 0.4);">
            <b>${idx + 1}.</b> ${esc(q)}
          </div>
        `).join("");

        document.getElementById("socratic-density").textContent = `Densidad en catálogo: ${(currentSocraticData.literature_density || {}).articles_found || 0} artículos en ${(currentSocraticData.literature_density || {}).journals_covered || 0} revistas.`;
        document.getElementById("socratic-step-1").hidden = true;
        document.getElementById("socratic-step-2").hidden = false;
        document.getElementById("socratic-reflection-input").focus();
      } catch (e) {
        showNotification({ title: "Error en el análisis", message: e.message, type: "error" });
      } finally {
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = "Comenzar Diálogo Socrático";
      }
    });
  }

  if (backBtn) {
    backBtn.addEventListener("click", () => {
      document.getElementById("socratic-step-2").hidden = true;
      document.getElementById("socratic-step-1").hidden = false;
      document.getElementById("socratic-input").focus();
    });
  }

  if (concertBtn) {
    concertBtn.addEventListener("click", async () => {
      const reflection = document.getElementById("socratic-reflection-input").value.trim();
      concertBtn.disabled = true;
      concertBtn.textContent = "Concertando radar…";
      try {
        currentConcertedData = await api("/socratic/concert", {}, {
          method: "POST",
          body: {
            field_name: currentSocraticData.primary_field.name,
            original_inquiry: document.getElementById("socratic-input").value.trim(),
            user_reflection: reflection,
            suggested_keywords: currentSocraticData.suggested_keywords
          }
        });
        document.getElementById("socratic-result-title").textContent = currentConcertedData.label;
        document.getElementById("socratic-result-summary").textContent = currentConcertedData.summary;
        document.getElementById("socratic-result-kws").textContent = currentConcertedData.recommended_keywords;
        document.getElementById("socratic-result-journals").textContent = currentConcertedData.key_journals.join(" · ");
        document.getElementById("socratic-step-2").hidden = true;
        document.getElementById("socratic-step-3").hidden = false;
      } catch (e) {
        showNotification({ title: "Error al concertar", message: e.message, type: "error" });
      } finally {
        concertBtn.disabled = false;
        concertBtn.textContent = "Concertar mi Radar";
      }
    });
  }

  if (pinBtn) {
    pinBtn.addEventListener("click", async () => {
      if (!currentConcertedData) return;
      pinBtn.disabled = true;
      pinBtn.textContent = "Anclando…";
      try {
        await api("/watch", {}, {
          method: "POST",
          body: { keywords: currentConcertedData.recommended_keywords, label: currentConcertedData.label }
        });
        document.getElementById("keywords").value = currentConcertedData.recommended_keywords;
        readForm();
        closeModal();
        switchView("explorer");
        await Promise.all([loadWatch(), renderFeed()]);
      } catch (e) {
        showNotification({ title: "Error al anclar", message: e.message, type: "error" });
      } finally {
        pinBtn.disabled = false;
        pinBtn.textContent = "📌 Anclar y Activar este Radar";
      }
    });
  }

  if (applyBtn) {
    applyBtn.addEventListener("click", async () => {
      if (!currentConcertedData) return;
      applyBtn.disabled = true;
      applyBtn.textContent = "Cargando publicaciones…";
      try {
        document.getElementById("keywords").value = currentConcertedData.recommended_keywords;
        closeModal();
        readForm();
        switchView("explorer");
        await renderFeed();
      } catch (e) {
        showNotification({ title: "Error al cargar el feed", message: e.message, type: "error" });
      } finally {
        applyBtn.disabled = false;
        applyBtn.textContent = "Ver Publicaciones Ahora";
      }
    });
  }
}

/* ---------------- match científico (revistas & revisores) ---------------- */
async function loadRpcArticlesForMatch() {
  const selectJournal = document.getElementById("match-rpc-select");
  const selectReviewer = document.getElementById("match-reviewer-select");
  try {
    const data = await api("/anchors/articles");
    const opts = '<option value="">-- Elige un artículo del corpus o describe tu manuscrito al lado --</option>' +
      data.articles.map(a => `<option value="${a.id}">[${a.year || "corpus"}] ${esc(a.title.slice(0, 75))}… (${esc(a.authors_str.slice(0, 35))})</option>`).join("");
    if (selectJournal) selectJournal.innerHTML = opts;
    if (selectReviewer) selectReviewer.innerHTML = opts;
  } catch (e) { /* silencioso */ }
}

async function runJournalMatch() {
  const select = document.getElementById("match-rpc-select");
  const input = document.getElementById("match-journal-input");
  const grid = document.getElementById("match-journals-grid");
  if (!grid) return;
  const articleId = select ? select.value : "";
  const queryText = input ? input.value.trim() : "";

  if (!articleId && !queryText) {
    grid.innerHTML = `<div class="stat-box" style="grid-column: 1 / -1; text-align: center; padding: 30px;"><p style="color:var(--on-surface-variant)">Por favor selecciona un artículo del corpus o describe el tema de tu manuscrito.</p></div>`;
    return;
  }

  grid.innerHTML = '<div class="stat-box" style="grid-column: 1 / -1; text-align: center; padding: 40px;"><p>Calculando afinidad con revistas y CFPs del catálogo...</p></div>';

  try {
    const params = { limit: 9 };
    if (articleId) params.article_id = articleId;
    if (queryText) params.topic = queryText;

    const data = await api("/match/journals", params);
    if (!data.matches || !data.matches.length) {
      grid.innerHTML = `<div class="stat-box" style="grid-column: 1 / -1; text-align: center; padding: 30px;"><p style="color:var(--on-surface-variant)">No se encontraron revistas ni CFPs con suficiente afinidad para esta propuesta.</p></div>`;
      return;
    }

    grid.innerHTML = data.matches.map(m => {
      const isCfp = m.match_type === "cfp";
      const concepts = (m.shared_concepts || []).map(c => `<span class="badge badge-match">#${esc(c)}</span>`).join(" ");
      const articles = (m.sample_articles || []).map(a =>
        `<div style="font-size: 12px; margin-top: 4px;">
          📄 <a href="${a.doi ? 'https://doi.org/' + encodeURIComponent(a.doi) : '#'}" target="_blank" rel="noopener" style="color: var(--brand-teal-dark); font-weight: 500;">${esc(a.title || "")}</a>
          <span style="color: var(--on-surface-variant)"> (${a.year || ''})</span>
        </div>`
      ).join("");

      return `
      <div class="journal-card">
        <div class="journal-top">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">
            <div>
              <div class="journal-name">${esc(m.journal)}</div>
              ${m.country ? `<span class="journal-publisher">📍 ${esc(m.country)}</span>` : ""}
            </div>
            <span class="badge badge-match" style="font-size: 13px; font-weight: 700;">${m.fidelity}% Match</span>
          </div>

          ${isCfp ? `<div style="margin: 8px 0; padding: 6px 10px; background: var(--accent-amber-subtle); border-radius: var(--radius-sm); font-size: 12px; color: #92400e; font-weight: 600;">📢 CFP: «${esc(m.cfp_title || '')}» (Cierre: ${esc(m.cfp_deadline || 'Próximo')})</div>` : ""}

          <p style="font-size: 13px; color: var(--on-surface-variant); margin-top: 8px; line-height: 1.5;">${esc(m.rationale || "")}</p>
          
          <div style="display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0;">${concepts}</div>
          
          ${articles ? `<div style="margin-top: 10px; border-top: 1px dashed rgba(192, 200, 201, 0.4); padding-top: 8px;"><span style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--outline);">Papers afines en la revista:</span>${articles}</div>` : ""}
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(192, 200, 201, 0.3); padding-top: 12px; margin-top: 12px;">
          ${m.url ? `<a href="${esc(m.url)}" target="_blank" rel="noopener" class="btn btn-primary sm">🔗 Ver Convocatoria</a>` : "<span></span>"}
          <button class="btn btn-ghost sm" data-follow-journal="${esc(m.journal)}">📌 Seguir</button>
        </div>
      </div>`;
    }).join("");

    grid.querySelectorAll("[data-follow-journal]").forEach(btn => {
      btn.addEventListener("click", async () => {
        const jName = btn.dataset.followJournal;
        try {
          await api("/watch", {}, { method: "POST", body: { keywords: jName, label: `Revista: ${jName}` } });
          btn.textContent = "✔ Siguiendo";
          btn.disabled = true;
          loadWatch();
        } catch (e) {
          showNotification({ title: "No se pudo seguir la revista", message: e.message, type: "error" });
        }
      });
    });

  } catch (e) {
    grid.innerHTML = `<div class="stat-box" style="grid-column: 1 / -1; text-align: center; padding: 30px; color: var(--error);"><p>Error al calcular match: ${esc(e.message)}</p></div>`;
  }
}

async function runReviewerMatch() {
  const select = document.getElementById("match-reviewer-select");
  const input = document.getElementById("match-reviewer-input");
  const grid = document.getElementById("match-reviewers-grid");
  if (!grid) return;
  const articleId = select ? select.value : "";
  const queryText = input ? input.value.trim() : "";

  if (!articleId && !queryText) {
    grid.innerHTML = `<div class="stat-box" style="grid-column: 1 / -1; text-align: center; padding: 30px;"><p style="color:var(--on-surface-variant)">Por favor selecciona un artículo del corpus o introduce el tema del manuscrito.</p></div>`;
    return;
  }

  grid.innerHTML = '<div class="stat-box" style="grid-column: 1 / -1; text-align: center; padding: 40px;"><p>Buscando evaluadores y editores afines...</p></div>';

  try {
    const params = { limit: 9 };
    if (articleId) params.article_id = articleId;
    if (queryText) params.topic = queryText;

    const data = await api("/match/reviewers", params);
    if (!data.matches || !data.matches.length) {
      grid.innerHTML = `<div class="stat-box" style="grid-column: 1 / -1; text-align: center; padding: 30px;"><p style="color:var(--on-surface-variant)">No se encontraron evaluadores sin conflicto de interés en el catálogo para esta búsqueda.</p></div>`;
      return;
    }

    grid.innerHTML = data.matches.map(m => {
      const initials = (m.name || "A").split(" ").map(w => w[0]).slice(0, 2).join("");
      const concepts = (m.shared_concepts || []).map(c => `<span class="badge badge-match">#${esc(c)}</span>`).join(" ");
      const articles = (m.articles || []).map(a =>
        `<div style="font-size: 12px; margin-top: 4px;">
          📄 <a href="${a.doi ? 'https://doi.org/' + encodeURIComponent(a.doi) : '#'}" target="_blank" rel="noopener" style="color: var(--brand-teal-dark); font-weight: 500;">${esc(a.title || "")}</a>
          <span style="color: var(--on-surface-variant)"> · ${esc(a.journal || "")}${a.year ? ' (' + a.year + ')' : ''}</span>
        </div>`
      ).join("");

      return `
      <div class="reviewer-card">
        <div>
          <div class="reviewer-header">
            <div class="reviewer-avatar">${esc(initials)}</div>
            <div style="min-width: 0; flex: 1;">
              <div class="reviewer-name">${esc(m.name)}</div>
              <div class="reviewer-inst">${esc(m.journal || "Publicaciones en el campo")}</div>
              ${m.orcid ? `<a href="https://orcid.org/${esc(m.orcid)}" target="_blank" rel="noopener" class="data-tabular" style="font-size: 11px; color: var(--brand-teal-dark);">ORCID: ${esc(m.orcid)} ↗</a>` : ""}
            </div>
            <span class="badge badge-match" style="font-size: 13px; font-weight: 700;">${m.idoneity}% Idoneidad</span>
          </div>

          <div class="reviewer-affinity-bar">
            <div class="reviewer-affinity-fill" style="width: ${m.idoneity}%"></div>
          </div>

          <p style="font-size: 13px; color: var(--on-surface-variant); margin-top: 8px; line-height: 1.5;">${esc(m.rationale || "")}</p>
          
          <div style="display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0;">${concepts}</div>
          
          ${articles ? `<div style="margin-top: 10px; border-top: 1px dashed rgba(192, 200, 201, 0.4); padding-top: 8px;"><span style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--outline);">Publicaciones que avalan su pericia:</span>${articles}</div>` : ""}
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(192, 200, 201, 0.3); padding-top: 12px; margin-top: 12px;">
          <button class="btn btn-primary sm btn-copy-ojs" data-ojs-slip="${encodeURIComponent(m.ojs_slip || '')}">📋 Ficha OJS</button>
          <button class="btn btn-ghost sm" data-follow-author="${esc(m.name)}">📌 Seguir</button>
        </div>
      </div>`;
    }).join("");

    grid.querySelectorAll(".btn-copy-ojs").forEach(btn => {
      btn.addEventListener("click", async () => {
        const rawText = decodeURIComponent(btn.dataset.ojsSlip || "");
        if (!rawText) return;
        try {
          await navigator.clipboard.writeText(rawText);
          const originalText = btn.innerHTML;
          btn.innerHTML = "✔ ¡Copiada!";
          setTimeout(() => { btn.innerHTML = originalText; }, 2400);
        } catch (e) {
          prompt("Copia los datos del revisor para OJS:", rawText);
        }
      });
    });

    grid.querySelectorAll("[data-follow-author]").forEach(btn => {
      btn.addEventListener("click", async () => {
        const authorName = btn.dataset.followAuthor;
        try {
          await api("/watch", {}, { method: "POST", body: { keywords: authorName, label: `Evaluador/a: ${authorName}` } });
          btn.textContent = "✔ Siguiendo";
          btn.disabled = true;
          loadWatch();
        } catch (e) {
          showNotification({ title: "No se pudo seguir al autor", message: e.message, type: "error" });
        }
      });
    });

  } catch (e) {
    grid.innerHTML = `<div class="stat-box" style="grid-column: 1 / -1; text-align: center; padding: 30px; color: var(--error);"><p>Error al buscar revisores: ${esc(e.message)}</p></div>`;
  }
}

function initScientificMatch() {
  const btnJournals = document.getElementById("btn-find-journal-matches");
  const selectJournals = document.getElementById("match-rpc-select");
  const inputJournals = document.getElementById("match-journal-input");

  const btnReviewers = document.getElementById("btn-find-reviewer-matches");
  const selectReviewers = document.getElementById("match-reviewer-select");
  const inputReviewers = document.getElementById("match-reviewer-input");

  if (btnJournals) btnJournals.addEventListener("click", runJournalMatch);
  if (selectJournals) selectJournals.addEventListener("change", () => {
    if (selectJournals.value) {
      if (inputJournals) inputJournals.value = "";
      runJournalMatch();
    }
  });
  if (inputJournals) inputJournals.addEventListener("keydown", e => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (selectJournals) selectJournals.value = "";
      runJournalMatch();
    }
  });

  if (btnReviewers) btnReviewers.addEventListener("click", runReviewerMatch);
  if (selectReviewers) selectReviewers.addEventListener("change", () => {
    if (selectReviewers.value) {
      if (inputReviewers) inputReviewers.value = "";
      runReviewerMatch();
    }
  });
  if (inputReviewers) inputReviewers.addEventListener("keydown", e => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (selectReviewers) selectReviewers.value = "";
      runReviewerMatch();
    }
  });
}

// ---------------------------------------------------------------- DOI Tracker Modal UI
window.openDoiTracker = async function(doi, title = "") {
  const modal = document.getElementById("doi-tracker-modal");
  const modalTitle = document.getElementById("tracker-modal-title");
  const modalDoi = document.getElementById("tracker-modal-doi");
  const loading = document.getElementById("tracker-loading");
  const content = document.getElementById("tracker-content");
  const summaryCards = document.getElementById("tracker-summary-cards");

  if (!modal) return;
  modalTitle.textContent = title ? `Huella Web: «${title}»` : "Huella Web y Difusión";
  modalDoi.innerHTML = `DOI: <code>${esc(doi)}</code> · <a href="https://doi.org/${esc(doi)}" target="_blank" rel="noopener">Abrir original ↗</a>`;

  loading.hidden = false;
  content.hidden = true;
  modal.hidden = false;

  try {
    const res = await api(`/doi/track?doi=${encodeURIComponent(doi)}`);
    const s = res.sources || {};

    // 0. Summary Cards
    const openalexCount = s.openalex?.count || 0;
    const crossrefCount = s.crossref?.count || 0;
    const wikiCount = s.wikipedia?.count || 0;
    const hnCount = s.hackernews?.count || 0;
    const seCount = s.stackexchange?.count || 0;
    const altmetricScore = s.altmetric?.count || 0;
    const waybackCount = s.wayback?.count || 0;

    summaryCards.innerHTML = `
      <div class="tracker-card">
        <div class="tracker-card-val">${openalexCount}</div>
        <div class="tracker-card-lbl">📚 Citas OpenAlex</div>
        <div class="tracker-card-sub">Crossref: ${crossrefCount}</div>
      </div>
      <div class="tracker-card">
        <div class="tracker-card-val">${wikiCount}</div>
        <div class="tracker-card-lbl">🌐 Wikipedia</div>
        <div class="tracker-card-sub">Artículos citando</div>
      </div>
      <div class="tracker-card">
        <div class="tracker-card-val">${hnCount + seCount}</div>
        <div class="tracker-card-lbl">💬 Debate Técnico</div>
        <div class="tracker-card-sub">HN: ${hnCount} · StackOverflow: ${seCount}</div>
      </div>
      <div class="tracker-card">
        <div class="tracker-card-val">${altmetricScore}</div>
        <div class="tracker-card-lbl">🏛️ Altmetric Score</div>
        <div class="tracker-card-sub">Políticas: ${s.altmetric?.detail?.policies || 0} · Prensa: ${s.altmetric?.detail?.news || 0}</div>
      </div>
      <div class="tracker-card">
        <div class="tracker-card-val">${waybackCount}</div>
        <div class="tracker-card-lbl">⏳ Preservación</div>
        <div class="tracker-card-sub">Capturas en Web Archive</div>
      </div>
    `;

    // 1. Tab Academic (Citing Papers)
    const citingPapers = s.openalex?.detail?.citing_papers || [];
    const tabAcademic = document.getElementById("tab-academic");
    if (citingPapers.length) {
      tabAcademic.innerHTML = `
        <div class="tracker-list-header">Últimas publicaciones académicas que citan este artículo:</div>
        <div class="tracker-items-list">
          ${citingPapers.map(p => `
            <div class="tracker-paper-item">
              <div class="tracker-item-title">
                <a href="${p.doi ? esc(p.doi) : '#'}" target="_blank" rel="noopener">${esc(p.title || "Sin título")}</a>
              </div>
              <div class="tracker-item-meta">
                <span><b>${esc(p.journal)}</b></span> · <span>${p.year || "s.f."}</span> · <span>Autores: ${esc((p.authors || []).join(", ") || "Varios")}</span>
                ${p.is_oa ? `<span class="badge oa">Acceso Abierto</span>` : ""}
                ${p.oa_url ? `<a href="${esc(p.oa_url)}" target="_blank" rel="noopener" class="tracker-pdf-link">PDF Libre 📄</a>` : ""}
              </div>
            </div>
          `).join("")}
        </div>
      `;
    } else {
      tabAcademic.innerHTML = `<div class="tracker-empty">No se encontraron artículos citantes detallados en OpenAlex para este DOI.</div>`;
    }

    // 2. Tab Wikipedia
    const wikiItems = Array.isArray(s.wikipedia?.detail) ? s.wikipedia.detail : [];
    const tabWiki = document.getElementById("tab-wiki");
    if (wikiItems.length && !wikiItems[0].error) {
      tabWiki.innerHTML = `
        <div class="tracker-list-header">Artículos de Wikipedia donde se referencia este trabajo:</div>
        <div class="tracker-items-list">
          ${wikiItems.map(w => `
            <div class="tracker-wiki-item">
              <div class="tracker-item-title">
                <span class="badge wiki-lang">${esc(w.wiki)}</span>
                <a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(w.title)}</a>
              </div>
              ${w.snippet ? `<div class="tracker-wiki-snippet">«…${esc(w.snippet)}…»</div>` : ""}
            </div>
          `).join("")}
        </div>
      `;
    } else {
      tabWiki.innerHTML = `<div class="tracker-empty">No se registran citas directas en artículos de Wikipedia en inglés o español.</div>`;
    }

    // 3. Tab Tech Debate
    const hnItems = Array.isArray(s.hackernews?.detail) ? s.hackernews.detail.filter(x => !x.error) : [];
    const seItems = Array.isArray(s.stackexchange?.detail) ? s.stackexchange.detail.filter(x => !x.error) : [];
    const tabTech = document.getElementById("tab-tech");
    if (hnItems.length || seItems.length) {
      let html = `<div class="tracker-list-header">Discusiones en comunidades técnicas y de desarrollo:</div><div class="tracker-items-list">`;
      if (hnItems.length) {
        html += `<div class="tracker-subgroup-title">🟠 Hacker News</div>`;
        html += hnItems.map(h => `
          <div class="tracker-tech-item">
            <a href="${esc(h.hn_url || h.url)}" target="_blank" rel="noopener"><b>${esc(h.title)}</b></a>
            <div class="tracker-item-meta">${h.points || 0} puntos · ${h.num_comments !== undefined ? h.num_comments : (h.comments || 0)} comentarios · ${h.date || ""}</div>
          </div>
        `).join("");
      }
      if (seItems.length) {
        html += `<div class="tracker-subgroup-title" style="margin-top:12px">⚡ StackOverflow / StackExchange</div>`;
        html += seItems.map(se => `
          <div class="tracker-tech-item">
            <a href="${esc(se.url)}" target="_blank" rel="noopener"><b>${esc(se.title)}</b></a>
          </div>
        `).join("");
      }
      html += `</div>`;
      tabTech.innerHTML = html;
    } else {
      tabTech.innerHTML = `<div class="tracker-empty">Sin menciones registradas en Hacker News o StackExchange.</div>`;
    }

    // 4. Tab Policy & Social
    const altDetail = s.altmetric?.detail || {};
    const tabPolicy = document.getElementById("tab-policy");
    tabPolicy.innerHTML = `
      <div class="tracker-list-header">Impacto social, mediático y en políticas públicas:</div>
      <div class="tracker-policy-box">
        <div class="tracker-policy-stat"><span>🏛️ Políticas Públicas:</span> <b>${altDetail.policies || 0} menciones</b></div>
        <div class="tracker-policy-stat"><span>📰 Medios y Prensa:</span> <b>${altDetail.news || 0} artículos</b></div>
        <div class="tracker-policy-stat"><span>🐦 Redes Sociales (Twitter/X):</span> <b>${altDetail.tweets || 0} publicaciones</b></div>
        <div class="tracker-policy-stat"><span>📝 Blogs de divulgación:</span> <b>${altDetail.blogs || 0} posts</b></div>
        ${altDetail.details_url ? `<div style="margin-top:16px"><a href="${esc(altDetail.details_url)}" target="_blank" rel="noopener" class="btn btn-primary sm">Ver informe completo en Altmetric ↗</a></div>` : ""}
      </div>
    `;

    // 5. Tab Wayback History
    const wbRows = Array.isArray(s.wayback?.detail) ? s.wayback.detail : [];
    const tabHistory = document.getElementById("tab-history");
    tabHistory.innerHTML = `
      <div class="tracker-list-header">Historial de preservación en Internet Archive (${waybackCount} capturas en total):</div>
      ${wbRows.length ? `
        <div class="tracker-history-list">
          ${wbRows.map(wb => `
            <div class="tracker-history-row">
              <span>📅 ${esc(wb.timestamp ? `${wb.timestamp.slice(0,4)}-${wb.timestamp.slice(4,6)}-${wb.timestamp.slice(6,8)} ${wb.timestamp.slice(8,10)}:${wb.timestamp.slice(10,12)}` : '')}</span>
              <span class="badge ${wb.status === '200' ? 'cited' : ''}">HTTP ${esc(wb.status || '200')}</span>
              <a href="https://web.archive.org/web/${esc(wb.timestamp)}/https://doi.org/${esc(doi)}" target="_blank" rel="noopener">Ver captura ↗</a>
            </div>
          `).join("")}
        </div>
      ` : `<div class="tracker-empty">Sin historial de capturas en Wayback Machine.</div>`}
    `;

    loading.hidden = true;
    content.hidden = false;

  } catch (err) {
    loading.hidden = true;
    content.hidden = false;
    summaryCards.innerHTML = `<div class="tracker-error">Error al rastrear DOI: ${esc(err.message)}</div>`;
  }
}

function initDoiTracker() {
  const modal = document.getElementById("doi-tracker-modal");
  const closeBtn = document.getElementById("btn-close-tracker");

  if (closeBtn && modal) {
    closeBtn.addEventListener("click", () => { modal.hidden = true; });
    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.hidden = true;
    });
  }

  // Delegated clicks for tracker buttons
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".btn-track-doi, [data-action='track-doi']");
    if (btn) {
      e.preventDefault();
      const doi = btn.dataset.doi;
      const title = btn.dataset.title || "";
      if (doi) openDoiTracker(doi, title);
    }
  });

  // Tab switching
  const tabs = document.querySelectorAll(".tracker-tab");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      const targetId = tab.dataset.tab;
      document.querySelectorAll(".tracker-tab-panel").forEach(p => {
        if (p.id === targetId) {
          p.hidden = false;
          p.classList.add("active");
        } else {
          p.hidden = true;
          p.classList.remove("active");
        }
      });
    });
  });
}

/* Aviso de instancia obsoleta.
   Un servidor viejo sirve la interfaz desde el disco pero responde 404 en los endpoints
   nuevos: la herramienta parece rota sin decir por qué. `/api/health` publica una huella
   de compilación y aquí se comprueba al arrancar. */
function mostrarAvisoBuild(mensaje, detalle) {
  const banner = document.getElementById("build-warning-banner");
  if (!banner) return;
  banner.innerHTML = `
    <span class="material-symbols-outlined" style="font-size:20px;">report</span>
    <div>
      <strong>${mensaje}</strong>
      <div class="build-warning-detail">${detalle}</div>
    </div>
    <button type="button" id="build-warning-close" title="Ocultar">✕</button>`;
  banner.hidden = false;
  banner.style.display = "flex";
  const cerrar = document.getElementById("build-warning-close");
  if (cerrar) cerrar.addEventListener("click", () => { banner.hidden = true; banner.style.display = "none"; });
}

async function checkBuildFingerprint() {
  if (!document.getElementById("build-warning-banner")) return;
  let salud;
  try {
    salud = await api("/health", {}, { timeoutMs: 8000 });
  } catch (e) {
    mostrarAvisoBuild("No se pudo comprobar la versión del servidor.",
      esc(String(e && e.message ? e.message : e)));
    return;
  }
  const huella = salud && salud.build;
  if (!huella) {
    mostrarAvisoBuild("El servidor en ejecución es MÁS ANTIGUO que la interfaz.",
      "No declara huella de compilación, así que no incluye las funciones recientes "
      + "(resumen determinista, huella editorial, backfill). Cierra la ventana donde corre el "
      + "servidor y vuelve a lanzarlo con <code>inicio.bat</code>.");
    return;
  }
  const nuevos = huella.endpoints_nuevos || {};
  const faltan = Object.keys(nuevos).filter(k => !nuevos[k]);
  if (faltan.length) {
    mostrarAvisoBuild("El servidor en ejecución está desactualizado.",
      `Le faltan ${faltan.length} endpoints: <code>${faltan.join(", ")}</code>. `
      + `Código cargado: <code>${esc(huella.codigo || "?")}</code> `
      + `(main.py del ${esc(huella.main_py_modificado || "?")}, ${huella.rutas_totales || "?"} rutas). `
      + "Cierra esa ventana y relanza con <code>inicio.bat</code>.");
    return;
  }
  const banner = document.getElementById("build-warning-banner");
  banner.hidden = true;
  banner.style.display = "none";
}

/* Huella editorial de una revista por OAI-PMH (Modo Revista, escalón 1 de la ingesta).
   Una petición entrega la revista completa: metadata, resumen y palabras clave. */
function renderJournalOaiResult(d) {
  const salida = document.getElementById("journal-oai-result");
  const estado = document.getElementById("journal-oai-status");
  if (!salida || !estado) return;

  if (!d.endpoint) {
    const sondeos = (d.intentos || []).map(i =>
      `<li><code>${esc(i.endpoint)}</code> — ${esc(i.detalle || "sin respuesta")}</li>`).join("");
    estado.innerHTML = `<strong>No se encontró endpoint OAI-PMH.</strong> Esta instalación no lo publica `
      + `(ocurre: no toda revista OAI lo expone). Se probaron ${(d.intentos || []).length} rutas; `
      + `sin OAI, la vía es la ficha por artículo (escalón 2).`;
    salida.innerHTML = `<ul style="font-size:0.82rem; color:var(--text-secondary); margin-top:8px;">${sondeos}</ul>`;
    salida.hidden = false;
    return;
  }

  const perfil = d.perfil || {};
  const cob = perfil.cobertura || {};
  const idiomas = Object.entries(perfil.idiomas || {})
    .map(([k, v]) => `${esc(k)} (${v})`).join(" · ") || "—";
  const claves = Object.keys(perfil.palabras_clave_frecuentes || {}).slice(0, 8)
    .map(k => `<span class="badge badge-source" style="margin:2px 4px 2px 0; display:inline-block;">${esc(k)}</span>`)
    .join("");
  const anios = Object.keys(perfil.por_anio || {});
  const rango = anios.length
    ? `${anios[0]}–${anios[anios.length - 1]} (${anios.length} años)`
    : "—";

  estado.innerHTML = `<strong>${esc(d.repositorio || "Revista")}</strong> · endpoint detectado en la sonda ${(d.intentos || []).length}`;

  salida.innerHTML = `
    <div class="ecosystem-metrics-grid" style="margin-top:12px;">
      <div class="eco-metric-card">
        <div class="eco-metric-header"><span class="material-symbols-outlined text-[18px]">library_books</span><span>Registros cosechados</span></div>
        <div class="eco-metric-value">${Number(perfil.total || 0).toLocaleString("es-ES")}</div>
      </div>
      <div class="eco-metric-card">
        <div class="eco-metric-header"><span class="material-symbols-outlined text-[18px]">calendar_month</span><span>Cobertura temporal</span></div>
        <div class="eco-metric-value" style="font-size:1rem;">${esc(rango)}</div>
      </div>
      <div class="eco-metric-card">
        <div class="eco-metric-header"><span class="material-symbols-outlined text-[18px]">translate</span><span>Idiomas</span></div>
        <div class="eco-metric-value" style="font-size:1rem;">${idiomas}</div>
      </div>
      <div class="eco-metric-card">
        <div class="eco-metric-header"><span class="material-symbols-outlined text-[18px]">verified</span><span>Cobertura de metadata</span></div>
        <div class="eco-metric-value" style="font-size:1rem;">resumen ${cob.con_resumen_pct ?? "?"}% · DOI ${cob.con_doi_pct ?? "?"}%</div>
        <div class="eco-metric-sub">resumen medio ${perfil.resumen_chars_promedio || 0} caracteres</div>
      </div>
    </div>
    <div style="margin-top:12px;">
      <div style="font-size:0.8rem; color:var(--text-secondary); margin-bottom:6px;">Descriptores más frecuentes de la revista:</div>
      ${claves || '<span class="panel-sub">—</span>'}
    </div>
    <div style="margin-top:10px; font-size:0.8rem; color:var(--text-secondary);">
      Endpoint: <code>${esc(d.endpoint)}</code>
    </div>`;
  salida.hidden = false;
}

function initJournalOai() {
  const boton = document.getElementById("btn-journal-oai");
  const entrada = document.getElementById("journal-oai-url");
  if (!boton || !entrada) return;

  const cosechar = async () => {
    const url = (entrada.value || "").trim();
    const estado = document.getElementById("journal-oai-status");
    const salida = document.getElementById("journal-oai-result");
    if (!url) {
      if (estado) { estado.hidden = false; estado.textContent = "Pega la URL de la revista (por ejemplo, https://revista.edu/index.php/mirevista)."; }
      return;
    }
    boton.disabled = true;
    if (salida) salida.hidden = true;
    if (estado) {
      estado.hidden = false;
      estado.textContent = "Detectando el endpoint OAI-PMH y cosechando la revista… puede tardar unos segundos.";
    }
    try {
      const d = await apiPost("/editorial/journal/profile", { url, max_records: 200 },
                              { timeoutMs: 180000 });
      renderJournalOaiResult(d);
    } catch (e) {
      if (estado) estado.textContent = "No se pudo cosechar: " + (e && e.message ? e.message : e);
    } finally {
      boton.disabled = false;
    }
  };

  boton.addEventListener("click", cosechar);
  entrada.addEventListener("keydown", ev => { if (ev.key === "Enter") cosechar(); });
}

(async function init() {
  writeForm();
  refreshNotifyButton();
  checkBuildFingerprint();
  loadRadarFilters();
  renderRadarExcludedBar();
  initRouter();
  initHomeInquiry();
  initSocratic();
  initScientificMatch();
  initDoiTracker();
  initJournalOai();
  await Promise.all([
    renderFeed(),
    renderStats(),
    renderSources(),
    loadWatch(),
    renderTrendingTopics(),
    loadRpcArticlesForMatch(),
  ]);
  initEpistemicTabs();
  loadEpistemicDashboard(null);
  if ("serviceWorker" in navigator) {
    try {
      const reg = await navigator.serviceWorker.register("sw.js");
      if (reg) reg.update();
    } catch (e) { /* SW opcional */ }
  }
})();