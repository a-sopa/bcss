"""Understand apps exported from AWS: Lambda (SAM, Serverless Framework, plain handlers) and Elastic Beanstalk."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".aws-sam", ".serverless", ".owncloud"}


class _SafeCloudFormationLoader(yaml.SafeLoader):
    """SafeLoader that tolerates CloudFormation tags such as !Ref and !GetAtt."""


def _any_tag(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_SafeCloudFormationLoader.add_multi_constructor("!", _any_tag)


MAX_CONFIG_BYTES = 256 * 1024


def load_yaml(path: Path) -> Any:
    if path.stat().st_size > MAX_CONFIG_BYTES:
        return {}
    try:
        return yaml.load(path.read_text(errors="ignore"), Loader=_SafeCloudFormationLoader) or {}
    except (yaml.YAMLError, RecursionError):
        return {}


def _scalar(value: Any) -> str | None:
    """Only scalars are used from configuration files; nested (possibly aliased) structures are ignored."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)[:4096]
    return None


@dataclass
class LambdaFunction:
    source: str  # where it was found: "template.yaml", "serverless.yml" or a handler file
    name: str
    handler: str  # "<module path>.<function>", relative to code_dir
    language: str  # "python", "node" or "other"
    runtime: str | None  # AWS runtime identifier, e.g. "python3.12"
    code_dir: str = "."
    env: dict[str, str] = field(default_factory=dict)
    triggers: list[str] = field(default_factory=list)


def _language(runtime: str | None, handler_file: str | None = None) -> str:
    value = (_scalar(runtime) or "").lower()
    if value.startswith("python"):
        return "python"
    if value.startswith("nodejs"):
        return "node"
    if value:
        return "other"
    if handler_file and handler_file.endswith(".py"):
        return "python"
    return "node" if handler_file else "other"


def _env(values: Any) -> dict[str, str]:
    if not isinstance(values, dict):
        return {}
    env = {}
    for key, value in list(values.items())[:200]:
        key, value = _scalar(key), "" if value is None else _scalar(value)
        if key is not None and value is not None:
            env[key] = value
    return env


