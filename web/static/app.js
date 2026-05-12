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
  prev: null,       // previous word dict (for /api/undo)
  prevHTML: null,   // innerHTML snapshot of #card before last advance
  stats: null,
  progress: null,
  intervals: null,
  next: null,       // pre-fetched next word
  countdownSec: 3,
  countdownTimer: null,
  revealTimer: null,
  animating: false,
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const cardPrev      = $('card-prev');
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
    renderPrevCard(null); // no prev on first load
    resetCardPositions();
    prefetchNext();
  } catch (e) {
    state.phase = 0;
    hintText.textContent = '加载失败，请刷新页面';
    show(hintArea);
    hide(ratingRow);
  }
}

// ── Web Animations API helpers ────────────────────────────────────────────────

const EXIT_EASING  = 'cubic-bezier(0.4, 0, 1, 1)';
const ENTER_EASING = 'cubic-bezier(0.34, 1.56, 0.64, 1)';

const KF_EXIT_LEFT  = [{ transform: 'none', opacity: 1 }, { transform: 'translateX(-100px) scale(0.97)', opacity: 0 }];
const KF_ENTER_RIGHT= [{ transform: 'translateX(80px) scale(0.97)', opacity: 0 }, { transform: 'none', opacity: 1 }];
const KF_EXIT_RIGHT = [{ transform: 'none', opacity: 1 }, { transform: 'translateX(100px)', opacity: 0 }];
const KF_ENTER_LEFT = [{ transform: 'translateX(-80px)', opacity: 0 }, { transform: 'none', opacity: 1 }];

function cancelCardAnims() {
  card.getAnimations().forEach(a => a.cancel());
}

async function cardExit(keyframes, duration) {
  cancelCardAnims();
  const anim = card.animate(keyframes, { duration, easing: EXIT_EASING, fill: 'forwards' });
  await anim.finished;
  return anim;
}

async function cardEnter(keyframes, duration, exitAnim) {
  if (exitAnim) exitAnim.cancel(); // drop forwards fill so enter starts clean
  cancelCardAnims();
  const anim = card.animate(keyframes, { duration, easing: ENTER_EASING });
  await anim.finished;
}

// ── Parallel card track helpers ───────────────────────────────────────────────

const CARD_GAP = 16;

function getCardW() { return card.offsetWidth + CARD_GAP; }

function resetCardPositions() {
  card.getAnimations().forEach(a => a.cancel());
  cardPrev.getAnimations().forEach(a => a.cancel());
  card.style.transform = '';
  cardPrev.style.transform = `translateX(${-getCardW()}px)`;
}

function renderPrevCard(html) {
  if (!html) {
    cardPrev.style.visibility = 'hidden';
    cardPrev.innerHTML = '';
    return;
  }
  cardPrev.innerHTML = html;
  cardPrev.style.visibility = '';
}

async function submitRating(rating) {
  if (state.animating) return;
  state.animating = true;
  const wordId = state.word.id;
  const btns = ratingRow.querySelectorAll('button');
  card.classList.add('loading');
  btns.forEach(b => b.disabled = true);

  const unlock = () => {
    card.classList.remove('loading');
    btns.forEach(b => b.disabled = false);
    state.animating = false;
    if (_pendingUndo && state.phase === 2) { _pendingUndo = false; _commitSwipe(); }
  };

  if (state.next) {
    // Optimistic: show next word immediately, submit in background
    const prevHTML  = card.innerHTML;                  // snapshot before content changes
    const exitAnim = await cardExit(KF_EXIT_LEFT, 160);
    state.prev      = state.word;                      // save for /api/undo
    state.prevHTML  = prevHTML;
    state.word      = state.next;
    state.intervals = state.next.intervals || null;
    state.next      = null;
    renderStats();
    setPhase(1);
    renderPrevCard(state.prevHTML);
    card.classList.remove('loading');
    btns.forEach(b => b.disabled = false);
    const enterDone = cardEnter(KF_ENTER_RIGHT, 240, exitAnim).then(unlock);
    const doSubmit = (wid, r) => submitWithRetry(wid, r)
      .then(data => {
        if (data.stats) { state.stats = data.stats; state.progress = data.progress ?? state.progress; renderStats(); }
        prefetchNext();
      })
      .catch(() => showToast('提交失败，请检查网络', () => doSubmit(wid, r)));
    doSubmit(wordId, rating);
    await enterDone;

  } else {
    // Fallback: wait for API
    try {
      const [data, exitAnim] = await Promise.all([
        submitWithRetry(wordId, rating),
        cardExit(KF_EXIT_LEFT, 160),
      ]);
      const prevHTML  = card.innerHTML;                // snapshot before content changes
      state.prev      = state.word;                    // save for /api/undo
      state.prevHTML  = prevHTML;
      state.word      = data.word;
      state.stats     = data.stats;
      state.progress  = data.progress;
      state.intervals = data.intervals;
      if (!data.word) { unlock(); return; }
      renderStats();
      setPhase(1);
      renderPrevCard(state.prevHTML);
      card.classList.remove('loading');
      btns.forEach(b => b.disabled = false);
      await cardEnter(KF_ENTER_RIGHT, 240, exitAnim);
      unlock();
      prefetchNext();
    } catch (e) {
      unlock();
      showToast('提交失败，请检查网络', () => submitRating(rating));
    }
  }
}

