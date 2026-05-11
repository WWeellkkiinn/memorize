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
const revealDivider = $('reveal-divider');
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
  const w = state.word;
  const s = state.stats;
  if (w) {
    statStage.textContent  = w.stage || '';
    statStage.style.color  = STAGE_COLORS[w.stage] || 'var(--text-muted)';
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

  wordPos.textContent    = w.pos || '';
  wordText.textContent   = w.word || '';
  wordPhone.textContent  = w.phonetic ? `/${w.phonetic}/` : '';

  definition.textContent = w.definition || '';

  let parsed = [];
  try { parsed = JSON.parse(w.examples || '[]'); } catch (_) {}
  examples.innerHTML = parsed.slice(0, 2).map(ex => `
    <div class="example-item">
      <div class="example-en">${escHtml(ex.en)}</div>
      <div class="example-zh hidden">${escHtml(ex.zh)}</div>
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
    hide(revealDivider);
    hide(definition);
    show(examples);   // 英文例句 Phase 1 可见，中文隐藏（由 renderWord 内联 hidden class 控制）
    hide(ratingRow);
    renderWord();
    startCountdown();
  } else if (n === 2) {
    hide(hintArea);
    show(revealDivider);
    show(definition);
    show(examples);
    // 显示中文翻译
    examples.querySelectorAll('.example-zh').forEach(el => el.classList.remove('hidden'));
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
    hintText.textContent = '加载失败，请刷新页面';
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
    hintText.textContent = '提交失败，请重试';
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
