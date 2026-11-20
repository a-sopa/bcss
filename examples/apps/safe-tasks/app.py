"""Safe Tasks: the same tiny task board as examples/apps/leaky-tasks, written securely.

Ready to deploy on OwnCloud as is: it listens on $PORT, keeps secrets in environment variables,
and ships with tests that the smart CI step runs before each version goes live.

Optional environment variables:
    SECRET_KEY      signs nothing yet, but is read from the environment, never from the code
    DATABASE_PATH   where the SQLite file lives (default: tasks.db)
"""

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import Flask, abort, g, jsonify, request, send_from_directory

MAX_TITLE = 200
MAX_NAME = 32
MAX_NOTE = 4096


def hash_password(password: str, salt: bytes | None = None) -> str:
    """scrypt with a random salt: slow to brute-force, unlike MD5."""
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return base64.b64encode(salt + digest).decode()


def verify_password(password: str, stored: str) -> bool:
    raw = base64.b64decode(stored)
    return hmac.compare_digest(hash_password(password, raw[:16]), stored)


def create_app(database: str | None = None) -> Flask:
    app = Flask(__name__, static_folder="static")
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    app.config["DATABASE"] = database or os.environ.get("DATABASE_PATH", "tasks.db")
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
    notes_key = AESGCM.generate_key(bit_length=256)  # AES-256-GCM: authenticated, quantum-resilient

    def get_db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.execute("CREATE TABLE IF NOT EXISTS tasks (owner TEXT NOT NULL, title TEXT NOT NULL)")
            g.db.execute("CREATE TABLE IF NOT EXISTS users (name TEXT PRIMARY KEY, password TEXT NOT NULL)")
        return g.db

    @app.teardown_appcontext
    def close_db(_error: BaseException | None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    def text_field(name: str, limit: int) -> str:
        value = (request.get_json(silent=True) or {}).get(name)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            abort(400, f"'{name}' must be 1–{limit} characters")
        return value.strip()

    @app.get("/")
    def home():
        # Static page; it renders data with textContent, so nothing user-supplied becomes HTML.
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/tasks")
    def list_tasks():
        owner = request.args.get("owner", "")[:MAX_NAME]
        rows = get_db().execute("SELECT title FROM tasks WHERE owner = ?", (owner,)).fetchall()
        return {"tasks": [row[0] for row in rows]}

    @app.post("/tasks")
    def add_task():
        owner, title = text_field("owner", MAX_NAME), text_field("title", MAX_TITLE)
        db = get_db()
        db.execute("INSERT INTO tasks (owner, title) VALUES (?, ?)", (owner, title))
        db.commit()
        return {"owner": owner, "title": title}, 201

    @app.post("/register")
    def register():
        name, password = text_field("name", MAX_NAME), text_field("password", 256)
        if len(password) < 12:
            abort(400, "passwords need at least 12 characters")
        db = get_db()
        try:
            db.execute("INSERT INTO users (name, password) VALUES (?, ?)", (name, hash_password(password)))
            db.commit()
        except sqlite3.IntegrityError:
            abort(409, "that name is taken")
        return {"name": name}, 201

    @app.post("/login")
    def login():
        name, password = text_field("name", MAX_NAME), text_field("password", 256)
        row = get_db().execute("SELECT password FROM users WHERE name = ?", (name,)).fetchone()
        if row is None or not verify_password(password, row[0]):
            abort(401, "wrong name or password")
        return {"token": secrets.token_urlsafe(32)}

    @app.post("/notes")
    def seal_note():
        note = text_field("note", MAX_NOTE).encode()
        nonce = os.urandom(12)
        sealed = AESGCM(notes_key).encrypt(nonce, note, None)
        return {"sealed": base64.b64encode(nonce + sealed).decode()}

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(409)
    def client_error(error):
        return jsonify(error=error.description), error.code

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
