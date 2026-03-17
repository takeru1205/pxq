"""Local command execution for pxq."""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path


class LocalProcessHandle:
    """Handle for a running local process with process group support."""

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self._proc = proc
        self._pid: int | None = proc.pid

    @property
    def pid(self) -> int | None:
        """Return the process group ID (same as main process PID after setsid)."""
        return self._pid

    @property
    def returncode(self) -> int | None:
        """Return the process exit code, or None if still running."""
        return self._proc.returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        """Wait for process to complete and return (stdout, stderr)."""
        return await self._proc.communicate()

    async def wait(self) -> int | None:
        """Wait for process to complete and return exit code."""
        await self._proc.wait()
        return self._proc.returncode


async def start_local_command(
    command: str,
    workdir: str | Path | None = None,
) -> LocalProcessHandle:
    """Start a local command in a new process group and return handle.

    Uses os.setsid() to create a new process group so all child processes
    can be terminated together via SIGTERM/SIGKILL to the group.

    Parameters
    ----------
    command : str
        Command to execute.
    workdir : str | Path | None
        Working directory for the command. Defaults to current directory.

    Returns
    -------
    LocalProcessHandle
        Handle to the running process with PID access.

    Notes
    -----
    This function only starts the process - it does NOT wait for completion.
    Use handle.communicate() or handle.wait() to wait for the process.
    """
    cwd = Path(workdir) if workdir else None

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            # Create new process group (POSIX only)
            preexec_fn=os.setsid,  # type: ignore[arg-type]
        )
    except OSError as e:
        raise RuntimeError(f"Failed to start process: {e}") from e

    return LocalProcessHandle(proc)


async def execute_local_command(
    command: str,
    workdir: str | Path | None = None,
    timeout_seconds: float = 3600.0,
) -> tuple[int, str, str]:
    """Execute a command locally and return (exit_code, stdout, stderr).

    Uses process group for proper child process cleanup.

    Parameters
    ----------
    command : str
        Command to execute.
    workdir : str | Path | None
        Working directory for the command. Defaults to current directory.
    timeout_seconds : float
        Maximum execution time before timeout.

    Returns
    -------
    tuple[int, str, str]
        (exit_code, stdout, stderr)
    """
    try:
        handle = await start_local_command(command, workdir)
    except RuntimeError as e:
        return (1, "", str(e))

    try:
        stdout, stderr = await asyncio.wait_for(
            handle.communicate(), timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        # Kill the entire process group
        if handle.pid is not None:
            stop_local_process(handle.pid, timeout=0)
        await handle.wait()
        return (-1, "", f"Command timed out after {timeout_seconds} seconds")

    exit_code = handle.returncode if handle.returncode is not None else -1
    return (exit_code, stdout.decode(errors="replace"), stderr.decode(errors="replace"))


def stop_local_process(pid: int, timeout: float = 5.0) -> bool:
    """Stop a local process group gracefully with SIGTERM, then SIGKILL if needed.

    Sends SIGTERM to the process group, waits up to `timeout` seconds,
    then sends SIGKILL if the process is still running.

    Parameters
    ----------
    pid : int
        Process group ID (typically the main process PID after setsid).
    timeout : float
        Seconds to wait after SIGTERM before sending SIGKILL. Default is 5.

    Returns
    -------
    bool
        True if process was stopped (either gracefully or forcefully),
        False if process was already dead or couldn't be signaled.

    Notes
    -----
    This function is synchronous and blocks for up to `timeout` seconds.
    Uses os.killpg() to send signals to the entire process group.
    """
    import time

    def is_process_alive(pid: int) -> bool:
        """Check if process group is still alive."""
        try:
            os.killpg(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    # Process already dead
    if not is_process_alive(pid):
        return False

    # Send SIGTERM to process group
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return False

    # Wait for graceful shutdown
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not is_process_alive(pid):
            return True
        time.sleep(0.1)

    # Force kill if still running
    try:
        os.killpg(pid, signal.SIGKILL)
        return True
    except (ProcessLookupError, PermissionError):
        return False
