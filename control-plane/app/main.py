"""OwnCloud control plane: host and run apps, with QuantumTrace analysis on every deployment.

Deploy pipeline: upload → migration analysis → QuantumTrace scan (optional gate) → detect runtime → build → run.
Every step is recorded in a shared event feed that other AI modules can read and write.
All routes except login and a minimal health check require an authenticated session (see security.py).
"""

import json
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from . import code_review, config, migration, quantum
from .aws_sources import SKIP_DIRS
from .runtime import GENERATED_DOCKERFILE, DeployError, Runtime, detect
from .security import SESSION_COOKIE, Admin, Guard, LoginLimiter, Sessions, client_id
from .store import Store
from .uploads import UploadError, safe_relative, write_sources

docs = {"docs_url": "/api/docs", "openapi_url": "/api/openapi.json"} if config.ENABLE_API_DOCS else {
    "docs_url": None, "redoc_url": None, "openapi_url": None,
}
app = FastAPI(title="OwnCloud control plane", version="0.2.0", **docs)
store = Store(config.DATA_DIR / "owncloud.db")
runtime = Runtime()
admin = Admin(config.DATA_DIR, config.ADMIN_PASSWORD)
sessions = Sessions(config.SESSION_TTL_SECONDS)
login_limiter = LoginLimiter()
app.add_middleware(Guard, sessions=sessions)

_deploying: set[str] = set()
_deploying_lock = threading.Lock()
_build_slots = threading.BoundedSemaphore(config.MAX_CONCURRENT_BUILDS)

BUSY = {"queued", "scanning", "building", "starting"}
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
HIDDEN_FILES = {GENERATED_DOCKERFILE}
HIDDEN_DIRS = SKIP_DIRS  # includes .owncloud (generated shims)

AppId = Annotated[str, PathParam(pattern=r"^[0-9a-f]{10}$")]

# A restart interrupts any deployment that was in progress.
for _record in store.list_apps():
    if _record["status"] in BUSY:
        store.update_app(_record["id"], status="failed", detail="Deployment interrupted by a control-plane restart. Redeploy the app.")


def app_dir(app_id: str) -> Path:
    return config.DATA_DIR / "apps" / app_id


def source_dir(app_id: str) -> Path:
    return app_dir(app_id) / "src"


def _view(app_record: dict[str, Any]) -> dict[str, Any]:
    """Reconcile the stored status with the live container state and add the public URL."""
    status = app_record["status"]
    if status not in BUSY | {"blocked", "failed"}:
        state = runtime.state(app_record["id"])
        if state == "running":
            status = "running"
        elif state == "restarting":
            status = "restarting"
        elif state in ("exited", "dead", "created"):
            status = "stopped" if status == "stopped" else "crashed"
        elif state is None:
            status = "missing"
    url = f"http://{config.PUBLIC_HOST}:{app_record['host_port']}" if app_record["host_port"] else None
    view = {**app_record, "status": status, "url": url if status == "running" else None}
    # Values can be secrets: expose only the variable names.
    view["env_keys"] = sorted(view.pop("env") or {})
    if view["migration"]:
        view["migration"] = {**view["migration"], "env": sorted(view["migration"]["env"])}
    return view


def _get_or_404(app_id: str) -> dict[str, Any]:
    record = store.get_app(app_id)
    if record is None:
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


def _deploy(app_id: str) -> None:
    record = store.get_app(app_id)
    if record is None:
        return
    root = source_dir(app_id)
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
        if record["enforce_gate"] and (critical or summary["status"] == "unavailable"):
            reason = (
                f"Deployment blocked: {critical} quantum-vulnerable finding(s)."
                if critical else "Deployment blocked: the code could not be analysed."
            )
            store.update_app(app_id, status="blocked", detail=reason)
            store.add_event(app_id, "gate", "high", "Deployment blocked by quantum gate", reason)
            return

        store.update_app(app_id, status="building", detail=f"Building a {spec.name} image")
        store.add_event(app_id, "deploy", "info", "Build started", f"Runtime: {spec.name}")
        image = runtime.build(app_id, root, spec)

        store.update_app(app_id, status="starting", detail="Starting container", image=image)
        host_port = runtime.run(app_id, image, spec, env)
        store.update_app(app_id, status="running", detail=None, host_port=host_port)
        store.add_event(app_id, "deploy", "info", "App is running", f"http://{config.PUBLIC_HOST}:{host_port}")
    except DeployError as exc:
        store.update_app(app_id, status="failed", detail=str(exc))
        store.add_event(app_id, "deploy", "high", "Deployment failed", str(exc))
    except Exception as exc:  # Docker or filesystem errors: report them on the app instead of losing them
        store.update_app(app_id, status="failed", detail=f"Unexpected error: {exc}")
        store.add_event(app_id, "deploy", "high", "Deployment failed", repr(exc))


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


class Login(BaseModel):
    password: str = Field(min_length=1, max_length=256)


# ---------------------------------------------------------------- routes: auth


