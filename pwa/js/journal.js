/* Thinkuy — modo revista: auditoría editorial, match y huella OAI (módulo ES). */
import { api, apiPost } from "./api.js";
import { bridge } from "./bridge.js";
import { esc, escapeHtml, showNotification } from "./dom.js";
import { renderProximityRadar } from "./radar.js";
import { state } from "./state.js";


function renderJournalAuditResults(data) {
  if (!state.currentJournalAuditData || state.currentJournalAuditData.journal_title !== data.journal_title) {
    state.radarComparedJournals = [];
  }
  state.currentJournalAuditData = data;
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
        const domFallback = (typeof state.currentJournalAuditData !== "undefined" && state.currentJournalAuditData && state.currentJournalAuditData.domain) || "";
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
          bridge.loadWatch();
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
          bridge.loadWatch();
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

export {
  initJournalOai,
  initScientificMatch,
  loadRpcArticlesForMatch,
  renderJournalAuditResults,
};