// ── Parallel card track — right-swipe to undo ─────────────────────────────────
// #card-prev lives at translateX(-getCardW()) off-screen left.
// During right swipe, both cards move by the same dx: they look strung together.
// On commit: current exits right, prev enters center; then content + positions reset.

const UNDO_THRESHOLD = 80;
let _sx = 0, _sy = 0, _swipeDir = null;
let _pendingUndo = false;

function _curCardDx() {
  const m = card.style.transform && card.style.transform.match(/translateX\((-?[\d.]+)px\)/);
  return m ? parseFloat(m[1]) : 0;
}

function _snapAllBack() {
  const curDx = _curCardDx();
  if (curDx === 0) return;
  const W = getCardW();
  const opts = { duration: 220, easing: ENTER_EASING };
  card.style.transform = '';
  card.animate([{ transform: `translateX(${curDx}px)` }, { transform: 'none' }], opts);
  if (state.prev) {
    cardPrev.style.transform = `translateX(${-W}px)`;
    cardPrev.animate(
      [{ transform: `translateX(${-W + curDx}px)` }, { transform: `translateX(${-W}px)` }],
      opts
    );
  }
}

async function _commitSwipe() {
  if (state.phase !== 2) return;
  if (state.animating) { _pendingUndo = true; _snapAllBack(); return; }
  state.animating = true;

  const W = getCardW();
  const curDx = _curCardDx();
  card.style.transform = '';
  cardPrev.style.transform = '';

  const exitAnim = card.animate(
    [{ transform: `translateX(${curDx}px)` }, { transform: `translateX(${W * 1.5}px)`, opacity: 0.4 }],
    { duration: 240, easing: EXIT_EASING, fill: 'forwards' }
  );
  const enterAnim = cardPrev.animate(
    [{ transform: `translateX(${-W + curDx}px)` }, { transform: 'translateX(0)' }],
    { duration: 240, easing: ENTER_EASING, fill: 'forwards' }
  );

  let data;
  try {
    [data] = await Promise.all([
      fetch('/api/undo', { method: 'POST' }).then(r => r.json()),
      exitAnim.finished,
      enterAnim.finished,
    ]);
  } catch {
    exitAnim.cancel(); enterAnim.cancel();
    resetCardPositions(); renderPrevCard(state.prevHTML);
    state.animating = false;
    return;
  }

  if (data && data.word) {
    // Set inline positions before cancel so element snaps to these values
    // Lock height before cancel so flex container doesn't reflow mid-swap
    card.style.minHeight = card.offsetHeight + 'px';

    card.style.transform = '';
    cardPrev.style.transform = `translateX(${-W}px)`;
    exitAnim.cancel();
    enterAnim.cancel();

    state.prev      = null;
    state.prevHTML  = null;
    state.word      = data.word;
    state.stats     = data.stats;
    state.progress  = data.progress;
    state.intervals = data.intervals;
    state.next      = null;
    renderStats();
    setPhase(1);
    renderPrevCard(null);

    // Release height lock after two frames (new content painted)
    requestAnimationFrame(() => requestAnimationFrame(() => {
      card.style.minHeight = '';
    }));
  } else {
    exitAnim.cancel(); enterAnim.cancel();
    resetCardPositions(); renderPrevCard(state.prevHTML);
  }
  state.animating = false;
  prefetchNext();
}

card.addEventListener('touchstart', e => {
  _sx = e.touches[0].clientX;
  _sy = e.touches[0].clientY;
  _swipeDir = null;
}, { passive: true });

card.addEventListener('touchmove', e => {
  if (state.phase !== 2) return;
  const dx = e.touches[0].clientX - _sx;
  const dy = e.touches[0].clientY - _sy;
  const adx = Math.abs(dx), ady = Math.abs(dy);
  if (_swipeDir === null && (adx > 6 || ady > 6)) {
    _swipeDir = adx > ady ? 'h' : 'v';
  }
  if (_swipeDir !== 'h' || dx <= 0) return;

  const W = getCardW();
  let travel;
  if (state.prev) {
    travel = dx <= UNDO_THRESHOLD ? dx : UNDO_THRESHOLD + (dx - UNDO_THRESHOLD) * 0.25;
    cardPrev.style.transform = `translateX(${-W + travel}px)`;
  } else {
    travel = Math.min(dx * 0.12, 18); // heavy resistance at boundary
  }
  card.style.transform = `translateX(${travel}px)`;
}, { passive: true });

card.addEventListener('touchend', e => {
  if (_swipeDir !== 'h') { _swipeDir = null; return; }
  const dx = e.changedTouches[0].clientX - _sx;
  _swipeDir = null;
  if (dx > UNDO_THRESHOLD && state.prev) {
    _commitSwipe();
  } else {
    _snapAllBack();
  }
}, { passive: true });

card.addEventListener('touchcancel', () => {
  _swipeDir = null;
  _snapAllBack();
}, { passive: true });

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
