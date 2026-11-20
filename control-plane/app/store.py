"""SQLite persistence for apps and the shared event feed."""

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS apps (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    runtime TEXT,
    status TEXT NOT NULL,
    detail TEXT,
    enforce_gate INTEGER NOT NULL DEFAULT 0,
    image TEXT,
    host_port INTEGER,
    scan_summary TEXT,
    env TEXT,
    migration TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    app_id TEXT,
    module TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT
);
"""

APP_FIELDS = {"name", "runtime", "status", "detail", "enforce_gate", "image", "host_port", "scan_summary", "env", "migration"}
JSON_FIELDS = ("scan_summary", "env", "migration")


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            # Databases created before environment variables and migration reports existed.
            columns = {row[1] for row in self._db.execute("PRAGMA table_info(apps)")}
            for column, statement in (
                ("env", "ALTER TABLE apps ADD COLUMN env TEXT"),
                ("migration", "ALTER TABLE apps ADD COLUMN migration TEXT"),
            ):
                if column not in columns:
                    self._db.execute(statement)
            self._db.commit()

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            rows = self._db.execute(sql, params).fetchall()
            self._db.commit()
            return rows

    @staticmethod
    def _app(row: sqlite3.Row) -> dict[str, Any]:
        app = dict(row)
        app["enforce_gate"] = bool(app["enforce_gate"])
        for key in JSON_FIELDS:
            app[key] = json.loads(app[key]) if app[key] else None
        return app

    def create_app(self, name: str, enforce_gate: bool, env: dict[str, str] | None = None) -> dict[str, Any]:
        """env=None means "use the environment declared by the app's AWS configuration"."""
        app_id = uuid.uuid4().hex[:10]
        now = time.time()
        self._query(
            "INSERT INTO apps (id, name, status, enforce_gate, env, created_at, updated_at) VALUES (?, ?, 'queued', ?, ?, ?, ?)",
            (app_id, name, int(enforce_gate), json.dumps(env) if env is not None else None, now, now),
        )
        return self.get_app(app_id)

    def update_app(self, app_id: str, **fields: Any) -> None:
        unknown = set(fields) - APP_FIELDS
        if unknown:
            raise ValueError(f"Unknown app fields: {unknown}")
        for key in JSON_FIELDS:
            if fields.get(key) is not None:
                fields[key] = json.dumps(fields[key])
        assignments = ", ".join(f"{key} = ?" for key in fields)
        self._query(
            f"UPDATE apps SET {assignments}, updated_at = ? WHERE id = ?",
            (*fields.values(), time.time(), app_id),
        )

    def get_app(self, app_id: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM apps WHERE id = ?", (app_id,))
        return self._app(rows[0]) if rows else None

    def list_apps(self) -> list[dict[str, Any]]:
        return [self._app(row) for row in self._query("SELECT * FROM apps ORDER BY created_at DESC")]

    def delete_app(self, app_id: str) -> None:
        self._query("DELETE FROM apps WHERE id = ?", (app_id,))

    def add_event(self, app_id: str | None, module: str, severity: str, title: str, detail: str | None = None) -> None:
        self._query(
            "INSERT INTO events (ts, app_id, module, severity, title, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), app_id, module, severity, title, detail),
        )

    def list_events(self, app_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if app_id:
            rows = self._query("SELECT * FROM events WHERE app_id = ? ORDER BY id DESC LIMIT ?", (app_id, limit))
        else:
            rows = self._query("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in rows]
