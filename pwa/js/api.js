/* Thinkuy — cliente HTTP y base de la API (módulo ES). */
"use strict";

export const API = "/api";

/** Petición GET/POST a la API con timeout y mensajes de error claros. */
export async function api(path, params = {}, opts = {}) {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") {
      if (Array.isArray(v)) {
        v.forEach(item => {
          if (item !== undefined && item !== null && item !== "") {
            qs.append(k, item);
          }
        });
      } else {
        qs.set(k, v);
      }
    }
  });
  const url = `${API}${path}${qs.toString() ? "?" + qs : ""}`;
  // Sin timeout, una petición colgada deja la promesa pendiente para siempre y la interfaz
  // parece muerta. `timeoutMs: 0` desactiva el límite.
  const timeoutMs = opts.timeoutMs === undefined ? 20000 : opts.timeoutMs;
  const controlador = new AbortController();
  const temporizador = timeoutMs > 0 ? setTimeout(() => controlador.abort(), timeoutMs) : null;
  let resp;
  try {
    const headers = { Accept: "application/json", ...(opts.headers || {}) };
    if (opts.body && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    resp = await fetch(url, {
      method: opts.method || "GET",
      headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      signal: controlador.signal,
    });
  } catch (e) {
    const alt = url.replace(window.location.origin, "");
    if (e && e.name === "AbortError") {
      throw new Error(`la petición a ${alt} tardó más de ${Math.round(timeoutMs / 1000)} s y se canceló.`);
    }
    throw new Error(`no se pudo contactar ${alt} (${url}). ¿Está corriendo el backend? Usa "inicio.bat" o arranca uvicorn.`);
  } finally {
    if (temporizador) clearTimeout(temporizador);
  }
  if (!resp.ok) throw new Error(`API ${resp.status}: ${url}`);
  return resp.json();
}

export async function apiPost(path, body, opts = {}) {
  return api(path, {}, { ...opts, method: "POST", body });
}

window.__API_BASE = API;
