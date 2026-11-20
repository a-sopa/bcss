"""Root-cause analysis: correlate metrics, logs and the latest code change into one explanation.

1. When did errors start, and on which version (router metrics)?
2. What failed (Python tracebacks / Node stack traces in the version's logs, or test output)?
3. What changed (line diff between this version and the previous one)?
→ The failing frame that sits on (or next to) a changed line is the most likely cause; the report names it,
  explains the exception, and proposes code: the lines as they were before, plus a targeted fix hint.
"""

import difflib
import re
import time
from pathlib import Path
from typing import Any

PY_FRAME = re.compile(r'File "(?:/app/)?([^"]+)", line (\d+), in (\S+)')
JS_FRAME = re.compile(r"at (?:(\S+) \()?(?:file://)?/app/([^:)]+):(\d+):\d+\)?")
PY_EXCEPTION = re.compile(r"^(\w+(?:\.\w+)*(?:Error|Exception|Exit|Interrupt|Warning)|\w+Error): ?(.*)$", re.MULTILINE)
JS_EXCEPTION = re.compile(r"^(\w*Error): (.+)$", re.MULTILINE)

HINTS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"ZeroDivisionError"), "a division by zero",
     "Guard the divisor (e.g. `if count == 0: return 0`) or validate the input before dividing."),
    (re.compile(r"KeyError"), "a missing dictionary key",
     "Use `.get(key, default)` or check `if key in data` before reading it."),
    (re.compile(r"(AttributeError|TypeError).*'?NoneType'?"), "a value that was None",
     "Check for None before using the value, or make the function always return an object."),
    (re.compile(r"IndexError"), "an index out of range", "Check the length before indexing, or iterate instead."),
    (re.compile(r"NameError"), "an undefined name (typo or missing import)", "Define or import the name before using it."),
    (re.compile(r"ModuleNotFoundError|ImportError|Cannot find module"), "a missing dependency",
     "Add the package to requirements.txt / package.json, or fix the import path."),
    (re.compile(r"too many (clients|connections)|connection pool|PoolTimeout", re.I), "database connections running out",
     "Reuse a connection pool and close connections (use `with` blocks) instead of opening one per request."),
    (re.compile(r"OperationalError|ECONNREFUSED|Connection refused|could not connect", re.I), "a dependency that cannot be reached",
     "Check the service address in the environment variables and that the dependency is running."),
    (re.compile(r"Timeout|timed out", re.I), "an operation that timed out",
     "Add a timeout and a retry with back-off, or move the slow work out of the request."),
    (re.compile(r"RecursionError|Maximum call stack"), "unbounded recursion", "Add a base case or rewrite the recursion as a loop."),
    (re.compile(r"JSONDecodeError|Unexpected token .* JSON|SyntaxError: Unexpected"), "invalid JSON or syntax",
     "Validate the input and handle the decoding error."),
    (re.compile(r"(ReferenceError).* is not defined"), "an undefined variable", "Declare or import it before use."),
    (re.compile(r"TypeError: Cannot read propert"), "reading a property of undefined",
     "Use optional chaining (`obj?.field`) or check the value first."),
    (re.compile(r"PermissionError|EACCES"), "a permission problem", "Write only to /tmp or a mounted volume inside the container."),
    (re.compile(r"MemoryError|OOMKilled"), "running out of memory", "Process data in chunks or stream it instead of loading it all."),
]


def _frames(logs: str) -> list[dict[str, Any]]:
    frames = [{"file": f, "line": int(l), "function": fn} for f, l, fn in PY_FRAME.findall(logs)]
    frames += [{"file": f, "line": int(l), "function": fn or "?"} for fn, f, l in JS_FRAME.findall(logs)]
    return [f for f in frames if not f["file"].startswith(("/usr", "usr/", "node:", "/opt")) and "site-packages" not in f["file"]
            and "node_modules" not in f["file"] and ".owncloud/" not in f["file"]]


def _exception(logs: str) -> tuple[str, str] | None:
    found = PY_EXCEPTION.findall(logs) + JS_EXCEPTION.findall(logs)
    return (found[-1][0], found[-1][1].strip()) if found else None


