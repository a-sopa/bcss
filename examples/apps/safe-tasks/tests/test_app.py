import pytest

from app import create_app, hash_password, verify_password


@pytest.fixture()
def client(tmp_path):
    return create_app(str(tmp_path / "tasks.db")).test_client()


def test_health(client):
    assert client.get("/health").get_json() == {"status": "ok"}


def test_tasks_round_trip(client):
    assert client.post("/tasks", json={"owner": "ana", "title": "Ship v1"}).status_code == 201
    assert client.get("/tasks?owner=ana").get_json() == {"tasks": ["Ship v1"]}


def test_sql_injection_returns_nothing(client):
    client.post("/tasks", json={"owner": "ana", "title": "private"})
    assert client.get("/tasks", query_string={"owner": "' OR '1'='1"}).get_json() == {"tasks": []}


def test_rejects_bad_input(client):
    assert client.post("/tasks", json={"owner": "", "title": "x"}).status_code == 400
    assert client.post("/tasks", json={"owner": "ana", "title": "x" * 201}).status_code == 400


def test_register_and_login(client):
    assert client.post("/register", json={"name": "ana", "password": "short"}).status_code == 400
    assert client.post("/register", json={"name": "ana", "password": "correct horse battery"}).status_code == 201
    assert client.post("/register", json={"name": "ana", "password": "correct horse battery"}).status_code == 409
    assert client.post("/login", json={"name": "ana", "password": "wrong password!!"}).status_code == 401
    token = client.post("/login", json={"name": "ana", "password": "correct horse battery"}).get_json()["token"]
    assert len(token) >= 40


def test_password_hashing_is_salted():
    first, second = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert first != second
    assert verify_password("correct horse battery", first)
    assert not verify_password("wrong", first)


def test_notes_are_sealed(client):
    sealed = client.post("/notes", json={"note": "meet at noon"}).get_json()["sealed"]
    assert "meet at noon" not in sealed


def test_security_headers(client):
    headers = client.get("/health").headers
    assert headers["Content-Security-Policy"] == "default-src 'self'"
    assert headers["X-Content-Type-Options"] == "nosniff"
