/* Thinkuy — popup de la extensión */
"use strict";

/* Shim de compatibilidad Chrome/Firefox (MV3) */
const browser = globalThis.browser || globalThis.chrome;

const DEFAULTS = {
  apiUrl: "http://localhost:8000",
  keywords: "comunicación política, ecología de los medios, narrativas televisivas, ética y estética",
  limit: 5,
  days: 365,
};

const SOURCE_NAMES = { scielo: "SciELO", crossref: "Crossref", openalex: "OpenAlex", redalyc: "Redalyc" };

async function getConfig() {
  const stored = await browser.storage.sync.get(DEFAULTS);
  return { ...DEFAULTS, ...stored };
}

async function fetchFeed(cfg) {
  const params = new URLSearchParams({
    keywords: cfg.keywords,
    limit: cfg.limit,
    days: cfg.days,
  });
  const resp = await fetch(`${cfg.apiUrl.replace(/\/$/, "")}/api/feed?${params}`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

function render(data, cfg) {
  const list = document.getElementById("list");
  const count = document.getElementById("count");
  count.hidden = false;
  count.textContent = String(data.count);
  if (!data.articles.length) {
    list.innerHTML = '<div class="empty">Sin señales con estos filtros.<br>Ajusta tus keywords en ⚙</div>';
    return;
  }
  list.innerHTML = data.articles.map(a => {
    const aus = (a.authors || []).map(x => `${x.family || ""} ${x.given || ""}`.trim()).filter(Boolean);
    const authors = aus.length ? (aus.length <= 2 ? aus.join(", ") : `${aus[0]} et al.`) : "s/a";
    const why = ((a.conversation && a.conversation.why) || []).join(" · ")
      || (a.matched || []).map(m => `«${m.keyword}»`).join(", ");
    return `<div class="item">
      <h3><a href="${(a.url || `https://doi.org/${a.doi}`)}" target="_blank" rel="noopener">${esc(a.title)}</a></h3>
      <div class="meta">${esc(authors)} — <span class="j">${esc(a.journal_title || "")}</span>${a.year ? ` · ${a.year}` : ""} · ${SOURCE_NAMES[a.source] || a.source}</div>
      ${why ? `<div class="why">⦿ ${esc(why)}</div>` : ""}
      <div class="exports">
        <a href="${cfg.apiUrl}/api/articles/${encodeURIComponent(a.doi || "")}/citation?format=apa" target="_blank">APA</a>
        <a href="${cfg.apiUrl}/api/articles/${encodeURIComponent(a.doi || "")}/citation?format=bibtex" target="_blank">BibTeX</a>
        <a href="${cfg.apiUrl}/api/articles/${encodeURIComponent(a.doi || "")}/citation?format=ris" target="_blank">RIS</a>
      </div>
    </div>`;
  }).join("");
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function refresh() {
  const list = document.getElementById("list");
  try {
    const cfg = await getConfig();
    const data = await fetchFeed(cfg);
    render(data, cfg);
  } catch (e) {
    list.innerHTML = `<div class="empty">⚠ No se pudo contactar el radar.<br>${esc(e.message)}<br><br>Verifica que el backend esté corriendo y la URL en ⚙</div>`;
  }
}

document.getElementById("refresh").addEventListener("click", refresh);
document.getElementById("options").addEventListener("click", () => {
  if (typeof browser !== "undefined" && browser.runtime && browser.runtime.openOptionsPage) {
    browser.runtime.openOptionsPage();
  } else {
    chrome.runtime.openOptionsPage();
  }
});
document.getElementById("open").addEventListener("click", async () => {
  const cfg = await getConfig();
  const url = cfg.apiUrl.includes("localhost") || cfg.apiUrl.includes("127.0.0.1")
    ? `${cfg.apiUrl.replace(/\/$/, "")}/app/`
    : cfg.apiUrl;
  browser.tabs.create({ url });
});

async function loadPins() {
  const box = document.getElementById("pins");
  try {
    const cfg = await getConfig();
    const resp = await fetch(`${cfg.apiUrl.replace(/\/$/, "")}/api/watch/total`, { signal: AbortSignal.timeout(10000) });
    if (!resp.ok) return;
    const data = await resp.json();
    const pins = (data.pins || []).filter(p => p.new > 0);
    if (!pins.length) { box.hidden = true; return; }
    box.hidden = false;
    box.innerHTML = `<div class="pins-title">📌 Anclas con novedades</div>` + pins.map(p => `
      <div class="pin" data-pin="${p.id}">
        <span class="pl">${esc(p.label)}</span>
        <span class="pn">◉ ${p.new}</span>
      </div>`).join("");
    box.querySelectorAll("[data-pin]").forEach(el =>
      el.addEventListener("click", () => {
        browser.tabs.create({ url: `${cfg.apiUrl.replace(/\/$/, "")}/app/` });
      }));
  } catch (e) { /* silencioso */ }
}

refresh();
loadPins();