/* Thinkuy — utilidades puras compartidas (módulo ES). */
"use strict";

import { esc } from "./dom.js";

/** Antirrebote: agrupa llamadas seguidas en una sola. */
export function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/** Normaliza una lista de palabras clave heterogénea a cadenas limpias. */
export function keywordStrings(list) {
  return (Array.isArray(list) ? list : [])
    .map(k => {
      if (typeof k === "string") return k.trim();
      if (k && typeof k === "object") return String(k.keyword ?? k.k ?? k.display_name ?? "").trim();
      return "";
    })
    .filter(Boolean);
}

/** Chip de palabra clave seleccionable. */
export function selectableKeywordChip(keyword) {
  const text = String(keyword || "").trim();
  if (!text) return "";
  return `<button type="button" class="keyword-chip is-selectable" data-keyword-toggle data-keyword="${esc(text)}" aria-pressed="false" title="Seleccionar palabra clave para anclar">${esc(text)}</button>`;
}

/** Línea de autores abreviada (máx. 3 + «et al.»). */
export function authorsLine(a) {
  const aus = (a.authors || []).map(au => `${au.family || ""} ${au.given || ""}`.trim()).filter(Boolean);
  if (!aus.length) return "Autores no disponibles";
  if (aus.length <= 3) return aus.join(", ");
  return `${aus.slice(0, 3).join(", ")} et al.`;
}

/** Extrae la forma canónica de un DOI (10.xxxx/…), desde URL o texto. */
export function extractCleanDoi(val) {
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
