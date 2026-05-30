'use strict';

const form = document.getElementById('pw-form');
const curEl = document.getElementById('cur');
const newEl = document.getElementById('new');
const confirmEl = document.getElementById('confirm');
const submitEl = document.getElementById('submit');
const msgEl = document.getElementById('msg');
const whoEl = document.getElementById('who');

// Require login; show who we are.
fetch('/api/auth/me')
  .then(r => { if (!r.ok) { location.replace('/login'); throw new Error('unauth'); } return r.json(); })
  .then(d => { if (d.user) whoEl.textContent = `${d.user.email} · 修改登录密码`; })
  .catch(() => {});

form.addEventListener('submit', async e => {
  e.preventDefault();
  msgEl.textContent = '';
  if (newEl.value !== confirmEl.value) {
    msgEl.textContent = '两次输入的新密码不一致';
    return;
  }
  submitEl.disabled = true;
  submitEl.textContent = '保存中…';
  try {
    const res = await fetch('/api/auth/password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: curEl.value, new_password: newEl.value }),
    });
    if (res.ok) {
      // Password change revokes all sessions — go re-login with the new password.
      alert('密码已修改，请用新密码重新登录');
      location.replace('/login');
      return;
    }
    let m = '修改失败';
    try { m = (await res.json()).detail || m; } catch (_) {}
    msgEl.textContent = m;
  } catch (_) {
    msgEl.textContent = '网络错误，请重试';
  } finally {
    submitEl.disabled = false;
    submitEl.textContent = '保 存';
  }
});
