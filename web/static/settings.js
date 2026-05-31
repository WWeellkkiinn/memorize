'use strict';

/* Settings overlay controller. Opens an in-page sheet over the card view — no
   navigation, so the flashcard underneath stays mounted and returning costs
   zero reload. Handles tabs, account info, password change, version/update,
   logout, and the back gesture (a pushed history entry closes the sheet).
   Relies on window.UI (ui.js); cooperates with admin.js via window.AdminTab. */

(function () {
  const $ = (id) => document.getElementById(id);
  const overlay = $('overlay');
  const body = overlay.querySelector('.overlay__body');
  const openBtn = $('settings-link');

  let isOpen = false;
  let closing = false;
  let accountLoaded = false;
  let versionLoaded = false;
  let pendingTab = null; // a tab requested via deep link, applied once account loads

  // ── Open / close ────────────────────────────────────────────────────────
  function showOverlay() {
    if (isOpen) return;
    isOpen = true;
    closing = false;
    overlay.classList.remove('hidden');
    overlay.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(() => overlay.classList.add('show'));
    loadAccount();
    loadVersion();
  }

  function hideOverlay() {
    if (!isOpen) return;
    isOpen = false;
    closing = false;
    overlay.classList.remove('show');
    overlay.setAttribute('aria-hidden', 'true');
    setTimeout(() => { if (!isOpen) overlay.classList.add('hidden'); }, 260);
  }

  // Open pushes a history entry so the hardware/back gesture closes the sheet
  // (popstate → hideOverlay) instead of leaving the app.
  function open() {
    history.pushState({ mzOverlay: true }, '');
    showOverlay();
  }

  function close() {
    if (!isOpen || closing) return;
    if (history.state && history.state.mzOverlay) {
      // Debounce: a second close() before popstate lands must not back() again,
      // or the extra pop would skip past the overlay entry and leave the page.
      closing = true;
      history.back(); // → popstate → hideOverlay (clears the flag)
    } else {
      hideOverlay();
    }
  }

  openBtn.addEventListener('click', open);
  overlay.addEventListener('click', (e) => {
    if (e.target.closest('[data-close]')) close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isOpen) close();
  });
  window.addEventListener('popstate', () => {
    if (isOpen) hideOverlay();
  });

  // ── Tabs ──────────────────────────────────────────────────────────────────
  const tabs = Array.from(overlay.querySelectorAll('.tab'));
  const panes = Array.from(overlay.querySelectorAll('.tabpane'));
  function selectTab(name) {
    tabs.forEach((t) => t.classList.toggle('is-active', t.dataset.tab === name));
    panes.forEach((p) => p.classList.toggle('is-active', p.dataset.pane === name));
    body.scrollTop = 0;
    if (name === 'users' && window.AdminTab) window.AdminTab.ensureLoaded();
  }
  tabs.forEach((t) => t.addEventListener('click', () => selectTab(t.dataset.tab)));

  // ── Account (loaded once, then cached) ──────────────────────────────────
  async function loadAccount() {
    if (accountLoaded) return;
    try {
      const { user } = await UI.api('/api/auth/me');
      $('acc-email').textContent = user.email || '—';
      $('acc-role').textContent = user.is_admin ? '管理员' : '普通用户';
      if (user.is_admin) {
        overlay.querySelector('.tab[data-tab="users"]').hidden = false;
        if (window.AdminTab) window.AdminTab.enable();
      }
      // 管理员状态已确定，整条 tab 栏此刻才一次性显示（CSS .is-account-ready）。
      overlay.classList.add('is-account-ready');
      accountLoaded = true;
      // Honor a tab requested via deep link (e.g. /admin → #admin → 用户管理),
      // now that admin status is known and the users tab is revealed.
      if (pendingTab) {
        if (pendingTab !== 'users' || user.is_admin) selectTab(pendingTab);
        pendingTab = null;
      }
    } catch (_) { /* UI.api already bounced to /login on 401 */ }
  }

  async function loadVersion() {
    if (versionLoaded) return;
    try {
      const data = await UI.api('/api/version');
      $('app-version').textContent = data.version || '—';
      versionLoaded = true;
    } catch (_) {
      $('app-version').textContent = '—';
    }
  }

  // ── Change password ───────────────────────────────────────────────────────
  $('pw-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const cur = $('pw-current').value;
    const next = $('pw-new').value;
    const confirm = $('pw-confirm').value;
    const msg = $('pw-msg');
    const btn = $('pw-submit');
    msg.className = 'msg';
    msg.textContent = '';
    if (next.length < 8) {
      msg.className = 'msg msg--error';
      msg.textContent = '新密码至少 8 位';
      return;
    }
    if (next !== confirm) {
      msg.className = 'msg msg--error';
      msg.textContent = '两次输入的新密码不一致';
      return;
    }
    btn.disabled = true;
    btn.textContent = '保存中…';
    try {
      await UI.api('/api/auth/password', {
        method: 'POST',
        body: { current_password: cur, new_password: next },
      });
      UI.toast('密码已修改，请重新登录');
      setTimeout(() => { location.href = '/login'; }, 1200);
    } catch (err) {
      msg.className = 'msg msg--error';
      msg.textContent = err.message;
      btn.disabled = false;
      btn.textContent = '保存';
    }
  });

  // ── Check for updates ─────────────────────────────────────────────────────
  $('update-btn').addEventListener('click', async () => {
    const btn = $('update-btn');
    btn.disabled = true;
    btn.textContent = '检查中…';
    const result = await UI.checkForUpdate();
    if (result === 'updating') {
      btn.textContent = '正在更新…'; // ui.js reloads the page on controllerchange
      return;
    }
    UI.toast(result === 'latest' ? '已是最新版本' : '当前环境不支持更新检测');
    btn.disabled = false;
    btn.textContent = '检查更新';
  });

  // ── Logout ────────────────────────────────────────────────────────────────
  $('logout-btn').addEventListener('click', async () => {
    const ok = await UI.confirm({
      title: '退出登录？',
      desc: '退出后需要重新输入邮箱和密码登录。',
      confirmText: '退出',
      danger: true,
    });
    if (!ok) return;
    await UI.api('/api/auth/logout', { method: 'POST' });
    location.href = '/login';
  });

  // ── Deep link: /settings & /profile → #settings；/admin → #admin ─────────
  // (#admin lands on the 用户管理 tab once account info confirms admin.)
  if (location.hash === '#settings' || location.hash === '#admin') {
    if (location.hash === '#admin') pendingTab = 'users';
    // strip the hash without adding history, then open with a closeable entry
    history.replaceState(null, '', location.pathname + location.search);
    open();
  }
})();
