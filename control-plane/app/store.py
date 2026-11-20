"""SQLite persistence: users, access tokens, apps (each owned by a user) and the shared event feed."""

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
    disabled INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    scope TEXT NOT NULL CHECK (scope IN ('read', 'write')),
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    last_used_at REAL
);
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
    owner_id TEXT,
    version INTEGER,
    canary_version INTEGER,
    database TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at REAL NOT NULL,
    finished_at REAL,
    status TEXT NOT NULL,
    detail TEXT,
    pipeline TEXT,
    canary TEXT
);
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    report TEXT
);
CREATE TABLE IF NOT EXISTS loadtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    finished_at REAL,
    status TEXT NOT NULL,
    plan TEXT,
    result TEXT
);
CREATE TABLE IF NOT EXISTS db_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    kind TEXT NOT NULL,
    statement TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    app_id TEXT,
    owner_id TEXT,
    module TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT
);
"""

# Columns added after the first release; each statement is a constant.
MIGRATIONS = (
    ("apps", "env", "ALTER TABLE apps ADD COLUMN env TEXT"),
    ("apps", "migration", "ALTER TABLE apps ADD COLUMN migration TEXT"),
    ("apps", "owner_id", "ALTER TABLE apps ADD COLUMN owner_id TEXT"),
    ("events", "owner_id", "ALTER TABLE events ADD COLUMN owner_id TEXT"),
    ("apps", "version", "ALTER TABLE apps ADD COLUMN version INTEGER"),
    ("apps", "canary_version", "ALTER TABLE apps ADD COLUMN canary_version INTEGER"),
    ("apps", "database", "ALTER TABLE apps ADD COLUMN database TEXT"),
)

# Per-app history tables and their JSON columns (names are constants, never user input).
HISTORY = {
    "deployments": ("detail", "pipeline", "canary"),
    "incidents": ("report",),
    "loadtests": ("plan", "result"),
    "db_actions": ("detail",),
}

APP_FIELDS = {"name", "runtime", "status", "detail", "enforce_gate", "image", "host_port", "scan_summary", "env", "migration",
              "version", "canary_version", "database"}
JSON_FIELDS = ("scan_summary", "env", "migration", "database")
USER_FIELDS = {"role", "disabled", "salt", "password_hash"}


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.Lock()
        with self._lock:
            # Older databases: add the new columns before the indexes that use them.
            for table, column, statement in MIGRATIONS:
                exists = self._db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                if exists and column not in {row[1] for row in self._db.execute(f"PRAGMA table_info({table})")}:
                    self._db.execute(statement)
            self._db.executescript(SCHEMA)
            self._db.executescript(
                "CREATE INDEX IF NOT EXISTS apps_owner ON apps(owner_id);"
                "CREATE INDEX IF NOT EXISTS events_owner ON events(owner_id);"
            )
            self._db.commit()

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            rows = self._db.execute(sql, params).fetchall()
            self._db.commit()
            return rows

    # ------------------------------------------------------------ users

    @staticmethod
    def _user(row: sqlite3.Row) -> dict[str, Any]:
        user = dict(row)
        user["disabled"] = bool(user["disabled"])
        return user

    def create_user(self, username: str, salt: str, password_hash: str, role: str) -> dict[str, Any]:
        user_id = uuid.uuid4().hex[:10]
        self._query(
            "INSERT INTO users (id, username, salt, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, salt, password_hash, role, time.time()),
        )
        return self.get_user(user_id)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM users WHERE id = ?", (user_id,))
        return self._user(rows[0]) if rows else None

    def user_by_name(self, username: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM users WHERE username = ?", (username,))
        return self._user(rows[0]) if rows else None

    def list_users(self) -> list[dict[str, Any]]:
        rows = self._query(
            "SELECT u.*, (SELECT COUNT(*) FROM apps a WHERE a.owner_id = u.id) AS app_count FROM users u ORDER BY u.created_at"
        )
        return [self._user(row) for row in rows]

    def update_user(self, user_id: str, **fields: Any) -> None:
        unknown = set(fields) - USER_FIELDS
        if unknown:
            raise ValueError(f"Unknown user fields: {unknown}")
        assignments = ", ".join(f"{key} = ?" for key in fields)
        self._query(f"UPDATE users SET {assignments} WHERE id = ?", (*fields.values(), user_id))

    def delete_user(self, user_id: str) -> None:
        self._query("DELETE FROM tokens WHERE user_id = ?", (user_id,))
        self._query("DELETE FROM users WHERE id = ?", (user_id,))

    def count_admins(self) -> int:
        return self._query("SELECT COUNT(*) FROM users WHERE role = 'admin' AND disabled = 0")[0][0]

    # ------------------------------------------------------------ access tokens

    def create_token(self, user_id: str, name: str, token: str, scope: str, expires_at: float) -> dict[str, Any]:
        token_id = uuid.uuid4().hex[:10]
        self._query(
            "INSERT INTO tokens (id, user_id, name, token_hash, scope, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token_id, user_id, name, token_digest(token), scope, time.time(), expires_at),
        )
        return self.list_tokens(user_id, token_id)[0]

    def list_tokens(self, user_id: str, token_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT id, name, scope, created_at, expires_at, last_used_at FROM tokens WHERE user_id = ?"
        params: tuple = (user_id,)
        if token_id:
            sql += " AND id = ?"
            params += (token_id,)
        return [dict(row) for row in self._query(sql + " ORDER BY created_at DESC", params)]

    def resolve_token(self, token: str) -> dict[str, Any] | None:
        """The token's owner and scope, if the token exists and has not expired."""
        rows = self._query("SELECT * FROM tokens WHERE token_hash = ?", (token_digest(token),))
        if not rows or rows[0]["expires_at"] < time.time():
            return None
        record = dict(rows[0])
        if not record["last_used_at"] or record["last_used_at"] < time.time() - 60:
            self._query("UPDATE tokens SET last_used_at = ? WHERE id = ?", (time.time(), record["id"]))
        return record

    def delete_token(self, user_id: str, token_id: str) -> bool:
        before = len(self.list_tokens(user_id, token_id))
        self._query("DELETE FROM tokens WHERE id = ? AND user_id = ?", (token_id, user_id))
        return before == 1

    def delete_user_tokens(self, user_id: str) -> None:
        self._query("DELETE FROM tokens WHERE user_id = ?", (user_id,))

    # ------------------------------------------------------------ apps

    @staticmethod
    def _app(row: sqlite3.Row) -> dict[str, Any]:
        app = dict(row)
        app["enforce_gate"] = bool(app["enforce_gate"])
        for key in JSON_FIELDS:
            app[key] = json.loads(app[key]) if app[key] else None
        return app

    def create_app(self, name: str, enforce_gate: bool, owner_id: str, env: dict[str, str] | None = None) -> dict[str, Any]:
        """env=None means "use the environment declared by the app's AWS configuration"."""
        app_id = uuid.uuid4().hex[:10]
        now = time.time()
        self._query(
            "INSERT INTO apps (id, name, status, enforce_gate, env, owner_id, created_at, updated_at) "
            "VALUES (?, ?, 'queued', ?, ?, ?, ?, ?)",
            (app_id, name, int(enforce_gate), json.dumps(env) if env is not None else None, owner_id, now, now),
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
        rows = self._query(
            "SELECT a.*, u.username AS owner FROM apps a LEFT JOIN users u ON u.id = a.owner_id WHERE a.id = ?", (app_id,)
        )
        return self._app(rows[0]) if rows else None

    def list_apps(self, owner_id: str | None = None) -> list[dict[str, Any]]:
        """All apps, or only those of one owner."""
        sql = "SELECT a.*, u.username AS owner FROM apps a LEFT JOIN users u ON u.id = a.owner_id"
        if owner_id is None:
            rows = self._query(sql + " ORDER BY a.created_at DESC")
        else:
            rows = self._query(sql + " WHERE a.owner_id = ? ORDER BY a.created_at DESC", (owner_id,))
        return [self._app(row) for row in rows]

    def count_apps(self, owner_id: str) -> int:
        return self._query("SELECT COUNT(*) FROM apps WHERE owner_id = ?", (owner_id,))[0][0]

    def adopt_orphans(self, owner_id: str) -> None:
        """Apps and events from before user accounts existed belong to the first admin."""
        self._query("UPDATE apps SET owner_id = ? WHERE owner_id IS NULL", (owner_id,))
        self._query(
            "UPDATE events SET owner_id = COALESCE((SELECT owner_id FROM apps WHERE apps.id = events.app_id), ?) WHERE owner_id IS NULL",
            (owner_id,),
        )

    def delete_app(self, app_id: str) -> None:
        for table in HISTORY:
            self._query(f"DELETE FROM {table} WHERE app_id = ?", (app_id,))
        self._query("DELETE FROM apps WHERE id = ?", (app_id,))

    # ------------------------------------------------------------ history (deployments, incidents, load tests, db)

    @staticmethod
    def _decode(table: str, row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        for key in HISTORY[table]:
            record[key] = json.loads(record[key]) if record.get(key) else None
        return record

    def insert(self, table: str, **fields: Any) -> int:
        if table not in HISTORY:
            raise ValueError(f"Unknown table {table}")
        fields.setdefault("created_at", time.time())
        values = [json.dumps(v) if k in HISTORY[table] and v is not None else v for k, v in fields.items()]
        with self._lock:
            cursor = self._db.execute(
                f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})", values,
            )
            self._db.commit()
            return int(cursor.lastrowid)

    def update_row(self, table: str, row_id: int, **fields: Any) -> None:
        if table not in HISTORY:
            raise ValueError(f"Unknown table {table}")
        allowed = {row[1] for row in self._query(f"PRAGMA table_info({table})")}
        if set(fields) - allowed:
            raise ValueError(f"Unknown columns {set(fields) - allowed}")
        values = [json.dumps(v) if k in HISTORY[table] and v is not None else v for k, v in fields.items()]
        self._query(f"UPDATE {table} SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*values, row_id))

    def rows(self, table: str, app_id: str, limit: int = 50) -> list[dict[str, Any]]:
        if table not in HISTORY:
            raise ValueError(f"Unknown table {table}")
        rows = self._query(f"SELECT * FROM {table} WHERE app_id = ? ORDER BY id DESC LIMIT ?", (app_id, limit))
        return [self._decode(table, row) for row in rows]

    def row(self, table: str, row_id: int) -> dict[str, Any] | None:
        if table not in HISTORY:
            raise ValueError(f"Unknown table {table}")
        rows = self._query(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
        return self._decode(table, rows[0]) if rows else None

    # ------------------------------------------------------------ events

    def add_event(self, app_id: str | None, module: str, severity: str, title: str, detail: str | None = None,
                  owner_id: str | None = None) -> None:
        if owner_id is None and app_id:
            rows = self._query("SELECT owner_id FROM apps WHERE id = ?", (app_id,))
            owner_id = rows[0]["owner_id"] if rows else None
        self._query(
            "INSERT INTO events (ts, app_id, owner_id, module, severity, title, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (time.time(), app_id, owner_id, module, severity, title, detail),
        )

    def list_events(self, owner_id: str | None, app_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Events visible to a user (owner_id) or to an admin (owner_id=None)."""
        clauses, params = [], []
        if owner_id is not None:
            clauses.append("owner_id = ?")
            params.append(owner_id)
        if app_id:
            clauses.append("app_id = ?")
            params.append(app_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._query(f"SELECT * FROM events{where} ORDER BY id DESC LIMIT ?", (*params, limit))
        return [dict(row) for row in rows]
