"""Detect how to run an app, then build and run it as a Docker container."""

import hashlib
import io
import json
import re
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docker
from docker.errors import APIError, BuildError, ImageNotFound, NotFound

from . import config
from .aws_sources import LambdaFunction, iter_text_files, lambda_functions, procfile_web

LABEL = "owncloud.app"
ROLE = "owncloud.role"  # router | version | database | loadtest | pipeline
VERSION_LABEL = "owncloud.version"
ROUTER_SOURCE = Path(__file__).parent / "router" / "router.py"
ROUTER_PORT = 8080
GENERATED_DOCKERFILE = "Dockerfile.owncloud"
PYTHON_ENTRYPOINTS = ("main.py", "app.py", "server.py")
SHIMS = Path(__file__).parent / "shims"

PYTHON_DOCKERFILE = """\
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT=8080
{dependencies}COPY . .
EXPOSE 8080
CMD ["python", "{entry}"]
"""

# Dependencies are installed before the code is copied, so code-only changes reuse the cached layer.
PYTHON_DEPENDENCIES = "COPY requirements.txt ./\nRUN pip install --no-cache-dir -r requirements.txt\n"

NODE_DOCKERFILE = """\
FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=8080
COPY package*.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY . .
EXPOSE 8080
CMD ["npm", "start"]
"""

STATIC_DOCKERFILE = """\
FROM nginx:1.27-alpine
COPY . /usr/share/nginx/html
EXPOSE 80
"""

# AWS Lambda: the function runs unchanged behind an HTTP shim that emulates API Gateway proxy events.
LAMBDA_PYTHON_DOCKERFILE = """\
FROM python:{version}-slim
ENV PYTHONUNBUFFERED=1 PORT=8080 OWNCLOUD_LAMBDA_HANDLER={handler} AWS_LAMBDA_FUNCTION_NAME={name}
COPY . /app
WORKDIR /app/{code_dir}
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi{extra}
EXPOSE 8080
CMD ["python", "/app/.owncloud/lambda_shim.py"]
"""

LAMBDA_NODE_DOCKERFILE = """\
FROM node:{version}-alpine
ENV NODE_ENV=production PORT=8080 OWNCLOUD_LAMBDA_HANDLER={handler} AWS_LAMBDA_FUNCTION_NAME={name}
COPY . /app
WORKDIR /app/{code_dir}
RUN if [ -f package.json ]; then npm install --omit=dev --no-audit --no-fund; fi{extra}
EXPOSE 8080
CMD ["node", "/app/.owncloud/lambda_shim.mjs"]
"""

# Elastic Beanstalk / Heroku style: a Procfile "web:" command, or EB's default application.py WSGI app.
PROCFILE_PYTHON_DOCKERFILE = """\
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT={port}
COPY . .
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi{extra}
EXPOSE {port}
CMD ["sh", "-c", {command}]
"""

PROCFILE_NODE_DOCKERFILE = """\
FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production PORT={port}
COPY . .
RUN if [ -f package.json ]; then npm install --omit=dev --no-audit --no-fund; fi
EXPOSE {port}
CMD ["sh", "-c", {command}]
"""

BEANSTALK_WSGI_COMMAND = "gunicorn --bind 0.0.0.0:$PORT application:application"


class DeployError(Exception):
    pass


@dataclass(frozen=True)
class RuntimeSpec:
    name: str
    port: int
    dockerfile: str | None  # None: use the app's own Dockerfile
    label: str = ""  # human-readable description of how the app runs
    files: dict[str, str] = field(default_factory=dict)  # extra files written into the build context


def _version(runtime: str | None, prefix: str, default: str) -> str:
    match = re.fullmatch(rf"{prefix}(\d+(?:\.\d+)?)(?:\.x)?", (runtime or "").lower())
    return match.group(1) if match else default


