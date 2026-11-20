"""Shared fixtures: temporary accounts created with the admin CLI and removed afterwards.

Run:  control-plane/.venv/bin/python -m pytest security-tests -q   (against `docker compose up`)
"""

import os
import secrets
import subprocess
import time

import httpx
import pytest

BASE = os.environ.get("OWNCLOUD_URL", "http://localhost:8088")
ORIGIN = BASE
CSRF = {"X-OwnCloud-CSRF": "1"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = secrets.token_hex(3)


def cli(*args: str, check: bool = True) -> str:
    """Account administration inside the control-plane container."""
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "control-plane", "python", "-m", "app.cli", *args],
        cwd=ROOT, capture_output=True, text=True,
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def request(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    """Retry nginx rate-limit responses so ordinary tests are not affected by bursts."""
    for attempt in range(8):
        response = client.request(method, url, **kwargs)
        if response.status_code != 429:
            return response
        time.sleep(1 + attempt)
    return response


def browser(username: str, password: str) -> httpx.Client:
    """A signed-in client that behaves like the console in a browser."""
    client = httpx.Client(base_url=BASE, timeout=60, headers={**CSRF, "Origin": ORIGIN})
    response = request(client, "POST", "/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return client


class Account:
    def __init__(self, username: str, password: str):
        self.username, self.password = username, password
        self.client = browser(username, password)
        self.id = self.client.get("/api/auth/me").json()["id"]

    def close(self) -> None:
        for app in request(self.client, "GET", "/api/apps").json():
            if app.get("owner") == self.username:
                request(self.client, "DELETE", f"/api/apps/{app['id']}")
        self.client.close()
        cli("delete", self.username, check=False)


def _account(prefix: str, admin: bool = False) -> Account:
    username = f"{prefix}-{RUN}"
    password = cli("create", username, *(["--admin"] if admin else []))
    return Account(username, password)


@pytest.fixture(scope="session")
def anon():
    with httpx.Client(base_url=BASE, timeout=30) as client:
        yield client


@pytest.fixture(scope="session")
def admin_account():
    account = _account("sec-admin", admin=True)
    yield account
    account.close()


@pytest.fixture(scope="session")
def admin(admin_account):
    return admin_account.client


@pytest.fixture(scope="session")
def alice():
    account = _account("alice")
    yield account
    account.close()


@pytest.fixture(scope="session")
def bob():
    account = _account("bob")
    yield account
    account.close()


@pytest.fixture(scope="session")
def app_id(admin):
    """A small static app to attack, owned by the test admin. It contains a stored XSS payload."""
    files = [("files", ("site/index.html", b"<h1>target</h1><script>alert(1)</script>", "text/html"))]
    response = request(admin, "POST", "/api/apps", data={"name": "attack-target"}, files=files)
    assert response.status_code == 201, response.text
    yield response.json()["id"]
    request(admin, "DELETE", f"/api/apps/{response.json()['id']}")


@pytest.fixture(scope="session")
def alice_app(alice):
    files = [("files", ("index.html", b"<h1>alice private</h1>", "text/html")),
             ("files", ("lib/secret.py", b"API_KEY = 'alice-only-secret-value'\n", "text/plain"))]
    response = request(alice.client, "POST", "/api/apps",
                       data={"name": "alice-app", "env": '{"ALICE_DB_PASSWORD": "alice-private-env"}'}, files=files)
    assert response.status_code == 201, response.text
    return response.json()["id"]
