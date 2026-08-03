"""Tests for the client deny-list scanner (scripts/check_client_denylist.py).

The scanner replaces a hardcoded list of customer names that used to live in the
public CI workflow. These tests pin the three properties that make the
replacement safe:

* an absent deny-list degrades to a warning, never a failure;
* a deny-listed name in a tracked file fails the build;
* the failure output never echoes the name it matched.

Every case runs against a throwaway git repo: the scanner only reads
``git ls-files``, so there has to be a real index for it to read.
"""
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCANNER = ROOT / "scripts" / "check_client_denylist.py"

# A word that is not a real customer name — the point of this whole exercise is
# that no real name appears in a public repo, tests included.
FAKE_NAME = "zorblatt"


def _git(repo: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """A minimal git repo carrying a copy of the scanner."""
    _git(tmp_path, "init", "-q")
    (tmp_path / "scripts").mkdir()
    shutil.copy2(SCANNER, tmp_path / "scripts" / SCANNER.name)
    return tmp_path


def _run(repo: pathlib.Path, denylist: str | None = None):
    import os

    env = dict(os.environ)
    env.pop("CLIENT_DENYLIST", None)
    if denylist is not None:
        env["CLIENT_DENYLIST"] = denylist
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / SCANNER.name)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )


def _track(repo: pathlib.Path, name: str, content: str) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", name)


def test_missing_denylist_warns_but_passes(repo):
    """No secret configured (forks, external PRs) must never break the build."""
    _track(repo, "notes.md", f"the {FAKE_NAME} account\n")
    result = _run(repo, denylist=None)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::warning::" in result.stdout


def test_empty_denylist_is_treated_as_absent(repo):
    _track(repo, "notes.md", f"the {FAKE_NAME} account\n")
    result = _run(repo, denylist="\n  \n# only a comment\n")
    assert result.returncode == 0
    assert "::warning::" in result.stdout


def test_denylisted_name_fails(repo):
    _track(repo, "notes.md", f"deployed for {FAKE_NAME} last quarter\n")
    result = _run(repo, denylist=FAKE_NAME)
    assert result.returncode == 1, result.stdout
    assert "notes.md:1" in result.stdout


def test_failure_output_never_echoes_the_name(repo):
    """CI logs of a public repo are public — the scanner must stay silent."""
    _track(repo, "notes.md", f"deployed for {FAKE_NAME} last quarter\n")
    result = _run(repo, denylist=FAKE_NAME)
    assert result.returncode == 1
    combined = (result.stdout + result.stderr).lower()
    assert FAKE_NAME not in combined
    assert "last quarter" not in combined


def test_separator_variants_are_caught(repo):
    """Splitting a name with a dash or a dot is the cheapest obfuscation."""
    _track(repo, "notes.md", "contact: zorb-latt and zorb.latt and zorblatt\n")
    result = _run(repo, denylist="zorb latt")
    assert result.returncode == 1


def test_parenthesised_letter_obfuscation_is_caught(repo):
    """The exact trick this change removes: `z(o)rblatt` reads fine, greps as nothing.

    A regex with a capturing group still matches the plain word, so the guard
    kept working while the name hid from full-text search. Stripping single-char
    parentheses before matching makes the dodge worthless.
    """
    _track(repo, "ci.yml", "PATTERN='z(o)rblatt|something-else'\n")
    result = _run(repo, denylist=FAKE_NAME)
    assert result.returncode == 1, result.stdout


def test_colour_context_is_ignored(repo):
    """Some client names are also colour words; badges and CSS are not leaks."""
    _track(
        repo,
        "README.md",
        "![Build](https://img.shields.io/badge/build-passing-zorblatt)\n",
    )
    _track(repo, "theme.css", ".hero { background-color: zorblatt; }\n")
    _track(repo, "palette.json", '{ "color": "zorblatt" }\n')
    result = _run(repo, denylist=FAKE_NAME)
    assert result.returncode == 0, result.stdout
    # Green because the hits were dropped as colour, not because the list was
    # never loaded -- a test that passes vacuously protects nothing.
    assert "1 entries checked" in result.stdout


def test_untracked_files_are_not_scanned(repo):
    """Only git ls-files is walked: __pycache__ / node_modules would be noise."""
    (repo / "scratch.md").write_text(f"{FAKE_NAME}\n", encoding="utf-8")
    result = _run(repo, denylist=FAKE_NAME)
    assert result.returncode == 0, result.stdout
    assert "1 entries checked" in result.stdout


def test_local_clientdeny_file_is_used_when_env_is_absent(repo):
    _track(repo, "notes.md", f"{FAKE_NAME} again\n")
    (repo / ".clientdeny").write_text(f"# local list\n{FAKE_NAME}\n", encoding="utf-8")
    result = _run(repo, denylist=None)
    assert result.returncode == 1, result.stdout
    assert FAKE_NAME not in (result.stdout + result.stderr).lower()


def test_canonical_scanner_is_byte_identical():
    """scripts/check_no_client_leak.py is shared verbatim with the sister repos.

    Editing it locally is how two repositories start converging on each other
    instead of on the canonical source, so the hash is pinned here.
    """
    import hashlib

    canonical = ROOT / "scripts" / "check_no_client_leak.py"
    data = canonical.read_bytes()
    assert len(data) == 4023, f"expected 4023 bytes, got {len(data)}"
    assert (
        hashlib.sha256(data).hexdigest().upper()
        == "33312E7E678C09663A7DA51151359F8244EA0CADD10E811FC2A31CCF38328CD3"
    ), "check_no_client_leak.py drifted from the canonical copy — re-fetch it, do not edit it"


def test_workflow_carries_no_client_names():
    """The guard file must not itself be the leak (this is the bug being fixed).

    A name written with parenthesised letters still matches as an ERE while
    hiding from full-text search, so the shape is banned outright.
    """
    import re

    workflow = (ROOT / ".github" / "workflows" / "no-client-leak.yml").read_text(
        encoding="utf-8"
    )
    assert "PATTERN=" not in workflow, "an inline name pattern is back in the workflow"
    # A single parenthesised letter inside a word: the obfuscation that was removed.
    assert not re.search(r"[A-Za-z]\([A-Za-z]\)[A-Za-z]", workflow), \
        "obfuscated literal detected in the workflow — names belong in a secret"
