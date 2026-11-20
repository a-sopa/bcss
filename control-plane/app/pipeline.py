"""Smart CI: snapshot every version, detect what changed, run only the tests that depend on it.

Test impact analysis:
- a dependency graph of the project from Python imports (AST) and JavaScript/TypeScript import/require;
- a test is selected when it changed or (transitively) imports a changed file;
- tests that failed in the previous pipeline are always re-run;
- dependency manifests, Dockerfiles or unknown files changing → the whole suite runs (conservative);
- documentation-only changes → no tests.
"""

import ast
import hashlib
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

from .aws_sources import SKIP_DIRS

KEEP_VERSIONS = 6
PY_TEST = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.py)$")
JS_TEST = re.compile(r"(^|/)([^/]+\.(test|spec)\.(js|mjs|cjs|ts|tsx|jsx)|__tests__/[^/]+\.(js|mjs|cjs|ts|tsx|jsx))$")
JS_IMPORT = re.compile(r"""(?:import\s[^'"]*?from\s*|import\s*\(?\s*|require\(\s*|export\s[^'"]*?from\s*)['"](\.{1,2}/[^'"]+)['"]""")
JS_EXTENSIONS = ("", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", "/index.js", "/index.ts")
CODE = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}
DOCS = {".md", ".txt", ".rst", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico"}
GENERATED = {"Dockerfile.owncloud"}


# ---------------------------------------------------------------- versions


def versions_dir(app_dir: Path) -> Path:
    return app_dir / "versions"


def snapshot(app_dir: Path, source: Path, version: int) -> Path:
    """Copy the source as it is deployed now; keep the last few versions for diffs and root-cause analysis."""
    target = versions_dir(app_dir) / str(version)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*SKIP_DIRS, *GENERATED))
    kept = sorted((int(p.name) for p in versions_dir(app_dir).iterdir() if p.name.isdigit()), reverse=True)
    for old in kept[KEEP_VERSIONS:]:
        shutil.rmtree(versions_dir(app_dir) / str(old), ignore_errors=True)
    return target


def files_of(root: Path) -> dict[str, str]:
    """relative path → sha256, for every file of a version."""
    result = {}
    if not root.is_dir():
        return result
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if path.is_file() and not path.is_symlink() and not any(p in SKIP_DIRS for p in relative.parts) and path.name not in GENERATED:
            result[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def changes(previous: Path | None, current: Path) -> dict[str, list[str]]:
    before = files_of(previous) if previous else {}
    after = files_of(current)
    return {
        "added": sorted(set(after) - set(before)),
        "modified": sorted(p for p in set(after) & set(before) if after[p] != before[p]),
        "removed": sorted(set(before) - set(after)),
    }


# ---------------------------------------------------------------- dependency graph


def _python_imports(root: Path, relative: str) -> set[str]:
    try:
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, ValueError, RecursionError):
        return set()
    package = PurePosixPath(relative).parent
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:  # relative import
                anchor = package
                for _ in range(node.level - 1):
                    anchor = anchor.parent
                prefix = ".".join(p for p in anchor.parts if p)
                base = ".".join(p for p in (prefix, base) if p)
            modules.add(base)
            modules.update(f"{base}.{alias.name}" if base else alias.name for alias in node.names)
    found = set()
    for module in modules:
        path = module.replace(".", "/")
        for candidate in (f"{path}.py", f"{path}/__init__.py"):
            # Absolute imports resolve from the project root or the importing file's folder (scripts run from there).
            for base in ("", package.as_posix()):
                full = str(PurePosixPath(base) / candidate) if base not in ("", ".") else candidate
                if (root / full).is_file():
                    found.add(full)
    return found


def _js_imports(root: Path, relative: str) -> set[str]:
    try:
        text = (root / relative).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return set()
    found = set()
    folder = PurePosixPath(relative).parent
    for spec in JS_IMPORT.findall(text):
        base = (folder / spec).as_posix()
        parts: list[str] = []
        for part in base.split("/"):
            if part == "..":
                if parts:
                    parts.pop()
            elif part not in ("", "."):
                parts.append(part)
        resolved = "/".join(parts)
        for ext in JS_EXTENSIONS:
            if (root / f"{resolved}{ext}").is_file():
                found.add(f"{resolved}{ext}")
                break
    return found


