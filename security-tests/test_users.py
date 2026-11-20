"""Attacks between accounts: IDOR, privilege escalation, token abuse, account lifecycle, enumeration."""

import subprocess
import time

import httpx
import pytest

from conftest import BASE, CSRF, ORIGIN, ROOT, RUN, browser, cli, request

APP_ROUTES = [
    ("GET", ""), ("GET", "/files"), ("GET", "/file?path=index.html"), ("GET", "/analysis"), ("GET", "/logs"),
    ("GET", "/stats"), ("GET", "/scan"), ("POST", "/redeploy"), ("POST", "/stop"), ("POST", "/start"),
    ("PUT", "/file?path=index.html"), ("POST", "/analysis/file"), ("GET", "/archive"),
    ("GET", "/deployments"), ("POST", "/rollback"), ("GET", "/traffic"), ("GET", "/incidents"),
    ("GET", "/database"), ("POST", "/database"), ("POST", "/database/optimize"),
    ("GET", "/loadtest/model"), ("GET", "/loadtests"), ("POST", "/loadtests"), ("GET", "/loadtest/k6"),
    ("DELETE", ""),
]


def _bearer(token: str, **extra) -> dict:
    return {"Authorization": f"Bearer {token}", **extra}


# ---------------------------------------------------------------- isolation between users (IDOR)


@pytest.mark.parametrize("method,suffix", APP_ROUTES)
def test_users_cannot_touch_each_others_apps(bob, alice_app, method, suffix):
    body = ({"content": "owned by bob"} if method == "PUT" else {"path": "a.py", "content": "x"} if "analysis/file" in suffix
            else {"max_users": 5} if suffix == "/loadtests" and method == "POST" else None)
    response = request(bob.client, method, f"/api/apps/{alice_app}{suffix}", json=body)
    assert response.status_code == 404, (method, suffix, response.status_code)  # indistinguishable from a missing app
    assert "alice" not in response.text


def test_app_lists_and_events_are_private(alice, bob, alice_app):
    assert alice_app in {a["id"] for a in request(alice.client, "GET", "/api/apps").json()}
    assert alice_app not in {a["id"] for a in request(bob.client, "GET", "/api/apps").json()}
    assert all(e["app_id"] != alice_app for e in request(bob.client, "GET", "/api/events", params={"limit": 1000}).json())
    assert request(bob.client, "GET", "/api/events", params={"app_id": alice_app}).status_code == 404


def test_admins_see_every_app_with_its_owner(admin, alice, alice_app):
    apps = {a["id"]: a for a in request(admin, "GET", "/api/apps").json()}
    assert apps[alice_app]["owner"] == alice.username


def test_secrets_never_leak_to_other_users(bob, admin, alice_app):
    for client in (bob.client, admin):
        listing = request(client, "GET", "/api/apps").text
        assert "alice-private-env" not in listing
    assert "alice-only-secret-value" not in request(bob.client, "GET", "/api/apps").text


# ---------------------------------------------------------------- privilege escalation


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/users", None),
    ("POST", "/api/users", {"username": "evil-admin", "password": "a-long-password-123", "role": "admin"}),
    ("PATCH", "/api/users/{self}", {"role": "admin"}),
    ("DELETE", "/api/users/{admin}", None),
])
def test_users_cannot_reach_admin_routes(bob, admin_account, method, path, body):
    url = path.format(self=bob.id, admin=admin_account.id)
    response = request(bob.client, method, url, json=body)
    assert response.status_code == 403
    assert request(bob.client, "GET", "/api/auth/me").json()["role"] == "user"


def test_signup_cannot_choose_a_role(anon):
    response = request(anon, "POST", "/api/auth/signup", headers=CSRF,
                       json={"username": f"mallory-{RUN}", "password": "a-long-password-123", "role": "admin"})
    assert response.status_code == 422  # unknown fields are rejected, never ignored


@pytest.mark.parametrize("username,password", [
    ("ab", "a-long-password-123"),                       # too short
    ("<script>alert(1)</script>", "a-long-password-123"),  # markup
    ("admin'--", "a-long-password-123"),                  # SQL
    ("../etc", "a-long-password-123"),                    # path
    (f"weak-{RUN}", "short"),                             # weak password
    (f"same-{RUN}", f"same-{RUN}-password"),               # password contains the username
    (f"common-{RUN}", "password1234"),                    # common password
])
def test_signup_validation(anon, username, password):
    response = request(anon, "POST", "/api/auth/signup", headers=CSRF, json={"username": username, "password": password})
    assert response.status_code == 422, (username, response.status_code)


