'use strict';

const MORPHEME_TYPES = new Set(['prefix', 'root', 'bound', 'free']);

const state = {
  phase: 0,         // 0=loading, 1=self-test, 2=revealed
  word: null,
  prev: null,       // previous word dict (for /api/undo)
  prevHTML: null,   // innerHTML snapshot of #card before last advance
  stats: null,
  progress: null,
  next: null,       // pre-fetched next word
  nextHTML: null,   // pre-rendered HTML for next word (built in prefetchNext)
  countdownSec: 3,
  countdownTimer: null,
  revealTimer: null,
  animating: false,
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
// Only the card-stage scaffold elements have ids; everything *inside* a card uses
// classes so the three cards (prev/current/next) share one HTML template without
// id collisions.
const cardStage = document.getElementById('card-stage');
const cardPrev  = document.getElementById('card-prev');
const cardNext  = document.getElementById('card-next');
const card      = document.getElementById('card');
const toast     = document.getElementById('toast');
const q = sel => card.querySelector(sel);

// ── Audio ─────────────────────────────────────────────────────────────────────

let _audio = null;     // 当前词
let _audioNext = null; // 下一张预加载
let _audioPrev = null; // 上一张保留（撤销用）

function _makeAudio(word) {
  const a = new Audio(`https://dict.youdao.com/dictvoice?audio=${encodeURIComponent(word)}&type=2`);
  a._word = word;
  return a;
}

// 释放 Audio 对象并取消未完成的网络请求
function _evictAudio(a) { if (a) a.src = ''; }

// word 传入时渲染新词（自动播放，优先复用预加载缓存）；不传时重播当前词
function speakWord(word) {
  if (word) {
    if (_audioNext?._word === word) {
      _evictAudio(_audioPrev);     // 丢弃两步前的音频
      _audioPrev = _audio;
      _audio = _audioNext;
      _audioNext = null;
    } else if (_audioPrev?._word === word) {
      _audio = _audioPrev;
      _audioPrev = null;
      if (!_audio.paused && !_audio.ended) return; // already playing from early trigger
    } else if (_audio?._word === word) {
      if (!_audio.paused && !_audio.ended) return; // already playing from early trigger (forward nav)
    } else {
      _evictAudio(_audioPrev);     // 丢弃两步前的音频
      _audioPrev = _audio;
      _audio = _makeAudio(word);
    }
  } else if (_audio?._word !== state.word?.word) {
    // no-arg replay but _audio is stale (mid-transition) — rebuild on demand
    if (state.word?.word) _audio = _makeAudio(state.word.word);
  }
  if (!_audio) return;
  if (_audio.ended) {
    // Some Android browsers won't replay an ended audio — recreate it
    const w = _audio._word;
    _evictAudio(_audio);
    _audio = _makeAudio(w);
  } else {
    _audio.currentTime = 0;
  }
  _audio.play().catch(() => {});
}

function _stopCurrent() {
  if (_audio && !_audio.paused) _audio.pause();
}

function preloadNextAudio(word) {
  if (!word) { _evictAudio(_audioNext); _audioNext = null; return; }
  if (_audioNext?._word === word) return;
  _evictAudio(_audioNext);
  _audioNext = _makeAudio(word);
  _audioNext.load();
}

// ── Utilities ─────────────────────────────────────────────────────────────────

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

const _wordRegexCache = new Map(); // two-slot: holds current + next word to avoid cross-pollution
function buildWordRegex(baseWord) {
  if (_wordRegexCache.has(baseWord)) return _wordRegexCache.get(baseWord);
  const forms = regularForms(baseWord);
  const re = forms.length
    ? new RegExp(`(^|[^A-Za-z])(${forms.map(f => f.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})(?=$|[^A-Za-z])`, 'gi')
    : null;
  if (_wordRegexCache.size >= 2) _wordRegexCache.delete(_wordRegexCache.keys().next().value);
  _wordRegexCache.set(baseWord, re);
  return re;
}

// sentence MUST be pre-escaped with escHtml; hit is a substring of the escaped string, safe to embed
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

function fetchTimeout(url, options = {}, ms = 10000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  return fetch(url, { ...options, signal: ctrl.signal }).finally(() => clearTimeout(timer));
}

async function submitWithRetry(wordId, rating, maxRetries = 3) {
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    if (attempt > 0) showToast(`网络异常，正在重试 (${attempt}/${maxRetries - 1})…`);
    try {
      const res = await fetchTimeout('/api/rate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ word_id: wordId, rating }),
      });
      guard401(res);
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

// Format helpers — single source of truth, also used by buildCardHTML.
function formatProgressText(p) {
  return p ? `${p.introduced}/${p.total}` : '';
}
function formatCountsText(s) {
  return s ? `${s.newTotal + s.reviewedTotal}次·新${s.newWords}·复${s.reviewedWords}` : '';
}

// Sync stats DOM in `root` with current state.stats/progress. Stage color is now
// driven by [data-stage] CSS rules, so this only updates numeric values.
// Default root is the live #card (NOT document, which would match #card-prev first).
function renderStats(root = card) {
  const s = state.stats;
  const p = state.progress;
  if (!root) return;
  if (p) {
    const prog = root.querySelector('.stat-progress');
    if (prog) prog.textContent = formatProgressText(p);
  }
  if (s) {
    const counts = root.querySelector('.stat-counts');
    if (counts) counts.textContent = formatCountsText(s);
  }
}

function buildMorphemeHTML(word) {
  if (word.morphemes) {
    const parts = word.morphemes.split('|').map(p => {
      const idx = p.indexOf(':');
      const text = idx >= 0 ? p.slice(0, idx) : p;
      const type = idx >= 0 ? p.slice(idx + 1) : 'root';
      const safeType = MORPHEME_TYPES.has(type) ? type : 'root';
      return `<span class="morpheme-${safeType}">${escHtml(text)}</span>`;
    });
    return parts.join('<span class="morpheme-sep">·</span>');
  }
  return escHtml(word.word || '');
}

function buildExamplesHTML(word) {
  let parsed = [];
  try { parsed = JSON.parse(word.examples || '[]'); } catch (_) {}
  if (!Array.isArray(parsed)) parsed = [];
  const wordRe = buildWordRegex(word.word);
  return parsed.slice(0, 2).map(ex =>
    `<div class="example-item">` +
    `<div class="example-en">${highlightWordHtml(ex.en, wordRe)}</div>` +
    `<div class="example-zh invisible">${escHtml(ex.zh)}</div>` +
    `</div>`
  ).join('');
}

function updateCountdownText() {
  const el = q('.hint-text');
  if (el) el.textContent = `单击查看答案，${state.countdownSec} 秒后自动揭示`;
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

function setPhase(n, skipReveal = false) {
  clearTimers();
  state.phase = n;

  const hintArea  = q('.hint-area');
  const definition = q('.definition');
  const examples  = q('.examples');
  const ratingRow = q('.rating-row');
  if (!hintArea) return; // card has no content yet (error state)

  if (n === 1) {
    show(hintArea);
    visHide(definition);
    show(examples);
    ratingRow.classList.remove('revealing');
    definition.classList.remove('revealing');
    visHide(ratingRow);
    examples.querySelectorAll('.example-zh').forEach(el => el.classList.remove('revealing'));
    startCountdown();
  } else if (n === 2) {
    hide(hintArea);
    visShow(definition);
    show(examples);
    const zhEls = examples.querySelectorAll('.example-zh');
    zhEls.forEach(el => el.classList.remove('invisible'));
    visShow(ratingRow);
    if (!skipReveal) {
      reveal(ratingRow);
      reveal(definition);
      zhEls.forEach((el, i) => {
        el.style.animationDelay = (50 + i * 50) + 'ms';
        el.addEventListener('animationend', () => { el.style.animationDelay = ''; }, { once: true });
        reveal(el);
      });
    }
  }
}

// ── API calls ─────────────────────────────────────────────────────────────────

let _prefetchCtrl = null;

function prefetchNext() {
  if (_prefetchCtrl) _prefetchCtrl.abort();
  _prefetchCtrl = new AbortController();
  const ctrl = _prefetchCtrl;
  const timeoutId = setTimeout(() => ctrl.abort(), 10000);
  const forWord = state.word?.id;
  fetch('/api/peek', { signal: ctrl.signal })
    .then(r => { clearTimeout(timeoutId); if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(data => {
      if (ctrl !== _prefetchCtrl) return;
      if (data.word && data.word.id !== forWord) {
        state.next = { ...data.word, intervals: data.intervals };
        state.nextHTML = buildCardHTML(state.next); // pre-render off critical path
        // Only stage DOM when no slide animation is in flight — otherwise we'd yank
        // the entering cardNext mid-animation. submitRating cleanup re-stages on finish.
        if (!state.animating) renderNextCard(state.nextHTML);
        preloadNextAudio(state.next.word);
      } else {
        state.next = null; // peek returned no new word — clear any stale data
        state.nextHTML = null;
        if (!state.animating) renderNextCard(null);
        _audioNext = null;
      }
    })
    .catch(() => { clearTimeout(timeoutId); });
}

function consumeNext(next) {
  const forWord = state.word?.id;
  if (next && next.word && next.word.id !== forWord) {
    state.next = { ...next.word, intervals: next.intervals };
    state.nextHTML = buildCardHTML(state.next);
    if (!state.animating) renderNextCard(state.nextHTML);
    preloadNextAudio(state.next.word);
  } else {
    state.next = null;
    state.nextHTML = null;
    if (!state.animating) renderNextCard(null);
    _audioNext = null;
  }
}

async function fetchWord() {
  if (state.animating) return;
  try {
    const res  = await fetch('/api/word');
    guard401(res);
    const data = await res.json();
    state.word      = data.word;
    state.stats     = data.stats;
    state.progress  = data.progress;
    if (!data.word) {
      card.innerHTML = `<div class="hint-area"><div class="hint-text">暂无单词</div></div>`;
      return;
    }
    card.innerHTML = buildCardHTML(state.word);
    renderStats();
    setPhase(1);
    speakWord(state.word.word);
    renderPrevCard(null); // no prev on first load
    renderNextCard(null); // no next until prefetch lands
    resetCardPositions();
    prefetchNext();
  } catch (e) {
    state.phase = 0;
    card.innerHTML = `<div class="hint-area"><div class="hint-text">加载失败，请刷新页面</div></div>`;
  }
}

// ── Web Animations API helpers ────────────────────────────────────────────────

const EXIT_EASING  = 'cubic-bezier(0.4, 0, 1, 1)';
const ENTER_EASING = 'cubic-bezier(0.34, 1.56, 0.64, 1)';
const RAIL_EASING  = 'ease-in-out';

// Single source of truth for card HTML — used for #card, #card-next, and (via
// snapshot) #card-prev. All three cards therefore have byte-identical structure.
// Produces phase-1 state (hint visible, definition/rating hidden); setPhase flips
// classes for phase 2.
function buildCardHTML(word) {
  if (!word) return '';
  const progressText = formatProgressText(state.progress);
  const countsText = formatCountsText(state.stats);
  return (
    `<div class="card-header">` +
      `<span class="word-text">${buildMorphemeHTML(word)}</span>` +
      `<div class="word-meta">` +
        `<span class="word-pos">${escHtml(word.pos || '')}</span>` +
        `<span class="word-phonetic">${word.phonetic ? '/' + escHtml(word.phonetic) + '/' : ''}</span>` +
        `<span class="speak-btn" role="button" tabindex="0" aria-label="朗读">🔊</span>` +
      `</div>` +
    `</div>` +
    `<div class="answer-area">` +
      `<div class="hint-area"><div class="hint-text">单击查看答案，3 秒后自动揭示</div></div>` +
      `<div class="definition invisible">${escHtml(word.definition || '')}</div>` +
    `</div>` +
    `<div class="examples">${buildExamplesHTML(word)}</div>` +
    `<div class="rating-row invisible">` +
      `<button class="rating-btn btn-again" data-rating="1">忘 了</button>` +
      `<button class="rating-btn btn-hard"  data-rating="2">模 糊</button>` +
      `<button class="rating-btn btn-good"  data-rating="3">记 得</button>` +
      `<button class="rating-btn btn-easy"  data-rating="4">轻 松</button>` +
    `</div>` +
    `<div class="stats-row">` +
      `<span class="stat-stage" data-stage="${escHtml(word.stage || '')}">${escHtml(word.stage || '')}</span>` +
      `<div class="stat-side">` +
        `<span class="stat-progress">${escHtml(progressText)}</span>` +
        `<span class="stat-counts">${escHtml(countsText)}</span>` +
      `</div>` +
    `</div>`
  );
}

// ── Parallel card track helpers ───────────────────────────────────────────────

const CARD_GAP = 16;

function getCardW() { return card.offsetWidth + CARD_GAP; }

function offScreen(side) {
  const sign = side === 'right' ? 1 : -1;
  return `translateX(${sign * getCardW()}px) translateY(-50%)`;
}

function resetCardPositions() {
  card.getAnimations().forEach(a => a.cancel());
  cardPrev.getAnimations().forEach(a => a.cancel());
  cardNext.getAnimations().forEach(a => a.cancel());
  card.style.transform = '';
  cardPrev.style.transform = offScreen('left');
  cardNext.style.transform = offScreen('right');
}

function renderPrevCard(html, side = 'left') {
  cardPrev.getAnimations().forEach(a => a.cancel());
  if (!html) {
    cardPrev.style.visibility = 'hidden';
    cardPrev.innerHTML = '';
    return;
  }
  const t = offScreen(side); // measure before innerHTML write
  cardPrev.innerHTML = html;
  cardPrev.style.visibility = '';
  cardPrev.style.transform = t;
}

// Park next card off-screen right, fully rendered in DOM so layout/font metrics
// are warm by the time the user submits a rating.
function renderNextCard(html) {
  cardNext.getAnimations().forEach(a => a.cancel());
  if (!html) {
    cardNext.style.visibility = 'hidden';
    cardNext.innerHTML = '';
    return;
  }
  cardNext.innerHTML = html;
  cardNext.style.visibility = '';
  cardNext.style.transform = offScreen('right');
}

async function submitRating(rating) {
  if (state.animating) return;
  state.animating = true;
  const wordId = state.word.id;
  const gen = ++_submitGen; // generation token — stale doSubmit retries check this
  card.classList.add('loading'); // belt + suspenders: CSS blocks pointer-events; click handler also checks this

  const SLIDE_DUR = 240;

  const unlock = () => {
    card.classList.remove('loading');
    state.animating = false;
    if (_pendingUndo && state.prev) { _pendingUndo = false; _commitSwipe(); }
  };

  if (state.next) {
    // Optimistic: parallel slide using pre-staged #card-next as the entering card.
    const prevHTML = card.innerHTML;
    const nextWord = state.next;
    // Consume immediately so a fresh prefetch during animation can populate state.next
    // with the word-after-next without racing the cleanup below.
    state.next = null;
    state.nextHTML = null;

    const W = getCardW();

    _stopCurrent();
    speakWord(nextWord.word);

    const exitAnim = card.animate(
      [{ transform: 'translateX(0)' }, { transform: `translateX(${-W}px)` }],
      { duration: SLIDE_DUR, easing: RAIL_EASING, fill: 'forwards' }
    );
    const enterAnim = cardNext.animate(
      [{ transform: `translateX(${W}px) translateY(-50%)` }, { transform: 'translateX(0) translateY(-50%)' }],
      { duration: SLIDE_DUR, easing: RAIL_EASING, fill: 'forwards' }
    );

    let doSubmitSettled = false;
    // Tracks whether the cardNext→card swap has occurred. Before swap, cardNext is
    // the visible incoming card; after swap, cardNext gets reassigned to the *next*
    // prefetched word, so writing stats into it would mutate the wrong card.
    let swapDone = false;
    const doSubmit = () => submitWithRetry(wordId, rating)
      .then(data => {
        doSubmitSettled = true;
        if (gen !== _submitGen) return;
        if (data.stats) {
          state.stats = data.stats;
          state.progress = data.progress ?? state.progress;
          // Pre-swap: refresh the still-sliding-in cardNext directly.
          // Post-swap: buildCardHTML below already used latest state.stats, nothing to do.
          if (!swapDone) renderStats(cardNext);
        }
        consumeNext(data.next);
        if (_pendingUndo && state.prev) { _pendingUndo = false; _commitSwipe(); }
      })
      .catch(() => {
        doSubmitSettled = true;
        if (gen !== _submitGen) return;
        showToast('提交失败，请检查网络', doSubmit);
      });
    doSubmit();

    await Promise.all([exitAnim.finished, enterAnim.finished]);

    // Snapshot old card content into #card-prev for undo, rebuild #card with new word.
    renderPrevCard(prevHTML, 'left');
    state.prev      = state.word;
    state.prevHTML  = prevHTML;
    state.word      = nextWord;
    card.innerHTML  = buildCardHTML(state.word);  // already uses latest state.stats — no extra renderStats needed
    swapDone = true;  // any future doSubmit settle will see this and skip cardNext write
    setPhase(1);

    card.style.transform = '';
    exitAnim.cancel();
    // state.nextHTML is null unless a fresh prefetch landed mid-animation while guarded.
    renderNextCard(state.nextHTML);

    card.classList.remove('loading');
    state.animating = false;
    if (_pendingUndo && state.prev && doSubmitSettled) { _pendingUndo = false; _commitSwipe(); }

  } else {
    // Fallback (no peek data): parallel slide — start exit immediately, stage cardNext
    // as soon as API returns, then enter. Both run concurrently like the optimistic path.
    try {
      const prevHTML = card.innerHTML;
      const W = getCardW();

      const exitAnim = card.animate(
        [{ transform: 'translateX(0)' }, { transform: `translateX(${-W}px)` }],
        { duration: SLIDE_DUR, easing: RAIL_EASING, fill: 'forwards' }
      );

      const data = await submitWithRetry(wordId, rating);

      if (!data.word) {
        exitAnim.cancel();
        card.style.transform = '';
        card.classList.remove('loading');
        _pendingUndo = false;
        state.animating = false;
        showToast('没有更多单词了');
        return;
      }

      // Stage cardNext with new content and start enter animation immediately —
      // may overlap with exit animation still in progress.
      state.stats    = data.stats;
      state.progress = data.progress;
      const newWord  = data.word;
      _stopCurrent();
      speakWord(newWord.word);
      renderNextCard(buildCardHTML(newWord)); // unified staging via renderNextCard
      cardNext.style.transform = `translateX(${W}px) translateY(-50%)`; // override offScreen to use current W

      const enterAnim = cardNext.animate(
        [{ transform: `translateX(${W}px) translateY(-50%)` }, { transform: 'translateX(0) translateY(-50%)' }],
        { duration: SLIDE_DUR, easing: RAIL_EASING, fill: 'forwards' }
      );

      await Promise.all([exitAnim.finished, enterAnim.finished]);

      renderPrevCard(prevHTML, 'left');
      state.prev     = state.word;
      state.prevHTML = prevHTML;
      state.word     = newWord;
      state.next     = null;
      state.nextHTML = null;
      card.innerHTML = cardNext.innerHTML; // reuse already-rendered HTML, avoid second buildCardHTML
      setPhase(1);
      card.style.transform = '';
      exitAnim.cancel();
      renderNextCard(state.nextHTML); // stage next-next if prefetch landed during animation

      unlock();
      prefetchNext();
    } catch (e) {
      card.style.transform = '';
      card.getAnimations().forEach(a => a.cancel());
      cardNext.getAnimations().forEach(a => a.cancel());
      cardNext.style.visibility = 'hidden';
      _pendingUndo = false;
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
let _cachedCardW = 0; // cached in touchstart; reset on resize
window.addEventListener('resize', () => { _cachedCardW = 0; }, { passive: true });
let _pendingUndo = false;
let _submitGen = 0;   // incremented each submitRating call; stale doSubmit retries check this

function _curCardDx() {
  const m = card.style.transform && card.style.transform.match(/translateX\((-?[\d.]+)px\)/);
  return m ? parseFloat(m[1]) : 0;
}

function _snapAllBack() {
  const curDx = _curCardDx();
  // No early return: curDx may be 0 due to cleared inline style while WAAPI runs elsewhere.
  // Animating from translateX(0)→none is a no-op visually but safely resets state.
  const opts = { duration: 220, easing: ENTER_EASING };
  card.style.transform = '';
  card.animate([{ transform: `translateX(${curDx}px)` }, { transform: 'none' }], opts);
  if (state.prev) {
    const W = _cachedCardW || getCardW();
    const offScreen = `translateX(${-W}px) translateY(-50%)`;
    cardPrev.style.transform = offScreen;
    cardPrev.animate(
      [{ transform: `translateX(${-W + curDx}px) translateY(-50%)` }, { transform: offScreen }],
      opts
    );
  } else {
    cardPrev.getAnimations().forEach(a => a.cancel()); // clear any stale fill:forwards
  }
}

async function _commitSwipe() {
  if (state.animating) { _pendingUndo = true; _snapAllBack(); return; }
  state.animating = true;
  ++_submitGen; // invalidate any in-flight doSubmit — prevents post-undo stats overwrite
  _evictAudio(_audioNext); _audioNext = null; // undo resets the queue; stale preload is wrong

  // Play prev word audio immediately in sync with animation — don't wait for API
  _stopCurrent();
  if (_audioPrev) {
    _audio = _audioPrev; // update _audio immediately so no-arg speakWord() plays correct word
    _audioPrev = null;
    _audio.currentTime = 0;
    _audio.play().catch(() => {});
  }

  // Batch all layout reads before any writes to avoid forced reflow
  const W = _cachedCardW || getCardW();
  const curDx = _curCardDx();
  const prevH = cardPrev.scrollHeight; // read before any style writes
  const curH  = card.offsetHeight;     // read before any style writes

  // Pin to CURRENT card height — keeps top:50% on #card-prev unchanged during animation.
  // We'll update the pin to prevH after the animation, once #card-prev is off-screen.
  if (curH > 0) cardStage.style.height = curH + 'px';

  // Don't clear inline transforms — WAAPI first keyframes override them without flash risk

  const exitAnim = card.animate(
    [{ transform: `translateX(${curDx}px)` }, { transform: `translateX(${W * 1.5}px)` }],
    { duration: 240, easing: RAIL_EASING, fill: 'forwards' }
  );
  const enterAnim = cardPrev.animate(
    [{ transform: `translateX(${-W + curDx}px) translateY(-50%)` },
     { transform: 'translateX(0) translateY(-50%)' }],
    { duration: 240, easing: RAIL_EASING, fill: 'forwards' }
  );

  let data;
  try {
    [data] = await Promise.all([
      fetchTimeout('/api/undo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      }).then(r => r.json()),
      exitAnim.finished,
      enterAnim.finished,
    ]);
  } catch {
    exitAnim.cancel(); enterAnim.cancel();
    cardStage.style.height = '';
    card.getAnimations().forEach(a => a.cancel());
    card.style.transform = '';
    renderPrevCard(state.prevHTML || null); // handles null (hides) and restores prevHTML in one call
    _pendingUndo = false;
    state.animating = false;
    return;
  }

  if (data && data.word) {
    // Set inline positions before cancel so elements snap to these values
    card.style.transform = '';
    cardPrev.style.transform = offScreen('left');
    exitAnim.cancel();  // #card snaps to center
    enterAnim.cancel(); // #card-prev snaps to off-screen left — top:50% jump now invisible

    // Update pin to prevH before setPhase(1) so the content-height change doesn't flex-reflow
    if (prevH > 0) cardStage.style.height = prevH + 'px';

    _pendingUndo    = false;
    state.prev      = null;
    state.prevHTML  = null;
    state.word      = data.word;
    state.stats     = data.stats;
    state.progress  = data.progress;
    state.next      = null;
    state.nextHTML  = null;
    card.innerHTML  = buildCardHTML(state.word);
    renderStats();
    setPhase(2, true);            // undo lands on already-revealed state
    speakWord(state.word.word);   // play audio for the restored word
    renderPrevCard(null);
    renderNextCard(null);
    cardStage.style.height = ''; // release: card height = prevH = stage height → no jump
  } else {
    exitAnim.cancel(); enterAnim.cancel();
    cardStage.style.height = '';
    card.getAnimations().forEach(a => a.cancel());
    card.style.transform = '';
    renderPrevCard(state.prevHTML || null);
  }
  state.animating = false;
  prefetchNext();
}

card.addEventListener('touchstart', e => {
  _sx = e.touches[0].clientX;
  _sy = e.touches[0].clientY;
  _swipeDir = null;
  _cachedCardW = card.offsetWidth + CARD_GAP; // cache once — avoids per-frame layout reads
}, { passive: true });

card.addEventListener('touchmove', e => {
  if (state.phase < 1 || !state.word) return;
  const dx = e.touches[0].clientX - _sx;
  const dy = e.touches[0].clientY - _sy;
  const adx = Math.abs(dx), ady = Math.abs(dy);
  if (_swipeDir === null && (adx > 6 || ady > 6)) {
    _swipeDir = adx > ady ? 'h' : 'v';
  }
  if (_swipeDir !== 'h' || dx <= 0) return;

  const W = _cachedCardW; // set in touchstart — no per-frame layout read
  let travel;
  if (state.prev) {
    travel = dx <= UNDO_THRESHOLD ? dx : UNDO_THRESHOLD + (dx - UNDO_THRESHOLD) * 0.25;
    cardPrev.style.transform = `translateX(${-W + travel}px) translateY(-50%)`;
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
  if (!state.animating) _snapAllBack();
}, { passive: true });

// ── Event listeners ───────────────────────────────────────────────────────────

// Event delegation: all interactive elements live inside #card and are recreated
// on every advance/undo (via buildCardHTML). Listening on #card itself survives.
card.addEventListener('click', e => {
  if (state.animating || card.classList.contains('loading')) return;

  const hit = e.target.closest('.rating-btn, .speak-btn');
  if (hit?.classList.contains('rating-btn')) {
    if (state.phase !== 2 || !state.word) return;
    submitRating(parseInt(hit.dataset.rating, 10));
    return;
  }
  if (hit) { speakWord(); return; }

  if (state.phase === 1) setPhase(2);
});

card.addEventListener('keydown', e => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  if (e.target.closest('.speak-btn')) {
    e.preventDefault();
    speakWord();
  }
});

// ── Auth / boot ─────────────────────────────────────────────────────────────

function redirectToLogin() {
  location.replace('/login');
}

// Any API call may 401 if the session expired mid-use — bounce to login.
function guard401(res) {
  if (res.status === 401) { redirectToLogin(); throw new Error('unauthenticated'); }
  return res;
}

async function boot() {
  // First-paint loading state: show a single placeholder card and keep prev/next
  // empty + hidden so they don't stack behind #card before the first word lands.
  card.innerHTML = `<div class="card-loading">正在加载…</div>`;
  renderPrevCard(null);
  renderNextCard(null);

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/service-worker.js').catch(() => {});
    // ui.js（随设置浮层一起加载）接管 controllerchange + 更新提示；仅当它缺席时这里兜底。
    if (!window.UI) {
      let _reloaded = false;
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (_reloaded) return; _reloaded = true;
        try { sessionStorage.setItem('mz_updated', '1'); } catch (_) {}
        location.reload();
      });
    }
  }
  if (!window.UI) {
    try {
      if (sessionStorage.getItem('mz_updated')) {
        sessionStorage.removeItem('mz_updated');
        showToast('已更新到最新版本');
      }
    } catch (_) {}
  }
  try {
    const res = await fetch('/api/auth/me');
    if (!res.ok) return redirectToLogin();
  } catch (_) {
    return redirectToLogin();
  }
  fetchWord();
}

document.addEventListener('DOMContentLoaded', boot);
