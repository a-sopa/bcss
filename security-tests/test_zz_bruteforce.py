"""Runs last (file name): it locks this machine out of *new* sign-ins for 5 minutes."""

import httpx

from conftest import BASE, CSRF


def test_login_brute_force_is_throttled():
    statuses = []
    with httpx.Client(base_url=BASE, timeout=30, headers=CSRF) as client:
        for i in range(12):
            statuses.append(client.post("/api/auth/login", json={"username": "admin", "password": f"guess-{i}"}).status_code)
    assert 429 in statuses, statuses
    assert statuses.count(401) <= 6, statuses
