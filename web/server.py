from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fsrs import Rating
from pydantic import BaseModel, Field

from memorize.config import DB_PATH
from memorize.scheduler import WordScheduler
from memorize.word_store import WordStore
from web.auth import SESSION_TTL, AuthStore

log = logging.getLogger(__name__)

_STATIC = Path(__file__).parent / "static"
_COOKIE = "session"
# Secure by default: cookie is only sent over HTTPS. Plain-HTTP local dev must
# opt out with SECURE_COOKIES=0, otherwise the browser drops the session cookie.
_SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "1").lower() in ("1", "true", "yes")
_APP_VERSION = os.environ.get("APP_VERSION", "dev")

# Per-user in-memory schedulers. Each holds its own FSRS queue / undo state.
# A WordScheduler instance is NOT thread-safe, so every user also gets a lock
# that routes hold for the whole request — this serializes one user's concurrent
# requests while different users still run in parallel. The registry lock only
# guards creation of these entries.
_schedulers: dict[int, WordScheduler] = {}
_user_locks: dict[int, threading.Lock] = {}
_registry_lock = threading.Lock()


def _get_lock(user_id: int) -> threading.Lock:
    # The lock is created once per user and never removed for the process lifetime.
    # This is the key invariant: every request for a user — including one that
    # rebuilds the scheduler after it was dropped — shares the SAME lock, so
    # per-user serialization can never be split by two lock objects. The dict is
    # bounded by the number of distinct users seen this process, which for this
    # app's scale is negligible (and cleared on restart).
    with _registry_lock:
        lock = _user_locks.get(user_id)
        if lock is None:
            lock = _user_locks[user_id] = threading.Lock()
        return lock


def _ensure_scheduler(app: FastAPI, user_id: int) -> WordScheduler | None:
    """Return the user's scheduler, building it on first use. Returns None if the
    user no longer exists. MUST be called while holding that user's lock."""
    with _registry_lock:
        sch = _schedulers.get(user_id)
    if sch is not None:
        return sch
    # Building fresh. Verify the user still exists before writing any per-user data:
    # this runs under the user lock, which admin_delete_user also holds for the whole
    # deletion, so a request that races a delete can't resurrect cards for a removed
    # user. init_cards_for_user also backfills cards for words imported after signup.
    if not app.state.auth.get_user_by_id(user_id):
        return None
    app.state.store.init_cards_for_user(user_id)
    sch = WordScheduler(app.state.store, user_id=user_id)
    with _registry_lock:
        _schedulers[user_id] = sch
    return sch


def _compute_stage(word: dict) -> str:
    if word["reps"] == 0:
        return "新词"
    s = word["stability"]
    if s <= 1:
        return "初识"
    if s <= 7:
        return "记忆"
    if s <= 21:
        return "熟悉"
    return "掌握"


def _build_response(scheduler: WordScheduler, store: WordStore, user_id: int) -> dict:
    word = scheduler.current_word()
    stats = store.get_today_stats(user_id)
    if word:
        word = dict(word)
        word["stage"] = _compute_stage(word)
        intervals = store.get_preview_intervals(word["id"], user_id)
    else:
        intervals = None
    progress = store.get_progress(user_id)
    return {"word": word, "stats": stats, "intervals": intervals, "progress": progress}


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = WordStore(DB_PATH)
    auth = AuthStore(DB_PATH)
    app.state.store = store
    app.state.auth = auth

    admin_email = os.environ.get("ADMIN_EMAIL", "").strip()
    admin_pass = os.environ.get("ADMIN_PASSWORD", "")
    if admin_email and admin_pass:
        admin = auth.ensure_admin(admin_email, admin_pass)
        # Bind legacy/desktop data (user 1) to the admin if ids line up; otherwise
        # just make sure the admin has a full deck.
        store.init_cards_for_user(admin["id"])
        log.info("Admin account ensured: %s (id=%d)", admin_email, admin["id"])
    elif auth.user_count() == 0:
        log.warning(
            "No users exist and ADMIN_EMAIL/ADMIN_PASSWORD not set — nobody can log in. "
            "Set these env vars to bootstrap the first admin."
        )
    auth.purge_expired()
    yield


app = FastAPI(lifespan=lifespan)


# ── Auth dependencies ─────────────────────────────────────────────────────────

