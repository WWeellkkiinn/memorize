'use strict';

/* User-management tab inside the settings overlay. Admin-only, lazy-loaded the
   first time the 用户管理 tab is shown. Renders one card per user (tap to expand
   detail + actions). Relies on window.UI (ui.js); driven by window.AdminTab,
   which settings.js calls: enable() once the viewer is confirmed admin, and
   ensureLoaded() when the tab is first opened. */

(function () {
  const $ = (id) => document.getElementById(id);
  let enabled = false;
  let loaded = false;

  function el(tag, props, ...kids) {
    const node = document.createElement(tag);
    if (props) Object.assign(node, props);
    for (const k of kids) if (k != null) node.append(k);
    return node;
  }

  function badge(isAdmin) {
    return el('span', {
      className: 'user-card__badge ' + (isAdmin ? 'is-admin' : 'is-user'),
      textContent: isAdmin ? '管理员' : '普通',
    });
  }

  function renderUser(u) {
    const card = el('div', { className: 'user-card' });

    const head = el('button', { type: 'button', className: 'user-card__head' },
      el('span', { className: 'user-card__email', textContent: u.email }),
      badge(u.is_admin),
      el('span', { className: 'user-card__chevron', textContent: '›' }),
    );
    head.addEventListener('click', () => card.classList.toggle('is-open'));

    const meta = el('div', { className: 'user-card__meta' },
      el('span', { textContent: 'ID ' + u.id }),
      el('span', { textContent: '注册 ' + (u.created_at ? String(u.created_at).slice(0, 10) : '—') }),
    );

    const resetBtn = el('button', { type: 'button', className: 'btn btn--soft btn-sm', textContent: '重置密码' });
    const delBtn = el('button', { type: 'button', className: 'btn btn--danger btn-sm', textContent: '删除' });
    const actions = el('div', { className: 'user-card__actions' }, resetBtn, delBtn);
    const detail = el('div', { className: 'user-card__detail' }, meta, actions);

    resetBtn.addEventListener('click', () => toggleReset(u, detail));
    delBtn.addEventListener('click', () => removeUser(u));

    card.append(head, detail);
    return card;
  }

  function toggleReset(u, detail) {
    const existing = detail.querySelector('.reset-inline');
    if (existing) { existing.remove(); return; }

    const input = el('input', { type: 'text', className: 'input', placeholder: '新密码（≥8 位）', autocomplete: 'off' });
    const ok = el('button', { type: 'button', className: 'btn btn--primary btn-sm', textContent: '确认' });
    const cancel = el('button', { type: 'button', className: 'btn btn--pill btn-sm', textContent: '取消' });
    const row = el('div', { className: 'reset-inline' }, input, ok, cancel);

    cancel.addEventListener('click', () => row.remove());
    ok.addEventListener('click', async () => {
      const pw = input.value;
      if (pw.length < 8) { UI.toast('密码至少 8 位'); return; }
      ok.disabled = true;
      try {
        await UI.api(`/api/admin/users/${u.id}/password`, { method: 'POST', body: { password: pw } });
        UI.toast('密码已重置');
        row.remove();
      } catch (err) {
        UI.toast(err.message);
        ok.disabled = false;
      }
    });

    detail.append(row);
    input.focus();
  }

  async function removeUser(u) {
    const ok = await UI.confirm({
      title: '删除用户？',
      desc: `将永久删除 ${u.email} 的账号及其全部复习进度，无法恢复。`,
      confirmText: '删除',
      danger: true,
    });
    if (!ok) return;
    try {
      await UI.api(`/api/admin/users/${u.id}`, { method: 'DELETE' });
      UI.toast('已删除');
      await load();
    } catch (err) {
      UI.toast(err.message);
    }
  }

  async function load() {
    try {
      const data = await UI.api('/api/admin/users');
      const wrap = $('user-list');
      wrap.replaceChildren();
      for (const u of (data.users || [])) wrap.append(renderUser(u));
      loaded = true;
    } catch (err) {
      UI.toast(err.message);
    }
  }

  // ── Create user (collapsible form) ────────────────────────────────────────
  function initCreate() {
    const toggle = $('create-toggle');
    const form = $('create-form');
    const chevron = toggle.querySelector('.nav-row__chevron');

    toggle.addEventListener('click', () => {
      form.classList.toggle('hidden');
      chevron.textContent = form.classList.contains('hidden') ? '＋' : '−';
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = $('c-email').value.trim();
      const password = $('c-pass').value;
      const msg = $('create-msg');
      const btn = $('create-btn');
      msg.className = 'msg';
      msg.textContent = '';
      if (!email) { msg.className = 'msg msg--error'; msg.textContent = '请输入邮箱'; return; }
      if (password.length < 8) { msg.className = 'msg msg--error'; msg.textContent = '密码至少 8 位'; return; }

      btn.disabled = true;
      try {
        await UI.api('/api/admin/users', {
          method: 'POST',
          body: { email, password, is_admin: $('c-admin').checked },
        });
        UI.toast('已创建');
        $('c-email').value = '';
        $('c-pass').value = '';
        $('c-admin').checked = false;
        form.classList.add('hidden');
        chevron.textContent = '＋';
        await load();
      } catch (err) {
        msg.className = 'msg msg--error';
        msg.textContent = err.message;
      } finally {
        btn.disabled = false;
      }
    });
  }

  window.AdminTab = {
    enable() {
      if (enabled) return;
      enabled = true;
      initCreate();
    },
    ensureLoaded() {
      if (!loaded) load();
    },
  };
})();
