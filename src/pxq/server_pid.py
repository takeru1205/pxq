"""PID file management utilities for pxq server.

The PID file is stored at ``~/.pxq/server.pid`` and contains the process ID
of the running server instance.

This module provides functions to:
- Read/write the PID file
- Verify server identity by port ownership and process cmdline
- Clean up stale PID files
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional


def get_pid_path() -> Path:
    """Get the path to the PID file.

    Returns
    -------
    Path
        Path to ``~/.pxq/server.pid``.
    """
    return Path.home() / ".pxq" / "server.pid"


def read_pid() -> Optional[int]:
    """Read the PID from the PID file.

    Returns
    -------
    Optional[int]
        The PID if the file exists and contains a valid integer, None otherwise.
    """
    pid_path = get_pid_path()
    if not pid_path.exists():
        return None

    try:
        content = pid_path.read_text().strip()
        return int(content) if content else None
    except (ValueError, OSError):
        return None


def write_pid(pid: int) -> None:
    """Write a PID to the PID file.

    Creates the parent directory if it does not exist.

    Parameters
    ----------
    pid : int
        The process ID to write.
    """
    pid_path = get_pid_path()
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(pid))


def clear_pid() -> None:
    """Remove the PID file if it exists.

    This is a no-op if the file does not exist.
    """
    pid_path = get_pid_path()
    if pid_path.exists():
        pid_path.unlink()


def is_server_running() -> bool:
    """Check if a server process is currently running.

    This checks if the PID file exists and if the process with that PID is alive.

    Returns
    -------
    bool
        True if a server process is running, False otherwise.
    """
    pid = read_pid()
    if pid is None:
        return False

    try:
        # os.kill with signal 0 checks if the process exists without sending a signal
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        # Process does not exist
        return False
    except PermissionError:
        # Process exists but we don't have permission to send signals
        # This means the server is running (likely started by another user or root)
        return True
    except OSError:
        # Any other OS error (e.g., invalid PID)
        return False


def get_server_pid() -> Optional[int]:
    """Get the PID of the running server.

    Returns the PID only if the server is actually running.

    Returns
    -------
    Optional[int]
        The PID of the running server, or None if no server is running.
    """
    pid = read_pid()
    if pid is None:
        return None

    try:
        os.kill(pid, 0)
        return pid
    except (ProcessLookupError, PermissionError, OSError):
        return None


def _get_server_port() -> int:
    """Get the configured server port.

    Returns
    -------
    int
        The server port (default 8765).
    """
    try:
        from .config import Settings

        return Settings().server_port
    except Exception:
        # Fallback to default port if config not available
        return 8765


def _is_pxq_process(pid: int) -> bool:
    """Check if a process is a pxq server process.

    Verifies the process cmdline contains 'uvicorn pxq.server:app' or similar.

    Parameters
    ----------
    pid : int
        The process ID to check.

    Returns
    -------
    bool
        True if the process is a pxq server, False otherwise.
    """
    try:
        # Try macOS/BSD style first (ps -o command=)
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            cmdline = result.stdout.strip()
            # Check for pxq server identity markers
            return (
                "uvicorn pxq.server:app" in cmdline
                or "pxq.server:app" in cmdline
                or "pxq.server:create_app" in cmdline
                or "-m pxq server" in cmdline
            )

        # Fallback: try reading /proc/{pid}/cmdline (Linux)
        try:
            cmdline_path = Path(f"/proc/{pid}/cmdline")
            if cmdline_path.exists():
                cmdline = cmdline_path.read_text().replace("\x00", " ")
                return (
                    "uvicorn pxq.server:app" in cmdline
                    or "pxq.server:app" in cmdline
                    or "pxq.server:create_app" in cmdline
                    or "-m pxq server" in cmdline
                )
        except (OSError, IOError):
            pass

        return False
    except (subprocess.TimeoutExpired, OSError):
        return False


def _get_pid_listening_on_port(port: int) -> Optional[int]:
    import platform
    import re

    system = platform.system()

    if system == "Linux":
        try:
            result = subprocess.run(
                ["ss", "-tlnp", f"( sport = :{port})"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                match = re.search(r"pid=(\d+)", result.stdout)
                if match:
                    return int(match.group(1))
        except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
            pass

        try:
            result = subprocess.run(
                ["netstat", "-tlnp"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if f":{port}" in line:
                        parts = line.split()
                        if parts:
                            pid_match = re.search(r"(\d+)/", parts[-1] if parts else "")
                            if pid_match:
                                return int(pid_match.group(1))
        except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
            pass

    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            pid_str = result.stdout.strip().split("\n")[0]
            return int(pid_str)
        return None
    except (subprocess.TimeoutExpired, OSError, ValueError, FileNotFoundError):
        return None


def get_pxq_server_pid() -> Optional[int]:
    """Get the PID of the actual pxq server process.

    This function identifies the pxq server by:
    1. Finding the process listening on the server port
    2. Verifying the process is actually a pxq server via cmdline check

    This handles stale PID files correctly by ignoring the PID file
    and detecting the actual server process.

    Returns
    -------
    Optional[int]
        The PID of the running pxq server, or None if:
        - No process is listening on the server port
        - A non-pxq process is listening on the port (safety guard)
    """
    port = _get_server_port()

    # Find the process listening on the server port
    listener_pid = _get_pid_listening_on_port(port)
    if listener_pid is None:
        return None

    # Verify the process is actually a pxq server
    if _is_pxq_process(listener_pid):
        return listener_pid

    # Non-pxq process owns the port - return None as safety guard
    return None


def is_pxq_server_running() -> bool:
    """Check if the pxq server is currently running.

    This verifies the server identity by port ownership and cmdline check,
    not just by PID file existence.

    Returns
    -------
    bool
        True if the pxq server is running, False otherwise.
    """
    return get_pxq_server_pid() is not None


def cleanup_stale_pid() -> bool:
    """Clean up a stale PID file.

    Removes the PID file if it doesn't match the actual pxq server PID.
    This handles the case where the PID file contains a dead PID or
    a PID from a previous server instance.

    Returns
    -------
    bool
        True if a stale PID file was removed, False otherwise.
    """
    # Get the actual pxq server PID (may be None if not running)
    actual_pid = get_pxq_server_pid()

    # Read the PID file
    file_pid = read_pid()

    if file_pid is None:
        # No PID file to clean
        return False

    if actual_pid is not None and actual_pid == file_pid:
        # PID file matches actual server - not stale
        return False

    # PID file is stale (either no server running or different PID)
    # Remove the stale PID file
    clear_pid()
    return True
