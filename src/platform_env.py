#!/usr/bin/env python3
"""Cross-platform environment bootstrap shared by every script in this repository.

This module is duplicated verbatim across sibling repositories. Keep the two copies
interchangeable: change it here and copy it over, rather than editing one side only.

Why this module exists
----------------------
These scripts shell out to the Azure CLI (``az``). On Windows, activating a
virtualenv from some terminals wipes ``PATH``, so ``az`` becomes unfindable
mid-session. The workaround is to rebuild ``PATH`` from the Windows registry
(machine-wide then user ``Environment`` keys).

That workaround used to be copy-pasted — behind an unconditional ``import winreg``
— into every script under ``src/``. ``winreg`` is a Windows-only stdlib module, so
the whole repository failed to even import on macOS and Linux. This module owns the
logic once, and is the single place where OS-specific behaviour is allowed to live.

Canonical prologue
------------------
Every script under ``src/`` that needs a working ``PATH`` starts with exactly these
three lines, right after its module docstring (the first line keeps whatever stdlib
modules that script needs)::

    import os, sys
    from platform_env import bootstrap
    bootstrap()

Public contract
---------------
======================  ==================================  ======================
symbol                  Windows                             macOS / Linux
======================  ==================================  ======================
``IS_WINDOWS``          ``True``                            ``False``
``AZ_NEEDS_SHELL``      ``True``                            ``False``
``restore_path()``      rebuilds ``PATH`` from registry     no-op
``configure_stdout()``  forces UTF-8 on stdout              same
``bootstrap()``         ``restore_path`` then ``configure_stdout``, in that order
``find_executable()``   ``shutil.which``, retried once      ``shutil.which``
======================  ==================================  ======================

``import winreg`` must appear nowhere else in the repository. The accompanying test
suite enforces that, together with the prologue above and the absence of any
hard-coded ``shell=True``; CI runs those tests on Linux, which is what turns the
guarantee into something more than a comment.
"""
from __future__ import annotations

import os
import shutil
import sys
from typing import List, Optional

__all__ = [
    "IS_WINDOWS",
    "AZ_NEEDS_SHELL",
    "restore_path",
    "configure_stdout",
    "bootstrap",
    "find_executable",
]

#: ``True`` on Windows, ``False`` on macOS/Linux/anything else. Every other
#: platform-dependent decision in this repository derives from this flag, so a
#: single ``monkeypatch.setattr(platform_env, "IS_WINDOWS", False)`` is enough to
#: exercise the non-Windows code paths from a Windows test run.
IS_WINDOWS = sys.platform.startswith("win")

#: Whether ``az`` must be launched through a shell.
#:
#: Windows: ``True``. The Azure CLI ships as an ``az.cmd`` batch shim, which
#: ``CreateProcess`` cannot start directly, so ``subprocess`` needs ``shell=True``.
#:
#: macOS / Linux: ``False``. ``az`` is a real executable there, and ``shell=True``
#: combined with an argv *list* is actively harmful on POSIX: the shell would run
#: only ``argv[0]`` and silently drop every argument.
#:
#: Always pass it as ``subprocess.<call>(argv_list, shell=AZ_NEEDS_SHELL)``.
AZ_NEEDS_SHELL = IS_WINDOWS

if IS_WINDOWS:  # pragma: no cover - platform-specific import
    import winreg
else:  # pragma: no cover - platform-specific import
    winreg = None  # type: ignore[assignment]


def _windows_path_from_registry() -> List[str]:
    """Read the machine-wide then user ``Path`` values from the Windows registry.

    Windows only — never reached on other platforms, where ``winreg`` is ``None``.

    Returns the values of ``HKLM\\SYSTEM\\CurrentControlSet\\Control\\Session
    Manager\\Environment\\Path`` and ``HKCU\\Environment\\Path``, in that order,
    with ``%VAR%`` references expanded. Unreadable or missing keys are skipped
    silently: a user with no personal ``Path`` is perfectly normal, and this runs at
    import time, where raising would be far worse than returning a shorter list.

    Returns:
        Zero, one or two ``PATH`` fragments, machine-wide first.
    """
    parts: List[str] = []
    for root, sub in [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg.HKEY_CURRENT_USER, "Environment"),
    ]:
        try:
            key = winreg.OpenKey(root, sub)
            value, _ = winreg.QueryValueEx(key, "Path")
            parts.append(os.path.expandvars(value))
            winreg.CloseKey(key)
        except Exception:
            pass
    return parts


def restore_path() -> None:
    """Repair ``os.environ["PATH"]`` when a terminal has truncated it.

    Windows: reads the machine-wide then user ``Path`` from the registry, joins them
    with ``;`` and *prepends* the result to the current ``PATH``. The existing
    ``PATH`` is kept as a suffix, so nothing the caller set is ever lost — duplicate
    entries are harmless. Failures are swallowed; worst case ``PATH`` is left as it
    was.

    macOS / Linux: **no-op**. There is no registry, and the ``PATH`` inherited from
    the shell is already authoritative — rewriting it could only break the caller's
    environment.

    Safe to call repeatedly, which is what ``bootstrap()`` and ``find_executable()``
    rely on.
    """
    if not IS_WINDOWS:
        return
    parts = _windows_path_from_registry()
    if parts:
        os.environ["PATH"] = ";".join(parts) + ";" + os.environ.get("PATH", "")


def configure_stdout() -> None:
    """Force ``stdout`` to UTF-8 so the scripts' box-drawing output survives.

    Behaviour is identical on every platform. It matters most on Windows, whose
    console defaults to a legacy code page (cp1252) that cannot encode the ``✓``,
    ``⚠`` and ``──`` characters these scripts print; on macOS/Linux stdout is
    normally UTF-8 already and this is a harmless confirmation.

    Silently does nothing when ``stdout`` has been replaced by an object without
    ``reconfigure()`` — a pytest capture buffer, a pipe wrapper, a notebook stream.

    Takes no argument on purpose: UTF-8 is the only value that makes the output
    correct, and a fixed signature keeps this module interchangeable with the copy
    shipped by the sibling repository.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def bootstrap() -> None:
    """Standard script preamble: repair ``PATH``, then make ``stdout`` UTF-8.

    This is the only entry point the calling scripts need. The order matters and is
    the same on every platform: ``restore_path()`` first, so that a later
    ``subprocess`` call can find ``az``, then ``configure_stdout()``.

    Windows: both steps do real work. macOS / Linux: only ``configure_stdout()`` has
    any effect, since ``restore_path()`` returns immediately.

    Safe to call at import time, and safe to call more than once.
    """
    restore_path()
    configure_stdout()


def find_executable(name: str) -> Optional[str]:
    """Locate an executable on ``PATH``, exactly like :func:`shutil.which`.

    macOS / Linux: a straight :func:`shutil.which` lookup on the inherited ``PATH``
    — this is the documented fallback that replaces the registry logic.

    Windows: the same :func:`shutil.which` lookup, so ``PATHEXT`` is honoured and
    ``az`` resolves to ``az.CMD``, except that a miss triggers one
    :func:`restore_path` retry in case ``PATH`` had been wiped by a venv activation.
    That retry is what lets the second attempt succeed where the first failed.

    Args:
        name: executable name, with or without extension (e.g. ``"az"``).

    Returns:
        Absolute path to the executable, or ``None`` when it is genuinely not on
        ``PATH``. Never raises.
    """
    found = shutil.which(name)
    if found is None and IS_WINDOWS:
        restore_path()
        found = shutil.which(name)
    return found
