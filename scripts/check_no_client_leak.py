#!/usr/bin/env python3
"""Fail if real customer / tenant identifiers leak into Git-tracked files.

This repo is public. It must never contain real Microsoft Fabric identifiers,
real workspace SQL endpoints, or personal filesystem paths.

Only files returned by ``git ls-files`` are scanned. The working tree is
deliberately NOT walked: ``__pycache__/*.pyc`` and ``node_modules`` embed
absolute build paths and would produce false positives.

Usage:
    python scripts/check_no_client_leak.py

Exit code 0 = clean, 1 = leak detected.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Placeholder GUIDs that are allowed to appear verbatim.
ALLOWED_GUIDS = {
    "00000000-0000-0000-0000-000000000000",
}

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".pptx", ".xlsx",
    ".docx", ".zip", ".gz", ".woff", ".woff2", ".ttf", ".eot",
}

GUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

# A real Fabric SQL/warehouse endpoint host: a long opaque token followed by
# ".datawarehouse.fabric.microsoft.com" (or the Synapse / Power BI equivalents).
FABRIC_ENDPOINT_RE = re.compile(
    r"\b[a-z0-9]{20,}(?:-[a-z0-9]{20,})?\."
    r"(?:datawarehouse|dev\.azuresynapse|pbidedicated)\b",
    re.IGNORECASE,
)

# Personal home directories. Placeholders such as C:\Users\<you> are fine.
PERSONAL_PATH_RE = re.compile(
    r"(?:[A-Za-z]:\\Users\\|/Users/|/home/)(?!<|\{|\$|%|USERNAME\b|username\b|you\b|user\b)"
    r"[A-Za-z0-9._-]+",
)

# Extra literals to forbid, as a comma-separated list. Deliberately empty by
# default: hardcoding an author's username here would re-publish the very thing
# this checker exists to remove.
#   NO_LEAK_EXTRA_LITERALS="acme,contoso" python scripts/check_no_client_leak.py
FORBIDDEN_LITERALS = [
    literal.strip().lower()
    for literal in os.environ.get("NO_LEAK_EXTRA_LITERALS", "").split(",")
    if literal.strip()
]

CHECKS = [
    ("real GUID", GUID_RE, lambda m: m.group(0).lower() not in ALLOWED_GUIDS),
    ("Fabric SQL endpoint", FABRIC_ENDPOINT_RE, lambda m: True),
    ("personal filesystem path", PERSONAL_PATH_RE, lambda m: True),
]


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def scan_file(rel_path: str) -> list[str]:
    path = REPO_ROOT / rel_path
    if path.suffix.lower() in BINARY_SUFFIXES or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    findings = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for label, pattern, keep in CHECKS:
            for match in pattern.finditer(line):
                if keep(match):
                    findings.append(
                        f"{rel_path}:{lineno}: {label}: {match.group(0)}"
                    )
        lowered = line.lower()
        for literal in FORBIDDEN_LITERALS:
            if literal in lowered:
                findings.append(
                    f"{rel_path}:{lineno}: author-specific marker: {literal}"
                )
    return findings


def main() -> int:
    findings: list[str] = []
    for rel_path in tracked_files():
        findings.extend(scan_file(rel_path))

    if findings:
        print("Client / tenant data leak detected in Git-tracked files:\n")
        for finding in findings:
            print(f"  {finding}")
        print(
            "\nReplace real values with visibly fake placeholders "
            "(e.g. <YOUR_WORKSPACE_ID> or 00000000-0000-0000-0000-000000000000)."
        )
        return 1

    print("No client data leak detected in Git-tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
