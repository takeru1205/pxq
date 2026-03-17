"""Tests for PID file management utilities."""

import os
from pathlib import Path
from unittest import mock

import pytest

from pxq.server_pid import (
    clear_pid,
    cleanup_stale_pid,
    get_pid_path,
    get_pxq_server_pid,
    get_server_pid,
    is_pxq_server_running,
    is_server_running,
    read_pid,
    write_pid,
)


class TestGetPidPath:
    """Tests for get_pid_path function."""

    def test_returns_correct_path(self):
        """get_pid_path should return ~/.pxq/server.pid."""
        path = get_pid_path()
        expected = Path.home() / ".pxq" / "server.pid"
        assert path == expected


class TestReadPid:
    """Tests for read_pid function."""

    def test_returns_none_when_file_does_not_exist(self, tmp_path):
        """read_pid should return None if PID file does not exist."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            result = read_pid()
            assert result is None

    def test_returns_pid_when_file_exists(self, tmp_path):
        """read_pid should return the PID from the file."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            pid_path = get_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text("12345")

            result = read_pid()
            assert result == 12345

    def test_returns_none_for_empty_file(self, tmp_path):
        """read_pid should return None for an empty file."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            pid_path = get_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text("")

            result = read_pid()
            assert result is None

    def test_returns_none_for_invalid_content(self, tmp_path):
        """read_pid should return None for non-integer content."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            pid_path = get_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text("not-a-pid")

            result = read_pid()
            assert result is None

    def test_handles_whitespace(self, tmp_path):
        """read_pid should handle leading/trailing whitespace."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            pid_path = get_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text("  12345  \n")

            result = read_pid()
            assert result == 12345


class TestWritePid:
    """Tests for write_pid function."""

    def test_creates_directory_if_not_exists(self, tmp_path):
        """write_pid should create parent directories."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            pid_path = get_pid_path()
            assert not pid_path.parent.exists()

            write_pid(12345)

            assert pid_path.parent.exists()
            assert pid_path.exists()
            assert pid_path.read_text() == "12345"

    def test_overwrites_existing_file(self, tmp_path):
        """write_pid should overwrite existing PID file."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            pid_path = get_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text("11111")

            write_pid(22222)

            assert pid_path.read_text() == "22222"


class TestClearPid:
    """Tests for clear_pid function."""

    def test_removes_existing_file(self, tmp_path):
        """clear_pid should remove the PID file."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            pid_path = get_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text("12345")

            clear_pid()

            assert not pid_path.exists()

    def test_is_noop_when_file_does_not_exist(self, tmp_path):
        """clear_pid should not raise if file does not exist."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            # Should not raise
            clear_pid()


class TestIsServerRunning:
    """Tests for is_server_running function."""

    def test_returns_false_when_no_pid_file(self, tmp_path):
        """is_server_running should return False when no PID file exists."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            assert is_server_running() is False

    def test_returns_false_when_process_not_running(self, tmp_path):
        """is_server_running should return False when process does not exist."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            # Write a PID that is very unlikely to exist
            pid_path = get_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text("999999998")

            result = is_server_running()
            assert result is False

    def test_returns_true_when_process_running(self, tmp_path):
        """is_server_running should return True when process exists."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            # Use current process PID
            current_pid = os.getpid()
            pid_path = get_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(current_pid))

            result = is_server_running()
            assert result is True

    def test_returns_true_on_permission_error(self, tmp_path):
        """is_server_running should return True on PermissionError.

        PermissionError indicates the process exists but we can't send signals.
        """
        with mock.patch.object(Path, "home", return_value=tmp_path):
            pid_path = get_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text("12345")

            with mock.patch("os.kill", side_effect=PermissionError()):
                result = is_server_running()
                assert result is True


