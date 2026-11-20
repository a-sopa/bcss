"""Detect how to run an app, then build and run it as a Docker container."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docker
from docker.errors import APIError, BuildError, ImageNotFound, NotFound

from . import config
from .aws_sources import LambdaFunction, iter_text_files, lambda_functions, procfile_web

LABEL = "owncloud.app"
GENERATED_DOCKERFILE = "Dockerfile.owncloud"
PYTHON_ENTRYPOINTS = ("main.py", "app.py", "server.py")
SHIMS = Path(__file__).parent / "shims"

PYTHON_DOCKERFILE = """\
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT=8080
COPY . .
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi
EXPOSE 8080
CMD ["python", "{entry}"]
"""

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
        return RuntimeSpec("python", 8080, PYTHON_DOCKERFILE.format(entry=entry), label=f"Python · {entry}")
    if (root / "index.html").is_file():
        return RuntimeSpec("static", 80, STATIC_DOCKERFILE, label="Static site")
    raise DeployError(
        "Could not detect how to run this app. Add a Dockerfile, a Lambda template (template.yaml / serverless.yml), "
        "a Procfile, a package.json, a main.py/app.py, or an index.html at the top level."
    )


class Runtime:
    def __init__(self) -> None:
        self.client = docker.from_env()

    @staticmethod
    def container_name(app_id: str) -> str:
        return f"owncloud-app-{app_id}"

    @staticmethod
    def image_tag(app_id: str) -> str:
        return f"owncloud/app-{app_id}:latest"

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:
            return False

    def build(self, app_id: str, root: Path, spec: RuntimeSpec) -> str:
        tag = self.image_tag(app_id)
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

    def run(self, app_id: str, image: str, spec: RuntimeSpec, env: dict[str, str] | None = None) -> int:
        """Start the app container and return the host port it is published on."""
        self.remove_container(app_id)
        container_port = f"{spec.port}/tcp"
        container = self.client.containers.run(
            image,
            detach=True,
            name=self.container_name(app_id),
            labels={LABEL: app_id},
            environment={**(env or {}), "PORT": str(spec.port)},
            ports={container_port: (config.BIND_HOST, None)},
            mem_limit=config.APP_MEMORY,
            nano_cpus=int(config.APP_CPUS * 1e9),
            pids_limit=256,
            security_opt=["no-new-privileges"],
            cap_drop=["NET_RAW", "MKNOD", "AUDIT_WRITE", "SYS_CHROOT", "SETFCAP"],
            network=self._app_network(),
            restart_policy={"Name": "on-failure", "MaximumRetryCount": 3},
        )
        container.reload()
        bindings = container.ports.get(container_port) or []
        if not bindings:
            raise DeployError("The container started but no port was published")
        return int(bindings[0]["HostPort"])

    def _app_network(self) -> str:
        """A bridge network without inter-container traffic, so one hosted app cannot attack another."""
        try:
            self.client.networks.get(config.APP_NETWORK)
        except NotFound:
            self.client.networks.create(
                config.APP_NETWORK, driver="bridge",
                options={"com.docker.network.bridge.enable_icc": "false"}, labels={LABEL: "network"},
            )
        return config.APP_NETWORK

    def _container(self, app_id: str):
        try:
            return self.client.containers.get(self.container_name(app_id))
        except NotFound:
            return None

    def state(self, app_id: str) -> str | None:
        container = self._container(app_id)
        return container.status if container else None

    def start(self, app_id: str) -> None:
        container = self._container(app_id)
        if container is None:
            raise DeployError("Container not found; redeploy the app")
        container.start()

    def stop(self, app_id: str) -> None:
        container = self._container(app_id)
        if container is not None:
            container.stop(timeout=5)

    def remove_container(self, app_id: str) -> None:
        container = self._container(app_id)
        if container is not None:
            container.remove(force=True)

    def remove_image(self, app_id: str) -> None:
        try:
            self.client.images.remove(self.image_tag(app_id), force=True)
        except ImageNotFound:
            pass

    def logs(self, app_id: str, tail: int = 200) -> str:
        container = self._container(app_id)
        if container is None:
            return ""
        return container.logs(tail=tail, timestamps=False).decode("utf-8", errors="replace")

    def stats(self, app_id: str) -> dict[str, Any] | None:
        container = self._container(app_id)
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