def _code_dir(root: Path, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return "."
    path = PurePosixPath(value.strip().replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        return "."
    relative = path.as_posix().strip("/") or "."
    return relative if (root / relative).is_dir() else "."


def _sam_functions(root: Path) -> list[LambdaFunction]:
    for filename in ("template.yaml", "template.yml", "template.json"):
        path = root / filename
        if not path.is_file():
            continue
        if path.stat().st_size > MAX_CONFIG_BYTES:
            return []
        try:
            doc = json.loads(path.read_text()) if filename.endswith(".json") else load_yaml(path)
        except ValueError:
            return []
        if not isinstance(doc, dict):
            return []
        defaults = (doc.get("Globals") or {}).get("Function") or {}
        functions = []
        for logical_id, resource in (doc.get("Resources") or {}).items():
            if not isinstance(resource, dict) or resource.get("Type") not in ("AWS::Serverless::Function", "AWS::Lambda::Function"):
                continue
            props = resource.get("Properties") or {}
            handler = _scalar(props.get("Handler") or defaults.get("Handler"))
            if not handler:
                continue
            runtime = _scalar(props.get("Runtime") or defaults.get("Runtime"))
            env = {
                **_env((defaults.get("Environment") or {}).get("Variables")),
                **_env((props.get("Environment") or {}).get("Variables")),
            }
            events = props.get("Events") if isinstance(props.get("Events"), dict) else {}
            triggers = [
                event["Type"] for event in events.values()
                if isinstance(event, dict) and isinstance(event.get("Type"), str)
            ]
            functions.append(LambdaFunction(
                source=filename, name=str(logical_id), handler=str(handler), language=_language(runtime),
                runtime=runtime, code_dir=_code_dir(root, props.get("CodeUri") or defaults.get("CodeUri")),
                env=env, triggers=triggers,
            ))
        return functions
    return []


def _serverless_functions(root: Path) -> list[LambdaFunction]:
    for filename in ("serverless.yml", "serverless.yaml"):
        path = root / filename
        if not path.is_file():
            continue
        doc = load_yaml(path)
        if not isinstance(doc, dict):
            return []
        provider = doc.get("provider") or {}
        functions = []
        for name, fn in (doc.get("functions") or {}).items():
            if not isinstance(fn, dict) or not _scalar(fn.get("handler")):
                continue
            runtime = _scalar(fn.get("runtime") or provider.get("runtime"))
            events = fn.get("events") if isinstance(fn.get("events"), list) else []
            triggers = [str(next(iter(event))) for event in events if isinstance(event, dict) and event]
            functions.append(LambdaFunction(
                source=filename, name=str(name), handler=_scalar(fn["handler"]), language=_language(runtime),
                runtime=runtime, env={**_env(provider.get("environment")), **_env(fn.get("environment"))},
                triggers=["Api" if t in ("http", "httpApi") else t for t in triggers],
            ))
        return functions
    return []


PYTHON_HANDLER = re.compile(r"^def\s+(lambda_handler|handler)\s*\(\s*event\s*,\s*context", re.MULTILINE)
NODE_HANDLER = re.compile(
    r"(exports\.handler\s*=|module\.exports\.handler\s*=|export\s+(const|let|var)\s+handler\b|export\s+(async\s+)?function\s+handler\b)"
)


def _plain_handler(root: Path) -> list[LambdaFunction]:
    for path in sorted(root.glob("*.py")):
        match = PYTHON_HANDLER.search(path.read_text(errors="ignore"))
        if match:
            return [LambdaFunction(source=path.name, name=path.stem, handler=f"{path.stem}.{match.group(1)}",
                                   language="python", runtime=None)]
    for name in ("index", "handler", "app", "lambda"):
        for ext in (".mjs", ".js", ".cjs"):
            path = root / f"{name}{ext}"
            if path.is_file() and NODE_HANDLER.search(path.read_text(errors="ignore")):
                return [LambdaFunction(source=path.name, name=name, handler=f"{name}.handler", language="node", runtime=None)]
    return []


def lambda_functions(root: Path) -> list[LambdaFunction]:
    return _sam_functions(root) or _serverless_functions(root) or _plain_handler(root)


def procfile_web(root: Path) -> str | None:
    path = root / "Procfile"
    if not path.is_file():
        return None
    for line in path.read_text(errors="ignore").splitlines():
        if line.strip().startswith("web:"):
            return line.split(":", 1)[1].strip() or None
    return None


def is_beanstalk(root: Path) -> bool:
    return (root / ".ebextensions").is_dir() or (root / ".elasticbeanstalk").is_dir()


def _beanstalk_env(root: Path) -> tuple[dict[str, str], list[str]]:
    env: dict[str, str] = {}
    sources = []
    folder = root / ".ebextensions"
    if not folder.is_dir():
        return env, sources
    for path in sorted(folder.glob("*.config")):
        if path.stat().st_size > MAX_CONFIG_BYTES:
            continue
        text = path.read_text(errors="ignore")
        try:
            doc = json.loads(text)
        except ValueError:
            doc = load_yaml(path)
        settings = doc.get("option_settings") if isinstance(doc, dict) else None
        found = {}
        if isinstance(settings, dict):
            found = _env(settings.get("aws:elasticbeanstalk:application:environment"))
        elif isinstance(settings, list):
            found = _env({
                item["option_name"]: item.get("value", "")
                for item in settings[:200]
                if isinstance(item, dict)
                and item.get("namespace") == "aws:elasticbeanstalk:application:environment"
                and _scalar(item.get("option_name"))
            })
        if found:
            env.update(found)
            sources.append(f".ebextensions/{path.name}")
    return env, sources


def _dotenv(root: Path) -> dict[str, str]:
    path = root / ".env"
    if not path.is_file():
        return {}
    env = {}
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        env[key.strip()] = value.strip().strip("'\"")
    return env


def environment(root: Path, function: LambdaFunction | None) -> tuple[dict[str, str], list[str]]:
    """Environment variables declared by the AWS configuration, and the files they came from."""
    env: dict[str, str] = {}
    sources = []
    dotenv = _dotenv(root)
    if dotenv:
        env.update(dotenv)
        sources.append(".env")
    beanstalk, files = _beanstalk_env(root)
    env.update(beanstalk)
    sources += files
    if function and function.env:
        env.update(function.env)
        sources.append(function.source)
    return env, sources


def iter_text_files(root: Path, suffixes: set[str] | None = None, max_bytes: int = 1_000_000):
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in SKIP_DIRS for part in relative.parts):
            continue
        if suffixes is not None and path.suffix.lower() not in suffixes:
            continue
        if path.stat().st_size > max_bytes:
            continue
        try:
            yield relative.as_posix(), path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
