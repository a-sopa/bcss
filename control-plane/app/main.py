"""OwnCloud control plane: host and run apps, with QuantumTrace analysis on every deployment.

Deploy pipeline: upload → migration analysis → QuantumTrace scan + security gate (optional) → snapshot → build →
impacted tests → canary (5% of traffic, statistical comparison) → promote, or roll back with a root-cause report.
Every step is recorded in a shared event feed that other AI modules can read and write.
Every route except sign-in, sign-up and a minimal health check needs a signed-in user or an access token
(see security.py). Users only see their own apps; admins see every app and manage accounts.
"""

import json
import re
import secrets
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi import Path as PathParam
from pydantic import BaseModel, ConfigDict, Field

from . import canary, code_review, config, database, loadtest, migration, pipeline, quantum, rca
from .aws_sources import SKIP_DIRS
from .runtime import GENERATED_DOCKERFILE, DeployError, Runtime, RuntimeSpec, detect
from .security import (
    SESSION_COOKIE, TOKEN_PREFIX, USERNAME_PATTERN, Guard, Principal, RateLimiter, Sessions, burn_password_check,
    client_id, hash_password, initial_admin_password, password_problem, verify_password,
)
from .store import Store
from .uploads import UploadError, safe_relative, write_sources

docs = {"docs_url": "/api/docs", "openapi_url": "/api/openapi.json"} if config.ENABLE_API_DOCS else {
    "docs_url": None, "redoc_url": None, "openapi_url": None,
}
app = FastAPI(title="OwnCloud control plane", version="0.2.0", **docs)
store = Store(config.DATA_DIR / "owncloud.db")
runtime = Runtime()
sessions = Sessions(config.SESSION_TTL_SECONDS)
login_limiter = RateLimiter(per_client=5, overall=30)
signup_limiter = RateLimiter(per_client=5, overall=50, window=3600)
app.add_middleware(Guard, sessions=sessions, users=store.get_user, tokens=store.resolve_token)

# First start with accounts: create the admin (from the configured or pre-accounts password) and give it older apps.
if not store.list_users():
    _salt, _hash = initial_admin_password(config.DATA_DIR, config.ADMIN_PASSWORD)
    store.create_user("admin", _salt, _hash, "admin")
store.adopt_orphans(next(u["id"] for u in store.list_users() if u["role"] == "admin"))
if config.ADMIN_PASSWORD:  # a generated password from an earlier start no longer applies
    (config.DATA_DIR / "admin-password.txt").unlink(missing_ok=True)

_deploying: set[str] = set()
_deploying_lock = threading.Lock()
_build_slots = threading.BoundedSemaphore(config.MAX_CONCURRENT_BUILDS)

BUSY = {"queued", "scanning", "building", "testing", "starting"}
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
HIDDEN_FILES = {GENERATED_DOCKERFILE}
HIDDEN_DIRS = SKIP_DIRS  # includes .owncloud (generated shims)

AppId = Annotated[str, PathParam(pattern=r"^[0-9a-f]{10}$")]
UserId = Annotated[str, PathParam(pattern=r"^[0-9a-f]{10}$")]


