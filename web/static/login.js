'use strict';

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/service-worker.js').catch(() => {});
}

const form = document.getElementById('login-form');
const emailEl = document.getElementById('email');
const passEl = document.getElementById('password');
const submitEl = document.getElementById('submit');
const errorEl = document.getElementById('error');

// Where to land after login. Resolve `next` against our own origin and only honor
// it if it stays same-origin — this rejects open-redirect tricks like //evil.com
// and /\evil.com (which browsers normalize to a foreign origin). Default to '/'.
function nextTarget() {
  const raw = new URLSearchParams(location.search).get('next');
  if (raw) {
    try {
      const u = new URL(raw, location.origin);
      // same-origin only, and never bounce back to /login (would loop)
      if (u.origin === location.origin && u.pathname !== '/login') {
        return u.pathname + u.search + u.hash;
      }
    } catch (_) {}
  }
  return '/';
}

// Already signed in? Skip the form.
fetch('/api/auth/me').then(r => { if (r.ok) location.replace(nextTarget()); }).catch(() => {});

form.addEventListener('submit', async e => {
  e.preventDefault();
  errorEl.textContent = '';
  submitEl.disabled = true;
  submitEl.textContent = '登录中…';
  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: emailEl.value.trim(), password: passEl.value }),
    });
    if (res.ok) {
      location.replace(nextTarget());
      return;
    }
    let msg = '登录失败';
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    errorEl.textContent = msg;
  } catch (_) {
    errorEl.textContent = '网络错误，请重试';
  } finally {
    submitEl.disabled = false;
    submitEl.textContent = '登 录';
  }
});
