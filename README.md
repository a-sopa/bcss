# OwnCloud — European cloud infrastructure with AI monitoring

A small cloud that hosts and runs your programs as Docker containers. Every deployment is analysed by
**QuantumTrace** for quantum-vulnerable cryptography before it runs.

```bash
echo "OWNCLOUD_ADMIN_PASSWORD=choose-a-long-password" > .env   # optional, 12+ characters
docker compose up -d --build
```

Without `.env`, a password is generated on first start:

```bash
docker compose exec control-plane cat /data/admin-password.txt
```

| URL | What |
| --- | --- |
| http://localhost:8088 | Website |
| http://localhost:8088/#/console | Console (sign in): deploy and manage apps |
| http://localhost:8088/#/console/apps/&lt;id&gt;/editor | Code editor with security highlighting |

Only port 8088 is published. The control plane and QuantumTrace are internal to Compose.
Hosted apps are published on random ports on `127.0.0.1`; the console links to each one.

## Code editor

Every app has a **Code** button in the console. It opens a Monaco editor (the editor behind VS Code and github.dev):
a file tree, syntax highlighting, and every line coloured by how vulnerable it is.

| Colour | Severity | Examples |
| --- | --- | --- |
| Yellow | Low: a weakness worth tidying | request without timeout, `http://` URL, `Math.random()`, silent `except: pass` |
| Orange | Medium: weak | MD5/SHA-1, predictable token, ECB mode, secret in a config file; Grover-weakened crypto |
| Red | High: vulnerable | XSS, SSRF, path traversal, `yaml.load`, TLS checks off, debug mode, hard-coded password; RSA/ECC (QuantumTrace) |
| Black | Critical: severely vulnerable | SQL / command injection, `eval`, unsafe deserialization, leaked AWS or private keys; crypto that is also classically weak (e.g. RSA-1024) |

Each finding has an explanation and a suggestion; many have a one-click **Apply fix** (also `Ctrl+.` in the editor),
e.g. `yaml.load` → `yaml.safe_load`, `verify=False` → `True`, a hard-coded secret → `os.environ[...]`.
The file is re-analysed as you type. **Save** (`Ctrl+S`) writes the file; **Save & redeploy** rebuilds the app.

The analyzer (`control-plane/app/code_review.py`) uses Python's AST for `.py` files and line rules for
JavaScript/TypeScript, Go, Java and configuration files; QuantumTrace adds the cryptography findings.
Try it with `examples/apps/vulnerable-shop`, which contains issues at every severity.

## How a deployment works

```
upload (folder / files / .zip)
  → migration analysis    AWS origin, environment variables, AWS services, hard-coded keys
  → detect runtime        Dockerfile · Lambda · Procfile · package.json · application.py · main.py/app.py · index.html
  → QuantumTrace scan     .py / .java / .go files → findings, tiers, exposure score
  → quantum gate          if enabled: block on any critical (quantum-vulnerable) finding
  → docker build          generated Dockerfile unless the app has its own
  → docker run            256 MB, 0.5 CPU, no-new-privileges, restart on failure
```

Apps must listen on the port in `$PORT` (8080 for Python/Node). Every step is written to a shared
event feed (`GET /api/events`) with `module`, `severity`, `title` and `detail`, so the other AI modules
(anomaly detection, event-aware scaling, …) can read from and write to the same timeline.

## Migrating from AWS

Console → **Migrate from AWS** (or `http://localhost:8088/#/console/migrate`). Upload the exported project and
OwnCloud shows a migration report before anything runs, then deploys it with its configuration imported.

| From | How it runs here |
| --- | --- |
| **Lambda** — SAM / CloudFormation `template.yaml`, Serverless Framework `serverless.yml`, or a plain `lambda_handler` / `exports.handler` | Unchanged, behind an HTTP shim that emulates API Gateway proxy events (`control-plane/app/shims/`). Python and Node.js; the runtime version comes from the template; the AWS SDK that Lambda bundles is installed if the code needs it |
| **Elastic Beanstalk** — `Procfile`, `application.py`, `.ebextensions` | Procfile `web:` command (its port is honoured), or gunicorn for EB's default `application:application` |
| **Containers** (ECS, App Runner, …) | Any `Dockerfile` |

The report (`POST /api/migrations/analyze`) contains:

- **Environment variables** from `template.yaml`, `serverless.yml`, `.ebextensions/*.config` and `.env` — editable before deploying.
- **AWS services** found in Python, JS/TS, Go and Java SDK calls, each mapped to an open-source replacement with the effort needed:
  S3 → MinIO, DynamoDB → ScyllaDB Alternator, SQS → ElasticMQ only need `AWS_ENDPOINT_URL`; others (SNS, Secrets Manager, KMS, SES, Cognito, …) need code changes.
- **Hard-coded AWS access keys** (`AKIA…`/`ASIA…`), with file and line.
- **Notes**: e.g. non-HTTP Lambda triggers (schedules, S3 or SQS events) are not emulated; extra functions in a template deploy as separate apps.

Samples in `examples/aws/`: `lambda-orders-sam` (SAM, Python, DynamoDB + S3), `beanstalk-shop` (Flask, SQS, a hard-coded example key),
`lambda-hello-node` (Node.js ESM handler).

## Security

The console can run arbitrary code on this machine, so it is locked down:

- **Authentication:** one admin account (scrypt-hashed password), server-side sessions in an `HttpOnly`, `SameSite=Strict`
  cookie, sign-out revokes the session. Every API route except sign-in and a minimal health check needs a session.
