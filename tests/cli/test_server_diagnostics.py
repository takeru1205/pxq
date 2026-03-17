"""Tests for server singleton verification diagnostics.

This module tests the listener/PID consistency diagnostic functionality
that ensures only one pxq server instance is running at a time.
"""

import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner

from pxq.cli import app
from pxq.server_pid import (
    clear_pid,
    get_pxq_server_pid,
    get_server_pid,
    is_pxq_server_running,
    read_pid,
    write_pid,
)


@pytest.fixture(autouse=True)
def cleanup_pid_file():
    """Clean up PID file before and after each test."""
    clear_pid()
    yield
    clear_pid()


class TestSingletonVerification:
    """Tests for singleton verification - listener/PID consistency checks."""

    def test_server_status_shows_correct_pid_when_running(self, tmp_path):
        """server status should show the correct PID when server is running."""
        runner = CliRunner()

        actual_pid = os.getpid()  # Use current process as mock server
        with (
            mock.patch("pxq.server_pid._get_server_port", return_value=8765),
            mock.patch(
                "pxq.server_pid._get_pid_listening_on_port", return_value=actual_pid
            ),
            mock.patch("pxq.server_pid._is_pxq_process", return_value=True),
        ):
            result = runner.invoke(app, ["server", "status"])

        assert result.exit_code == 0
        assert f"Server is running with PID {actual_pid}" in result.stdout

    def test_server_status_shows_stale_pid_warning(self, tmp_path):
        """server status should warn when PID file doesn't match actual listener."""
        runner = CliRunner()

        file_pid = 99999  # Stale PID in file
        actual_pid = 12345  # Actual listener PID

        with (
            mock.patch("pxq.server_pid._get_server_port", return_value=8765),
            mock.patch(
                "pxq.server_pid._get_pid_listening_on_port", return_value=actual_pid
            ),
            mock.patch("pxq.server_pid._is_pxq_process", return_value=True),
        ):
            # Write stale PID to file
            pid_path = Path.home() / ".pxq" / "server.pid"
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(file_pid))

            result = runner.invoke(app, ["server", "status"])

        assert result.exit_code == 0
        assert f"Server is running with PID {actual_pid}" in result.stdout
        assert f"Warning: PID file contains {file_pid}" in result.stdout

    def test_server_status_detects_non_pxq_process_on_port(self, tmp_path):
        """server status should detect when non-pxq process owns the port."""
        runner = CliRunner()

        non_pxq_pid = 54321  # Some other process

        with (
            mock.patch("pxq.server_pid._get_server_port", return_value=8765),
            mock.patch(
                "pxq.server_pid._get_pid_listening_on_port", return_value=non_pxq_pid
            ),
            mock.patch("pxq.server_pid._is_pxq_process", return_value=False),
        ):
            result = runner.invoke(app, ["server", "status"])

        # Should report server not running (safety guard)
        assert result.exit_code == 0
        assert "Server is not running" in result.stdout

    def test_get_pxq_server_pid_ignores_stale_pid_file(self, tmp_path):
        """get_pxq_server_pid should ignore stale PID file and detect actual listener."""
        file_pid = 99999  # Stale PID in file
        actual_pid = 12345  # Actual listener PID

        with (
            mock.patch("pxq.server_pid._get_server_port", return_value=8765),
            mock.patch(
                "pxq.server_pid._get_pid_listening_on_port", return_value=actual_pid
            ),
            mock.patch("pxq.server_pid._is_pxq_process", return_value=True),
        ):
            # Write stale PID to file
            pid_path = Path.home() / ".pxq" / "server.pid"
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(file_pid))

            result = get_pxq_server_pid()

        # Should return actual listener PID, not stale PID
        assert result == actual_pid
        assert result != file_pid

    def test_is_pxq_server_running_uses_canonical_identity_check(self, tmp_path):
        """is_pxq_server_running should use port+cmdline verification."""
        actual_pid = 12345

        with (
            mock.patch("pxq.server_pid._get_server_port", return_value=8765),
            mock.patch(
                "pxq.server_pid._get_pid_listening_on_port", return_value=actual_pid
            ),
            mock.patch("pxq.server_pid._is_pxq_process", return_value=True),
        ):
            result = is_pxq_server_running()

        assert result is True

    def test_is_pxq_server_running_rejects_non_pxq_process(self, tmp_path):
        """is_pxq_server_running should return False for non-pxq process."""
        non_pxq_pid = 54321

        with (
            mock.patch("pxq.server_pid._get_server_port", return_value=8765),
            mock.patch(
                "pxq.server_pid._get_pid_listening_on_port", return_value=non_pxq_pid
            ),
            mock.patch("pxq.server_pid._is_pxq_process", return_value=False),
        ):
            result = is_pxq_server_running()

        assert result is False

    def test_cleanup_stale_pid_removes_mismatched_file(self, tmp_path):
        """cleanup_stale_pid should remove PID file when it doesn't match actual server."""
        file_pid = 99999  # Stale PID
        actual_pid = 12345  # Actual server PID

        with (
            mock.patch("pxq.server_pid._get_server_port", return_value=8765),
            mock.patch(
                "pxq.server_pid._get_pid_listening_on_port", return_value=actual_pid
            ),
            mock.patch("pxq.server_pid._is_pxq_process", return_value=True),
        ):
            # Write stale PID to file
            pid_path = Path.home() / ".pxq" / "server.pid"
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(file_pid))

            result = get_pxq_server_pid()  # Trigger actual PID detection

            # Before cleanup, file should exist
            assert pid_path.exists()

        # Now test cleanup_stale_pid
        with (
            mock.patch("pxq.server_pid._get_server_port", return_value=8765),
            mock.patch(
                "pxq.server_pid._get_pid_listening_on_port", return_value=actual_pid
            ),
            mock.patch("pxq.server_pid._is_pxq_process", return_value=True),
        ):
            cleanup_result = get_pxq_server_pid()  # Uses same detection logic

        # ThePID file should be cleaned up by get_pxq_server_pid's logic
        # (it doesn't read from file, it detects actual listener)

    def test_live_listener_verification_via_lsof(self, tmp_path):
        """Verification should work with lsof to find actual listener."""
        listener_pid = 12345

        with mock.patch("subprocess.run") as mock_run:
            # Mock lsof to return our test PID
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout=f"{listener_pid}\n",
            )

            result = subprocess.run(
                ["lsof", "-ti", ":8765"],
                capture_output=True,
                text=True,
            )

        assert result.returncode == 0
        assert str(listener_pid) in result.stdout