def current(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(401, "Authentication required")
    return principal


def browser_session(principal: Annotated[Principal, Depends(current)]) -> Principal:
    """Account management is only possible from a signed-in browser session, never with an access token."""
    if principal.via != "session":
        raise HTTPException(403, "Sign in to the console to do this")
    return principal


def admin_session(principal: Annotated[Principal, Depends(browser_session)]) -> Principal:
    if not principal.is_admin:
        raise HTTPException(403, "Administrators only")
    return principal


User = Annotated[Principal, Depends(current)]
SessionUser = Annotated[Principal, Depends(browser_session)]
Admin = Annotated[Principal, Depends(admin_session)]

# Containers of apps that no longer exist (e.g. deleted mid-deploy before this fix) are removed.
runtime.sweep({record["id"] for record in store.list_apps()})

# A restart interrupts any deployment that was in progress; an interrupted canary goes back to the stable version.
for _record in store.list_apps():
    if _record["status"] in BUSY:
        store.update_app(_record["id"], status="failed", detail="Deployment interrupted by a control-plane restart. Redeploy the app.")
    elif _record["status"] == "canary" and _record["version"]:
        try:
            _stable = store.rows("deployments", _record["id"], 50)
            _port = next((d["detail"]["port"] for d in _stable if d["version"] == _record["version"] and d["detail"]), 8080)
            runtime.set_routes(_record["id"], [{"version": _record["version"], "port": _port, "weight": 100, "role": "stable"}])
            runtime.remove_version(_record["id"], _record["canary_version"])
        except Exception:
            pass
        store.update_app(_record["id"], status="running", canary_version=None,
                         detail="The canary was stopped by a control-plane restart; the stable version kept serving.")


def app_dir(app_id: str) -> Path:
    return config.DATA_DIR / "apps" / app_id


def source_dir(app_id: str) -> Path:
    return app_dir(app_id) / "src"


def _view(app_record: dict[str, Any]) -> dict[str, Any]:
    """Reconcile the stored status with the live container state and add the public URL."""
    status = app_record["status"]
    if status not in BUSY | {"blocked", "failed", "canary"}:
        state = runtime.state(app_record["id"], app_record["version"])
        if state == "running":
            status = "running"
        elif state == "restarting":
            status = "restarting"
        elif state in ("exited", "dead", "created"):
            status = "stopped" if status == "stopped" else "crashed"
        elif state is None:
            status = "missing"
    url = f"http://{config.PUBLIC_HOST}:{app_record['host_port']}" if app_record["host_port"] else None
    view = {**app_record, "status": status, "url": url if status in ("running", "canary") else None}
    # Values can be secrets: expose only the variable names.
    view["env_keys"] = sorted(view.pop("env") or {})
    if view["migration"]:
        view["migration"] = {**view["migration"], "env": sorted(view["migration"]["env"])}
    return view


def _owned(app_id: str, principal: Principal) -> dict[str, Any]:
    """The app, if it exists and this user may see it. Other users' apps look exactly like missing ones."""
    record = store.get_app(app_id)
    if record is None or (not principal.is_admin and record["owner_id"] != principal.id):
        raise HTTPException(404, "App not found")
    return record


def _parse_env(raw: str | None) -> dict[str, str] | None:
    if raw is None or not raw.strip():
        return None
    try:
        env = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(422, "env must be a JSON object of strings") from exc
    if not isinstance(env, dict) or len(env) > 200:
        raise HTTPException(422, "env must be a JSON object with at most 200 variables")
    for key, value in env.items():
        if not ENV_KEY_PATTERN.match(key) or not isinstance(value, str) or len(value) > 32_768 or "\x00" in value:
            raise HTTPException(422, f"Invalid environment variable: {key[:40]!r}")
    return env


async def _read_uploads(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    """Check counts and sizes before reading anything into memory."""
    if not files or len(files) > config.MAX_UPLOAD_FILES:
        raise HTTPException(422, f"Upload between 1 and {config.MAX_UPLOAD_FILES} files")
    if any(f.size is None for f in files) or sum(f.size for f in files) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Uploads are limited to 50 MB")
    return [(f.filename or "file", await f.read()) for f in files]


def _migration_events(app_id: str, report: dict[str, Any]) -> None:
    if report["platform"].startswith("AWS"):
        store.add_event(app_id, "migration", "info", f"Imported from {report['platform']}", report["runtime_label"])
    if report["services"]:
        mapped = ", ".join(f"{s['aws']} → {s['replacement']}" for s in report["services"])
        store.add_event(app_id, "migration", "low", f"{len(report['services'])} AWS dependenc(ies) mapped", mapped)
    if report["access_keys"]:
        places = ", ".join(f"{k['file']}:{k['line']}" for k in report["access_keys"])
        store.add_event(app_id, "migration", "high", "Hard-coded AWS access key found", places)


def _scan_event(app_id: str, summary: dict[str, Any]) -> None:
    if summary.get("status") == "skipped":
        store.add_event(app_id, "quantum", "info", "Quantum scan skipped", summary.get("reason"))
        return
    tiers = summary["tiers"]
    if tiers["critical"]:
        severity, title = "high", f"{tiers['critical']} quantum-vulnerable finding(s)"
    elif tiers["medium"]:
        severity, title = "medium", f"{tiers['medium']} finding(s) weakened by quantum attacks"
    else:
        severity, title = "info", "No quantum-vulnerable cryptography found"
    detail = f"Exposure score {summary['score']} across {summary['files_scanned']} file(s)" if summary["score"] is not None else None
    store.add_event(app_id, "quantum", severity, title, detail)


def deploy(app_id: str) -> None:
    with _deploying_lock:
        if app_id in _deploying:
            return
        _deploying.add(app_id)
    try:
        with _build_slots:  # bound concurrent builds (CPU, memory, disk)
            _deploy(app_id)
    finally:
        with _deploying_lock:
            _deploying.discard(app_id)
        if store.get_app(app_id) is None:  # deleted while deploying: nothing of it may keep running
            runtime.remove_app(app_id)
            shutil.rmtree(app_dir(app_id), ignore_errors=True)


def _probe_paths(app_id: str) -> list[str]:
    """Health-probe paths: the root plus the pages real visitors use most (so canaries are tested where it matters)."""
    metrics = runtime.router_metrics(app_id) or {}
    counts: dict[str, int] = {}
    for entry in metrics.get("log", []):
        if entry["method"] == "GET" and entry["status"] < 400 and not entry.get("load") and "redacted" not in entry["path"]:
            counts[entry["path"]] = counts.get(entry["path"], 0) + 1
    return ["/", *[p for p, _ in sorted(counts.items(), key=lambda kv: -kv[1]) if p != "/"][:4]]


def _deployment_port(app_id: str, version: int) -> int:
    for record in store.rows("deployments", app_id, 100):
        if record["version"] == version and record["detail"]:
            return record["detail"].get("port", 8080)
    return 8080


def _record_incident(app_id: str, report: dict[str, Any]) -> None:
    title = {"canary_rollback": "Canary rolled back", "tests_failed": "Tests failed", "crash": "Version crashed",
             "error_spike": "Error spike"}.get(report["kind"], "Incident")
    store.insert("incidents", app_id=app_id, kind=report["kind"], title=f"{title}: v{report['version']}", report=report)
    store.add_event(app_id, "incident", "high", f"{title} (v{report['version']})", report["summary"])


def _critical_code_findings(app_id: str) -> list[dict[str, Any]]:
    """Critical security-review findings (injection, eval, leaked keys…) across the uploaded source."""
    findings = []
    for item in _list_sources(app_id):
        content = _read_text(source_dir(app_id) / item["path"])
        if content is not None:
            findings += [f for f in code_review.review(item["path"], content) if f["severity"] == "critical"]
    return [{"file": f["file"], "line": f["line"], "title": f["title"]} for f in findings]


def _gate_reason(vulnerabilities: list[dict[str, Any]], quantum_critical: int, unavailable: bool) -> str:
    parts = []
    if vulnerabilities:
        titles = list(dict.fromkeys(f["title"] for f in vulnerabilities))
        listed = ", ".join(titles[:4]) + (", …" if len(titles) > 4 else "")
        parts.append(f"{len(vulnerabilities)} critical vulnerabilit{'y' if len(vulnerabilities) == 1 else 'ies'} ({listed})")
    if quantum_critical:
        parts.append(f"{quantum_critical} quantum-vulnerable finding(s)")
    if not parts and unavailable:
        return "Deployment blocked: the code could not be analysed."
    return "Deployment blocked: " + " and ".join(parts) + ". Open Code to see and fix them."


def _deploy(app_id: str) -> None:
    record = store.get_app(app_id)
    if record is None:
        return
    root = source_dir(app_id)
    previous = record["version"]
    version = max([previous or 0] + [d["version"] for d in store.rows("deployments", app_id, 1)]) + 1
    deployment = store.insert("deployments", app_id=app_id, version=version, status="running")

    def finish(status: str, **fields: Any) -> None:
        store.update_row("deployments", deployment, status=status, finished_at=time.time(), **fields)

    try:
        report = migration.analyze(root)
        env = record["env"] if record["env"] is not None else report["env"]
        store.update_app(app_id, migration=report, env=env)
        _migration_events(app_id, report)

        spec = detect(root)
        store.update_app(app_id, runtime=spec.name, status="scanning", detail="Analysing source code with QuantumTrace")
        try:
            summary, full = quantum.scan(root, label=record["name"])
            if full is not None:
                (app_dir(app_id) / "scan.json").write_text(json.dumps(full))
            _scan_event(app_id, summary)
        except quantum.ScanUnavailable as exc:
            summary = {"status": "unavailable", "reason": "QuantumTrace is not reachable."}
            store.add_event(app_id, "quantum", "medium", "Quantum scan unavailable", str(exc))
        store.update_app(app_id, scan_summary=summary)
        critical = summary.get("tiers", {}).get("critical", 0)
        if record["enforce_gate"]:
            vulnerabilities = _critical_code_findings(app_id)
            if critical or vulnerabilities or summary["status"] == "unavailable":
                reason = _gate_reason(vulnerabilities, critical, summary["status"] == "unavailable")
                store.update_app(app_id, status="blocked" if not previous else "running", detail=reason)
                store.add_event(app_id, "gate", "high", "Deployment blocked by security gate", reason)
                return finish("blocked", detail={"reason": reason, "vulnerabilities": vulnerabilities[:20]})

        # Snapshot this version and work out what changed since the running one.
        snapshot = pipeline.snapshot(app_dir(app_id), root, version)
        before = pipeline.versions_dir(app_dir(app_id)) / str(previous) if previous else None
        before = before if before and before.is_dir() else None
        changed = pipeline.changes(before, snapshot)
        touched = changed["added"] + changed["modified"] + changed["removed"]

        store.update_app(app_id, status="building", detail=f"Building v{version} ({spec.name})")
        store.add_event(app_id, "deploy", "info", f"Build of v{version} started", f"{len(touched)} file(s) changed")
        image = runtime.build(app_id, root, spec, version)
        store.update_row("deployments", deployment, detail={"port": spec.port, "runtime": spec.name, "image": image})

        # Smart CI: only the tests that depend on what changed.
        last = next((d for d in store.rows("deployments", app_id, 5) if d["pipeline"] and d["id"] != deployment), None)
        selection = pipeline.select_tests(snapshot, changed, (last["pipeline"] or {}).get("failing_files", []) if last else [])
        store.update_app(app_id, status="testing", detail=selection["reason"])
        result = pipeline.run_tests(runtime, app_id, image, spec.name, selection)
        result["changed"] = changed
        store.update_row("deployments", deployment, pipeline=result)
        if result["status"] == "passed":
            store.add_event(app_id, "pipeline", "info", f"Tests passed: {len(result['tests'])} of {len(result['all_tests'])} file(s)",
                            f"{result['duration']} s; ~{result['estimated_saving']} s saved by skipping unaffected tests")
        elif result["status"] == "failed":
            report = rca.analyse(kind="tests_failed", version=version, logs=result["output"], current=snapshot,
                                 previous=before, changed=touched)
            _record_incident(app_id, report)
            stable = previous is not None and runtime.state(app_id, previous) == "running"
            store.update_app(app_id, status="running" if stable else "failed",
                             detail=f"v{version} was not deployed: tests failed. " + report["summary"])
            runtime.remove_version(app_id, version, image=True)
            return finish("tests_failed")

        if store.get_app(app_id) is None:
            return  # deleted during the build or the tests
        host_port = runtime.ensure_router(app_id)
        stable = previous is not None and runtime.state(app_id, previous) == "running"
        if not stable:
            store.update_app(app_id, status="starting", detail=f"Starting v{version}")
            name = runtime.run_version(app_id, version, spec, env)
            if not runtime.wait_running(name) or not runtime.wait_ready(app_id, version, spec.port):
                logs = runtime.logs(app_id, version, tail=300)
                report = rca.analyse(kind="crash", version=version, logs=logs, current=snapshot, previous=before,
                                     changed=touched, oom=runtime.oom_killed(app_id, version))
                _record_incident(app_id, report)
                raise DeployError(f"v{version} stopped right after starting. {report['summary']}")
            runtime.set_routes(app_id, [{"version": version, "port": spec.port, "weight": 100, "role": "stable"}],
                               probe_paths=_probe_paths(app_id))
            if previous:
                runtime.remove_version(app_id, previous)
            store.update_app(app_id, status="running", detail=None, host_port=host_port, image=image, version=version, canary_version=None)
            store.add_event(app_id, "deploy", "info", f"v{version} is running", f"http://{config.PUBLIC_HOST}:{host_port}")
            finish("deployed")
        else:
            _canary(app_id, version, previous, spec, env, deployment, snapshot, before, touched, image)
        for old in range(1, version - 2):  # keep the images of the last three versions
            if old not in (version, previous):
                runtime.remove_version(app_id, old, image=True)
    except DeployError as exc:
        store.update_app(app_id, status="failed", detail=str(exc))
        store.add_event(app_id, "deploy", "high", "Deployment failed", str(exc))
        finish("failed", detail={"error": str(exc)[:2000]})
    except Exception as exc:  # Docker or filesystem errors: report them on the app instead of losing them
        store.update_app(app_id, status="failed", detail=f"Unexpected error: {exc}")
        store.add_event(app_id, "deploy", "high", "Deployment failed", repr(exc))
        finish("failed", detail={"error": repr(exc)[:2000]})


def _canary(app_id: str, version: int, stable: int, spec: RuntimeSpec, env: dict[str, str] | None, deployment: int,
            snapshot: Path, before: Path | None, touched: list[str], image: str) -> None:
    """Give the new version a small share of traffic, watch it, then promote it or roll back on its own."""
    percent = config.CANARY_PERCENT
    store.update_app(app_id, status="canary", canary_version=version,
                     detail=f"Canary: v{version} receives {percent}% of traffic and is being compared with v{stable}")
    store.add_event(app_id, "canary", "info", f"Canary started: v{version} at {percent}%")
    name = runtime.run_version(app_id, version, spec, env)
    started = time.time()
    stable_port = _deployment_port(app_id, stable)
    probes = _probe_paths(app_id)
    result: dict[str, Any] = {"anomalous": False}
    store.update_app(app_id, detail=f"Starting v{version}; it gets traffic once it answers requests")
    if not runtime.wait_running(name) or not runtime.wait_ready(app_id, version, spec.port):
        result = canary.verdict(None, f"v{version}", f"v{stable}", started, crashed=True)
    else:
        started = time.time()
        store.update_app(app_id, detail=f"Canary: v{version} receives {percent}% of traffic and is being compared with v{stable}")
        runtime.set_routes(app_id, [
            {"version": stable, "port": stable_port, "weight": 100 - percent, "role": "stable"},
            {"version": version, "port": spec.port, "weight": percent, "role": "canary"},
        ], probe_paths=probes)
        while time.time() - started < config.CANARY_SECONDS:
            time.sleep(5)
            if store.get_app(app_id) is None:
                return  # deleted during the canary; deploy() removes everything
            container = runtime.get(name)
            crashed = container is None or container.status not in ("running",)
            result = canary.verdict(runtime.router_metrics(app_id), f"v{version}", f"v{stable}", started, crashed)
            if result["anomalous"]:
                break
    result["percent"], result["seconds"] = percent, round(time.time() - started)

    if result["anomalous"]:
        runtime.set_routes(app_id, [{"version": stable, "port": stable_port, "weight": 100, "role": "stable"}], probe_paths=probes)
        logs = runtime.logs(app_id, version, tail=400, since=started - 5)
        report = rca.analyse(kind="canary_rollback", version=version, logs=logs, current=snapshot, previous=before, changed=touched,
                             metrics=runtime.router_metrics(app_id), since=started, symptom=result["reason"],
                             oom=runtime.oom_killed(app_id, version))
        runtime.remove_version(app_id, version)
        _record_incident(app_id, report)
        store.update_app(app_id, status="running", canary_version=None,
                         detail=f"v{version} was rolled back automatically: {result['reason']}. v{stable} keeps serving.")
        store.add_event(app_id, "canary", "high", f"Automatic rollback of v{version}", result["reason"])
        store.update_row("deployments", deployment, status="rolled_back", finished_at=time.time(), canary=result)
        return

    runtime.set_routes(app_id, [{"version": version, "port": spec.port, "weight": 100, "role": "stable"}], probe_paths=probes)
    time.sleep(2)  # let requests in flight on the old version finish
    runtime.remove_version(app_id, stable)
    store.update_app(app_id, status="running", version=version, canary_version=None, image=image, detail=None)
    note = "" if result.get("enough_data") else " (little traffic: decided on health probes)"
    store.add_event(app_id, "canary", "info", f"v{version} promoted to 100%",
                    f"Error rate {result['canary']['error_rate']:.0%} vs {result['stable']['error_rate']:.0%}{note}")
    store.update_row("deployments", deployment, status="promoted", finished_at=time.time(), canary=result)


# ---------------------------------------------------------------- source files (editor)


def _source_file(app_id: str, relative: str, *, must_exist: bool = True) -> tuple[Path, str]:
    """Resolve an editor path inside the app's source folder; refuse traversal, symlinks and generated files."""
    try:
        clean = safe_relative(relative)
    except UploadError as exc:
        raise HTTPException(400, "Invalid file path") from exc
    if clean.name in HIDDEN_FILES or any(part in HIDDEN_DIRS for part in clean.parts):
        raise HTTPException(403, "This file is managed by OwnCloud")
    root = source_dir(app_id).resolve()
    target = root.joinpath(*clean.parts)
    current = target
    while current != root:
        if current.is_symlink():
            raise HTTPException(403, "Symbolic links cannot be edited")
        current = current.parent
    if not target.resolve().is_relative_to(root):
        raise HTTPException(400, "Invalid file path")
    if must_exist and not target.is_file():
        raise HTTPException(404, "File not found")
    return target, clean.as_posix()


def _list_sources(app_id: str) -> list[dict[str, Any]]:
    root = source_dir(app_id)
    files = []
    if not root.is_dir():
        return files
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink() or not path.is_file() or path.name in HIDDEN_FILES:
            continue
        if any(part in HIDDEN_DIRS for part in relative.parts):
            continue
        files.append({"path": relative.as_posix(), "size": path.stat().st_size,
                      "language": code_review.language_of(relative.as_posix())})
        if len(files) >= config.MAX_UPLOAD_FILES:
            break
    return files


def _read_text(path: Path) -> str | None:
    if path.stat().st_size > config.MAX_EDIT_BYTES:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def _quantum_for(inputs: list[dict[str, str]], label: str) -> tuple[list[dict[str, Any]], str]:
    inputs = [i for i in inputs if Path(i["name"]).suffix.lower() in quantum.SOURCE_SUFFIXES]
    if not inputs:
        return [], "skipped"
    try:
        return quantum.editor_findings(quantum.scan_inputs(inputs, label)), "ok"
    except quantum.ScanUnavailable:
        return [], "unavailable"


def _worst(findings: list[dict[str, Any]]) -> str | None:
    levels = [code_review.SEVERITIES.index(f["severity"]) for f in findings]
    return code_review.SEVERITIES[max(levels)] if levels else None


def _ordered(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(findings, key=lambda f: (-code_review.SEVERITIES.index(f["severity"]), f["file"], f["line"], f["column"]))


class FileContent(BaseModel):
    content: str = Field(max_length=config.MAX_EDIT_BYTES)


class BufferAnalysis(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    content: str = Field(max_length=config.MAX_EDIT_BYTES)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown fields (e.g. "role") are rejected, not ignored


class Login(Strict):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class Signup(Strict):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(Strict):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class NewUser(Strict):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=256)
    role: Literal["admin", "user"] = "user"


class UserUpdate(Strict):
    role: Literal["admin", "user"] | None = None
    disabled: bool | None = None


class NewToken(Strict):
    name: str = Field(min_length=1, max_length=60, pattern=r"^[\w .:@()-]+$")
    scope: Literal["read", "write"] = "read"
    days: int = Field(default=90, ge=1, le=365)


# ---------------------------------------------------------------- routes: auth


def _start_session(response: Response, user_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, sessions.create(user_id), max_age=config.SESSION_TTL_SECONDS, path="/api",
        httponly=True, samesite="strict", secure=config.COOKIE_SECURE,
    )


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {key: user[key] for key in ("id", "username", "role", "disabled", "created_at") if key in user} | (
        {"app_count": user["app_count"]} if "app_count" in user else {}
    )


def _valid_new_account(username: str, password: str) -> str:
    username = username.strip().lower()
    if not USERNAME_PATTERN.match(username):
        raise HTTPException(422, "Usernames are 3–32 characters: lowercase letters, digits, '.', '_' or '-'")
    problem = password_problem(password, username)
    if problem:
        raise HTTPException(422, problem)
    return username


@app.get("/api/auth/config")
def auth_config() -> dict[str, bool]:
    return {"signup": config.ALLOW_SIGNUP}


@app.post("/api/auth/login")
def login(body: Login, request: Request, response: Response) -> dict[str, Any]:
    client = client_id(request)
    wait = login_limiter.retry_after(client)
    if wait:
        raise HTTPException(429, "Too many failed attempts; try again later", headers={"Retry-After": str(wait)})
    user = store.user_by_name(body.username.strip().lower())
    if user is None:
        burn_password_check(body.password)
    if user is None or not verify_password(body.password, user["salt"], user["password_hash"]) or user["disabled"]:
        login_limiter.record(client)
        raise HTTPException(401, "Incorrect username or password")  # same answer for every failure
    login_limiter.clear(client)
    _start_session(response, user["id"])
    return _public_user(user)


@app.post("/api/auth/signup", status_code=201)
def signup(body: Signup, request: Request, response: Response) -> dict[str, Any]:
    if not config.ALLOW_SIGNUP:
        raise HTTPException(403, "Sign-up is disabled; ask an administrator for an account")
    client = client_id(request)
    wait = signup_limiter.retry_after(client)
    if wait:
        raise HTTPException(429, "Too many accounts created; try again later", headers={"Retry-After": str(wait)})
    username = _valid_new_account(body.username, body.password)
    if store.user_by_name(username):
        raise HTTPException(409, "This username is taken")
    signup_limiter.record(client)
    user = store.create_user(username, *hash_password(body.password), "user")
    _start_session(response, user["id"])
    return _public_user(user)


@app.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    sessions.revoke(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/api", httponly=True, samesite="strict", secure=config.COOKIE_SECURE)
    return {"authenticated": False}


@app.get("/api/auth/me")
def me(user: User) -> dict[str, Any]:
    return {"id": user.id, "username": user.username, "role": user.role, "via": user.via, "scope": user.scope}


@app.post("/api/auth/password")
def change_password(body: PasswordChange, user: SessionUser) -> dict[str, bool]:
    record = store.get_user(user.id)
    if not verify_password(body.current_password, record["salt"], record["password_hash"]):
        raise HTTPException(403, "The current password is incorrect")
    problem = password_problem(body.new_password, user.username)
    if problem:
        raise HTTPException(422, problem)
    salt, password_hash = hash_password(body.new_password)
    store.update_user(user.id, salt=salt, password_hash=password_hash)
    sessions.revoke_user(user.id, keep=user.session)  # sign out every other browser
    return {"changed": True}


# ---------------------------------------------------------------- routes: access tokens


@app.get("/api/tokens")
def list_tokens(user: SessionUser) -> list[dict[str, Any]]:
    return store.list_tokens(user.id)


@app.post("/api/tokens", status_code=201)
def create_token(body: NewToken, user: SessionUser) -> dict[str, Any]:
    if len(store.list_tokens(user.id)) >= 20:
        raise HTTPException(422, "At most 20 access tokens per user")
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    record = store.create_token(user.id, body.name.strip(), token, body.scope, time.time() + body.days * 86400)
    return {**record, "token": token}  # shown once; only its hash is stored


@app.delete("/api/tokens/{token_id}", status_code=204)
def delete_token(token_id: Annotated[str, PathParam(pattern=r"^[0-9a-f]{10}$")], user: SessionUser) -> None:
    if not store.delete_token(user.id, token_id):
        raise HTTPException(404, "Token not found")


# ---------------------------------------------------------------- routes: users (admins)


@app.get("/api/users")
def list_users(admin: Admin) -> list[dict[str, Any]]:
    return [_public_user(u) for u in store.list_users()]


@app.post("/api/users", status_code=201)
def create_user(body: NewUser, admin: Admin) -> dict[str, Any]:
    username = _valid_new_account(body.username, body.password)
    if store.user_by_name(username):
        raise HTTPException(409, "This username is taken")
    return _public_user(store.create_user(username, *hash_password(body.password), body.role))


@app.patch("/api/users/{user_id}")
def update_user(user_id: UserId, body: UserUpdate, admin: Admin) -> dict[str, Any]:
    target = store.get_user(user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    if user_id == admin.id and (body.role == "user" or body.disabled):
        raise HTTPException(409, "You cannot demote or disable your own account")
    changes: dict[str, Any] = {}
    if body.role is not None:
        changes["role"] = body.role
    if body.disabled is not None:
        changes["disabled"] = int(body.disabled)
    if changes:
        store.update_user(user_id, **changes)
    if body.disabled:
        sessions.revoke_user(user_id)
        for record in store.list_apps(user_id):
            runtime.stop(record["id"])
            store.update_app(record["id"], status="stopped")
    return _public_user(store.get_user(user_id))


@app.delete("/api/users/{user_id}", status_code=204)
def delete_user(user_id: UserId, admin: Admin) -> None:
    if store.get_user(user_id) is None:
        raise HTTPException(404, "User not found")
    if user_id == admin.id:
        raise HTTPException(409, "You cannot delete your own account")
    sessions.revoke_user(user_id)
    for record in store.list_apps(user_id):
        _remove_app(record["id"])
    store.delete_user(user_id)


# ---------------------------------------------------------------- routes: platform


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/system")
def system(user: User) -> dict[str, Any]:
    try:
        quantumtrace = httpx.get(f"{config.QUANTUMTRACE_URL}/openapi.json", timeout=2).is_success
    except httpx.HTTPError:
        quantumtrace = False
    return {"status": "ok", "docker": runtime.ping(), "quantumtrace": quantumtrace}


@app.get("/api/apps")
def list_apps(user: User) -> list[dict[str, Any]]:
    return [_view(record) for record in store.list_apps(None if user.is_admin else user.id)]


@app.post("/api/apps", status_code=201)
async def create_app(
    background: BackgroundTasks,
    user: SessionUser,
    name: str = Form(..., max_length=100),
    enforce_gate: bool = Form(False),
    env: str | None = Form(None, max_length=512 * 1024),
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    """Upload and deploy. Without `env`, the environment declared by the app's AWS configuration is used."""
    name = name.strip().lower()
    if not NAME_PATTERN.match(name):
        raise HTTPException(422, "Name must be 1–40 lowercase letters, digits or hyphens")
    variables = _parse_env(env)
    if not user.is_admin and store.count_apps(user.id) >= config.MAX_APPS_PER_USER:
        raise HTTPException(403, f"App limit reached ({config.MAX_APPS_PER_USER}); delete an app first")
    uploaded = await _read_uploads(files)
    record = store.create_app(name, enforce_gate, user.id, variables)
    try:
        count = write_sources(uploaded, source_dir(record["id"]))
    except UploadError as exc:
        store.delete_app(record["id"])
        shutil.rmtree(app_dir(record["id"]), ignore_errors=True)
        raise HTTPException(422, str(exc)) from exc
    store.add_event(record["id"], "deploy", "info", "App uploaded", f"{count} file(s)")
    background.add_task(deploy, record["id"])
    return _view(store.get_app(record["id"]))


@app.post("/api/migrations/analyze")
async def analyze_migration(user: SessionUser, files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """Migration report for an upload, without deploying it."""
    uploaded = await _read_uploads(files)
    with tempfile.TemporaryDirectory(prefix="owncloud-analyze-") as tmp:
        root = Path(tmp) / "src"
        try:
            write_sources(uploaded, root)
        except UploadError as exc:
            raise HTTPException(422, str(exc)) from exc
        return migration.analyze(root)


@app.get("/api/apps/{app_id}")
def get_app(app_id: AppId, user: User) -> dict[str, Any]:
    return _view(_owned(app_id, user))


@app.post("/api/apps/{app_id}/redeploy")
def redeploy(app_id: AppId, user: User, background: BackgroundTasks) -> dict[str, Any]:
    _owned(app_id, user)
    store.update_app(app_id, status="queued", detail=None)
    background.add_task(deploy, app_id)
    return _view(store.get_app(app_id))


@app.post("/api/apps/{app_id}/stop")
def stop(app_id: AppId, user: User) -> dict[str, Any]:
    _owned(app_id, user)
    runtime.stop(app_id)
    store.update_app(app_id, status="stopped")
    store.add_event(app_id, "deploy", "info", "App stopped")
    return _view(store.get_app(app_id))


@app.post("/api/apps/{app_id}/start")
def start(app_id: AppId, user: User) -> dict[str, Any]:
    record = _owned(app_id, user)
    try:
        runtime.start(app_id, record["version"])
    except DeployError as exc:
        raise HTTPException(409, str(exc)) from exc
    store.update_app(app_id, status="running")
    store.add_event(app_id, "deploy", "info", "App started")
    return _view(store.get_app(app_id))


@app.delete("/api/apps/{app_id}", status_code=204)
def delete(app_id: AppId, user: User) -> None:
    _owned(app_id, user)
    _remove_app(app_id)


def _remove_app(app_id: str) -> None:
    store.add_event(app_id, "deploy", "info", "App deleted")
    runtime.remove_app(app_id)
    shutil.rmtree(app_dir(app_id), ignore_errors=True)
    store.delete_app(app_id)


@app.get("/api/apps/{app_id}/logs")
def logs(app_id: AppId, user: User, tail: int = Query(200, ge=1, le=2000)) -> dict[str, str]:
    record = _owned(app_id, user)
    return {"logs": runtime.logs(app_id, record["version"], tail)}


@app.get("/api/apps/{app_id}/stats")
def stats(app_id: AppId, user: User) -> dict[str, Any] | None:
    record = _owned(app_id, user)
    return runtime.stats(app_id, record["version"])


@app.get("/api/apps/{app_id}/scan")
def scan_result(app_id: AppId, user: User) -> dict[str, Any]:
    _owned(app_id, user)
    path = app_dir(app_id) / "scan.json"
    if not path.is_file():
        raise HTTPException(404, "No QuantumTrace result for this app")
    return json.loads(path.read_text())


@app.get("/api/events")
def events(
    user: User,
    app_id: Annotated[str | None, Query(pattern=r"^[0-9a-f]{10}$")] = None,
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    if app_id:
        _owned(app_id, user)
    return store.list_events(None if user.is_admin else user.id, app_id, limit)


# ---------------------------------------------------------------- routes: editor


@app.get("/api/apps/{app_id}/files")
def list_files(app_id: AppId, user: User) -> dict[str, Any]:
    _owned(app_id, user)
    return {"files": _list_sources(app_id)}


@app.get("/api/apps/{app_id}/archive")
def archive(app_id: AppId, user: User) -> dict[str, Any]:
    """Every text file of the app in one response (used to download or compare a whole project)."""
    _owned(app_id, user)
    files, skipped, total = [], [], 0
    for item in _list_sources(app_id):
        content = _read_text(source_dir(app_id) / item["path"])
        if content is None:
            skipped.append(item["path"])
            continue
        total += len(content.encode())
        if total > config.MAX_UPLOAD_BYTES:
            raise HTTPException(413, "The project is larger than 50 MB")
        files.append({"path": item["path"], "content": content})
    return {"files": files, "skipped": skipped}


@app.get("/api/apps/{app_id}/file")
def read_file(app_id: AppId, user: User, path: str = Query(..., max_length=300)) -> dict[str, Any]:
    _owned(app_id, user)
    target, clean = _source_file(app_id, path)
    content = _read_text(target)
    if content is None:
        raise HTTPException(415, "Only UTF-8 text files up to 1 MB can be opened")
    return {"path": clean, "content": content, "language": code_review.language_of(clean)}


@app.put("/api/apps/{app_id}/file")
def write_file(app_id: AppId, user: User, body: FileContent, path: str = Query(..., max_length=300)) -> dict[str, Any]:
    _owned(app_id, user)
    target, clean = _source_file(app_id, path, must_exist=False)
    if not target.exists() and len(_list_sources(app_id)) >= config.MAX_UPLOAD_FILES:
        raise HTTPException(422, "Too many files")
    if target.exists() and not target.is_file():
        raise HTTPException(409, "A folder with this name exists")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body.content, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(409, "The file could not be saved") from exc
    store.add_event(app_id, "editor", "info", f"Edited {clean}")
    return {"path": clean, "size": target.stat().st_size}


@app.get("/api/apps/{app_id}/analysis")
def analyse_app(app_id: AppId, user: User) -> dict[str, Any]:
    """Security review and QuantumTrace findings for every source file, on the editor's severity scale."""
    record = _owned(app_id, user)
    findings: list[dict[str, Any]] = []
    inputs = []
    for item in _list_sources(app_id):
        content = _read_text(source_dir(app_id) / item["path"])
        if content is None:
            continue
        findings += code_review.review(item["path"], content)
        inputs.append(quantum.source_input(item["path"], content))
    quantum_findings, quantum_status = _quantum_for(inputs, record["name"])
    findings = _ordered(findings + quantum_findings)
    per_file: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        per_file.setdefault(f["file"], []).append(f)
    return {
        "findings": findings,
        "files": {path: _worst(items) for path, items in per_file.items()},
        "counts": {level: sum(1 for f in findings if f["severity"] == level) for level in code_review.SEVERITIES},
        "quantum": quantum_status,
    }


@app.post("/api/analysis/file")
def analyse_workspace_file(body: BufferAnalysis, user: User) -> dict[str, Any]:
    """Findings for any file (e.g. from a local workspace in VS Code), not tied to a deployed app."""
    try:
        clean = safe_relative(body.path).as_posix()
    except UploadError as exc:
        raise HTTPException(400, "Invalid file path") from exc
    findings = code_review.review(clean, body.content)
    quantum_findings, quantum_status = _quantum_for([quantum.source_input(clean, body.content)], user.username)
    return {"findings": _ordered(findings + quantum_findings), "quantum": quantum_status}


@app.post("/api/apps/{app_id}/analysis/file")
def analyse_buffer(app_id: AppId, user: User, body: BufferAnalysis) -> dict[str, Any]:
    """Findings for one (possibly unsaved) file, for live highlighting while editing."""
    record = _owned(app_id, user)
    _, clean = _source_file(app_id, body.path, must_exist=False)
    findings = code_review.review(clean, body.content)
    quantum_findings, quantum_status = _quantum_for([quantum.source_input(clean, body.content)], record["name"])
    return {"findings": _ordered(findings + quantum_findings), "quantum": quantum_status}


# ---------------------------------------------------------------- routes: deployments, traffic, incidents


@app.get("/api/apps/{app_id}/deployments")
def deployments(app_id: AppId, user: User) -> list[dict[str, Any]]:
    _owned(app_id, user)
    return store.rows("deployments", app_id, 30)


@app.post("/api/apps/{app_id}/rollback")
def rollback(app_id: AppId, user: SessionUser) -> dict[str, Any]:
    """Go back to the newest earlier version whose image is still available."""
    record = _owned(app_id, user)
    current = record["version"]
    if not current or record["status"] in BUSY | {"canary"}:
        raise HTTPException(409, "Nothing to roll back to right now")
    candidates = [d for d in store.rows("deployments", app_id, 30)
                  if d["version"] < current and d["status"] in ("promoted", "deployed") and d["detail"]]
    target = next((d for d in candidates if runtime.client.images.list(name=runtime.image_tag(app_id, d["version"]))), None)
    if target is None:
        raise HTTPException(409, "No earlier version is available")
    spec = RuntimeSpec(target["detail"].get("runtime", "?"), target["detail"].get("port", 8080), None)
    name = runtime.run_version(app_id, target["version"], spec, record["env"])
    if not runtime.wait_running(name):
        runtime.remove_version(app_id, target["version"])
        raise HTTPException(409, f"v{target['version']} did not start")
    runtime.set_routes(app_id, [{"version": target["version"], "port": spec.port, "weight": 100, "role": "stable"}],
                       probe_paths=_probe_paths(app_id))
    runtime.remove_version(app_id, current)
    store.update_app(app_id, version=target["version"], status="running", detail=f"Rolled back from v{current} to v{target['version']}")
    store.insert("deployments", app_id=app_id, version=target["version"], status="manual_rollback", finished_at=time.time(),
                 detail={**target["detail"], "from": current})
    store.add_event(app_id, "deploy", "medium", f"Rolled back to v{target['version']}", f"by {user.username}")
    return _view(store.get_app(app_id))


def _series(buckets: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    points = []
    for bucket in buckets:
        latencies = sorted(bucket["latency"])
        p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None
        points.append({"t": bucket["t"], "rps": round(bucket["requests"] / size, 2),
                       "error_rate": round(bucket["errors"] / bucket["requests"], 3) if bucket["requests"] else 0.0,
                       "p95": p95, "probe_errors": bucket["probe_errors"], "probes": bucket["probes"]})
    return points


@app.get("/api/apps/{app_id}/traffic")
def traffic(app_id: AppId, user: User) -> dict[str, Any]:
    """Per-version traffic, the edge cache per region, and the navigation the router has learned."""
    _owned(app_id, user)
    metrics = runtime.router_metrics(app_id)
    if not metrics:
        return {"available": False}
    size = metrics.get("bucket_seconds", 5)
    weights = {b["name"]: {"weight": b["weight"], "role": b.get("role")} for b in metrics["routes"].get("backends", [])}
    log = metrics.get("log", [])
    real = [e for e in log if not e.get("load")]
    regions: dict[str, dict[str, Any]] = {}
    for region, data in metrics.get("cache", {}).get("regions", {}).items():
        hits, misses = data.get("hits", 0), data.get("misses", 0)
        regions[region] = {**data, "hit_rate": round(hits / (hits + misses), 3) if hits + misses else None,
                           "visitors": len({e["client"] for e in real if e["region"] == region})}
    paths: dict[str, int] = {}
    for entry in real:
        paths[entry["path"]] = paths.get(entry["path"], 0) + 1
    edge = sum(1 for e in log if e["backend"] == "edge")
    return {
        "available": True, "time": metrics["time"], "bucket_seconds": size,
        "versions": {name: {"series": _series(buckets, size)[-120:], **weights.get(name, {"weight": 0, "role": "retired"})}
                     for name, buckets in metrics.get("backends", {}).items()},
        "cache": {"bytes": metrics.get("cache", {}).get("bytes", 0), "regions": regions,
                  "served_from_edge": edge, "requests": len(log)},
        "top_paths": [{"path": p, "count": c} for p, c in sorted(paths.items(), key=lambda kv: -kv[1])[:10]],
        "predictions": metrics.get("transitions", [])[:15],
    }


@app.get("/api/apps/{app_id}/incidents")
def incidents(app_id: AppId, user: User) -> list[dict[str, Any]]:
    _owned(app_id, user)
    return store.rows("incidents", app_id, 20)


# ---------------------------------------------------------------- routes: managed database


@app.get("/api/apps/{app_id}/database")
def database_status(app_id: AppId, user: User) -> dict[str, Any]:
    record = _owned(app_id, user)
    enabled = bool((record["database"] or {}).get("enabled"))
    return {"enabled": enabled, **(database.status(runtime, store, app_id) if enabled else {})}


@app.post("/api/apps/{app_id}/database")
def database_enable(app_id: AppId, user: SessionUser, background: BackgroundTasks) -> dict[str, Any]:
    record = _owned(app_id, user)
    if (record["database"] or {}).get("enabled"):
        raise HTTPException(409, "This app already has a database")
    if record["status"] in BUSY | {"canary"}:
        raise HTTPException(409, "Wait for the current deployment to finish")
    try:
        url = database.enable(runtime, app_id)
    except Exception as exc:
        raise HTTPException(502, f"The database could not be created: {exc}") from exc
    store.update_app(app_id, database={"enabled": True, "since": time.time()}, env={**(record["env"] or {}), "DATABASE_URL": url})
    store.add_event(app_id, "database", "info", "PostgreSQL database created", "DATABASE_URL was added; redeploying")
    store.update_app(app_id, status="queued", detail="Redeploying with DATABASE_URL")
    background.add_task(deploy, app_id)
    return {"enabled": True}


@app.post("/api/apps/{app_id}/database/optimize")
def database_optimize(app_id: AppId, user: SessionUser) -> dict[str, Any]:
    record = _owned(app_id, user)
    if not (record["database"] or {}).get("enabled"):
        raise HTTPException(409, "This app has no database")
    return {"actions": database.optimise(runtime, store, app_id)}


# ---------------------------------------------------------------- routes: load tests


class LoadTestRequest(Strict):
    max_users: int = Field(default=50, ge=1, le=loadtest.MAX_VIRTUAL_USERS)


_load_running: set[str] = set()


@app.get("/api/apps/{app_id}/loadtest/model")
def loadtest_model(app_id: AppId, user: User) -> dict[str, Any]:
    _owned(app_id, user)
    return loadtest.model(runtime.router_metrics(app_id))


@app.get("/api/apps/{app_id}/loadtests")
def loadtests(app_id: AppId, user: User) -> list[dict[str, Any]]:
    _owned(app_id, user)
    return store.rows("loadtests", app_id, 10)


def _run_load_test(app_id: str, test_id: int, test_plan: dict[str, Any]) -> None:
    try:
        result = loadtest.run(runtime, app_id, test_plan)
        store.update_row("loadtests", test_id, status="finished", finished_at=time.time(), result=result)
        store.add_event(app_id, "loadtest", "info", "Load test finished", result["verdict"])
    except Exception as exc:
        store.update_row("loadtests", test_id, status="failed", finished_at=time.time(), result={"error": str(exc)[:1000]})
    finally:
        _load_running.discard(app_id)


@app.post("/api/apps/{app_id}/loadtests", status_code=202)
def start_load_test(app_id: AppId, body: LoadTestRequest, user: SessionUser, background: BackgroundTasks) -> dict[str, Any]:
    record = _owned(app_id, user)
    if record["status"] not in ("running", "canary"):
        raise HTTPException(409, "Start the app before load testing it")
    if app_id in _load_running:
        raise HTTPException(409, "A load test is already running for this app")
    learned = loadtest.model(runtime.router_metrics(app_id))
    if not learned["requests"]:
        raise HTTPException(409, "No real traffic has been seen yet: open the app and use it a little first")
    test_plan = loadtest.plan(learned, body.max_users)
    _load_running.add(app_id)
    test_id = store.insert("loadtests", app_id=app_id, status="running", plan={**test_plan, "learned_from": learned["requests"]})
    background.add_task(_run_load_test, app_id, test_id, test_plan)
    return {"id": test_id, "status": "running", "plan": test_plan}


@app.get("/api/apps/{app_id}/loadtest/k6")
def loadtest_k6(app_id: AppId, user: User, max_users: int = Query(50, ge=1, le=loadtest.MAX_VIRTUAL_USERS)) -> Response:
    record = _owned(app_id, user)
    learned = loadtest.model(runtime.router_metrics(app_id))
    if not learned["requests"]:
        raise HTTPException(409, "No real traffic has been seen yet")
    base = f"http://{config.PUBLIC_HOST}:{record['host_port']}"
    return Response(loadtest.k6_script(learned, base, max_users), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{record["name"]}-loadtest.js"'})


# ---------------------------------------------------------------- autopilot


def _autopilot() -> None:
    """Background loop: detect error spikes on running apps (with root-cause analysis) and tune databases."""
    last_incident: dict[str, float] = {}
    last_optimise = last_sweep = 0.0
    while True:
        time.sleep(10)
        try:
            if time.time() - last_sweep > 600:
                last_sweep = time.time()
                with _deploying_lock:
                    known = {record["id"] for record in store.list_apps()} | _deploying
                runtime.sweep(known)
            optimise = time.time() - last_optimise > 30
            if optimise:
                last_optimise = time.time()
            for record in store.list_apps():
                app_id, version = record["id"], record["version"]
                if record["status"] != "running" or not version:
                    continue
                if optimise and (record["database"] or {}).get("enabled"):
                    database.optimise(runtime, store, app_id)
                if time.time() - last_incident.get(app_id, 0) < 600:
                    continue
                metrics = runtime.router_metrics(app_id)
                recent = canary.window(metrics, f"v{version}", time.time() - 60)
                if recent["requests"] >= 10 and recent["error_rate"] >= 0.2:
                    last_incident[app_id] = time.time()
                    folder = pipeline.versions_dir(app_dir(app_id))
                    current = folder / str(version)
                    earlier = sorted((int(p.name) for p in folder.iterdir() if p.name.isdigit() and int(p.name) < version), reverse=True) \
                        if folder.is_dir() else []
                    previous = folder / str(earlier[0]) if earlier else None
                    changed = pipeline.changes(previous, current) if current.is_dir() else {"added": [], "modified": [], "removed": []}
                    report = rca.analyse(kind="error_spike", version=version, logs=runtime.logs(app_id, version, tail=400, since=time.time() - 180),
                                         current=current, previous=previous, changed=changed["added"] + changed["modified"],
                                         metrics=metrics, since=time.time() - 600,
                                         symptom=f"{recent['error_rate']:.0%} of {recent['requests']} requests failed in the last minute")
                    _record_incident(app_id, report)
        except Exception:  # keep the loop alive; problems show up as missing data, not a dead thread
            continue


threading.Thread(target=_autopilot, name="autopilot", daemon=True).start()
