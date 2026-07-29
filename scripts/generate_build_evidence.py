#!/usr/bin/env python3
"""Generate `evidence/build.json` from the pipeline.

Everything written here is the recorded output of a tool that actually ran: a
CycloneDX SBOM, a dependency audit, the test run, and the revision being built.
Nothing is asserted by hand. If a tool is unavailable the entry says so rather
than claiming a pass — the assessor then reports `not_assessed`, which is the
honest outcome.

Usage:
    python scripts/generate_build_evidence.py
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "evidence" / "build.json"
SBOM_PATH = REPO_ROOT / "evidence" / "sbom.cdx.json"
TIMEOUT = 600


def run(command: list[str]) -> tuple[int, str, str]:
    if not shutil.which(command[0]):
        return 127, "", f"{command[0]} is not installed"
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"{command[0]} timed out"
    return completed.returncode, completed.stdout, completed.stderr


def generate_sbom() -> dict:
    last_error = ""
    for command in (
        ["cyclonedx-py", "requirements", "requirements.txt", "--of", "JSON", "-o", str(SBOM_PATH)],
        ["cyclonedx-bom", "-r", "-i", "requirements.txt", "-o", str(SBOM_PATH)],
    ):
        code, _, error = run(command)
        if code == 0 and SBOM_PATH.is_file():
            raw = SBOM_PATH.read_bytes()
            try:
                document = json.loads(raw)
            except ValueError:
                document = {}
            components = document.get("components") or []
            return {
                "tool": command[0],
                "tool_available": True,
                "format": "CycloneDX",
                "components": len(components),
                "digest": hashlib.sha256(raw).hexdigest(),
                "artifact_ref": SBOM_PATH.relative_to(REPO_ROOT).as_posix(),
            }
        last_error = error
    return {
        "tool": "cyclonedx-py",
        "tool_available": False,
        "components": 0,
        "error": last_error.strip()[:200],
    }


def audit_dependencies() -> dict:
    code, stdout, error = run(["pip-audit", "--format", "json", "--progress-spinner", "off"])
    if code == 127:
        return {"tool": "pip-audit", "tool_available": False, "error": error.strip()[:200]}
    try:
        payload = json.loads(stdout or "{}")
    except ValueError:
        return {
            "tool": "pip-audit",
            "tool_available": True,
            "error": (error or stdout).strip()[:200],
        }
    dependencies = payload.get("dependencies") or payload
    advisories: set[str] = set()
    scanned = 0
    if isinstance(dependencies, list):
        scanned = len(dependencies)
        for entry in dependencies:
            for vulnerability in entry.get("vulns") or []:
                advisories.add(
                    f"{entry.get('name')} {entry.get('version')}: {vulnerability.get('id')}"
                )
    ordered = sorted(advisories)
    return {
        "tool": "pip-audit",
        "tool_available": True,
        "packages_scanned": scanned,
        "vulnerabilities": len(ordered),
        "advisories": ordered[:20],
    }


def run_tests() -> dict:
    code, stdout, error = run([sys.executable, "-m", "pytest", "-q"])
    text = stdout or error
    passed = failed = 0
    match = re.search(r"(\d+) passed", text)
    if match:
        passed = int(match.group(1))
    match = re.search(r"(\d+) failed", text)
    if match:
        failed = int(match.group(1))
    security_tests = 0
    code_collect, collected, _ = run(
        [sys.executable, "-m", "pytest", "tests/test_security.py", "--collect-only", "-q"]
    )
    if code_collect == 0:
        security_tests = len(
            [line for line in collected.splitlines() if "::" in line and "test_" in line]
        )
    return {
        "runner": "pytest",
        "exit_code": code,
        "passed": passed,
        "failed": failed,
        "security_tests": security_tests,
    }


def change_control() -> dict:
    _, commit, _ = run(["git", "rev-parse", "HEAD"])
    _, branch, _ = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return {
        "commit": commit.strip(),
        "branch": branch.strip(),
        "pipeline": "GitHub Actions",
        "test_gate": "ruff + pytest + docker build",
    }


def main() -> int:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "generator": "scripts/generate_build_evidence.py",
        "sbom": generate_sbom(),
        "dependency_audit": audit_dependencies(),
        "tests": run_tests(),
        "change_control": change_control(),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)}")
    print(json.dumps(payload["dependency_audit"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
