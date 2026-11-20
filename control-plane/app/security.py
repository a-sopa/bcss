"""Authentication and request hardening for the control plane.

- User accounts with scrypt-hashed passwords; roles "admin" and "user".
- Browser sessions: server-side, in an HttpOnly, SameSite=Strict cookie; tokens are stored hashed.
- Personal access tokens (`Authorization: Bearer oc_…`) for tools such as the VS Code extension. They are
  limited to an allow-list of code/analysis routes ("read" or "write" scope) and can never manage
  accounts or tokens.
- CSRF: cookie-authenticated state changes need the X-OwnCloud-CSRF header (a custom header forces a CORS
  preflight, which this API never grants) and, when present, an allow-listed Origin. Bearer tokens are not
  sent automatically by browsers, so they need no CSRF header.
- Cookie tossing: a request carrying more than one session cookie is refused.
- DNS rebinding: the Host header must be allow-listed.
- Request size limits, login rate limiting and security headers on every response.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import config

log = logging.getLogger("owncloud.security")

SESSION_COOKIE = "owncloud_session"
CSRF_HEADER = "x-owncloud-csrf"
TOKEN_PREFIX = "oc_"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_PATHS = {"/api/auth/login", "/api/auth/signup", "/api/auth/config", "/api/health"}
UPLOAD_PATHS = {"/api/apps", "/api/migrations/analyze"}
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")

_APP = r"/api/apps/[0-9a-f]{10}"
TOKEN_ROUTES = {
    "read": [
        ("GET", re.compile(r"^/api/auth/me$")),
        ("GET", re.compile(r"^/api/apps$")),
        ("GET", re.compile(rf"^{_APP}$")),
        ("GET", re.compile(rf"^{_APP}/(files|file|analysis|archive)$")),
        ("POST", re.compile(rf"^{_APP}/analysis/file$")),
        ("POST", re.compile(r"^/api/analysis/file$")),
    ],
    "write": [
        ("PUT", re.compile(rf"^{_APP}/file$")),
        ("POST", re.compile(rf"^{_APP}/redeploy$")),
    ],
}

API_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-origin",
}


# ---------------------------------------------------------------- passwords


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    return salt.hex(), hashlib.scrypt(password.encode(), salt=salt, **SCRYPT).hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    if not isinstance(password, str) or not 0 < len(password) <= 256:
        return False
    _, candidate = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(candidate, hash_hex)


_DUMMY = hash_password("timing-equaliser")


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check, so unknown usernames are not revealed by timing."""
    verify_password(password, *_DUMMY)


COMMON_PASSWORDS = {
    "password1234", "123456789012", "qwertyuiopas", "passwordpassword", "letmein12345", "administrator",
    "owncloud1234", "welcome12345", "iloveyou1234", "changeme1234",
}


def password_problem(password: str, username: str) -> str | None:
    if len(password) < 12:
        return "Passwords must be at least 12 characters"
    if len(password) > 256:
        return "Passwords must be at most 256 characters"
    if password.lower() in COMMON_PASSWORDS or username.lower() in password.lower():
        return "Choose a less predictable password"
    return None


def initial_admin_password(data_dir: Path, configured: str | None) -> tuple[str, str]:
    """(salt, hash) for the first admin: the configured password, the pre-accounts admin, or a generated one."""
    if configured:
        if len(configured) < 12:
            raise RuntimeError("OWNCLOUD_ADMIN_PASSWORD must be at least 12 characters")
        return hash_password(configured)
    legacy = data_dir / "admin.json"
    if legacy.is_file():
        record = json.loads(legacy.read_text())
        return record["salt"], record["hash"]
    password = secrets.token_urlsafe(18)
    data_dir.mkdir(parents=True, exist_ok=True)
    secret_file = data_dir / "admin-password.txt"
    secret_file.write_text(password + "\n")
    os.chmod(secret_file, 0o600)
    log.warning("Created the OwnCloud user 'admin'; read its password from %s", secret_file)
    return hash_password(password)


# ---------------------------------------------------------------- sessions and rate limiting


