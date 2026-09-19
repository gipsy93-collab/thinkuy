/* Thinkuy — radar de proximidad autoral (módulo ES). */
import { api } from "./api.js";
import { bridge } from "./bridge.js";
import { esc, escapeHtml, showNotification } from "./dom.js";
import { state } from "./state.js";
import { authorsLine, debounce, keywordStrings, selectableKeywordChip } from "./utils.js";

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
    button.addEventListener("click", () => bridge.openDoiTracker(button.dataset.doi, button.dataset.title));
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
    if (doi) bridge.openDoiTracker(doi, title);
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
    await bridge.loadWatch();
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
    bridge.renderStats();
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
  bridge.readForm(); bridge.renderFeed(); bridge.refreshSuggest();
});
document.getElementById("btn-refresh")?.addEventListener("click", () => { bridge.renderFeed(); bridge.renderSources(); bridge.loadWatch(); });
document.getElementById("btn-pin")?.addEventListener("click", bridge.addWatch);
document.getElementById("btn-cfp")?.addEventListener("click", async () => {
  try {
    const data = await api("/cfp");
    const kws = (data.cfp && data.cfp.keywords) || [];
    const kwInput = document.getElementById("keywords");
    if (kwInput) kwInput.value = kws.slice(0, 6).join(", ");
    bridge.readForm();
    bridge.renderFeed();
  } catch (e) { /* silencioso */ }
});
document.getElementById("btn-notify")?.addEventListener("click", async () => {
  if (!("Notification" in window)) { showNotification({ title: "Notificaciones", message: "Tu navegador no soporta notificaciones.", type: "info" }); return; }
  const p = await Notification.requestPermission();
  bridge.refreshNotifyButton();
  if (p === "granted") bridge.loadWatch();
});
document.getElementById("keywords")?.addEventListener("input", debounce(bridge.refreshSuggest, 400));
document.getElementById("keywords")?.addEventListener("keydown", e => {
  if (e.key === "Enter") {
    e.preventDefault();
    bridge.readForm();
    bridge.renderFeed();
    bridge.refreshSuggest();
  }
});


// ================================================================

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
  state.radarComparedJournals.forEach((comp, idx) => {
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
  if (state.radarComparedJournals.length === 0) {
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

  const count = state.radarComparedJournals.length;
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
  state.radarComparedJournals.forEach((comp, idx) => {
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

  if (state.radarComparedJournals.length >= 3) {
    showError("Máximo 3 revistas contrastadas simultáneamente. Descarte una para añadir otra.");
    return;
  }

  let title = typeof queryOrObj === "string" ? queryOrObj.trim() : (queryOrObj.journal_title || "");
  let domain = typeof queryOrObj === "object" ? (queryOrObj.domain || "") : "";
  let rank = typeof queryOrObj === "object" ? queryOrObj.harmonic_rank : undefined;

  const targetTitle = (state.currentJournalAuditData && (state.currentJournalAuditData.journal_title || state.currentJournalAuditData.query || "")).toLowerCase().trim();
  if (title.toLowerCase().trim() === targetTitle) {
    showError("Esta es la revista auditada de referencia.");
    return;
  }

  if (state.radarComparedJournals.some(c => c.title.toLowerCase().trim() === title.toLowerCase().trim())) {
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
  const totalDomains = (state.currentJournalAuditData && state.currentJournalAuditData.proximity_radar && state.currentJournalAuditData.proximity_radar.total_domains) || 58900000;
  
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

  state.radarComparedJournals.push({
    title,
    domain,
    rank,
    target_radius: calcRadius(rank),
    orbit_name: orbitInfo.name,
    orbit_badge: orbitInfo.badge,
  });

  const radarSvg = document.getElementById("scivis-radar-svg");
  if (radarSvg && state.currentJournalAuditData) {
    renderProximityRadar(radarSvg, state.currentJournalAuditData.proximity_radar, state.currentJournalAuditData);
  }
}

function removeJournalFromRadarComparison(index) {
  if (index >= 0 && index < state.radarComparedJournals.length) {
    state.radarComparedJournals.splice(index, 1);
    const radarSvg = document.getElementById("scivis-radar-svg");
    if (radarSvg && state.currentJournalAuditData) {
      renderProximityRadar(radarSvg, state.currentJournalAuditData.proximity_radar, state.currentJournalAuditData);
    }
  }
}

export { renderProximityRadar, renderRadar, renderRadarExcludedBar };
