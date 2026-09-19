/* Thinkuy — estado compartido y persistencia local (módulo ES). */
"use strict";

export const CONFIG_KEY = "thinkuy-config";
export const RADAR_FILTER_STORAGE_KEY = "thinkuy-radar-filters-v1";

export const DEFAULT_CONFIG = {
  keywords: "comunicación política, ecología de los medios, narrativas televisivas, ética y estética",
  langs: ["es", "pt"],
  sources: ["scielo", "crossref", "openalex", "redalyc"],
  limit: 20,
  days: 3650,
  sort: "relevance",
};

export function loadConfig() {
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

export function saveConfig() {
  localStorage.setItem(CONFIG_KEY, JSON.stringify(state.config));
}

export function loadRadarFilters() {
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

export function saveRadarFilters() {
  try {
    localStorage.setItem(RADAR_FILTER_STORAGE_KEY, JSON.stringify({
      excluded: state.radarExcluded || [],
      included: state.radarIncluded || [],
      names: state.radarExcludedNames || {},
    }));
  } catch (e) { /* almacenamiento no disponible */ }
}

export const state = {
  config: loadConfig(),
  deferredPrompt: null,
  radarExcluded: [],
  radarIncluded: [],
  radarExcludedNames: {},
  currentEpistemicRoles: [],
  screeningProtocolId: null,
  screeningArticlesCache: [],
  radarComparedJournals: [],
  currentHomePersona: "researcher",
  currentJournalAuditData: null,
  currentLibrarianData: null,
  lastLibrarianData: null,
  epistemicSubmotorLoaded: false,
  reviewSubmotorLoaded: false,
  activeEpistemicRoleFilter: "all",
  activeEpistemicSourceFilter: "all",
  currentSocraticData: null,
  currentConcertedData: null,
};
