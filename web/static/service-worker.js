'use strict';

const CACHE = 'memorize-v4';
const ASSETS = [
  '/', '/login',
  '/static/style.css', '/static/app.js',
  '/static/login.css', '/static/login.js',
  '/static/ui.css', '/static/ui.js',
  '/static/overlay.css', '/static/settings.js', '/static/admin.js',
  '/manifest.webmanifest',
  '/static/icon-192.png', '/static/icon-512.png',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => Promise.allSettled(ASSETS.map(a => c.add(a))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Never cache API calls (auth-sensitive, must hit the network). Static GETs are
// served cache-first so the app shell opens offline; navigations fall back to
// the cached index on network failure.
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.pathname.startsWith('/api/')) return;

  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).catch(() =>
        caches.match('/', { ignoreSearch: true })
          .then(cached => cached || caches.match(e.request, { ignoreSearch: true }))
      )
    );
    return;
  }
  // ignoreSearch so cache-busting query strings (e.g. ?v=63) still match the
  // precached path-only entries in ASSETS.
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then(cached => cached || fetch(e.request)));
});
