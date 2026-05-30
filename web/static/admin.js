'use strict';

const usersBody = document.getElementById('users-body');
const createForm = document.getElementById('create-form');
const createMsg = document.getElementById('create-msg');

function setMsg(el, text, ok) {
  el.textContent = text;
  el.className = 'msg ' + (ok ? 'ok' : 'err');
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (res.status === 401) { location.replace('/login'); throw new Error('unauth'); }
  if (res.status === 403) { location.replace('/'); throw new Error('forbidden'); }
  return res;
}

function el(tag, props, ...children) {
  const node = document.createElement(tag);
  if (props) Object.assign(node, props);
  for (const c of children) node.append(c);
  return node;
}

function renderUsers(users) {
  usersBody.replaceChildren();
  for (const u of users) {
    const role = u.is_admin ? el('span', { className: 'badge', textContent: '管理员' }) : document.createTextNode('用户');

    const resetBtn = el('button', { className: 'btn-ghost', textContent: '重置密码' });
    resetBtn.addEventListener('click', () => resetPassword(u));
    const delBtn = el('button', { className: 'btn-danger', textContent: '删除' });
    delBtn.addEventListener('click', () => deleteUser(u));

    const actions = el('div', { className: 'row-actions' }, resetBtn, delBtn);

    usersBody.append(el('tr', null,
      el('td', { textContent: String(u.id) }),
      el('td', { textContent: u.email }),
      el('td', { textContent: u.display_name || '' }),
      el('td', null, role),
      el('td', null, actions),
    ));
  }
}

async function loadUsers() {
  try {
    const res = await api('/api/admin/users');
    const data = await res.json();
    renderUsers(data.users || []);
  } catch (_) {}
}

createForm.addEventListener('submit', async e => {
  e.preventDefault();
  setMsg(createMsg, '', true);
  const body = {
    email: document.getElementById('c-email').value.trim(),
    display_name: document.getElementById('c-name').value.trim(),
    password: document.getElementById('c-pass').value,
    is_admin: document.getElementById('c-admin').checked,
  };
  try {
    const res = await api('/api/admin/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      setMsg(createMsg, '创建成功', true);
      createForm.reset();
      loadUsers();
    } else {
      let msg = '创建失败';
      try { msg = (await res.json()).detail || msg; } catch (_) {}
      setMsg(createMsg, msg, false);
    }
  } catch (_) {
    setMsg(createMsg, '网络错误', false);
  }
});

async function resetPassword(u) {
  const pw = prompt(`为 ${u.email} 设置新密码（≥8 位）：`);
  if (!pw) return;
  const res = await api(`/api/admin/users/${u.id}/password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password: pw }),
  });
  if (res.ok) alert('密码已更新，该用户已被登出');
  else {
    let msg = '更新失败';
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    alert(msg);
  }
}

async function deleteUser(u) {
  if (!confirm(`确定删除用户 ${u.email}？该用户的复习进度将一并删除。`)) return;
  const res = await api(`/api/admin/users/${u.id}`, { method: 'DELETE' });
  if (res.ok) loadUsers();
  else {
    let msg = '删除失败';
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    alert(msg);
  }
}

loadUsers();
