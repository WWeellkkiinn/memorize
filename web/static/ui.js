'use strict';

/* Shared helpers for the secondary pages (settings, admin, login).
   Exposes window.UI with: toast, confirm, api, redirectToLogin. */

(function () {
  function redirectToLogin() {
    const here = location.pathname + location.search;
    location.replace('/login?next=' + encodeURIComponent(here));
  }

  // fetch wrapper: JSON in/out, bounces to /login on 401, throws the server's
  // `detail` message on any other non-2xx so callers can show it inline.
  async function api(path, options) {
    options = options || {};
    const init = { method: options.method || 'GET', headers: {} };
    if (options.body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(options.body);
    }
    const res = await fetch(path, init);
    if (res.status === 401) {
      redirectToLogin();
      throw new Error('unauthenticated');
    }
    let data = null;
    try { data = await res.json(); } catch (_) { /* empty body */ }
    if (!res.ok) {
      const msg = (data && (data.detail || data.message)) || ('请求失败（' + res.status + '）');
      throw new Error(typeof msg === 'string' ? msg : '请求失败');
    }
    return data;
  }

  let toastTimer = null;
  function toast(message, ms) {
    let el = document.querySelector('.ui-toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'ui-toast';
      el.setAttribute('role', 'status');
      document.body.appendChild(el);
    }
    el.textContent = message;
    // force reflow so the transition replays even on repeat calls
    void el.offsetWidth;
    el.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), ms || 2200);
  }

  // Promise<boolean> confirm dialog. opts: { title, desc, confirmText,
  // cancelText, danger }. Resolves false on cancel / backdrop / Escape.
  function confirmDialog(opts) {
    opts = opts || {};
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'modal-overlay';
      overlay.innerHTML =
        '<div class="modal" role="dialog" aria-modal="true">' +
          '<h2 class="modal__title"></h2>' +
          (opts.desc ? '<p class="modal__desc"></p>' : '') +
          '<div class="modal__actions">' +
            '<button type="button" class="btn btn--pill" data-act="cancel"></button>' +
            '<button type="button" class="btn" data-act="ok"></button>' +
          '</div>' +
        '</div>';
      overlay.querySelector('.modal__title').textContent = opts.title || '确认操作';
      if (opts.desc) overlay.querySelector('.modal__desc').textContent = opts.desc;
      const cancelBtn = overlay.querySelector('[data-act="cancel"]');
      const okBtn = overlay.querySelector('[data-act="ok"]');
      cancelBtn.textContent = opts.cancelText || '取消';
      okBtn.textContent = opts.confirmText || '确认';
      okBtn.classList.add(opts.danger ? 'btn--danger-solid' : 'btn--primary');

      let settled = false;
      function close(result) {
        if (settled) return;
        settled = true;
        overlay.classList.remove('show');
        document.removeEventListener('keydown', onKey);
        setTimeout(() => overlay.remove(), 160);
        resolve(result);
      }
      function onKey(e) {
        if (e.key === 'Escape') close(false);
        else if (e.key === 'Enter') close(true);
      }
      overlay.addEventListener('click', (e) => { if (e.target === overlay) close(false); });
      cancelBtn.addEventListener('click', () => close(false));
      okBtn.addEventListener('click', () => close(true));
      document.addEventListener('keydown', onKey);

      document.body.appendChild(overlay);
      void overlay.offsetWidth;
      overlay.classList.add('show');
      okBtn.focus();
    });
  }

  // ── PWA update handling ──────────────────────────────────────────────────
  // A new service worker calls skipWaiting() on install, so it activates and
  // fires `controllerchange`. We reload once when that happens and show a toast
  // after the reload (flag survives via sessionStorage). The index/card page
  // (app.js) mirrors this with the same `mz_updated` key.
  if ('serviceWorker' in navigator) {
    let reloaded = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (reloaded) return;
      reloaded = true;
      try { sessionStorage.setItem('mz_updated', '1'); } catch (_) {}
      location.reload();
    });
  }
  window.addEventListener('load', () => {
    try {
      if (sessionStorage.getItem('mz_updated')) {
        sessionStorage.removeItem('mz_updated');
        toast('已更新到最新版本');
      }
    } catch (_) {}
  });

  // Manual "check for updates". Returns one of:
  //   'unsupported' | 'updating' (a new SW is coming, reload imminent) | 'latest'
  async function checkForUpdate() {
    if (!('serviceWorker' in navigator)) return 'unsupported';
    const reg = await navigator.serviceWorker.getRegistration();
    if (!reg) return 'unsupported';
    try { await reg.update(); } catch (_) { /* offline / fetch failed */ }
    await new Promise((r) => setTimeout(r, 1200));
    if (reg.installing || reg.waiting) return 'updating';
    return 'latest';
  }

  window.UI = {
    toast: toast,
    confirm: confirmDialog,
    api: api,
    redirectToLogin: redirectToLogin,
    checkForUpdate: checkForUpdate,
  };
})();
