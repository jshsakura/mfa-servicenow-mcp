"""Cross-platform process-liveness predicate for the auth layer.

Stateless sibling helper (see CLAUDE.md: the AuthManager class is frozen, its
stateless helpers are not).

Why this module exists — `os.kill(pid, 0)` is NOT a liveness probe on Windows:

    CPython docs, os.kill():
      "The Windows kill() only supports the CTRL_C_EVENT and CTRL_BREAK_EVENT
       signals; any other value will cause the process to be unconditionally
       killed by the TerminateProcess API, and the exit code will be set to sig."

So on Windows the idiomatic POSIX check `os.kill(pid, 0)` **terminates the
target process** with exit code 0 and then returns successfully — the caller
kills a live sibling MCP host and concludes it is alive. The login-lock sweep
runs that check against every lock file at startup, so a second MCP host
booting on Windows would kill the first host's in-flight login and then refuse
to log in itself ("login in progress in another terminal").

`_is_pid_alive` never signals the target on any platform.
"""

import ctypes
import logging
import os
import sys
from typing import Optional

logger = logging.getLogger(__name__)

# Windows constants (winnt.h / processthreadsapi.h / winerror.h).
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259  # GetExitCodeProcess reports this while the process runs
_ERROR_ACCESS_DENIED = 5

_kernel32: Optional[ctypes.CDLL] = None


def _get_kernel32() -> ctypes.CDLL:
    """Lazily bind kernel32 with the signatures we rely on.

    `restype` matters: the ctypes default is C `int` (32-bit), which truncates
    a 64-bit HANDLE and would make CloseHandle miss — leaking a handle per call.
    """
    global _kernel32
    if _kernel32 is None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        _kernel32 = kernel32
    return _kernel32


def _last_error() -> int:
    """Win32 GetLastError. Isolated so it can be exercised off-Windows."""
    return ctypes.get_last_error()  # type: ignore[attr-defined]  # win32-only


def _is_pid_alive(pid: int) -> bool:
    """Return True if `pid` refers to a running process. Never signals it.

    A pid we can see but not query (another user's process) counts as ALIVE:
    callers use this to decide whether a peer still holds a lock, and stealing
    a live peer's lock is worse than waiting out a dead one.
    """
    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
        return _is_pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except OSError as exc:
        logger.debug("PID liveness check failed for %s: %s", pid, exc)
        return False
    return True


def _is_pid_alive_windows(pid: int) -> bool:
    """Windows liveness via OpenProcess + GetExitCodeProcess (never TerminateProcess)."""
    try:
        kernel32 = _get_kernel32()
    except Exception as exc:  # noqa: BLE001 — ctypes/kernel32 unavailable
        logger.debug("kernel32 unavailable for PID liveness check: %s", exc)
        return True  # can't tell — assume alive rather than steal a peer's lock
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
    if not handle:
        # ERROR_ACCESS_DENIED: the process exists, it just isn't ours.
        # Anything else (typically ERROR_INVALID_PARAMETER) means it's gone.
        return _last_error() == _ERROR_ACCESS_DENIED
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True  # can't tell — assume alive
        return exit_code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)
