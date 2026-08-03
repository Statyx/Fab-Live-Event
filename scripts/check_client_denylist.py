#!/usr/bin/env python3
"""Fail if a name from the private client deny-list appears in Git-tracked files.

This repo is public, so the deny-list itself must never be committed here. The
list is injected at run time and stays out of the source tree:

    1. ``CLIENT_DENYLIST`` -- one entry per line (GitHub Actions secret).
    2. ``.clientdeny`` at the repo root -- gitignored, for local runs.

Neither present? The rule is skipped with a warning and the build stays green.
An absent secret must never break a fork, a PR from outside the org, or a
contributor's laptop.

Only files returned by ``git ls-files`` are scanned, for the same reason as the
structural checker: ``__pycache__/*.pyc`` and ``node_modules`` embed absolute
paths and produce false positives.

Two deliberate properties:

* **Nothing is echoed.** A finding prints the file, the line number and a hash
  prefix of the entry -- never the entry itself, never the source line. CI logs
  of a public repo are public: a chatty scanner would re-publish the very name
  it is guarding.
* **Colour contexts are ignored.** Some client names double as ordinary colour
  words. A hit on a line that is plainly about colour -- a shields.io badge, a
  hex token, ``rgb()``, a CSS declaration -- is dropped. The rule is generic; no
  name and no colour is hardcoded here.

Usage:
    python scripts/check_client_denylist.py

Exit code 0 = clean or not configured, 1 = a deny-listed name was found.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_DENYLIST = REPO_ROOT / ".clientdeny"

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".pptx", ".xlsx",
    ".docx", ".zip", ".gz", ".woff", ".woff2", ".ttf", ".eot",
}

# A line that is plainly about colour. Generic on purpose: it keys on the
# colour syntax around the hit, not on which word was matched.
COLOUR_CONTEXT_RE = re.compile(
    r"""
      img\.shields\.io                      # badge URLs: .../badge/x-y-<colour>
    | \#[0-9A-Fa-f]{3,8}\b                  # hex token
    | \brgba?\s*\(                          # rgb() / rgba()
    | \bhsla?\s*\(                          # hsl() / hsla()
    | (?:^|[;{,\s])(?:color|background|background-color|fill|stroke|border
        |border-color|outline|box-shadow|--[\w-]+)\s*:   # CSS declaration
    | "(?:color|colour|fill|stroke|background)"\s*:      # JSON theme key
    """,
    re.IGNORECASE | re.VERBOSE,
)

# The obfuscation this whole change exists to remove: a single character wrapped
# in parentheses. `n(a)me` still matches as an ERE and reads fine to a human, but
# no full-text search for the name finds it. Parentheses are stripped before
# matching so the trick buys nothing.
SINGLE_CHAR_PAREN_RE = re.compile(r"\(([A-Za-z0-9])\)")


def load_denylist() -> tuple[list[str], str]:
    """Return (entries, source-label). Empty list means "not configured"."""
    raw = os.environ.get("CLIENT_DENYLIST", "")
    source = "the CLIENT_DENYLIST environment variable"
    if not raw.strip() and LOCAL_DENYLIST.is_file():
        raw = LOCAL_DENYLIST.read_text(encoding="utf-8", errors="ignore")
        source = str(LOCAL_DENYLIST.name)

    entries = []
    for line in raw.splitlines():
        entry = line.strip()
        if entry and not entry.startswith("#"):
            entries.append(entry)
    return entries, source


def compile_entry(entry: str) -> re.Pattern[str]:
    """Word-bounded, case-insensitive, separator-tolerant literal match.

    A two-word entry also catches the hyphenated, underscored and glued
    spellings -- the separator is where obfuscation is cheapest.
    """
    parts = [re.escape(part) for part in entry.split()]
    body = r"[\s._\-]*".join(parts)
    return re.compile(rf"\b{body}\b", re.IGNORECASE)


def fingerprint(entry: str) -> str:
    """Stable, non-reversible label so a maintainer can tell entries apart."""
    digest = hashlib.sha256(entry.strip().lower().encode("utf-8")).hexdigest()
    return digest[:8]


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def scan_file(rel_path: str, patterns: list[tuple[int, str, re.Pattern[str]]]) -> list[str]:
    path = REPO_ROOT / rel_path
    if path.suffix.lower() in BINARY_SUFFIXES or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    findings = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        colour_line = COLOUR_CONTEXT_RE.search(line) is not None
        if colour_line:
            continue  # the word is being used as a colour, not as a name
        variants = {line, SINGLE_CHAR_PAREN_RE.sub(r"\1", line)}
        for index, mark, pattern in patterns:
            if any(pattern.search(variant) for variant in variants):
                findings.append(f"{rel_path}:{lineno}: deny-list entry #{index} [{mark}]")
    return findings


def main() -> int:
    entries, source = load_denylist()
    if not entries:
        print(
            "::warning::Client deny-list not configured "
            "(set the CLIENT_DENYLIST secret, or a gitignored .clientdeny file) "
            "- name-based scanning skipped. Structural checks still ran."
        )
        return 0

    patterns = [
        (index, fingerprint(entry), compile_entry(entry))
        for index, entry in enumerate(entries, start=1)
    ]

    findings: list[str] = []
    for rel_path in tracked_files():
        findings.extend(scan_file(rel_path, patterns))

    if findings:
        # Entries are reported by index + hash prefix only: printing the name
        # here would leak it into public CI logs.
        print(
            f"Deny-listed client name(s) found in Git-tracked files "
            f"({len(entries)} entries loaded from {source}):\n"
        )
        for finding in findings:
            print(f"  {finding}")
        print(
            "\nThe matched text is deliberately not shown. Open the file at the "
            "line above and anonymise it before merging."
        )
        return 1

    print(f"No deny-listed client name found ({len(entries)} entries checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
