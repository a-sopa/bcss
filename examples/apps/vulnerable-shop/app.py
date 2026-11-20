"""Intentionally vulnerable demo app: open it in the OwnCloud code editor to see every severity colour."""

import hashlib
import os
import random
import sqlite3
import subprocess

import requests
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import Flask, request, send_file

app = Flask(__name__, static_folder="static")
db = sqlite3.connect(":memory:", check_same_thread=False)
db.execute("CREATE TABLE products (name TEXT, price REAL)")
db.execute("INSERT INTO products VALUES ('Pastel de nata', 1.2), ('Bica', 0.8)")

AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"  # AWS documentation example key
ADMIN_PASSWORD = "lisboa-2026"
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=1024)


@app.route("/")
def home():
    return app.send_static_file("index.html")


@app.route("/search")
def search():
    term = request.args.get("q", "")
    rows = db.execute(f"SELECT name, price FROM products WHERE name LIKE '%{term}%'").fetchall()
    return {"results": rows}


@app.route("/hello")
def hello():
    return f"<h1>Olá {request.args.get('name', 'visitante')}</h1>"


@app.route("/ping")
def ping():
    return subprocess.run("ping -c 1 " + request.args["host"], shell=True, capture_output=True, text=True).stdout


@app.route("/preview")
def preview():
    return requests.get(request.args["url"], verify=False).text


@app.route("/download")
def download():
    return send_file(os.path.join("files", request.args["name"]))


@app.route("/config", methods=["POST"])
def config():
    return {"config": yaml.load(request.data)}


@app.route("/token")
def token():
    session_token = random.choice("abcdef0123456789")
    fingerprint = hashlib.md5(session_token.encode()).hexdigest()
    return {"token": session_token, "fingerprint": fingerprint}


app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=True)
