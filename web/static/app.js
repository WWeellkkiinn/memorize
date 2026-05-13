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
  nextHTML: null,   // pre-rendered HTML for next word (built in prefetchNext)
  countdownSec: 3,
  countdownTimer: null,
  revealTimer: null,
  animating: false,
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const cardStage     = $('card-stage');
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
const ratingBtns    = Array.from(ratingRow.querySelectorAll('button')); // cached once
const speakBtn      = $('speak-btn');
const statStage     = $('stat-stage');
const statProgress  = $('stat-progress');
const statCounts    = $('stat-counts');
const toast         = $('toast');

// ── Audio ─────────────────────────────────────────────────────────────────────

let _audio = null;

// word 传入时创建新音频对象并播放（自动播放）；不传时重播当前缓存（按钮重听）
function speakWord(word) {
  if (word) {
    _audio = new Audio(`https://dict.youdao.com/dictvoice?audio=${encodeURIComponent(word)}&type=2`);
  }
  if (!_audio) return;
  _audio.currentTime = 0;
  _audio.play().catch(() => {});
}

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

function renderWord() {
  const w = state.word;
  if (!w) return;
  wordPos.textContent    = w.pos || '';
  wordPhone.textContent  = w.phonetic ? `/${w.phonetic}/` : '';
  wordText.innerHTML     = buildMorphemeHTML(w);
  definition.textContent = w.definition || '';
  examples.innerHTML     = buildExamplesHTML(w);
  renderIntervals();
  speakWord(w.word);
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

function setPhase(n, skipReveal = false) {
  clearTimers();
  state.phase = n;

  if (n === 1) {
    show(hintArea);
    visHide(definition);
    show(examples);
    ratingRow.classList.remove('revealing');
    definition.classList.remove('revealing');
    visHide(ratingRow);
    renderWord(); // replaces examples.innerHTML — querySelectorAll after to hit new nodes
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
    .then(r => { clearTimeout(timeoutId); if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(data => {
      if (ctrl !== _prefetchCtrl) return; // stale — a newer prefetch superseded this one
      if (data.word && data.word.id !== forWord) {
        state.next = { ...data.word, intervals: data.intervals };
        state.nextHTML = buildNextCardHTML(state.next); // pre-render off critical path
      } else {
        state.next = null; // peek returned no new word — clear any stale data
        state.nextHTML = null;
      }
    })
    .catch(() => { clearTimeout(timeoutId); });
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
const RAIL_EASING  = 'ease-in-out';

// Build phase-1 HTML for #card-prev. IDs are intentionally duplicated from #card —
// CSS selectors apply equally (desired), and JS always uses startup-cached refs inside #card.
function buildNextCardHTML(word) {
  if (!word) return '';
  const stageColor = STAGE_COLORS[word.stage] || 'var(--text-muted)';
  return (
    `<div id="card-header">` +
    `<span id="word-text">${buildMorphemeHTML(word)}</span>` +
    `<div id="word-meta">` +
    `<span id="word-pos">${escHtml(word.pos || '')}</span>` +
    `<span id="word-phonetic">${word.phonetic ? '/' + escHtml(word.phonetic) + '/' : ''}</span>` +
    `</div></div>` +
    `<div id="answer-area">` +
    `<div id="hint-area"><div id="hint-text">单击查看答案</div></div>` +
    `<div id="definition" class="invisible">${escHtml(word.definition || '')}</div>` +
    `</div>` +
    `<div id="examples">${buildExamplesHTML(word)}</div>` +
    `<div id="rating-row" class="invisible">` +
    `<button class="rating-btn btn-again"><span class="btn-label">忘 了</span><span class="interval"></span></button>` +
    `<button class="rating-btn btn-hard"><span class="btn-label">模 糊</span><span class="interval"></span></button>` +
    `<button class="rating-btn btn-good"><span class="btn-label">记 得</span><span class="interval"></span></button>` +
    `<button class="rating-btn btn-easy"><span class="btn-label">轻 松</span><span class="interval"></span></button>` +
    `</div>` +
    `<div id="stats-row">` +
    `<span id="stat-stage" style="color:${stageColor}">${escHtml(word.stage || '')}</span>` +
    `<span id="stat-progress"></span><span id="stat-counts"></span>` +
    `</div>`
  );
}

// ── Parallel card track helpers ───────────────────────────────────────────────

const CARD_GAP = 16;

function getCardW() { return card.offsetWidth + CARD_GAP; }

function prevOffScreen(side = 'left', w = null) {
  const sign = side === 'right' ? 1 : -1;
  return `translateX(${sign * (w ?? getCardW())}px) translateY(-50%)`;
}

function resetCardPositions() {
  card.getAnimations().forEach(a => a.cancel());
  cardPrev.getAnimations().forEach(a => a.cancel());
  card.style.transform = '';
  cardPrev.style.transform = prevOffScreen('left');
}

function renderPrevCard(html, side = 'left', w = null) {
  cardPrev.getAnimations().forEach(a => a.cancel());
  if (!html) {
    cardPrev.style.visibility = 'hidden';
    cardPrev.innerHTML = '';
    return;
  }
  const offScreen = prevOffScreen(side, w); // read layout BEFORE DOM write to avoid forced reflow
  cardPrev.innerHTML = html;
  cardPrev.style.visibility = '';
  cardPrev.style.transform = offScreen;
}

async function submitRating(rating) {
  if (state.animating) return;
  state.animating = true;
  const wordId = state.word.id;
  const gen = ++_submitGen; // generation token — stale doSubmit retries check this
  card.classList.add('loading');
  ratingBtns.forEach(b => b.disabled = true);

  const SLIDE_DUR = 240;

  const unlock = () => {
    card.classList.remove('loading');
    ratingBtns.forEach(b => b.disabled = false);
    state.animating = false;
    if (_pendingUndo && state.prev) { _pendingUndo = false; _commitSwipe(); }
  };

  if (state.next) {
    // Optimistic: parallel slide — both cards visible simultaneously
    const prevHTML  = card.innerHTML;
    const nextWord  = state.next;

    // Pre-render next card off-screen RIGHT (compute W before DOM write to avoid double reflow)
    const W = getCardW();
    renderPrevCard(state.nextHTML || buildNextCardHTML(nextWord), 'right', W);

    // Both cards slide LEFT together on the same rail — identical easing keeps them locked
    const exitAnim = card.animate(
      [{ transform: 'translateX(0)' }, { transform: `translateX(${-W}px)` }],
      { duration: SLIDE_DUR, easing: RAIL_EASING, fill: 'forwards' }
    );
    const enterAnim = cardPrev.animate(
      [{ transform: `translateX(${W}px) translateY(-50%)` }, { transform: 'translateX(0) translateY(-50%)' }],
      { duration: SLIDE_DUR, easing: RAIL_EASING, fill: 'forwards' }
    );

    // Submit in background while animating; gen check prevents stale retries and state overwrites
    let doSubmitSettled = false;
    const doSubmit = (wid, r) => submitWithRetry(wid, r)
      .then(data => {
        doSubmitSettled = true;
        if (gen !== _submitGen) return; // newer rating submitted — discard stale response
        if (data.stats) { state.stats = data.stats; state.progress = data.progress ?? state.progress; renderStats(); }
        prefetchNext();
        // Handle pending undo here in case animation finished before doSubmit settled
        if (_pendingUndo && state.prev) { _pendingUndo = false; _commitSwipe(); }
      })
      .catch(() => {
        doSubmitSettled = true;
        if (gen !== _submitGen) return; // newer rating submitted — stop retrying silently
        showToast('提交失败，请检查网络', () => doSubmit(wid, r));
      });
    doSubmit(wordId, rating);

    await Promise.all([exitAnim.finished, enterAnim.finished]);

    // Invisible swap: set inline positions BEFORE canceling WAAPI fill so elements snap correctly
    renderPrevCard(prevHTML, 'left'); // old card → off-screen LEFT (cancels enterAnim inside)
    card.style.transform = '';        // #card target = center
    exitAnim.cancel();                // #card snaps to center (fill removed → inline style wins)

    // Update state and render new word into #card (now at 0)
    state.prev      = state.word;
    state.prevHTML  = prevHTML;
    state.word      = nextWord;
    state.intervals = nextWord.intervals || null;
    state.next      = null;
    state.nextHTML  = null;
    renderStats();
    setPhase(1);
    // Re-enable UI; check _pendingUndo only if doSubmit already settled — otherwise doSubmit.then handles it
    card.classList.remove('loading');
    ratingBtns.forEach(b => b.disabled = false);
    state.animating = false;
    if (_pendingUndo && state.prev && doSubmitSettled) { _pendingUndo = false; _commitSwipe(); }

  } else {
    // Fallback (no peek data): exit left + wait for API + enter from right (single-card)
    try {
      const prevHTML = card.innerHTML;
      const W = getCardW();
      const [data] = await Promise.all([
        submitWithRetry(wordId, rating),
        card.animate(
          [{ transform: 'translateX(0)' }, { transform: `translateX(${-W}px)` }],
          { duration: SLIDE_DUR, easing: EXIT_EASING, fill: 'forwards' }
        ).finished,
      ]);

      if (!data.word) {
        card.style.transform = '';
        card.getAnimations().forEach(a => a.cancel());
        card.classList.remove('loading');
        ratingBtns.forEach(b => b.disabled = false);
        _pendingUndo = false;
        state.animating = false;
        showToast('没有更多单词了');
        return;
      }

      // Snap card back to center, load new content
      card.style.transform = '';
      card.getAnimations().forEach(a => a.cancel());

      state.prev      = state.word;
      state.prevHTML  = prevHTML;
      state.word      = data.word;
      state.stats     = data.stats;
      state.progress  = data.progress;
      state.intervals = data.intervals;
      state.next      = null;
      state.nextHTML  = null;
      renderStats();
      setPhase(1);
      renderPrevCard(state.prevHTML, 'left');

      // Enter from right (single card) — buttons stay locked until animation completes
      await card.animate(
        [{ transform: `translateX(${W}px)` }, { transform: 'translateX(0)' }],
        { duration: SLIDE_DUR, easing: ENTER_EASING }
      ).finished;

      unlock();
      prefetchNext();
    } catch (e) {
      card.style.transform = '';
      card.getAnimations().forEach(a => a.cancel());
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
    cardPrev.style.transform = prevOffScreen();
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
    state.intervals = data.intervals;
    state.next      = null;
    state.nextHTML  = null;
    renderStats();
    renderWord();
    setPhase(2, true);
    renderPrevCard(null);
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

card.addEventListener('click', () => {
  if (state.animating) return;
  if (state.phase === 1) setPhase(2);
});

ratingRow.addEventListener('click', e => {
  e.stopPropagation();
  const btn = e.target.closest('[data-rating]');
  if (!btn || btn.disabled || card.classList.contains('loading')) return;
  if (state.phase !== 2 || !state.word) return;
  submitRating(parseInt(btn.dataset.rating, 10));
});

speakBtn.addEventListener('click', e => {
  e.stopPropagation();
  speakWord();
});

// ── Boot ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', fetchWord);
