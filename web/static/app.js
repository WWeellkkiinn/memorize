'use strict';

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
  intervals: null,
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
const statCounts    = $('stat-counts');

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

function clearTimers() {
  clearInterval(state.countdownTimer);
  clearTimeout(state.revealTimer);
  state.countdownTimer = null;
  state.revealTimer = null;
}

// 卡片高度平滑过渡：分帧写入确保浏览器有起始快照，支持取消上一轮动画
let _animCancel = null;

function animateCardHeight(callback) {
  if (_animCancel) { _animCancel(); _animCancel = null; }

  const from = card.offsetHeight;
  card.style.height = from + 'px';
  card.style.overflow = 'hidden';
  callback();
  card.style.height = 'auto';
  const to = card.offsetHeight;
  card.style.height = from + 'px';
  void card.offsetHeight;

  const cleanup = () => {
    card.style.height = '';
    card.style.overflow = '';
    card.style.transition = '';
    _animCancel = null;
  };

  if (from === to) { cleanup(); return; }

  let rafId, timeoutId, listener;

  _animCancel = () => {
    cancelAnimationFrame(rafId);
    clearTimeout(timeoutId);
    card.removeEventListener('transitionend', listener);
    cleanup();
  };

  // transition 和 height 分帧写入，保证浏览器能捕捉起始快照
  rafId = requestAnimationFrame(() => {
    card.style.transition = 'height 0.35s cubic-bezier(0.16, 1, 0.3, 1)';
    card.style.height = to + 'px';
    listener = (e) => {
      if (e.propertyName !== 'height') return;
      card.removeEventListener('transitionend', listener);
      clearTimeout(timeoutId);
      cleanup();
    };
    timeoutId = setTimeout(() => {
      card.removeEventListener('transitionend', listener);
      cleanup();
    }, 500);
    card.addEventListener('transitionend', listener);
  });
}

// ── Render ────────────────────────────────────────────────────────────────────

function renderStats() {
  const w = state.word;
  const s = state.stats;
  if (w) {
    statStage.textContent = w.stage || '';
    statStage.style.color = STAGE_COLORS[w.stage] || 'var(--text-muted)';
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
  wordText.textContent  = w.word || '';
  wordPhone.textContent = w.phonetic ? `/${w.phonetic}/` : '';

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
    show(ratingRow);
    renderWord();
    startCountdown();
  } else if (n === 2) {
    hide(hintArea);
    visShow(definition);
    show(examples);
    examples.querySelectorAll('.example-zh').forEach(el => el.classList.remove('invisible'));
    show(ratingRow);
    // 揭示 fade-in 动画：定义先出，例句中文错开跟上
    definition.classList.add('revealing');
    definition.addEventListener('animationend', () => definition.classList.remove('revealing'), { once: true });
    examples.querySelectorAll('.example-zh').forEach((el, i) => {
      el.style.animationDelay = (50 + i * 50) + 'ms';
      el.classList.add('revealing');
      el.addEventListener('animationend', () => {
        el.classList.remove('revealing');
        el.style.animationDelay = '';
      }, { once: true });
    });
  }
}

// ── API calls ─────────────────────────────────────────────────────────────────

async function fetchWord() {
  try {
    const res  = await fetch('/api/word');
    const data = await res.json();
    state.word      = data.word;
    state.stats     = data.stats;
    state.intervals = data.intervals;
    renderStats();
    if (!data.word) return;
    setPhase(1);
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
  const btns = ratingRow.querySelectorAll('button');
  card.classList.add('loading');
  btns.forEach(b => b.disabled = true);

  function reset() {
    card.style.animation = '';
    card.classList.remove('loading');
    btns.forEach(b => b.disabled = false);
  }

  try {
    const [res] = await Promise.all([
      fetch('/api/rate', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ word_id: state.word.id, rating }),
      }),
      cardAnimate('cardExit', 80),
    ]);
    if (!res.ok) throw new Error('rate failed: ' + res.status);
    const data = await res.json();
    state.word      = data.word;
    state.stats     = data.stats;
    state.intervals = data.intervals;
    if (!data.word) { reset(); return; }

    renderStats();
    setPhase(1);
    reset();
    await cardAnimate('cardEnter', 160, 'cubic-bezier(0.34, 1.56, 0.64, 1)');
    card.style.animation = '';

  } catch (e) {
    reset();
    hintText.textContent = '提交失败，请重试';
    hide(hintArea);
    visShow(definition);
    show(ratingRow);
    state.phase = 2;
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
