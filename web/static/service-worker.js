'use strict';

// Network-first service worker.
//
// 在线时每次都拉最新的 HTML/CSS/JS（源站已对 HTML/manifest 设 no-cache、对 /static 设
// no-cache，Cloudflare 与浏览器只做廉价的条件校验，未变即 304），缓存仅作离线兜底。
// 这样任何部署都能即时到达设备，不再依赖 ?v= 版本号（旧实现 ignoreSearch 把它废掉了），
// 也不再依赖每次记得 bump CACHE 名。代价：在线启动多几个 304 校验请求；离线用上次缓存。
const CACHE = 'memorize-v9';
const ASSETS = [
  '/', '/login',
  '/static/style.css', '/static/app.js',
  '/static/login.css', '/static/login.js',
  '/static/ui.css', '/static/ui.js',
  '/static/overlay2.css', '/static/settings.js', '/static/admin.js',
  '/manifest.webmanifest',
  '/static/icon-192.png', '/static/icon-512.png',
];

self.addEventListener('install', e => {
  // 预缓存外壳，保证首次离线也能打开；个别失败可容忍。
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

// 网络优先：同源 GET（含导航）先走网络拿最新并顺手更新缓存，网络失败再回退缓存。
// /api/ 永不拦截（鉴权敏感，必须直连且看到真实错误）；跨源（字体/发音）也不拦。
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;

  e.respondWith(
    fetch(e.request)
      .then(resp => {
        // 只缓存正常的非重定向响应（重定向响应缓存给导航会触发浏览器报错）。
        if (resp && resp.ok && !resp.redirected) {
          const copy = resp.clone();
          caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => {});
        }
        return resp;
      })
      .catch(() =>
        caches.match(e.request, { ignoreSearch: true })
          .then(cached => cached || (e.request.mode === 'navigate'
            ? caches.match('/', { ignoreSearch: true })
            : undefined))
      )
  );
});
