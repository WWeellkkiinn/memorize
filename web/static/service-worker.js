'use strict';

const CACHE = 'memorize-v2';
const ASSETS = [
  '/', '/login', '/profile',
  '/static/style.css', '/static/app.js',
  '/static/login.css', '/static/login.js',
  '/static/profile.js',
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
    e.respondWith(fetch(e.request).catch(() => caches.match('/') || caches.match(e.request)));
    return;
  }
  e.respondWith(caches.match(e.request).then(cached => cached || fetch(e.request)));
});
