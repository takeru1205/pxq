"""Tests for runpod_ssh shared SSH argument builders.

These tests verify the interactive vs non-interactive SSH helper functions
that centralize SSH command construction across runpod_exec.py and log_collector.py.
"""

from __future__ import annotations

from pathlib import Path

from pxq.providers.runpod_ssh import (
    SSHConnectionInfo,
    build_interactive_ssh_args,
    build_non_interactive_ssh_args,
)


class TestSSHConnectionInfo:
    """Tests for SSHConnectionInfo dataclass."""

    def test_proxy_method(self) -> None:
        """Test proxy SSH connection info."""
        conn = SSHConnectionInfo(method="proxy", host="proxy.example.com")
        assert conn.is_proxy()
        assert not conn.is_direct_tcp()
        assert conn.username == "root"
        assert conn.port is None

    def test_direct_tcp_method(self) -> None:
        """Test direct TCP SSH connection info."""
        conn = SSHConnectionInfo(method="direct_tcp", host="203.0.113.50", port=2222)
        assert not conn.is_proxy()
        assert conn.is_direct_tcp()
        assert conn.username == "root"
        assert conn.port == 2222

    def test_custom_username(self) -> None:
        """Test custom username."""
        conn = SSHConnectionInfo(
            method="direct_tcp", host="203.0.113.50", username="ubuntu"
        )
        assert conn.username == "ubuntu"


class TestBuildInteractiveSshArgs:
    """Tests for build_interactive_ssh_args with -tt PTY allocation."""

    def test_includes_tt_for_pty_allocation(self) -> None:
        """Verify interactive mode includes -tt for PTY allocation."""
        conn = SSHConnectionInfo(method="direct_tcp", host="203.0.113.50", port=2222)
        result = build_interactive_ssh_args(conn)

        assert "-tt" in result
        # -tt should come before the target
        tt_index = result.index("-tt")
        target_index = result.index("root@203.0.113.50")
        assert tt_index < target_index

    def test_direct_tcp_includes_port(self) -> None:
        """Verify direct TCP mode includes -p port."""
        conn = SSHConnectionInfo(method="direct_tcp", host="203.0.113.50", port=2222)
        result = build_interactive_ssh_args(conn)

        assert "-p" in result
        assert "2222" in result

    def test_proxy_mode_no_port_flag(self) -> None:
        """Verify proxy mode does not include -p flag."""
        conn = SSHConnectionInfo(method="proxy", host="proxy.example.com")
        result = build_interactive_ssh_args(conn)

        assert "-p" not in result

    def test_includes_base_ssh_options(self) -> None:
        """Verify standard SSH options are included."""
        conn = SSHConnectionInfo(method="direct_tcp", host="203.0.113.50", port=22)
        result = build_interactive_ssh_args(conn)

        assert "StrictHostKeyChecking=no" in result
        assert "UserKnownHostsFile=/dev/null" in result
        assert "BatchMode=yes" in result
        assert "ConnectTimeout=15" in result

    def test_starts_with_ssh_command(self) -> None:
        """Verify command starts with ssh."""
        conn = SSHConnectionInfo(method="direct_tcp", host="203.0.113.50", port=22)
        result = build_interactive_ssh_args(conn)

        assert result[0] == "ssh"

    def test_custom_username(self) -> None:
        """Verify custom username is used in target."""
        conn = SSHConnectionInfo(
            method="direct_tcp", host="203.0.113.50", port=22, username="ubuntu"
        )
        result = build_interactive_ssh_args(conn)

        assert "ubuntu@203.0.113.50" in result

    def test_with_identity_file(self) -> None:
        """Verify identity file is included when provided."""
        conn = SSHConnectionInfo(method="direct_tcp", host="203.0.113.50", port=22)
        identity = Path("/home/user/.ssh/id_rsa")
        result = build_interactive_ssh_args(conn, identity_file=identity)

        assert "-i" in result
        assert "/home/user/.ssh/id_rsa" in result