- **Brute force:** sign-in is rate-limited in nginx (10/min) and in the API (5 failures per client, 30 overall, per 5 minutes).
- **CSRF:** state-changing requests need the `X-OwnCloud-CSRF` header (it forces a CORS preflight, which is never granted)
  and an allow-listed `Origin`. This also stops hosted apps on other `localhost` ports, which browsers treat as the same site.
- **DNS rebinding:** unknown `Host` names are dropped by nginx and refused by the API.
- **Injection:** parameterised SQL only; strict validation of app names, IDs, environment variables and Lambda handler
  names (no Dockerfile injection); no shell is ever invoked by the control plane.
- **Path traversal / uploads:** editor and upload paths are normalised and confined to the app folder (no `..`, absolute
  paths, symlinks or generated files); zip slip, zip bombs, too many files and oversized bodies are rejected.
- **Parsers:** YAML/JSON configuration is size-limited and only scalar values are used (no "billion laughs").
- **XSS / clickjacking:** React escaping, a strict Content-Security-Policy (`script-src 'self'`, `frame-ancestors 'none'`),
  `X-Frame-Options`, `nosniff`, `no-referrer`; API responses are JSON with `default-src 'none'`.
- **SSRF:** the control plane fetches nothing user-supplied; its only outbound call is to QuantumTrace.
- **Isolation:** hosted apps run on a network where containers cannot reach each other or the control plane, with memory,
  CPU and process limits, `no-new-privileges` and fewer Linux capabilities. Platform containers drop all capabilities
  (nginx keeps the four it needs) and run read-only where possible. Environment variable values are never returned by the API.

### Attack test suite

```bash
control-plane/.venv/bin/python -m pytest security-tests -q
```

83 attacks against the running stack: unauthenticated access, forged cookies, session replay after sign-out, CSRF
from other origins and from hosted apps, DNS rebinding, open redirects, SQL / command / Dockerfile / environment
injection, path traversal (encoded, absolute, Windows, NUL byte), zip slip, zip bombs, oversized bodies, YAML bombs,
analyzer DoS, secret disclosure, security headers, dotfiles, exposed internal ports, hosted-app network isolation and
sign-in brute force. The last test locks this machine out of *new* sign-ins for 5 minutes (restart the control plane to reset).

Known limits: the control plane has full access to Docker through its socket, hosted apps are served over plain HTTP
on localhost, and hosted apps can still reach the internet and services on the host bound to `0.0.0.0`.

## Layout

| Path | What |
| --- | --- |
| `control-plane/` | FastAPI + Docker SDK. `app/main.py` (API and pipeline), `security.py` (auth, CSRF, headers), `code_review.py` (security analyzer), `runtime.py` (build/run), `quantum.py` (QuantumTrace client), `migration.py` + `aws_sources.py` (AWS migration), `store.py` (SQLite) |
| `security-tests/` | Attack suite run against the live stack |
| `JunctionX/` | QuantumTrace scanner (teammate's code), run as its own service |
| `frontend/` | Website and console (Vite, React, TypeScript, Tailwind) |
| `examples/apps/` | Sample apps: `legacy-payments` (RSA, gets blocked by the gate), `secure-notes` (AES-256), `hello-node`, `landing-static` |

## API

| Method | Path | |
| --- | --- | --- |
| `POST` | `/api/apps` | multipart: `name`, `enforce_gate`, `files[]`, optional `env` (JSON; defaults to the variables in the app's AWS config) |
| `POST` | `/api/migrations/analyze` | multipart `files[]` → migration report, nothing deployed |
| `GET` | `/api/apps`, `/api/apps/{id}` | status, URL, scan summary |
| `POST` | `/api/apps/{id}/stop` · `/start` · `/redeploy` | lifecycle |
| `DELETE` | `/api/apps/{id}` | removes container, image and files |
| `GET` | `/api/apps/{id}/logs` · `/stats` · `/scan` | logs, CPU/memory, full QuantumTrace result |
| `GET` | `/api/events?app_id=` | shared event feed |
| `GET` | `/api/apps/{id}/files` · `/file?path=` | Source tree and file contents (editor) |
| `PUT` | `/api/apps/{id}/file?path=` | Save a file: `{"content": "…"}` |
| `GET` | `/api/apps/{id}/analysis` | Security + QuantumTrace findings for every file |
| `POST` | `/api/apps/{id}/analysis/file` | Findings for an unsaved buffer: `{"path", "content"}` |
| `POST` | `/api/auth/login` · `/logout`, `GET /api/auth/me` | Session (all other routes need it) |
| `GET` | `/api/system` | Docker and QuantumTrace reachability |
| `GET` | `/api/health` | `{"status": "ok"}` only |

All requests except `GET` need the header `X-OwnCloud-CSRF: 1`.

## Developing without Compose

```bash
# QuantumTrace on :8001
docker build -t owncloud/quantumtrace JunctionX && docker run -d -p 127.0.0.1:8001:8000 owncloud/quantumtrace

# Control plane on :8000 (then point the frontend at it with OWNCLOUD_API=http://localhost:8000)
cd control-plane && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000

# Frontend on :5180 (proxies /api to the Compose stack on :8088 by default)
cd frontend && npm install && npm run dev
```

> This is a hackathon demo, not a multi-tenant platform: apps run with resource limits but share the
> host's Docker daemon, and the control plane has full access to it through the Docker socket.
