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
const stageBadge    = $('stage-badge');
const wordPos       = $('word-pos');
const wordText      = $('word-text');
const wordPhone     = $('word-phonetic');
const hintArea      = $('hint-area');
const hintCountdown = $('hint-countdown');
const hintLabel     = $('hint-label');
const revealDivider = $('reveal-divider');
const definition    = $('definition');
const examples      = $('examples');
const ratingRow     = $('rating-row');
const statNew       = $('stat-new');
const statReview    = $('stat-review');

// ── Utilities ─────────────────────────────────────────────────────────────────

function formatInterval(days) {
  if (days <= 1)   return '1天';
  if (days < 7)    return days + '天';
  if (days < 30)   return Math.round(days / 7) + '周';
  if (days < 365)  return Math.round(days / 30) + '个月';
  return (days / 365).toFixed(1) + '年';
}

function show(el) { el.classList.remove('hidden'); }
function hide(el) { el.classList.add('hidden'); }

function escHtml(s) {
  return String(s || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function clearTimers() {
  clearInterval(state.countdownTimer);
  clearTimeout(state.revealTimer);
  state.countdownTimer = null;
  state.revealTimer = null;
}

// ── Render ────────────────────────────────────────────────────────────────────

function renderStats() {
  if (!state.stats) return;
  const s = state.stats;
  statNew.textContent    = `新词 ${s.newWords}`;
  statReview.textContent = `复习 ${s.reviewedWords}`;
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

  stageBadge.textContent  = w.stage;
  stageBadge.style.color  = STAGE_COLORS[w.stage] || 'var(--text)';
  wordPos.textContent     = w.pos || '';
  wordText.textContent    = w.word || '';
  wordPhone.textContent   = w.phonetic ? `/${w.phonetic}/` : '';

  definition.textContent  = w.definition || '';

  let parsed = [];
  try { parsed = JSON.parse(w.examples || '[]'); } catch (_) {}
  examples.innerHTML = parsed.slice(0, 2).map(ex => `
    <div class="example-item">
      <div class="example-en">${escHtml(ex.en)}</div>
      <div class="example-zh">${escHtml(ex.zh)}</div>
    </div>
  `).join('');

  renderIntervals();
}

function updateCountdownText() {
  hintCountdown.textContent = state.countdownSec;
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
    hide(revealDivider);
    hide(definition);
    hide(examples);
    hide(ratingRow);
    renderWord();
    startCountdown();
  } else if (n === 2) {
    hide(hintArea);
    show(revealDivider);
    show(definition);
    show(examples);
    show(ratingRow);
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
    hintCountdown.textContent = '!';
    hintLabel.textContent = '加载失败，请刷新页面';
    show(hintArea);
  }
}

async function submitRating(rating) {
  ratingRow.querySelectorAll('button').forEach(b => b.disabled = true);
  try {
    const res  = await fetch('/api/rate', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ word_id: state.word.id, rating }),
    });
    if (!res.ok) throw new Error('rate failed: ' + res.status);
    const data = await res.json();
    state.word      = data.word;
    state.stats     = data.stats;
    state.intervals = data.intervals;
    renderStats();
    if (!data.word) return;
    setPhase(1);
  } catch (e) {
    hintCountdown.textContent = '!';
    hintLabel.textContent = '提交失败，请重试';
    show(hintArea);
    show(ratingRow);
    state.phase = 2;
  } finally {
    ratingRow.querySelectorAll('button').forEach(b => b.disabled = false);
  }
}

// ── Event listeners ───────────────────────────────────────────────────────────

card.addEventListener('click', () => {
  if (state.phase === 1) setPhase(2);
});

ratingRow.addEventListener('click', e => {
  e.stopPropagation();
  const btn = e.target.closest('[data-rating]');
  if (!btn || state.phase !== 2 || !state.word) return;
  submitRating(parseInt(btn.dataset.rating, 10));
});

// ── Boot ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', fetchWord);