def _provided_sdk(root: Path, function: LambdaFunction) -> str:
    """Lambda runtimes ship the AWS SDK; install it when the code relies on that."""
    code = root / function.code_dir
    if function.language == "python":
        uses_boto3 = any(re.search(r"^\s*(import|from)\s+boto3", text, re.MULTILINE) for _, text in iter_text_files(code, {".py"}))
        requirements = (code / "requirements.txt").read_text(errors="ignore") if (code / "requirements.txt").is_file() else ""
        return " && pip install --no-cache-dir boto3" if uses_boto3 and "boto3" not in requirements.lower() else ""
    packages = sorted({
        match for _, text in iter_text_files(code, {".js", ".mjs", ".cjs"})
        for match in re.findall(r"""['"](@aws-sdk/[a-z0-9-]+)['"]""", text)
    })
    declared = ""
    if (code / "package.json").is_file():
        declared = (code / "package.json").read_text(errors="ignore")
    missing = [p for p in packages if f'"{p}"' not in declared]
    return f" && npm install --no-save --no-audit --no-fund {' '.join(missing)}" if missing else ""


HANDLER_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,200}\.[A-Za-z_$][A-Za-z0-9_$]{0,100}$")
CODE_DIR_PATTERN = re.compile(r"^(\.|[A-Za-z0-9_][A-Za-z0-9_./-]{0,200})$")


def _lambda_spec(root: Path, function: LambdaFunction) -> RuntimeSpec:
    # These values come from user-supplied templates and end up in a Dockerfile: allow only safe characters.
    if not HANDLER_PATTERN.match(function.handler) or ".." in function.handler:
        raise DeployError(f"Unsupported Lambda handler name: {function.handler[:80]!r}")
    if not CODE_DIR_PATTERN.match(function.code_dir) or ".." in function.code_dir:
        raise DeployError("Unsupported Lambda CodeUri")
    values = {
        "handler": function.handler,
        "name": re.sub(r"[^A-Za-z0-9-_]", "-", function.name),
        "code_dir": function.code_dir,
        "extra": _provided_sdk(root, function),
    }
    if function.language == "python":
        version = _version(function.runtime, "python", "3.12")
        return RuntimeSpec(
            "lambda-python", 8080, LAMBDA_PYTHON_DOCKERFILE.format(version=version, **values),
            label=f"AWS Lambda · Python {version} · {function.handler}",
            files={".owncloud/lambda_shim.py": (SHIMS / "lambda_shim.py").read_text()},
        )
    if function.language == "node":
        version = _version(function.runtime, "nodejs", "22")
        return RuntimeSpec(
            "lambda-node", 8080, LAMBDA_NODE_DOCKERFILE.format(version=version, **values),
            label=f"AWS Lambda · Node.js {version} · {function.handler}",
            files={".owncloud/lambda_shim.mjs": (SHIMS / "lambda_shim.mjs").read_text()},
        )
    raise DeployError(
        f"Lambda runtime {function.runtime!r} is not supported yet. Python and Node.js functions run unchanged; "
        "other runtimes can be deployed with a Dockerfile."
    )


def _command_port(command: str) -> int:
    """Procfiles often hard-code the port (EB uses 8000); otherwise the app reads $PORT."""
    match = re.search(r"(?:--bind|-b)[ =]\S*?:(\d+)|--port[ =](\d+)|\s-p\s+(\d+)", command)
    return int(next(g for g in match.groups() if g)) if match else 8080


def _process_spec(root: Path, command: str, label: str, extra: str = "") -> RuntimeSpec:
    if len(command) > 1000 or any(ord(c) < 32 for c in command):
        raise DeployError("The Procfile web command contains unsupported characters")
    port = _command_port(command)
    if (root / "package.json").is_file() and not any(root.glob("*.py")):
        dockerfile = PROCFILE_NODE_DOCKERFILE.format(port=port, command=json.dumps(command))
        return RuntimeSpec("procfile-node", port, dockerfile, label=label)
    dockerfile = PROCFILE_PYTHON_DOCKERFILE.format(port=port, command=json.dumps(command), extra=extra)
    return RuntimeSpec("procfile-python", port, dockerfile, label=label)