def test_signup_creates_a_regular_isolated_user(anon, alice_app):
    with httpx.Client(base_url=BASE, timeout=30, headers=CSRF) as client:
        username = f"newbie-{RUN}"
        response = request(client, "POST", "/api/auth/signup", json={"username": username, "password": "correct-horse-battery"})
        try:
            if response.status_code == 429:
                pytest.skip("sign-up rate limit reached by earlier runs")
            assert response.status_code == 201
            assert response.json()["role"] == "user"
            assert request(client, "GET", "/api/apps").json() == []
            assert request(client, "POST", "/api/auth/signup", json={"username": username, "password": "another-password-1"}).status_code in (409, 429)
        finally:
            cli("delete", username, check=False)


def test_admins_cannot_lock_themselves_out(admin, admin_account):
    assert request(admin, "PATCH", f"/api/users/{admin_account.id}", json={"role": "user"}).status_code == 409
    assert request(admin, "PATCH", f"/api/users/{admin_account.id}", json={"disabled": True}).status_code == 409
    assert request(admin, "DELETE", f"/api/users/{admin_account.id}").status_code == 409


# ---------------------------------------------------------------- personal access tokens


@pytest.fixture(scope="module")
def alice_tokens(alice):
    read = request(alice.client, "POST", "/api/tokens", json={"name": "read", "scope": "read", "days": 1}).json()
    write = request(alice.client, "POST", "/api/tokens", json={"name": "write", "scope": "write", "days": 1}).json()
    yield read["token"], write["token"]
    for token in (read, write):
        request(alice.client, "DELETE", f"/api/tokens/{token['id']}")


def test_tokens_are_shown_once_and_stored_hashed(alice, alice_tokens):
    listing = request(alice.client, "GET", "/api/tokens").text
    assert alice_tokens[0] not in listing and alice_tokens[1] not in listing
    stored = cli("list")
    assert alice_tokens[0] not in stored


def test_read_token_can_read_and_analyse(alice_tokens, alice_app):
    with httpx.Client(base_url=BASE, timeout=30, headers=_bearer(alice_tokens[0])) as client:
        assert request(client, "GET", "/api/apps").status_code == 200
        assert request(client, "GET", f"/api/apps/{alice_app}/analysis").status_code == 200
        analysis = request(client, "POST", "/api/analysis/file", json={"path": "x.py", "content": "eval(input())\n"})
        assert analysis.status_code == 200 and analysis.json()["findings"][0]["severity"] == "critical"


@pytest.mark.parametrize("method,path,body", [
    ("PUT", "/api/apps/{app}/file?path=index.html", {"content": "x"}),
    ("POST", "/api/apps/{app}/redeploy", None),
    ("POST", "/api/apps/{app}/stop", None),
    ("DELETE", "/api/apps/{app}", None),
    ("POST", "/api/tokens", {"name": "escalate", "scope": "write"}),
    ("GET", "/api/tokens", None),
    ("POST", "/api/auth/password", {"current_password": "x", "new_password": "y" * 20}),
    ("GET", "/api/users", None),
    ("GET", "/api/events", None),
    ("GET", "/api/apps/{app}/logs", None),
    ("POST", "/api/apps/{app}/rollback", None),
    ("POST", "/api/apps/{app}/database", None),
    ("POST", "/api/apps/{app}/loadtests", {"max_users": 5}),
    ("GET", "/api/apps/{app}/traffic", None),
    ("GET", "/api/apps/{app}/incidents", None),
])
def test_read_token_is_limited(alice_tokens, alice_app, method, path, body):
    with httpx.Client(base_url=BASE, timeout=30, headers=_bearer(alice_tokens[0])) as client:
        response = request(client, method, path.format(app=alice_app), json=body)
        assert response.status_code == 403, (path, response.status_code)


def test_write_token_can_save_but_not_manage_the_account(alice_tokens, alice_app):
    with httpx.Client(base_url=BASE, timeout=30, headers=_bearer(alice_tokens[1])) as client:
        assert request(client, "PUT", f"/api/apps/{alice_app}/file", params={"path": "notes.txt"}, json={"content": "hi"}).status_code == 200
        assert request(client, "POST", "/api/tokens", json={"name": "x", "scope": "write"}).status_code == 403
        assert request(client, "DELETE", f"/api/apps/{alice_app}").status_code == 403
        assert request(client, "POST", "/api/apps", files=[("files", ("a.html", b"x"))], data={"name": "via-token"}).status_code == 403


