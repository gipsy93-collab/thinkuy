/* Thinkuy — opciones de la extensión */
"use strict";

const browser = globalThis.browser || globalThis.chrome;

const DEFAULTS = {
  apiUrl: "http://localhost:8000",
  keywords: "comunicación política, ecología de los medios, narrativas televisivas, ética y estética",
  limit: 5,
  days: 180,
};

async function load() {
  const cfg = { ...DEFAULTS, ...(await browser.storage.sync.get(DEFAULTS)) };
  document.getElementById("apiUrl").value = cfg.apiUrl;
  document.getElementById("keywords").value = cfg.keywords;
  document.getElementById("limit").value = String(cfg.limit);
  document.getElementById("days").value = String(cfg.days);
  document.getElementById("notificationsEnabled").checked = cfg.notificationsEnabled !== false;
}

document.getElementById("save").addEventListener("click", async () => {
  const cfg = {
    apiUrl: document.getElementById("apiUrl").value.trim().replace(/\/+$/, ""),
    keywords: document.getElementById("keywords").value.trim(),
    limit: parseInt(document.getElementById("limit").value, 10),
    days: parseInt(document.getElementById("days").value, 10),
    notificationsEnabled: document.getElementById("notificationsEnabled").checked,
  };
  await browser.storage.sync.set(cfg);
  const st = document.getElementById("status");
  st.textContent = "✔ Configuración guardada";
  setTimeout(() => { st.textContent = ""; }, 2500);
});

document.getElementById("test").addEventListener("click", async () => {
  const st = document.getElementById("status");
  const apiUrl = document.getElementById("apiUrl").value.trim().replace(/\/+$/, "");
  try {
    const resp = await fetch(`${apiUrl}/api/health`, { signal: AbortSignal.timeout(8000) });
    const data = await resp.json();
    if (data.status === "ok") {
      st.textContent = `✔ Radar conectado · ${data.stats.articles} artículos · ${data.stats.journals} revistas`;
    } else {
      st.textContent = "✖ Respuesta inesperada del servidor";
    }
  } catch (e) {
    st.textContent = `✖ No se pudo conectar: ${e.message}`;
  }
});

load();