class TestBuildNonInteractiveSshArgs:
    """Tests for build_non_interactive_ssh_args without PTY allocation."""

    def test_no_tt_flag(self) -> None:
        """Verify non-interactive mode does not include -tt."""
        conn = SSHConnectionInfo(method="direct_tcp", host="203.0.113.50", port=2222)
        result = build_non_interactive_ssh_args(conn)

        assert "-tt" not in result

    def test_direct_tcp_includes_port(self) -> None:
        """Verify direct TCP mode includes -p port."""
        conn = SSHConnectionInfo(method="direct_tcp", host="203.0.113.50", port=2222)
        result = build_non_interactive_ssh_args(conn)

        assert "-p" in result
        assert "2222" in result

    def test_proxy_mode_no_port_flag(self) -> None:
        """Verify proxy mode does not include -p flag."""
        conn = SSHConnectionInfo(method="proxy", host="proxy.example.com")
        result = build_non_interactive_ssh_args(conn)

        assert "-p" not in result

    def test_includes_base_ssh_options(self) -> None:
        """Verify standard SSH options are included."""
        conn = SSHConnectionInfo(method="direct_tcp", host="203.0.113.50", port=22)
        result = build_non_interactive_ssh_args(conn)

        assert "StrictHostKeyChecking=no" in result
        assert "UserKnownHostsFile=/dev/null" in result
        assert "BatchMode=yes" in result
        assert "ConnectTimeout=15" in result

    def test_starts_with_ssh_command(self) -> None:
        """Verify command starts with ssh."""
        conn = SSHConnectionInfo(method="direct_tcp", host="203.0.113.50", port=22)
        result = build_non_interactive_ssh_args(conn)

        assert result[0] == "ssh"

    def test_custom_username(self) -> None:
        """Verify custom username is used in target."""
        conn = SSHConnectionInfo(
            method="direct_tcp", host="203.0.113.50", port=22, username="ubuntu"
        )
        result = build_non_interactive_ssh_args(conn)

        assert "ubuntu@203.0.113.50" in result

    def test_with_identity_file(self) -> None:
        """Verify identity file is included when provided."""
        conn = SSHConnectionInfo(method="direct_tcp", host="203.0.113.50", port=22)
        identity = Path("/home/user/.ssh/id_rsa")
        result = build_non_interactive_ssh_args(conn, identity_file=identity)

        assert "-i" in result
        assert "/home/user/.ssh/id_rsa" in result


class TestInteractiveVsNonInteractiveParity:
    """Tests comparing interactive and non-interactive modes."""

    def test_both_modes_share_base_options(self) -> None:
        """Verify both modes use the same base SSH options."""
        conn = SSHConnectionInfo(method="direct_tcp", host="203.0.113.50", port=2222)
        interactive = build_interactive_ssh_args(conn)
        non_interactive = build_non_interactive_ssh_args(conn)

        # Both should have these options
        for option in [
            "StrictHostKeyChecking=no",
            "UserKnownHostsFile=/dev/null",
            "BatchMode=yes",
            "ConnectTimeout=15",
            "-p",
            "2222",
            "root@203.0.113.50",
        ]:
            assert option in interactive, f"{option} missing from interactive"
            assert option in non_interactive, f"{option} missing from non-interactive"

    def test_only_interactive_has_tt(self) -> None:
        """Verify only interactive mode has -tt flag."""
        conn = SSHConnectionInfo(method="direct_tcp", host="203.0.113.50", port=2222)
        interactive = build_interactive_ssh_args(conn)
        non_interactive = build_non_interactive_ssh_args(conn)

        assert "-tt" in interactive
        assert "-tt" not in non_interactive

    def test_target_position_differs(self) -> None:
        """Verify target position differs between modes.

        Interactive: [..., "-tt", "user@host"]
        Non-interactive: [..., "user@host"]
        """
        conn = SSHConnectionInfo(method="direct_tcp", host="203.0.113.50", port=2222)
        interactive = build_interactive_ssh_args(conn)
        non_interactive = build_non_interactive_ssh_args(conn)

        target = "root@203.0.113.50"
        interactive_target_idx = interactive.index(target)
        non_interactive_target_idx = non_interactive.index(target)

        # Interactive should have -tt before target
        assert interactive[interactive_target_idx - 1] == "-tt"
        # Non-interactive should have port number before target (from -p flag)
        assert non_interactive[non_interactive_target_idx - 1] == "2222"
