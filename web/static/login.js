'use strict';

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/service-worker.js').catch(() => {});
}

const form = document.getElementById('login-form');
const emailEl = document.getElementById('email');
const passEl = document.getElementById('password');
const submitEl = document.getElementById('submit');
const errorEl = document.getElementById('error');

// Already signed in? Skip the form.
fetch('/api/auth/me').then(r => { if (r.ok) location.replace('/'); }).catch(() => {});

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
      location.replace('/');
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