def detect(root: Path) -> RuntimeSpec:
    dockerfile = root / "Dockerfile"
    if dockerfile.is_file():
        match = re.search(r"^\s*EXPOSE\s+(\d+)", dockerfile.read_text(errors="ignore"), re.MULTILINE | re.IGNORECASE)
        return RuntimeSpec("docker", int(match.group(1)) if match else 8080, None, label="Dockerfile")
    functions = lambda_functions(root)
    if functions:
        return _lambda_spec(root, functions[0])
    command = procfile_web(root)
    if command:
        return _process_spec(root, command, f"Procfile · {command}")
    if (root / "package.json").is_file():
        return RuntimeSpec("node", 8080, NODE_DOCKERFILE, label="Node.js · npm start")
    if (root / "application.py").is_file():
        requirements = (root / "requirements.txt").read_text(errors="ignore") if (root / "requirements.txt").is_file() else ""
        extra = "" if "gunicorn" in requirements.lower() else " && pip install --no-cache-dir gunicorn"
        return _process_spec(root, BEANSTALK_WSGI_COMMAND, "Elastic Beanstalk · application.py (WSGI)", extra)
    top_level_py = sorted(p.name for p in root.glob("*.py"))
    entry = next((name for name in PYTHON_ENTRYPOINTS if name in top_level_py), None)
    if entry is None and len(top_level_py) == 1:
        entry = top_level_py[0]
    if entry:
        dependencies = PYTHON_DEPENDENCIES if (root / "requirements.txt").is_file() else ""
        return RuntimeSpec("python", 8080, PYTHON_DOCKERFILE.format(entry=entry, dependencies=dependencies), label=f"Python · {entry}")
    if (root / "index.html").is_file():
        return RuntimeSpec("static", 80, STATIC_DOCKERFILE, label="Static site")
    raise DeployError(
        "Could not detect how to run this app. Add a Dockerfile, a Lambda template (template.yaml / serverless.yml), "
        "a Procfile, a package.json, a main.py/app.py, or an index.html at the top level."
    )