class Sessions:
    def __init__(self, ttl: int, limit: int = 1000) -> None:
        self._ttl = ttl
        self._limit = limit
        self._sessions: dict[str, tuple[str, float]] = {}  # sha256(token) → (user id, expiry)
        self._lock = threading.Lock()

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._sessions = {k: v for k, v in self._sessions.items() if v[1] > now}
            while len(self._sessions) >= self._limit:
                self._sessions.pop(min(self._sessions, key=lambda k: self._sessions[k][1]))
            self._sessions[self._key(token)] = (user_id, now + self._ttl)
        return token

    def user(self, token: str | None) -> str | None:
        if not token or len(token) > 128:
            return None
        with self._lock:
            entry = self._sessions.get(self._key(token))
            return entry[0] if entry and entry[1] > time.time() else None

    def revoke(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._sessions.pop(self._key(token), None)

    def revoke_user(self, user_id: str, keep: str | None = None) -> None:
        """End every session of a user (optionally except the current one)."""
        kept = self._key(keep) if keep else None
        with self._lock:
            self._sessions = {k: v for k, v in self._sessions.items() if v[0] != user_id or k == kept}


class RateLimiter:
    """At most `per_client` events per client and `overall` in total per window."""

    def __init__(self, per_client: int, overall: int, window: int = 300) -> None:
        self.per_client, self.overall, self.window = per_client, overall, window
        self._events: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()
        self._lock = threading.Lock()

    def _trim(self, queue: deque[float], now: float) -> None:
        while queue and queue[0] < now - self.window:
            queue.popleft()

    def retry_after(self, client: str) -> int:
        now = time.time()
        with self._lock:
            mine = self._events.setdefault(client, deque())
            self._trim(mine, now)
            self._trim(self._all, now)
            if len(mine) >= self.per_client:
                return int(mine[0] + self.window - now) + 1
            if len(self._all) >= self.overall:
                return int(self._all[0] + self.window - now) + 1
            return 0

    def record(self, client: str) -> None:
        now = time.time()
        with self._lock:
            self._events.setdefault(client, deque()).append(now)
            self._all.append(now)
            if len(self._events) > 10_000:
                self._events.clear()

    def clear(self, client: str) -> None:
        with self._lock:
            self._events.pop(client, None)


def client_id(request: Request) -> str:
    """The peer address; X-Real-IP only when running behind the bundled proxy, which always sets it."""
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-real-ip")
    if config.TRUST_PROXY and forwarded:
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return peer


# ---------------------------------------------------------------- request guard


@dataclass(frozen=True)
class Principal:
    id: str
    username: str
    role: str
    via: str  # "session" or "token"
    scope: str | None = None  # token scope
    session: str | None = None  # raw session token, to keep it when revoking the others

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _host(header: str) -> str:
    header = header.strip().lower()
    if header.startswith("["):
        return header[1:].split("]", 1)[0]
    return header.rsplit(":", 1)[0] if header.count(":") == 1 else header


def _deny(status: int, detail: str) -> Response:
    return JSONResponse({"detail": detail}, status_code=status, headers=API_HEADERS)


def _token_allowed(scope: str, method: str, path: str) -> bool:
    routes = TOKEN_ROUTES["read"] + (TOKEN_ROUTES["write"] if scope == "write" else [])
    return any(method == m and pattern.match(path) for m, pattern in routes)


class Guard(BaseHTTPMiddleware):
    def __init__(self, app, sessions: Sessions, users: Callable[[str], dict | None],
                 tokens: Callable[[str], dict | None]) -> None:
        super().__init__(app)
        self.sessions = sessions
        self.users = users
        self.tokens = tokens

    async def dispatch(self, request: Request, call_next) -> Response:
        if _host(request.headers.get("host", "")) not in config.ALLOWED_HOSTS:
            return _deny(400, "Invalid host")

        path = request.url.path
        unsafe = request.method not in SAFE_METHODS
        authorization = request.headers.get("authorization")

        if unsafe:
            origin = request.headers.get("origin")
            if origin is not None and origin not in config.ALLOWED_ORIGINS:
                return _deny(403, "Cross-origin request refused")
            if authorization is None and request.headers.get(CSRF_HEADER) != "1":
                return _deny(403, "Missing CSRF header")
            length = request.headers.get("content-length")
            if length is None:
                if request.headers.get("transfer-encoding"):
                    return _deny(411, "Content-Length required")
            else:
                if not length.isdigit():
                    return _deny(400, "Invalid Content-Length")
                limit = config.MAX_UPLOAD_BYTES + 1024 * 1024 if path in UPLOAD_PATHS else config.MAX_JSON_BODY
                if int(length) > limit:
                    return _deny(413, "Request body too large")

        # Another site on this host (e.g. a hosted app on another port) can set cookies for it.
        if request.headers.get("cookie", "").count(f"{SESSION_COOKIE}=") > 1:
            response = _deny(400, "Conflicting session cookies; sign in again")
            response.delete_cookie(SESSION_COOKIE, path="/api")
            return response

        request.state.principal = None
        if path.startswith("/api/") and path not in PUBLIC_PATHS:
            principal = self._authenticate(request, authorization)
            if isinstance(principal, Response):
                return principal
            request.state.principal = principal

        response = await call_next(request)
        for key, value in API_HEADERS.items():
            response.headers.setdefault(key, value)
        return response

    def _authenticate(self, request: Request, authorization: str | None) -> Principal | Response:
        if authorization is not None:
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() != "bearer" or not token.startswith(TOKEN_PREFIX) or len(token) > 128:
                return _deny(401, "Invalid access token")
            record = self.tokens(token)
            if record is None:
                return _deny(401, "Invalid or expired access token")
            if not _token_allowed(record["scope"], request.method, request.url.path):
                return _deny(403, "This access token cannot be used here")
            user = self.users(record["user_id"])
            if user is None or user["disabled"]:
                return _deny(401, "Account disabled")
            return Principal(user["id"], user["username"], user["role"], "token", record["scope"])

        raw = request.cookies.get(SESSION_COOKIE)
        user_id = self.sessions.user(raw)
        user = self.users(user_id) if user_id else None
        if user is None or user["disabled"]:
            return _deny(401, "Authentication required")
        return Principal(user["id"], user["username"], user["role"], "session", session=raw)
