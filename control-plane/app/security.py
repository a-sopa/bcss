"""Authentication and request hardening for the control plane.

- One admin account; the password is stored only as a scrypt hash.
- Server-side sessions in an HttpOnly, SameSite=Strict cookie; tokens are stored hashed.
- CSRF: state-changing requests need the X-OwnCloud-CSRF header (a custom header forces a CORS
  preflight, which this API never grants) and, when present, an allow-listed Origin. This matters
  because hosted apps run on other localhost ports, which browsers treat as the same *site*.
- DNS rebinding: the Host header must be allow-listed.
- Request size limits, login rate limiting and security headers on every response.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import threading
import time
from collections import deque
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import config

log = logging.getLogger("owncloud.security")

SESSION_COOKIE = "owncloud_session"
CSRF_HEADER = "x-owncloud-csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_PATHS = {"/api/auth/login", "/api/health"}
UPLOAD_PATHS = {"/api/apps", "/api/migrations/analyze"}
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}

API_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)


class Admin:
    """Holds the admin password hash. The plain password is never kept in memory after start-up."""

    def __init__(self, data_dir: Path, configured: str | None) -> None:
        self._salt = secrets.token_bytes(16)
        if configured:
            if len(configured) < 12:
                raise RuntimeError("OWNCLOUD_ADMIN_PASSWORD must be at least 12 characters")
            self._hash = _hash_password(configured, self._salt)
            return
        stored = data_dir / "admin.json"
        if stored.is_file():
            record = json.loads(stored.read_text())
            self._salt, self._hash = bytes.fromhex(record["salt"]), bytes.fromhex(record["hash"])
            return
        password = secrets.token_urlsafe(18)
        self._hash = _hash_password(password, self._salt)
        data_dir.mkdir(parents=True, exist_ok=True)
        stored.write_text(json.dumps({"salt": self._salt.hex(), "hash": self._hash.hex()}))
        secret_file = data_dir / "admin-password.txt"
        secret_file.write_text(password + "\n")
        os.chmod(secret_file, 0o600)
        log.warning("Generated the OwnCloud admin password; read it from %s", secret_file)

    def verify(self, password: str) -> bool:
        if not isinstance(password, str) or not 0 < len(password) <= 256:
            return False
        return hmac.compare_digest(_hash_password(password, self._salt), self._hash)


class Sessions:
    def __init__(self, ttl: int, limit: int = 200) -> None:
        self._ttl = ttl
        self._limit = limit
        self._sessions: dict[str, float] = {}  # sha256(token) → expiry
        self._lock = threading.Lock()

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create(self) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._sessions = {k: v for k, v in self._sessions.items() if v > now}
            while len(self._sessions) >= self._limit:
                self._sessions.pop(min(self._sessions, key=self._sessions.get))
            self._sessions[self._key(token)] = now + self._ttl
        return token

    def valid(self, token: str | None) -> bool:
        if not token or len(token) > 128:
            return False
        with self._lock:
            expiry = self._sessions.get(self._key(token))
            return expiry is not None and expiry > time.time()

    def revoke(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._sessions.pop(self._key(token), None)


class LoginLimiter:
    """At most `per_client` failures per client and `overall` failures in total per window."""

    def __init__(self, per_client: int = 5, overall: int = 30, window: int = 300) -> None:
        self.per_client, self.overall, self.window = per_client, overall, window
        self._failures: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()
        self._lock = threading.Lock()

    def _trim(self, queue: deque[float], now: float) -> None:
        while queue and queue[0] < now - self.window:
            queue.popleft()

    def retry_after(self, client: str) -> int:
        now = time.time()
        with self._lock:
            mine = self._failures.setdefault(client, deque())
            self._trim(mine, now)
            self._trim(self._all, now)
            if len(mine) >= self.per_client:
                return int(mine[0] + self.window - now) + 1
            if len(self._all) >= self.overall:
                return int(self._all[0] + self.window - now) + 1
            return 0

    def failed(self, client: str) -> None:
        now = time.time()
        with self._lock:
            self._failures.setdefault(client, deque()).append(now)
            self._all.append(now)
            if len(self._failures) > 10_000:
                self._failures.clear()

    def succeeded(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)


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


def _host(header: str) -> str:
    header = header.strip().lower()
    if header.startswith("["):
        return header[1:].split("]", 1)[0]
    return header.rsplit(":", 1)[0] if header.count(":") == 1 else header


def _deny(status: int, detail: str) -> Response:
    return JSONResponse({"detail": detail}, status_code=status, headers=API_HEADERS)


class Guard(BaseHTTPMiddleware):
    def __init__(self, app, sessions: Sessions) -> None:
        super().__init__(app)
        self.sessions = sessions

    async def dispatch(self, request: Request, call_next) -> Response:
        if _host(request.headers.get("host", "")) not in config.ALLOWED_HOSTS:
            return _deny(400, "Invalid host")

        path = request.url.path
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and origin not in config.ALLOWED_ORIGINS:
                return _deny(403, "Cross-origin request refused")
            if request.headers.get(CSRF_HEADER) != "1":
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

        if path.startswith("/api/") and path not in PUBLIC_PATHS:
            if not self.sessions.valid(request.cookies.get(SESSION_COOKIE)):
                return _deny(401, "Authentication required")

        response = await call_next(request)
        for key, value in API_HEADERS.items():
            response.headers.setdefault(key, value)
        return response
