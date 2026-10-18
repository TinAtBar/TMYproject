// mobile: Service Worker – App-Shell offline verfügbar (Netz zuerst, Cache als Rückfall).
// Neue Server-Version → neue Dateien kommen automatisch über das Netz; VERSION erhöhen räumt alte Caches.
const VERSION = 'barlagepm-shell-2.7.0';
const SHELL = ['./', 'index.html', 'css/styles.css', 'css/mobil.css', 'css/ablage.css', 'css/fortschritt.css', 'css/budget.css', 'css/optik.css', 'css/masken.css', 'css/dashboard.css', 'css/cockpit.css', 'css/fertigung-r27.css', 'css/exporte.css', 'css/tickets.css', 'css/glanz.css', 'css/dstil-glas.css', 'css/dstil-leitstand.css', 'css/freigaben.css', 'js/app.js', 'manifest.webmanifest', 'icons/icon-180.png', 'icons/icon-192.png', 'icons/logo.png', 'icons/favicon.ico'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION).then(c => Promise.all(SHELL.map(u => c.add(u).catch(() => null)))).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request; const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/') || url.pathname.startsWith('/zertifikat')) return;
  e.respondWith((async () => {
    const cache = await caches.open(VERSION);
    try {
      const res = await fetch(req, { cache: 'no-cache' });
      if (res.ok) cache.put(req.mode === 'navigate' ? 'index.html' : req, res.clone());
      return res;
    } catch (err) {
      const hit = await cache.match(req.mode === 'navigate' ? 'index.html' : req, { ignoreSearch: req.mode === 'navigate' });
      if (hit) return hit;
      if (req.mode === 'navigate') { const idx = await cache.match('index.html'); if (idx) return idx; }
      return new Response('Offline', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
    }
  })());
});
