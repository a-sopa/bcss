"""Client for the QuantumTrace scan API: the code-analysis step of every deployment."""

import re
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

from . import config

SOURCE_SUFFIXES = {".py", ".java", ".go"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
MAX_SOURCE_FILES = 2000
TIER_ORDER = {"critical": 0, "medium": 1, "unknown": 2, "resilient": 3}


class ScanUnavailable(Exception):
    """QuantumTrace could not be reached or rejected the request."""


def collect_inputs(root: Path) -> list[dict[str, str]]:
    inputs = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        inputs.append({
            "name": relative.as_posix(),
            "source_type": "source",
            "format": "raw",
            "content": content,
            "encoding": "utf-8",
        })
        if len(inputs) >= MAX_SOURCE_FILES:
            break
    return inputs


def summarize(result: dict[str, Any]) -> dict[str, Any]:
    findings = result.get("findings", [])
    tiers = Counter(f.get("challenge_tier", "unknown") for f in findings)
    ranked = sorted(findings, key=lambda f: TIER_ORDER.get(f.get("challenge_tier", "unknown"), 2))
    return {
        "status": result.get("status", "completed"),
        "scan_id": result.get("scan_id"),
        "score": result.get("score", {}).get("value"),
        "files_scanned": sum(c.get("assessed", 0) for c in result.get("coverage", [])),
        "findings": len(findings),
        "tiers": {tier: tiers.get(tier, 0) for tier in ("critical", "medium", "resilient", "unknown")},
        "quantum_vulnerable": sum(1 for f in findings if f.get("quantum_status") == "vulnerable"),
        "top": [
            {
                "algorithm": f.get("algorithm"),
                "tier": f.get("challenge_tier"),
                "quantum_status": f.get("quantum_status"),
                "usage": f.get("usage"),
                "file": f["evidence"][0]["file"] if f.get("evidence") else None,
                "locator": f["evidence"][0]["locator"] if f.get("evidence") else None,
                "rationale": f.get("rationale"),
                "recommendation": f.get("recommendation"),
            }
            for f in ranked[:50]
        ],
    }


def scan_inputs(inputs: list[dict[str, str]], label: str) -> dict[str, Any]:
    """Full QuantumTrace result for raw source inputs."""
    try:
        response = httpx.post(
            f"{config.QUANTUMTRACE_URL}/api/scans",
            json={"inputs": inputs, "label": label},
            timeout=120,
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ScanUnavailable(str(exc)) from exc


def source_input(name: str, content: str) -> dict[str, str]:
    return {"name": name, "source_type": "source", "format": "raw", "content": content, "encoding": "utf-8"}


def scan(root: Path, label: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return (summary, full QuantumTrace result). The full result is None when nothing was scanned."""
    inputs = collect_inputs(root)
    if not inputs:
        return {"status": "skipped", "reason": "No Python, Java or Go source files to analyse."}, None
    result = scan_inputs(inputs, label)
    return summarize(result), result


def editor_findings(result: dict[str, Any]) -> list[dict[str, Any]]:
    """QuantumTrace findings on the editor's severity scale.

    Shor-breakable (critical tier) → high (red), or critical (black) when also classically weak;
    Grover-weakened (medium tier) → medium (orange); unknown parameters → low (yellow).
    """
    findings = []
    for f in result.get("findings", []):
        tier = f.get("challenge_tier", "unknown")
        if tier == "resilient" or f.get("quantum_status") == "not_applicable" or not f.get("evidence"):
            continue
        evidence = f["evidence"][0]
        match = re.match(r"line:(\d+):column:(\d+)", evidence.get("locator", ""))
        if not match:
            continue
        line, column = int(match.group(1)), int(match.group(2))
        if tier == "critical":
            severity = "critical" if f.get("classical_issues") else "high"
            title = f"{f['algorithm']} is breakable by quantum computers"
        elif tier == "medium":
            severity, title = "medium", f"{f['algorithm']} is weakened by quantum attacks"
        else:
            severity, title = "low", f"{f['algorithm']}: parameters could not be verified"
        issues = "; ".join(f.get("classical_issues", []))
        findings.append({
            "id": f"QT:{f.get('id')}", "file": evidence["file"], "line": line, "column": column,
            "end_line": line, "end_column": column + max(1, len(f.get("algorithm", ""))),
            "severity": severity, "rule": f.get("rule_id") or "QUANTUMTRACE", "title": title,
            "message": (f.get("rationale") or "") + (f" Also classically weak: {issues}." if issues else ""),
            "suggestion": f.get("recommendation") or "", "cwe": "CWE-327", "source": "quantum", "fix": None,
        })
    return findings
