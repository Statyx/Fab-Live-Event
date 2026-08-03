#!/usr/bin/env python3
"""
Cross-platform environment handling for the deploy scripts (single source of truth).

Why this exists: activating a virtualenv on Windows can wipe the inherited PATH,
after which the `az` CLI — invoked through subprocess by every deploy script — is
no longer found. On Windows we rebuild PATH from the registry (machine `Path`
then user `Path`), which is exactly what each script used to do inline.

`winreg` is a Windows-only stdlib module, so importing it unconditionally made
this repository unimportable on macOS / Linux. Here the import is guarded: on
other platforms the process PATH is already authoritative, so `restore_path()`
is a no-op and executable lookup falls back to `shutil.which`.

Windows behaviour is unchanged; other platforms simply stop crashing.

Shared with the twin repository (Fab-Network-Operations) — keep the module name
and the API surface identical on both sides.
"""
import os
import shutil
import sys
from typing import Optional

IS_WINDOWS = sys.platform.startswith("win")

if IS_WINDOWS:  # pragma: no cover - platform dependent
    import winreg
else:  # pragma: no cover - platform dependent
    winreg = None

# `az` is a .cmd shim on Windows, so subprocess needs the shell to resolve it.
# On POSIX, shell=True with an argv LIST silently runs only argv[0] and drops
# every following argument, so it must stay False there.
AZ_NEEDS_SHELL = IS_WINDOWS

_MACHINE_ENV = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
_USER_ENV = "Environment"


def restore_path() -> None:
    """Self-heal os.environ['PATH'] from the Windows registry. No-op elsewhere."""
    if not IS_WINDOWS:
        return
    parts = []
    # Machine-wide PATH first, then the user PATH — same order as the Windows shell.
    for root, sub in [(winreg.HKEY_LOCAL_MACHINE, _MACHINE_ENV),
                      (winreg.HKEY_CURRENT_USER, _USER_ENV)]:
        try:
            k = winreg.OpenKey(root, sub)
            v, _ = winreg.QueryValueEx(k, "Path")
            parts.append(os.path.expandvars(v))
            winreg.CloseKey(k)
        except Exception:
            pass
    if parts:
        os.environ["PATH"] = ";".join(parts) + ";" + os.environ.get("PATH", "")


def find_executable(executable: str) -> Optional[str]:
    """Locate an executable on the standard PATH (healing it first on Windows)."""
    restore_path()
    return shutil.which(executable)


def configure_stdout() -> None:
    """Force UTF-8 stdout so the emoji/box-drawing output survives cp1252 consoles."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def bootstrap() -> None:
    """Standard prologue for every entry point: heal PATH, then force UTF-8 stdout."""
    restore_path()
    configure_stdout()
