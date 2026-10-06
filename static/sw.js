// Nestor am Handy: Service Worker nur für Installierbarkeit und eine Offline-Seite.
// Immer zuerst das Netz – eine alte Fassung im Handy darf nie mit einem neueren Laptop sprechen (Teachbuddy, 14.09.).
const CACHE = "nestor-handy-2";
const SCHALE = ["/handy", "/static/basis.js", "/static/handy.js", "/static/style.css", "/static/handy.css"];

self.addEventListener("install", (e) => { self.skipWaiting(); e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SCHALE)).catch(() => {})); });
self.addEventListener("activate", (e) => e.waitUntil(caches.keys()
  .then((k) => Promise.all(k.filter((n) => n !== CACHE).map((n) => caches.delete(n)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // mit Parametern (Kopplung /handy?k=…, Umleitung) nie anfassen – eine umgeleitete Antwort darf keine Navigation beantworten
  if (e.request.method !== "GET" || url.origin !== location.origin || url.search || !SCHALE.includes(url.pathname)) return;
  // cache: no-cache – sonst liefert der HTTP-Zwischenspeicher des Browsers die alte Fassung (Test 06.10.: altes CSS)
  e.respondWith(fetch(url.href, { cache: "no-cache", credentials: "same-origin" }).then((r) => {
    if (r.ok) { const kopie = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, kopie)); }
    return r;
  }).catch(() => caches.match(e.request)));
});
