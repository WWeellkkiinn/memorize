'use strict';

const MORPHEME_TYPES = new Set(['prefix', 'root', 'bound', 'free']);

const STAGE_COLORS = {
  '新词': 'var(--stage-new)',
  '初识': 'var(--stage-familiar)',
  '记忆': 'var(--stage-memory)',
  '熟悉': 'var(--stage-known)',
  '掌握': 'var(--stage-mastered)',
};

const state = {
  phase: 0,         // 0=loading, 1=self-test, 2=revealed
  word: null,
  stats: null,
  progress: null,
  intervals: null,
  next: null,       // pre-fetched next word
  countdownSec: 3,
  countdownTimer: null,
  revealTimer: null,
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const card          = $('card');
const wordPos       = $('word-pos');
const wordText      = $('word-text');
const wordPhone     = $('word-phonetic');
const hintArea      = $('hint-area');
const hintText      = $('hint-text');
const definition    = $('definition');
const examples      = $('examples');
const ratingRow     = $('rating-row');
const statStage     = $('stat-stage');
const statProgress  = $('stat-progress');
const statCounts    = $('stat-counts');
const toast         = $('toast');

// ── Utilities ─────────────────────────────────────────────────────────────────

function formatInterval(days) {
  if (days <= 1)   return '1天';
  if (days < 7)    return days + '天';
  if (days < 30)   return Math.round(days / 7) + '周';
  if (days < 365)  return Math.round(days / 30) + '个月';
  return (days / 365).toFixed(1) + '年';
}

function show(el)    { el.classList.remove('hidden'); el.classList.remove('invisible'); }
function hide(el)    { el.classList.add('hidden'); }
function visHide(el) { el.classList.add('invisible'); }
function visShow(el) { el.classList.remove('invisible'); }

function reveal(el) {
  el.classList.add('revealing');
  el.addEventListener('animationend', () => el.classList.remove('revealing'), { once: true });
}

function escHtml(s) {
  return String(s || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

const _isCVC = s => {
  if (s.length < 3) return false;
  const [a, b, c] = [s[s.length-3], s[s.length-2], s[s.length-1]];
  return /[bcdfghjklmnpqrstvwxyz]/i.test(a)
    && /[aeiou]/i.test(b)
    && /[bcdfghjklmnpqrstvwxyz]/i.test(c)
    && !/[wxy]/i.test(c);
};

function regularForms(baseWord) {
  const w = String(baseWord || '').trim().toLowerCase();
  if (!/^[a-z]+$/.test(w) || w.length < 2) return [w].filter(Boolean);
  const consonantY = /[^aeiou]y$/.test(w);
  const cvc        = _isCVC(w);
  const forms = new Set([w]);
  if (/[sxz]$|[cs]h$/.test(w)) forms.add(w + 'es');
  else if (consonantY)          forms.add(w.slice(0, -1) + 'ies');
  else                          forms.add(w + 's');
  if (consonantY)               forms.add(w.slice(0, -1) + 'ied');
  else if (/e$/.test(w))        forms.add(w + 'd');
  else if (cvc)                 { forms.add(w + w[w.length-1] + 'ed'); forms.add(w + 'ed'); }
  else                          forms.add(w + 'ed');
  if (/ie$/.test(w))            forms.add(w.slice(0, -2) + 'ying');
  else if (/e$/.test(w) && !/(ee|ye|oe)$/.test(w)) forms.add(w.slice(0, -1) + 'ing');
  else if (cvc)                 { forms.add(w + w[w.length-1] + 'ing'); forms.add(w + 'ing'); }
  else                          forms.add(w + 'ing');
  return [...forms].sort((a, b) => b.length - a.length);
}

let _wordRegexCache = { word: null, re: null };
function buildWordRegex(baseWord) {
  if (_wordRegexCache.word === baseWord) return _wordRegexCache.re;
  const forms = regularForms(baseWord);
  const re = forms.length
    ? new RegExp(`(^|[^A-Za-z])(${forms.map(f => f.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})(?=$|[^A-Za-z])`, 'gi')
    : null;
  _wordRegexCache = { word: baseWord, re };
  return re;
}

function highlightWordHtml(sentence, re) {
  if (!re) return escHtml(sentence);
  return escHtml(sentence).replace(re, (_, pre, hit) => `${pre}<mark class="word-hit">${hit}</mark>`);
}

function showToast(msg, onRetry = null) {
  toast.textContent = msg;
  if (onRetry) {
    const btn = document.createElement('button');
    btn.textContent = '重试';
    btn.onclick = () => { hideToast(); onRetry(); };
    toast.appendChild(btn);
  }
  toast.classList.remove('hidden');
}

function hideToast() {
  toast.classList.add('hidden');
}

async function submitWithRetry(wordId, rating, maxRetries = 3) {
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    if (attempt > 0) showToast(`网络异常，正在重试 (${attempt}/${maxRetries - 1})…`);
    try {
      const res = await fetch('/api/rate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ word_id: wordId, rating }),
      });
      if (!res.ok) throw new Error('status ' + res.status);
      hideToast();
      return await res.json();
    } catch (e) {
      if (attempt < maxRetries - 1) {
        await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
      } else {
        throw e;
      }
    }
  }
}

function clearTimers() {
  clearInterval(state.countdownTimer);
  clearTimeout(state.revealTimer);
  state.countdownTimer = null;
  state.revealTimer = null;
}

// ── Render ────────────────────────────────────────────────────────────────────

function renderStats() {
  const w = state.word;
  const s = state.stats;
  const p = state.progress;
  if (w) {
    statStage.textContent = w.stage || '';
    statStage.style.color = STAGE_COLORS[w.stage] || 'var(--text-muted)';
  }
  if (p) {
    statProgress.textContent = `${p.introduced} / ${p.total}`;
  }
  if (s) {
    const total = s.newTotal + s.reviewedTotal;
    statCounts.textContent = `共${total}次 | 新词${s.newWords} | 复习${s.reviewedWords}`;
  }
}

function renderIntervals() {
  if (!state.intervals) return;
  const iv = state.intervals;
  $('int-again').textContent = formatInterval(iv.again);
  $('int-hard').textContent  = formatInterval(iv.hard);
  $('int-good').textContent  = formatInterval(iv.good);
  $('int-easy').textContent  = formatInterval(iv.easy);
}

function renderWord() {
  const w = state.word;
  if (!w) return;

  wordPos.textContent   = w.pos || '';
  wordPhone.textContent = w.phonetic ? `/${w.phonetic}/` : '';

  if (w.morphemes) {
    const parts = w.morphemes.split('|').map(p => {
      const idx = p.indexOf(':');
      const text = idx >= 0 ? p.slice(0, idx) : p;
      const type = idx >= 0 ? p.slice(idx + 1) : 'root';
      const safeType = MORPHEME_TYPES.has(type) ? type : 'root';
      return `<span class="morpheme-${safeType}">${escHtml(text)}</span>`;
    });
    wordText.innerHTML = parts.join('<span class="morpheme-sep">·</span>');
  } else {
    wordText.textContent = w.word || '';
  }

  definition.textContent = w.definition || '';

  let parsed = [];
  try { parsed = JSON.parse(w.examples || '[]'); } catch (_) {}
  const wordRe = buildWordRegex(w.word);
  examples.innerHTML = parsed.slice(0, 2).map(ex => `
    <div class="example-item">
      <div class="example-en">${highlightWordHtml(ex.en, wordRe)}</div>
      <div class="example-zh invisible">${escHtml(ex.zh)}</div>
    </div>
  `).join('');

  renderIntervals();
}

function updateCountdownText() {
  hintText.textContent = `单击查看答案，${state.countdownSec} 秒后自动揭示`;
}

// ── State machine ─────────────────────────────────────────────────────────────

function startCountdown() {
  state.countdownSec = 3;
  updateCountdownText();
  state.countdownTimer = setInterval(() => {
    state.countdownSec = Math.max(0, state.countdownSec - 1);
    updateCountdownText();
  }, 1000);
  state.revealTimer = setTimeout(() => setPhase(2), 3000);
}

function setPhase(n) {
  clearTimers();
  state.phase = n;

  if (n === 1) {
    show(hintArea);
    visHide(definition);
    show(examples);
    ratingRow.classList.remove('revealing');
    definition.classList.remove('revealing');
    examples.querySelectorAll('.example-zh').forEach(el => el.classList.remove('revealing'));
    visHide(ratingRow);
    renderWord();
    startCountdown();
  } else if (n === 2) {
    hide(hintArea);
    visShow(definition);
    show(examples);
    const zhEls = examples.querySelectorAll('.example-zh');
    zhEls.forEach(el => el.classList.remove('invisible'));
    visShow(ratingRow);
    reveal(ratingRow);
    reveal(definition);
    zhEls.forEach((el, i) => {
      el.style.animationDelay = (50 + i * 50) + 'ms';
      el.addEventListener('animationend', () => { el.style.animationDelay = ''; }, { once: true });
      reveal(el);
    });
  }
}

// ── API calls ─────────────────────────────────────────────────────────────────

function prefetchNext() {
  const forWord = state.word?.id;
  fetch('/api/peek').then(r => r.json()).then(data => {
    // Ignore stale result: server hasn't advanced yet, returned current word
    if (data.word && data.word.id !== forWord) {
      state.next = { ...data.word, intervals: data.intervals };
    }
  }).catch(() => {});
}

async function fetchWord() {
  try {
    const res  = await fetch('/api/word');
    const data = await res.json();
    state.word      = data.word;
    state.stats     = data.stats;
    state.progress  = data.progress;
    state.intervals = data.intervals;
    renderStats();
    if (!data.word) return;
    setPhase(1);
    prefetchNext();
  } catch (e) {
    state.phase = 0;
    hintText.textContent = '加载失败，请刷新页面';
    show(hintArea);
    hide(ratingRow);
  }
}

function cardAnimate(name, duration, easing = 'ease') {
  return new Promise(resolve => {
    card.style.animation = `${name} ${duration}ms ${easing} forwards`;
    const done = () => { clearTimeout(fallback); card.removeEventListener('animationend', onEnd); resolve(); };
    const onEnd = e => { if (e.target === card && e.animationName === name) done(); };
    const fallback = setTimeout(done, duration + 100);
    card.addEventListener('animationend', onEnd);
  });
}

async function submitRating(rating) {
  const wordId = state.word.id;
  const btns = ratingRow.querySelectorAll('button');
  card.classList.add('loading');
  btns.forEach(b => b.disabled = true);

  function reset() {
    card.style.animation = '';
    card.classList.remove('loading');
    btns.forEach(b => b.disabled = false);
  }

  if (state.next) {
    // Optimistic path: show next word immediately, submit rating in background
    await cardAnimate('cardExit', 80);
    state.word      = state.next;
    state.intervals = state.next.intervals || null;
    state.next      = null;
    renderStats();
    setPhase(1);
    reset();
    cardAnimate('cardEnter', 160, 'cubic-bezier(0.34, 1.56, 0.64, 1)')
      .then(() => { card.style.animation = ''; });

    const doSubmit = (wid, r) => submitWithRetry(wid, r)
      .then(data => {
        if (data.stats) { state.stats = data.stats; state.progress = data.progress ?? state.progress; renderStats(); }
        prefetchNext();  // server has advanced, gets actual next-next word
      })
      .catch(() => showToast('提交失败，请检查网络', () => doSubmit(wid, r)));

    doSubmit(wordId, rating);

  } else {
    // Fallback: wait for API (no prefetch ready)
    try {
      const [data] = await Promise.all([
        submitWithRetry(wordId, rating),
        cardAnimate('cardExit', 80),
      ]);
      state.word      = data.word;
      state.stats     = data.stats;
      state.progress  = data.progress;
      state.intervals = data.intervals;
      if (!data.word) { reset(); return; }
      renderStats();
      setPhase(1);
      reset();
      await cardAnimate('cardEnter', 160, 'cubic-bezier(0.34, 1.56, 0.64, 1)');
      card.style.animation = '';
      prefetchNext();
    } catch (e) {
      reset();
      showToast('提交失败，请检查网络', () => submitRating(rating));
    }
  }
}

// ── Event listeners ───────────────────────────────────────────────────────────

card.addEventListener('click', () => {
  if (state.phase === 1) setPhase(2);
});

ratingRow.addEventListener('click', e => {
  e.stopPropagation();
  const btn = e.target.closest('[data-rating]');
  if (!btn || btn.disabled || card.classList.contains('loading')) return;
  if (state.phase !== 2 || !state.word) return;
  submitRating(parseInt(btn.dataset.rating, 10));
});

// ── Boot ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', fetchWord);
