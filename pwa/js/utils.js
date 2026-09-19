/* Thinkuy — utilidades puras compartidas (módulo ES). */
"use strict";

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
