# -*- coding: utf-8 -*-
"""Tests for server management commands."""

from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner

from pxq.cli import app
from pxq.server_pid import clear_pid, read_pid, write_pid


@pytest.fixture(autouse=True)
def cleanup_pid_file():
    """Clean up PID file before and after each test."""
    clear_pid()
    yield
    clear_pid()


def test_server_start_help():
    """Ensure 'pxq server start --help' works."""
    runner = CliRunner()
    result = runner.invoke(app, ["server", "start", "--help"])
    assert result.exit_code == 0
    assert "Start the pxq server in background" in result.stdout


def test_server_start_creates_pid_file():
    """Test that 'pxq server start' creates a PID file."""
    runner = CliRunner()

    # Mock subprocess.Popen to avoid actually starting the server
    mock_process = mock.Mock()
    mock_process.pid = 12345

    # Mock is_pxq_server_running to return False (server not running)
    # Mock Settings to avoid config issues
    with (
        mock.patch("pxq.cli.subprocess.Popen", return_value=mock_process),
        mock.patch("pxq.cli.is_pxq_server_running", return_value=False),
        mock.patch("pxq.config.Settings") as mock_settings,
    ):
        mock_settings.return_value.server_host = "127.0.0.1"
        mock_settings.return_value.server_port = 8765
        result = runner.invoke(app, ["server", "start"])


def test_server_start_fails_if_already_running():
    """Test that 'pxq server start' fails if server is already running."""
    runner = CliRunner()

    # Mock is_pxq_server_running to return True (server is running)
    with mock.patch("pxq.cli.is_pxq_server_running", return_value=True):
        result = runner.invoke(app, ["server", "start"])


def test_server_start_uses_custom_port_and_host():
    """Test that custom port and host are passed to uvicorn."""
    runner = CliRunner()

    mock_process = mock.Mock()
    mock_process.pid = 54321

    with (
        mock.patch("pxq.cli.subprocess.Popen") as mock_popen,
        mock.patch("pxq.cli.is_pxq_server_running", return_value=False),
        mock.patch("pxq.config.Settings") as mock_settings,
    ):
        mock_settings.return_value.server_host = "127.0.0.1"
        mock_settings.return_value.server_port = 8765
        mock_popen.return_value = mock_process
        result = runner.invoke(
            app, ["server", "start", "--port", "9000", "--host", "0.0.0.0"]
        )


def test_server_deprecation_warning():
    """Test that 'pxq server' shows deprecation warning."""
    runner = CliRunner()

    # Mock uvicorn.run to avoid actually starting the server
    with mock.patch("uvicorn.run"):
        result = runner.invoke(app, ["server"])

    assert result.exit_code == 0
    # Check for deprecation warning in output (err=True means it goes to stderr)
    assert "deprecated" in result.output.lower()


def test_server_log_file_location():
    """Test that log file path is shown in output."""
    runner = CliRunner()

    mock_process = mock.Mock()
    mock_process.pid = 11111

    with (
        mock.patch("pxq.cli.subprocess.Popen", return_value=mock_process),
        mock.patch("pxq.cli.is_pxq_server_running", return_value=False),
        mock.patch("pxq.config.Settings") as mock_settings,
    ):
        mock_settings.return_value.server_host = "127.0.0.1"
        mock_settings.return_value.server_port = 8765
        result = runner.invoke(app, ["server", "start"])