def test_tokens_cannot_cross_users(alice_tokens, bob):
    bob_app = request(bob.client, "POST", "/api/apps", data={"name": "bob-app"}, files=[("files", ("index.html", b"bob"))]).json()["id"]
    with httpx.Client(base_url=BASE, timeout=30, headers=_bearer(alice_tokens[1])) as client:
        assert request(client, "GET", f"/api/apps/{bob_app}").status_code == 404
        assert request(client, "PUT", f"/api/apps/{bob_app}/file", params={"path": "index.html"}, json={"content": "pwned"}).status_code == 404
    request(bob.client, "DELETE", f"/api/apps/{bob_app}")


@pytest.mark.parametrize("header", [
    "Bearer oc_this-token-does-not-exist-at-all-1234567890", "Bearer not-an-owncloud-token", "Basic YWRtaW46YWRtaW4=",
    "Bearer " + "oc_" + "A" * 500, "Bearer", "",
])
def test_invalid_tokens_are_rejected(header):
    with httpx.Client(base_url=BASE, timeout=30, headers={"Authorization": header}) as client:
        assert request(client, "GET", "/api/apps").status_code == 401


def test_revoked_token_stops_working(alice):
    created = request(alice.client, "POST", "/api/tokens", json={"name": "temp", "scope": "read", "days": 1}).json()
    with httpx.Client(base_url=BASE, timeout=30, headers=_bearer(created["token"])) as client:
        assert request(client, "GET", "/api/apps").status_code == 200
        request(alice.client, "DELETE", f"/api/tokens/{created['id']}")
        assert request(client, "GET", "/api/apps").status_code == 401


def test_token_requests_from_other_origins_are_refused(alice_tokens, alice_app):
    headers = _bearer(alice_tokens[1], Origin="https://evil.example")
    with httpx.Client(base_url=BASE, timeout=30, headers=headers) as client:
        response = request(client, "PUT", f"/api/apps/{alice_app}/file", params={"path": "index.html"}, json={"content": "x"})
        assert response.status_code == 403


def test_users_cannot_revoke_each_others_tokens(alice, bob):
    created = request(alice.client, "POST", "/api/tokens", json={"name": "mine", "scope": "read", "days": 1}).json()
    assert request(bob.client, "DELETE", f"/api/tokens/{created['id']}").status_code == 404
    assert any(t["id"] == created["id"] for t in request(alice.client, "GET", "/api/tokens").json())
    request(alice.client, "DELETE", f"/api/tokens/{created['id']}")


# ---------------------------------------------------------------- account lifecycle


def test_disabling_a_user_ends_sessions_and_tokens(admin):
    username, password = f"temp-{RUN}", cli("create", f"temp-{RUN}")
    client = browser(username, password)
    token = request(client, "POST", "/api/tokens", json={"name": "t", "scope": "read", "days": 1}).json()["token"]
    user_id = request(client, "GET", "/api/auth/me").json()["id"]
    try:
        assert request(admin, "PATCH", f"/api/users/{user_id}", json={"disabled": True}).status_code == 200
        assert request(client, "GET", "/api/apps").status_code == 401
        with httpx.Client(base_url=BASE, timeout=30, headers=_bearer(token)) as bearer:
            assert request(bearer, "GET", "/api/apps").status_code == 401
        relogin = request(httpx.Client(base_url=BASE, headers=CSRF), "POST", "/api/auth/login", json={"username": username, "password": password})
        assert relogin.status_code == 401
    finally:
        request(admin, "DELETE", f"/api/users/{user_id}")
        client.close()


def test_password_change_signs_out_other_sessions(admin):
    username, password = f"pwchange-{RUN}", cli("create", f"pwchange-{RUN}")
    first, second = browser(username, password), browser(username, password)
    try:
        wrong = request(first, "POST", "/api/auth/password", json={"current_password": "nope", "new_password": "a-brand-new-password"})
        assert wrong.status_code == 403
        assert request(first, "POST", "/api/auth/password",
                       json={"current_password": password, "new_password": "a-brand-new-password"}).status_code == 200
        assert request(first, "GET", "/api/apps").status_code == 200      # this browser stays signed in
        assert request(second, "GET", "/api/apps").status_code == 401     # every other one is signed out
    finally:
        cli("delete", username, check=False)
        first.close()
        second.close()


