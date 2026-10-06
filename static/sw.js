// Nestor am Handy: Service Worker nur für Installierbarkeit und eine Offline-Seite.
// Immer zuerst das Netz – eine alte Fassung im Handy darf nie mit einem neueren Laptop sprechen (Teachbuddy, 14.09.).
const CACHE = "nestor-handy";
const SCHALE = ["/handy", "/static/basis.js", "/static/handy.js", "/static/style.css", "/static/handy.css"];

self.addEventListener("install", (e) => { self.skipWaiting(); e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SCHALE)).catch(() => {})); });
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || !SCHALE.includes(url.pathname)) return;
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok) { const kopie = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, kopie)); }
    return r;
  }).catch(() => caches.match(e.request)));
});