class TestGetServerPid:
    """Tests for get_server_pid function."""

    def test_returns_none_when_no_pid_file(self, tmp_path):
        """get_server_pid should return None when no PID file exists."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            assert get_server_pid() is None

    def test_returns_none_when_process_not_running(self, tmp_path):
        """get_server_pid should return None when process does not exist."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            pid_path = get_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text("999999998")

            result = get_server_pid()
            assert result is None

    def test_returns_pid_when_process_running(self, tmp_path):
        """get_server_pid should return PID when process exists."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            current_pid = os.getpid()
            pid_path = get_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(current_pid))

            result = get_server_pid()
            assert result == current_pid


class TestGetPxqServerPid:
    """Tests for get_pxq_server_pid function."""

    def test_returns_none_when_no_process_on_port(self, tmp_path):
        """get_pxq_server_pid should return None when no process on port."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            # Mock _get_server_port to return a port that's not in use
            with mock.patch("pxq.server_pid._get_server_port", return_value=59999):
                # Mock _get_pid_listening_on_port to return None
                with mock.patch(
                    "pxq.server_pid._get_pid_listening_on_port", return_value=None
                ):
                    result = get_pxq_server_pid()
                    assert result is None

    def test_returns_pid_when_pxq_server_on_port(self, tmp_path):
        """get_pxq_server_pid should return PID when pxq server is on port."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            test_pid = 12345
            with mock.patch("pxq.server_pid._get_server_port", return_value=8765):
                with mock.patch(
                    "pxq.server_pid._get_pid_listening_on_port",
                    return_value=test_pid,
                ):
                    with mock.patch(
                        "pxq.server_pid._is_pxq_process", return_value=True
                    ):
                        result = get_pxq_server_pid()
                        assert result == test_pid

    def test_returns_none_when_non_pxq_process_on_port(self, tmp_path):
        """get_pxq_server_pid should return None for non-pxq process (safety guard)."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            test_pid = 54321
            with mock.patch("pxq.server_pid._get_server_port", return_value=8765):
                with mock.patch(
                    "pxq.server_pid._get_pid_listening_on_port",
                    return_value=test_pid,
                ):
                    # Non-pxq process - should return None
                    with mock.patch(
                        "pxq.server_pid._is_pxq_process", return_value=False
                    ):
                        result = get_pxq_server_pid()
                        assert result is None

    def test_ignores_stale_pid_file(self, tmp_path):
        """get_pxq_server_pid should ignore stale PID file."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            # Write a stale PID to the file
            pid_path = get_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text("99999")

            actual_pid = 11111
            with mock.patch("pxq.server_pid._get_server_port", return_value=8765):
                with mock.patch(
                    "pxq.server_pid._get_pid_listening_on_port",
                    return_value=actual_pid,
                ):
                    with mock.patch(
                        "pxq.server_pid._is_pxq_process", return_value=True
                    ):
                        # Should return actual PID, not stale PID from file
                        result = get_pxq_server_pid()
                        assert result == actual_pid
                        assert result != 99999


class TestIsPxqServerRunning:
    """Tests for is_pxq_server_running function."""

    def test_returns_true_when_pxq_server_running(self, tmp_path):
        """is_pxq_server_running should return True when pxq server is running."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            with mock.patch("pxq.server_pid._get_server_port", return_value=8765):
                with mock.patch(
                    "pxq.server_pid._get_pid_listening_on_port", return_value=12345
                ):
                    with mock.patch(
                        "pxq.server_pid._is_pxq_process", return_value=True
                    ):
                        result = is_pxq_server_running()
                        assert result is True

    def test_returns_false_when_no_server_running(self, tmp_path):
        """is_pxq_server_running should return False when no server running."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            with mock.patch("pxq.server_pid._get_server_port", return_value=8765):
                with mock.patch(
                    "pxq.server_pid._get_pid_listening_on_port", return_value=None
                ):
                    result = is_pxq_server_running()
                    assert result is False

    def test_returns_false_when_non_pxq_process_on_port(self, tmp_path):
        """is_pxq_server_running should return False for non-pxq process."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            with mock.patch("pxq.server_pid._get_server_port", return_value=8765):
                with mock.patch(
                    "pxq.server_pid._get_pid_listening_on_port", return_value=54321
                ):
                    with mock.patch(
                        "pxq.server_pid._is_pxq_process", return_value=False
                    ):
                        result = is_pxq_server_running()
                        assert result is False


