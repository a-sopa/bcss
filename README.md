# OwnCloud — European cloud infrastructure with AI monitoring

A small cloud that hosts and runs your programs as Docker containers. Every deployment is analysed by
**QuantumTrace** for quantum-vulnerable cryptography before it runs.

```bash
echo "OWNCLOUD_ADMIN_PASSWORD=choose-a-long-password" > .env   # optional, 12+ characters
docker compose up -d --build
```

The first account is **`admin`**, with that password. Without `.env`, its password is generated on first start:

```bash
docker compose exec control-plane cat /data/admin-password.txt
```

The password in `.env` is only used to create `admin`; change it later in **Settings**.

| URL | What |
| --- | --- |
| http://localhost:8088 | Website |
| http://localhost:8088/#/console | Console (sign in): deploy and manage apps |
| http://localhost:8088/#/console/apps/&lt;id&gt;/editor | Code editor with security highlighting |
| http://localhost:8088/#/console/settings | Password, access tokens, users (admins) |

Only port 8088 is published. The control plane and QuantumTrace are internal to Compose.
Hosted apps are published on random ports on `127.0.0.1` (a different site from the console on `localhost`);
the console links to each one.

## Accounts

- **Sign-up** is open by default: anyone who can reach the console can create an account (set
  `OWNCLOUD_ALLOW_SIGNUP=false` in `.env` to let only admins create accounts). New accounts are regular users.
- **Users** see and manage only their own apps (at most 10 each, `OWNCLOUD_MAX_APPS_PER_USER`).
  **Admins** see every app with its owner and manage accounts under **Settings → Users**: create, promote,
  disable (signs the user out and stops their apps) or delete (removes their apps).
- **Access tokens** (Settings → Access tokens) let tools such as the VS Code extension use an account.
- From the host, accounts can also be managed with the admin CLI:

```bash
docker compose exec control-plane python -m app.cli list
docker compose exec control-plane python -m app.cli create <username> [--admin]   # prints a generated password
docker compose exec control-plane python -m app.cli reset-password <username>
```

## VS Code extension

