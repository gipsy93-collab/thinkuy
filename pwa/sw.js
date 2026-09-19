/* Thinkuy — Service Worker: shell offline + API directa sin caché */
"use strict";

const CACHE = "thinkuy-v73";
const SHELL = [
  "./",
  "./index.html",
  "./css/style.css?v=5.49",
  "./js/app.js?v=5.49",
  "./js/api.js",
  "./js/dom.js",
  "./js/state.js",
  "./widget.html",
  "./embed.js",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/icon.svg",
  "./icons/logo-rpc-original.png",
];

self.addEventListener("install", e => {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(SHELL))
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;

  // Las llamadas a la API siempre van directamente a la red
  if (req.url.includes("/api/")) {
    e.respondWith(fetch(req));
    return;
  }

  // Red primero siempre, caché como respaldo offline (evita assets congelados)
  e.respondWith(
    fetch(req)
      .then(resp => {
        if (resp && resp.ok) {
          const copy = resp.clone();
          caches.open(CACHE).then(c => c.put(req, copy));
        }
        return resp;
      })
      .catch(() => caches.match(req).then(hit => hit || Response.error()))
  );
});