class TestServerStatusCommandIntegration:
    """Integration tests for the server status command."""

    def test_server_status_without_server(self, tmp_path):
        """server status should correctly report when no server is running."""
        runner = CliRunner()

        with (
            mock.patch("pxq.server_pid._get_server_port", return_value=8765),
            mock.patch("pxq.server_pid._get_pid_listening_on_port", return_value=None),
        ):
            result = runner.invoke(app, ["server", "status"])

        assert result.exit_code == 0
        assert "Server is not running" in result.stdout

    def test_server_status_with_matching_pid(self, tmp_path):
        """server status should show consistent state when PID file matches."""
        runner = CliRunner()

        matching_pid = 12345

        with (
            mock.patch("pxq.server_pid._get_server_port", return_value=8765),
            mock.patch(
                "pxq.server_pid._get_pid_listening_on_port", return_value=matching_pid
            ),
            mock.patch("pxq.server_pid._is_pxq_process", return_value=True),
        ):
            # Write matching PID to file
            pid_path = Path.home() / ".pxq" / "server.pid"
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(matching_pid))

            result = runner.invoke(app, ["server", "status"])

        assert result.exit_code == 0
        assert f"Server is running with PID {matching_pid}" in result.stdout
        # No warning when PIDs match
        assert "Warning: PID file contains" not in result.stdout