`vscode-extension/` contains **OwnCloud Security**, which brings the web editor's analysis into VS Code:
the same yellow/orange/red/black line colours, Problems-panel entries, hover explanations with suggestions,
quick fixes (`Ctrl+.`), live re-analysis while typing, *Analyse workspace*, and an **OwnCloud** sidebar listing
your apps (download an app's source, edit it, *Push changes and redeploy*).

```bash
code --install-extension vscode-extension/owncloud-security.vsix
```

Then: console → **Settings → Access tokens → Create**, and in VS Code run **OwnCloud: Sign in** with
`http://localhost:8088` and the token. Build and test it yourself:

```bash
cd vscode-extension && npm install && npm run compile && npm run package
npm run test:unit                                   # plus API tests with OWNCLOUD_URL + OWNCLOUD_TEST_TOKEN
VSCODE_CLI=/snap/bin/code npm run test:vscode       # runs inside a real VS Code with an isolated profile
```

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
upload / edit / push
  → migration analysis    AWS origin, environment variables, AWS services, hard-coded keys
  → detect runtime        Dockerfile · Lambda · Procfile · package.json · application.py · main.py/app.py · index.html
  → QuantumTrace scan     .py / .java / .go files → findings, tiers, exposure score (optional gate)
  → snapshot vN           the exact source of this version, kept for diffs and rollbacks
  → docker build          dependencies cached separately from code
  → smart CI              only the tests affected by what changed since the running version
  → readiness             the new version gets traffic only once it answers HTTP
  → canary              5% of traffic for 45 s, compared statistically with the current version
  → promote to 100%  —or—  automatic rollback + root-cause report
```

Every app runs behind its own **router** (`owncloud-app-<id>`, the public address, which never changes between
versions) on a **private network** with its versions (`…-v<N>`) and optional database; apps cannot reach each other
or the control plane, which talks to routers only through the Docker API. Apps must listen on `$PORT`
(8080 for Python/Node). Every step is written to the shared event feed (`GET /api/events`).

## AI features

Each app in the console has tabs for these. Try them with `examples/apps/smart-shop`.

| Feature | How it works |
| --- | --- |
| **Smart CI/CD** (Deployments tab) | Each version's source is snapshotted; files are compared with the running version; a dependency graph (Python imports via AST, JS/TS `import`/`require`) selects only the tests that depend on what changed, plus last run's failures. Dependency or Dockerfile changes run everything; docs-only changes run nothing. The pipeline reports *ran 1 of 3 test files, ~12 s saved*. |
| **Self-healing canary** (Deployments) | The new version receives `OWNCLOUD_CANARY_PERCENT` (5%) of real traffic for `OWNCLOUD_CANARY_SECONDS` (45 s), plus health probes on the pages visitors use most. Error rate (two-proportion z-test), p95 latency and crashes are compared with the stable version; anomalies roll back automatically, otherwise the canary is promoted. Manual rollback is one click. |
| **Root-cause analysis** (Incidents tab) | On a rollback, failed tests, a crash or an error spike in production (checked every 10 s), metrics, logs and the code diff are correlated: *"Errors on the canary (v3) started 20 s ago because of the change made in this version at line 14 of catalog.py: ZeroDivisionError — a division by zero."* — with the fix hint, the code at fault and the change to revert. |
| **Autonomous database tuning** (Database tab) | One click adds a private PostgreSQL 16 (`DATABASE_URL`). Every 30 s the optimiser reads `pg_stat_statements`, explains slow queries (`EXPLAIN (GENERIC_PLAN)`), creates indexes for filtered sequential scans on large tables, keeps them only if the planner uses them and the cost falls, drops its own unused indexes, and suggests rewrites (`OFFSET` → keyset, `NOT IN` → `NOT EXISTS`, `SELECT *`, leading `%`…). |
| **Predictive edge cache** (Traffic & edge tab) | The router keeps a cache per region (Lisbon, Madrid, Paris, Frankfurt…, from the visitor's language or an `X-OwnCloud-Region` header — logical edge locations, all served by one router on this machine). It learns a Markov model of navigation per region and prefetches the pages visitors are likely to open next, and re-warms popular pages before they expire. Only anonymous GET responses that are cacheable (`Cache-Control: public/max-age`, or static assets) are stored; requests with cookies or authorization always go to the app. |
| **Generated load tests** (Load test tab) | From the real traffic: entry pages, page-to-page probabilities, think time and peak rate. Virtual users replay that behaviour in growing stages (up to 200) against the router until p95 > 1 s or errors > 1%, giving the capacity in req/s. The scenario downloads as a **k6** script. Only GET requests are replayed; sensitive query values (token, key, email…) are never recorded. |

```bash
control-plane/.venv/bin/python scripts/test-ai-features.py   # end-to-end check of all six (several minutes)
```

Apps deployed before routers existed keep their old container until their next **Redeploy**, which moves them to
the router architecture (and gives them all of the above).

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

- **Authentication:** user accounts with scrypt-hashed passwords (12+ characters, not containing the username, not a
  common password), server-side sessions in an `HttpOnly`, `SameSite=Strict` cookie, a new session on every sign-in
  (no fixation). Every API route except sign-in, sign-up and a minimal health check needs a session or a token.
- **Authorisation:** every app route checks ownership; another user's app is indistinguishable from a missing one
  (404). Admin routes need an admin *browser session*. Request bodies reject unknown fields (no mass assignment of
  `role`). Admins cannot demote, disable or delete themselves.
- **Access tokens:** `oc_` + 256 random bits, stored as SHA-256, shown once, expiring (≤ 1 year), revocable. A token
  only reaches an allow-list of code/analysis routes ("read" or "write" scope) and can never manage the account,
  tokens or users. Disabling a user or changing a password ends their sessions.
- **Enumeration:** wrong password and unknown user return the same answer in the same time (a dummy hash is computed).
- **Cookie tossing:** hosted apps are linked on `127.0.0.1` while the console only answers on `localhost`
  (`127.0.0.1:8088` redirects), so apps are a different site; requests carrying two session cookies are refused.
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

151 attacks against the running stack (`test_attacks.py`, `test_users.py`), using temporary accounts it creates and
removes: cross-user access to every app route, privilege escalation, role mass assignment, token scope and
cross-user abuse, revoked/expired/forged tokens, disabled accounts, password changes, username enumeration (answers
and timing), cookie tossing, session fixation, unauthenticated access, forged cookies, session replay after sign-out, CSRF
from other origins and from hosted apps, DNS rebinding, open redirects, SQL / command / Dockerfile / environment
injection, path traversal (encoded, absolute, Windows, NUL byte), zip slip, zip bombs, oversized bodies, YAML bombs,
analyzer DoS, secret disclosure, security headers, dotfiles, exposed internal ports, hosted-app network isolation and
sign-in brute force. The last test locks this machine out of *new* sign-ins for 5 minutes (restart the control plane to reset).

Known limits: the control plane has full access to Docker through its socket, so every user can run code on this
machine inside resource-limited containers (that is what a cloud does — keep sign-up off unless you trust who can
reach the console); hosted apps are served over plain HTTP; they can still reach the internet and services on the host
bound to `0.0.0.0`; and for a public deployment, serve the console and the apps on separate domains with HTTPS.

## Layout

| Path | What |
| --- | --- |
| `control-plane/` | FastAPI + Docker SDK. `app/main.py` (API and pipeline), `security.py` (auth, CSRF, headers), `code_review.py` (security analyzer), `runtime.py` (build/run), `quantum.py` (QuantumTrace client), `migration.py` + `aws_sources.py` (AWS migration), `store.py` (SQLite) |
| `control-plane/app/router/` | Per-app router (traffic split, metrics, edge cache, prefetch) and the load generator |
| `control-plane/app/{pipeline,canary,rca,database,loadtest}.py` | Smart CI, canary analysis, root-cause analysis, database tuning, load tests |
| `scripts/` | End-to-end checks: `test-ai-features.py`, `test-vscode.py` |
| `security-tests/` | Attack suite run against the live stack |
| `vscode-extension/` | OwnCloud Security extension for VS Code |
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
| `POST` | `/api/auth/signup`, `GET /api/auth/config` | Self-service account (when enabled) |
| `POST` | `/api/auth/password` | Change password: `{"current_password", "new_password"}` |
| `GET` `POST` `DELETE` | `/api/tokens` | Personal access tokens (browser session only) |
| `GET` `POST` `PATCH` `DELETE` | `/api/users` | Accounts (admins, browser session only) |
| `POST` | `/api/analysis/file` | Findings for any file `{"path", "content"}` (used by the VS Code extension) |
| `GET` | `/api/apps/{id}/archive` | Every text file of an app in one response |
| `GET` | `/api/apps/{id}/deployments` · `POST …/rollback` | Pipeline + canary history; roll back one version |
| `GET` | `/api/apps/{id}/traffic` | Per-version requests/errors/latency, edge cache per region, learned navigation |
| `GET` | `/api/apps/{id}/incidents` | Root-cause reports |
| `GET` `POST` | `/api/apps/{id}/database` · `POST …/database/optimize` | Managed PostgreSQL and its optimiser |
| `GET` | `/api/apps/{id}/loadtest/model` · `…/loadtest/k6` | Learned traffic model; k6 script |
| `GET` `POST` | `/api/apps/{id}/loadtests` | Run and list generated load tests (`{"max_users"}`) |
| `GET` | `/api/system` | Docker and QuantumTrace reachability |
| `GET` | `/api/health` | `{"status": "ok"}` only |

Browser requests other than `GET` need the header `X-OwnCloud-CSRF: 1`. Tools authenticate with
`Authorization: Bearer oc_…` instead (no CSRF header needed).

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