@app.post("/api/auth/login")
def login(body: Login, request: Request, response: Response) -> dict[str, bool]:
    client = client_id(request)
    wait = login_limiter.retry_after(client)
    if wait:
        raise HTTPException(429, "Too many failed attempts; try again later", headers={"Retry-After": str(wait)})
    if not admin.verify(body.password):
        login_limiter.failed(client)
        raise HTTPException(401, "Incorrect password")
    login_limiter.succeeded(client)
    response.set_cookie(
        SESSION_COOKIE, sessions.create(), max_age=config.SESSION_TTL_SECONDS, path="/api",
        httponly=True, samesite="strict", secure=config.COOKIE_SECURE,
    )
    return {"authenticated": True}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    sessions.revoke(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/api", httponly=True, samesite="strict", secure=config.COOKIE_SECURE)
    return {"authenticated": False}


@app.get("/api/auth/me")
def me() -> dict[str, bool]:
    return {"authenticated": True}  # the guard already rejected anonymous requests


# ---------------------------------------------------------------- routes: platform


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/system")
def system() -> dict[str, Any]:
    try:
        quantumtrace = httpx.get(f"{config.QUANTUMTRACE_URL}/openapi.json", timeout=2).is_success
    except httpx.HTTPError:
        quantumtrace = False
    return {"status": "ok", "docker": runtime.ping(), "quantumtrace": quantumtrace}


@app.get("/api/apps")
def list_apps() -> list[dict[str, Any]]:
    return [_view(record) for record in store.list_apps()]


@app.post("/api/apps", status_code=201)
async def create_app(
    background: BackgroundTasks,
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
    uploaded = await _read_uploads(files)
    record = store.create_app(name, enforce_gate, variables)
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
async def analyze_migration(files: list[UploadFile] = File(...)) -> dict[str, Any]:
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
def get_app(app_id: AppId) -> dict[str, Any]:
    return _view(_get_or_404(app_id))


@app.post("/api/apps/{app_id}/redeploy")
def redeploy(app_id: AppId, background: BackgroundTasks) -> dict[str, Any]:
    _get_or_404(app_id)
    store.update_app(app_id, status="queued", detail=None)
    background.add_task(deploy, app_id)
    return _view(store.get_app(app_id))


@app.post("/api/apps/{app_id}/stop")
def stop(app_id: AppId) -> dict[str, Any]:
    _get_or_404(app_id)
    runtime.stop(app_id)
    store.update_app(app_id, status="stopped")
    store.add_event(app_id, "deploy", "info", "App stopped")
    return _view(store.get_app(app_id))


@app.post("/api/apps/{app_id}/start")
def start(app_id: AppId) -> dict[str, Any]:
    _get_or_404(app_id)
    try:
        runtime.start(app_id)
    except DeployError as exc:
        raise HTTPException(409, str(exc)) from exc
    store.update_app(app_id, status="running")
    store.add_event(app_id, "deploy", "info", "App started")
    return _view(store.get_app(app_id))


@app.delete("/api/apps/{app_id}", status_code=204)
def delete(app_id: AppId) -> None:
    _get_or_404(app_id)
    runtime.remove_container(app_id)
    runtime.remove_image(app_id)
    shutil.rmtree(app_dir(app_id), ignore_errors=True)
    store.delete_app(app_id)
    store.add_event(app_id, "deploy", "info", "App deleted")


@app.get("/api/apps/{app_id}/logs")
def logs(app_id: AppId, tail: int = Query(200, ge=1, le=2000)) -> dict[str, str]:
    _get_or_404(app_id)
    return {"logs": runtime.logs(app_id, tail)}


@app.get("/api/apps/{app_id}/stats")
def stats(app_id: AppId) -> dict[str, Any] | None:
    _get_or_404(app_id)
    return runtime.stats(app_id)


@app.get("/api/apps/{app_id}/scan")
def scan_result(app_id: AppId) -> dict[str, Any]:
    _get_or_404(app_id)
    path = app_dir(app_id) / "scan.json"
    if not path.is_file():
        raise HTTPException(404, "No QuantumTrace result for this app")
    return json.loads(path.read_text())


@app.get("/api/events")
def events(
    app_id: Annotated[str | None, Query(pattern=r"^[0-9a-f]{10}$")] = None,
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return store.list_events(app_id, limit)


# ---------------------------------------------------------------- routes: editor


@app.get("/api/apps/{app_id}/files")
def list_files(app_id: AppId) -> dict[str, Any]:
    _get_or_404(app_id)
    return {"files": _list_sources(app_id)}


@app.get("/api/apps/{app_id}/file")
def read_file(app_id: AppId, path: str = Query(..., max_length=300)) -> dict[str, Any]:
    _get_or_404(app_id)
    target, clean = _source_file(app_id, path)
    content = _read_text(target)
    if content is None:
        raise HTTPException(415, "Only UTF-8 text files up to 1 MB can be opened")
    return {"path": clean, "content": content, "language": code_review.language_of(clean)}


@app.put("/api/apps/{app_id}/file")
def write_file(app_id: AppId, body: FileContent, path: str = Query(..., max_length=300)) -> dict[str, Any]:
    _get_or_404(app_id)
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
def analyse_app(app_id: AppId) -> dict[str, Any]:
    """Security review and QuantumTrace findings for every source file, on the editor's severity scale."""
    record = _get_or_404(app_id)
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


@app.post("/api/apps/{app_id}/analysis/file")
def analyse_buffer(app_id: AppId, body: BufferAnalysis) -> dict[str, Any]:
    """Findings for one (possibly unsaved) file, for live highlighting while editing."""
    record = _get_or_404(app_id)
    _, clean = _source_file(app_id, body.path, must_exist=False)
    findings = code_review.review(clean, body.content)
    quantum_findings, quantum_status = _quantum_for([quantum.source_input(clean, body.content)], record["name"])
    return {"findings": _ordered(findings + quantum_findings), "quantum": quantum_status}
