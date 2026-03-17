from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class SSHConnectionInfo:
    """RunPod SSH connection descriptor supporting both proxy and direct TCP modes."""

    method: str  # "proxy" or "direct_tcp"
    host: str
    port: Optional[int] = None
    username: str = "root"
    supports_file_transfer: bool = True

    def is_proxy(self) -> bool:
        """Check if this is a proxy SSH connection."""
        return self.method == "proxy"

    def is_direct_tcp(self) -> bool:
        """Check if this is a direct TCP SSH connection."""
        return self.method == "direct_tcp"


def build_ssh_base_args(
    identity_file: Optional[Path] = None,
) -> List[str]:
    """Build SSH base options list.

    Args:
        identity_file: Optional path to SSH private key file.

    Returns:
        List of SSH option arguments.
    """
    args: List[str] = [
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
    ]
    if identity_file is not None:
        args.extend(["-i", str(identity_file)])
    return args


def build_ssh_target(connection_info: SSHConnectionInfo) -> str:
    """Build user@host target string.

    Args:
        connection_info: SSH connection descriptor.

    Returns:
        Target string in format user@host.
    """
    return f"{connection_info.username}@{connection_info.host}"


def build_ssh_command(
    connection_info: SSHConnectionInfo,
    command: str,
    identity_file: Optional[Path] = None,
) -> List[str]:
    """Build complete SSH command list.

    Args:
        connection_info: SSH connection descriptor.
        command: Remote command to execute.
        identity_file: Optional path to SSH private key file.

    Returns:
        Complete SSH command as a list suitable for subprocess_exec.
    """
    args = ["ssh", *build_ssh_base_args(identity_file)]

    # Proxy mode: no -p flag (uses SSH proxy)
    # Direct TCP mode: include -p flag with port
    if connection_info.is_direct_tcp() and connection_info.port is not None:
        args.extend(["-p", str(connection_info.port)])

    args.extend([build_ssh_target(connection_info), command])
    return args


def build_interactive_ssh_args(
    connection_info: SSHConnectionInfo,
    identity_file: Optional[Path] = None,
) -> List[str]:
    """Build SSH command arguments for interactive PTY sessions.

    Use this when you need terminal behavior (e.g., running commands that
    expect a TTY, interactive shells, or programs that detect terminal type).

    Args:
        connection_info: SSH connection descriptor.
        identity_file: Optional path to SSH private key file.

    Returns:
        Complete SSH command list with -tt for PTY allocation.
    """
    args = ["ssh", *build_ssh_base_args(identity_file)]

    # Proxy mode: no -p flag (uses SSH proxy)
    # Direct TCP mode: include -p flag with port
    if connection_info.is_direct_tcp() and connection_info.port is not None:
        args.extend(["-p", str(connection_info.port)])

    # Add PTY allocation flag for interactive behavior
    args.extend(["-tt", build_ssh_target(connection_info)])
    return args


def build_non_interactive_ssh_args(
    connection_info: SSHConnectionInfo,
    identity_file: Optional[Path] = None,
) -> List[str]:
    """Build SSH command arguments for non-interactive script execution.

    Use this for file transfers, log collection, and other background
    operations that don't need terminal behavior.

    Args:
        connection_info: SSH connection descriptor.
        identity_file: Optional path to SSH private key file.

    Returns:
        Complete SSH command list without PTY allocation.
    """
    args = ["ssh", *build_ssh_base_args(identity_file)]

    # Proxy mode: no -p flag (uses SSH proxy)
    # Direct TCP mode: include -p flag with port
    if connection_info.is_direct_tcp() and connection_info.port is not None:
        args.extend(["-p", str(connection_info.port)])

    args.extend([build_ssh_target(connection_info)])
    return args
