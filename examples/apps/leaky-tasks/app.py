"""Leaky Tasks: a tiny task board that is deliberately insecure.

DEMO ONLY. Every route contains a classic vulnerability so the OwnCloud editor and QuantumTrace have
something to find at every severity. Never expose this app to the internet.
Its safe twin is examples/apps/safe-tasks.
"""

import hashlib
import os
import pickle
import random
import sqlite3
import subprocess

import requests
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from flask import Flask, request

app = Flask(__name__)

DEBUG = True                                    # medium: debug setting on
SECRET_KEY = "tasks-super-secret-2024"          # high: hard-coded secret
AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"      # critical: leaked AWS key (AWS's documentation example)
BACKUP_URL = "http://backup.leaky-tasks.eu/upload"  # low: clear-text URL

SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=1024)  # QuantumTrace: RSA-1024
NOTES_KEY = os.urandom(16)

db = sqlite3.connect("tasks.db", check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS tasks (owner TEXT, title TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS users (name TEXT, password TEXT, token TEXT)")


@app.get("/")
def home():
    # high: reflected XSS, the name is written into HTML unescaped
    return f"<h1>Tasks for {request.args.get('user', 'guest')}</h1><a href='/tasks?owner=guest'>Open</a>"


@app.get("/tasks")
def list_tasks():
    owner = request.args.get("owner", "")
    # critical: SQL injection, try ?owner=' OR '1'='1
    rows = db.execute(f"SELECT title FROM tasks WHERE owner = '{owner}'").fetchall()
    return {"tasks": [r[0] for r in rows]}


@app.post("/register")
def register():
    name, password = request.form["name"], request.form["password"]
    password_hash = hashlib.md5(password.encode()).hexdigest()  # high: MD5 for passwords
    token = str(random.randint(100000, 999999))                 # medium: predictable session token
    db.execute("INSERT INTO users VALUES (?, ?, ?)", (name, password_hash, token))
    return {"token": token}


@app.get("/ping")
def ping():
    host = request.args.get("host", "localhost")
    # critical: command injection through the shell, try ?host=x;cat /etc/passwd
    return subprocess.run(f"ping -c 1 {host}", shell=True, capture_output=True, text=True).stdout


@app.get("/calc")
def calc():
    return str(eval(request.args.get("expr", "1+1")))  # critical: arbitrary code execution


@app.post("/import")
def import_tasks():
    tasks = pickle.loads(request.data)  # critical: unsafe deserialization of the request body
    return {"imported": len(tasks)}


@app.post("/settings")
def settings():
    return {"settings": yaml.load(request.data)}  # high: unsafe YAML loading


@app.get("/fetch")
def fetch():
    # high: SSRF + TLS checks disabled; low: no timeout
    return requests.get(request.args["url"], verify=False).text


@app.get("/files")
def download():
    return open(request.args["name"]).read()  # high: path traversal, try ?name=../../etc/passwd


@app.post("/notes")
def seal_note():
    encryptor = Cipher(algorithms.AES(NOTES_KEY), modes.ECB()).encryptor()  # medium: ECB mode
    padded = request.data.ljust(16 * (len(request.data) // 16 + 1), b" ")
    return (encryptor.update(padded) + encryptor.finalize()).hex()


@app.get("/public-key")
def public_key():
    try:
        return SIGNING_KEY.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()
    except:  # low: errors silently ignored
        pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=True)  # high: debugger on
