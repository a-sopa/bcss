"""Settings, read once from the environment."""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("OWNCLOUD_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
QUANTUMTRACE_URL = os.environ.get("QUANTUMTRACE_URL", "http://localhost:8001").rstrip("/")

# Hosted apps publish a random host port on this address; links use PUBLIC_HOST.
BIND_HOST = os.environ.get("OWNCLOUD_BIND_HOST", "127.0.0.1")
PUBLIC_HOST = os.environ.get("OWNCLOUD_PUBLIC_HOST", "localhost")

# Per-app container limits.
APP_MEMORY = os.environ.get("OWNCLOUD_APP_MEMORY", "256m")
APP_CPUS = float(os.environ.get("OWNCLOUD_APP_CPUS", "0.5"))

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_UPLOAD_FILES = 2000
MAX_EDIT_BYTES = 1024 * 1024  # largest file the editor opens or saves
MAX_JSON_BODY = 2 * 1024 * 1024

# Hosted apps join this network, where containers cannot reach each other.
APP_NETWORK = os.environ.get("OWNCLOUD_APP_NETWORK", "owncloud-apps")
MAX_CONCURRENT_BUILDS = int(os.environ.get("OWNCLOUD_MAX_CONCURRENT_BUILDS", "2"))


def _csv(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# --- Security ---------------------------------------------------------------
# Admin password: set OWNCLOUD_ADMIN_PASSWORD, otherwise one is generated on first start
# and written to DATA_DIR/admin-password.txt (readable only by its owner).
ADMIN_PASSWORD = os.environ.get("OWNCLOUD_ADMIN_PASSWORD") or None
SESSION_TTL_SECONDS = int(os.environ.get("OWNCLOUD_SESSION_TTL", str(12 * 3600)))
COOKIE_SECURE = os.environ.get("OWNCLOUD_COOKIE_SECURE", "false").lower() == "true"
# Host header allow-list (DNS-rebinding protection) and Origin allow-list (CSRF protection).
ALLOWED_HOSTS = {h.lower() for h in _csv("OWNCLOUD_ALLOWED_HOSTS", "localhost,127.0.0.1,::1,control-plane")}
ALLOWED_ORIGINS = set(_csv(
    "OWNCLOUD_ALLOWED_ORIGINS",
    "http://localhost:8088,http://127.0.0.1:8088,http://localhost:5180,http://127.0.0.1:5180",
))
# Only behind the bundled nginx (which overwrites X-Real-IP) is that header trusted for rate limiting.
TRUST_PROXY = os.environ.get("OWNCLOUD_TRUST_PROXY", "false").lower() == "true"
ENABLE_API_DOCS = os.environ.get("OWNCLOUD_ENABLE_API_DOCS", "false").lower() == "true"