class TestCleanupStalePid:
    """Tests for cleanup_stale_pid function."""

    def test_returns_false_when_no_pid_file(self, tmp_path):
        """cleanup_stale_pid should return False when no PID file exists."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            with mock.patch("pxq.server_pid._get_server_port", return_value=8765):
                with mock.patch(
                    "pxq.server_pid._get_pid_listening_on_port", return_value=None
                ):
                    result = cleanup_stale_pid()
                    assert result is False

    def test_returns_false_when_pid_matches_actual_server(self, tmp_path):
        """cleanup_stale_pid should return False when PID file matches actual server."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            actual_pid = 12345
            pid_path = get_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(actual_pid))

            with mock.patch("pxq.server_pid._get_server_port", return_value=8765):
                with mock.patch(
                    "pxq.server_pid._get_pid_listening_on_port",
                    return_value=actual_pid,
                ):
                    with mock.patch(
                        "pxq.server_pid._is_pxq_process", return_value=True
                    ):
                        result = cleanup_stale_pid()
                        assert result is False
                        # PID file should still exist
                        assert pid_path.exists()

    def test_removes_stale_pid_file_when_server_not_running(self, tmp_path):
        """cleanup_stale_pid should remove stale PID when server not running."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            stale_pid = 99999
            pid_path = get_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(stale_pid))

            with mock.patch("pxq.server_pid._get_server_port", return_value=8765):
                with mock.patch(
                    "pxq.server_pid._get_pid_listening_on_port", return_value=None
                ):
                    result = cleanup_stale_pid()
                    assert result is True
                    # PID file should be removed
                    assert not pid_path.exists()

    def test_removes_stale_pid_file_when_different_server(self, tmp_path):
        """cleanup_stale_pid should remove stale PID when different server running."""
        with mock.patch.object(Path, "home", return_value=tmp_path):
            stale_pid = 99999
            actual_pid = 11111
            pid_path = get_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(stale_pid))

            with mock.patch("pxq.server_pid._get_server_port", return_value=8765):
                with mock.patch(
                    "pxq.server_pid._get_pid_listening_on_port",
                    return_value=actual_pid,
                ):
                    with mock.patch(
                        "pxq.server_pid._is_pxq_process", return_value=True
                    ):
                        result = cleanup_stale_pid()
                        assert result is True
                        # PID file should be removed
                        assert not pid_path.exists()


class TestIsPxqProcess:
    """Tests for _is_pxq_process helper function."""

    def test_detects_uvicorn_pxq_server(self):
        """_is_pxq_process should detect uvicorn pxq.server:app."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout="python -m uvicorn pxq.server:app --host 127.0.0.1 --port 8765",
            )
            from pxq.server_pid import _is_pxq_process

            result = _is_pxq_process(12345)
            assert result is True

    def test_detects_foreground_pxq_server(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout="/Users/take/pxq/.venv/bin/python -m pxq server",
            )
            from pxq.server_pid import _is_pxq_process

            result = _is_pxq_process(12345)
            assert result is True

    def test_detects_foreground_pxq_server_with_args(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout="python -m pxq server --port 8765 --host 127.0.0.1",
            )
            from pxq.server_pid import _is_pxq_process

            result = _is_pxq_process(12345)
            assert result is True

    def test_rejects_non_pxq_process(self):
        """_is_pxq_process should reject non-pxq process."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout="python some_other_script.py"
            )
            from pxq.server_pid import _is_pxq_process

            result = _is_pxq_process(12345)
            assert result is False

    def test_handles_subprocess_timeout(self):
        """_is_pxq_process should handle subprocess timeout."""
        import subprocess

        with mock.patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="ps", timeout=5)
            from pxq.server_pid import _is_pxq_process

            result = _is_pxq_process(12345)
            assert result is False


class TestGetPidListeningOnPort:
    """Tests for _get_pid_listening_on_port helper function."""

    def test_returns_pid_from_lsof(self):
        """_get_pid_listening_on_port should return PID from lsof."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="12345\n")
            from pxq.server_pid import _get_pid_listening_on_port

            result = _get_pid_listening_on_port(8765)
            assert result == 12345

    def test_returns_none_when_no_listener(self):
        """_get_pid_listening_on_port should return None when no listener."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stdout="")
            from pxq.server_pid import _get_pid_listening_on_port

            result = _get_pid_listening_on_port(59999)
            assert result is None

    def test_returns_none_on_error(self):
        """_get_pid_listening_on_port should return None on error."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("lsof not found")
            from pxq.server_pid import _get_pid_listening_on_port

            result = _get_pid_listening_on_port(8765)
            assert result is None
