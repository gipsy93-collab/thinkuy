/* Thinkuy — lógica del widget PWA (módulo ES). */
import { API, api, apiPost } from "./api.js";
import { esc, escapeHtml, showNotification } from "./dom.js";
import { loadRadarFilters, saveConfig, saveRadarFilters, state } from "./state.js";
import { authorsLine, debounce, extractCleanDoi, keywordStrings, selectableKeywordChip } from "./utils.js";
import { bridge } from "./bridge.js";
import { renderRadar, renderRadarExcludedBar } from "./radar.js";
import { initJournalOai, initScientificMatch, loadRpcArticlesForMatch, renderJournalAuditResults } from "./journal.js";
import { ensureProtocol, refreshPrismaFlow, setupChartingTab, setupPrismaReport, setupProtocolManager, setupScreeningTab } from "./review.js";

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


function renderLibrarianResults(data) {
  state.currentLibrarianData = data;
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


async function loadEpistemicDashboard(librarianData) {
  const epistemicSection = document.getElementById("librarian-epistemic-section");
  if (!epistemicSection) return;

  state.lastLibrarianData = librarianData;
  state.epistemicSubmotorLoaded = false;
  state.reviewSubmotorLoaded = false;

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

      if (targetId === "submotor-panel-epistemic" && !state.epistemicSubmotorLoaded) {
        loadEpistemicSubmotorA(state.lastLibrarianData);
        setupSnowballingExplorer(state.lastLibrarianData);
      } else if (targetId === "submotor-panel-review" && !state.reviewSubmotorLoaded) {
        state.reviewSubmotorLoaded = true;
        refreshPrismaFlow();
      }
    };
  });

  const recalcBtn = document.getElementById("btn-recalc-epistemic");
  if (recalcBtn) {
    recalcBtn.onclick = () => {
      loadEpistemicSubmotorA(state.lastLibrarianData, true);
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

  // Corpus CURADO: escuelas y trayectoria se calculan sobre los artículos INCLUIDOS del protocolo,
  // NO sobre los resultados crudos de la búsqueda. Medido (22-09-2026): con DOIs arbitrarios
  // salen escuelas de paleontología o bibliometría.
  const pid = await ensureProtocol();
  let nIncluidos = null;
  if (pid) {
    try {
      const inc = await api(`/review/protocol/${pid}/screenings`, { decision: "included", limit: 1 });
      nIncluidos = inc.total ?? 0;
    } catch (_) { /* sin dato: se declara abajo */ }
  }

  if (indicator) {
    if (pid) {
      indicator.textContent = `Corpus curado del protocolo: ${nIncluidos ?? "?"} artículos incluidos con criterio (escuelas y trayectoria se calculan SOLO sobre estos)`;
    } else {
      indicator.textContent = "Vista global del catálogo (sin protocolo activo)";
    }
  }

  if (state.epistemicSubmotorLoaded && !forceRefresh) return;
  state.epistemicSubmotorLoaded = true;

  if (schoolsContainer) {
    schoolsContainer.innerHTML = `<div class="loading-placeholder">Analizando escuelas de pensamiento sobre el corpus curado...</div>`;
  }
  if (mainpathContainer) {
    mainpathContainer.innerHTML = `<div class="loading-placeholder">Calculando Trayectoria Principal (SPC) sobre el corpus curado...</div>`;
  }

  const corpusParams = pid ? { protocol_id: pid } : {};

  // 1. Escuelas de Pensamiento (asíncrono, no bloqueante)
  try {
    const schoolsParams = { limit: 12, threshold: 2, ...corpusParams };
    const schoolsData = await api("/graph/schools", schoolsParams);
    renderEpistemicSchools(schoolsData.schools || []);
    if (schoolsContainer && (schoolsData.fallback_global || (schoolsData.corpus_n === 0))) {
      const texto = schoolsData.corpus_n === 0
        ? "No hay artículos incluidos en el protocolo: incluye obras en el cribado para calcular escuelas sobre contenido curado."
        : (schoolsData.aviso || "");
      schoolsContainer.insertAdjacentHTML("afterbegin",
        `<div class="snowball-empty-hint" style="border-left:3px solid #FFA726; padding-left:8px;">${esc(texto)}</div>`);
    }
  } catch (err) {
    console.error("Error al cargar escuelas de pensamiento:", err);
    if (schoolsContainer) {
      schoolsContainer.innerHTML = `<div class="snowball-empty-hint">No se pudieron calcular escuelas: ${esc(err.message || err)}</div>`;
    }
  }

  // 2. Main Path (asíncrono)
  try {
    const mpParams = { top_n: 15, ...corpusParams };
    const mpData = await api("/graph/main-path", mpParams);
    renderMainPath(mpData.main_path_transitions || []);
    if (mainpathContainer) {
      const g = mpData.grafo || {};
      let nota = `<div class="text-xs text-secondary" style="margin-bottom:6px;">Corpus: ${esc(mpData.origen_corpus || "global")} (${mpData.corpus_n ?? 0}) · Base del grafo: ${g.nodos || 0} nodos · ${g.aristas || 0} aristas · densidad ${g.densidad ?? 0}.</div>`;
      if (mpData.fallback_global) {
        nota += `<div class="snowball-empty-hint" style="border-left:3px solid #FFA726; padding-left:8px;">${esc(mpData.aviso || "")}</div>`;
      }
      mainpathContainer.insertAdjacentHTML("afterbegin", nota);
    }
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
      state.currentEpistemicRoles = librarianData.articles.map(a => {
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
      state.currentEpistemicRoles = rolesData.roles || [];
    }

    if (!state.currentEpistemicRoles || state.currentEpistemicRoles.length === 0) {
      // Si no hay roles en memoria pero el protocolo activo ya tiene obras, cargarlas desde el protocolo
      try {
        const pid = await ensureProtocol();
        if (pid) {
          const scData = await api(`/review/protocol/${pid}/screenings`, { limit: 60 });
          if (scData && scData.screenings && scData.screenings.length > 0) {
            state.currentEpistemicRoles = scData.screenings.map(s => {
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

    renderEpistemicRoles(state.currentEpistemicRoles);

    if (transferSummary) {
      transferSummary.textContent = `${state.currentEpistemicRoles.length} publicaciones clasificadas listas para screening`;
    }
  } catch (err) {
    console.error("Error al clasificar roles:", err);
    if (librarianData && librarianData.articles && librarianData.articles.length > 0) {
      state.currentEpistemicRoles = librarianData.articles.map(a => ({
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
      renderEpistemicRoles(state.currentEpistemicRoles);
      if (transferSummary) {
        transferSummary.textContent = `${state.currentEpistemicRoles.length} publicaciones cargadas directamente`;
      }
    } else {
      rolesContainer.innerHTML = `<div class="snowball-empty-hint">Utiliza la <strong>Sonda Federada</strong> arriba para cosechar en tiempo real desde OpenAlex, OpenAIRE y Dialnet para este protocolo.</div>`;
    }
  }

  // Integración de la Sonda Federada en Vivo de Paso 0
  const harvestBtn = document.getElementById("btn-protocol-harvest");
  const harvestInput = document.getElementById("input-protocol-harvest-query");
  const harvestStatus = document.getElementById("protocol-harvest-status");
  const harvestYearFrom = document.getElementById("input-protocol-harvest-year-from");
  const harvestYearTo = document.getElementById("input-protocol-harvest-year-to");

  if (harvestInput && !harvestInput.value) {
    try {
      const activeProto = window.activeProtocolObj;
      if (activeProto && (activeProto.research_question || activeProto.title)) {
        harvestInput.value = activeProto.research_question || activeProto.title;
      }
    } catch (_) {}
  }

  // El rango de años es una opción del investigador: se prellena desde el protocolo, pero se
  // puede borrar. Vacío = sin filtro (la búsqueda no acota el universo por defecto).
  if (harvestYearFrom && !harvestYearFrom.value) {
    try {
      const activeProto = window.activeProtocolObj;
      if (activeProto && activeProto.date_from) harvestYearFrom.value = String(activeProto.date_from);
    } catch (_) {}
  }
  if (harvestYearTo && !harvestYearTo.value) {
    try {
      const activeProto = window.activeProtocolObj;
      if (activeProto && activeProto.date_to) harvestYearTo.value = String(activeProto.date_to);
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
      const payload = { query: q, limit: 100 };
      const yf = harvestYearFrom ? harvestYearFrom.value.trim() : "";
      const yt = harvestYearTo ? harvestYearTo.value.trim() : "";
      if (yf) payload.year_from = parseInt(yf, 10);
      if (yt) payload.year_to = parseInt(yt, 10);
      harvestBtn.disabled = true;
      const origHtml = harvestBtn.innerHTML;
      harvestBtn.innerHTML = `<span class="material-symbols-outlined text-[15px] animate-spin">sync</span> Cosechando...`;
      if (harvestStatus) harvestStatus.innerHTML = `<span class="text-secondary">Consultando en paralelo OpenAlex · OpenAIRE Graph · Dialnet...</span>`;
      try {
        const res = await apiPost(`/review/protocol/${pid}/harvest-search`, payload, { timeoutMs: 300000 });
        if (res && res.articles) {
          state.currentEpistemicRoles = res.articles;
          renderEpistemicRoles(state.currentEpistemicRoles);
          if (transferSummary) {
            transferSummary.textContent = `${state.currentEpistemicRoles.length} publicaciones cosechadas listas para screening`;
          }
          if (harvestStatus) {
            const f = res.filtro_anios;
            const filtroTxt = (f && f.activo)
              ? ` · Filtro ${f.year_from || "…"}–${f.year_to || "…"}${f.excluidos_por_rango ? ` (${f.excluidos_por_rango} fuera de rango)` : ""}${f.sin_anio ? ` (${f.sin_anio} sin año)` : ""}`
              : " · Sin filtro de año";
            harvestStatus.innerHTML = `<span style="color:var(--brand-teal); font-weight:600;">✅ Cosecha completada: ${res.harvested_count || res.articles.length} obras agregadas a screening (Total identificado: ${res.total_matched || res.articles.length})${filtroTxt}.</span>`;
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

      let articles = (state.currentEpistemicRoles && state.currentEpistemicRoles.length > 0)
        ? state.currentEpistemicRoles
        : (state.lastLibrarianData && state.lastLibrarianData.articles ? state.lastLibrarianData.articles : []);

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

  setupPrismaReport();
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
      state.activeEpistemicRoleFilter = chip.dataset.role;
      filterRolesList();
    };
  });

  const sourceChips = document.querySelectorAll(".role-src-chip");
  sourceChips.forEach(chip => {
    chip.onclick = () => {
      sourceChips.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      state.activeEpistemicSourceFilter = chip.dataset.source;
      filterRolesList();
    };
  });

  filterRolesList();
}

function filterRolesList() {
  const container = document.getElementById("epistemic-roles-container");
  if (!container) return;

  const roleFilter = state.activeEpistemicRoleFilter;
  const srcFilter = state.activeEpistemicSourceFilter;

  const filtered = state.currentEpistemicRoles.filter(r => {
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

  if (candidateArticles.length === 0 && Array.isArray(state.currentEpistemicRoles) && state.currentEpistemicRoles.length > 0) {
    candidateArticles = state.currentEpistemicRoles.filter(a => a.doi);
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
      if (state.screeningProtocolId) body.protocol_id = state.screeningProtocolId;
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
      const auditData = await api("/scivis/audit", { query: q, refresh: 1 }, { timeoutMs: 180000 });
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
    state.currentHomePersona = persona;
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

    if (state.currentHomePersona === "journal") {
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
        const auditData = await api("/scivis/audit", { query: q }, { timeoutMs: 180000 });
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
        const data = await api("/librarian/assist", {}, { method: "POST", body: { inquiry: q, limit: 36, source: "live" }, timeoutMs: 180000 });
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
    if (!state.currentLibrarianData) return;
    const kwInput = document.getElementById("keywords");
    if (kwInput) {
      kwInput.value = (state.currentLibrarianData.keywords || [state.currentLibrarianData.corrected || state.currentLibrarianData.inquiry]).join(", ");
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
      if (!state.currentLibrarianData) return;
      const radarTopic = document.getElementById("radar-topic");
      if (radarTopic) {
        radarTopic.value = state.currentLibrarianData.corrected || state.currentLibrarianData.inquiry;
      }
      switchView("radar");
      const radarOrbitBtn = document.getElementById("btn-radar");
      if (radarOrbitBtn) radarOrbitBtn.click();
    });
  }

  if (pinBtn) {
    pinBtn.addEventListener("click", async () => {
      if (!state.currentLibrarianData) return;
      pinBtn.disabled = true;
      pinBtn.textContent = "Anclando…";
      try {
        const kws = (state.currentLibrarianData.keywords || [state.currentLibrarianData.corrected || state.currentLibrarianData.inquiry]).join(", ");
        const label = state.currentLibrarianData.heard_as || state.currentLibrarianData.inquiry;
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
        state.currentSocraticData = await api("/socratic/analyze", {}, { method: "POST", body: { inquiry } });
        // Si la inquietud es trivial ("hola"), el backend pide precisar sin inventar campo.
        if (state.currentSocraticData && state.currentSocraticData.status === "need_clarification") {
          showNotification({ title: "Análisis socrático", message: state.currentSocraticData.message || "Cuéntame un poco más para ubicarte en el campo correcto.", type: "info" });
          const dens = state.currentSocraticData.literature_density || {};
          document.getElementById("socratic-density").textContent = `Catálogo: ${dens.articles_found || 0} artículos en ${dens.journals_covered || 0} revistas. Precisa tu tema para continuar.`;
          document.getElementById("socratic-step-1").hidden = false;
          document.getElementById("socratic-step-2").hidden = true;
          return;
        }
        document.getElementById("socratic-field-badge").textContent = `Campo: ${state.currentSocraticData.primary_field.name}`;
        document.getElementById("socratic-epistemic").textContent = state.currentSocraticData.epistemic_reflection;
        
        const qList = document.getElementById("socratic-questions-list");
        qList.innerHTML = state.currentSocraticData.socratic_questions.map((q, idx) => `
          <div style="font-size: 13px; padding: 6px 10px; background: #FFFFFF; border-radius: var(--radius-sm); border: 1px solid rgba(192, 200, 201, 0.4);">
            <b>${idx + 1}.</b> ${esc(q)}
          </div>
        `).join("");

        document.getElementById("socratic-density").textContent = `Densidad en catálogo: ${(state.currentSocraticData.literature_density || {}).articles_found || 0} artículos en ${(state.currentSocraticData.literature_density || {}).journals_covered || 0} revistas.`;
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
        state.currentConcertedData = await api("/socratic/concert", {}, {
          method: "POST",
          body: {
            field_name: state.currentSocraticData.primary_field.name,
            original_inquiry: document.getElementById("socratic-input").value.trim(),
            user_reflection: reflection,
            suggested_keywords: state.currentSocraticData.suggested_keywords
          }
        });
        document.getElementById("socratic-result-title").textContent = state.currentConcertedData.label;
        document.getElementById("socratic-result-summary").textContent = state.currentConcertedData.summary;
        document.getElementById("socratic-result-kws").textContent = state.currentConcertedData.recommended_keywords;
        document.getElementById("socratic-result-journals").textContent = state.currentConcertedData.key_journals.join(" · ");
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
      if (!state.currentConcertedData) return;
      pinBtn.disabled = true;
      pinBtn.textContent = "Anclando…";
      try {
        await api("/watch", {}, {
          method: "POST",
          body: { keywords: state.currentConcertedData.recommended_keywords, label: state.currentConcertedData.label }
        });
        document.getElementById("keywords").value = state.currentConcertedData.recommended_keywords;
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
      if (!state.currentConcertedData) return;
      applyBtn.disabled = true;
      applyBtn.textContent = "Cargando publicaciones…";
      try {
        document.getElementById("keywords").value = state.currentConcertedData.recommended_keywords;
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



/* Puente para radar.js/journal.js: funciones del home que ellos invocan. */
Object.assign(bridge, {
  addWatch, loadWatch, renderFeed, renderStats, renderSources, refreshSuggest,
  refreshNotifyButton, readForm, openDoiTracker: (...a) => window.openDoiTracker(...a),
});

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