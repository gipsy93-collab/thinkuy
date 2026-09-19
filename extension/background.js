/* Thinkuy — service worker de fondo: badge con nuevas publicaciones de las
   keywords ancladas (cada 6 horas) + notificaciones del sistema. */
"use strict";

const browser = globalThis.browser || globalThis.chrome;

const DEFAULTS = {
  apiUrl: "http://localhost:8000",
  keywords: "comunicación política, ecología de los medios, narrativas televisivas, ética y estética",
  limit: 5,
  days: 365,
  notificationsEnabled: true,
};

let lastTotal = 0;

async function getConfig() {
  const stored = await browser.storage.sync.get(DEFAULTS);
  return { ...DEFAULTS, ...stored };
}

async function updateBadge() {
  try {
    const cfg = await getConfig();
    const apiUrl = cfg.apiUrl.replace(/\/$/, "");

    // 1) Prioridad: nuevas publicaciones de las keywords ancladas
    try {
      const resp = await fetch(`${apiUrl}/api/watch/total`, { signal: AbortSignal.timeout(15000) });
      if (resp.ok) {
        const data = await resp.json();
        const total = data.total || 0;
        browser.action.setBadgeText({ text: total > 0 ? String(Math.min(total, 99)) : "" });
        browser.action.setBadgeBackgroundColor({ color: "#F59E0B" });
        if (cfg.notificationsEnabled && total > 0 && total > lastTotal) {
          notify(total);
        }
        lastTotal = total;
        return;
      }
    } catch (e) { /* el servidor de anclas no está disponible → probar feed */ }

    // 2) Fallback: cuenta del feed personalizado
    const params = new URLSearchParams({ keywords: cfg.keywords, limit: cfg.limit, days: cfg.days });
    const resp = await fetch(`${apiUrl}/api/feed?${params}`, { signal: AbortSignal.timeout(15000) });
    if (!resp.ok) return;
    const data = await resp.json();
    const n = data.count || 0;
    browser.action.setBadgeText({ text: n > 0 ? String(n) : "" });
    browser.action.setBadgeBackgroundColor({ color: "#F59E0B" });
  } catch (e) {
    browser.action.setBadgeText({ text: "?" });
    browser.action.setBadgeBackgroundColor({ color: "#F87171" });
  }
}

function notify(total) {
  browser.notifications.create("radar-new", {
    type: "basic",
    iconUrl: "icons/icon128.png",
    title: "Thinkuy",
    message: `${total} nueva${total === 1 ? "" : "s"} publicación${total === 1 ? "" : "es"} coincide${total === 1 ? "" : "n"} con tus keywords ancladas.`,
    priority: 1,
  });
}

browser.notifications.onClicked.addListener(async id => {
  if (id === "radar-new") {
    const cfg = await getConfig();
    browser.tabs.create({ url: `${cfg.apiUrl.replace(/\/$/, "")}/app/` });
    browser.notifications.clear(id);
  }
});

browser.runtime.onInstalled.addListener(() => {
  browser.alarms.create("radar-refresh", { periodInMinutes: 360 });
  if (browser.contextMenus) {
    browser.contextMenus.create({
      id: "radar-open",
      title: "Abrir Thinkuy",
      contexts: ["action"],
    });
  }
  updateBadge();
});

browser.runtime.onStartup.addListener(() => updateBadge());

browser.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === "radar-refresh") updateBadge();
});

if (browser.contextMenus) {
  browser.contextMenus.onClicked.addListener(async info => {
    if (info.menuItemId === "radar-open") {
      const cfg = await getConfig();
      browser.tabs.create({ url: `${cfg.apiUrl.replace(/\/$/, "")}/app/` });
    }
  });
}