def dependency_graph(root: Path, files: list[str]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for relative in files:
        suffix = PurePosixPath(relative).suffix
        if suffix == ".py":
            graph[relative] = _python_imports(root, relative)
        elif suffix in CODE:
            graph[relative] = _js_imports(root, relative)
    return graph


def is_test(path: str) -> bool:
    return bool(PY_TEST.search(path) or JS_TEST.search(path))


def select_tests(root: Path, changed: dict[str, list[str]], previous_failures: list[str]) -> dict[str, Any]:
    """Which tests to run for this change, and why."""
    files = sorted(files_of(root))
    tests = [f for f in files if is_test(f)]
    touched = set(changed["added"]) | set(changed["modified"]) | set(changed["removed"])
    if not tests:
        return {"tests": [], "all_tests": [], "reason": "No tests found", "mode": "none"}
    if not touched:
        return {"tests": [], "all_tests": tests, "reason": "No files changed", "mode": "none"}

    suffixes = {PurePosixPath(f).suffix.lower() for f in touched}
    names = {PurePosixPath(f).name for f in touched}
    if not changed["modified"] and not changed["removed"] and len(touched) == len(files):
        return {"tests": tests, "all_tests": tests, "reason": "First deployment: full test suite", "mode": "full"}
    infrastructure = names & {"requirements.txt", "package.json", "package-lock.json", "Dockerfile", "Pipfile",
                              "pyproject.toml", "setup.py", "conftest.py", "pytest.ini", "tsconfig.json"}
    if infrastructure:
        return {"tests": tests, "all_tests": tests, "mode": "full",
                "reason": f"{', '.join(sorted(infrastructure))} changed: dependencies or test setup may affect everything"}
    unknown = sorted(f for f in touched if PurePosixPath(f).suffix.lower() not in CODE | DOCS)
    if unknown:
        return {"tests": tests, "all_tests": tests, "mode": "full",
                "reason": f"Non-code files changed ({', '.join(unknown[:3])}): running everything to be safe"}
    if suffixes <= DOCS:
        return {"tests": [], "all_tests": tests, "reason": "Only documentation changed", "mode": "none"}

    graph = dependency_graph(root, files)
    reverse: dict[str, set[str]] = defaultdict(set)
    for source, targets in graph.items():
        for target in targets:
            reverse[target].add(source)
    impacted: dict[str, str] = {}  # file → the change that impacts it
    frontier = [(f, f) for f in touched]
    while frontier:
        current, cause = frontier.pop()
        for dependant in reverse.get(current, ()):
            if dependant not in impacted:
                impacted[dependant] = cause
                frontier.append((dependant, cause))
    selected: dict[str, str] = {}
    for test in tests:
        if test in touched:
            selected[test] = "the test itself changed"
        elif test in impacted:
            selected[test] = f"depends on {impacted[test]}"
        elif test in previous_failures:
            selected[test] = "failed in the previous pipeline"
    return {
        "tests": sorted(selected), "all_tests": tests, "mode": "impacted",
        "why": selected, "reason": f"{len(selected)} of {len(tests)} test file(s) depend on what changed",
    }


# ---------------------------------------------------------------- running tests


def test_command(runtime_name: str, tests: list[str]) -> list[str] | None:
    """Command to run the selected tests inside the app image, or None when the image has no test runner."""
    py = [f"/app/{t}" for t in tests if t.endswith(".py")]
    js = [f"/app/{t}" for t in tests if not t.endswith(".py")]
    if runtime_name in ("python", "procfile-python", "lambda-python") and py:
        script = ('python -c "import pytest" 2>/dev/null || pip install -q pytest >/dev/null 2>&1; '
                  'cd /app && python -m pytest -q -p no:cacheprovider --rootdir=/app "$@"')
        return ["sh", "-c", script, "pytest", *py]
    if runtime_name in ("node", "procfile-node", "lambda-node") and js:
        return ["sh", "-c", 'cd /app && node --test "$@"', "node-test", *js]
    return None


def summarise_output(output: str) -> dict[str, Any]:
    """Counts from pytest or node --test output, and the failing test files."""
    passed = failed = 0
    match = re.search(r"(\d+) passed", output)
    if match:
        passed = int(match.group(1))
    match = re.search(r"(\d+) failed", output)
    if match:
        failed = int(match.group(1))
    node_pass = re.search(r"^# pass (\d+)", output, re.MULTILINE)
    node_fail = re.search(r"^# fail (\d+)", output, re.MULTILINE)
    if node_pass:
        passed, failed = int(node_pass.group(1)), int(node_fail.group(1)) if node_fail else 0
    failing = sorted(set(re.findall(r"^FAILED /app/([^:\s]+)", output, re.MULTILINE))
                     | set(re.findall(r"/app/([^\s:]+\.(?:test|spec)\.[cm]?[jt]sx?)", output) if failed else []))
    return {"passed": passed, "failed": failed, "failing_files": failing}


def run_tests(runtime, app_id: str, image: str, runtime_name: str, selection: dict[str, Any]) -> dict[str, Any]:
    tests = selection["tests"]
    result: dict[str, Any] = {**selection, "status": "skipped", "duration": 0.0, "output": ""}
    if not tests:
        return result
    command = test_command(runtime_name, tests)
    if command is None:
        result["reason"] += " — this runtime has no test runner, tests were not run"
        return result
    started = time.time()
    code, output, _ = runtime.run_task(app_id, image, command, role="pipeline", timeout=300, working_dir="/app")
    duration = time.time() - started
    counts = summarise_output(output)
    skipped_files = len(selection["all_tests"]) - len(tests)
    per_file = duration / max(1, len(tests))
    result.update(
        status="passed" if code == 0 else "failed", exit_code=code, duration=round(duration, 1),
        output=output[-6000:], **counts,
        skipped_files=skipped_files, estimated_saving=round(per_file * skipped_files, 1),
    )
    return result