def changed_lines(previous: Path | None, current: Path, files: list[str]) -> dict[str, dict[str, Any]]:
    """For each changed file: the new line numbers that changed, and a unified diff."""
    result = {}
    for relative in files:
        new_path = current / relative
        old_path = previous / relative if previous else None
        try:
            new = new_path.read_text(encoding="utf-8").splitlines()
            old = old_path.read_text(encoding="utf-8").splitlines() if old_path and old_path.is_file() else []
        except (UnicodeDecodeError, OSError):
            continue
        lines: set[int] = set()
        for tag, _, _, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
            if tag in ("replace", "insert"):
                lines.update(range(j1 + 1, j2 + 1))
            elif tag == "delete":
                lines.add(max(1, j1))
        diff = "\n".join(difflib.unified_diff(old, new, f"a/{relative}", f"b/{relative}", lineterm="", n=2))
        result[relative] = {"lines": sorted(lines), "diff": diff[:6000], "old": old, "new": new}
    return result


def _onset(metrics: dict | None, backend: str, since: float) -> float | None:
    if not metrics:
        return None
    for bucket in metrics.get("backends", {}).get(backend, []):
        if bucket["t"] + metrics.get("bucket_seconds", 5) >= since and (bucket["errors"] or bucket["probe_errors"]):
            return bucket["t"]
    return None


def _ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds} s ago"
    return f"{seconds // 60} min ago"


def analyse(*, kind: str, version: int, logs: str, current: Path, previous: Path | None, changed: list[str],
            metrics: dict | None = None, since: float | None = None, symptom: str = "", oom: bool = False) -> dict[str, Any]:
    """An incident report. `kind`: canary_rollback | tests_failed | crash | error_spike."""
    frames = _frames(logs)
    exception = _exception(logs) or (("OOMKilled", "the container exceeded its memory limit") if oom else None)
    diffs = changed_lines(previous, current, changed)

    culprit, on_changed_line = None, False
    for frame in reversed(frames):  # innermost project frame first
        info = diffs.get(frame["file"])
        if info and any(abs(frame["line"] - line) <= 2 for line in info["lines"]):
            culprit, on_changed_line = frame, True
            break
    if culprit is None and frames:
        culprit = frames[-1]
    if culprit is None and diffs:
        first = next(iter(diffs))
        if diffs[first]["lines"]:
            culprit = {"file": first, "line": diffs[first]["lines"][0], "function": "?"}

    text = f"{exception[0]}: {exception[1]}" if exception else logs[-500:]
    meaning, hint = "an unexpected error", "Compare the change with the previous version, or roll back."
    for pattern, what, how in HINTS:
        if pattern.search(text):
            meaning, hint = what, how
            break

    onset = _onset(metrics, f"v{version}", since or 0) if metrics else None
    when = f"started {_ago(time.time() - onset)}" if onset else "appeared"
    what = {"canary_rollback": f"Errors on the canary (v{version})", "tests_failed": f"Tests failed for v{version}",
            "crash": f"v{version} crashed", "error_spike": f"HTTP 5xx errors on v{version}"}.get(kind, f"A problem in v{version}")
    location = f"line {culprit['line']} of {culprit['file']}" if culprit else "the new version"
    cause = f"{exception[0]} — {meaning}" if exception else meaning
    because = "the change made in this version" if on_changed_line else ("code in" if culprit else "")
    summary = (f"{what} {when} because of {because} at {location}: {cause}." if on_changed_line
               else f"{what} {when}: {cause} at {location}.")
    if symptom:
        summary += f" ({symptom})"

    suggested = None
    if culprit and culprit["file"] in diffs:
        info = diffs[culprit["file"]]
        start, end = max(1, culprit["line"] - 3), culprit["line"] + 3
        old_block = [line for line in difflib.unified_diff(info["old"], info["new"], lineterm="", n=3)]
        suggested = {
            "file": culprit["file"],
            "current": "\n".join(f"{n:>4}  {info['new'][n - 1]}" for n in range(start, min(end, len(info["new"])) + 1)),
            "revert": "\n".join(old_block[2:40]) if old_block else "",
        }

    return {
        "kind": kind, "version": version, "summary": summary, "onset": onset,
        "exception": {"type": exception[0], "message": exception[1][:500]} if exception else None,
        "culprit": {**culprit, "changed_in_this_version": on_changed_line} if culprit else None,
        "frames": frames[-8:], "hint": hint, "meaning": meaning,
        "changes": [{"file": f, "lines": d["lines"][:50], "diff": d["diff"]} for f, d in diffs.items()][:10],
        "suggested_fix": suggested, "log_excerpt": logs[-3000:],
    }
