/* Thinkuy — cribado PRISMA y charting JBI (modo investigador). Módulo ES. */
import { api, apiPost } from "./api.js";
import { esc, showNotification } from "./dom.js";
import { state } from "./state.js";
import { extractCleanDoi } from "./utils.js";

// ================================================================
// GESTOR DE PROYECTOS / PROTOCOLOS PERSISTENTES (PRISMA / JBI)
// ================================================================

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
        state.screeningProtocolId = res.protocol_id;
        localStorage.setItem("thinkuy_active_protocol_id", state.screeningProtocolId);
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
    state.screeningProtocolId = savedPid;
  } else if (protocols.length > 0) {
    state.screeningProtocolId = protocols[0].id;
    localStorage.setItem("thinkuy_active_protocol_id", state.screeningProtocolId);
  }

  // Renderizar opciones del selector de proyectos
  select.innerHTML = protocols.map(p =>
    `<option value="${p.id}" ${p.id === state.screeningProtocolId ? "selected" : ""}>${esc(p.title || "Protocolo #" + p.id)} [${esc(p.framework || "PCC")}]</option>`
  ).join("");

  const updateStatusBadge = (pid) => {
    const activeP = protocols.find(p => p.id === pid);
    if (badgeStatus && activeP) {
      badgeStatus.textContent = activeP.status || "screening";
    }
  };
  updateStatusBadge(state.screeningProtocolId);

  // Cambio de protocolo por el usuario
  select.onchange = async () => {
    const newPid = parseInt(select.value, 10);
    if (newPid) {
      state.screeningProtocolId = newPid;
      localStorage.setItem("thinkuy_active_protocol_id", state.screeningProtocolId);
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
          state.screeningProtocolId = res.protocol_id;
          localStorage.setItem("thinkuy_active_protocol_id", state.screeningProtocolId);
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
  if (state.screeningProtocolId) return state.screeningProtocolId;
  const savedPid = parseInt(localStorage.getItem("thinkuy_active_protocol_id"), 10);
  if (savedPid) {
    state.screeningProtocolId = savedPid;
    return state.screeningProtocolId;
  }
  try {
    const data = await api("/review/protocols", { limit: 1 });
    if (data.protocols && data.protocols.length > 0) {
      state.screeningProtocolId = data.protocols[0].id;
      localStorage.setItem("thinkuy_active_protocol_id", state.screeningProtocolId);
      return state.screeningProtocolId;
    }
  } catch (_) {}
  // Auto-create a default protocol
  try {
    const res = await apiPost("/review/protocol", {
      title: "Scoping Review — Sesión " + new Date().toISOString().slice(0, 10),
      framework: "PCC",
      status: "screening",
    });
    state.screeningProtocolId = res.protocol_id;
    localStorage.setItem("thinkuy_active_protocol_id", state.screeningProtocolId);
    return state.screeningProtocolId;
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
      const cached = state.screeningArticlesCache.find(x => (x.doi || "").toLowerCase() === doiCard);
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
      const cached = state.screeningArticlesCache.find(x =>
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
        state.screeningArticlesCache = screenings;
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
      } else if (state.currentEpistemicRoles && state.currentEpistemicRoles.length > 0) {
        articles = state.currentEpistemicRoles.filter(a => a.doi);
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

      state.screeningArticlesCache = articles;
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
        const cached = state.screeningArticlesCache.find(a => (a.doi || "").toLowerCase() === doi);
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

export {
  ensureProtocol,
  refreshPrismaFlow,
  setupChartingTab,
  setupProtocolManager,
  setupScreeningTab,
};