# ---------------------------------------------------------------- enumeration and session attacks


def test_unknown_users_and_wrong_passwords_look_identical(anon, admin_account):
    def attempt(username):
        return request(anon, "POST", "/api/auth/login", headers=CSRF, json={"username": username, "password": "wrong-password-123"})

    known, unknown = attempt(admin_account.username), attempt(f"nobody-{RUN}")
    assert known.status_code == unknown.status_code == 401, (known.status_code, unknown.status_code)
    assert known.json() == unknown.json()


TIMING_PROBE = r"""
import statistics, time
from starlette.testclient import TestClient
from app.main import app, login_limiter
client = TestClient(app, base_url="http://localhost")
def timed(username):
    login_limiter._events.clear(); login_limiter._all.clear()  # measure the password check, not the limiter
    start = time.perf_counter()
    response = client.post("/api/auth/login", headers={"X-OwnCloud-CSRF": "1"},
                           json={"username": username, "password": "wrong-password-123"})
    assert response.status_code == 401, response.status_code
    return time.perf_counter() - start
known, unknown = [], []
for _ in range(10):
    known.append(timed("%s")); unknown.append(timed("ghost-user-nobody"))
print(statistics.median(known), statistics.median(unknown))
"""


def test_login_timing_does_not_reveal_usernames(admin_account):
    # Measured inside the container against the real endpoint (fresh rate limiter, no network noise).
    output = subprocess.run(
        ["docker", "compose", "exec", "-T", "control-plane", "python", "-c", TIMING_PROBE % admin_account.username],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    known, unknown = float(output[-2]), float(output[-1])
    assert known > 0.01 and unknown > 0.01, (known, unknown)  # both paths really run scrypt
    assert abs(known - unknown) < 0.25 * max(known, unknown), (known, unknown)


def test_cookie_tossing_is_refused(alice):
    session = alice.client.cookies.get("owncloud_session")
    tossed = f"owncloud_session=attacker-planted-value; owncloud_session={session}"
    with httpx.Client(base_url=BASE, timeout=30) as client:
        response = request(client, "GET", "/api/apps", headers={"Cookie": tossed})
        assert response.status_code == 400


def test_hosted_apps_are_a_different_site_from_the_console(admin, app_id):
    for _ in range(60):
        app = request(admin, "GET", f"/api/apps/{app_id}").json()
        if app["url"]:
            break
        time.sleep(1)
    assert app["url"].startswith("http://127.0.0.1:")  # console: localhost → separate cookie jar and site
    redirect = httpx.get("http://127.0.0.1:8088/api/apps", follow_redirects=False)
    assert redirect.status_code == 301 and redirect.headers["location"].startswith("http://localhost:8088/")


def test_signup_can_be_queried_without_signing_in(anon):
    assert request(anon, "GET", "/api/auth/config").json() == {"signup": True}


def test_session_fixation_is_not_possible(admin_account):
    planted = "attacker-chosen-session-id-value"
    with httpx.Client(base_url=BASE, timeout=30, headers={**CSRF, "Origin": ORIGIN}, cookies={"owncloud_session": planted}) as client:
        response = request(client, "POST", "/api/auth/login", json={"username": admin_account.username, "password": admin_account.password})
        assert response.cookies.get("owncloud_session") not in (None, planted)


def test_an_app_deleted_mid_deploy_leaves_nothing_running(bob):
    """Deleting during the build must not let the deploy start the app afterwards (an unmanaged app)."""
    files = [("files", ("index.html", b"<h1>short-lived</h1>", "text/html"))]
    app = request(bob.client, "POST", "/api/apps", data={"name": "short-lived"}, files=files).json()["id"]
    time.sleep(1)  # the deploy is now running in the background
    assert request(bob.client, "DELETE", f"/api/apps/{app}").status_code == 204
    seen, leftovers = False, ""
    for _ in range(25):  # observe from outside (Docker only) long enough for the deploy to finish
        time.sleep(3)
        leftovers = subprocess.run(["docker", "ps", "-a", "--filter", f"label=owncloud.app={app}", "--format", "{{.Names}}"],
                                   capture_output=True, text=True).stdout.strip()
        seen = seen or bool(leftovers)
    assert leftovers == "", leftovers