def current_user(request: Request) -> dict:
    sid = request.cookies.get(_COOKIE)
    user = request.app.state.auth.get_session_user(sid)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="admin only")
    return user


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    response.headers["X-Frame-Options"] = "DENY"
    # 缓存策略集中一处按 path 裁决（不散落到各路由）：SW 脚本绝不缓存，否则新版 SW
    # 发不到设备、PWA 永远更新不了缓存的 CSS/JS（本次「更新不生效」的根因）；入口壳 /
    # /login、manifest、/static 版本化资源统一 no-cache，让 Cloudflare/浏览器每次只做
    # 廉价条件校验（未变即 304），改动即时到达设备。SW 自己的离线缓存不受此影响。
    path = request.url.path
    if path == "/service-worker.js":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    elif path.startswith("/static/") or path in ("/", "/login", "/manifest.webmanifest"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/static", StaticFiles(directory=_STATIC), name="static")


# ── Pages ─────────────────────────────────────────────────────────────────────

def _guarded_page(request: Request, filename: str):
    """Serve an authenticated page, or 302 to /login when there's no valid session.
    Server-side guard (defense in depth) — the page JS also redirects on 401."""
    if request.app.state.auth.get_session_user(request.cookies.get(_COOKIE)) is None:
        return RedirectResponse("/login", status_code=302)
    return FileResponse(_STATIC / filename)


@app.get("/")
def root(request: Request):
    return _guarded_page(request, "index.html")


@app.get("/login")
def login_page():
    return FileResponse(_STATIC / "login.html")


def _settings_redirect(request: Request, target: str, login_next: str):
    """Single-page now: these legacy page routes open the in-page overlay. /admin
    lands on the 用户管理 tab (#admin); the rest on #settings. The fragment never
    reaches the server, so for a logged-out visitor we carry it through ?next
    instead of silently dropping them on the card view after login."""
    if request.app.state.auth.get_session_user(request.cookies.get(_COOKIE)) is None:
        return RedirectResponse(f"/login?next={login_next}", status_code=302)
    return RedirectResponse(target, status_code=302)


@app.get("/admin")
def admin_page(request: Request):
    return _settings_redirect(request, "/#admin", "/%23admin")


@app.get("/settings")
def settings_page(request: Request):
    return _settings_redirect(request, "/#settings", "/%23settings")


@app.get("/profile")
def profile_page(request: Request):
    return _settings_redirect(request, "/#settings", "/%23settings")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(_STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/service-worker.js")
def service_worker():
    # Cache-Control（no-store）由 security_headers_middleware 按 path 统一设置。
    return FileResponse(_STATIC / "service-worker.js", media_type="application/javascript")


@app.get("/.well-known/assetlinks.json")
def asset_links():
    # Digital Asset Links — lets the signed TWA APK drop the browser address bar.
    return FileResponse(_STATIC / "assetlinks.json", media_type="application/json")


@app.get("/memorize.apk")
def download_apk():
    return FileResponse(
        _STATIC / "memorize.apk",
        media_type="application/vnd.android.package-archive",
        filename="memorize.apk",
    )


# ── Auth API ──────────────────────────────────────────────────────────────────

@app.get("/api/version")
def api_version():
    return {"version": _APP_VERSION}


class LoginRequest(BaseModel):
    email: str
    password: str


def _set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        key=_COOKIE,
        value=sid,
        httponly=True,
        samesite="lax",
        secure=_SECURE_COOKIES,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(_COOKIE, path="/", secure=_SECURE_COOKIES, httponly=True, samesite="lax")


@app.post("/api/auth/login")
def login(body: LoginRequest, request: Request):
    auth: AuthStore = request.app.state.auth
    user = auth.verify_login(body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    sid = auth.create_session(user["id"])
    response = JSONResponse({"user": user})
    _set_session_cookie(response, sid)
    return response


@app.post("/api/auth/logout")
def logout(request: Request):
    sid = request.cookies.get(_COOKIE)
    request.app.state.auth.delete_session(sid)
    response = JSONResponse({"ok": True})
    _clear_session_cookie(response)
    return response


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    return {"user": user}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/auth/password")
def change_password(body: ChangePasswordRequest, request: Request,
                    user: dict = Depends(current_user)):
    auth: AuthStore = request.app.state.auth
    if not auth.verify_login(user["email"], body.current_password):
        raise HTTPException(status_code=400, detail="当前密码错误")
    try:
        auth.set_password(user["id"], body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # set_password revokes every session (including this one); the client must
    # re-login with the new password, so clear the cookie here too.
    response = JSONResponse({"ok": True})
    _clear_session_cookie(response)
    return response


# ── Word API (per-user) ───────────────────────────────────────────────────────

class RateRequest(BaseModel):
    word_id: int
    rating: int = Field(ge=1, le=4)


class EmptyRequest(BaseModel):
    pass


@contextmanager
def _user_scheduler(request: Request, user_id: int):
    """Yield the user's scheduler while holding their per-user lock; 401 if the
    user no longer exists. `with lock` guarantees release on every path, including
    a provisioning error or the 401 below."""
    lock = _get_lock(user_id)
    with lock:
        sch = _ensure_scheduler(request.app, user_id)
        if sch is None:
            raise HTTPException(status_code=401, detail="账号已不存在")
        yield sch


@app.get("/api/word")
def get_word(request: Request, user: dict = Depends(current_user)):
    with _user_scheduler(request, user["id"]) as sch:
        return _build_response(sch, request.app.state.store, user["id"])


@app.get("/api/peek")
def peek_word(request: Request, user: dict = Depends(current_user)):
    with _user_scheduler(request, user["id"]) as sch:
        word = sch.peek_next()
        if word:
            word = dict(word)
            word["stage"] = _compute_stage(word)
            intervals = request.app.state.store.get_preview_intervals(word["id"], user["id"])
        else:
            intervals = None
    return {"word": word, "intervals": intervals}


@app.post("/api/rate")
def rate_word(body: RateRequest, request: Request, user: dict = Depends(current_user)):
    with _user_scheduler(request, user["id"]) as sch:
        store = request.app.state.store
        sch.rate(body.word_id, Rating(body.rating))
        resp = _build_response(sch, store, user["id"])
        nxt = sch.peek_next()
        if nxt:
            nxt = dict(nxt)
            nxt["stage"] = _compute_stage(nxt)
            resp["next"] = {"word": nxt, "intervals": store.get_preview_intervals(nxt["id"], user["id"])}
        else:
            resp["next"] = {"word": None, "intervals": None}
        return resp


@app.post("/api/undo")
def undo_word(body: EmptyRequest, request: Request, user: dict = Depends(current_user)):
    store = request.app.state.store
    with _user_scheduler(request, user["id"]) as sch:
        word = sch.undo_last_rating()
        if not word:
            return {"word": None, "stats": None, "intervals": None, "progress": None}
        word = dict(word)
        word["stage"] = _compute_stage(word)
        intervals = store.get_preview_intervals(word["id"], user["id"])
        stats = store.get_today_stats(user["id"])
        progress = store.get_progress(user["id"])
    return {"word": word, "stats": stats, "intervals": intervals, "progress": progress}


# ── Admin API ─────────────────────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""
    is_admin: bool = False


class SetPasswordRequest(BaseModel):
    password: str


@app.get("/api/admin/users")
def admin_list_users(request: Request, admin: dict = Depends(require_admin)):
    return {"users": request.app.state.auth.list_users()}


@app.post("/api/admin/users")
def admin_create_user(body: CreateUserRequest, request: Request, admin: dict = Depends(require_admin)):
    auth: AuthStore = request.app.state.auth
    try:
        user = auth.create_user(body.email, body.password, body.display_name, body.is_admin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Give the new user a full deck up front.
    request.app.state.store.init_cards_for_user(user["id"])
    return {"user": user}


@app.post("/api/admin/users/{user_id}/password")
def admin_set_password(user_id: int, body: SetPasswordRequest, request: Request,
                       admin: dict = Depends(require_admin)):
    auth: AuthStore = request.app.state.auth
    if not auth.get_user_by_id(user_id):
        raise HTTPException(status_code=404, detail="user not found")
    try:
        auth.set_password(user_id, body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # set_password already deleted the user's sessions (forcing re-login). The
    # in-memory scheduler holds only password-independent FSRS queue state, so it's
    # safe to keep — no eviction needed.
    return {"ok": True}


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, request: Request, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不能删除自己")
    auth: AuthStore = request.app.state.auth
    if not auth.get_user_by_id(user_id):
        raise HTTPException(status_code=404, detail="user not found")
    # Hold the user's lock across the whole deletion so it can't interleave with an
    # in-flight rate/undo/word request for that user. The lock object itself is
    # never removed (see _get_lock), so dropping the scheduler here can't split
    # the lock: any straggler request rebuilds a fresh empty scheduler under the
    # same lock and simply finds no cards (data already gone) — a harmless no-op.
    lock = _get_lock(user_id)
    with lock:
        auth.delete_user(user_id)
        request.app.state.store.delete_user_data(user_id)
        with _registry_lock:
            _schedulers.pop(user_id, None)
    return {"ok": True}
