"""Attack suite against a running OwnCloud stack (docker compose up).

Run:  control-plane/.venv/bin/python -m pytest security-tests -q
The admin password comes from OWNCLOUD_TEST_PASSWORD or the control-plane container.
The brute-force test runs last: it locks this machine out of *new* sign-ins for 5 minutes.
"""

import io
import json
import os
import subprocess
import time
import zipfile

import httpx
import pytest

BASE = os.environ.get("OWNCLOUD_URL", "http://localhost:8088")
ORIGIN = BASE
CSRF = {"X-OwnCloud-CSRF": "1"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _password() -> str:
    if os.environ.get("OWNCLOUD_TEST_PASSWORD"):
        return os.environ["OWNCLOUD_TEST_PASSWORD"]
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "control-plane", "cat", "/data/admin-password.txt"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()


def _request(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    """Retry nginx rate-limit responses so ordinary tests are not affected by bursts."""
    for attempt in range(8):
        response = client.request(method, url, **kwargs)
        if response.status_code != 429:
            return response
        time.sleep(1 + attempt)
    return response


@pytest.fixture(scope="session")
def anon():
    with httpx.Client(base_url=BASE, timeout=30) as client:
        yield client


@pytest.fixture(scope="session")
def admin():
    client = httpx.Client(base_url=BASE, timeout=60, headers={**CSRF, "Origin": ORIGIN})
    response = _request(client, "POST", "/api/auth/login", json={"password": _password()})
    assert response.status_code == 200, response.text
    yield client
    client.close()


@pytest.fixture(scope="session")
def app_id(admin):
    """A small static app to attack. Its contents include a stored XSS payload."""
    files = [("files", ("site/index.html", b"<h1>target</h1><script>alert(1)</script>", "text/html"))]
    response = _request(admin, "POST", "/api/apps", data={"name": "attack-target"}, files=files)
    assert response.status_code == 201, response.text
    yield response.json()["id"]
    _request(admin, "DELETE", f"/api/apps/{response.json()['id']}")


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


# ---------------------------------------------------------------- authentication

PROTECTED = [
    ("GET", "/api/apps"), ("GET", "/api/system"), ("GET", "/api/events"), ("GET", "/api/auth/me"),
    ("GET", "/api/apps/0123456789"), ("GET", "/api/apps/0123456789/files"),
    ("GET", "/api/apps/0123456789/file?path=index.html"), ("GET", "/api/apps/0123456789/analysis"),
    ("POST", "/api/apps/0123456789/redeploy"), ("DELETE", "/api/apps/0123456789"),
    ("POST", "/api/migrations/analyze"), ("GET", "/api/docs"), ("GET", "/api/openapi.json"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_every_endpoint_requires_a_session(anon, method, path):
    response = _request(anon, method, path, headers=CSRF)
    assert response.status_code == 401, (path, response.status_code)


def test_health_reveals_nothing(anon):
    assert _request(anon, "GET", "/api/health").json() == {"status": "ok"}


def test_wrong_password_is_rejected(anon):
    response = _request(anon, "POST", "/api/auth/login", json={"password": "not-the-password"}, headers=CSRF)
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("cookie", ["forged", "A" * 43, "' OR 1=1 --", "x" * 5000])
def test_forged_session_cookies_are_rejected(anon, cookie):
    response = _request(anon, "GET", "/api/apps", headers={"Cookie": f"owncloud_session={cookie}"})
    assert response.status_code in (400, 401, 431)


def test_session_cookie_flags():
    with httpx.Client(base_url=BASE, timeout=30, headers=CSRF) as client:
        response = _request(client, "POST", "/api/auth/login", json={"password": _password()})
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api" in cookie


def test_logout_invalidates_the_session():
    with httpx.Client(base_url=BASE, timeout=30, headers=CSRF) as client:
        _request(client, "POST", "/api/auth/login", json={"password": _password()})
        token = client.cookies.get("owncloud_session")
        assert _request(client, "GET", "/api/apps").status_code == 200
        _request(client, "POST", "/api/auth/logout")
    with httpx.Client(base_url=BASE, timeout=30) as replay:
        response = _request(replay, "GET", "/api/apps", headers={"Cookie": f"owncloud_session={token}"})
        assert response.status_code == 401


def test_login_body_size_and_type_limits(anon):
    big = _request(anon, "POST", "/api/auth/login", content=b"{" + b" " * (3 * 1024 * 1024) + b"}",
                   headers={**CSRF, "Content-Type": "application/json"})
    assert big.status_code == 413
    wrong_type = _request(anon, "POST", "/api/auth/login", json={"password": ["a", "b"]}, headers=CSRF)
    assert wrong_type.status_code == 422


# ---------------------------------------------------------------- CSRF, CORS, DNS rebinding


def test_state_change_without_csrf_header_is_refused(admin, app_id):
    response = admin.post(f"/api/apps/{app_id}/stop", headers={"X-OwnCloud-CSRF": ""})
    assert response.status_code == 403


@pytest.mark.parametrize("origin", ["http://localhost:32775", "https://evil.example", "null", "http://localhost:8088.evil.example"])
def test_cross_origin_state_change_is_refused(admin, app_id, origin):
    # A hosted app on another localhost port is the same *site*, so SameSite alone would not stop it.
    response = admin.post(f"/api/apps/{app_id}/stop", headers={**CSRF, "Origin": origin})
    assert response.status_code == 403


def test_html_form_csrf_is_refused(admin, app_id):
    # What a malicious page can send without a preflight: a form post with no custom header.
    response = admin.post(f"/api/apps/{app_id}/redeploy", headers={"X-OwnCloud-CSRF": "", "Origin": "https://evil.example",
                                                                    "Content-Type": "application/x-www-form-urlencoded"})
    assert response.status_code == 403


def test_cors_preflight_is_never_granted(anon):
    response = anon.options("/api/apps", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
                                                  "Access-Control-Request-Headers": "x-owncloud-csrf"})
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("host", ["evil.example", "rebind.attacker.test", "localhost.evil.example", "127.0.0.1.nip.io"])
def test_dns_rebinding_host_is_refused(admin, host):
    # nginx drops the connection for unknown hosts; the API also refuses them with 400 if reached.
    try:
        response = _request(admin, "GET", "/api/apps", headers={"Host": host})
    except httpx.RemoteProtocolError:
        return
    assert response.status_code == 400


def test_no_open_redirects(anon):
    for path, host in (("/api", "localhost:8088"), ("/api", "evil.example"), ("//evil.example/", "localhost:8088")):
        try:
            response = anon.get(path, headers={"Host": host})
        except httpx.RemoteProtocolError:
            continue
        assert "evil.example" not in response.headers.get("location", "")


# ---------------------------------------------------------------- injection


@pytest.mark.parametrize("name", ["x' OR '1'='1", "a; DROP TABLE apps; --", "<img src=x onerror=alert(1)>", "../../etc", "A" * 200, "${jndi:ldap://x}"])
def test_malicious_app_names_are_rejected(admin, name):
    files = [("files", ("index.html", b"hi", "text/html"))]
    response = _request(admin, "POST", "/api/apps", data={"name": name}, files=files)
    assert response.status_code == 422


@pytest.mark.parametrize("app", ["' OR 1=1--", "..", "0123456789; ls", "%2e%2e", "0123456789abcdef"])
def test_malicious_app_ids_are_rejected(admin, app):
    response = _request(admin, "GET", f"/api/apps/{app}")
    assert response.status_code in (404, 422), response.status_code


def test_sql_injection_in_query_parameters_is_rejected(admin):
    assert _request(admin, "GET", "/api/events", params={"app_id": "' OR '1'='1"}).status_code == 422
    assert _request(admin, "GET", "/api/events", params={"limit": "1; DROP TABLE events"}).status_code == 422
    assert _request(admin, "GET", "/api/apps").status_code == 200  # tables intact


@pytest.mark.parametrize("env", [
    {"A=B\nC": "x"}, {"PATH;rm -rf /": "x"}, {"OK": "nul\x00byte"}, {"OK": ["not", "a", "string"]}, {"": "x"},
])
def test_malicious_environment_variables_are_rejected(admin, env):
    files = [("files", ("index.html", b"hi", "text/html"))]
    response = _request(admin, "POST", "/api/apps", data={"name": "env-attack", "env": json.dumps(env)}, files=files)
    assert response.status_code == 422


def test_dockerfile_injection_through_a_lambda_handler_is_blocked(admin):
    template = b'Resources:\n  Fn:\n    Type: AWS::Serverless::Function\n    Properties:\n      Runtime: python3.12\n      Handler: "app.handler\\nRUN touch /pwned"\n'
    files = [("files", ("template.yaml", template, "text/yaml")), ("files", ("app.py", b"def handler(e, c):\n    return 1\n", "text/plain"))]
    response = _request(admin, "POST", "/api/apps", data={"name": "inject-lambda"}, files=files)
    assert response.status_code == 201
    app = response.json()["id"]
    try:
        for _ in range(30):
            state = _request(admin, "GET", f"/api/apps/{app}").json()
            if state["status"] not in ("queued", "scanning", "building", "starting"):
                break
            time.sleep(1)
        assert state["status"] == "failed" and "Unsupported Lambda handler" in state["detail"]
    finally:
        _request(admin, "DELETE", f"/api/apps/{app}")


# ---------------------------------------------------------------- path traversal and uploads


@pytest.mark.parametrize("path", [
    "../../../etc/passwd", "..%2f..%2fetc%2fpasswd", "/etc/passwd", "..\\..\\etc\\passwd", "index.html\x00.png",
    "C:/Windows/win.ini", "a/../../../etc/passwd", "./index.html", "",
])
def test_editor_path_traversal_is_refused(admin, app_id, path):
    """Either refused, or (for names like './index.html' or a literal '%2f') kept inside the project."""
    def inside(response):
        stored = response.json()["path"]
        return not stored.startswith("/") and ".." not in stored.split("/") and "\\" not in stored

    read = _request(admin, "GET", f"/api/apps/{app_id}/file", params={"path": path})
    assert "root:" not in read.text and "[fonts]" not in read.text
    assert read.status_code in (400, 404, 422) or (read.status_code == 200 and inside(read)), (path, read.status_code)
    write = _request(admin, "PUT", f"/api/apps/{app_id}/file", params={"path": path}, json={"content": "pwned"})
    assert write.status_code in (400, 404, 422) or (write.status_code == 200 and inside(write)), (path, write.status_code)
    if write.status_code == 200:
        _request(admin, "PUT", f"/api/apps/{app_id}/file", params={"path": "index.html"},
                 json={"content": "<h1>target</h1><script>alert(1)</script>"})
    escaped = subprocess.run(["docker", "compose", "exec", "-T", "control-plane", "sh", "-c",
                              "ls /data/apps/*/pwned /data/pwned /etc/passwd.bak 2>/dev/null; grep -l pwned /etc/passwd 2>/dev/null"],
                             cwd=ROOT, capture_output=True, text=True).stdout
    assert escaped.strip() == "", escaped


@pytest.mark.parametrize("path", ["Dockerfile.owncloud", ".owncloud/lambda_shim.py", ".git/config", "node_modules/x.js"])
def test_generated_and_hidden_files_cannot_be_edited(admin, app_id, path):
    response = _request(admin, "PUT", f"/api/apps/{app_id}/file", params={"path": path}, json={"content": "x"})
    assert response.status_code == 403


def test_stored_xss_is_returned_as_inert_json(admin, app_id):
    response = _request(admin, "GET", f"/api/apps/{app_id}/file", params={"path": "index.html"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_editor_save_size_limit(admin, app_id):
    response = _request(admin, "PUT", f"/api/apps/{app_id}/file", params={"path": "big.txt"}, json={"content": "a" * (1024 * 1024 + 10)})
    assert response.status_code in (413, 422)


@pytest.mark.parametrize("entry", ["../../evil.txt", "/etc/cron.d/evil", "..\\..\\evil.txt", "a/../../evil.txt"])
def test_zip_slip_is_refused(admin, entry):
    files = [("files", ("app.zip", zip_bytes({entry: b"pwned", "index.html": b"ok"}), "application/zip"))]
    response = _request(admin, "POST", "/api/apps", data={"name": "zip-slip"}, files=files)
    assert response.status_code == 422


def test_zip_bomb_is_refused(admin):
    bomb = zip_bytes({"bomb.txt": b"\0" * (55 * 1024 * 1024)})
    assert len(bomb) < 1024 * 1024  # small on the wire
    response = _request(admin, "POST", "/api/migrations/analyze", files=[("files", ("bomb.zip", bomb, "application/zip"))])
    assert response.status_code == 422


def test_too_many_zip_entries_is_refused(admin):
    archive = zip_bytes({f"f{i}.txt": b"x" for i in range(2001)})
    response = _request(admin, "POST", "/api/migrations/analyze", files=[("files", ("many.zip", archive, "application/zip"))])
    assert response.status_code == 422


def test_oversized_upload_is_refused(admin):
    payload = os.urandom(61 * 1024 * 1024)
    response = _request(admin, "POST", "/api/migrations/analyze", files=[("files", ("big.bin", payload, "application/octet-stream"))])
    assert response.status_code == 413


def test_conflicting_paths_do_not_crash_the_server(admin):
    files = [("files", ("a", b"file", "text/plain")), ("files", ("a/b.txt", b"nested", "text/plain"))]
    response = _request(admin, "POST", "/api/migrations/analyze", files=files)
    assert response.status_code == 422


# ---------------------------------------------------------------- denial of service through parsers


def test_yaml_billion_laughs_is_harmless(admin):
    levels = ['a: &a ["lol","lol","lol","lol","lol","lol","lol","lol","lol"]']
    for i in range(1, 10):
        levels.append(f"{chr(97 + i)}: &{chr(97 + i)} [" + ",".join([f"*{chr(96 + i)}"] * 9) + "]")
    template = ("\n".join(levels) + "\nResources:\n  Fn:\n    Type: AWS::Serverless::Function\n    Properties:\n"
                "      Handler: app.handler\n      Runtime: python3.12\n      Environment:\n        Variables:\n          BOMB: *j\n").encode()
    files = [("files", ("template.yaml", template, "text/yaml")), ("files", ("app.py", b"def handler(e, c): pass\n", "text/plain"))]
    start = time.time()
    response = _request(admin, "POST", "/api/migrations/analyze", files=files)
    assert response.status_code == 200 and time.time() - start < 10
    assert "BOMB" not in response.json()["env"]


def test_pathological_source_does_not_hang_the_analyzer(admin, app_id):
    content = "x = '" + "a" * 500_000 + "'\n" + ("(" * 5000) + "\n" + "\n".join(f"v{i} = {i}" for i in range(20_000))
    start = time.time()
    response = _request(admin, "POST", f"/api/apps/{app_id}/analysis/file", json={"path": "evil.py", "content": content[:1_000_000]})
    assert response.status_code == 200 and time.time() - start < 15


# ---------------------------------------------------------------- secrets and information disclosure


def test_environment_values_are_never_returned(admin):
    files = [("files", ("index.html", b"hi", "text/html"))]
    response = _request(admin, "POST", "/api/apps", data={"name": "secret-env", "env": json.dumps({"DB_PASSWORD": "hunter2-very-secret"})}, files=files)
    app = response.json()["id"]
    try:
        assert "hunter2" not in _request(admin, "GET", "/api/apps").text
        assert "hunter2" not in _request(admin, "GET", f"/api/apps/{app}").text
        assert _request(admin, "GET", f"/api/apps/{app}").json()["env_keys"] == ["DB_PASSWORD"]
    finally:
        _request(admin, "DELETE", f"/api/apps/{app}")


def test_security_headers_on_the_website(anon):
    response = _request(anon, "GET", "/")
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe-eval" not in csp
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "nginx/" not in response.headers.get("server", "")


def test_dotfiles_are_not_served(anon):
    for path in ("/.env", "/.git/config", "/.htaccess"):
        assert _request(anon, "GET", path).status_code == 404


def test_internal_services_are_not_exposed_on_the_host():
    for port in (8000, 8001):
        with pytest.raises(httpx.ConnectError):
            httpx.get(f"http://127.0.0.1:{port}/", timeout=3)


# ---------------------------------------------------------------- isolation of hosted apps

PROBE = r"""
import socket, sys
targets = sys.argv[1:]
for target in targets:
    host, port = target.rsplit(":", 1)
    try:
        socket.create_connection((host, int(port)), timeout=3).close()
        print("REACHABLE", target)
    except OSError:
        print("blocked", target)
"""


def test_hosted_apps_cannot_reach_the_control_plane_or_each_other(admin, app_id):
    for _ in range(60):
        if _request(admin, "GET", f"/api/apps/{app_id}").json()["status"] == "running":
            break
        time.sleep(2)
    target_ip = subprocess.run(
        ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", f"owncloud-app-{app_id}"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert target_ip, "the target app must be running for this test to mean anything"
    url = _request(admin, "GET", f"/api/apps/{app_id}").json()["url"]
    assert httpx.get(url, timeout=5).status_code == 200  # reachable from the host, as intended
    gateway = subprocess.run(
        ["docker", "network", "inspect", "-f", "{{(index .IPAM.Config 0).Gateway}}", "owncloud-apps"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "owncloud-apps", "python:3.12-slim", "python", "-c", PROBE,
         "control-plane:8000", "quantumtrace:8000", "owncloud-control-plane-1:8000", f"{target_ip}:80",
         f"{gateway}:8088", f"{gateway}:8000"],
        capture_output=True, text=True, timeout=120,
    )
    assert "REACHABLE" not in result.stdout, result.stdout


# ---------------------------------------------------------------- brute force (keep last)


def test_zz_login_brute_force_is_throttled():
    statuses = []
    with httpx.Client(base_url=BASE, timeout=30, headers=CSRF) as client:
        for i in range(12):
            statuses.append(client.post("/api/auth/login", json={"password": f"guess-{i}"}).status_code)
    assert 429 in statuses, statuses
    assert statuses.count(401) <= 6, statuses
