#!/usr/bin/env python3
"""Cross-platform environment bootstrap shared by every deploy/utility script.

Why this module exists
----------------------
The deploy scripts shell out to the Azure CLI (`az`). On Windows, activating a
virtualenv from some terminals wipes `PATH`, so `az` becomes unfindable mid-session.
The workaround is to rebuild `PATH` from the Windows registry (machine + user
`Environment` keys).

That workaround used to be copy-pasted — behind an unconditional `import winreg` —
into every script under `src/`. `winreg` is a Windows-only stdlib module, so the whole
repository failed to even import on macOS and Linux. This module owns the logic once:

* on Windows the behaviour is unchanged (same registry keys, same order, same `;`
  separator, same silent failure mode);
* on any other platform `restore_path()` is a no-op and executable lookup falls back
  to the normal `PATH` via `shutil.which`.

Usage in a script::

    from platform_env import bootstrap
    bootstrap()

Kept byte-for-byte in sync with the twin repository (Fab-Network-Operations): same
module name, same API surface, same semantics.
"""
from __future__ import annotations

import os
import shutil
import sys
from typing import List, Optional

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:  # pragma: no cover - platform-specific import
    import winreg
else:  # pragma: no cover - platform-specific import
    winreg = None  # type: ignore[assignment]

# On Windows `az` is a .cmd shim, which CreateProcess cannot launch directly — hence
# shell=True. On POSIX, shell=True with an argv list would run only "az" and drop every
# argument, so the shell must stay off there.
AZ_NEEDS_SHELL = IS_WINDOWS


def _windows_path_from_registry() -> List[str]:
    """Read the machine-wide then user `Path` values from the registry.

    Unreadable keys are skipped silently: a missing user `Path` is normal, and this
    runs at import time where raising would be worse than a shorter PATH.
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
    """Prepend the registry-declared `PATH` to the current one (Windows only).

    No-op on macOS/Linux, where the inherited `PATH` is already authoritative.
    """
    if not IS_WINDOWS:
        return
    parts = _windows_path_from_registry()
    if parts:
        os.environ["PATH"] = ";".join(parts) + ";" + os.environ.get("PATH", "")


def configure_stdout(encoding: str = "utf-8") -> None:
    """Force UTF-8 on stdout so the scripts' box-drawing/emoji output survives."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding=encoding)


def bootstrap(encoding: str = "utf-8") -> None:
    """Standard preamble: self-heal PATH, then make stdout UTF-8."""
    restore_path()
    configure_stdout(encoding)


def find_executable(name: str) -> Optional[str]:
    """Locate `name` on PATH, self-healing PATH once on Windows before giving up."""
    found = shutil.which(name)
    if found is None and IS_WINDOWS:
        restore_path()
        found = shutil.which(name)
    return found