class Runtime:
    """Each app: a private network, a router container (the public entry point, stable across versions)
    and one container per running version. The control plane talks to routers through the Docker API only."""

    def __init__(self) -> None:
        self.client = docker.from_env()
        self._router_image: str | None = None

    # ------------------------------------------------------------ names

    @staticmethod
    def network_name(app_id: str) -> str:
        return f"owncloud-net-{app_id}"

    @staticmethod
    def router_name(app_id: str) -> str:
        return f"owncloud-app-{app_id}"

    @staticmethod
    def version_name(app_id: str, version: int) -> str:
        return f"owncloud-app-{app_id}-v{version}"

    @staticmethod
    def image_tag(app_id: str, version: int) -> str:
        return f"owncloud/app-{app_id}:v{version}"

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:
            return False

    # ------------------------------------------------------------ images

    def build(self, app_id: str, root: Path, spec: RuntimeSpec, version: int) -> str:
        tag = self.image_tag(app_id, version)
        options: dict[str, Any] = {"path": str(root), "tag": tag, "rm": True, "forcerm": True, "labels": {LABEL: app_id}}
        for relative, content in spec.files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        if spec.dockerfile:
            (root / GENERATED_DOCKERFILE).write_text(spec.dockerfile)
            options["dockerfile"] = GENERATED_DOCKERFILE
        try:
            self.client.images.build(**options)
        except BuildError as exc:
            lines = [chunk.get("stream", "") or chunk.get("error", "") for chunk in exc.build_log]
            tail = "".join(lines).strip().splitlines()[-8:]
            raise DeployError("Build failed:\n" + "\n".join(tail)) from exc
        except APIError as exc:
            raise DeployError(f"Build failed: {exc.explanation}") from exc
        return tag

    def router_image(self) -> str:
        """The router image, rebuilt whenever router.py changes."""
        source = ROUTER_SOURCE.read_bytes()
        tag = f"owncloud/router:{hashlib.sha256(source).hexdigest()[:12]}"
        if self._router_image == tag:
            return tag
        try:
            self.client.images.get(tag)
        except ImageNotFound:
            dockerfile = (
                "FROM python:3.12-slim\nCOPY router.py /router.py\nRUN mkdir /config\n"
                f"USER nobody\nEXPOSE {ROUTER_PORT}\nCMD [\"python\", \"-u\", \"/router.py\"]\n"
            ).encode()
            context = io.BytesIO()
            with tarfile.open(fileobj=context, mode="w") as archive:
                for name, data in (("Dockerfile", dockerfile), ("router.py", source)):
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
            context.seek(0)
            self.client.images.build(fileobj=context, custom_context=True, tag=tag, rm=True, labels={LABEL: "router"})
        self._router_image = tag
        return tag

    # ------------------------------------------------------------ containers

    def _get(self, name: str):
        try:
            return self.client.containers.get(name)
        except NotFound:
            return None

    def ensure_network(self, app_id: str) -> str:
        """A private network per app: its router, versions and database talk; other apps cannot reach it."""
        name = self.network_name(app_id)
        try:
            self.client.networks.get(name)
        except NotFound:
            self.client.networks.create(name, driver="bridge", labels={LABEL: app_id})
        return name

    def _limits(self) -> dict[str, Any]:
        return {
            "mem_limit": config.APP_MEMORY,
            "nano_cpus": int(config.APP_CPUS * 1e9),
            "pids_limit": 256,
            "security_opt": ["no-new-privileges"],
            "cap_drop": ["NET_RAW", "MKNOD", "AUDIT_WRITE", "SYS_CHROOT", "SETFCAP"],
        }

    def run_version(self, app_id: str, version: int, spec: RuntimeSpec, env: dict[str, str] | None) -> str:
        """Start one version of the app on its private network (not published on the host)."""
        name = self.version_name(app_id, version)
        existing = self._get(name)
        if existing is not None:
            existing.remove(force=True)
        self.client.containers.run(
            self.image_tag(app_id, version), detach=True, name=name,
            labels={LABEL: app_id, ROLE: "version", VERSION_LABEL: str(version)},
            environment={**(env or {}), "PORT": str(spec.port)},
            network=self.ensure_network(app_id),
            restart_policy={"Name": "on-failure", "MaximumRetryCount": 3},
            **self._limits(),
        )
        return name

    def wait_running(self, name: str, seconds: float = 20) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            container = self._get(name)
            if container is None:
                return False
            if container.status == "running":
                time.sleep(1.5)  # give the process a moment to bind its port or crash
                container.reload()
                return container.status == "running"
            if container.status in ("exited", "dead"):
                return False
            time.sleep(0.5)
        return False

    def wait_ready(self, app_id: str, version: int, port: int, path: str = "/", seconds: float = 120) -> bool:
        """Readiness: the version answers HTTP at all (whether its answers are good is the canary's job)."""
        router = self._get(self.router_name(app_id))
        if router is None:
            return False
        url = f"http://{self.version_name(app_id, version)}:{port}{path}"
        probe = ("import sys, urllib.request, urllib.error\n"
                 "try:\n    code = urllib.request.urlopen(sys.argv[1], timeout=3).status\n"
                 "except urllib.error.HTTPError as e:\n    code = e.code\n"
                 "except Exception:\n    code = 0\n"
                 "sys.exit(0 if code > 0 else 1)")
        deadline = time.time() + seconds
        while time.time() < deadline:
            container = self._get(self.version_name(app_id, version))
            if container is None or container.status in ("exited", "dead"):
                return False
            if router.exec_run(["python", "-c", probe, url]).exit_code == 0:
                return True
            time.sleep(1)
        return False

    def ensure_router(self, app_id: str) -> int:
        """Start the app's router if needed; returns its host port (the app's public address)."""
        name = self.router_name(app_id)
        router = self._get(name)
        if router is not None and router.labels.get(ROLE) != "router":
            router.remove(force=True)  # a container from before routers existed
            router = None
        if router is not None and router.image.tags and router.image.tags[0] != self.router_image():
            router.remove(force=True)  # router code changed
            router = None
        if router is None:
            router = self.client.containers.run(
                self.router_image(), detach=True, name=name,
                labels={LABEL: app_id, ROLE: "router"},
                ports={f"{ROUTER_PORT}/tcp": (config.BIND_HOST, None)},
                network=self.ensure_network(app_id),
                mem_limit="256m", nano_cpus=int(0.5e9), pids_limit=128,
                security_opt=["no-new-privileges"], cap_drop=["ALL"],
                restart_policy={"Name": "unless-stopped"},
            )
        elif router.status != "running":
            router.start()
        for _ in range(20):
            router.reload()
            bindings = router.ports.get(f"{ROUTER_PORT}/tcp") or []
            if bindings:
                return int(bindings[0]["HostPort"])
            time.sleep(0.25)
        raise DeployError("The router started but no port was published")

    def set_routes(self, app_id: str, backends: list[dict[str, Any]], **options: Any) -> None:
        """Tell the router where to send traffic: [{name, version, weight, role}]."""
        router = self._get(self.router_name(app_id))
        if router is None:
            raise DeployError("Router not found; redeploy the app")
        routes = {
            "backends": [
                {"name": f"v{b['version']}", "host": self.version_name(app_id, b["version"]), "port": b["port"],
                 "weight": b["weight"], "role": b["role"]}
                for b in backends
            ],
            **options,
        }
        data = json.dumps(routes).encode()
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as tar:
            info = tarfile.TarInfo("routes.json")
            info.size, info.mtime, info.mode = len(data), int(time.time()), 0o644
            tar.addfile(info, io.BytesIO(data))
        router.put_archive("/config", archive.getvalue())

    def router_metrics(self, app_id: str) -> dict[str, Any] | None:
        """The router's latest metrics, or None. The router rewrites the file every second and Docker reads
        size and content separately, so a read can catch a swap halfway: retry instead of failing."""
        router = self._get(self.router_name(app_id))
        if router is None or router.status != "running":
            return None
        for _ in range(4):
            try:
                stream, _ = router.get_archive("/tmp/metrics.json")
                with tarfile.open(fileobj=io.BytesIO(b"".join(stream))) as tar:
                    member = tar.extractfile("metrics.json")
                    return json.loads(member.read()) if member else None
            except (NotFound, APIError):
                return None
            except (ValueError, tarfile.TarError, KeyError):
                time.sleep(0.2)
        return None

    def remove_version(self, app_id: str, version: int, image: bool = False) -> None:
        container = self._get(self.version_name(app_id, version))
        if container is not None:
            container.remove(force=True)
        if image:
            try:
                self.client.images.remove(self.image_tag(app_id, version), force=True)
            except ImageNotFound:
                pass

    def _app_containers(self, app_id: str) -> list:
        return self.client.containers.list(all=True, filters={"label": f"{LABEL}={app_id}"})

    def state(self, app_id: str, version: int | None) -> str | None:
        """State of the app: its router and current version must both run."""
        router = self._get(self.router_name(app_id))
        current = self._get(self.version_name(app_id, version)) if version else None
        if router is None or router.labels.get(ROLE) != "router":
            return router.status if router is not None else None  # pre-router container, if any
        if current is None:
            return None
        if router.status == "running" and current.status == "running":
            return "running"
        if "restarting" in (router.status, current.status):
            return "restarting"
        return current.status if current.status != "running" else router.status

    def start(self, app_id: str, version: int | None) -> None:
        containers = [self._get(self.version_name(app_id, version)) if version else None, self._get(self.router_name(app_id))]
        if any(c is None for c in containers):
            raise DeployError("Containers not found; redeploy the app")
        for container in containers:
            container.start()

    def stop(self, app_id: str) -> None:
        for container in self._app_containers(app_id):
            if container.labels.get(ROLE) != "database" and container.status == "running":
                container.stop(timeout=5)

    def remove_app(self, app_id: str) -> None:
        """Containers, images, private network and database volume of an app."""
        for container in self._app_containers(app_id):
            container.remove(force=True, v=True)
        for image in self.client.images.list(filters={"label": f"{LABEL}={app_id}"}):
            try:
                self.client.images.remove(image.id, force=True)
            except (ImageNotFound, APIError):
                pass
        for volume in self.client.volumes.list(filters={"label": f"{LABEL}={app_id}"}):
            try:
                volume.remove(force=True)
            except APIError:
                pass
        try:
            self.client.networks.get(self.network_name(app_id)).remove()
        except (NotFound, APIError):
            pass

    def sweep(self, known: set[str]) -> int:
        """Remove everything labelled for an app that no longer exists (e.g. deleted while it was deploying)."""
        removed = 0

        def orphan(labels: dict | None) -> bool:
            owner = (labels or {}).get(LABEL)
            return bool(owner) and owner not in known and owner not in ("router", "network")

        for container in self.client.containers.list(all=True, filters={"label": LABEL}):
            if orphan(container.labels):
                container.remove(force=True, v=True)
                removed += 1
        for network in self.client.networks.list(filters={"label": LABEL}):
            if orphan(network.attrs.get("Labels")):
                try:
                    network.remove()
                except APIError:
                    pass
        for volume in self.client.volumes.list(filters={"label": LABEL}):
            if orphan(volume.attrs.get("Labels")):
                try:
                    volume.remove(force=True)
                except APIError:
                    pass
        for image in self.client.images.list(filters={"label": LABEL}):
            if orphan(image.labels):
                try:
                    self.client.images.remove(image.id, force=True)
                except (ImageNotFound, APIError):
                    pass
        return removed

    def logs(self, app_id: str, version: int | None, tail: int = 200, since: float | None = None) -> str:
        container = self._get(self.version_name(app_id, version)) if version else None
        if container is None:
            container = self._get(self.router_name(app_id))  # a pre-router app
        if container is None:
            return ""
        options: dict[str, Any] = {"tail": tail, "timestamps": False}
        if since:
            options["since"] = int(since)
        return container.logs(**options).decode("utf-8", errors="replace")

    def oom_killed(self, app_id: str, version: int) -> bool:
        container = self._get(self.version_name(app_id, version))
        return bool(container and container.attrs.get("State", {}).get("OOMKilled"))

    def run_task(self, app_id: str, image: str, command: list[str], role: str, timeout: int,
                 files: dict[str, bytes] | None = None, working_dir: str | None = None,
                 limits: dict[str, Any] | None = None) -> tuple[int, str, dict[str, bytes]]:
        """Run a one-off container on the app's network (tests, load tests). Returns (exit code, logs, /out files)."""
        name = f"owncloud-{role}-{app_id}"
        old = self._get(name)
        if old is not None:
            old.remove(force=True)
        container = self.client.containers.create(
            image, command=command, name=name, labels={LABEL: app_id, ROLE: role}, working_dir=working_dir,
            network=self.ensure_network(app_id), **(limits or self._limits()),
        )
        try:
            if files:
                archive = io.BytesIO()
                with tarfile.open(fileobj=archive, mode="w") as tar:
                    for path, data in files.items():
                        info = tarfile.TarInfo(path.lstrip("/"))
                        info.size, info.mode = len(data), 0o755
                        tar.addfile(info, io.BytesIO(data))
                container.put_archive("/", archive.getvalue())
            container.start()
            try:
                code = container.wait(timeout=timeout).get("StatusCode", 1)
            except Exception:
                container.kill()
                code = 124
            output = container.logs().decode("utf-8", errors="replace")
            results: dict[str, bytes] = {}
            try:
                stream, _ = container.get_archive("/tmp/out")
                with tarfile.open(fileobj=io.BytesIO(b"".join(stream))) as tar:
                    for member in tar.getmembers():
                        if member.isfile() and member.size < 20 * 1024 * 1024:
                            results[member.name.split("/", 1)[-1]] = tar.extractfile(member).read()
            except (NotFound, APIError):
                pass
            return code, output, results
        finally:
            container.remove(force=True)

    def stats(self, app_id: str, version: int | None) -> dict[str, Any] | None:
        container = self._get(self.version_name(app_id, version)) if version else None
        if container is None or container.status != "running":
            return None
        raw = container.stats(stream=False)
        cpu, pre = raw["cpu_stats"], raw["precpu_stats"]
        cpu_delta = cpu["cpu_usage"]["total_usage"] - pre.get("cpu_usage", {}).get("total_usage", 0)
        system_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
        cpus = cpu.get("online_cpus") or 1
        memory = raw.get("memory_stats", {})
        return {
            "cpu_percent": round(cpu_delta / system_delta * cpus * 100, 2) if system_delta > 0 else 0.0,
            "memory_bytes": memory.get("usage", 0),
            "memory_limit_bytes": memory.get("limit", 0),
        }

    def get(self, name: str):
        return self._get(name)
